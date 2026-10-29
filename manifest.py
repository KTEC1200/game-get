#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifest.py —— manifest 契约的唯一实现（software-plan §2）。

为什么单独一个模块：`orchestrator.py`（通用链路）与 `krkr_auto_extract.py`（加密 krkr 专用链路）
都要产出同一份契约的 manifest。两份各写一遍必然漂移，而 manifest 是「交付清单」，
漂移了就等于两个工具对「交付了多少东西」说法不一致。

## counts 三段式（2026-10-29 定案）

| 段 | 含义 | 硬规矩 |
|---|---|---|
| `raw` | 解包器直接吐出来的东西，含待转格式（`.tlg` 等） | 必须能对上归档索引条目数；差 1 都不许过 |
| `final` | **交付口径**：raw 去掉被消费的中间格式，加上 `png/` 里的转换成品 | 报给用户看的就是这个数 |
| `converted` | 被后处理吃掉的中间格式计数，用来解释 `raw.total != final.total` | 没有后处理就是 `{}` |

实例（`高慢妻陥落！！`，2838 raw）：
    raw       = 2838（.ogg 1394 + .tlg 865 + .png 436 + …）
    final     = 2695（.ogg 1394 + .png 1301 + …）   ← 图片报 1301 而不是 436
    converted = {".tlg": 865}

## 为什么 `final` 要重新数而不是算减法

「raw.total - converted_total + png_total」在转换失败、同名覆盖、大小写冲突时都会算错。
一律**实际扫盘**，扫出来多少就是多少——数产物，不推产物。
"""
from __future__ import annotations

import json
from pathlib import Path

#: 后处理会「吃掉」的中间格式 —— raw 里有、final 里没有，差额由 converted 解释。
#: 目前只有 `.tlg`（tlg2png）；将来接 E-mote（`.pimg`/`.psb`）时加在这里。
CONVERTIBLE: set[str] = {".tlg"}

MANIFEST_VERSION = 1


# ---------------------------------------------------------------- 扫盘


def iter_final_files(raw_dir: Path, png_dir: Path,
                     convertible: set[str] | None = None) -> list[tuple[Path, str]]:
    """返回 `[(绝对路径, 相对标签)]` —— final 口径的全部交付文件。

    标签一律用 `/` 分隔（`as_posix()`）：manifest 要跨机器看/比对，
    Windows 的 `raw/sub\\c.ogg` 和 Linux 的 `raw/sub/c.ogg` 混在同一份文件里
    会让任何按标签做的比对都失败。
    """
    conv = CONVERTIBLE if convertible is None else convertible
    out: list[tuple[Path, str]] = []
    if raw_dir.is_dir():
        for p in sorted(raw_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() not in conv:
                out.append((p, f"raw/{p.relative_to(raw_dir).as_posix()}"))
    if png_dir.is_dir():
        for p in sorted(png_dir.rglob("*")):
            if p.is_file():
                out.append((p, f"png/{p.relative_to(png_dir).as_posix()}"))
    return out


def _tally(files: list[Path]) -> dict:
    by_ext: dict[str, int] = {}
    size = 0
    for p in files:
        ext = p.suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
        try:
            size += p.stat().st_size
        except OSError:
            pass
    return {"by_ext": dict(sorted(by_ext.items())), "total": len(files), "bytes": size}


def scan_raw(raw_dir: Path) -> dict:
    """raw 段：递归数全部文件（含待转格式）。"""
    files = [p for p in raw_dir.rglob("*") if p.is_file()] if raw_dir.is_dir() else []
    return _tally(files)


def scan_png(png_dir: Path) -> dict:
    """png/ 段：单独报一份，方便核对「转出多少张图」。"""
    files = [p for p in png_dir.rglob("*") if p.is_file()] if png_dir.is_dir() else []
    return _tally(files)


def counts(raw_dir: Path, png_dir: Path,
           convertible: set[str] | None = None) -> dict:
    """产出 counts 三段式：`{"raw": …, "final": …, "converted": …}`。"""
    conv = CONVERTIBLE if convertible is None else convertible
    raw = scan_raw(raw_dir)
    final_files = iter_final_files(raw_dir, png_dir, conv)
    final = _tally([p for p, _label in final_files])
    converted = {e: n for e, n in raw["by_ext"].items() if e in conv}
    return {"raw": raw, "final": final, "converted": converted}


# ---------------------------------------------------------------- 对账


def reconcile(expected: int | None, actual: int) -> dict:
    """对账块。

    `expected is None` 表示**没有地面真相可用**（例如加密 xp3 连 GARbro 都列不出条目）。
    这时 `diff` 也是 None，且带 `method` 说明原因 —— 不许把「没验」伪装成「验过了」。
    """
    if expected is None:
        return {"expected": None, "actual": actual, "diff": None,
                "method": "no-index-available"}
    return {"expected": expected, "actual": actual, "diff": actual - expected,
            "method": "archive-index"}


# ---------------------------------------------------------------- 落盘


def build(*, engine: str | None, source: dict, counts_block: dict,
          reconcile_block: dict, verify: dict, postprocess: list,
          png_dir: dict | None = None, stages: list | None = None,
          tool: str = "unknown", extra: dict | None = None) -> dict:
    """按契约拼一份 manifest（不落盘）。

    参数全部是纯数据，调用方各自填自己的阶段细节 —— 契约稳定，阶段信息自由。
    """
    import time as _time

    man: dict = {
        "manifest_version": MANIFEST_VERSION,
        "tool": tool,
        "engine": engine,
        "source": source,
        "counts": counts_block,
        "postprocess": postprocess,
        "verify": verify,
        "reconcile": reconcile_block,
        "png_dir": png_dir or {"total": 0, "by_ext": {}, "bytes": 0},
        "stages": stages or [],
        "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if extra:
        man.update(extra)
    return man


def write(path: Path, man: dict) -> Path:
    """把 manifest 写成 UTF-8 JSON（`ensure_ascii=False`，中日文路径原样可读）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python manifest.py <输出目录>   # 读 <目录>/manifest.json 并摘要")
        raise SystemExit(2)
    mp = Path(sys.argv[1])
    if mp.is_dir():
        mp = mp / "manifest.json"
    m = read(mp)
    c = m.get("counts", {})
    print(f"tool    : {m.get('tool')}  engine: {m.get('engine')}")
    for seg in ("raw", "final"):
        s = c.get(seg, {})
        print(f"{seg:<8}: {s.get('total')} 个文件 {s.get('bytes', 0)/1048576:.1f} MB "
              f"{s.get('by_ext')}")
    print(f"converted: {c.get('converted')}")
    r = m.get("reconcile", {})
    print(f"对账    : 期望 {r.get('expected')} vs 落盘 {r.get('actual')} "
          f"(diff={r.get('diff')}, method={r.get('method')})")
