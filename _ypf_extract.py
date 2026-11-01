#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yu-Ris YPF 封包提取器（自研；格式逆向自 arc_unpacker ypf_archive_decoder.cc）。

格式（版本 0x1EE 实测）:
  头 32B: "YPF\\0" + u32 version + u32 file_count + u32 table_size + 0x00*16
  表@0x20, 每条目: skip(4) + name_len_enc(u8, ^0xFF 查置换表得实际名长)
                   + name(原始 XOR 单字节 key) + type(u8) + compressed(u8, 1=zlib)
                   + size_orig(u32) + size_comp(u32) + offset(u32) + extra(版本>=0x1D9 为 8B)
  名字 key 猜测: name[-4] ^ '.' 应落在已知扩展名的 '.' 上
  YCG 图片: "YCG\\0"+w+h+depth(32)+comp(1)+12B+orig1+comp1+8B+orig2+comp2 @0x38 起
            两段 zlib 流拼接 = BGRA8888 原始像素

用法:
  python _ypf_extract.py <x.ypf> <outdir> [--ycg-png] [--no-ycg] [--manifest PATH]
  --ycg-png: YCG 直接转 PNG（默认开）; --no-ycg 保留 .ycg 原始文件
  --manifest 不给就不写；给了则按 software-plan §2 契约落一份 manifest.json。
"""
from __future__ import annotations

import io
import sys
import zlib
from pathlib import Path

GOOD_EXT = {"bmp", "png", "ogg", "wav", "txt", "ybn"}


def swap_table(swaps):
    t = list(range(256))
    for a, b in swaps:
        t[a], t[b] = b, a
    return t


# 四种名长置换表（同 arc_unpacker name_size_tables）
NAME_SIZE_TABLES = [
    swap_table([(0x03, 0x48), (0x06, 0x35), (0x0C, 0x10), (0x11, 0x19),
                (0x1C, 0x1E), (0x09, 0x0B), (0x0D, 0x13), (0x15, 0x1B),
                (0x20, 0x23), (0x26, 0x29), (0x2C, 0x2F), (0x2E, 0x32)]),
    swap_table([(0x0C, 0x10), (0x11, 0x19), (0x1C, 0x1E), (0x09, 0x0B),
                (0x0D, 0x13), (0x15, 0x1B), (0x20, 0x23), (0x26, 0x29),
                (0x2C, 0x2F), (0x2E, 0x32)]),
    swap_table([(0x09, 0x0B), (0x0D, 0x13), (0x15, 0x1B), (0x20, 0x23),
                (0x26, 0x29), (0x2C, 0x2F), (0x2E, 0x32)]),
    swap_table([(0x03, 0x48), (0x06, 0x35), (0x09, 0x0B), (0x0C, 0x10),
                (0x0D, 0x13), (0x11, 0x19), (0x15, 0x1B), (0x1C, 0x1E),
                (0x20, 0x23), (0x26, 0x29), (0x2C, 0x2F), (0x2E, 0x32)]),
]


def extra_header_size(version: int) -> int:
    if version == 0xDE:
        return 12
    if version >= 0x1D9:
        return 8
    return 4


def parse_table(buf: bytes, version: int, table, file_count: int) -> list[dict]:
    extra = extra_header_size(version)
    pos = 0
    entries = []
    for i in range(file_count):
        pos += 4
        if pos >= len(buf):
            raise ValueError(f"truncated at name_len #{i}")
        name_len = table[buf[pos] ^ 0xFF]
        pos += 1
        if name_len <= 0 or pos + name_len + 14 + extra > len(buf):
            raise ValueError(f"truncated at entry #{i}")
        name = buf[pos:pos + name_len]
        pos += name_len
        etype = buf[pos]
        comp = buf[pos + 1]
        size_orig = int.from_bytes(buf[pos + 2:pos + 6], "little")
        size_comp = int.from_bytes(buf[pos + 6:pos + 10], "little")
        offset = int.from_bytes(buf[pos + 10:pos + 14], "little")
        pos += 14 + extra
        entries.append({"name": name, "type": etype, "compressed": comp == 1,
                        "size_orig": size_orig, "size_comp": size_comp,
                        "offset": offset})
    return entries


def guess_key(names: list[bytes]) -> int:
    for name in names:
        if len(name) < 4:
            continue
        key = name[-4] ^ ord(".")
        dec = bytes(b ^ key for b in name)
        ext = dec.decode("cp932", errors="replace").rsplit(".", 1)[-1].lower()
        if ext in GOOD_EXT:
            return key
    raise SystemExit("猜 key 失败：没有已知扩展名的条目（用 --key 手动指定）")


def ycg_to_png(data: bytes):
    from PIL import Image
    if data[:4] != b"YCG\x00":
        return None
    w = int.from_bytes(data[4:8], "little")
    h = int.from_bytes(data[8:12], "little")
    depth = int.from_bytes(data[12:16], "little")
    method = int.from_bytes(data[16:20], "little")
    if depth != 32 or method != 1:
        raise ValueError(f"YCG depth={depth} method={method} 不支持")
    c1 = int.from_bytes(data[0x20:0x24], "little")
    c2 = int.from_bytes(data[0x30:0x34], "little")
    raw = zlib.decompress(data[0x38:0x38 + c1]) + zlib.decompress(data[0x38 + c1:0x38 + c1 + c2])
    if len(raw) != w * h * 4:
        raise ValueError(f"YCG 像素数不符: {len(raw)} != {w*h*4}")
    im = Image.frombytes("RGBA", (w, h), raw, "raw", "BGRA")
    return im


def write_manifest(out_root: Path, arc_path: Path, version: int, key: int,
                   entry_count: int, n_zlib: int, n_ycg: int, n_plain: int,
                   fails: list[str], path: Path) -> dict:
    """按 software-plan §2 契约写 manifest（raw/final/converted 三段式）。

    转换是**内联**的：`--ycg-png`（默认）时 `.ycg` 落盘就是 `.png`，磁盘上不存在中间格式，
    所以走 `manifest.counts_flat()`（raw == final，converted 为空）；
    YCG→PNG 的明细写进 postprocess。

    地面真相 = YPF 表里的条目数（`entry_count`），这是格式自己声明的，不是猜的。
    `--no-ycg` 时 `.ycg` 原样落盘，仍然一 entry 一文件，对账口径不变。
    """
    import manifest as mf
    counts_block = mf.counts_flat(out_root)
    man = mf.build(
        tool="_ypf_extract.py",
        engine="Yu-Ris",
        source={"archive": str(arc_path), "out_root": str(out_root),
                "ypf_version": version, "name_xor_key": key, "entries": entry_count},
        counts_block=counts_block,
        reconcile_block=mf.reconcile(entry_count, counts_block["raw"]["total"]),
        verify={"verified": False,
                "note": "本工具只做解压/解码，不做内容级验收；"
                        "请用 orchestrator.py 或 _verify_media.py"},
        postprocess=[{"tool": "内联 YCG→PNG（两段 zlib 拼 BGRA）",
                      "detail": {"zlib_inflate": n_zlib, "ycg_to_png": n_ycg,
                                 "plain_copy": n_plain}}],
        extra={"fail_count": len(fails), "fails": fails[:50]},
    )
    mf.write(path, man)
    return man


def read_index(arc_path: Path):
    """解析 YPF 索引，返回 (version, entries, key, data_all)。

    **这是「地面真相」的唯一出处**：条目数 = len(entries)，main() 落盘与 orchestrator
    的对账都用它。抄成两份必然漂移——一边按 195 条对账、另一边按 194 条，谁也说不清谁错。
    四种名长置换表逐个试，校验「条数相符 且 没有越界条目」才算命中。
    """
    data_all = arc_path.read_bytes()
    version = int.from_bytes(data_all[4:8], "little")
    file_count = int.from_bytes(data_all[8:12], "little")
    table_size = int.from_bytes(data_all[12:16], "little")
    table_buf = data_all[0x20:0x20 + table_size]

    entries = None
    for t in NAME_SIZE_TABLES:
        try:
            cand = parse_table(table_buf, version, t, file_count)
        except ValueError:
            continue
        bad = [e for e in cand if e["offset"] + e["size_comp"] > len(data_all)]
        if len(cand) == file_count and not bad:
            entries = cand
            break
    if entries is None:
        raise ValueError(f"{arc_path.name}: 四种名长置换表都解析失败")
    key = guess_key([e["name"] for e in entries])
    return version, entries, key, data_all


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    args = [a for a in argv if not a.startswith("--")]
    ycg_png = "--no-ycg" not in argv
    man_path = Path(argv[argv.index("--manifest") + 1]) if "--manifest" in argv else None
    arc_path, out_root = Path(args[0]), Path(args[1])

    try:
        version, entries, key, data_all = read_index(arc_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{arc_path.name}: version={version:#x} count={len(entries)}")
    print(f"  名字 XOR key = {key:#04x}")

    out_root.mkdir(parents=True, exist_ok=True)
    n_zlib = n_ycg = n_plain = 0
    fails = []
    for e in entries:
        name = bytes(b ^ key for b in e["name"]).decode("cp932", errors="replace")
        name = name.replace("\\", "/")
        raw = data_all[e["offset"]:e["offset"] + e["size_comp"]]
        if len(raw) != e["size_comp"]:
            fails.append(f"{name}: 数据越界 offset={e['offset']} comp={e['size_comp']}")
            continue
        if e["compressed"]:
            try:
                raw = zlib.decompress(raw)
                n_zlib += 1
            except zlib.error as exc:
                fails.append(f"{name}: zlib {exc}")
                continue
        if len(raw) != e["size_orig"]:
            fails.append(f"{name}: 解压后 {len(raw)} != 声明 {e['size_orig']}")
            continue
        if raw[:4] == b"YCG\x00" and ycg_png:
            try:
                im = ycg_to_png(raw)
                dst = out_root / (name.rsplit(".", 1)[0] + ".png")
                im.save(dst)
                n_ycg += 1
                continue
            except Exception as exc:
                fails.append(f"{name}: YCG {exc}")
        dst = out_root / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        n_plain += 1

    print(f"  zlib 解压 {n_zlib}，YCG→PNG {n_ycg}，原样落盘 {n_plain}，失败 {len(fails)}")
    for f in fails[:20]:
        print("   FAIL", f)

    if man_path is not None:
        try:
            write_manifest(out_root, arc_path, version, key, len(entries),
                           n_zlib, n_ycg, n_plain, fails, man_path)
            print(f"  manifest -> {man_path}")
        except Exception as exc:  # manifest 失败不该毁掉已落盘的产物
            print(f"  [WARN] manifest 写入失败（产物不受影响）：{exc}", file=sys.stderr)
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
