#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ren'Py RPA 一键解包 + 按资源类型分类归档。

用法:
  python rpa_extract_organized.py <archive.rpa> <输出目录> [--only REGEX] [--manifest PATH]

`--manifest PATH` 不给就不写；给了则按 software-plan §2 契约落一份 manifest.json
（RPA 条目裸存无转换，故 raw == final、converted 为空，对账以索引去重条目数为地面真相）。

与 `rpa_tool.py extract` 的区别：直接从归档**按分类写盘**，不做「先全解再搬运」的两次 I/O。
分类规则见 classify()；所有分类平铺在输出目录下（`<输出目录>/<分类>/<包内路径>`）。
（旧文档里的 `--flat-cats` 参数从未实现过，2026-10-29 已从本文档删掉。）

性能说明：直接用 file.seek+read 分块写，实测 ~200 MB/s；5.9 GB 约 30 秒。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rpa_tool import iter_entries, load_index  # noqa: E402

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def classify(rel: str) -> str:
    """决定一个包内路径该归到哪个资源目录。

    ⚠️ 教训（2026-10-13 实测）：**不能只按目录判**。
      - `images/animations/` 下除 .avi/.webm 还有 282 个 jpg（动画缩略图）
      - 视频还散落在 `images/mm/`、`images/notes/`、`tl/chinese/images/animations/`
    因此：先按**扩展名**认媒体本体，再退回按目录分；`tl/` 视为本地化补丁树整体保留。
    """
    r = rel.replace("\\", "/")
    low = r.lower()
    ext = low.rsplit(".", 1)[-1] if "." in low else ""

    if low.startswith("tl/") or ext in ("rpyc", "rpyb", "rpy", "rpym", "rpymc"):
        return "Scripts"
    if ext == "avi":
        return "Video_AVI"
    if ext == "webm":
        return "Video_WebM"
    if ext in ("mp3", "ogg", "wav", "opus", "flac", "m4a"):
        return "Audio_Music" if low.startswith("sound/music/") else "Audio_SFX"
    if low.startswith("images/"):
        parts = r.split("/")
        return "Image_" + (parts[1] if len(parts) >= 2 and parts[1] else "misc")
    if low.startswith("sound/"):
        return "Audio_SFX"
    if low.startswith(("gui/", "cache/")):
        return "UI"
    return "Other"


def write_manifest(dest: Path, src: Path, ver, key: int, total: int,
                   cats: dict[str, list[int]], path: Path) -> dict:
    """按 software-plan §2 契约写 manifest（raw/final/converted 三段式）。

    RPA 条目是裸存，没有后处理转换，落盘即成品 → `manifest.counts_flat()`
    （raw == final，converted 为空）。分类明细写进 postprocess。

    地面真相 = 归档索引里**按名字去重**后的条目数（同一名字的多段算一个文件，
    本工具落盘时就是按名字拼成一份的）。`total` 传的就是这个数。
    """
    import manifest as mf
    counts_block = mf.counts_flat(dest)
    man = mf.build(
        tool="rpa_extract_organized.py",
        engine="Ren'Py",
        source={"archive": str(src), "out_root": str(dest),
                "version": ver, "xor_key": f"0x{key:08x}", "entries": total},
        counts_block=counts_block,
        reconcile_block=mf.reconcile(total, counts_block["raw"]["total"]),
        verify={"verified": False,
                "note": "本工具只解包分类，不做内容级验收；"
                        "请用 orchestrator.py 或 _verify_media.py"},
        postprocess=[{"tool": "内联分类归档",
                      "detail": {c: {"files": n, "bytes": b}
                                 for c, (n, b) in sorted(cats.items())}}],
    )
    mf.write(path, man)
    return man


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("outdir")
    ap.add_argument("--only", help="只解名字匹配该正则的条目")
    ap.add_argument("--manifest", default=None,
                    help="manifest.json 输出路径（不给就不写）")
    a = ap.parse_args()

    src, dest = Path(a.archive), Path(a.outdir)
    index, ver, idxoff, key = load_index(src)
    ents = list(iter_entries(index, key))
    import re
    if a.only:
        pat = re.compile(a.only)
        ents = [e for e in ents if pat.search(e[0])]

    # 同一名字若有多段，按 offset 排序后拼接
    by_name: dict[str, list] = {}
    for name, off, ln in ents:
        by_name.setdefault(name, []).append((off, ln))

    dest.mkdir(parents=True, exist_ok=True)
    cats: dict[str, list[int]] = {}
    t0 = time.time()
    written = 0
    total = len(by_name)

    with src.open("rb") as fh:
        for i, (name, segs) in enumerate(sorted(by_name.items()), 1):
            cat = classify(name)
            sub = name.replace("\\", "/")
            if cat.startswith("Image_") and sub.startswith("images/"):
                sub = sub[len("images/"):]
            target = dest / cat / sub
            target.parent.mkdir(parents=True, exist_ok=True)
            segs.sort()
            with target.open("wb") as out:
                for off, ln in segs:
                    fh.seek(off)
                    remain = ln
                    while remain > 0:
                        chunk = fh.read(min(1 << 22, remain))
                        if not chunk:
                            raise IOError(f"{name}: 归档数据提前结束（还差 {remain} 字节）")
                        out.write(chunk)
                        remain -= len(chunk)
                        written += len(chunk)
            st = cats.setdefault(cat, [0, 0])
            st[0] += 1
            st[1] += target.stat().st_size
            if i % 1000 == 0:
                el = time.time() - t0
                print(f"  [{i}/{total}] {written/1024/1024:.0f} MB  {el:.0f}s", flush=True)

    el = time.time() - t0
    print(f"\n完成: {total} 个文件, {written/1024/1024:.1f} MB, {el:.0f}s "
          f"({written/1024/1024/el if el else 0:.0f} MB/s) -> {dest}")
    print(f"\n{'分类':<22}{'数量':>8}{'MB':>12}")
    print("-" * 44)
    for c, (n, b) in sorted(cats.items(), key=lambda x: -x[1][1]):
        print(f"{c:<22}{n:>8}{b/1024/1024:>12.1f}")

    if a.manifest:
        try:
            write_manifest(dest, src, ver, key, total, cats, Path(a.manifest))
            print(f"\nmanifest -> {a.manifest}")
        except Exception as exc:  # manifest 失败不该毁掉已落盘的产物
            print(f"\n[WARN] manifest 写入失败（产物不受影响）：{exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
