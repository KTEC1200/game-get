#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按媒体类型归档产物（v0.7.0）：类目清单 CSV + 同盘硬链接视图。

为什么是「清单 + 链接」而不是把 `raw/` 里的文件搬走：
  1. **对账口径不能动**。`manifest.counts` 与 `reconcile` 全部以 `raw/` 为准，
     搬走文件会让「索引 7361 vs 落盘 7361」这条唯一的交付担保失效；
  2. **不占空间**。同一分区内硬链接只是目录项，不复制字节；真链接不上就如实报数，
     绝不偷偷改成复制（拷 100 GiB 会把用户的盘填满）；
  3. **分类规则只写一份**。坑 5 的教训：按目录判会把 `images/animations/` 下
     282 个 `.jpg` 分进视频。所以这里**扩展名优先**，认不出才退回路径里的目录名。

产物（都落在输出目录下）：
  `类目清单.csv`                 每行一个交付文件：类目,标签,扩展名,字节
  `分类/<图片|音频|视频|其他>/raw|png/…`   与 raw/png 同构的硬链接视图
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

#: 类目名（就是用户在资源管理器里看到的目录名，别改成英文）
IMAGE, AUDIO, VIDEO, OTHER = "图片", "音频", "视频", "其他"
KINDS = (IMAGE, AUDIO, VIDEO, OTHER)

#: 扩展名 → 类目。**扩展名优先**，这张表是唯一判据（大小写无关）。
EXT_KIND: dict[str, str] = {}
for _ext in ("png jpg jpeg bmp gif webp tga dds tif tiff avif jxl icc".split()):
    EXT_KIND[_ext] = IMAGE
for _ext in ("ogg wav mp3 flac m4a opus wma aac ape aiff aif mid midi".split()):
    EXT_KIND[_ext] = AUDIO
for _ext in ("mp4 webm avi wmv mkv mpg mpeg mov flv m4v ts".split()):
    EXT_KIND[_ext] = VIDEO

#: 扩展名认不出时，才看路径里有没有这些目录名（都是实测见过的归档命名）。
DIR_HINT = {
    "image": IMAGE, "images": IMAGE, "img": IMAGE, "cg": IMAGE, "tlg": IMAGE,
    "audio": AUDIO, "bgm": AUDIO, "voice": AUDIO, "se": AUDIO, "sound": AUDIO,
    "video": VIDEO, "videos": VIDEO, "movie": VIDEO, "movies": VIDEO, "mv": VIDEO,
}

#: 视图目录名与清单名（写死在这，不要在调用方再拼一遍）
VIEW_NAME = "分类"
CSV_NAME = "类目清单.csv"


def kind_of(label: str) -> str:
    """判断一个交付标签属于哪类。`label` 形如 `raw/sub/a.ogg` / `png/a.png`。

    规则：**先扩展名**（唯一可信的媒体本体），认不出再看路径目录名，最后落「其他」。
    """
    parts = label.replace("\\", "/").split("/")
    name = parts[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    for seg in reversed(parts[:-1]):
        hit = DIR_HINT.get(seg.lower())
        if hit:
            return hit
    return OTHER


def plan(files: list[tuple[Path, str]]) -> list[dict]:
    """把 `[(绝对路径, 标签)]` 变成归档计划（纯函数，不碰磁盘）。"""
    rows: list[dict] = []
    for src, label in files:
        normalised = label.replace("\\", "/")
        try:
            size = src.stat().st_size
        except OSError:
            size = -1               # 文件在枚举后消失：照样记一行，别静默丢
        rows.append({
            "kind": kind_of(normalised),
            "label": normalised,
            "ext": normalised.rsplit(".", 1)[-1].lower() if "." in normalised else "",
            "size": size,
            "src": src,
        })
    return rows


def write_csv(rows: list[dict], dst: Path) -> None:
    """写清单。用 `utf-8-sig`：中文表头在 Excel 里直接双击不会变乱码。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["类目", "相对路径", "扩展名", "字节"])
        for r in rows:
            w.writerow([r["kind"], r["label"], r["ext"], r["size"]])


def _view_root(out_dir: Path) -> Path:
    """视图目录：已有同名且非空时**不覆盖**，顺延成 `分类-2`、`分类-3`…"""
    base = out_dir / VIEW_NAME
    if not base.exists() or not any(base.iterdir()):
        return base
    for i in range(2, 10):
        cand = out_dir / f"{VIEW_NAME}-{i}"
        if not cand.exists() or not any(cand.iterdir()):
            return cand
    return out_dir / f"{VIEW_NAME}-{os.getpid()}"


def build_view(rows: list[dict], view_root: Path) -> tuple[int, int]:
    """按类目建硬链接（不复制）。返回 (成功数, 失败数)。"""
    ok = failed = 0
    for r in rows:
        dest = view_root / r["kind"] / r["label"]
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            os.link(r["src"], dest)
            ok += 1
        except OSError:
            # 跨卷/权限/源文件消失都在这里。**不退化成复制**：一次 100 GiB 的拷贝
            # 比少几个链接糟得多，而失败数会如实写进 manifest 与摘要。
            failed += 1
    return ok, failed


def organize(files: list[tuple[Path, str]], out_dir: Path) -> dict:
    """主入口：写清单 + 建视图，返回给 manifest/摘要用的统计。"""
    rows = plan(files)
    out_dir = Path(out_dir)
    write_csv(rows, out_dir / CSV_NAME)
    view_root = _view_root(out_dir)
    linked, failed = build_view(rows, view_root)
    counts = {k: 0 for k in KINDS}
    for r in rows:
        counts[r["kind"]] += 1
    return {
        "total": len(rows),
        "kinds": counts,
        "linked": linked,
        "failed": failed,
        "csv": str(out_dir / CSV_NAME),
        "view": str(view_root),
        "method": "hardlink",
    }
