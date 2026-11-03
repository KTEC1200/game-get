#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""golden 基线的路径归一化（批次 C6，2026-11-03）。

基线里原本存着 `D:\\K\\deepseek\\_fixtures\\unity_game\\MyGame_Data` 这种**绝对路径**，
于是 `test_fixture_matches_golden` 靠逐字比对：仓库换个盘（clone、CI 工作目录、QA 副本）
这条就必红。会随环境变红的「护栏」很快就没人看了，所以生成与比对两侧都要归一化。

这里只测归一化函数本身（纯函数，不跑 detect）：
生成侧与比对侧走的是同一个 `normalise_paths`，所以它正确就等于两侧口径一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_golden as mg  # noqa: E402


def test_repo_absolute_path_becomes_placeholder_posix():
    """★C6★ 仓库内绝对路径 → `<repo>/<相对 posix 路径>`（反斜杠统一成正斜杠）。"""
    raw = str(mg.ROOT / "_fixtures" / "unity_game" / "MyGame_Data")
    assert mg.normalise_paths(raw) == "<repo>/_fixtures/unity_game/MyGame_Data"


def test_repo_path_inside_longer_string_is_normalised():
    """路径嵌在整句 evidence 里（facts 之外还有 notes/evidence 字符串）也要归一化。"""
    raw = f"在 {mg.ROOT / '_fixtures' / 'unity_game'} 下发现 `MyGame_Data/`"
    got = mg.normalise_paths(raw)
    assert "<repo>/_fixtures/unity_game" in got
    assert str(mg.ROOT) not in got


def test_forward_slash_form_is_normalised_too():
    """同一个路径用正斜杠写（JSON 里常见）也必须归一化。"""
    raw = str(mg.ROOT).replace("\\", "/") + "/_fixtures/renpy_game"
    assert mg.normalise_paths(raw) == "<repo>/_fixtures/renpy_game"


def test_outside_repo_path_is_left_alone():
    """仓库外的路径（真实样本 `D:\\HY\\...`）原样保留：那是本机事实，不该被改写。"""
    outside = r"D:\HY\Swipe Right for Sugar Mama Sensei"
    assert mg.normalise_paths(outside) == outside


def test_nested_structures_are_walked():
    """dict / list 里嵌的路径也要处理（facts 就是 dict）。"""
    payload = {"facts": {"unity_data_dir": str(mg.ROOT / "_fixtures" / "unity_game")},
               "list": [str(mg.ROOT / "a"), 1, None, True]}
    got = mg.normalise_paths(payload)
    assert got["facts"]["unity_data_dir"] == "<repo>/_fixtures/unity_game"
    assert got["list"][0] == "<repo>/a"
    assert got["list"][1:] == [1, None, True]


def test_golden_file_has_no_absolute_repo_paths():
    """★C6 契约★ 仓库里的基线文件本身不许再出现机器绝对路径。"""
    text = mg.GOLDEN.read_text(encoding="utf-8")
    assert str(mg.ROOT) not in text, "基线里还残留绝对路径，换机器就会红"
    assert '"unity_data_dir": "<repo>/' in text


@pytest.mark.parametrize("name", ["unity_game", "renpy_game"])
def test_snapshot_of_fixture_is_stable_under_normalisation(name):
    """同一份 fixture 在生成侧和比对侧算出来必须完全一致（幂等）。"""
    snap = mg.normalise_paths(mg.snapshot_fixtures()[name])
    again = mg.normalise_paths(snap)
    assert snap == again
    assert str(mg.ROOT) not in str(snap)
