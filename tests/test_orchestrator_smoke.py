#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator 的**真实样本**冒烟测试。

与 test_orchestrator.py 分工：那边用 monkeypatch 测编排契约（快、零依赖），
这边真跑 `D:\\HY` 下的样本，验证两条链路真的通。

设计取舍：
  * 样本缺失 → **skip 而不是 fail**（换机器/清盘不会红）。
  * 默认只跑**快速档**：`--dry-run`（只 detect，秒级）。
    完整链路要几分钟，且会写盘，用 `ORCH_SMOKE_FULL=1` 显式开启。
  * 完整链路一律输出到 `tmp_path`，不碰 `D:\\HY` 原始文件。

跑法：
    python -m pytest tests/test_orchestrator_smoke.py -q
    ORCH_SMOKE_FULL=1 python -m pytest tests/test_orchestrator_smoke.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402

HY = Path(r"D:\HY")

#: 已实现链路各取一个已验证过的样本（Ren'Py/KiriKiri 2026-10-29 实测，
#: RPG Maker/Yu-Ris 2026-10-30 接入后实测，ExHIBIT 2026-10-30 接入后实测）。
#: 快速档只 detect（秒级）；`ORCH_SMOKE_FULL=1` 会**真解包并写进 tmp_path**，
#: 这些都是数 GB 级的样本，跑之前先看 C 盘余量。
SAMPLES: list[tuple[str, Path, str]] = [
    ("Swipe Right", HY / "Swipe Right for Sugar Mama Sensei", "Ren'Py"),
    ("兼职人妻", HY / r"pork社\兼职人妻", "KiriKiri"),
    ("常識改変学園", HY / "常識改変学園-製品版-", "RPG Maker"),
    ("あまねぇ", HY / "あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-", "Yu-Ris"),
    ("夕凪荘", HY / "夕凪荘的S级的女朋友们", "ExHIBIT"),
]

FULL = os.environ.get("ORCH_SMOKE_FULL") == "1"


def _sample(name: str) -> Path:
    for n, p, _e in SAMPLES:
        if n == name:
            if not p.is_dir():
                pytest.skip(f"样本不存在: {p}")
            return p
    raise KeyError(name)


# ---------------------------------------------------------------------------
# 快速档：只 detect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,path,engine", SAMPLES,
                         ids=[s[0] for s in SAMPLES])
def test_dry_run_detects_expected_engine(name, path, engine):
    """detect 必须判出预期引擎，且该引擎在 IMPLEMENTED 里（否则链路走不到）。"""
    if not path.is_dir():
        pytest.skip(f"样本不存在: {path}")
    st = orch.stage_detect(orch.Ctx(
        game_dir=path, out_dir=Path(os.devnull).parent / "_unused",
        work_dir=Path(os.devnull).parent / "_unused",
        manifest_path=Path(os.devnull)))
    assert st.ok, st.detail
    assert st.data["engine"] == engine
    assert engine in orch.IMPLEMENTED


# ---------------------------------------------------------------------------
# 完整档：真解包 + 真验收（ORCH_SMOKE_FULL=1）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not FULL, reason="完整链路较慢，设 ORCH_SMOKE_FULL=1 开启")
@pytest.mark.parametrize("name,path,engine", SAMPLES,
                         ids=[s[0] for s in SAMPLES])
def test_full_chain_exit_zero(name, path, engine, tmp_path):
    """全链跑到退出码 0，且 manifest 的对账/验收都是 0 失败。"""
    if not path.is_dir():
        pytest.skip(f"样本不存在: {path}")
    out = tmp_path / "out"
    rc = orch.main([str(path), "--out", str(out)])
    assert rc == 0, f"{name} 退出码 {rc}"

    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert man["engine"] == engine
    assert man["reconcile"]["diff"] == 0
    v = man["verify"]
    assert v["verified"] is True
    assert v["image_fail"] == 0 and v["audio_fail"] == 0 and v["video_fail"] == 0
    # counts 三段式齐备，且 final 不含被消费的中间格式
    assert set(man["counts"]) == {"raw", "final", "converted"}
    assert ".tlg" not in man["counts"]["final"]["by_ext"]
    # 对账的地面真相必须真的取到了（不是 None 混过去）
    assert man["reconcile"]["expected"] is not None
    assert man["reconcile"]["actual"] == man["reconcile"]["expected"]


@pytest.mark.skipif(not FULL, reason="完整链路较慢，设 ORCH_SMOKE_FULL=1 开启")
def test_full_chain_reuse_raw_is_idempotent(tmp_path):
    """--reuse-raw 复跑必须得到同样的结论（断点续传不能改变判定）。"""
    path = _sample("兼职人妻")
    out = tmp_path / "out"
    assert orch.main([str(path), "--out", str(out)]) == 0
    man1 = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    # 源与目标同一目录（实测踩过 copytree 自杀）
    assert orch.main([str(path), "--out", str(out),
                      "--reuse-raw", str(out / "raw")]) == 0
    man2 = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert man1["counts"]["final"]["total"] == man2["counts"]["final"]["total"]
    assert man1["reconcile"]["expected"] == man2["reconcile"]["expected"]
