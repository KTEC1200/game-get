#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifest.py 的测试 —— 契约唯一实现的护栏。

为什么这些测试重要：manifest 是**交付清单**。`orchestrator.py` 和
`krkr_auto_extract.py` 都靠它说「交付了多少东西」。契约一旦漂移，
两个工具就会对同一份产物给出不同答案，而用户只看得到 manifest。

三条最关键的规矩（都来自真实踩坑）：
  1. `final` 一律实际扫盘，**不做减法** —— 减法在转换失败/同名覆盖时算错。
  2. `reconcile(expected=None)` 必须 `diff=None` + `method="no-index-available"`
     —— **不许把「没验」伪装成「验过了」**。
  3. 标签一律 `as_posix()` —— Windows 反斜杠混进 manifest 会让跨机器比对失败。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import manifest as mf  # noqa: E402


def _write(p: Path, data: bytes = b"x" * 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _png(p: Path) -> Path:
    return _write(p, b"\x89PNG\r\n\x1a\n" + b"x" * 16)


# ---------------------------------------------------------------------------
# 规矩 1：final 是扫出来的，不是算出来的
# ---------------------------------------------------------------------------


def test_final_excludes_convertible_and_includes_png_dir(tmp_path):
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.ogg")
    _write(raw / "b.png")
    _write(raw / "c.tlg")            # 中间格式，final 里不该出现
    _png(png / "c.png")              # 转换成品，final 里要出现

    c = mf.counts(raw, png)

    assert c["raw"]["total"] == 3
    assert c["final"]["total"] == 3          # a.ogg + b.png + png/c.png
    assert ".tlg" not in c["final"]["by_ext"]
    assert c["final"]["by_ext"][".png"] == 2  # raw 的 b.png + 转换的 c.png
    assert c["converted"] == {".tlg": 1}


def test_final_counts_real_files_not_subtraction(tmp_path):
    """★核心★ 转换失败（png/ 里没有对应成品）时，final 必须反映真实情况。

    如果用「raw.total - converted + png.total」这种减法，这里会算出
    final = 2（错，实际只有 a.ogg 一个成品），掩盖「tlg 没转出来」。
    """
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.ogg")
    _write(raw / "c.tlg")            # 有 tlg
    png.mkdir()                       # 但 png/ 是空的 —— 转换失败/没跑

    c = mf.counts(raw, png)

    assert c["raw"]["total"] == 2
    assert c["final"]["total"] == 1, "tlg 没转出来就不该被算成交付成品"
    assert c["final"]["by_ext"] == {".ogg": 1}
    assert c["converted"] == {".tlg": 1}


def test_final_survives_extra_png_without_raw_counterpart(tmp_path):
    """png/ 里有 raw 里没有对应 tlg 的 png（手工补的/上次残留）→ 照收。

    这也是「不许减法」的理由：减法会把这类文件丢掉。
    """
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.ogg")
    _png(png / "manual.png")

    c = mf.counts(raw, png)

    assert c["final"]["total"] == 2
    assert c["final"]["by_ext"][".png"] == 1


def test_counts_missing_dirs_are_zero_not_error(tmp_path):
    """目录还不存在（解包前）→ 全 0，不许抛异常。"""
    c = mf.counts(tmp_path / "nope", tmp_path / "also-nope")
    assert c["raw"]["total"] == 0
    assert c["final"]["total"] == 0
    assert c["converted"] == {}


def test_counts_bytes_are_summed(tmp_path):
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.ogg", b"x" * 100)
    _write(raw / "b.ogg", b"x" * 50)
    c = mf.counts(raw, png)
    assert c["raw"]["bytes"] == 150
    assert c["final"]["bytes"] == 150


def test_convertible_is_overridable(tmp_path):
    """将来接 E-mote（.pimg）时，调用方可以传自己的 convertible 集合。"""
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.pimg")
    _write(raw / "b.ogg")

    c = mf.counts(raw, png, {".pimg"})

    assert c["final"]["total"] == 1
    assert c["converted"] == {".pimg": 1}


# ---------------------------------------------------------------------------
# 规矩 2：没验 ≠ 验过了
# ---------------------------------------------------------------------------


def test_reconcile_with_expected_reports_diff():
    r = mf.reconcile(100, 98)
    assert r == {"expected": 100, "actual": 98, "diff": -2, "method": "archive-index"}


def test_reconcile_exact_match_is_zero():
    r = mf.reconcile(2562, 2562)
    assert r["diff"] == 0
    assert r["method"] == "archive-index"


def test_reconcile_none_expected_is_explicitly_unverified():
    """★核心★ 没有地面真相时，必须明说「没对账」，不许 diff=0 蒙混。"""
    r = mf.reconcile(None, 42)
    assert r["expected"] is None
    assert r["diff"] is None, "没验过就不许给出 0"
    assert r["method"] == "no-index-available"
    assert r["actual"] == 42


# ---------------------------------------------------------------------------
# 规矩 3：标签一律正斜杠（跨机器可比）
# ---------------------------------------------------------------------------


def test_final_labels_use_forward_slashes(tmp_path):
    """★回归护栏★ Windows 嵌套路径必须出 `raw/sub/c.ogg`，不能出 `raw\\sub\\c.ogg`。"""
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "sub" / "deep" / "c.ogg")
    _png(png / "sub" / "c.png")

    files = mf.iter_final_files(raw, png)
    labels = [label for _p, label in files]

    assert "raw/sub/deep/c.ogg" in labels
    assert "png/sub/c.png" in labels
    for label in labels:
        assert "\\" not in label, f"标签里不许出现反斜杠：{label}"


def test_iter_final_files_ignores_directories(tmp_path):
    raw, png = tmp_path / "raw", tmp_path / "png"
    (raw / "emptydir").mkdir(parents=True)
    _write(raw / "a.ogg")
    labels = [lbl for _p, lbl in mf.iter_final_files(raw, png)]
    assert labels == ["raw/a.ogg"]


def test_iter_final_files_paths_are_absolute(tmp_path):
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.ogg")
    for p, _label in mf.iter_final_files(raw, png):
        assert p.is_absolute()
        assert p.is_file()


# ---------------------------------------------------------------------------
# build / write / read
# ---------------------------------------------------------------------------


def _blocks(tmp_path):
    raw, png = tmp_path / "raw", tmp_path / "png"
    _write(raw / "a.ogg")
    _write(raw / "c.tlg")
    _png(png / "c.png")
    return raw, png


def test_build_has_all_contract_keys(tmp_path):
    raw, png = _blocks(tmp_path)
    man = mf.build(
        tool="test", engine="KiriKiri",
        source={"game_dir": str(tmp_path), "archives": []},
        counts_block=mf.counts(raw, png),
        reconcile_block=mf.reconcile(2, 2),
        verify={"verified": True}, postprocess=[],
    )
    for key in ("manifest_version", "tool", "engine", "source", "counts",
                "postprocess", "verify", "reconcile", "png_dir", "stages",
                "generated_at"):
        assert key in man, f"契约缺字段：{key}"
    assert man["manifest_version"] == mf.MANIFEST_VERSION


def test_build_extra_can_extend_but_not_clobber_contract(tmp_path):
    raw, png = _blocks(tmp_path)
    man = mf.build(
        tool="t", engine=None, source={}, counts_block=mf.counts(raw, png),
        reconcile_block=mf.reconcile(None, 2), verify={}, postprocess=[],
        extra={"custom": 1},
    )
    assert man["custom"] == 1
    assert man["counts"]["raw"]["total"] == 2


def test_write_read_roundtrip_keeps_cjk(tmp_path):
    """中日文路径必须原样可读（ensure_ascii=False），否则人工核对时全是转义。"""
    raw = tmp_path / "raw"
    _write(raw / "高慢妻" / "画像.tlg")
    man = mf.build(tool="t", engine="KiriKiri", source={"game_dir": "D:\\HY\\高慢妻陥落！！"},
                   counts_block=mf.counts(raw, tmp_path / "png"),
                   reconcile_block=mf.reconcile(1, 1), verify={}, postprocess=[])
    out = mf.write(tmp_path / "out" / "manifest.json", man)

    text = out.read_text(encoding="utf-8")
    assert "高慢妻陥落" in text, "CJK 不许被转成 \\uXXXX"
    assert "\\u9ad8" not in text, "出现了转义形式说明 ensure_ascii 没关掉"

    back = mf.read(out)
    assert back["engine"] == "KiriKiri"
    assert back["source"]["game_dir"] == "D:\\HY\\高慢妻陥落！！"
    assert back["counts"]["raw"]["by_ext"] == {".tlg": 1}


def test_write_creates_parent_dirs(tmp_path):
    out = mf.write(tmp_path / "a" / "b" / "manifest.json", {"x": 1})
    assert out.is_file()


def test_manifest_is_json_serialisable(tmp_path):
    raw, png = _blocks(tmp_path)
    man = mf.build(tool="t", engine="Ren'Py", source={},
                   counts_block=mf.counts(raw, png),
                   reconcile_block=mf.reconcile(2, 2), verify={}, postprocess=[])
    json.dumps(man, ensure_ascii=False)   # 不抛就是过


# ---------------------------------------------------------------------------
# CLI 自检
# ---------------------------------------------------------------------------


def test_cli_prints_summary(tmp_path):
    raw, png = _blocks(tmp_path)
    man = mf.build(tool="t", engine="KiriKiri", source={},
                   counts_block=mf.counts(raw, png),
                   reconcile_block=mf.reconcile(2, 2), verify={}, postprocess=[])
    mf.write(tmp_path / "manifest.json", man)

    # 子进程要显式指定 UTF-8：本机控制台是 GBK，摘要里有中文，
    # 不指定的话 stdout 解不出来（实测 UnicodeDecodeError）。
    r = subprocess.run([sys.executable, str(Path(mf.__file__)), str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert r.returncode == 0, r.stderr
    assert "KiriKiri" in r.stdout
    assert "converted" in r.stdout


def test_cli_without_args_exits_2():
    r = subprocess.run([sys.executable, str(Path(mf.__file__))],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 2
