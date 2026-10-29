#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量提取驱动 A：KiriKiri（GARbro.Console -x）+ Ren'Py（rpa_tool extract）。
输出到 _extracted/<游戏名>/<包名>/，逐包对账条目数 vs 落盘文件数。UTF-8 JSON 报告。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

HY = Path("D:/HY")
OUT = Path(__file__).parent / "_extracted"
GARbro = r"D:\K\galgame\GARbro\GARbro.Console.exe"

KRKR = [
    HY / "pork社" / "温泉蒸汽人妻",
    HY / "pork社" / "高慢妻陥落！！",
    HY / "pork社" / "昼下がりの団地妻たち ～熟れた匂いとムレた肌～",
    HY / "pork社" / "昼下がり、欲求不満な人妻たちは… 〜牝堕ち・危険日種付け・交尾狂い〜",
    HY / "pork社" / "堕落妻子",
    HY / "教师催眠1",
    HY / "教师催眠2",
]
RENPY_RPA = [
    HY / "Swipe Right for Sugar Mama Sensei",
    HY / "催眠性指導 -Secret Lesson-",
]


def garbro_entries(xp3: Path) -> int | None:
    try:
        r = subprocess.run([GARbro, str(xp3)], capture_output=True, timeout=600)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
    except Exception:
        return None
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if lines and "unknown format" in lines[0].lower():
        return None
    return max(0, len(lines) - 1)


def safe_name(rel: str) -> str:
    s = re.sub(r"[/\\]+", "_", rel)
    return re.sub(r'[<>:"|?*]', "_", s).strip("._ ") or "root"


def run_krkr() -> list[dict]:
    results = []
    for game in KRKR:
        gout = OUT / game.name
        gout.mkdir(parents=True, exist_ok=True)
        for xp3 in sorted(game.rglob("*.xp3")):
            rel = xp3.relative_to(game)
            sub = gout / safe_name(str(rel.with_suffix("")))
            sub.mkdir(parents=True, exist_ok=True)
            n_before = sum(1 for _ in sub.rglob("*") if _.is_file())
            t0 = time.time()
            try:
                r = subprocess.run([GARbro, "-x", str(xp3)], cwd=str(sub),
                                   capture_output=True, timeout=1800)
                code = r.returncode
            except Exception as exc:
                code = f"EXC:{type(exc).__name__}"
            el = time.time() - t0
            n_after = sum(1 for _ in sub.rglob("*") if _.is_file())
            entries = garbro_entries(xp3)
            results.append({
                "game": game.name, "archive": str(rel), "mb": round(xp3.stat().st_size / 1048576, 1),
                "listed_entries": entries, "files_new": n_after - n_before,
                "files_total_in_dir": n_after, "exit": code, "sec": round(el, 1),
            })
            print(f"  {game.name} / {rel}: entries={entries} new={n_after - n_before} "
                  f"exit={code} {el:.0f}s", file=sys.stderr)
    return results


def run_renpy() -> list[dict]:
    results = []
    for game in RENPY_RPA:
        gout = OUT / game.name
        gout.mkdir(parents=True, exist_ok=True)
        for rpa in sorted(game.rglob("*.rpa")):
            rel = rpa.relative_to(game)
            sub = gout / safe_name(str(rel.with_suffix("")))
            if sub.exists():
                shutil.rmtree(sub)
            sub.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            r = subprocess.run([sys.executable, str(Path(__file__).parent / "rpa_tool.py"),
                                "extract", str(rpa), str(sub)],
                               capture_output=True, timeout=1800)
            el = time.time() - t0
            n_files = sum(1 for _ in sub.rglob("*") if _.is_file())
            tail = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
            results.append({
                "game": game.name, "archive": str(rel),
                "mb": round(rpa.stat().st_size / 1048576, 1),
                "files": n_files, "exit": r.returncode, "sec": round(el, 1),
                "tail": tail[-1] if tail else "",
            })
            print(f"  {game.name} / {rel}: files={n_files} exit={r.returncode} {el:.0f}s",
                  file=sys.stderr)
    return results


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    krkr = run_krkr()
    renpy = run_renpy()
    out = OUT / "_batch_A_extract.json"
    out.write_text(json.dumps({"krkr": krkr, "renpy": renpy}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"written: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
