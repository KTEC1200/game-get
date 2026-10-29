#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AdvHD 样本编排：逐 .arc 调 GARbro（先列后提），计数对账；.dat(ASF/WMV) 复制为 .wmv。

用法: python _advhd_run.py <游戏根目录> <输出根目录> --garbro <GARbro.Console.exe>
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# .arc 的列表输出没有表头，每行一个条目：`  size [OFFSET] name`（xp3 有表头，别套用 -1 习惯）
ENTRY_RE = re.compile(r"^\s*\d+ \[[0-9A-Fa-f]+\] ")
SKIP_ARCS: set[str] = set()  # 需要保留的都提


def garbro_entries(exe: str, arc: Path) -> int:
    r = subprocess.run([exe, str(arc)], capture_output=True, timeout=600)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if lines and "unknown format" in lines[0].lower():
        return -1
    n = sum(1 for ln in lines if ENTRY_RE.match(ln))
    if n == 0 and lines:
        # 格式变了就暴露出来，别静默给 0
        print(f"  [警告] {arc.name} 列表无条目行，首行: {lines[0][:60]!r}")
    return n


def garbro_extract(exe: str, arc: Path, dest: Path) -> int:
    n_have = sum(1 for p in dest.rglob("*") if p.is_file()) if dest.exists() else 0
    if n_have > 0:
        return n_have  # 已提取过，只清点
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([exe, "-x", str(arc)], capture_output=True, cwd=str(dest), timeout=3600)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    if "unknown format" in out[:200].lower():
        return -1
    return sum(1 for p in dest.rglob("*") if p.is_file())


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gi = sys.argv.index("--garbro")
    exe = sys.argv[gi + 1]
    root, out_root = Path(args[0]), Path(args[1])

    arcs = sorted(root.glob("*.arc"))
    print(f"发现 {len(arcs)} 个 .arc")

    # 1) .dat = ASF/WMV 视频，直接复制改名
    dat_out = out_root / "Video"
    dat_out.mkdir(parents=True, exist_ok=True)
    dats = sorted(root.glob("*.dat"))
    for d in dats:
        dst = dat_out / (d.stem + ".wmv")
        if not dst.exists():
            shutil.copy2(d, dst)
        print(f"[视频] {d.name} ({d.stat().st_size/1024/1024:.1f}MB) -> Video/{dst.name}")
    print(f"视频复制: {len(dats)} 个\n")

    # 2) .arc 逐包：列条目数 -> 提取 -> 落盘数对账
    bad = []
    for arc in arcs:
        n_idx = garbro_entries(exe, arc)
        dest = out_root / arc.stem
        if arc.stem in SKIP_ARCS:
            print(f"[跳过] {arc.name}")
            continue
        n_out = garbro_extract(exe, arc, dest)
        flag = "OK " if n_idx == n_out else "!! "
        print(f"{flag}{arc.name:<18} 索引 {n_idx:>6}  落盘 {n_out:>6}")
        if n_idx != n_out:
            bad.append(arc.name)
    print()
    if bad:
        print("对账不一致:", bad)
        return 1
    print("全部对账一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
