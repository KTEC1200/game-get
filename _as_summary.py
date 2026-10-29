#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总 AssetStudio JSON 导出结果：按类型统计数量，并抽样看容器来源。

用法: python _as_summary.py <JSON导出目录>
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    d = Path(sys.argv[1])
    types = Counter()
    bytes_by_type = Counter()
    containers = Counter()
    samples = defaultdict(list)
    parse_err = 0

    for p in d.rglob("*.json"):
        t = p.parent.name
        types[t] += 1
        bytes_by_type[t] += p.stat().st_size
        if len(samples[t]) < 6:
            samples[t].append(p.name)
        try:
            j = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            parse_err += 1
            continue
        if isinstance(j, dict):
            c = j.get("m_Container") or j.get("container") or j.get("m_SourceFile")
            if isinstance(c, list) and c and t == "AssetBundle":
                for item in c[:3]:
                    if isinstance(item, dict):
                        containers[str(item.get("first") or item.get("Second"))] += 1

    print(f"目录: {d}")
    print(f"JSON 总数: {sum(types.values())}   解析失败: {parse_err}")
    print()
    print(f"{'type':<22}{'count':>8}{'MB':>10}   samples")
    print("-" * 96)
    for t, n in types.most_common():
        mb = bytes_by_type[t] / 1024 / 1024
        s = ", ".join(samples[t][:4])
        print(f"{t:<22}{n:>8}{mb:>10.2f}   {s[:60]}")
    if containers:
        print()
        print("AssetBundle 容器(前 20):")
        for c, n in containers.most_common(20):
            print(f"  {n:>4}  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
