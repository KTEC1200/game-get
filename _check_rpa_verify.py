#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对 _verify_media.py 的 CSV：区分「真媒体失败」与「非媒体文件误判」。"""
import collections
import csv
import pathlib

rows = list(csv.DictReader(open(r"D:\K\deepseek\_rpa_media.csv", encoding="utf-8-sig")))
fail = [r for r in rows if r["ok"] == "0"]
print("总行数:", len(rows), " 失败:", len(fail))
print()

print("==== 失败项按扩展名 ====")
c = collections.Counter(pathlib.Path(r["relpath"]).suffix.lower() or "<none>" for r in fail)
for k, v in c.most_common():
    print(f"  {k:<10} {v}")
print()

print("==== 真实媒体扩展名的通过/失败 ====")
media = {".avi", ".webm", ".mp4", ".mkv", ".mp3", ".ogg", ".wav", ".opus", ".flac"}
by = collections.defaultdict(lambda: [0, 0])
for r in rows:
    e = pathlib.Path(r["relpath"]).suffix.lower()
    if e in media:
        by[e][0 if r["ok"] == "1" else 1] += 1
for e, (ok, bad) in sorted(by.items()):
    print(f"  {e:<8} ok={ok:<5} fail={bad}")
print()

print("==== 通过项中 kind=video 的 codec 分布 ====")
print(" ", dict(collections.Counter(r["codec"] for r in rows if r["ok"] == "1" and r["kind"] == "video")))
print()

print("==== 失败的非媒体文件示例 ====")
for r in fail[:5]:
    print("  ", r["relpath"], "|", r["info"][:70])
