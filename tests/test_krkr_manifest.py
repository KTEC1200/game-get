#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`krkr_auto_extract.write_manifest()` 的测试。

这个模块整体没法在 CI 里跑（它靠 GUI 注入 + Explorer 拖拽），
但 manifest 生成那半截是纯数据逻辑，必须被锁住 —— 否则契约漂移了没人发现。

关键断言：
  * `data/` 是 raw（含 .tlg），`png/` 是转换成品，**final 里不许有 .tlg**；
  * 加密 xp3 没有地面真相 → `reconcile` 必须 `expected=None, diff=None,
    method="no-index-available"`，**不许假装对过账**；
  * `verify.verified` 必须是 False（本工具确实不做内容验收）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import krkr_auto_extract as kae  # noqa: E402


def _write(p: Path, data: bytes = b"x" * 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _png(p: Path) -> Path:
    return _write(p, b"\x89PNG\r\n\x1a\n" + b"x" * 16)


def _fake_output(tmp_path: Path) -> Path:
    """造一个 KrkrExtract_Output 形态：data/ 里 raw + png/ 里转换成品。"""
    out = tmp_path / "KrkrExtract_Output"
    _write(out / "data" / "bgm01.ogg")
    _write(out / "data" / "se01.ogg")
    _write(out / "data" / "bg01.tlg")       # 待转格式
    _write(out / "data" / "plain.png")      # raw 里也有 png
    _write(out / "data" / "script.ks")
    _png(out / "png" / "bg01.png")          # tlg 的转换成品
    return out


def test_manifest_three_section_counts(tmp_path):
    out = _fake_output(tmp_path)
    mp = tmp_path / "manifest.json"

    man, counts = kae.write_manifest(out, tmp_path / "game", [
        {"name": "data.xp3", "files": 4, "total_after": 4},
    ], mp)

    assert counts["raw"]["total"] == 5
    assert ".tlg" in counts["raw"]["by_ext"]
    # final = raw 去掉 .tlg(1) + png/ 的成品(1) = 5
    assert counts["final"]["total"] == 5
    assert ".tlg" not in counts["final"]["by_ext"]
    assert counts["final"]["by_ext"][".png"] == 2   # plain.png + 转换的 bg01.png
    assert counts["converted"] == {".tlg": 1}

    assert man["counts"] == counts
    assert man["tool"] == "krkr_auto_extract.py"
    assert man["engine"] == "KiriKiri"


def test_manifest_reconcile_is_explicitly_unverified(tmp_path):
    """★核心★ 加密 xp3 没地面真相 → 必须明说没对账，不许 diff=0。"""
    out = _fake_output(tmp_path)
    man, _counts = kae.write_manifest(out, tmp_path / "game", [], tmp_path / "m.json")

    r = man["reconcile"]
    assert r["expected"] is None
    assert r["diff"] is None, "没验过就不许报 0"
    assert r["method"] == "no-index-available"
    assert r["actual"] == 5


def test_manifest_marks_verify_not_done(tmp_path):
    out = _fake_output(tmp_path)
    man, _c = kae.write_manifest(out, tmp_path / "game", [], tmp_path / "m.json")
    assert man["verify"]["verified"] is False
    assert "note" in man["verify"]


def test_manifest_records_per_archive(tmp_path):
    """逐包明细走 manifest 的规范三键（2026-11-04 统一）。

    加密包没有索引 → `entries` 必须是 None（没对账 ≠ 对上了）；
    本包实测新增数进 `extracted`。早前的 files/total_after 别名已不再产出。
    """
    out = _fake_output(tmp_path)
    per = [{"name": "data.xp3", "entries": None, "extracted": 3, "total_after": 3},
           {"name": "voice.xp3", "entries": None, "extracted": 2, "total_after": 5}]
    man, _c = kae.write_manifest(out, tmp_path / "game", per, tmp_path / "m.json")

    assert man["source"]["archives"] == per
    assert all(a["entries"] is None for a in man["source"]["archives"]), \
        "加密包没有地面真相，entries 不能填成实测数"
    assert man["source"]["encrypted"] is True


def test_manifest_postprocess_empty_when_no_png_dir(tmp_path):
    out = tmp_path / "KrkrExtract_Output"
    _write(out / "data" / "a.ogg")
    man, _c = kae.write_manifest(out, tmp_path / "game", [], tmp_path / "m.json")
    assert man["postprocess"] == []
    assert man["png_dir"]["total"] == 0


def test_manifest_postprocess_present_when_png_dir(tmp_path):
    out = _fake_output(tmp_path)
    man, _c = kae.write_manifest(out, tmp_path / "game", [], tmp_path / "m.json")
    assert len(man["postprocess"]) == 1
    assert man["png_dir"]["total"] == 1


def test_manifest_written_as_readable_json(tmp_path):
    out = _fake_output(tmp_path)
    mp = tmp_path / "sub" / "manifest.json"
    kae.write_manifest(out, tmp_path / "ゲーム", [], mp)

    assert mp.is_file()
    text = mp.read_text(encoding="utf-8")
    assert "ゲーム" in text, "CJK 路径必须原样可读"
    back = json.loads(text)
    assert back["manifest_version"] == 1
