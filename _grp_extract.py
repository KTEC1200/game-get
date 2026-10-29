#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ExHIBIT .grp 音频库提取（算法照抄 GARbro-Mod ArcFormats/ExHibit/ArcGRP.cs）。

结构：resNNNN.grp 为音频数据；同名 res(NNNN-1).grp 往下找直到 AiFS 文件即是 TOC。
TOC: i32 res_count @0xC；自 0x10 起每块 = { i32 num（或 0x01000000 标志+重读）,
u32 start_index @+4, u32 @+8, u32 count @+0xC } + count×(u32 offset, u32 size)。
size!=0 的对 → res 文件内 offset 处切出 size 字节，命名 {start_index+i:D5}.ogg。

用法: python _grp_extract.py <res目录> <输出目录>
"""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path


def find_toc(res_dir: Path, arc_num: int) -> tuple[Path, int] | None:
    toc_num = arc_num - 1
    arc_index = 1
    while toc_num >= 0:
        toc_name = res_dir / f"res{toc_num:04d}.grp"
        if not toc_name.exists():
            return None
        head = toc_name.read_bytes()[:8]
        if head[:4] == b"AiFS":
            return toc_name, arc_index
        toc_num -= 1
        arc_index += 1
    return None


def main() -> int:
    res_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    arcs = sorted(res_dir.glob("res[0-9]*.grp"))
    total_ok = total_fail = 0
    for arc in arcs:
        name = arc.name
        if name.lower().endswith(".grp") and arc.read_bytes()[:4] == b"AiFS":
            print(f"[TOC] {name}（作为目录使用，不切分）")
            continue
        digits = "".join(ch for ch in name[3:8] if ch.isdigit())
        arc_num = int(digits)
        found = find_toc(res_dir, arc_num)
        if not found:
            print(f"[跳过] {name}: 找不到 AiFS TOC")
            continue
        toc_path, arc_index = found
        toc = toc_path.read_bytes()
        res_count = struct.unpack_from("<i", toc, 0xC)[0]
        if res_count < arc_index:
            print(f"[跳过] {name}: TOC 块数不足 ({res_count} < {arc_index})")
            continue
        io_off = 0x10
        data = arc.read_bytes()
        entries = []
        for _ in range(res_count):
            num = struct.unpack_from("<i", toc, io_off)[0]
            if num == 0x01000000:
                io_off += 4
                num = struct.unpack_from("<i", toc, io_off)[0]
            start_index = struct.unpack_from("<I", toc, io_off + 4)[0]
            count = struct.unpack_from("<I", toc, io_off + 0xC)[0]
            if num == arc_index:
                base = io_off + 0x10
                for i in range(count):
                    offset, size = struct.unpack_from("<II", toc, base + i * 8)
                    if size:
                        entries.append((start_index + i, offset, size))
                break
            io_off += 0x10 + count * 8
        # 切分
        (out_dir / name[:-4]).mkdir(parents=True, exist_ok=True)
        ok = fail = 0
        for idx, offset, size in entries:
            try:
                blob = bytes(data[offset:offset + size])
                if len(blob) != size:
                    raise ValueError("越界")
                if blob[:4] not in (b"OggS", b"RIFF"):
                    raise ValueError(f"头异常 {blob[:4].hex()}")
                (out_dir / name[:-4] / f"{idx:05d}.ogg").write_bytes(blob)
                ok += 1
            except Exception as exc:
                fail += 1
                if fail <= 5:
                    print(f"  FAIL {idx}: {exc}")
        print(f"{name}: {len(entries)} 条（索引 {start_index} 起），落盘 {ok} 失败 {fail}")
        total_ok += ok
        total_fail += fail
    print(f"\n合计 ok {total_ok} fail {total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
