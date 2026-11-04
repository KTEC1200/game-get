#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工介入方案（`manual.py`）的测试。

重心：**方案必须可执行**。三件事缺一个用户就卡住 ——
  ① 要准备什么（工具在哪）② 一步步做什么 ③ 做完跑哪条命令。
另外路径带空格时命令必须带引号：用户是复制粘贴，不是自己拼。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import manual  # noqa: E402


def _plan(error: str, engine: str | None = "KiriKiri", **kw):
    return manual.plan_for(
        error, engine=engine,
        game_dir=kw.pop("game_dir", Path(r"D:\HY\Some Game")),
        out_dir=kw.pop("out_dir", Path(r"D:\HY\Some Game\_extracted\Some Game")),
        raw_dir=kw.pop("raw_dir", Path(r"D:\HY\Some Game\_extracted\Some Game\raw")),
        png_dir=kw.pop("png_dir", Path(r"D:\HY\Some Game\_extracted\Some Game\png")),
        **kw)


# ---------------------------------------------------------------------------
# 场景映射
# ---------------------------------------------------------------------------

def test_kirikiri_encrypted_plan_has_tool_steps_and_resume_command():
    plan = _plan("extract-failed", tools={"krkr": r"D:\bin\krkr\KrkrExtract.Lite.exe"})

    assert plan is not None
    assert plan.code == manual.CODE_KIRIKIRI_ENCRYPTED
    assert r"D:\bin\krkr\KrkrExtract.Lite.exe" in " ".join(plan.needs)
    assert any("拖进 KrkrExtract" in s for s in plan.steps)
    assert plan.target and plan.target.endswith("raw")
    assert plan.then and "--reuse-raw" in plan.then, "不给续跑命令 = 用户做完还得自己猜"
    assert any("--allow-gui" in a for a in plan.alternatives)


def test_kirikiri_gui_failure_gets_its_own_code():
    """GUI 链路已经跑过但失败：要区分「没试过」与「试过不成」，处置不一样。"""
    plan = _plan("extract-failed", stages=[{"stage": "extract",
                                            "detail": "GUI 链路失败或没有产出 KrkrExtract_Output (rc=1)"}])
    assert plan.code == manual.CODE_KIRIKIRI_GUI_FAILED


def test_unity_no_assets_plan_points_at_assetstudio():
    plan = _plan("extract-failed", engine="Unity",
                 tools={"assetstudio": r"D:\bin\assetstudio\AssetStudio.CLI.exe"})
    assert plan.code == manual.CODE_UNITY_NO_ASSETS
    assert any("AssetStudio.GUI.exe" in n for n in plan.needs)
    assert any("Image_Texture2D" in s for s in plan.steps)


def test_engine_no_chain_plan_says_put_files_into_raw():
    plan = _plan("chain-not-implemented", engine="Tyrano")
    assert plan.code == manual.CODE_ENGINE_NO_CHAIN
    assert "Tyrano" in plan.summary
    assert plan.target and plan.target.endswith("raw")
    assert plan.then and "--reuse-raw" in plan.then


def test_detect_failed_plan_mentions_engine_override():
    plan = _plan("detect-failed", engine=None)
    assert plan.code == manual.CODE_DETECT_FAILED
    assert "--engine" in (plan.then or "")


def test_unknown_failure_returns_none():
    """没有合适方案就别硬凑 —— 一段编出来的指引比一句错误码更害人。"""
    assert _plan("verify-failed") is None
    assert _plan("cancelled") is None
    assert _plan("reset-failed") is None


# ---------------------------------------------------------------------------
# 可执行性：路径引号 / 渲染 / 序列化
# ---------------------------------------------------------------------------

def test_resume_command_quotes_paths_with_spaces():
    plan = _plan("chain-not-implemented", engine="Tyrano",
                 game_dir=Path(r"D:\HY\Some Game"),
                 out_dir=Path(r"D:\HY\Some Game\_out"),
                 raw_dir=Path(r"D:\HY\Some Game\_out\raw"))
    assert '"D:\\HY\\Some Game"' in plan.then
    assert '--reuse-raw "D:\\HY\\Some Game\\_out\\raw"' in plan.then


def test_render_contains_every_actionable_part():
    plan = _plan("extract-failed", tools={"krkr": r"D:\bin\krkr\KrkrExtract.Lite.exe"})
    text = plan.render()

    assert plan.summary in text
    assert "需要准备" in text and "按顺序做" in text
    assert "产物放到" in text and "做完重跑" in text
    assert "--reuse-raw" in text
    assert plan.steps[0] in text


def test_as_dict_is_json_serialisable():
    plan = _plan("extract-failed", tools={"krkr": "x"})
    data = plan.as_dict()
    json.dumps(data, ensure_ascii=False)          # 不抛就是可序列化
    assert data["steps"] and isinstance(data["steps"], list)
    assert data["code"] == plan.code


def test_render_dict_roundtrip():
    """CLI 拿到的是 manifest 里的 dict，必须能还原成同样的区块。"""
    plan = _plan("extract-failed", tools={"krkr": "x"})
    assert manual.render_dict(plan.as_dict()) == plan.render()
    assert manual.render_dict({}) == ""
    assert manual.render_dict(None) == ""


# ---------------------------------------------------------------------------
# dry-run 预判
# ---------------------------------------------------------------------------

def test_dry_run_warns_before_a_40_minute_run():
    plan = manual.dry_run_plan(
        "KiriKiri", game_dir=Path(r"D:\HY\G"), out_dir=Path(r"D:\HY\out"),
        raw_dir=Path(r"D:\HY\out\raw"), png_dir=Path(r"D:\HY\out\png"),
        xp3_probe=(False, "data.xp3"), tools={"krkr": "x"})
    assert plan is not None
    assert "预判" in plan.summary and "data.xp3" in plan.summary
    assert plan.then and "--reuse-raw" in plan.then


def test_dry_run_stays_quiet_when_static_unpack_looks_fine():
    assert manual.dry_run_plan(
        "KiriKiri", game_dir=Path("g"), out_dir=Path("o"), raw_dir=Path("o/raw"),
        png_dir=Path("o/png"), xp3_probe=(True, "data.xp3")) is None
    assert manual.dry_run_plan(
        "Ren'Py", game_dir=Path("g"), out_dir=Path("o"), raw_dir=Path("o/raw"),
        png_dir=Path("o/png"), xp3_probe=None) is None
