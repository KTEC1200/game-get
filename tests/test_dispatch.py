#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""galgame_dispatch 的回归测试。

三层：
  1. test_fixture_*  —— 合成 fixture，进 git，任何环境都能跑（快、无外部依赖）
  2. test_real_*     —— 真实游戏目录，只在存在时跑（skipif），用于验证指纹规则
  3. test_contract_* —— 不依赖样本的契约（阈值、ADVICE 覆盖率、manifest 约定）

跑法：
    python -m pytest tests/ -v
    python -m pytest tests/ -v -k fixture     # 只跑合成样本
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import galgame_dispatch as gd  # noqa: E402

FIXTURES = ROOT / "_fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden_detect.json"

# 12 个已跑通样本的真实路径 → 期望引擎。
# 路径不存在时该用例自动 skip（换机器/清盘不会红）。
# 注意 `My Best Deal` 已从磁盘消失，Ren'Py 分支由 Swipe Right 覆盖。
REAL_SAMPLES: list[tuple[str, str, str]] = [
    # (样本名, 相对 D:\\HY 的路径, 期望引擎)
    ("兼职人妻", r"pork社\兼职人妻", "KiriKiri"),
    ("My Wife", "My Wife Wants to Be a Professional Cosplayer", "Unity"),
    ("Swipe Right", "Swipe Right for Sugar Mama Sensei", "Ren'Py"),
    ("SPITE", "SPITE", "Tyrano/Electron"),  # Electron，归入 asar 分支
    ("常識改変学園", "常識改変学園-製品版-", "RPG Maker"),
    ("ラブラブ", r"tm\ラブラブお痴験バイト性活", "AdvHD"),
    ("あまねぇ", "あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-", "Yu-Ris"),
    ("夕凪荘", "夕凪荘的S级的女朋友们", "ExHIBIT"),
    ("甜蜜女友2+", r"甜蜜女友\【PC电脑】甜蜜女友2+", "CatSystem2"),
    ("高慢妻陥落！！", r"pork社\高慢妻陥落！！", "KiriKiri"),
    ("教师催眠1", "教师催眠1", "KiriKiri"),
]

HY_ROOT = Path(r"D:\HY")


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _normalise(value):
    """与 `make_golden.normalise_paths` **同一套**归一化（批次 C6）。

    基线里存的是 `<repo>/...` 形式的路径，现场扫出来的是绝对路径 —— 比对前必须过同一
    个函数，否则「仓库换个位置」就会红。这里刻意 import 生成脚本而不是抄一份实现：
    两份实现迟早分叉，而分叉的表现是「测试莫名其妙红」。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import make_golden
    return make_golden.normalise_paths(value)


def _fixture_dirs() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.is_dir())


# ---------------------------------------------------------------- fixtures
@pytest.mark.parametrize("fixture", _fixture_dirs(), ids=lambda p: p.name)
def test_fixture_matches_golden(fixture: Path) -> None:
    """每个 fixture 的判定必须与黄金基线逐字段一致。

    比 `evidence` 与 `facts` 是刻意的（2026-10-30 加固）：重构 `scan()` 时最容易犯的错
    不是「得分算错」，而是「证据串写错」或「fact 丢了」——只比得分的话这两类错误全绿。
    """
    want = _golden()["fixtures"][fixture.name]

    rep = gd.scan(fixture)
    best = rep.best

    assert (best.engine if best else None) == want["engine"]
    assert (best.score if best else 0) == want["score"]
    assert bool(best and best.score >= gd.THRESHOLD) == want["above_threshold"]
    assert [
        {"engine": g.engine, "score": g.score, "evidence": g.evidence}
        for g in rep.guesses
    ] == want["guesses"]
    # facts 里可能有仓库内的绝对路径（unity_data_dir）：归一化后再比，
    # 否则「仓库装在哪个盘」会决定这条回归护栏红不红（批次 C6）。
    assert _normalise(rep.facts) == want["facts"]
    assert any("[警告]" in n for n in rep.notes) == want["has_warning"]
    assert any("[注意]" in n for n in rep.notes) == want["has_attention"]


def test_fixture_count() -> None:
    """fixture 数量变了要显式确认（防止误删回归样本）。"""
    assert len(_fixture_dirs()) == 6


def test_golden_covers_all_fixtures() -> None:
    """基线与 fixture 目录必须一一对应，不能有孤儿。"""
    assert set(_golden()["fixtures"]) == {p.name for p in _fixture_dirs()}


# ------------------------------------------------------------ real samples
@pytest.mark.parametrize(
    "name,rel,expect",
    REAL_SAMPLES,
    ids=[s[0] for s in REAL_SAMPLES],
)
def test_real_sample_detects_expected_engine(name: str, rel: str, expect: str) -> None:
    """真实样本必须判定到期望引擎（超过阈值）。"""
    path = HY_ROOT / rel
    if not path.is_dir():
        pytest.skip(f"样本不存在：{path}")

    rep = gd.scan(path)
    best = rep.best
    assert best is not None, f"{name} 未命中任何规则"
    assert best.score >= gd.THRESHOLD, f"{name} 得分 {best.score} 未达阈值"
    assert best.engine == expect, f"{name} 判成 {best.engine}，期望 {expect}"


@pytest.mark.parametrize(
    "name,rel,expect",
    REAL_SAMPLES,
    ids=[s[0] for s in REAL_SAMPLES],
)
def test_real_sample_matches_golden(name: str, rel: str, expect: str) -> None:
    """真实样本的完整判定（含证据串与 facts）必须与基线一致。

    比 `test_real_sample_detects_expected_engine` 更严：那个只要求「引擎对」，
    引擎对但证据少了一条 / fact 丢了照样绿。重构 `scan()` 时必须让这条也绿。
    """
    path = HY_ROOT / rel
    if not path.is_dir():
        pytest.skip(f"样本不存在：{path}")
    want = _golden()["real"].get(path.name)
    if not want or want.get("missing"):
        pytest.skip("基线里没有这个样本")

    rep = gd.scan(path)
    best = rep.best
    assert (best.engine if best else None) == want["engine"]
    assert (best.score if best else 0) == want["score"]
    assert [
        {"engine": g.engine, "score": g.score, "evidence": g.evidence}
        for g in rep.guesses
    ] == want["guesses"]
    # facts 里可能有仓库内的绝对路径（unity_data_dir）：归一化后再比，
    # 否则「仓库装在哪个盘」会决定这条回归护栏红不红（批次 C6）。
    assert _normalise(rep.facts) == want["facts"]


# ------------------------------------------------------------- 其它契约
def test_threshold_unchanged() -> None:
    """阈值被改动会让所有历史判定失效，必须显式确认。"""
    assert gd.THRESHOLD == 60


def test_advice_covers_all_engines() -> None:
    """每个能判出来的引擎都必须有对应的 extractor 建议（否则 orchestrator 无从分派）。"""
    golden = _golden()
    engines = {v["engine"] for v in golden["fixtures"].values() if v["engine"]}
    engines |= {v["engine"] for v in golden["real"].values() if v.get("engine")}
    missing = engines - set(gd.ADVICE)
    assert not missing, f"这些引擎判得出来但没有 ADVICE 分派建议：{missing}"


def test_detect_covers_all_implemented_engines() -> None:
    """ADVICE 里声称支持的引擎，必须在 golden 里至少有一个样本真的被判定出来。

    这是「宣称支持 N 个引擎」与「实测能判 N 个引擎」之间的一致性护栏：
    只加 ADVICE 不加规则（或规则失效）会立刻红。
    """
    golden = _golden()
    detected = {v["engine"] for v in golden["fixtures"].values() if v["engine"]}
    detected |= {v["engine"] for v in golden["real"].values() if v.get("engine")}
    declared = set(gd.ADVICE)
    assert declared <= detected, (
        f"这些引擎在 ADVICE 里声明支持，但没有任何样本被真正判定出来：{declared - detected}"
    )


def test_garbro_probe_entry_count_has_no_off_by_one() -> None:
    """★口径护栏★ GARbro 列表输出**无表头**，条目数 = 非空行数。

    这条曾经是 bug：`max(0, len(lines) - 1)` 让每包少算 1 条，而条目数是对账的
    地面真相——差 1 就等于对账永远不过。`toolbridge.garbro_list()` 早就是
    `len(lines)`，两处口径必须一致，否则同一个包会给出两个「真相」。
    """
    import toolbridge as tb
    from pathlib import Path

    exe = r"D:\K\galgame\GARbro\GARbro.Console.exe"
    if not Path(exe).is_file():
        pytest.skip("本机没装 GARbro，无法验真实口径")
    xp3 = Path(r"D:\HY\pork社\兼职人妻\data.xp3")
    if not xp3.is_file():
        pytest.skip("样本已不在盘上")

    verdict, n = gd.garbro_probe(xp3, exe)
    assert verdict == "GARbro 可识别"
    ok, n_tb = tb.garbro_list(xp3)[:2]
    assert ok is True
    assert n == n_tb == 2562, f"两处口径不一致：dispatch={n} toolbridge={n_tb}"
