#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 AssetStudio 的 JSON 枚举做全量画像：音频分类 + 图片分类。

用法: python _as_catalog.py <JSON导出目录> [--csv out.csv]
只读。输出用于最终交付清单与 README。
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 音频命名规律（实测自本作）
def audio_kind(name: str) -> str:
    if re.fullmatch(r"V[ABC]\d+", name):
        return "语音(角色%s)" % name[1]
    if name.lower().startswith("bgm"):
        return "BGM"
    if re.fullmatch(r"(ADD|SEX|FE|SYASEI|sexyvoice|sex)\w*", name, re.I):
        return "成人音效"
    if re.fullmatch(r"SE_\w+", name, re.I):
        return "系统音效"
    return "音效/其他"


def image_kind(name: str) -> str:
    if re.fullmatch(r"CG\d+(_\d+)?", name):
        return "CG(Spine图集页)"
    if re.fullmatch(r"(wife|prison|ToDay|ToNight|Dance|Date|Massage|Money|Sing|Repent|Chat|Animate)(_\d+)?", name):
        return "剧情动画(Spine图集页)"
    if name.startswith("Background"):
        return "背景(分类)"
    if name.lower() in ("park", "castle", "hotel", "ninja", "japan", "knight",
                        "room1", "room2", "ntrback", "black", "white", "pink", "red"):
        return "背景"
    if name.startswith("Icon_") or name.startswith("Shop_Icon"):
        return "图标"
    if name.startswith("Button") or name.startswith("Frame") or name.startswith("Panel") \
       or name.startswith("Menu_") or name.startswith("Box") or name.startswith("Bar") \
       or name.startswith("Scroll") or name.startswith("Fill_"):
        return "UI"
    if name.startswith("Preview_"):
        return "商店预览"
    if name.startswith("Effect_"):
        return "特效"
    if name.startswith("fg_") or name.startswith("Elisa") or name.startswith("Icon_Logo"):
        return "立绘/其它"
    return "其他"


def main() -> int:
    d = Path(sys.argv[1])
    csv_out = None
    if "--csv" in sys.argv:
        csv_out = Path(sys.argv[sys.argv.index("--csv") + 1])

    aud = Counter()
    img = Counter()
    rows = []
    for p in d.rglob("*.json"):
        t = p.parent.name
        if t not in ("AudioClip", "Texture2D", "Sprite"):
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        name = j.get("m_Name") or j.get("Name") or p.stem
        if t == "AudioClip":
            k = audio_kind(name)
            aud[k] += 1
        else:
            k = image_kind(name)
            img[f"{t}:{k}"] += 1
        rows.append({"type": t, "name": name,
                     "kind": audio_kind(name) if t == "AudioClip" else image_kind(name)})

    print("==== 音频分类 (AudioClip) ====")
    tot = sum(aud.values())
    for k, v in aud.most_common():
        print(f"  {k:<18} {v:>5}  ({v/tot*100:.1f}%)")
    print(f"  {'合计':<18} {tot:>5}")

    print("\n==== 图片分类 (Texture2D / Sprite) ====")
    itot = sum(img.values())
    for k, v in img.most_common():
        print(f"  {k:<34} {v:>5}")
    print(f"  {'合计':<34} {itot:>5}")

    if csv_out:
        with csv_out.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=["type", "name", "kind"])
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: (r["type"], r["kind"], r["name"])))
        print(f"\n清单写入: {csv_out}  ({len(rows)} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
