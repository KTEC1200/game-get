#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Unity 数据文件里找视频容器魔数（用 mmap，避免读爆内存）。

用法: python _scan_unity_video.py <文件或目录...>

注意（AGENTS.md 坑 3）：魔数命中不等于真文件。
Unity 的资源的「文件头」集中在 .assets 的开头区域，而 .resS/.resource 是裸数据流，
所以这里对 .resS 的命中只能算「线索」，必须再交叉定位才能定性。
本脚本对命中的偏移额外打印前后 16 字节上下文，便于人工判断。
"""
import mmap
import sys
from pathlib import Path

SIGS = {
    "MP4/ftyp":     b"ftyp",
    "MP4/moov":     b"moov",
    "MP4/mdat":     b"mdat",
    "WebM/MKV":     b"\x1a\x45\xdf\xa3",
    "AVI":          b"RIFF",
    "ASF/WMV":      b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",
    "FLV":          b"FLV\x01",
    "MPEG-PS":      b"\x00\x00\x01\xba",
    "OggS":         b"OggS",
    "UnityFS":      b"UnityFS",
    "CAB-":         b"CAB-",
}
MAX_HITS_PER_SIG = 8


def scan(p: Path) -> None:
    size = p.stat().st_size
    print(f"\n=== {p.name}  ({size:,} bytes / {size/1024/1024:.1f} MB) ===")
    if size == 0:
        print("  (empty)")
        return
    with p.open("rb") as fh:
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            for name, sig in SIGS.items():
                hits = []
                start = 0
                while len(hits) < MAX_HITS_PER_SIG:
                    i = mm.find(sig, start)
                    if i < 0:
                        break
                    hits.append(i)
                    start = i + 1
                if hits:
                    # 统计总数（最多再走一遍到 200 个就够说明问题）
                    n = len(hits)
                    extra = mm.find(sig, start)
                    cnt = f"{n}+" if extra >= 0 else str(n)
                    locs = ", ".join(f"0x{h:08X}" for h in hits[:5])
                    print(f"  {name:<12} count={cnt:<5} first: {locs}")
                    h0 = hits[0]
                    ctx = mm[max(0, h0 - 8):h0 + 16]
                    print(f"      ctx@0x{h0:08X}: {ctx!r}")


def main() -> int:
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.stat().st_size > 0:
                    scan(f)
        else:
            scan(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
