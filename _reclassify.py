#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对已归档目录做「原地重分类」：按 _organize_rpa.classify 的规则把放错的文件移到正确分类目录。

用法: python _reclassify.py <已归档目录>
幂等：多次运行结果一致。会清理空目录。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _organize_rpa import classify  # noqa: E402

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    root = Path(sys.argv[1])
    # 已知分类目录名（用于识别「已归档」的层级）
    cats = {p.name for p in root.iterdir() if p.is_dir()}

    moved = 0
    for p in list(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        top = rel.parts[0]
        if top not in cats:
            continue  # 不在已知分类目录里，跳过
        # 还原成「包内相对路径」以便复用 classify
        inner = "/".join(rel.parts[1:])
        # Image_* 归档时剥掉了 images/ 前缀，这里补回去再判
        if top.startswith("Image_"):
            inner = "images/" + inner
        want = classify(inner)
        if want != top:
            # 目标子路径：沿用 inner（Image_* 仍剥前缀）
            sub = inner[len("images/"):] if want.startswith("Image_") and inner.startswith("images/") else inner
            tgt = root / want / sub
            tgt.parent.mkdir(parents=True, exist_ok=True)
            if tgt.exists():
                tgt = tgt.with_name(tgt.stem + "_dup" + tgt.suffix)
            shutil.move(str(p), str(tgt))
            moved += 1

    # 清理空目录
    for d in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: -len(str(x))):
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass

    print(f"重分类移动 {moved} 个文件\n")
    for d in sorted(x for x in root.iterdir() if x.is_dir()):
        f = [y for y in d.rglob("*") if y.is_file()]
        mb = sum(y.stat().st_size for y in f) / 1024 / 1024
        ext = {}
        for y in f:
            ext[y.suffix.lower()] = ext.get(y.suffix.lower(), 0) + 1
        es = ", ".join(f"{k}={v}" for k, v in sorted(ext.items(), key=lambda x: -x[1])[:5])
        print(f"  {d.name:<22} {len(f):>5} 个  {mb:>9.1f} MB  [{es}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
