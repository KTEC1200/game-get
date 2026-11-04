#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`_unity_extract.py` 的两条硬规矩（2026-11-04）：

1. **子进程诊断不许吞**：AssetStudio 起不来（缺 DLL / 被安全软件拦）和「这个游戏
   真没有这类资产」在计数上都是 0。rc + stderr 是唯一能区分它们的证据。
2. **合并断点续跑产物时不许拍平路径**：旧实现用 `relative_to(src).name` 拍平，
   AssetStudio 一旦按子目录输出，不同目录下的同名文件就互相顶掉，而且
   `if not tgt.exists(): skip` 让丢失完全无声。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _unity_extract as ue  # noqa: E402


def _proc(rc: int = 0, out: bytes = b"", err: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, out, err)


# ---------------------------------------------------------------------------
# 1. rc / env 透出
# ---------------------------------------------------------------------------

def test_run_as_passes_sanitized_env(tmp_path, monkeypatch):
    """★核心★ 子进程必须拿 toolbridge 的干净环境（冻结包 PATH 里混着 _MEI）。"""
    captured: dict = {}
    monkeypatch.setenv("PYTHONHOME", r"C:\bundle\_MEI123")

    def fake_run(cmd, **kw):
        captured.update(kw)
        return _proc()

    monkeypatch.setattr(ue.subprocess, "run", fake_run)
    ue._run_as(tmp_path, tmp_path, "AudioClip", "JSON", as_exe=Path("as.exe"))

    assert "PYTHONHOME" not in captured["env"], "PYTHONHOME 没被洗掉"
    assert captured["env"]["PATH"].find("_MEI") == -1


def test_run_as_turns_missing_exe_into_diagnostic(tmp_path):
    """工具根本起不来时不许抛裸异常：返回 rc=-2 + 原因，交给上层报。"""
    proc = ue._run_as(tmp_path, tmp_path / "t", "AudioClip", "JSON",
                      as_exe=Path(r"Z:\no\such\AssetStudio.CLI.exe"))

    assert proc.returncode == -2
    assert b"Error" in proc.stderr


def test_expected_counts_reports_rc_and_stderr(tmp_path, monkeypatch):
    """rc≠0 时必须留下 errors（含 rc 与 stderr 尾部），不能只给一个计数。"""
    def fake_run(data_dir, tmp, type_name, export_type, as_exe=None):
        (tmp / f"{type_name}.json").write_text(json.dumps({"m_Name": type_name}),
                                               encoding="utf-8")
        return _proc(rc=3, err=b"Failed to load assembly")

    monkeypatch.setattr(ue, "_run_as", fake_run)

    exp = ue.expected_counts(tmp_path, as_exe=Path("as.exe"), tmp_root=tmp_path / "w")

    assert exp["total"] == 3, "计数仍要照数（rc 不是成功判据）"
    assert len(exp["errors"]) == 3
    assert "rc=3" in exp["errors"][0] and "Failed to load assembly" in exp["errors"][0]


def test_extract_all_reports_convert_rc(tmp_path, monkeypatch):
    def fake_run(data_dir, tmp, type_name, export_type, as_exe=None):
        (tmp / type_name).mkdir(parents=True, exist_ok=True)
        (tmp / type_name / "a.png").write_bytes(b"A")
        return _proc(rc=1, err=b"access violation")

    monkeypatch.setattr(ue, "_run_as", fake_run)

    got = ue.extract_all(tmp_path, tmp_path / "raw", as_exe=Path("as.exe"),
                         tmp_root=tmp_path / "w")

    assert len(got["errors"]) == 3
    assert "access violation" in got["errors"][0]


# ---------------------------------------------------------------------------
# 2. 合并保留相对路径（断点续跑）
# ---------------------------------------------------------------------------

def _fake_convert(payload: dict[str, bytes]):
    """造一个「按子目录输出」的 AssetStudio：{相对路径: 内容}。"""
    def fake_run(data_dir, tmp, type_name, export_type, as_exe=None):
        if export_type == "Convert":
            for rel, data in payload.items():
                p = tmp / type_name / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
        return _proc()
    return fake_run


def test_merge_keeps_relative_paths(tmp_path, monkeypatch):
    """★核心★ 子目录结构必须保留：拍平会让不同目录的同名文件互相顶掉。"""
    out = tmp_path / "raw"
    (out / "Image_Texture2D").mkdir(parents=True)      # 目标已存在 → 走合并分支
    monkeypatch.setattr(ue, "_run_as",
                        _fake_convert({"sub/a.png": b"A", "b.png": b"B"}))

    ue.extract_all(tmp_path, out, as_exe=Path("as.exe"), tmp_root=tmp_path / "w")

    assert (out / "Image_Texture2D" / "sub" / "a.png").is_file(), "子目录被拍平了"
    assert (out / "Image_Texture2D" / "b.png").is_file()


def test_merge_skips_identical_duplicate(tmp_path, monkeypatch):
    out = tmp_path / "raw"
    (out / "Image_Texture2D").mkdir(parents=True)
    (out / "Image_Texture2D" / "a.png").write_bytes(b"A")      # 同内容 = 重复导出
    monkeypatch.setattr(ue, "_run_as", _fake_convert({"a.png": b"A"}))

    ue.extract_all(tmp_path, out, as_exe=Path("as.exe"), tmp_root=tmp_path / "w")

    assert (out / "Image_Texture2D" / "a.png").read_bytes() == b"A"


def test_merge_refuses_conflicting_same_name(tmp_path, monkeypatch):
    """同路径不同内容 = 真冲突，必须报错——静默跳过就是静默丢文件。"""
    out = tmp_path / "raw"
    (out / "Image_Texture2D").mkdir(parents=True)
    (out / "Image_Texture2D" / "a.png").write_bytes(b"OLD")
    monkeypatch.setattr(ue, "_run_as", _fake_convert({"a.png": b"NEW"}))

    with pytest.raises(ValueError, match="同名不同内容"):
        ue.extract_all(tmp_path, out, as_exe=Path("as.exe"), tmp_root=tmp_path / "w")
