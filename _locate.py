#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 GARbro 的条目列表(offset -> name) 与魔数命中偏移做交叉定位。

用法:
  python _locate.py <归档> <garbro列表文件>

GARbro.Console 无选项时的输出行形如:
      776 [0FDB77C2] others/button_checkbox.png
其中 [........] 是 8 位十六进制偏移。

本脚本读该列表，建立 偏移->名字 的有序表，然后对给定的一批魔数偏移，
报告每个偏移落在哪个条目内（以及相对条目的偏移）。
"""
import re
import sys
from pathlib import Path

LINE_RE = re.compile(r"^\s*(\d+)\s+\[([0-9A-Fa-f]{8})\]\s+(.+?)\s*$")


def main() -> int:
    arch = Path(sys.argv[1])
    listing = Path(sys.argv[2])
    entries = []  # (offset, size, name)
    for ln in listing.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(ln)
        if not m:
            continue
        size = int(m.group(1))
        off = int(m.group(2), 16)
        entries.append((off, size, m.group(3)))
    entries.sort()
    offs = [e[0] for e in entries]
    print(f"归档: {arch}  ({arch.stat().st_size:,} bytes)")
    print(f"条目: {len(entries)}")
    print()

    import bisect
    # 要查的魔数偏移
    probes = {
        "FLV":       [0x0D1447ED],
        "MPEG-PS":   [0x02483BE5, 0x09D63E8F, 0x0A5BFA08, 0x0A65FB3F, 0x0A701C9B],
        "JPEG":      [0x02295957, 0x022A43A4, 0x02381213, 0x0238BCD8, 0x02396778],
        "OGG":       [0x0222B978],
        "PNG":       [0x03C5E186],
    }
    print(f"{'probe':<10}{'offset':>12}   {'container entry':<46}{'offset-in-entry'}")
    print("-" * 96)
    for tag, plist in probes.items():
        for p in plist:
            i = bisect.bisect_right(offs, p) - 1
            if i < 0:
                print(f"{tag:<10}0x{p:08X}   <before first entry>")
                continue
            o, sz, nm = entries[i]
            delta = p - o
            inside = "OK" if delta < sz else "OUTSIDE"
            print(f"{tag:<10}0x{p:08X}   {nm[:44]:<46}{delta} (size={sz}, {inside})")
        print()

    # JPEG/MPEG-PS 命中是否真的落在 .ogg 里？统计
    print("---- 所有 JPEG 命中所在条目类型 (重新全扫) ----")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
