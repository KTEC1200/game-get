#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Artemis Engine（pf8 / pf6 / pf2）封包提取器（自研；格式实测逆向，见 verified-findings 新章）。

格式（pf8 实测于 D:\HY\Toshiue Kanojo 的三个归档，2026-11-02）:
  @0x00  3B   魔数 "pf8"（同族 "pf6" / "pf2"；本工具按同一布局尝试）
  @0x03  u32  index_size —— 索引区字节数；索引区 = 文件 [7, 7+index_size)
  @0x07  u32  count      —— 条目数（与索引区首 4 字节同值，同一次出现两遍）
  索引区（idx = bytes[7 : 7+index_size]）:
    idx[0:4]  u32 count（与头部同值）
    随后 count 条，每条:
      u32 name_len  —— 名字**字节数，不含 NUL**
      name          —— name_len 字节，UTF-8（不是 UTF-8 时回退 CP932）
      u32 reserved  —— 实测恒 0
      u32 offset    —— 数据段文件偏移
      u32 size      —— 字节数
    尾部: (count+1) × u64 文件大小表 + u32 指向该表 —— **本工具不用**（offset/size 已在条目里）
  数据段: **整段按 key = SHA1(索引区) 的 20 字节循环 XOR**（data[i] ^= key[i % 20]，i 为段内下标）。
  字节恒等式: 7 + index_size + Σsize == 文件大小（实测三个归档精确相等 → 无对齐填充、无空洞）。

地面真相
--------
read_index() 是**唯一出处**：expected_counts()（orchestrator 对账用）与 main()（落盘用）都走它。
别在别处另写一份索引解析——两处各写一份必然漂移（_grp_extract.py 的注释同理）。

对账口径
--------
一个条目必出一个文件，所以「期望落盘数 = Σ 条目数」。**多个归档之间名字会重叠**
（实测 Toshiue Kanojo: 3977 条 / 3907 个不同名字，跨包重名 70），所以每个归档各落一个
子目录 <输出>/<归档文件名>/ —— 不是一个平铺目录：平铺会让后一个包覆盖前一个包，
落盘数比条目数少 70，而谁都看不出来。

用法:
  python _pfs_extract.py <游戏目录> <输出目录> [--manifest PATH]
  （游戏目录 = 含 .pfs 的那一层；本工具只扫**顶层**，备份目录里的副本不算）
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path
from typing import Any

#: 归档魔数（同族三兄弟；按 pf8 布局解析全部三种）
MAGICS = (b"pf8", b"pf6", b"pf2")

#: 已知扩展名 -> 解密后应有的魔数。XOR key 或索引解析错了，这里会立刻炸出来。
#: 只列**能用魔数判死的**：文本/着色器/脚本之类没法判，不列（别猜）。
KNOWN_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8\xff",),
    ".bmp": (b"BM",),
    ".gif": (b"GIF",),
    ".ogg": (b"OggS",),
    ".wav": (b"RIFF",),
    ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3"),
    ".ttf": (b"\x00\x01\x00\x00", b"OTTO"),
}


def _head(p: Path, n: int = 4) -> bytes:
    """只读文件头 n 字节（归档动辄几百 MB，别 read_bytes() 整包）。"""
    try:
        with p.open("rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def is_pfs(p: Path) -> bool:
    """是不是 Artemis 归档（判据是**魔数**不是文件名）。"""
    return p.is_file() and _head(p, 3) in MAGICS


def iter_archives(game_dir: Path) -> list[Path]:
    """游戏目录**顶层**的 Artemis 归档（只扫一层）。

    不入 rglob：追加包常被补丁/备份目录整份拷贝一份（本作『翻译补丁备份』里就有一份
    同尺寸的 .pfs.001），rglob 会把它再解一遍——条目数翻倍、还可能撞名。
    """
    if not game_dir.is_dir():
        return []
    return [p for p in sorted(game_dir.iterdir()) if is_pfs(p)]


def decode_name(raw: bytes) -> str:
    """条目名解码：先 UTF-8，失败回退 CP932（实测本作是 UTF-8 的日文名）。"""
    raw = raw.rstrip(b"\x00")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp932", errors="replace")


def _safe_rel(name: str) -> Path | None:
    """包内名字 -> 安全相对路径；带 .. 片段 / 盘符 / 空名的一律 None（不许写到输出目录外）。"""
    name = name.replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        return None
    if any(p == ".." for p in parts) or ":" in parts[0]:
        return None
    return Path(*parts)


def _xor(buf: bytes, key: bytes) -> bytes:
    """key 循环 XOR。用大整数一次异或——逐字节生成器要慢两个量级（570 MB 会跑几分钟）。"""
    n = len(buf)
    if not n:
        return buf
    k = key * (n // len(key) + 1)
    return (int.from_bytes(buf, "big") ^ int.from_bytes(k[:n], "big")).to_bytes(n, "big")


def read_index(archive: Path) -> dict[str, Any]:
    """解析一个归档的索引。**这是地面真相的唯一出处。**

    返回 {magic, index_size, count, entries, key, file_size, identity_ok, bad_bounds, by_ext}，
    其中 entries = [(name, offset, size), ...]（name 已解码、反斜杠转 '/'）。
    解析失败抛 ValueError（调用方决定是跳过还是失败）。
    """
    size = archive.stat().st_size
    with archive.open("rb") as fh:
        head = fh.read(11)
        if len(head) < 11:
            raise ValueError(f"{archive.name}: 文件不足 11 字节，不是 pf8")
        magic = head[:3]
        if magic not in MAGICS:
            raise ValueError(f"{archive.name}: 魔数 {magic!r} 不是 pf8/pf6/pf2")
        index_size = struct.unpack_from("<I", head, 3)[0]
        count = struct.unpack_from("<I", head, 7)[0]
        if index_size < 4 or 7 + index_size > size:
            raise ValueError(f"{archive.name}: 索引区越界（index_size={index_size} 文件 {size}）")
        fh.seek(7)
        idx = fh.read(index_size)
    if len(idx) != index_size:
        raise ValueError(f"{archive.name}: 索引区读取不足")
    if struct.unpack_from("<I", idx, 0)[0] != count:
        raise ValueError(f"{archive.name}: 头部条目数 {count} != 索引区首 4 字节")

    key = hashlib.sha1(idx).digest()
    entries: list[tuple[str, int, int]] = []
    bad_bounds: list[str] = []
    by_ext: dict[str, int] = {}
    off = 4
    for i in range(count):
        if off + 4 > len(idx):
            raise ValueError(f"{archive.name}: 索引在条目 {i} 处截断")
        name_len = struct.unpack_from("<I", idx, off)[0]
        off += 4
        if off + name_len + 12 > len(idx):
            raise ValueError(f"{archive.name}: 名字区越界（条目 {i}，name_len={name_len}）")
        name = decode_name(idx[off:off + name_len]).replace("\\", "/")
        off += name_len
        off += 4                                     # reserved，实测恒 0
        offset, fsize = struct.unpack_from("<II", idx, off)
        off += 8
        entries.append((name, offset, fsize))
        if offset + fsize > size:
            bad_bounds.append(f"{name}(offset={offset} size={fsize})")
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else "(无扩展名)"
        by_ext[ext] = by_ext.get(ext, 0) + 1

    total = sum(e[2] for e in entries)
    return {"magic": magic.decode(), "index_size": index_size, "count": count,
            "entries": entries, "key": key, "file_size": size,
            "identity_ok": 7 + index_size + total == size,
            "bad_bounds": bad_bounds, "by_ext": by_ext}


def expected_counts(game_dir: Path) -> dict[str, Any]:
    """地面真相：{total, by_arc, identity, unlistable, arcs}。

    * total      —— 全部可列归档的条目数之和（一个条目必出一个文件）
    * by_arc     —— {归档文件名: 条目数}
    * identity   —— {归档文件名: bool}：字节恒等式 7+index_size+Σsize==文件大小 是否成立
                    （不是硬门槛——别的引擎版本可能有填充——但一律报出来）
    * unlistable —— 索引解析失败的归档名（**有它就说明没有完整地面真相**，不许假装对过账）
    """
    arcs = iter_archives(game_dir)
    by_arc: dict[str, int] = {}
    identity: dict[str, bool] = {}
    unlistable: list[str] = []
    for arc in arcs:
        try:
            info = read_index(arc)
        except ValueError:
            unlistable.append(arc.name)
            continue
        by_arc[arc.name] = info["count"]
        identity[arc.name] = bool(info["identity_ok"])
    return {"total": sum(by_arc.values()), "by_arc": by_arc, "identity": identity,
            "unlistable": unlistable, "arcs": [a.name for a in arcs]}


def _magic_verdict(name: str, head: bytes) -> bool | None:
    """按扩展名查 KNOWN_MAGIC：None = 该扩展名没法用魔数判（不算失败）。"""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    cands = KNOWN_MAGIC.get(ext)
    if cands is None:
        return None
    return any(head.startswith(c) for c in cands)


def extract_archive(archive: Path, out_root: Path) -> dict[str, Any]:
    """解开一个归档到 out_root/<归档文件名>/，返回统计。

    一 entry 一文件、保持包内相对路径。落盘前按扩展名验魔数：**key 或索引解析错了，
    这里会立刻变成 fail，而不是一堆静默的垃圾**（魔数不符即判失败，宁可缺也不给假的）。
    """
    info = read_index(archive)
    key = info["key"]
    dest_root = out_root / archive.name
    ok = fail = magic_checked = magic_bad = 0
    fails: list[str] = []
    with archive.open("rb") as fh:
        for name, offset, size in info["entries"]:
            try:
                rel = _safe_rel(name)
                if rel is None:
                    raise ValueError(f"名字不安全: {name!r}")
                fh.seek(offset)
                blob = fh.read(size)
                if len(blob) != size:
                    raise ValueError(f"越界（offset={offset} size={size}）")
                blob = _xor(blob, key)
                if size:
                    verdict = _magic_verdict(name, blob[:8])
                    if verdict is not None:
                        magic_checked += 1
                        if not verdict:
                            magic_bad += 1
                            raise ValueError(f"解密后魔数不符扩展名（{blob[:4].hex()}）")
                dst = dest_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(blob)
                ok += 1
            except Exception as exc:                  # 单条坏不该毁掉整包
                fail += 1
                fails.append(f"{name}: {exc}")
    return {"archive": archive.name, "entries": info["count"], "ok": ok, "fail": fail,
            "magic_checked": magic_checked, "magic_bad": magic_bad, "fails": fails,
            "identity_ok": bool(info["identity_ok"]), "key_sha1": key.hex(),
            "by_ext": info["by_ext"], "bad_bounds": info["bad_bounds"]}


def write_manifest(out_root: Path, game_dir: Path, exp: dict[str, Any],
                   stats: list[dict[str, Any]], actual: int, path: Path) -> dict:
    """按 software-plan §2 契约写 manifest（raw/final/converted 三段式）。

    解密是**内联**的：落盘就是成品（png/ogg 原样），磁盘上不存在中间格式，
    所以走 manifest.counts_flat()（raw == final、converted 为空）。
    本工具的对账口径是**自己的子树**（out_root = raw/）：期望 = 条目总数，实际 = 落盘文件数；
    全局对账由 orchestrator 做。有归档列不出条目时不写对账（mf.reconcile(None, ...)），
    不许把「没验」伪装成「验过了」。
    """
    import manifest as mf

    counts_block = mf.counts_flat(out_root)
    expected = None if exp["unlistable"] else exp["total"]
    fails = [f for s in stats for f in s["fails"]]
    man = mf.build(
        tool="_pfs_extract.py",
        engine="Artemis",
        source={"game_dir": str(game_dir), "out_root": str(out_root),
                "archives": [{"name": s["archive"], "entries": s["entries"],
                              "extracted": s["ok"], "identity_ok": s["identity_ok"],
                              "key_sha1": s["key_sha1"],
                              "magic_checked": s["magic_checked"],
                              "magic_bad": s["magic_bad"]} for s in stats],
                "unlistable": list(exp["unlistable"])},
        counts_block=counts_block,
        reconcile_block=mf.reconcile(expected, actual),
        verify={"verified": False,
                "note": "本工具只做解密/落盘，不做内容级验收；"
                        "请用 orchestrator.py 或 _verify_media.py"},
        postprocess=[],
        extra={"fail_count": len(fails), "fails": fails[:50]},
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
        print("用法: python _pfs_extract.py <游戏目录> <输出目录> [--manifest PATH]")
        return 2
    game_dir, out_root = Path(args[0]), Path(args[1])

    exp = expected_counts(game_dir)
    if not exp["arcs"]:
        print(f"{game_dir}: 顶层没有 pf8/pf6/pf2 归档")
        return 2
    for name in exp["unlistable"]:
        print(f"[跳过] {name}: 索引解析失败")
    out_root.mkdir(parents=True, exist_ok=True)

    stats: list[dict[str, Any]] = []
    for arc in iter_archives(game_dir):
        try:
            s = extract_archive(arc, out_root)
        except ValueError as exc:
            print(f"[跳过] {exc}", file=sys.stderr)
            continue
        stats.append(s)
        print(f"{arc.name}: {s['entries']} 条 -> 落盘 {s['ok']} 失败 {s['fail']}"
              f"（魔数校验 {s['magic_checked']} 个，不符 {s['magic_bad']}）")
        for f in s["fails"][:5]:
            print("   FAIL", f)

    total_ok = sum(s["ok"] for s in stats)
    total_fail = sum(s["fail"] for s in stats)
    actual = sum(1 for p in out_root.rglob("*") if p.is_file())
    if exp["unlistable"]:
        print(f"\n合计 ok {total_ok} fail {total_fail}；{len(exp['unlistable'])} 个归档列不出条目，未对账")
    else:
        print(f"\n合计 ok {total_ok} fail {total_fail}；对账 期望 {exp['total']} vs 落盘 {actual}")
    if man_path is not None:
        try:
            write_manifest(out_root, game_dir, exp, stats, actual, man_path)
            print(f"manifest -> {man_path}")
        except Exception as exc:                      # manifest 失败不该毁掉已落盘的产物
            print(f"[WARN] manifest 写入失败（产物不受影响）：{exc}", file=sys.stderr)
    if exp["unlistable"]:
        print(f"[WARN] {len(exp['unlistable'])} 个归档索引解析失败：{exp['unlistable']}")
    return 0 if total_fail == 0 and not exp["unlistable"] and len(stats) == len(exp["arcs"]) and actual == exp["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
