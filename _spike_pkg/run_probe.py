#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结探针驱动：解析样本路径（CJK 不进命令行）+ 跑冻结/未冻结两组对照。用完即弃。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FROZEN = REPO / "_spike_pkg" / "dist" / "probe" / "probe.exe"
UNFROZEN = [sys.executable, str(REPO / "_spike_pkg" / "probe.py")]


def make_wav() -> str:
    p = Path(tempfile.gettempdir()) / "_spike_probe.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 1600)
    return str(p)


def pick_archive() -> str:
    sys.path.insert(0, str(REPO))
    import build_cases as bc
    for _name, s in bc.SAMPLES.items():
        gid = s["game_dir"]
        d = Path(gid)
        if not d.exists():
            continue
        for ext in (".xp3", ".ypf", ".int"):
            hits = sorted(d.rglob(f"*{ext}"))
            if hits:
                return str(hits[0])
    return ""


def pick_game() -> str:
    sys.path.insert(0, str(REPO))
    import build_cases as bc
    for _name, s in bc.SAMPLES.items():
        gid = s["game_dir"]
        d = Path(gid)
        if d.exists():
            return str(d)
    return ""


def run(label: str, argv: list[str]) -> None:
    print(f"\n{'#' * 70}\n# {label}\n# {' '.join(argv[:2])}\n{'#' * 70}", flush=True)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=180, encoding="utf-8",
                           errors="replace")
        print(r.stdout)
        if r.stderr.strip():
            print(f"[stderr] {r.stderr.strip()[:800]}")
        print(f"[rc={r.returncode}]")
    except Exception as exc:  # noqa: BLE001
        print(f"[EXC] {type(exc).__name__}: {exc}")


def main() -> int:
    wav = make_wav()
    archive = pick_archive()
    game = pick_game()
    print(json.dumps({"frozen": str(FROZEN), "frozen_exists": FROZEN.exists(),
                      "wav": wav, "archive": archive, "game": game},
                     ensure_ascii=False, indent=2))

    if FROZEN.exists():
        run("冻结 selftest", [str(FROZEN), "selftest"])
        run("冻结 deps", [str(FROZEN), "deps"])
        run("冻结 external", [str(FROZEN), "external", wav, archive])
        run("冻结 detect", [str(FROZEN), "detect", game, str(REPO / "cases")])

    run("未冻结 selftest（对照）", [*UNFROZEN, "selftest"])
    run("未冻结 external（对照）", [*UNFROZEN, "external", wav, archive])
    run("未冻结 detect（对照）", [*UNFROZEN, "detect", game, str(REPO / "cases")])

    du = 0
    if FROZEN.parent.exists():
        for p in FROZEN.parent.rglob("*"):
            if p.is_file():
                du += p.stat().st_size
        print(f"\n冻结包体积: {du/1024/1024:.1f} MiB  ({len(list(FROZEN.parent.rglob('*')))} 个路径)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
