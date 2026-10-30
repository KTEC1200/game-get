#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ExHIBIT .grp 音频库提取（算法照抄 GARbro-Mod ArcFormats/ExHibit/ArcGRP.cs）。

结构：resNNNN.grp 为音频数据；同名 res(NNNN-1).grp 往下找直到 AiFS 文件即是 TOC。
TOC: i32 res_count @0xC；自 0x10 起每块 = { i32 num（或 0x01000000 标志+重读）,
u32 start_index @+4, u32 @+8, u32 count @+0xC } + count×(u32 offset, u32 size)。
size!=0 的对 → res 文件内 offset 处切出 size 字节，命名 {start_index+i:D5}.ogg。

用法: python _grp_extract.py <res目录> <输出目录> [--manifest PATH]
  --manifest 不给就不写；给了则按 software-plan §2 契约落一份 manifest.json。

地面真相
--------
`expected_counts(res_dir)` 是**唯一出处**：它按 TOC 数出每个可切分 `.grp` 的非空条目数。
orchestrator 的对账和 main() 的收尾统计都走它，**别在别处另写一份 TOC 解析**——
两处各写一份，一边按 6755 条对账、另一边按 6754 条，谁也说不清谁错
（这正是 AdvHD 那边 `len(lines)-1` 每包少算 1 的翻版）。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Any

#: 一个条目 = TOC 里的 (索引, 数据偏移, 数据长度)。
Entry = tuple[int, int, int]


def _head(p: Path, n: int = 4) -> bytes:
    """只读文件头 n 字节。

    **不要用 `p.read_bytes()[:4]`**：res2001.grp 有 402 MB，为了看 4 个字节
    把整个文件读进内存是纯粹的浪费（原版就是这么写的，本作实测时白读了几百 MB）。
    """
    try:
        with p.open("rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def find_toc(res_dir: Path, arc_num: int) -> tuple[Path, int] | None:
    """从 res(arc_num-1).grp 往下找，返回 `(TOC 路径, arc_index)`。

    `arc_index` 是「这个数据包在 TOC 里排第几块」（从 1 起），TOC 每块的 `num`
    字段要与它相等才能对上。
    """
    toc_num = arc_num - 1
    arc_index = 1
    while toc_num >= 0:
        toc_name = res_dir / f"res{toc_num:04d}.grp"
        if not toc_name.exists():
            return None
        if _head(toc_name) == b"AiFS":
            return toc_name, arc_index
        toc_num -= 1
        arc_index += 1
    return None


def arc_num_of(name: str) -> int | None:
    """`res2001.grp` → 2001；取不到数字返回 None。"""
    digits = "".join(ch for ch in name[3:8] if ch.isdigit())
    return int(digits) if digits else None


def grp_arcs(res_dir: Path) -> list[Path]:
    """可切分的数据包：`res[0-9]*.grp` 里**排除 AiFS 文件本身**（那是 TOC，不是数据）。"""
    out: list[Path] = []
    for p in sorted(res_dir.glob("res[0-9]*.grp")):
        if _head(p) == b"AiFS":
            continue
        out.append(p)
    return out


def toc_files(res_dir: Path) -> list[Path]:
    """目录里的 AiFS 文件（纯 TOC，不切分）。"""
    return [p for p in sorted(res_dir.glob("res[0-9]*.grp")) if _head(p) == b"AiFS"]


def read_entries(res_dir: Path, arc: Path) -> tuple[list[Entry], Path, int] | None:
    """读一个数据包的条目表，返回 `(entries, toc路径, start_index)`；列不出返回 None。

    **这是 TOC 解析的唯一实现**（`expected_counts` 与 `main()` 都走它）。
    `size == 0` 的对是占位，不算条目——与切分时的 `if size` 保持同一口径。
    """
    n = arc_num_of(arc.name)
    if n is None:
        return None
    found = find_toc(res_dir, n)
    if found is None:
        return None
    toc_path, arc_index = found
    toc = toc_path.read_bytes()
    if len(toc) < 0x10:
        return None
    res_count = struct.unpack_from("<i", toc, 0xC)[0]
    if res_count < arc_index:
        return None
    io_off = 0x10
    for _ in range(res_count):
        if io_off + 0x10 > len(toc):
            return None
        num = struct.unpack_from("<i", toc, io_off)[0]
        if num == 0x01000000:
            # 转义标志：跳过这 4 字节再读一次 num
            io_off += 4
            if io_off + 0x10 > len(toc):
                return None
            num = struct.unpack_from("<i", toc, io_off)[0]
        start_index = struct.unpack_from("<I", toc, io_off + 4)[0]
        count = struct.unpack_from("<I", toc, io_off + 0xC)[0]
        if num == arc_index:
            base = io_off + 0x10
            entries: list[Entry] = []
            for i in range(count):
                pos = base + i * 8
                if pos + 8 > len(toc):
                    break
                offset, size = struct.unpack_from("<II", toc, pos)
                if size:
                    entries.append((start_index + i, offset, size))
            return entries, toc_path, start_index
        io_off += 0x10 + count * 8
    return None


def expected_counts(res_dir: Path) -> dict[str, Any]:
    """地面真相：`{total, by_arc, toc, unlistable, arcs}`。

    * `total`      —— 全部可切分数据包的非空条目数之和（本作 6755 + 2430 = 9185）
    * `by_arc`     —— `{包名: 条目数}`
    * `toc`        —— `{包名: TOC 文件名}`
    * `unlistable` —— 找不到 TOC / 块对不上的包名（**有它就说明没有完整地面真相**）
    """
    by_arc: dict[str, int] = {}
    toc_of: dict[str, str] = {}
    unlistable: list[str] = []
    arcs = grp_arcs(res_dir)
    for arc in arcs:
        got = read_entries(res_dir, arc)
        if got is None:
            unlistable.append(arc.name)
            continue
        entries, toc_path, _start = got
        by_arc[arc.name] = len(entries)
        toc_of[arc.name] = toc_path.name
    return {
        "total": sum(by_arc.values()),
        "by_arc": by_arc,
        "toc": toc_of,
        "unlistable": unlistable,
        "arcs": [a.name for a in arcs],
    }


def write_manifest(out_dir: Path, res_dir: Path, exp: dict[str, Any],
                   n_ok: int, n_fail: int, fails: list[str], path: Path) -> dict:
    """按 software-plan §2 契约写 manifest（raw/final/converted 三段式）。

    切分是内联的：`.grp` 里切出来就是 `.ogg`，磁盘上不存在中间格式，
    所以走 `manifest.counts_flat()`（raw == final，converted 为空）。

    这份 manifest 的对账口径是**本工具自己的子树**（`out_dir` = `raw/audio/`）：
    期望 = TOC 条目数，实际 = 该目录下的 `.ogg` 数。全局对账（raw 总数）由 orchestrator 做。
    """
    import manifest as mf

    counts_block = mf.counts_flat(out_dir)
    man = mf.build(
        tool="_grp_extract.py",
        engine="ExHIBIT",
        source={
            "toc_dir": str(res_dir),
            "out_root": str(out_dir),
            "arcs": [{"name": name, "entries": n, "toc": exp["toc"].get(name)}
                     for name, n in exp["by_arc"].items()],
            "unlistable": list(exp["unlistable"]),
        },
        counts_block=counts_block,
        reconcile_block=mf.reconcile(exp["total"], counts_block["raw"]["total"]),
        verify={"verified": False,
                "note": "本工具只做切分，不做内容级验收；"
                        "请用 orchestrator.py 或 _verify_media.py"},
        postprocess=[],
        extra={"fail_count": n_fail, "fails": fails[:50], "written": n_ok},
    )
    mf.write(path, man)
    return man


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    man_path: Path | None = None
    if "--manifest" in args:
        i = args.index("--manifest")
        if i + 1 >= len(args):
            print("--manifest 需要一个路径参数", file=sys.stderr)
            return 2
        man_path = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) < 2:
        print("用法: python _grp_extract.py <res目录> <输出目录> [--manifest PATH]")
        return 2
    res_dir, out_dir = Path(args[0]), Path(args[1])

    exp = expected_counts(res_dir)
    for t in toc_files(res_dir):
        print(f"[TOC] {t.name}（作为目录使用，不切分）")
    for name in exp["unlistable"]:
        print(f"[跳过] {name}: 找不到 AiFS TOC 或块对不上")
    if exp["total"]:
        print(f"地面真相：{len(exp['by_arc'])} 个数据包，共 {exp['total']} 条")

    total_ok = total_fail = 0
    fails: list[str] = []
    for arc in grp_arcs(res_dir):
        # 再取一次条目表只是重读那个小 TOC 文件（数据包另读），换来 main() 不必
        # 自己聚合一遍——聚合口径只在 expected_counts 里存在一份。
        got = read_entries(res_dir, arc)
        if got is None:
            continue
        entries, _toc_path, start_index = got
        data = arc.read_bytes()
        arc_out = out_dir / arc.name[:-4]
        arc_out.mkdir(parents=True, exist_ok=True)
        ok = fail = 0
        for idx, offset, size in entries:
            try:
                blob = bytes(data[offset:offset + size])
                if len(blob) != size:
                    raise ValueError("越界")
                if blob[:4] not in (b"OggS", b"RIFF"):
                    raise ValueError(f"头异常 {blob[:4].hex()}")
                (arc_out / f"{idx:05d}.ogg").write_bytes(blob)
                ok += 1
            except Exception as exc:
                fail += 1
                if fail <= 5:
                    print(f"  FAIL {idx}: {exc}")
                fails.append(f"{arc.name}:{idx}: {exc}")
        print(f"{arc.name}: {len(entries)} 条（索引 {start_index} 起），落盘 {ok} 失败 {fail}")
        total_ok += ok
        total_fail += fail

    actual = sum(1 for p in out_dir.rglob("*") if p.is_file()) if out_dir.is_dir() else 0
    print(f"\n合计 ok {total_ok} fail {total_fail}；对账 期望 {exp['total']} vs 落盘 {actual}")
    if man_path is not None:
        try:
            write_manifest(out_dir, res_dir, exp, total_ok, total_fail, fails, man_path)
            print(f"manifest -> {man_path}")
        except Exception as exc:  # manifest 失败不该毁掉已落盘的产物
            print(f"[WARN] manifest 写入失败（产物不受影响）：{exc}", file=sys.stderr)
    if exp["unlistable"]:
        print(f"[WARN] {len(exp['unlistable'])} 个包列不出条目，地面真相不完整")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
