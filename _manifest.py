#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为解包产物生成清单 manifest.csv（验收用）。

用法: python _manifest.py <解包目录> [--out 路径]
列出 相对路径 / 类型 / 字节数，并按类型汇总。
"""
import csv
import sys
from collections import Counter
from pathlib import Path

CATEGORY = {
    # 原始 .tlg（CG/背景，KiriKiri 专有格式）
    ".tlg": "image/TLG(未转换)",
    # 已转换或原本就是 PNG
    ".png": "image/PNG",
    ".jpg": "image/JPEG", ".jpeg": "image/JPEG",
    ".bmp": "image/BMP", ".webp": "image/WebP",
    # 音频
    ".ogg": "audio/OGG",
    ".wav": "audio/WAV", ".mp3": "audio/MP3", ".opus": "audio/OPUS",
    # 视频
    ".mp4": "video/MP4", ".wmv": "video/WMV", ".avi": "video/AVI",
    ".mkv": "video/MKV", ".webm": "video/WebM", ".mpg": "video/MPEG",
    # 脚本/配置（非目标资源，仅记录）
    ".ks": "script/KS", ".tjs": "script/TJS",
    ".asd": "config/ASD", ".txt": "text", ".dll": "binary/DLL",
}


def main() -> int:
    d = Path(sys.argv[1])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--out" else d / "manifest.csv"
    rows = []
    for p in sorted(d.rglob("*")):
        if not p.is_file() or p.name in ("manifest.csv", "asset_catalog.csv", "README.md", "_garbro.log"):
            continue
        ext = p.suffix.lower()
        rows.append({
            "relpath": str(p.relative_to(d)),
            "category": CATEGORY.get(ext, f"other/{ext.lstrip('.') or 'noext'}"),
            "bytes": p.stat().st_size,
        })
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["relpath", "category", "bytes"])
        w.writeheader()
        w.writerows(rows)

    agg = Counter()
    total = Counter()
    for r in rows:
        agg[r["category"]] += 1
        total[r["category"]] += r["bytes"]
    print(f"清单: {out}")
    print(f"文件总数: {len(rows)}")
    print()
    print(f"{'category':<22}{'count':>8}{'MB':>12}")
    print("-" * 42)
    for cat, n in agg.most_common():
        print(f"{cat:<22}{n:>8}{total[cat]/1024/1024:>12.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
