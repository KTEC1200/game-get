#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按魔数扫描归档，判断里面到底有没有视频/其它容器。

用法: python _scan_video.py <归档文件>
只读，不改动原文件。输出各魔数的命中次数与前若干个偏移。
"""
import sys
from pathlib import Path

SIGS = {
    "MP4/ftyp":      b"ftyp",
    "MPEG-PS":       b"\x00\x00\x01\xba",
    "MPEG-TS":       b"\x47",
    "Matroska/webm": b"\x1a\x45\xdf\xa3",
    "AVI/RIFF":      b"RIFF",
    "WMV/ASF":       b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",
    "FLV":           b"FLV\x01",
    "OGG":           b"OggS",
    "PNG":           b"\x89PNG\r\n\x1a\n",
    "JPEG":          b"\xff\xd8\xff",
    "TLG0":          b"TLG0.0\x00",
    "TLG5":          b"TLG5.0\x00",
    "TLG6":          b"TLG6.0\x00",
    "PSB":           b"PSB\x00",
    "XP3":           b"XP3\r\n \n\x1a\x8bg\x01",
}
CHUNK = 16 * 1024 * 1024
OVERLAP = 64


def main() -> int:
    p = Path(sys.argv[1])
    size = p.stat().st_size
    counts = {k: 0 for k in SIGS}
    firsts = {k: [] for k in SIGS}
    off = 0
    tail = b""
    with p.open("rb") as fh:
        while True:
            buf = fh.read(CHUNK)
            if not buf:
                break
            data = tail + buf
            base = off - len(tail)
            for name, sig in SIGS.items():
                start = 0
                while True:
                    i = data.find(sig, start)
                    if i < 0:
                        break
                    counts[name] += 1
                    if len(firsts[name]) < 5:
                        firsts[name].append(base + i)
                    start = i + 1
            tail = data[-OVERLAP:]
            off += len(buf)
    print(f"file: {p}")
    print(f"size: {size:,} bytes ({size/1024/1024:.1f} MB)")
    print()
    print(f"{'signature':<16}{'count':>10}   first offsets")
    print("-" * 62)
    for name in SIGS:
        c = counts[name]
        if c:
            fs = ", ".join(f"0x{x:08X}" for x in firsts[name])
            print(f"{name:<16}{c:>10}   {fs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
