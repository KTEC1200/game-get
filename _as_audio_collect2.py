#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 AssetStudio.CLI 导不全的 AudioClip 用「多轮 + 正则分组」的方式尽量收全。

背景（实测 2026-10-12，详见 verified-findings.md §8）:
  本作音频是 FSB5(FMOD Sample Bank 5) 容器，数据在外置 resources.resource 中。
  AssetStudio.CLI 单次导出 1183 个 AudioClip 时只有约 8 个落到磁盘，
  且日志里每个资产都打印 "Exporting AudioClip: X"、**没有任何报错**（静默失败）。
  但换成不同的 --names 分组、多跑几次时，每次都能再多成功一批
  => 失败与「运行内的处理顺序/规模」有关，可用分组反复跑来累积。

本轮策略: 用正则 alternation 把多个名字合并进一次运行，减少进程启动开销。
  第 1 轮: ^(VA0|VA1|...|VA9) 这类「前缀+首位」合并（每组 10 个）
  第 2 轮: 两两组合 (VA00|VA01|...) 进一步细分
  第 3 轮: 全名前缀粗分组兜底
每轮输出到独立目录，按文件内容哈希去重累积。

用法:
  python _as_audio_collect2.py <输入目录> <累积输出目录>
"""
import hashlib
import itertools
import shutil
import subprocess
import sys
from pathlib import Path

EXE = r"D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe"
VOICE_PREFIXES = ["VA", "VB", "VC", "FE", "SEX", "ADD", "SE", "bgm", "SYASEI",
                  "sexyvoice", "ding", "punch", "camera", "door", "cross", "sex"]


def rounds() -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []

    # 第 1 轮：前缀 + 首位数字（合并成一次运行）
    r1 = []
    for p in VOICE_PREFIXES:
        alts = "|".join(f"{p}{d}" for d in "0123456789")
        r1.append(f"^({alts})")
    r1.append(r"^[0-9]")
    for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
        r1.append(f"^{c}")
    out.append(("round1", r1))

    # 第 2 轮：前缀 + 前两位数字，两两合并
    r2 = []
    for p in ("VA", "VB", "VC"):
        pairs = [f"{p}{a}{b}" for a in "0123456789" for b in "0123456789"]
        for i in range(0, len(pairs), 2):
            alts = "|".join(pairs[i:i + 2])
            r2.append(f"^({alts})")
    out.append(("round2", r2))

    # 第 3 轮：单个两位前缀（更细）
    r3 = []
    for p in ("VA", "VB", "VC"):
        for a in "0123456789":
            for b in "0123456789":
                r3.append(f"^{p}{a}{b}")
    out.append(("round3", r3))
    return out


def digest(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    src, dest = Path(argv[0]), Path(argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    work = dest.parent / (dest.name + "_work")
    work.mkdir(parents=True, exist_ok=True)

    seen = {digest(p) for p in dest.rglob("*.wav")}
    print(f"起始已累积: {len(seen)}", flush=True)

    for rname, pats in rounds():
        print(f"\n=== {rname}: {len(pats)} 个模式 ===", flush=True)
        gained_total = 0
        for i, pat in enumerate(pats, 1):
            tmp = work / "cur"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    [EXE, str(src), str(tmp), "--game", "Normal",
                     "--types", "AudioClip", "--names", pat,
                     "--export_type", "Convert", "--group_assets", "ByType"],
                    capture_output=True, timeout=900)
            except subprocess.TimeoutExpired:
                print(f"  [{i}/{len(pats)}] TIMEOUT {pat[:40]}", flush=True)
                continue

            added = 0
            for w in list(tmp.rglob("*.wav")):
                d = digest(w)
                if d in seen:
                    continue
                seen.add(d)
                tgt = dest / w.name
                n = 1
                while tgt.exists():
                    tgt = dest / f"{w.stem}_{n}{w.suffix}"
                    n += 1
                shutil.move(str(w), str(tgt))
                added += 1
            gained_total += added
            if added:
                print(f"  [{i}/{len(pats)}] +{added:<4} 累计={len(seen)}   {pat[:46]}", flush=True)
        print(f"  {rname} 共新增 {gained_total}，累计 {len(seen)}", flush=True)
        if gained_total == 0 and rname == "round2":
            print("  连续无新增，提前结束", flush=True)
            break

    shutil.rmtree(work, ignore_errors=True)
    total = list(dest.rglob("*.wav"))
    mb = sum(p.stat().st_size for p in total) / 1024 / 1024
    print(f"\n完成: {len(total)} 个 wav, {mb:.1f} MB -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
