#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Electron asar 归档解析器（asar v1 格式），纯标准库。

格式（全部小端 uint32）:
    [0] = 4                    （Pickle 尺寸字段自身的长度，恒为 4）
    [1] = header_size          （头 pickle 总长 = JSON + 对齐填充）
    [2] = header_object_size   （= header_size - 4）
    [3] = header_string_size   （JSON 字节长）
    [16 : 16+header_string_size] = JSON 索引
    文件数据从 8 + header_size 开始；条目的 offset 是相对该起点的**十进制字符串**。
    目录节点含 "files"；"unpacked": true 的文件不在 asar 里，在 <同名>.unpacked/ 旁路目录。

用法:
  python asar_tool.py info    <app.asar>
  python asar_tool.py list    <app.asar> [-o out.txt]
  python asar_tool.py extract <app.asar> <输出目录> [--only 正则] [--flat]
                             [--unpacked <app.asar.unpacked 目录，缺省取同目录>]

只读源文件；不改动归档。
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def parse_header(fh) -> tuple[int, int, dict]:
    """返回 (data_start, json_bytes, index)。data_start = 8 + header_size。"""
    pre = fh.read(16)
    if len(pre) < 16:
        raise ValueError(f"文件太小，不是 asar（{len(pre)} 字节）")
    a, header_size, obj_size, str_size = struct.unpack("<4I", pre)
    if a != 4:
        raise ValueError(f"首 uint32 = {a}（应为 4），不是 asar")
    raw = fh.read(str_size)
    index = json.loads(raw.decode("utf-8"))
    return 8 + header_size, raw, index


def iter_entries(index: dict):
    """摊平成 (路径, 信息)。信息为 dict：文件含 size/offset/unpacked，目录含 files。"""
    stack = [("", index)]
    while stack:
        prefix, node = stack.pop()
        for name, info in node.get("files", {}).items():
            rel = f"{prefix}/{name}" if prefix else name
            if "files" in info:
                stack.append((rel, info))
            else:
                yield rel, info


def cmd_info(a) -> int:
    p = Path(a.archive)
    with p.open("rb") as fh:
        data_start, raw, index = parse_header(fh)
    files = [(rel, i) for rel, i in iter_entries(index) if "offset" in i or i.get("unpacked")]
    dirs = sum(1 for _, i in iter_entries(index) if "files" in i)
    unpacked = sum(1 for _, i in files if i.get("unpacked"))
    total = sum(int(i.get("size", 0)) for _, i in files)
    print(f"归档: {p}")
    print(f"  文件大小: {p.stat().st_size:,} 字节 ({p.stat().st_size/1024/1024:.1f} MB)")
    print(f"  索引 JSON: {len(raw):,} 字节   数据区起点: 0x{data_start:X}")
    print(f"  条目: {len(files)} 个文件 / {dirs} 个目录（其中 {unpacked} 个 unpacked 旁路）")
    print(f"  内含文件合计: {total:,} 字节 ({total/1024/1024:.1f} MB)")
    return 0


def cmd_list(a) -> int:
    p = Path(a.archive)
    with p.open("rb") as fh:
        _, _, index = parse_header(fh)
    rows = []
    for rel, i in iter_entries(index):
        if "files" in i:
            continue
        mark = " [unpacked]" if i.get("unpacked") else ""
        rows.append(f"{int(i.get('size', 0)):>12}  {rel}{mark}")
    rows.sort(key=lambda r: r.split("  ", 1)[1])
    if a.out:
        Path(a.out).write_text("\n".join(rows), encoding="utf-8")
        print(f"条目清单写入: {a.out}  ({len(rows)} 行)")
    else:
        for r in rows[:60]:
            print(r)
        if len(rows) > 60:
            print(f"... 共 {len(rows)} 条")
    return 0


def cmd_extract(a) -> int:
    src = Path(a.archive)
    dest = Path(a.outdir)
    unpacked_dir = Path(a.unpacked) if a.unpacked else src.with_name(src.name + ".unpacked")
    pat = re.compile(a.only) if a.only else None
    with src.open("rb") as fh:
        data_start, _, index = parse_header(fh)
        ents = [(rel, i) for rel, i in iter_entries(index) if "files" not in i]
        if pat:
            ents = [(r, i) for r, i in ents if pat.search(r)]
        dest.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        done = err = skipped = 0
        written = 0
        total = len(ents)
        for n, (rel, info) in enumerate(ents, 1):
            target = dest / (rel.replace("/", os.sep) if not a.flat
                             else re.sub(r"[/\\]", "_", rel))
            try:
                if info.get("unpacked"):
                    side = unpacked_dir / rel.replace("/", os.sep)
                    if side.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(side, target)
                        done += 1
                        written += side.stat().st_size
                    else:
                        skipped += 1
                    continue
                size = int(info["size"])
                off = data_start + int(info["offset"])
                target.parent.mkdir(parents=True, exist_ok=True)
                fh.seek(off)
                remain = size
                with target.open("wb") as out:
                    while remain > 0:
                        chunk = fh.read(min(1 << 22, remain))
                        if not chunk:
                            raise IOError(f"数据提前结束（{rel} 还差 {remain} 字节）")
                        out.write(chunk)
                        remain -= len(chunk)
                        written += len(chunk)
                done += 1
            except Exception as exc:
                err += 1
                print(f"  [失败] {rel}: {type(exc).__name__}: {exc}", file=sys.stderr)
            if n % 500 == 0 or n == total:
                el = time.time() - t0
                print(f"  [{n}/{total}] ok={done} err={err} skip={skipped}  "
                      f"{written/1024/1024:.1f} MB  {el:.0f}s", flush=True)
    print(f"\n解包完成: {done} 个文件, {err} 个失败, {skipped} 个旁路缺失, "
          f"{written/1024/1024:.1f} MB -> {dest}")
    return 0 if err == 0 else 1


import os
import shutil

def main() -> int:
    ap = argparse.ArgumentParser(description="Electron asar 归档工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("info"); p1.add_argument("archive"); p1.set_defaults(f=cmd_info)
    p2 = sub.add_parser("list")
    p2.add_argument("archive"); p2.add_argument("-o", "--out"); p2.set_defaults(f=cmd_list)
    p3 = sub.add_parser("extract")
    p3.add_argument("archive"); p3.add_argument("outdir")
    p3.add_argument("--only", help="只解名字匹配该正则的条目")
    p3.add_argument("--flat", action="store_true", help="平铺输出（把 / 换成 _）")
    p3.add_argument("--unpacked", help="app.asar.unpacked 旁路目录（缺省取归档同目录）")
    p3.set_defaults(f=cmd_extract)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
