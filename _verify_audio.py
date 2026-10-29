#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐个 ffprobe 校验音频：能解出编码/时长/采样率才算「可播放」。

用法: python _verify_audio.py <目录> [扩展名...]
只读。用于决策树 §6 验收判据 2「产物可开」。
"""
import json
import subprocess
import sys
from pathlib import Path

FFPROBE = r"D:\ffmpeg\bin\ffprobe.exe"


def probe(p: Path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(p)],
            capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if r.returncode != 0:
        return None, (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:120]
    try:
        j = json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception as exc:
        return None, f"bad-json: {exc}"
    streams = j.get("streams") or []
    if not streams:
        return None, "no-streams"
    s = streams[0]
    dur = j.get("format", {}).get("duration") or s.get("duration")
    return {
        "codec": s.get("codec_name"),
        "sr": s.get("sample_rate"),
        "ch": s.get("channels"),
        "dur": float(dur) if dur else None,
    }, None


def main() -> int:
    d = Path(sys.argv[1])
    exts = [e.lower() for e in (sys.argv[2:] or [".ogg"])]
    files = sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts)
    ok = bad = 0
    total_dur = 0.0
    fails = []
    codecs = {}
    for i, p in enumerate(files, 1):
        info, err = probe(p)
        if info:
            ok += 1
            codecs[info["codec"]] = codecs.get(info["codec"], 0) + 1
            if info["dur"]:
                total_dur += info["dur"]
        else:
            bad += 1
            fails.append(f"{p.relative_to(d)} :: {err}")
        if i % 200 == 0:
            print(f"  [{i}/{len(files)}] ok={ok} bad={bad}", flush=True)
    print()
    print("=" * 60)
    print(f"目录: {d}")
    print(f"音频文件: {len(files)}  可解码: {ok}  失败: {bad}")
    print(f"总时长: {total_dur/60:.1f} 分钟")
    print(f"编码分布: {codecs}")
    if fails:
        print("失败清单(前 30):")
        for f in fails[:30]:
            print("  " + f)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
