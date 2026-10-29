#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 RPA 解包产物按资源类型归档到目标目录，并生成清单。

用法:
  python _organize_rpa.py <解包暂存目录> <目标目录> [--move] [--verify-csv <media.csv>]

默认 copy（保留暂存目录，待验收通过后自行删除）；--move 直接搬运。

分类规则（按本作实测的包内布局）:
  images/animations/*.avi  -> Video_AVI
  images/animations/*.webm -> Video_WebM
  其它 images/*            -> Image_*
  sound/music/*            -> Audio_Music
  sound/*                  -> Audio_SFX
  tl/**, *.rpyc/rpyb/...   -> Scripts
  gui/**, cache/**         -> UI
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def classify(rel: str) -> str:
    """按「扩展名优先」分类。

    ⚠️ 教训（2026-10-13 实测踩到）：**不能只按目录判**。
      - `images/animations/` 下除了 .avi/.webm 还有 282 个 jpg（动画缩略图）
      - 视频还散落在 `images/mm/`、`images/notes/`、`tl/chinese/images/animations/`
    所以先用扩展名识别**媒体本体**，再退回按目录分。
    唯一的例外：`tl/` 是本地化补丁树，其内容一律归 Scripts，不拆出去。
    """
    r = rel.replace("\\", "/")
    low = r.lower()
    ext = low.rsplit(".", 1)[-1] if "." in low else ""

    # 本地化补丁树整体保留（里面的图/视频是补丁资源）
    if low.startswith("tl/") or ext in ("rpyc", "rpyb", "rpy", "rpym", "rpymc"):
        return "Scripts"

    # 1) 媒体本体：按扩展名
    if ext == "avi":
        return "Video_AVI"
    if ext == "webm":
        return "Video_WebM"
    if ext == "mp3":
        return "Audio_Music" if low.startswith("sound/music/") else "Audio_SFX"
    if ext in ("ogg", "wav", "opus", "flac", "m4a"):
        return "Audio_SFX"

    # 2) 其余按目录
    if low.startswith("images/"):
        parts = r.split("/")
        return "Image_" + (parts[1] if len(parts) >= 2 and parts[1] else "misc")
    if low.startswith("sound/"):
        return "Audio_SFX"
    if low.startswith(("gui/", "cache/")):
        return "UI"
    return "Other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("dest")
    ap.add_argument("--move", action="store_true")
    a = ap.parse_args()

    stage, dest = Path(a.stage), Path(a.dest)
    files = [p for p in stage.rglob("*") if p.is_file()]
    buckets: dict[str, int] = {}
    op = shutil.move if a.move else shutil.copy2

    for i, p in enumerate(files, 1):
        rel = str(p.relative_to(stage))
        cat = classify(rel)
        sub = rel.replace("\\", "/")
        # 去掉 images/ 前缀，避免 Image_animations/animations/... 这种冗余
        if cat.startswith("Image_") and sub.startswith("images/"):
            sub = sub[len("images/"):]
        target = dest / cat / sub
        target.parent.mkdir(parents=True, exist_ok=True)
        op(str(p), str(target))
        buckets[cat] = buckets.get(cat, 0) + 1
        if i % 1000 == 0:
            print(f"  [{i}/{len(files)}]", flush=True)

    print("\n归档结果:")
    total = 0
    for cat, n in sorted(buckets.items(), key=lambda x: -x[1]):
        d = dest / cat
        mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024 / 1024
        total += n
        print(f"  {cat:<22} {n:>6} 个  {mb:>9.1f} MB")
    print(f"  {'合计':<22} {total:>6} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
