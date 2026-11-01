#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结构建：把 orchestrator 冻成 onedir exe（软件化阶段 3，verified-findings §19.2 第 2 条）。

数据文件清单 —— **唯一出处**。新增任何「代码要读的数据文件」时同步改这里
（与 `manifest.CONVERTIBLE` 同理：清单只写一份，漏一个不是降级而是**启动即崩**）：
  rules/                          engines.json（引擎指纹规则表，rules/__init__.py 按 __file__ 定位）
  cases/                          案例库（index.json + case JSON，case_lib.DEFAULT_CASES_DIR 按 __file__ 定位）
  _gyu_tool.cs / _hg3_tool.cs     自带 C# 解码器源码（exe 不入库，首用 csc 现编，编出的 exe 落源码旁）
  _uia_item_rect.ps1              krkr GUI 链路的 UIA 矩形辅助脚本（krkr_auto_extract 按 __file__ 调）
  toolbridge.json（若存在）        工具路径覆盖配置（可选；缺失时走内置候选 + PATH）

不需要 --hidden-import：orchestrator 对 7 条链路的兄弟模块全部**顶部静态 import**
（tests/test_orchestrator.py §8.5 护栏锁着），PyInstaller 静态分析跟得全。
不进包的：asar_tool / _advhd_run / _spite_* 等（orchestrator 链路够不着的独立脚本，
进包只会变大；§19.1 的「14/14 可 import」是探针口径，不是产品口径）。

环境：Python 3.14.6 + PyInstaller 6.22.3 实测可冻（§19.1）。
教训（§19.3）：--add-data 的相对路径相对 **spec 目录**解析（不是 cwd）——这里一律传绝对路径。

用法：
  python build_exe.py            # 构建 → _spike_pkg/dist/orchestrator/orchestrator.exe
  python build_exe.py --check    # 只校验清单文件是否齐全，不构建
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DIST = REPO / "_spike_pkg" / "dist"
BUILD = REPO / "_spike_pkg" / "build"
SPEC = REPO / "_spike_pkg"
EXE = DIST / "orchestrator" / "orchestrator.exe"

#: (源相对路径, 包内目标目录)。目标目录 "." = _internal 根（与仓库根布局镜像，
#: 各模块的 `Path(__file__).parent` 定位才能命中）。
DATA_FILES: list[tuple[str, str]] = [
    ("rules", "rules"),
    ("cases", "cases"),
    ("_gyu_tool.cs", "."),
    ("_hg3_tool.cs", "."),
    ("_uia_item_rect.ps1", "."),
]


def data_args() -> tuple[list[str], list[str]]:
    """返回 (--add-data 参数列表, 缺失文件列表)。toolbridge.json 可选，缺了不算错。"""
    args: list[str] = []
    missing: list[str] = []
    for src, dst in DATA_FILES:
        p = REPO / src
        if not p.exists():
            missing.append(src)
            continue
        args += ["--add-data", f"{p};{dst}"]
    opt = REPO / "toolbridge.json"
    if opt.exists():
        args += ["--add-data", f"{opt};."]
    return args, missing


def check() -> int:
    args, missing = data_args()
    for a in DATA_FILES:
        mark = "OK " if (REPO / a[0]).exists() else "MISS"
        print(f"[{mark}] {a[0]} -> _internal/{a[1] if a[1] != '.' else ''}")
    if (REPO / "toolbridge.json").exists():
        print("[OK ] toolbridge.json（可选）")
    else:
        print("[opt] toolbridge.json 不存在（可选，缺失走内置候选 + PATH）")
    if missing:
        print("\n缺失：", ", ".join(missing), file=sys.stderr)
        return 1
    print(f"\n清单齐全，--add-data 共 {args.count('--add-data')} 项")
    return 0


def build() -> int:
    args, missing = data_args()
    if missing:
        print("数据文件缺失，先补齐再构建：", ", ".join(missing), file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onedir", "--name", "orchestrator",
           "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(SPEC),
           *args, str(REPO / "orchestrator.py")]
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"PyInstaller 失败 rc={r.returncode}", file=sys.stderr)
        return r.returncode
    n = sum(1 for p in DIST.joinpath("orchestrator").rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in DIST.joinpath("orchestrator").rglob("*") if p.is_file())
    print(f"\n产物：{EXE}\n  {n} 个文件，{size / 1024 / 1024:.1f} MiB")
    print("冒烟：", f'"{EXE}" <游戏目录> --out <输出目录> --dry-run')
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只校验清单，不构建")
    a = ap.parse_args(argv)
    return check() if a.check else build()


if __name__ == "__main__":
    sys.exit(main())
