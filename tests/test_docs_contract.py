# -*- coding: utf-8 -*-
"""README 与代码的**契约**测试（批次 C13，2026-11-03）。

只锁一件事：README「支持的引擎」表格里列出的引擎名集合，必须等于
`orchestrator.IMPLEMENTED` 加上「判得出但无链路」的那个（Tyrano/Electron）。

为什么只锁这一条：这是唯一一条**用户会照着做决定**的事实（「我的游戏能解吗」）。
测试数量、文件行数这类数字天天变，锁它们只会制造无谓维护；
而「文档说支持 X，代码里根本没链路」是纯粹的错误信息。

解析方式刻意保持笨拙（只认 Markdown 表格第一列 + 反引号里的名字）：
宁可解析失败时给出明白的错误，也不要写一个「聪明的」解析器 —— 那玩意儿坏了没人知道。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402

README = ROOT / "README.md"

#: README 里额外提到的、**判得出但没链路**的引擎（与 run() 的退出码 2 对应）。
NO_CHAIN_ENGINES = {"Tyrano/Electron"}

#: README 表格里的名字与本代码里的名字不完全一致时的映射（文档给人看，代码给机器看）。
#: 只允许「同一件事的两种写法」，不许把没实现的写成实现的。
README_TO_CODE = {
    "Ren'Py": "Ren'Py",
    "KiriKiri": "KiriKiri",
    "RPG Maker MV/MZ": "RPG Maker",
    "Yu-Ris": "Yu-Ris",
    "AdvHD": "AdvHD",
    "ExHIBIT/Retouch": "ExHIBIT",
    "CatSystem2": "CatSystem2",
    "Unity": "Unity",
    "Artemis (iMel)": "Artemis",
}


def _engine_section() -> str:
    """截出「支持的引擎」那一节（到下一个二级标题为止）。"""
    text = README.read_text(encoding="utf-8")
    m = re.search(r"^##\s*支持的引擎.*?$(.*?)(?=^##\s)", text, re.S | re.M)
    assert m, "README 里找不到「## 支持的引擎」一节（改标题要同步改这个测试）"
    return m.group(1)


def _table_engine_names() -> list[str]:
    """表格第一列的名字（`| 名字 | 特征 | 方式 |` 的行；跳过表头与分隔行）。"""
    names: list[str] = []
    for line in _engine_section().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("-: "):
            continue                                   # 分隔行
        if cells[0] in ("引擎", "Engine"):
            continue                                   # 表头
        names.append(cells[0])
    return names


def test_readme_engine_table_matches_implemented():
    """★C13★ 文档里列的引擎 == 代码里真正实现的引擎（多一个少一个都算错）。"""
    documented = set(_table_engine_names())
    assert documented, "README 引擎表格解析出 0 行（表格结构变了？）"

    unknown = documented - set(README_TO_CODE)
    assert not unknown, f"README 里有未登记的引擎写法：{sorted(unknown)}（见 README_TO_CODE）"

    code_side = {README_TO_CODE[n] for n in documented}
    assert code_side == set(orch.IMPLEMENTED), (
        f"文档与代码不一致：文档多出 {sorted(code_side - set(orch.IMPLEMENTED))}，"
        f"代码多出 {sorted(set(orch.IMPLEMENTED) - code_side)}")


def test_readme_mentions_every_no_chain_engine():
    """「判得出但没链路」的引擎也必须被文档点名（否则用户会以为漏了）。"""
    text = README.read_text(encoding="utf-8")
    for engine in NO_CHAIN_ENGINES:
        assert engine in text, f"README 没提到「{engine}」——用户会以为它不被支持"


def test_readme_no_chain_engines_are_not_implemented():
    """反向保护：写进「无链路」集合的引擎不许悄悄出现在 IMPLEMENTED 里。"""
    assert not (NO_CHAIN_ENGINES & set(orch.IMPLEMENTED)), \
        "有引擎同时被标成「已实现」和「无链路」，两者只能取其一"
