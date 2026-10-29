#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一媒体验收：图片（Pillow）、音频/视频（ffprobe）。

用法:
  python _verify_media.py <目录> [--csv out.csv]

按扩展名分流：
  .png/.jpg/.jpeg/.bmp/.webp/.gif  -> Pillow verify() + 尺寸
  其余（音频/视频）                 -> ffprobe 解出 codec/时长/分辨率
输出每类的 通过/失败 计数与失败清单，可选导出 CSV。
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

FFPROBE = r"D:\ffmpeg\bin\ffprobe.exe"
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tga"}
# 只有这些扩展名才送去 ffprobe。其余（.rpyc/.otf/.txt/.json…）不是媒体，
# 送去只会得到 "Invalid data found"，把验收结果搅浑（实测踩过，见 verified-findings.md §9.4）。
AV_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".mpg", ".mpeg",
          ".mp3", ".ogg", ".wav", ".opus", ".flac", ".m4a", ".aac", ".wma"}


def probe_av(p: Path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(p)],
            capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        return None, (err[-1][:140] if err else "ffprobe-failed")
    try:
        j = json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception as exc:
        return None, f"bad-json: {exc}"
    streams = j.get("streams") or []
    if not streams:
        return None, "no-streams"
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    s = v or a
    dur = j.get("format", {}).get("duration") or s.get("duration")
    return {
        "codec": s.get("codec_name"),
        "kind": "video" if v else "audio",
        "w": v.get("width") if v else None,
        "h": v.get("height") if v else None,
        "sr": a.get("sample_rate") if a else None,
        "dur": float(dur) if dur else None,
    }, None


def main() -> int:
    d = Path(sys.argv[1])
    csv_out = Path(sys.argv[sys.argv.index("--csv") + 1]) if "--csv" in sys.argv else None
    files = sorted(p for p in d.rglob("*") if p.is_file() and p.suffix)
    stats = Counter()
    fails: list[str] = []
    rows = []
    total_dur = Counter()
    dims = Counter()
    codecs = Counter()

    for i, p in enumerate(files, 1):
        ext = p.suffix.lower()
        if ext in IMG_EXT:
            try:
                from PIL import Image
                with Image.open(p) as im:
                    im.verify()
                with Image.open(p) as im:
                    w, h, fmt = im.size[0], im.size[1], im.format
                stats["image/ok"] += 1
                dims[f"{w}x{h}"] += 1
                rows.append({"relpath": str(p.relative_to(d)), "kind": "image",
                             "ok": 1, "codec": fmt, "info": f"{w}x{h}"})
            except Exception as exc:
                stats["image/fail"] += 1
                fails.append(f"[image] {p.relative_to(d)} :: {type(exc).__name__}: {exc}")
                rows.append({"relpath": str(p.relative_to(d)), "kind": "image",
                             "ok": 0, "codec": "", "info": str(exc)[:80]})
        elif ext not in AV_EXT:
            # 非媒体文件：不送 ffprobe，单独归类（不算失败）
            stats[f"nonmedia/{ext.lstrip('.') or 'noext'}"] += 1
            rows.append({"relpath": str(p.relative_to(d)), "kind": "nonmedia",
                         "ok": 1, "codec": "", "info": ""})
        else:
            info, err = probe_av(p)
            if info:
                stats[f"{info['kind']}/ok"] += 1
                codecs[f"{info['kind']}:{info['codec']}"] += 1
                if info["dur"]:
                    total_dur[info["kind"]] += info["dur"]
                if info["w"]:
                    dims[f"{info['w']}x{info['h']}"] += 1
                rows.append({"relpath": str(p.relative_to(d)), "kind": info["kind"],
                             "ok": 1, "codec": info["codec"],
                             "info": f"{info['dur']:.2f}s" if info["dur"] else ""})
            else:
                stats[f"av/fail"] += 1
                fails.append(f"[av] {p.relative_to(d)} :: {err}")
                rows.append({"relpath": str(p.relative_to(d)), "kind": "av",
                             "ok": 0, "codec": "", "info": err[:80]})
        if i % 500 == 0:
            print(f"  [{i}/{len(files)}] {dict(stats)}", flush=True)

    print()
    print("=" * 64)
    print(f"目录: {d}")
    print(f"文件总数: {len(files)}")
    for k in sorted(stats):
        print(f"  {k:<14} {stats[k]}")
    for k in sorted(total_dur):
        print(f"  {k} 总时长: {total_dur[k]/60:.1f} 分钟")
    print(f"编码分布: {dict(codecs)}")
    print("尺寸分布 (top 8):")
    for k, v in dims.most_common(8):
        print(f"    {k:<14} {v}")
    if fails:
        print(f"\n失败清单 (共 {len(fails)}，显示前 30):")
        for f in fails[:30]:
            print("  " + f)
    if csv_out:
        with csv_out.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=["relpath", "kind", "ok", "codec", "info"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n明细写入: {csv_out}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
