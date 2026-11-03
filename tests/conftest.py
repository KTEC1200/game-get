# -*- coding: utf-8 -*-
"""测试套件的全局约束（目前只有一条：临时目录不许落在仓库盘上）。

背景（2026-11-03 实测）：本机有一个批量删除守卫，pytest 退出清理
`%TEMP%\\pytest-of-<user>\\` 时会抛 BaseException，表现为「测试全绿、退出码 1」；
更坑的是把 `--basetemp` 指到仓库所在盘之后，**测试内部的清理动作**也会被拦住，
直接制造 5 条与代码无关的假失败（unity / krkr 那几条）。

这条 fixture 只在「发现 basetemp 在仓库里」时**发警告**：
  · 不 skip、不 fail —— 那会把真实结果掩盖掉（这比警告危险得多）；
  · 警告会出现在 pytest 的 warnings summary 里，跑的人一眼能看到「这次的结果不可信」。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def warn_if_basetemp_inside_repo(tmp_path: Path) -> None:
    """★C9★ tmp_path 落在仓库根之下时报警（不阻断）。

    检测的是**当前用例的 tmp_path**：pytest 的 basetemp 在仓库里时，每个用例的
    tmp_path 都在仓库里 —— 比去解析 `--basetemp` 参数更可靠（它可能来自环境变量或
    pytest.ini，参数里根本看不到）。
    """
    try:
        tmp_path.resolve().relative_to(REPO_ROOT)
    except (ValueError, OSError):
        return                       # 在仓库外：正常情况，什么都不做
    warnings.warn(
        f"pytest 的 tmp_path 落在仓库内（{tmp_path}）：本机的批量删除守卫会拦住测试内的"
        f"清理动作，可能制造与代码无关的假失败。请用默认 basetemp（系统 temp）重跑。",
        stacklevel=1,
    )
