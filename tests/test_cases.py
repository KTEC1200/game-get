#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`cases/` 案例库的测试。

锁住三件事：
  1. **纯函数**：`_case_id` 确定性 + discriminator 生效；`_summarize` 分类正确；
     `build_index` 分组；`validate_cases` 能抓住 provenance 造假。
  2. **构建产物**：`cases/*.json` + `index.json` 的结构（12 案例、case_id 唯一、
     docs 案例的 counts/verify/reconcile/manifest_path 必须 null、failures 每条有 ref）。
  3. **诚实纪律**：docs 重建的案例不许伪造 manifest 口径的数字。

不依赖 D:\HY 真实游戏目录（测试读已构建好的 JSON，不重跑 build_all）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_cases as bc  # noqa: E402

CASES_DIR = ROOT / "cases"


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------
def test_case_id_deterministic():
    a = bc._case_id("Ren'Py", ["rpa", "renpy_dir"], "Swipe Right", None)
    b = bc._case_id("Ren'Py", ["rpa", "renpy_dir"], "Swipe Right", None)
    assert a == b
    assert len(a) == 12


def test_case_id_order_insensitive():
    a = bc._case_id("Ren'Py", ["rpa", "renpy_dir"], "Swipe Right", None)
    b = bc._case_id("Ren'Py", ["renpy_dir", "rpa"], "Swipe Right", None)
    assert a == b


def test_case_id_discriminator_separates_same_signature():
    """兼职人妻 vs 高慢妻 指纹完全相同，靠 discriminator 区分。"""
    sig = ["xp3", "xp3_known_names"]
    plain = bc._case_id("KiriKiri", sig, "兼职人妻", "xp3-plain")
    enc = bc._case_id("KiriKiri", sig, "高慢妻陥落！！", "xp3-encrypted")
    assert plain != enc


def test_summarize_classifies_by_ext():
    counts = {
        "final": {
            "by_ext": {
                ".png": 100, ".jpg": 50, ".tlg": 30,   # 图片（含待转 .tlg）
                ".ogg": 200, ".wav": 40,                 # 音频
                ".mpg": 5, ".webm": 3,                   # 视频
                ".ks": 900,                               # 脚本（不计入三类）
            },
            "total": 1328,
        }
    }
    s = bc._summarize(counts)
    assert s["images"] == 180
    assert s["audio"] == 240
    assert s["video"] == 8
    assert s["total"] == 1328


def test_summarize_empty():
    assert bc._summarize(None) == {"images": None, "audio": None,
                                   "video": None, "total": None}


def _mk_case(**over) -> dict:
    base = {
        "schema": bc.SCHEMA_VERSION,
        "case_id": "abc123456789",
        "engine": "Ren'Py",
        "engine_label": "Ren'Py",
        "sample": "Test Game",
        "game_dir": "C:\\test",
        "discriminator": None,
        "fingerprint": {"signals": ["rpa"], "score": 100, "threshold": 60,
                        "signature": "deadbeef0001", "reconstructed": False},
        "decision": {"extractor": "rpa_tool"},
        "timing": {"total": 10.0},
        "result": {"ok": True, "source": "docs", "summary": {"images": 1},
                   "media_minutes": None, "counts": None, "verify": None,
                   "reconcile": None},
        "failures": [],
        "provenance": {"source": "docs-reconstructed", "manifest_path": None,
                       "doc_refs": ["AGENTS.md"], "generated_at": "now"},
    }
    base.update(over)
    return base


def test_validate_accepts_good_case():
    assert bc.validate_cases([_mk_case()]) == []


def test_validate_rejects_docs_case_with_manifest_path():
    c = _mk_case()
    c["provenance"]["manifest_path"] = "_extracted/x/manifest.json"
    problems = bc.validate_cases([c])
    assert any("manifest_path" in p for p in problems)


def test_validate_rejects_docs_case_with_counts():
    c = _mk_case()
    c["result"]["counts"] = {"final": {"total": 1}}
    problems = bc.validate_cases([c])
    assert any("counts" in p for p in problems)


def test_validate_rejects_bad_source():
    c = _mk_case()
    c["provenance"]["source"] = "guess"
    problems = bc.validate_cases([c])
    assert any("source" in p for p in problems)


def test_validate_rejects_failure_without_ref():
    c = _mk_case()
    c["failures"] = [{"stage": "extract", "symptom": "x", "root_cause": "y",
                      "fix": "z", "ref": ""}]
    problems = bc.validate_cases([c])
    assert any("ref" in p for p in problems)


def test_validate_rejects_duplicate_case_id():
    c = _mk_case()
    problems = bc.validate_cases([c, c])
    assert any("重复" in p or "duplicate" in p.lower() for p in problems)


def test_validate_rejects_missing_field():
    c = _mk_case()
    del c["decision"]
    problems = bc.validate_cases([c])
    assert any("decision" in p for p in problems)


# ---------------------------------------------------------------------------
# 构建产物（读已落盘的 cases/*.json + index.json）
# ---------------------------------------------------------------------------
def _load_built_cases() -> list[dict]:
    files = sorted(CASES_DIR.glob("*.json"))
    cases = []
    for f in files:
        if f.name == "index.json":
            continue
        if f.name.startswith("_"):
            continue
        cases.append(json.loads(f.read_text(encoding="utf-8")))
    return cases


def test_built_cases_exist():
    cases = _load_built_cases()
    assert len(cases) == 13


def test_write_all_preserves_unrelated_and_rejects_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "CASES", tmp_path)
    unrelated = tmp_path / "other.json"
    unrelated.write_bytes(b"original")
    case = _mk_case()
    path = tmp_path / bc._case_filename(case)
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        bc.write_all([case])
    assert unrelated.read_bytes() == b"original"
    assert path.read_bytes() == b"existing"


def test_build_all_skips_existing_and_missing_manifests(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "CASES", tmp_path)
    case = _mk_case()
    (tmp_path / bc._case_filename(case)).write_text(json.dumps(case), encoding="utf-8")
    monkeypatch.setattr(bc, "SAMPLES", {"Test Game": {"manifest": "missing.json"},
                                      "Missing": {"manifest": "also-missing.json"}})
    monkeypatch.setattr(bc, "_load_failures", lambda: {})
    monkeypatch.setattr(bc, "_load_docs_meta", lambda: {})
    assert bc.build_all() == []


def test_index_and_validate_use_disk_and_are_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "CASES", tmp_path)
    case = _mk_case()
    (tmp_path / bc._case_filename(case)).write_text(json.dumps(case), encoding="utf-8")
    monkeypatch.setattr(bc, "build_all", lambda: pytest.fail("unexpected rebuild"))
    assert bc.main(["--index", "--validate"]) == 0
    before = (tmp_path / "index.json").read_bytes()
    assert bc.main(["--index", "--validate"]) == 0
    assert (tmp_path / "index.json").read_bytes() == before


def test_toshiue_case_uses_recorded_manifest():
    manifest = json.loads((CASES_DIR / "_toshiue_manifest.json").read_text(encoding="utf-8"))
    case = next(c for c in _load_built_cases() if c["sample"] == "Toshiue Kanojo")
    detect = next(s for s in manifest["stages"] if s["stage"] == "detect")
    assert case["fingerprint"]["signals"] == sorted(detect["fired_ids"])
    assert case["fingerprint"]["score"] == detect["score"]
    assert case["result"]["reconcile"] == manifest["reconcile"]
    assert case["provenance"]["manifest_path"] == "cases/_toshiue_manifest.json"


def test_built_cases_validate_clean():
    cases = _load_built_cases()
    assert bc.validate_cases(cases) == []


def test_built_case_ids_unique():
    cases = _load_built_cases()
    ids = [c["case_id"] for c in cases]
    assert len(ids) == len(set(ids))


def test_built_cases_sources_mixed():
    cases = _load_built_cases()
    sources = {c["provenance"]["source"] for c in cases}
    assert "manifest" in sources
    assert "docs-reconstructed" in sources


def test_built_docs_cases_have_null_manifest_fields():
    cases = _load_built_cases()
    docs = [c for c in cases if c["provenance"]["source"] == "docs-reconstructed"]
    assert docs, "应该至少有一个 docs 重建案例"
    for c in docs:
        assert c["provenance"]["manifest_path"] is None
        assert c["result"]["counts"] is None
        assert c["result"]["verify"] is None
        assert c["result"]["reconcile"] is None


def test_built_manifest_cases_have_real_counts():
    cases = _load_built_cases()
    man = [c for c in cases if c["provenance"]["source"] == "manifest"]
    assert man, "应该至少有一个 manifest 案例"
    for c in man:
        assert c["provenance"]["manifest_path"]
        assert c["result"]["counts"] is not None
        assert c["result"]["reconcile"] is not None


def test_built_failures_all_have_refs():
    cases = _load_built_cases()
    for c in cases:
        for i, f in enumerate(c.get("failures", [])):
            assert f.get("ref"), f"{c['case_id']} failures[{i}] 缺 ref"


def test_index_covers_all_signatures():
    idx = json.loads((CASES_DIR / "index.json").read_text(encoding="utf-8"))
    cases = _load_built_cases()
    assert idx["schema"] == "cases-index/1"
    # 每个有签名的 case 都应出现在 by_signature 里
    for c in cases:
        sig = c["fingerprint"].get("signature")
        if sig:
            assert sig in idx["by_signature"], f"签名 {sig} 不在索引里"
    # 索引里的 case_id 都应指向真实 case
    known = {c["case_id"] for c in cases}
    for sig, entries in idx["by_signature"].items():
        for e in entries:
            assert e["case_id"] in known


def test_kiri_kiri_signature_groups_encrypted_cases():
    """KiriKiri 三样本共享一个签名，靠 discriminator 区分 —— 索引必须体现。"""
    idx = json.loads((CASES_DIR / "index.json").read_text(encoding="utf-8"))
    kira = [e for entries in idx["by_signature"].values() for e in entries
            if e["engine"] == "KiriKiri" and e["discriminator"]]
    discs = {e["discriminator"] for e in kira}
    assert "xp3-plain" in discs
    assert "xp3-encrypted" in discs
    assert "xp3-encrypted-krkrZ" in discs
