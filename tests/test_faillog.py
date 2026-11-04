#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""失败日志（`faillog.py`）的测试。

这模块的验收不是「能写文件」——那是顺手的事。真正要锁的是三条：
  ① 写的 **位置** 对（软件根目录，而不是跟着产物走的 `_work/`）；
  ② 内容 **够定位**（时间、error、引擎、游戏/输出路径、失败阶段、rc）；
  ③ **永不抛**（两处都写不了也只往 stderr 说一句）——失败日志写不进去
     绝不能变成一个新的失败。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import faillog  # noqa: E402


def test_writes_block_with_time_error_and_context(tmp_path):
    """★核心★ 一条失败要能独立看懂：什么时候、哪个游戏、哪一步、为什么。"""
    p = faillog.log_failure(
        error="extract-failed", engine="KiriKiri",
        game_dir=r"D:\HY\高慢妻陥落！！", out_dir=r"D:\out\高慢妻", rc=1,
        stages=[{"stage": "extract", "ok": False, "detail": "GARbro 列不出目录"},
                {"stage": "detect", "ok": True, "detail": "KiriKiri (score=90)"}],
        root=tmp_path)

    assert p == tmp_path / "failures.log"
    text = p.read_text(encoding="utf-8")
    assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}\]", text), "缺时间戳"
    assert "extract-failed" in text and "engine=KiriKiri" in text and "rc=1" in text
    assert r"D:\HY\高慢妻陥落！！" in text
    assert "extract" in text and "GARbro 列不出目录" in text
    # 成功的阶段不写：日志里只留噪声就没人看了
    assert "score=90" not in text


def test_creates_missing_directories(tmp_path):
    p = faillog.log_failure(error="x", root=tmp_path / "deep" / "nested")
    assert p is not None and p.is_file()


def test_falls_back_when_primary_is_unwritable(tmp_path, monkeypatch):
    """主位置建不出来（比如 exe 放在只读目录）→ 退到 LOCALAPPDATA。"""
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file, not a dir", encoding="utf-8")
    fb = tmp_path / "fb" / "failures.log"
    monkeypatch.setattr(faillog, "fallback_path", lambda: fb)

    p = faillog.log_failure(error="x", root=blocked / "sub")

    assert p == fb and fb.is_file()


def test_never_raises_when_both_paths_fail(tmp_path, monkeypatch, capsys):
    """★核心★ 两处都写不了：返回 None + stderr 一行，**不抛**。"""
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file", encoding="utf-8")
    monkeypatch.setattr(faillog, "fallback_path", lambda: blocked / "also" / "failures.log")

    p = faillog.log_failure(error="x", root=blocked / "primary")

    assert p is None
    assert "失败日志写不进去" in capsys.readouterr().err


def test_rotates_when_file_exceeds_limit(tmp_path, monkeypatch):
    """长期使用的用户不该攒出一个几百 MB 的文本文件。"""
    monkeypatch.setattr(faillog, "MAX_BYTES", 50)
    (tmp_path / "failures.log").write_text("x" * 200, encoding="utf-8")

    faillog.log_failure(error="fresh", root=tmp_path)

    assert (tmp_path / "failures.log.1").is_file(), "旧文件应被轮转"
    text = (tmp_path / "failures.log").read_text(encoding="utf-8")
    assert "fresh" in text and "x" * 200 not in text


def test_header_only_written_when_creating_file(tmp_path):
    faillog.log_failure(error="first", root=tmp_path)
    faillog.log_failure(error="second", root=tmp_path)

    text = (tmp_path / "failures.log").read_text(encoding="utf-8")
    assert text.count("# Galgame Unpacker 失败日志") == 1, "文件头只该出现一次"
    assert text.count("---") == 2, "两条失败应各成一块"


def test_values_are_flattened_to_one_line(tmp_path):
    """换行会把「一条失败一块」的格式打乱，值必须压平。"""
    faillog.log_failure(error="e", root=tmp_path, extra={"detail": "line1\nline2"})
    text = (tmp_path / "failures.log").read_text(encoding="utf-8")
    assert "line1 line2" in text


def test_traceback_is_truncated_to_tail(tmp_path):
    long_tb = "\n".join(f"frame{i}" for i in range(200))
    faillog.log_failure(error="e", root=tmp_path, exc_text=long_tb)
    text = (tmp_path / "failures.log").read_text(encoding="utf-8")
    assert "frame199" in text, "末尾必须有（根因在这里）"
    assert "frame0" not in text, "开头 40 行之外应被裁掉，避免日志爆量"
