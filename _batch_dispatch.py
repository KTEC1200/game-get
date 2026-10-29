#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量判定：对 <3GB 待解清单逐个跑 galgame_dispatch.scan（含 GARbro 实调），输出 UTF-8 JSON。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import galgame_dispatch as gd  # noqa: E402

HY = Path("D:/HY")
GARbro = r"D:\K\galgame\GARbro\GARbro.Console.exe"
OUT = Path(__file__).parent / "_extracted"
LIMIT = 3 * 1024 ** 3

DONE = {"SPITE", "My Wife Wants to Be a Professional Cosplayer", "最佳的交易", "兼职人妻"}
# meikura 与 tm 的本体在子目录，直接对子目录判定
SUBDIR_TARGETS = [
    HY / "meikura" / "meikuraS",
    HY / "meikura" / "Maid for Loving You",
    HY / "tm" / "ラブラブお痴験バイト性活",
]


def dir_size(p: Path) -> int:
    total = 0
    for dp, _dn, fn in os.walk(p):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def main() -> int:
    targets: list[Path] = []
    for top in sorted(HY.iterdir()):
        if not top.is_dir() or top.name in DONE:
            continue
        if top.name == "pork社":
            for child in sorted(top.iterdir()):
                if child.is_dir() and child.name not in DONE and dir_size(child) < LIMIT:
                    targets.append(child)
            continue
        if top.name in ("meikura", "tm"):
            continue
        if dir_size(top) < LIMIT:
            targets.append(top)
    targets.extend(SUBDIR_TARGETS)

    report = []
    for t in targets:
        size = dir_size(t)
        rep = gd.scan(t, garbro_exe=GARbro)
        best = rep.best
        entry = {
            "path": str(t),
            "gb": round(size / 1024 ** 3, 3),
            "engine": best.engine if best else None,
            "score": best.score if best else 0,
            "facts": {k: v for k, v in rep.facts.items() if k != "unity_big_files"},
            "notes": rep.notes,
            "garbro": rep.facts.get("garbro_probes"),
        }
        report.append(entry)
        print(f"{t.name}: {entry['engine']} ({entry['score']})", file=sys.stderr)

    out = Path(__file__).parent / "_extracted" / "_batch_dispatch.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
