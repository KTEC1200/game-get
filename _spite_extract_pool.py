#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SPITE 字符串池提取 v4：反向行走找起点 + 三种引号感知的平衡扫描 + 自写元素解析。"""
import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
t = src.read_text(encoding="utf-8", errors="replace")
anchor_val = "spite-media://localhost/"
anchor_i = t.find(anchor_val)
assert anchor_i > 0

QUOTES = "\"'`"


def prev_string_open(close_pos: int) -> int | None:
    q = t[close_pos]
    k = close_pos - 1
    while k >= 0:
        if t[k] == q:
            n = 0
            m = k - 1
            while m >= 0 and t[m] == "\\":
                n += 1
                m -= 1
            if n % 2 == 0:
                return k
            k = m
        k -= 1
    return None


def balanced(start: int) -> int | None:
    depth = 0
    quote = None
    i = start
    while i < len(t):
        c = t[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        else:
            if c in QUOTES:
                quote = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


# 反向行走找数组起点
open_i = prev_string_open(anchor_i + len(anchor_val))
p = open_i
start = None
while p > 0:
    before = t[p - 1]
    if before == ",":
        j = p - 2
        while j >= 0 and t[j] in " \t\r\n":
            j -= 1
        if j < 0 or t[j] not in QUOTES:
            print(f"[诊断] 停 @ {p}: {t[max(0, j - 80):j + 20]!r}")
            break
        p = prev_string_open(j)
        if p is None:
            break
    elif before == "[":
        start = p - 1
        break
    else:
        print(f"[诊断] 停 @ {p}, before={before!r}: {t[max(0, p - 80):p + 20]!r}")
        break
if start is None:
    raise SystemExit("反向行走未找到数组起点")
print(f"起点 @ {start}，前文: {t[max(0, start - 40):start]!r}")
end = balanced(start)
print(f"终点 @ {end}（覆盖锚点: {end is not None and end > anchor_i}）")


def unescape_str(raw: str) -> str:
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            n = raw[i + 1]
            if n == "n":
                out.append("\n")
            elif n == "r":
                out.append("\r")
            elif n == "t":
                out.append("\t")
            elif n == "b":
                out.append("\b")
            elif n == "f":
                out.append("\f")
            elif n == "0":
                out.append("\0")
            elif n == "x" and i + 3 < len(raw):
                out.append(chr(int(raw[i + 2:i + 4], 16)))
                i += 2
            elif n == "u" and i + 5 < len(raw):
                out.append(chr(int(raw[i + 2:i + 6], 16)))
                i += 4
            else:
                out.append(n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


# 自写解析：元素 = 三种引号字符串；其余 token 跳过记 None
arr = []
i = start + 1
quote = None
buf = []
while i < end:
    c = t[i]
    if quote:
        if c == "\\":
            buf.append(c)
            buf.append(t[i + 1] if i + 1 < len(t) else "")
            i += 2
            continue
        if c == quote:
            raw = "".join(buf)
            if quote == "`":
                arr.append(raw)
            else:
                arr.append(unescape_str(raw))
            quote = None
            buf = []
        else:
            buf.append(c)
        i += 1
        continue
    if c in QUOTES:
        quote = c
        buf = []
        i += 1
        continue
    if c == ",":
        i += 1
        continue
    # 非字符串 token（数字/标识符等）：跳到下一个逗号或结尾
    j = i
    while j < end and t[j] not in ",[]":
        j += 1
    if j > i:
        arr.append(None)
    i = j if j > i else i + 1

print(f"解析条目 {len(arr)}，含锚点: {anchor_val in arr}")
if anchor_val in arr:
    ai = arr.index(anchor_val)
    print(f"锚点 0 基索引: {ai}")

K = None
for m in re.finditer(r"function ([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*)\)\{const ([A-Za-z_$][\w$]*)=([A-Za-z_$][\w$]*)\(\);return \3\[\2-(\d+)\]\}", t):
    K = int(m.group(5))
    print(f"解码器偏移 K = {K}")
    break
if K is not None:
    v = 3497 - K
    print(f"sanity: arr[{v}] = {arr[v]!r}" if 0 <= v < len(arr) else "sanity 越界")
out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pool.json")
out.write_text(json.dumps({"K": K, "pool": arr}, ensure_ascii=False), encoding="utf-8")
print(f"池已转存: {out}")
