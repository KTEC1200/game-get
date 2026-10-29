#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demojibake() 的回归测试。

背景（2026-10-29 修的既有缺陷）：`装備.rpgmvo` 是**合法日文名**，
但它按 GBK 编码后恰好能按 Shift-JIS 解成 `ﾗｰゆ`（半角片假名），
于是被判成乱码，还会建议把好文件改成乱码名——有害建议。

真乱码的还原结果一定是**全角日文**；出现半角片假名（U+FF61–U+FF9F）说明原名本来就好。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from galgame_dispatch import demojibake  # noqa: E402


# --------------------------------------------------------- 合法日文名，不该动
@pytest.mark.parametrize(
    "name",
    [
        "装備.rpgmvo",      # 本次修的误报案例（会解成半角片假名 ﾗｰゆ）
        "装備",
        "装甲.png",
        "設定.dat",
        "画像.png",
        "効果音.ogg",
        "音楽",
        "背景",
    ],
)
def test_legal_japanese_name_not_flagged(name: str) -> None:
    """合法的日文文件名必须原样返回 None（不许建议改名）。"""
    assert demojibake(name) is None


# ------------------------------------------------------- 真乱码，必须能还原
@pytest.mark.parametrize(
    "mojibake_name,expected",
    [
        # 教程里那个真实案例：Shift-JIS 名被按 GBK 解读
        ("僼傽僀儖攋懝僠僃僢僋僣乕儖.exe", "ファイル破損チェックツール.exe"),
        ("僒僂儞僪", "サウンド"),
        ("僎乕儉", "ゲーム"),
    ],
)
def test_real_mojibake_is_repaired(mojibake_name: str, expected: str) -> None:
    """真乱码必须还原成全角日文。"""
    assert demojibake(mojibake_name) == expected


# ------------------------------------------------------------ 结构不变式
def test_repaired_result_is_fullwidth_kana_only() -> None:
    """凡是被判定为乱码的，还原结果里不允许出现半角片假名。"""
    candidates = [
        "僼傽僀儖攋懝僠僃僢僋僣乕儖.exe",
        "僒僂儞僪",
        "装備.rpgmvo",
        "設定.dat",
        "画像.png",
    ]
    for name in candidates:
        fixed = demojibake(name)
        if fixed is None:
            continue
        assert not any("\uff61" <= c <= "\uff9f" for c in fixed), (
            f"{name!r} 被判成乱码但还原结果含半角片假名：{fixed!r}"
        )


def test_extension_preserved() -> None:
    """还原后扩展名必须原样保留。"""
    fixed = demojibake("僼傽僀儖攋懝僠僃僢僋僣乕儖.exe")
    assert fixed is not None and fixed.endswith(".exe")


def test_no_dot_name_handled() -> None:
    """没有扩展名的名字也不能崩。"""
    assert demojibake("僒僂儞僪") == "サウンド"
