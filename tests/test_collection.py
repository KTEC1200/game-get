#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集合目录识别（count_subdir_games）的回归测试。

历史缺陷（都在 2026-10-29 修）：
  1. 封包扩展名只认 `.xp3/.rpa/.asar` + `_Data` → CatSystem2（`.int`）、Yu-Ris（`.ypf`）、
     ExHIBIT（`.gyu`）、AdvHD（`.arc`）的集合目录全部漏判。
  2. 补全扩展名后「只看封包」又过头了 → `夕凪荘` 的 `res/`、`userdata/` 是同一游戏内部的
     资源目录（含 .gyu/.grp，但没有 exe），被误判成 2 个独立子游戏。
     正解：真子游戏 = 有封包 **且** 有 exe。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from galgame_dispatch import count_subdir_games  # noqa: E402


def _mk_game(d: Path, exe: str = "game.exe", pack: str = "data.xp3") -> None:
    """造一个「像游戏」的目录：有 exe + 有封包。"""
    d.mkdir(parents=True, exist_ok=True)
    if exe:
        (d / exe).write_bytes(b"MZ")
    if pack:
        (d / pack).write_bytes(b"XP3\r\n \n\x1a\x8bg\x01")


def _mk_resources(d: Path, pack: str = "res2000.grp") -> None:
    """造一个「只是资源目录」的目录：有封包但**没有** exe。"""
    d.mkdir(parents=True, exist_ok=True)
    (d / pack).write_bytes(b"AiFS")


# --------------------------------------------------- 真子游戏：必须认出来
@pytest.mark.parametrize(
    "pack",
    ["data.xp3", "archive.rpa", "app.asar", "game.arc", "data.ypf", "cg.gyu", "image00.int"],
)
def test_pack_plus_exe_is_a_game(tmp_path: Path, pack: str) -> None:
    """每种受支持的封包类型 + exe 都要被认成独立游戏。"""
    _mk_game(tmp_path / "game1", pack=pack)
    _mk_game(tmp_path / "game2", pack=pack)
    found = count_subdir_games(tmp_path, ["game1", "game2"])
    assert found == ["game1", "game2"], f"{pack} 未被识别"


# ------------------------------------------ 资源目录：绝不能被当成子游戏
@pytest.mark.parametrize("pack", ["res2000.grp", "data.ypf", "cg.gyu", "image00.int"])
def test_pack_without_exe_is_not_a_game(tmp_path: Path, pack: str) -> None:
    """只有封包、没有 exe 的目录是资源目录，不能算子游戏（夕凪荘 res/userdata 的教训）。"""
    _mk_resources(tmp_path / "res", pack=pack)
    _mk_resources(tmp_path / "userdata", pack=pack)
    found = count_subdir_games(tmp_path, ["res", "userdata"])
    assert found == [], f"资源目录被误判成子游戏（pack={pack}）"


def test_exe_without_pack_is_not_a_game(tmp_path: Path) -> None:
    """只有 exe、没有封包的目录（比如工具目录）也不算子游戏。"""
    d = tmp_path / "tools"
    d.mkdir()
    (d / "tool.exe").write_bytes(b"MZ")
    assert count_subdir_games(tmp_path, ["tools"]) == []


# ------------------------------------------------------------ 真实场景对照
def test_mixed_collection(tmp_path: Path) -> None:
    """集合目录里既有真游戏、又有资源目录时，只报真游戏。"""
    _mk_game(tmp_path / "game1", pack="data.xp3")
    _mk_game(tmp_path / "game2", pack="image00.int")
    _mk_resources(tmp_path / "res")
    found = count_subdir_games(tmp_path, ["game1", "game2", "res"])
    assert found == ["game1", "game2"]


def test_unity_data_dir_counts(tmp_path: Path) -> None:
    """Unity 的 `Xxx_Data/` 目录也算游戏特征（沿用原有判据）。"""
    d = tmp_path / "MyGame"
    d.mkdir()
    (d / "MyGame.exe").write_bytes(b"MZ")
    (d / "MyGame_Data").mkdir()
    found = count_subdir_games(tmp_path, ["MyGame"])
    assert found == ["MyGame"]


def test_nested_game_found_within_two_levels(tmp_path: Path) -> None:
    """本体藏在下一层（如 `7/`）也要能认出来。"""
    inner = tmp_path / "outer" / "7"
    _mk_game(inner, pack="data.xp3")
    assert count_subdir_games(tmp_path, ["outer"]) == ["outer"]


def test_empty_dir(tmp_path: Path) -> None:
    """空目录不报错。"""
    (tmp_path / "empty").mkdir()
    assert count_subdir_games(tmp_path, ["empty"]) == []


def test_missing_dir(tmp_path: Path) -> None:
    """不存在的子目录不崩。"""
    assert count_subdir_games(tmp_path, ["nope"]) == []
