# -*- coding: utf-8 -*-
"""cases/ 案例库查表（软件化：cases 接入 orchestrator）的测试。

两条纪律被这几组测试钉死：
1. **签名算法只有一个出处**（`case_lib.signature`）——用「每个 case 文件里存的
   fingerprint.signature 必须能被重算出来」来锁，而不是把哈希值抄进测试里。
   抄哈希只能证明「今天算得出这个值」，重算证明「算法与案例库一致」。
2. **查表只是报告层**——命中/未命中/案例库缺失都不许让编排器失败（ok=True），
   更不许拿案例的 expected_total 去替代归档索引对账。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_cases as bc          # noqa: E402
import case_lib                   # noqa: E402
import orchestrator as orch       # noqa: E402

CASES = ROOT / "cases"
CASE_FILES = sorted(p for p in CASES.glob("*.json")
                    if not p.name.startswith("_") and p.name != "index.json")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. 签名 / case_id：与案例库里已有的值逐一对上
# ---------------------------------------------------------------------------


def test_signature_is_none_without_engine():
    """没判出引擎就不许凭空造签名——空串也会哈希出一个「看起来合法」的假签名。"""
    assert case_lib.signature(None, ["xp3"]) is None
    assert case_lib.signature("", ["xp3"]) is None


def test_signature_ignores_signal_order():
    a = case_lib.signature("KiriKiri", ["xp3", "xp3_known_names"])
    b = case_lib.signature("KiriKiri", ["xp3_known_names", "xp3"])
    assert a == b


@pytest.mark.parametrize("path", CASE_FILES, ids=[p.stem for p in CASE_FILES])
def test_each_case_signature_recomputes(path):
    """案例文件里存的签名必须能被 case_lib 重算出来（算法漂移会在这里炸）。"""
    case = _load(path)
    fp = case["fingerprint"]
    if not fp.get("signature"):
        pytest.skip(f"{case['sample']} 无指纹签名（目录缺失）")
    assert case_lib.signature(fp["engine"], fp["signals"]) == fp["signature"], \
        f"{case['sample']}: 签名与案例库不一致"


@pytest.mark.parametrize("path", CASE_FILES, ids=[p.stem for p in CASE_FILES])
def test_each_case_id_recomputes(path):
    """case_id 也必须能由 (engine, signals, sample, discriminator) 重算。"""
    case = _load(path)
    assert case_lib.case_id(case["engine"], case["fingerprint"]["signals"],
                            case["sample"], case.get("discriminator")) == case["case_id"]


def test_case_id_discriminator_separates_same_signature():
    sig = ["xp3", "xp3_known_names"]
    plain = case_lib.case_id("KiriKiri", sig, "兼职人妻", "xp3-plain")
    enc = case_lib.case_id("KiriKiri", sig, "高慢妻陥落！！", "xp3-encrypted")
    assert plain != enc


def test_build_cases_still_exposes_private_helpers():
    """test_cases.py 直接调 bc._case_id —— 重构后必须保持可用（薄委托即可）。"""
    assert bc._case_id("Ren'Py", ["rpa"], "x", None) == \
        case_lib.case_id("Ren'Py", ["rpa"], "x", None)


# ---------------------------------------------------------------------------
# 2. 索引与查表
# ---------------------------------------------------------------------------


def test_load_index_reads_real_index():
    idx = case_lib.load_index(CASES)
    assert idx and idx["schema"] == "cases-index/1"
    assert "by_signature" in idx


def test_load_index_missing_returns_none(tmp_path):
    assert case_lib.load_index(tmp_path) is None


def test_load_index_corrupt_returns_none(tmp_path):
    (tmp_path / "index.json").write_text("{not json", encoding="utf-8")
    assert case_lib.load_index(tmp_path) is None


def test_lookup_hits_three_kirikiri_variants():
    """同签名不同 discriminator 的三个 KiriKiri 案例必须全部列出，不能只挑一个。"""
    res = case_lib.lookup("KiriKiri", ["xp3", "xp3_known_names"], CASES)
    assert res["index_present"] is True
    assert res["signature"] == "6519ddb81f58"
    discs = {c["discriminator"] for c in res["candidates"]}
    assert discs == {"xp3-plain", "xp3-encrypted", "xp3-encrypted-krkrZ"}
    # 每个候选都带上了历史失败教训的条数与提取器名
    for c in res["candidates"]:
        assert c["failures"] > 0
        assert c["decision"]["extractor"]


def test_lookup_miss_returns_empty_but_keeps_signature():
    res = case_lib.lookup("KiriKiri", ["no_such_signal"], CASES)
    assert res["signature"]
    assert res["candidates"] == []


def test_lookup_missing_index_is_not_an_error(tmp_path):
    res = case_lib.lookup("KiriKiri", ["xp3"], tmp_path)
    assert res["index_present"] is False
    assert res["candidates"] == []


def test_lookup_survives_missing_case_file(tmp_path):
    """索引里登记了 case、文件却被删了 —— 报缺口（missing），不许抛异常。"""
    sig = case_lib.signature("X", [])
    idx = {"schema": "cases-index/1", "by_signature": {
        sig: [{"case_id": "deadbeef0000", "engine": "X",
               "engine_label": "X", "sample": "幽灵",
               "discriminator": None, "provenance": "manifest"}]}}
    (tmp_path / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    res = case_lib.lookup("X", [], tmp_path)
    assert len(res["candidates"]) == 1
    assert res["candidates"][0]["missing"] is True
    assert res["candidates"][0]["failures"] == 0


# ---------------------------------------------------------------------------
# 3. orchestrator 阶段：报告层，永不失败
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path, game_dir: Path | None = None) -> orch.Ctx:
    return orch.Ctx(game_dir=game_dir or tmp_path,
                    out_dir=tmp_path / "out", work_dir=tmp_path / "work",
                    manifest_path=tmp_path / "out" / "manifest.json")


REAL_KIRIKIRI = Path(r"D:\HY\pork社\兼职人妻")


def test_stage_hits_real_sample(tmp_path):
    if not REAL_KIRIKIRI.is_dir():
        pytest.skip(f"样本不存在: {REAL_KIRIKIRI}")
    st = orch.stage_case_lookup(
        _ctx(tmp_path, REAL_KIRIKIRI),
        {"engine": "KiriKiri", "fired_ids": ["xp3", "xp3_known_names"]})
    assert st.ok and not st.skipped
    assert st.data["signature"] == "6519ddb81f58"
    assert len(st.data["candidates"]) == 3
    assert "命中 3 个案例" in st.detail


def test_stage_no_match_is_ok_not_failure(tmp_path):
    st = orch.stage_case_lookup(_ctx(tmp_path),
                                {"engine": "KiriKiri", "fired_ids": ["bogus"]})
    assert st.ok, "查不到案例是正常结果，不是失败"
    assert st.data["candidates"] == []
    assert "无匹配案例" in st.detail


def test_stage_missing_cases_dir_is_skipped(tmp_path):
    """案例库整个不在（干净检出）→ 跳过，不许把解包搞挂。"""
    st = orch.stage_case_lookup(_ctx(tmp_path),
                                {"engine": "KiriKiri", "fired_ids": ["xp3"]},
                                cases_dir=tmp_path / "no_cases")
    assert st.ok and st.skipped
    assert st.data["index_present"] is False


def test_stage_forced_engine_without_detect_data(tmp_path):
    """--engine 强制模式没跑 detect：要么补扫，要么跳过，反正不能抛。"""
    st = orch.stage_case_lookup(_ctx(tmp_path), None)
    assert st.ok


# ---------------------------------------------------------------------------
# 4. manifest：命中信息要落在读 manifest 的人会看的地方
# ---------------------------------------------------------------------------


def test_manifest_source_carries_case_match(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.raw_dir).mkdir(parents=True)
    (ctx.raw_dir / "a.ogg").write_bytes(b"x")

    case_stage = orch.Stage("case-lookup", ok=True, detail="命中 1 个案例")
    case_stage.data = {
        "signature": "6519ddb81f58", "index_present": True,
        "candidates": [{
            "case_id": "3f7607cd8585", "sample": "兼职人妻",
            "engine_label": "KiriKiri", "discriminator": "xp3-plain",
            "provenance": "docs-reconstructed",
            "decision": {"extractor": "garbro", "expected_total": 2562},
            "failures": 3,
        }],
    }
    extract = orch.Stage("extract", ok=True)
    extract.data = {"expected_total": 1}
    verify = orch.Stage("verify", ok=True)
    verify.data = {"verified": False}
    post = orch.Stage("postprocess", ok=True, skipped=True)

    man = orch.build_manifest(ctx, [case_stage, extract, post, verify], "KiriKiri")
    cm = man["source"]["case_match"]
    assert cm["signature"] == "6519ddb81f58"
    assert cm["candidates"][0]["case_id"] == "3f7607cd8585"
    assert cm["candidates"][0]["decision"]["extractor"] == "garbro"
    assert cm["candidates"][0]["failures"] == 3
    # 案例库不是地面真相：对账仍然只认归档索引
    assert man["reconcile"]["expected"] == 1


def test_manifest_source_has_no_case_match_when_missed(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.raw_dir).mkdir(parents=True)
    case_stage = orch.Stage("case-lookup", ok=True, detail="无匹配案例")
    case_stage.data = {"signature": "x", "index_present": True, "candidates": []}
    extract = orch.Stage("extract", ok=True)
    extract.data = {}
    verify = orch.Stage("verify", ok=True)
    verify.data = {"verified": False}
    man = orch.build_manifest(ctx, [case_stage, extract, verify], "KiriKiri")
    assert "case_match" not in man["source"], "没命中就别写空字段"
