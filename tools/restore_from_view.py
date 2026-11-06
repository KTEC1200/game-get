#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 organize.py 的「分类」硬链接视图还原 raw/ 与 png/（数据恢复工具）。

## 背景

`--overwrite` 的旧实现会直接删除 `raw/` 与 `png/`。但 `organize.py` 生成的
`分类/<图片|音频|视频|其他>/raw|png/...` 是**同盘硬链接**：删掉 raw/ 里的
目录项只是少了一个名字，文件数据仍由 `分类/` 视图里的链接持有，一字节没丢
（2026-11-06 实跑现场：`分类/` 里 9818 个文件、4.4 GiB 完好，抽样文件硬链接数为 2）。

本脚本按视图里的目录项**重建** raw/ 与 png/，同样只建硬链接、不复制字节。

## 安全性（三条红线）

  · 只读 `分类/` 视图：不删、不改、不重建视图，`.galunpack-view` 标记原样保留；
  · 目标已存在且 `os.path.samefile(dst, src)` 时**跳过**（与 organize.build_view
    的「已链同一文件跳过」语义一致），不 unlink 再 link；
  · 目标已存在但不是同一文件时默认**拒绝覆盖**并计数，只有显式 `--force` 才动；
    链接失败也**不退化成复制**（避免一次把用户的盘写满）。

## 用法（脚本不依赖本仓库任何模块，可单独拷到出问题的机器上运行）

    # 1) 先看会做什么，不写盘：
    python restore_from_view.py --out "D:\\HY\\教师催眠2\\output" --dry-run

    # 2) 真正还原：
    python restore_from_view.py --out "D:\\HY\\教师催眠2\\output"

    # 3) 验证（文件数、总字节、抽样文件大小与 samefile）：
    python restore_from_view.py --out "D:\\HY\\教师催眠2\\output" --check --sample 8

    # 视图不在默认的 <out>/分类 时：
    python restore_from_view.py --out ... --view "D:\\...\\分类-2"

退出码：0 成功 / 1 参数或视图错误 / 2 有冲突或链接失败 / 3 --check 不通过。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: 与 organize.py 保持一致（脚本独立，故意不 import 它）。
VIEW_NAME = "分类"
VIEW_MARK = ".galunpack-view"
KINDS = ("图片", "音频", "视频", "其他")
PREFIXES = ("raw", "png")


class ViewError(Exception):
    """视图不存在 / 没有标记 / 结构异常 —— 一律停下，不猜、不碰用户目录。"""


def _say(text: str) -> None:
    """中文输出；控制台编码不支持时退到 ASCII 安全串，不让报告把脚本打断。"""
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, OSError):
        try:
            print(str(text).encode("utf-8", "backslashreplace").decode("ascii", "replace"),
                  flush=True)
        except Exception:  # noqa: BLE001
            pass


def iter_view_entries(view_root: Path) -> list[tuple[str, str, Path]]:
    """枚举视图，返回 ``[(prefix, rel, src_path), ...]``（按路径排序，结果可复现）。

    结构：``<view>/<类目>/<raw|png>/<相对路径>``。要求根目录有 `.galunpack-view`
    标记 —— 没有就说明这是用户自己的同名目录，一个文件都不能动。
    """
    view_root = Path(view_root)
    if not view_root.is_dir():
        raise ViewError(f"视图目录不存在：{view_root}")
    if not (view_root / VIEW_MARK).is_file():
        raise ViewError(
            f"{view_root} 里没有 {VIEW_MARK} 标记，无法确认这是 organize.py 生成的视图；"
            f"为免误动你自己的目录，已停止。如确认无误，请用 --view 指到带标记的目录。")

    found: dict[tuple[str, str], Path] = {}
    for kind_dir in sorted((p for p in view_root.iterdir()
                            if p.is_dir() and p.name in KINDS), key=lambda p: p.name):
        for prefix in PREFIXES:
            base = kind_dir / prefix
            if not base.is_dir():
                continue
            for src in sorted((p for p in base.rglob("*") if p.is_file()),
                              key=lambda p: p.as_posix()):
                rel = src.relative_to(base).as_posix()
                key = (prefix, rel)
                if key in found:
                    # 同一个交付标签出现在两个类目里：视图被旧规则污染过。
                    # 同一份数据就跳过，不同数据必须停下（不能静默挑一个）。
                    try:
                        if os.path.samefile(found[key], src):
                            continue
                    except OSError:
                        pass
                    raise ViewError(f"视图里 {prefix}/{rel} 指向两个不同文件："
                                    f"{found[key]} 与 {src}；请先人工核对再恢复")
                found[key] = src
    return [(prefix, rel, src) for (prefix, rel), src in
            sorted(found.items(), key=lambda kv: (kv[0][0], kv[0][1]))]


def restore(out_dir: Path, view_root: Path, *, dry_run: bool = False,
            force: bool = False) -> dict:
    """按视图重建 ``<out>/raw`` 与 ``<out>/png``，返回统计 dict。"""
    out_dir = Path(out_dir)
    view_root = Path(view_root)
    entries = iter_view_entries(view_root)
    res: dict = {
        "out": str(out_dir), "view": str(view_root), "dry_run": dry_run,
        "force": force, "entries": len(entries), "linked": 0,
        "skipped_same": 0, "conflicts": 0, "failed": 0,
        "by_prefix": {p: 0 for p in PREFIXES}, "errors": [],
    }

    def note(msg: str) -> None:
        if len(res["errors"]) < 20:
            res["errors"].append(msg)

    for prefix, rel, src in entries:
        dst = out_dir / prefix / Path(rel)
        if dst.exists():
            try:
                same = os.path.samefile(dst, src)
            except OSError:
                same = False
            if same:
                res["skipped_same"] += 1        # 已链同一文件：什么都不做
                continue
            if not force:
                res["conflicts"] += 1
                note(f"目标已存在且不是同一文件（未覆盖，加 --force 才动）：{dst}")
                continue
            try:
                dst.unlink()
            except OSError as exc:
                res["failed"] += 1
                note(f"--force 覆盖失败 {dst}: {type(exc).__name__}: {exc}")
                continue
        if dry_run:
            res["linked"] += 1
            res["by_prefix"][prefix] += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(src, dst)                   # 同盘硬链接：零拷贝
        except OSError as exc:
            # 绝不用 shutil.copy2 兜底：一次 100 GiB 的复制会把用户的盘填满。
            res["failed"] += 1
            note(f"建硬链接失败 {dst}: {type(exc).__name__}: {exc}")
        else:
            res["linked"] += 1
            res["by_prefix"][prefix] += 1
    return res


def _dir_stats(root: Path) -> tuple[int, int]:
    """目录里的 (文件数, 总字节)。目录不存在返回 (0, 0)。"""
    if not root.is_dir():
        return 0, 0
    total = size = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        total += 1
        try:
            size += p.stat().st_size
        except OSError:
            pass
    return total, size


def check(out_dir: Path, view_root: Path, *, sample: int = 5) -> dict:
    """验证还原结果：文件数、总字节、抽样文件大小与是否同一文件。"""
    out_dir = Path(out_dir)
    view_root = Path(view_root)
    entries = iter_view_entries(view_root)
    res: dict = {"out": str(out_dir), "view": str(view_root),
                 "view_entries": len(entries), "missing": 0, "samples": []}
    for prefix in PREFIXES:
        n, size = _dir_stats(out_dir / prefix)
        res[f"{prefix}_files"] = n
        res[f"{prefix}_bytes"] = size
        res[f"expected_{prefix}_from_view"] = sum(1 for p, _r, _s in entries if p == prefix)
    for prefix, rel, src in entries:
        if not (out_dir / prefix / Path(rel)).is_file():
            res["missing"] += 1

    step = max(1, len(entries) // max(1, sample)) if entries else 1
    picked = entries[::step][:max(1, sample)]
    for prefix, rel, src in picked:
        dst = out_dir / prefix / Path(rel)
        try:
            expected_size = src.stat().st_size
        except OSError:
            expected_size = -1
        try:
            actual_size = dst.stat().st_size
        except OSError:
            actual_size = -1
        try:
            same = os.path.samefile(dst, src)
        except OSError:
            same = False
        res["samples"].append({
            "path": f"{prefix}/{rel}", "expected_size": expected_size,
            "actual_size": actual_size, "samefile": same,
            "ok": dst.is_file() and same and expected_size == actual_size,
        })
    res["ok"] = (res["missing"] == 0
                 and all(s["ok"] for s in res["samples"])
                 and res["raw_files"] >= res["expected_raw_from_view"]
                 and res["png_files"] >= res["expected_png_from_view"])
    return res


def _report(res: dict, *, as_json: bool) -> None:
    if as_json:
        _say(json.dumps(res, ensure_ascii=False, indent=2))
        return
    _say(f"输出目录：{res['out']}")
    _say(f"视图目录：{res['view']}")
    if "raw_files" in res:                     # --check
        _say(f"raw/  : {res['raw_files']} 个文件，{res['raw_bytes']} 字节"
             f"（视图应有 {res['expected_raw_from_view']}）")
        _say(f"png/  : {res['png_files']} 个文件，{res['png_bytes']} 字节"
             f"（视图应有 {res['expected_png_from_view']}）")
        _say(f"视图条目 {res['view_entries']}，缺失 {res['missing']}")
        for s in res["samples"]:
            _say(f"  抽样 {s['path']}：{s['actual_size']}/{s['expected_size']} 字节 "
                 f"samefile={s['samefile']} {'OK' if s['ok'] else 'FAIL'}")
        _say("验证：" + ("通过" if res["ok"] else "不通过"))
    else:
        _say(f"视图条目 {res['entries']}（raw {res['by_prefix']['raw']} / "
             f"png {res['by_prefix']['png']} 预计）")
        _say(f"新建硬链接 {res['linked']}，已链同一文件跳过 {res['skipped_same']}，"
             f"冲突未覆盖 {res['conflicts']}，失败 {res['failed']}"
             + ("（--dry-run，未写盘）" if res["dry_run"] else ""))
    for err in res.get("errors", []):
        _say("  ! " + err)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="从 organize.py 的分类硬链接视图还原 raw/ 与 png/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("示例：\n"
                "  python restore_from_view.py --out D:\\HY\\教师催眠2\\output --dry-run\n"
                "  python restore_from_view.py --out D:\\HY\\教师催眠2\\output\n"
                "  python restore_from_view.py --out D:\\HY\\教师催眠2\\output --check"))
    ap.add_argument("--out", required=True, help="输出目录（raw/ 与 png/ 的上一级）")
    ap.add_argument("--view", default=None, help=f"视图目录，默认 <out>/{VIEW_NAME}")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不建任何链接")
    ap.add_argument("--check", action="store_true", help="只验证，输出文件数与抽样大小")
    ap.add_argument("--force", action="store_true",
                    help="目标已存在且不是同一文件时允许覆盖（默认拒绝）")
    ap.add_argument("--sample", type=int, default=5, help="--check 的抽样数，默认 5")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出，便于脚本消费")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    view_root = Path(args.view) if args.view else out_dir / VIEW_NAME
    try:
        res = (check(out_dir, view_root, sample=max(1, args.sample)) if args.check
               else restore(out_dir, view_root,
                            dry_run=args.dry_run, force=args.force))
    except ViewError as exc:
        _say(f"错误：{exc}")
        return 1
    _report(res, as_json=args.json)
    if args.check:
        return 0 if res["ok"] else 3
    return 0 if (res["conflicts"] == 0 and res["failed"] == 0) else 2


if __name__ == "__main__":
    sys.exit(main())
