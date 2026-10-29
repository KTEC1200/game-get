#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PNAP 容器逐帧 carve：从 .pna 中按 PNG 签名→IEND 切出全部帧。

用法: python _pna_carve.py <pna目录或文件> <输出目录>
AdvHD 的 .pna = "PNAP" 头 + 帧索引 + 内嵌若干标准 PNG（GARbro 不认，原样吐出）。
PNG 自定界：8字节签名起始，IEND chunk 结束。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

PNG = b"\x89PNG\r\n\x1a\n"
IEND = b"IEND"


def carve(data: bytes) -> list[bytes]:
    frames = []
    i = data.find(PNG)
    while i >= 0:
        end = data.find(IEND, i)
        if end < 0:
            break
        end += 8  # 'IEND' + CRC(4)
        frames.append(data[i:end])
        i = data.find(PNG, end)
    return frames


def main() -> int:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    files = [src] if src.is_file() else sorted(p for p in src.rglob("*.pna"))
    out.mkdir(parents=True, exist_ok=True)
    total = ok = 0
    for p in files:
        frames = carve(p.read_bytes())
        base = p.stem
        for n, fr in enumerate(frames):
            dst = out / f"{base}__f{n:03d}.png"
            dst.write_bytes(fr)
            total += 1
        print(f"{p.name}: {len(frames)} 帧")
    # 抽验：Pillow 逐个 verify
    from PIL import Image
    for f in sorted(out.glob("*.png")):
        try:
            with Image.open(f) as im:
                im.verify()
            ok += 1
        except Exception as exc:
            print("FAIL", f.name, exc)
    print(f"\ncarve {total} 帧, Pillow verify 通过 {ok}/{total}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
