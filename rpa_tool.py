#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ren'Py RPA 归档解析器（RPA-2.0 / RPA-3.0），纯标准库。

RPA 格式（RPA-3.0）:
    b"RPA-3.0 " + b"%016x" % index_offset + b" " + b"%08x" % key + b"\n"
索引位于文件末尾 index_offset 处，是一个 pickle 字典:
    { "path/in/archive": [ (offset, length, prefix), ... ], ... }
每个文件的真实数据 = prefix + 文件本身（prefix 是解密用的头部字节）。
offset / length 都要与 key 异或。

用法:
  python rpa_tool.py list   <archive.rpa> [-o out.txt]
  python rpa_tool.py extract <archive.rpa> <输出目录> [--only 正则] [--flat]
  python rpa_tool.py info   <archive.rpa>

只读源文件；不改动归档。
"""
from __future__ import annotations

import argparse
import pickle
import re
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


def parse_header(fh) -> tuple[int, int, int]:
    """返回 (header_len, index_offset, key)。"""
    head = fh.read(64)
    if head.startswith(b"RPA-3.0 "):
        # RPA-3.0 <16位hex index_offset> <8位hex key>
        parts = head.split(b"\n", 1)[0].split(b" ")
        return 3, int(parts[1], 16), int(parts[2], 16)
    if head.startswith(b"RPA-2.0 "):
        parts = head.split(b"\n", 1)[0].split(b" ")
        return 2, int(parts[1], 16), 0
    raise ValueError(f"不是 RPA 归档（头部: {head[:16]!r}）")


def load_index(path: Path):
    """读索引，返回 {name: [(offset, length, prefix), ...]} 与元信息。

    注意: 现代 Ren'Py 会把 pickle 索引再用 **zlib 压缩**（头 `78 9C`）后放在文件末尾，
    所以要先 zlib.decompress 再 pickle.loads。
    """
    with path.open("rb") as fh:
        ver, index_off, key = parse_header(fh)
        fh.seek(index_off)
        raw = fh.read()
    # 索引可能是 zlib 压缩的
    if raw[:1] == b"\x78":  # zlib magic (0x78 0x01/0x9C/0xDA)
        try:
            import zlib
            raw = zlib.decompress(raw)
        except Exception as exc:
            print(f"[警告] zlib 解压索引失败: {exc}", file=sys.stderr)
    import io
    up = pickle.Unpickler(io.BytesIO(raw))
    try:
        index = up.load()
    except Exception:
        # 退化：截到最后一个 '.' 再试
        cut = raw.rfind(b".")
        index = pickle.loads(raw[: cut + 1])
    if not isinstance(index, dict):
        raise ValueError(f"索引不是 dict，而是 {type(index)}")
    return index, ver, index_off, key


def iter_entries(index: dict, key: int):
    """把索引摊平成 (name, offset, length)。RPA 里同一路径可能有多段（prefix）。"""
    for name, parts in index.items():
        if not isinstance(parts, (list, tuple)):
            continue
        for item in parts:
            off, ln = item[0], item[1]
            if key:
                off ^= key
                ln ^= key
            yield name, off, ln


def cmd_info(a) -> int:
    p = Path(a.archive)
    index, ver, off, key = load_index(p)
    ents = list(iter_entries(index, key))
    total = sum(e[2] for e in ents)
    print(f"归档: {p}")
    print(f"  格式: RPA-{ver}.0   索引偏移: 0x{off:X}   异或 key: 0x{key:08X}")
    print(f"  文件大小: {p.stat().st_size:,} 字节 ({p.stat().st_size/1024/1024:.1f} MB)")
    print(f"  条目: {len(index)} 个路径 / {len(ents)} 段")
    print(f"  解包后预估: {total:,} 字节 ({total/1024/1024:.1f} MB)")
    return 0


def cmd_list(a) -> int:
    p = Path(a.archive)
    index, ver, off, key = load_index(p)
    ents = list(iter_entries(index, key))
    lines = [f"{ln:>12}  {name}" for name, o, ln in sorted(ents)]
    if a.out:
        Path(a.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"条目清单写入: {a.out}  ({len(lines)} 行)")
    else:
        for ln in lines[:40]:
            print(ln)
        if len(lines) > 40:
            print(f"... 共 {len(lines)} 条")
    return 0


def cmd_extract(a) -> int:
    src = Path(a.archive)
    dest = Path(a.outdir)
    index, ver, off, key = load_index(src)
    ents = list(iter_entries(index, key))
    pat = re.compile(a.only) if a.only else None
    if pat:
        ents = [e for e in ents if pat.search(e[0])]
    # 按路径合并（RPA 可能把同一文件拆成多段；prefix 非空时拼接）
    by_name: dict[str, list] = {}
    for name, o, ln in ents:
        by_name.setdefault(name, []).append((o, ln))

    dest.mkdir(parents=True, exist_ok=True)
    total = len(by_name)
    done = err = 0
    written = 0
    t0 = time.time()
    with src.open("rb") as fh:
        for i, (name, segs) in enumerate(sorted(by_name.items()), 1):
            segs.sort()
            if a.flat:
                target = dest / re.sub(r"[\\/]", "_", name)
            else:
                target = dest / name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as out:
                    for o, ln in segs:
                        fh.seek(o)
                        remain = ln
                        while remain > 0:
                            chunk = fh.read(min(1 << 22, remain))
                            if not chunk:
                                raise IOError(f"归档数据提前结束（还差 {remain} 字节）")
                            out.write(chunk)
                            remain -= len(chunk)
                            written += len(chunk)
                done += 1
            except Exception as exc:
                err += 1
                print(f"  [失败] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            if i % 200 == 0 or i == total:
                el = time.time() - t0
                mb = written / 1024 / 1024
                print(f"  [{i}/{total}] ok={done} err={err}  {mb:.1f} MB  "
                      f"{el:.0f}s  ({mb/el if el else 0:.1f} MB/s)", flush=True)
    print(f"\n解包完成: {done} 个文件, {err} 个失败, {written/1024/1024:.1f} MB -> {dest}")
    return 0 if err == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Ren'Py RPA 归档工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("info"); p1.add_argument("archive"); p1.set_defaults(f=cmd_info)
    p2 = sub.add_parser("list")
    p2.add_argument("archive"); p2.add_argument("-o", "--out"); p2.set_defaults(f=cmd_list)
    p3 = sub.add_parser("extract")
    p3.add_argument("archive"); p3.add_argument("outdir")
    p3.add_argument("--only", help="只解名字匹配该正则的条目")
    p3.add_argument("--flat", action="store_true", help="平铺输出（把 / 换成 _）")
    p3.set_defaults(f=cmd_extract)

    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
