#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 AssetStudio.CLI 的多模式分批法，把 CLI 一次性导不全的 AudioClip 尽量收全。

背景（实测 2026-10-12，见 verified-findings.md §8）：
  CLI 单次导出 resources.assets 里的 1183 个 AudioClip 时，绝大多数静默失败
  （日志里每一个都打印 `Exporting AudioClip: X`，但只有极少数写到磁盘，且无任何报错）。
  但把资产**按名字模式分组**、分别跑多次导出时，每次都能多成功几个
  → 说明失败取决于运行内的处理顺序，用不同分组反复跑即可逐步累积。

策略：
  * 生成多种名字正则模式（按前缀+首位数字、按前缀+前两位数字……）分批导出；
  * 每一批输出到独立目录，最后全部合并去重；
  * 同名资产由 AssetStudio 自行加序号，故不做名字去重，只按「文件内容哈希」去重。

用法:
  python _as_audio_collect.py <输入目录或文件> <累积输出目录>
"""
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXE = r"D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe"


def patterns() -> list[str]:
    """生成覆盖全部命名的模式集合。"""
    pats: list[str] = []
    prefixes = ["VA", "VB", "VC", "FE", "SEX", "ADD", "bgm", "SYASEI", "sexyvoice",
                "ding", "punch", "camera", "door", "cross", "sex"]
    # 1) 每个前缀 + 首位数字 0-9  -> 例如 ^VA1
    for p in prefixes:
        for d in "0123456789":
            pats.append(f"^{p}{d}")
    # 2) 每个前缀 + 前两位数字 -> 例如 ^VA12（覆盖首位相同、次位不同导致的失败）
    for p in ("VA", "VB", "VC"):
        for a in "0123456789":
            for b in "0123456789":
                pats.append(f"^{p}{a}{b}")
    # 3) 纯字母开头的杂项：按首字母
    for c in "abcdefghijklmnopqrstuvwxyz":
        pats.append(f"^{c}")
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        pats.append(f"^{c}")
    pats.append("^[0-9]")
    return list(dict.fromkeys(pats))  # 去重且保序


def digest(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    work = dest.parent / (dest.name + "_work")
    work.mkdir(parents=True, exist_ok=True)

    # 已有文件（支持断点续跑）
    seen: dict[str, Path] = {}
    for p in dest.rglob("*.wav"):
        seen[digest(p)] = p
    print(f"起始已累积: {len(seen)} 个 wav", flush=True)

    pats = patterns()
    print(f"模式总数: {len(pats)}", flush=True)
    for i, pat in enumerate(pats, 1):
        tmp = work / "cur"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [EXE, str(src), str(tmp), "--game", "Normal",
                 "--types", "AudioClip", "--names", pat,
                 "--export_type", "Convert", "--group_assets", "ByType"],
                capture_output=True, timeout=900)
        except subprocess.TimeoutExpired:
            print(f"  [{i}/{len(pats)}] {pat} TIMEOUT", flush=True)
            continue

        added = 0
        for w in tmp.rglob("*.wav"):
            d = digest(w)
            if d not in seen:
                seen[d] = w
                added += 1
        if added:
            # 立即搬运到 dest，避免 work 目录膨胀
            for d, w in list(seen.items()):
                if w.parent == tmp or tmp in w.parents:
                    tgt = dest / w.name
                    n = 1
                    while tgt.exists():
                        tgt = dest / f"{w.stem}_{n}{w.suffix}"
                        n += 1
                    shutil.move(str(w), str(tgt))
                    seen[d] = tgt
        if added or i % 40 == 0:
            print(f"  [{i}/{len(pats)}] {pat:<10} +{added:<4} 累计={len(seen)}", flush=True)

    shutil.rmtree(work, ignore_errors=True)
    total = len(list(dest.rglob("*.wav")))
    mb = sum(p.stat().st_size for p in dest.rglob("*.wav")) / 1024 / 1024
    print(f"\n完成: 共 {total} 个 wav, {mb:.1f} MB -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
