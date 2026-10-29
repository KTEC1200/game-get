#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描游戏库根目录：顶层目录两级体积清单 + 引擎特征签名，用于挑选下一个解包样本。

用法:
  python _scan_hy_inventory.py <库根目录> <输出.json> [--limit-gb 3]

只读，不改动任何文件。输出 UTF-8 JSON：
  每个顶层目录的总体积 / 文件数 / 直接子目录体积（前 12）/ 封包扩展名计数 /
  *_Data 目录 / exe 样例，以及根目录下的散文件清单。
引擎特征只作粗判（.xp3=KiriKiri、.rpa=Ren'Py、.asar=Tyrano/Electron、*_Data=Unity），
正式判定用 galgame_dispatch.py。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ARCH_EXTS = (".xp3", ".rpa", ".asar", ".bundle")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--limit-gb", type=float, default=3.0)
    a = ap.parse_args()
    root = Path(a.root)
    limit = int(a.limit_gb * 1024 ** 3)

    loose = []
    result = []
    for p in sorted(root.iterdir()):
        if p.is_file():
            try:
                loose.append({"name": p.name, "gb": round(p.stat().st_size / 1024 ** 3, 3)})
            except OSError:
                pass
            continue
        if not p.is_dir():
            continue

        total = 0
        count = 0
        kids: dict[str, list[int]] = {}
        ext_count: dict[str, int] = {}
        data_dirs: list[str] = []
        exes: list[str] = []
        for dp, dn, fn in os.walk(p):
            rel = os.path.relpath(dp, p)
            first = None if rel == "." else rel.split(os.sep)[0]
            for d in dn:
                if d.endswith("_Data"):
                    data_dirs.append(os.path.relpath(os.path.join(dp, d), p))
            for f in fn:
                fp = os.path.join(dp, f)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                total += sz
                count += 1
                if first:
                    k = kids.setdefault(first, [0, 0])
                    k[0] += sz
                    k[1] += 1
                low = f.lower()
                for e in ARCH_EXTS:
                    if low.endswith(e):
                        ext_count[e] = ext_count.get(e, 0) + 1
                        break
                else:
                    if low.endswith((".rpyc", ".rpyb")):
                        ext_count[".rpyc"] = ext_count.get(".rpyc", 0) + 1
                if low.endswith(".exe") and len(exes) < 6:
                    exes.append(os.path.relpath(fp, p))

        result.append({
            "path": str(top_path := p),
            "name": p.name,
            "bytes": total,
            "gb": round(total / 1024 ** 3, 3),
            "files": count,
            "under_limit": total < limit,
            "children": [
                {"name": k, "gb": round(v[0] / 1024 ** 3, 3), "files": v[1]}
                for k, v in sorted(kids.items(), key=lambda x: -x[1][0])[:12]
            ],
            "archives": ext_count,
            "unity_data_dirs": data_dirs[:5],
            "exes": exes,
        })
        print(f"scanned: {p.name}  {count} files  {total / 1024 ** 3:.2f} GB", file=sys.stderr)

    out = {"root": str(root), "limit_gb": a.limit_gb, "loose_files": loose, "dirs": result}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
