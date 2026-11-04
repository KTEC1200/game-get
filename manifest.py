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
from typing import Mapping

#: 后处理会「吃掉」的中间格式 —— raw 里有、final 里没有，差额由 converted 解释。
#: 这是**唯一出处**：orchestrator 直接引用（`CONVERTIBLE = set(manifest.CONVERTIBLE)`），
#: 别在别处再写一份——两处各写一份，一边按 .tlg 算 final、另一边按 .tlg+.pna 算，交付数字就对不上。
#:   · `.tlg` —— tlg2png 转 PNG
#:   · `.pna` —— PNAP 多帧容器（AdvHD），按 PNG 签名→IEND 逐帧 carve 成多个 PNG
#: 将来接 E-mote（`.pimg`/`.psb`）时加在这里。
CONVERTIBLE: set[str] = {".tlg", ".pna"}

MANIFEST_VERSION = 1


# ---------------------------------------------------------------- 扫盘


def _excluded_set(raw_dir: Path, exclude) -> set:
    """把「被后处理消费掉的 raw 文件」统一成绝对路径集合。

    传进来的可以是绝对 `Path`、相对 `raw_dir` 的 `Path`，或者 `as_posix()` 字符串
    ——写后处理的人手上有哪种就用哪种，转换在这里做一次就够了。
    """
    if not exclude:
        return set()
    out = set()
    for item in exclude:
        p = Path(item)
        out.add(p if p.is_absolute() else (raw_dir / p))
    return out


def iter_final_files(raw_dir: Path, png_dir: Path,
                     convertible: set[str] | None = None,
                     exclude=None) -> list[tuple[Path, str]]:
    """返回 `[(绝对路径, 相对标签)]` —— final 口径的全部交付文件。

    标签一律用 `/` 分隔（`as_posix()`）：manifest 要跨机器看/比对，
    Windows 的 `raw/sub\\c.ogg` 和 Linux 的 `raw/sub/c.ogg` 混在同一份文件里
    会让任何按标签做的比对都失败。

    `convertible` 是**按扩展名**排除待转格式（`.tlg`/`.pna`）。
    `exclude` 是**按路径**排除被后处理消费掉的 raw 文件——CatSystem2 要用它：
    引擎会把扩展名二次混淆，raw 里同一个 `.hg3` 可能叫 `.KFX` 也可能叫 `.hg3`，
    照扩展名排除必然漏（漏掉的那几个就会以「还没转的中间产物」身份混进交付清单，
    而 counts 那边照样自洽，属于无声的错）。传路径就没有这个歧义。
    """
    conv = CONVERTIBLE if convertible is None else convertible
    skip = _excluded_set(raw_dir, exclude)
    out: list[tuple[Path, str]] = []
    if raw_dir.is_dir():
        for p in sorted(raw_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() not in conv and p not in skip:
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
           convertible: set[str] | None = None,
           exclude=None) -> dict:
    """产出 counts 三段式：`{"raw": …, "final": …, "converted": …}`。

    `raw` 永远是**全部**落盘文件（含待转格式、含被消费的中间产物）——对账要拿它跟索引比，
    少算一个就变成「两边都对不上但谁也没错」。`final` 才是交付口径。
    """
    conv = CONVERTIBLE if convertible is None else convertible
    raw = scan_raw(raw_dir)
    final_files = iter_final_files(raw_dir, png_dir, conv, exclude)
    final = _tally([p for p, _label in final_files])
    converted = {e: n for e, n in raw["by_ext"].items() if e in conv}
    return {"raw": raw, "final": final, "converted": converted}


# ---------------------------------------------------------------- 对账


def counts_flat(out_dir: Path) -> dict:
    """输出目录**就是**成品目录时的 counts（内联转换工具用）。

    有些解包器把格式转换做在落盘之前：`_rpgmv_decrypt.py` 的 `.rpgmvp` 落盘时已经是 `.png`，
    `_ypf_extract.py` 的 `.ycg` 直接落成 `.png`。磁盘上**根本不存在**中间格式，
    所以 `raw` 与 `final` 是同一份产物、`converted` 只能是 `{}`
    —— 硬造一个带 `.ycg`/`.rpgmvp` 的 raw 段就是编数据。

    转换明细（`.rpgmvp`→`.png` 多少个、YCG→PNG 多少个）由 `postprocess` 记录，
    那才是它该待的地方。

    注意：这里**不套用 `CONVERTIBLE`**。扁平工具的语义是「落盘即成品」，
    磁盘上不会留下待转格式；若某个工具需要「先落 raw 再后处理」，它就该用
    `raw/` + `png/` 两目录形态（走 `counts()`），不要用这个函数。
    """
    raw = scan_raw(out_dir)
    final = {"by_ext": dict(raw["by_ext"]), "total": raw["total"], "bytes": raw["bytes"]}
    return {"raw": raw, "final": final, "converted": {}}


# ---------------------------------------------------------------- 规范化
#
# 2026-11-04：`source.archives` 的键名在四条链路里各写各的
# （orchestrator 用 archive/expected/got，krkr 用 name/files/total_after，
#  cs2/unity/pfs 用 name/entries）。下游读 manifest 的人得按链路分支写兼容代码，
#  ——「同一份契约」就名存实亡了。这里定死**规范三键**，别名在入口一次翻译完。
#
# 语义必须分清（早前混用过的根源）：
#   entries   = **地面真相**（归档索引/枚举声明的条目数），没有就是 None
#   extracted = **实际落盘数**。加密 krkr 没有索引，只有实测新增数 —— 它属于 extracted，
#               绝不能塞进 entries，否则「没对过账」会看起来像「对上了」。

ARCHIVE_FIELDS = ("name", "entries", "extracted")

#: 规范名 ← 历史别名（按优先级）。改规范名等于改契约，必须同步 README 与测试。
_ARCHIVE_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "archive"),
    "entries": ("entries", "expected"),
    "extracted": ("extracted", "got", "files"),
}
_ALIAS_SET = {a for aliases in _ARCHIVE_ALIASES.values() for a in aliases}


def normalise_archives(items) -> list[dict]:
    """把任意链路的 `source.archives` 归一成 `{name, entries, extracted}`。

    三个规范键**总是存在**（没有就是 None），其余附加键（`listable`/`note`/
    `total_after` 等）原样保留 —— 归一化是为了让核心字段可预测，不是为了砍信息。
    非 Mapping 的条目原样丢弃：manifest 是交付记录，宁可少一条脏数据，
    也不要让下游拿到一个没法读的裸值。
    """
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        rec: dict = {}
        for canon in ARCHIVE_FIELDS:
            rec[canon] = None
            for alias in _ARCHIVE_ALIASES[canon]:
                if alias in item:
                    rec[canon] = item[alias]
                    break
        for k, v in item.items():
            if k not in _ALIAS_SET:
                rec[k] = v
        out.append(rec)
    return out


#: `verify.status` 的单值枚举（唯一出处）。消费方只认这一个字段判「验没验成」，
#: 不要再自己去拼 image_fail/audio_fail/... —— 那种拼法每加一类媒体就要改一次。
VERIFY_STATUSES = ("ok", "partial", "failed", "skipped")

#: 判定 status 所需要的基础失败计数（缺省补 None = 该链路没测这一项）。
_VERIFY_FAIL_FIELDS = ("image_fail", "audio_fail", "video_fail", "zero_byte")


def verify_status(verify: Mapping | None) -> str:
    """把 verify 块压成一个结论：ok / partial / failed / skipped。

    · `skipped` —— 没验：没有 verified 字段，或明确写了 reason=disabled/not-run。
      加密 KiriKiri 走 GUI 解包、本来就不验收，属于这一类，不是「验失败了」。
    · `failed`  —— 验了但没走完（取消 / 没有产物 / 验收阶段自身报错）。
    · `partial` —— 走完了，但有文件没过（`fail_total > 0`）。
    · `ok`      —— 走完了且失败为 0。

    优先用 `fail_total`（stage_verify 已经算好的总失败数，含零字节超护栏的那一条）；
    老 manifest 没有这个字段时退回三类媒体失败计数之和。
    """
    v = verify or {}
    if "verified" not in v:
        return "skipped"
    if not v.get("verified"):
        return "skipped" if v.get("reason") in ("disabled", "not-run") else "failed"
    total = v.get("fail_total")
    if isinstance(total, int):
        return "partial" if total > 0 else "ok"
    counted = [v.get(k) for k in ("image_fail", "audio_fail", "video_fail")]
    if any(isinstance(n, int) and n > 0 for n in counted):
        return "partial"
    return "ok"


def normalise_verify(verify: Mapping | None) -> dict:
    """补齐判定所需字段并写入 `status`（其余字段原样保留）。"""
    out: dict = dict(verify or {})
    for k in _VERIFY_FAIL_FIELDS:
        out.setdefault(k, None)
    out["status"] = verify_status(out)
    return out


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

    `source.archives` 与 `verify` 在这里统一规范化（`normalise_archives` /
    `normalise_verify`）：四条链路各写各的键名，下游就得按链路分支兼容；
    归一化放在**唯一出口**，新链路天然守规矩，不用每个作者记一遍。
    """
    import time as _time

    src = dict(source or {})
    if "archives" in src:
        src["archives"] = normalise_archives(src["archives"])

    man: dict = {
        "manifest_version": MANIFEST_VERSION,
        "tool": tool,
        "engine": engine,
        "source": src,
        "counts": counts_block,
        "postprocess": postprocess,
        "verify": normalise_verify(verify),
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
    v = m.get("verify", {})
    # status 对老 manifest 可能不存在：现场算一遍比显示 "?" 有用
    print(f"验收    : {v.get('status') or verify_status(v)}  "
          f"(图片 {v.get('image_ok')}/{v.get('image_fail')}失败, "
          f"音频 {v.get('audio_ok')}/{v.get('audio_fail')}失败, "
          f"视频 {v.get('video_ok')}/{v.get('video_fail')}失败)")
