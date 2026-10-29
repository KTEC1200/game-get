#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Pillow 逐个 verify() + 读尺寸，校验图片是否真能打开。

用法: python _verify_images.py <目录>
用于决策树 §6 验收判据 2「图片能被看图器/Pillow 打开」。
"""
import sys
from collections import Counter
from pathlib import Path

from PIL import Image


def main() -> int:
    d = Path(sys.argv[1])
    files = sorted(p for p in d.rglob("*")
                   if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"))
    ok = bad = 0
    fails = []
    sizes = Counter()
    dims = Counter()
    tiny = []
    for i, p in enumerate(files, 1):
        try:
            with Image.open(p) as im:
                im.verify()          # 校验完整性
            with Image.open(p) as im:  # verify() 后需重开才能读属性
                w, h = im.size
                fmt, mode = im.format, im.mode
            ok += 1
            sizes[fmt] += 1
            dims[f"{w}x{h}"] += 1
            if w < 16 or h < 16:
                tiny.append(f"{p.name} ({w}x{h})")
        except Exception as exc:
            bad += 1
            fails.append(f"{p.relative_to(d)} :: {type(exc).__name__}: {exc}")
        if i % 200 == 0:
            print(f"  [{i}/{len(files)}] ok={ok} bad={bad}", flush=True)
    print()
    print("=" * 60)
    print(f"目录: {d}")
    print(f"图片: {len(files)}  可打开: {ok}  失败: {bad}")
    print(f"格式分布: {dict(sizes)}")
    print("尺寸分布 (top 10):")
    for k, v in dims.most_common(10):
        print(f"    {k:<14} {v}")
    if tiny:
        print(f"异常小图 ({len(tiny)}): {tiny[:5]}")
    if fails:
        print("失败清单(前 30):")
        for f in fails[:30]:
            print("  " + f)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
