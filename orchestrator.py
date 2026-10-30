#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator.py —— detect → extract → postprocess → verify → manifest 一条命令跑完。

用法:
  python orchestrator.py <游戏目录> --out <输出目录> [选项]

选项:
  --out DIR            输出目录（必填；会建 raw/ png/ _work/ manifest.json）
  --work DIR           日志与中间产物目录（默认 <out>/_work）
  --manifest PATH      manifest 落地路径（默认 <out>/manifest.json）
  --engine NAME        跳过 detect，强制指定引擎
  --reuse-raw DIR      跳过 extract，直接复用已存在的 raw 产物（断点续传）
  --allow-gui          允许走 GUI 自动化链路（加密 KiriKiri，需真注入 + 拖拽，慢）
  --no-verify          跳过 verify 阶段（仅调试用；manifest 里会标记未验收）
  --strict             对账/验收任何不为 0 都以退出码 1 结束（默认也返回 1，此开关留作显式声明）
  --json PATH          额外把完整结果写成 JSON
  --dry-run            只做 detect + 计划，不动文件

退出码:
  0  全链通过（对账 0 差、验收 0 失败）
  1  有阶段失败 / 对账有差 / 验收有失败
  2  引擎判出来了但本阶段还没实现对应链路
  3  引擎没判出来

设计纪律（照 software-plan §2 与 AGENTS.md 归档纪律）:
  1. 地面真相优先：Ren'Py 用 RPA 索引条目数、KiriKiri 用 GARbro 列表行数，绝不拿工具退出码当真相。
  2. 对账必须到 0：raw 产物数 != 索引条目数 就判失败，不"差不多"。
  3. 验收看产物：图片走 Pillow verify()，音视频走 toolbridge.ffprobe（带扩展名白名单）。
  4. counts 分 raw / final / converted 三段（software-plan §2 定案）。
  5. 每个阶段都落日志到 _work/，失败时能只读日志复盘。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import galgame_dispatch as gd          # noqa: E402
import manifest                        # noqa: E402
import rpa_tool                        # noqa: E402
import toolbridge as tb                # noqa: E402
import _rpgmv_decrypt as rpgmv         # noqa: E402  （复用它的筛选常量，别抄第二份）
import _ypf_extract as ypf             # noqa: E402  （复用它的表解析，别抄第二份）
import _pna_carve as pna               # noqa: E402  （复用它的 carve()，别抄第二份）
import _grp_extract as grp             # noqa: E402  （复用它的 TOC 解析，别抄第二份）
import _cs2_int_extract as cs2         # noqa: E402  （复用它的地面真相/魔数识别，别抄第二份）

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 常量

#: 后处理会"吃掉"的中间格式 —— raw 里有、final 里没有，差额由 manifest.converted 解释。
#: **唯一出处是 `manifest.CONVERTIBLE`**，这里只做引用（两处各写一份必然漂移）。
CONVERTIBLE = set(manifest.CONVERTIBLE)

#: 图片类（Pillow 能验的）；与 `_verify_media.py` 一致，**外加 `.mos`**。
#: `.mos` 是 AdvHD 的图片容器，内容就是裸 PNG：2026-10-30 实测 `ラブラブお痴験バイト性活`
#: 677/677 全部以 PNG 魔数 `89 50 4e 47 0d 0a 1a 0a` 开头（verified-findings §13）。
#: 不列进来它们会被当「非媒体文件」静默放过，交付清单里就少验 677 张图。
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tga", ".mos"}

#: 只有这些才送 ffprobe（其余送进去只会得到 Invalid data，把结果搅浑）
AV_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".mpg", ".mpeg",
          ".mp3", ".ogg", ".wav", ".opus", ".flac", ".m4a", ".aac", ".wma"}

#: 已实现完整链路的引擎（其余判得出来但没链路 → 退出码 2）
IMPLEMENTED = ("Ren'Py", "KiriKiri", "RPG Maker", "Yu-Ris", "AdvHD", "ExHIBIT",
               "CatSystem2")


# ---------------------------------------------------------------- 结构

@dataclass
class Stage:
    name: str
    ok: bool = False
    seconds: float = 0.0
    detail: str = ""
    data: dict = field(default_factory=dict)
    skipped: bool = False

    def as_dict(self) -> dict:
        return {"stage": self.name, "ok": self.ok, "skipped": self.skipped,
                "seconds": round(self.seconds, 2), "detail": self.detail, **self.data}


@dataclass
class Ctx:
    game_dir: Path
    out_dir: Path
    work_dir: Path
    manifest_path: Path
    reuse_raw: Path | None = None
    allow_gui: bool = False
    do_verify: bool = True
    engine: str | None = None
    # 被后处理「消费掉」的 raw 文件（相对 raw_dir 的 posix 路径）。交付清单要排除它们，
    # 但**不能删**：raw 要留着跟索引对账（少一个就变成「两边都对不上」）。
    # CatSystem2 用它：HG-3 转出的 PNG 进了 png/，raw 里那份中间产物不该再算一次交付。
    # 按**路径**而不是按扩展名 —— 引擎把扩展名混淆过，照扩展名排除必然漏。
    consumed: list[str] = field(default_factory=list)

    @property
    def raw_dir(self) -> Path:
        return self.out_dir / "raw"

    @property
    def png_dir(self) -> Path:
        return self.out_dir / "png"

    def log(self, stage: str, text: str) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        with (self.work_dir / f"{stage}.log").open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip("\n") + "\n")


def _count(root: Path, exts: set[str] | None = None) -> tb.Products:
    return tb.count_products(root, exts)


def _by_ext_round(prod: tb.Products) -> dict:
    return {k: v for k, v in sorted(prod.by_ext.items())}


# ---------------------------------------------------------------- 阶段 1: detect

def stage_detect(ctx: Ctx) -> Stage:
    st = Stage("detect")
    t0 = time.time()
    try:
        rep = gd.scan(ctx.game_dir)
    except Exception as exc:                                   # noqa: BLE001
        st.detail = f"detect 异常: {type(exc).__name__}: {exc}"
        st.seconds = time.time() - t0
        return st
    best = rep.best
    st.data = {
        "engine": best.engine if best else None,
        "score": best.score if best else 0,
        "above_threshold": bool(best and best.score >= gd.THRESHOLD),
        "guesses": [{"engine": g.engine, "score": g.score} for g in rep.guesses[:4]],
        "notes": rep.notes,
    }
    ctx.log("detect", json.dumps(st.data, ensure_ascii=False, indent=2))
    st.seconds = time.time() - t0
    if not best or best.score < gd.THRESHOLD:
        st.detail = "未命中任何引擎（低于阈值 %d）" % gd.THRESHOLD
        return st
    st.ok = True
    st.detail = f"{best.engine} (score={best.score})"
    return st


# ---------------------------------------------------------------- 阶段 2: extract

def _renpy_archives(game_dir: Path) -> list[Path]:
    """找 .rpa。顶层优先；顶层没有才递归（有的游戏把包放 game/ 子目录）。"""
    top = sorted(p for p in game_dir.glob("*.rpa") if p.is_file())
    if top:
        return top
    return sorted(p for p in game_dir.rglob("*.rpa") if p.is_file())


def _renpy_expected(archive: Path) -> int:
    """地面真相：归档里**去重后**的路径数（多段条目按名字合并成一个文件）。"""
    index, _ver, _off, key = rpa_tool.load_index(archive)
    names = {name for name, _o, _ln in rpa_tool.iter_entries(index, key)}
    return len(names)


def stage_extract_renpy(ctx: Ctx) -> Stage:
    st = Stage("extract")
    t0 = time.time()
    archives = _renpy_archives(ctx.game_dir)
    if ctx.reuse_raw:
        # 复用模式：不重新解包，但**仍然算地面真相**，对账不能因为跳步就失效
        st.skipped = True
        st.detail = f"复用已有 raw: {ctx.reuse_raw}"
        st.data = {"reused_from": str(ctx.reuse_raw)}
        if archives:
            try:
                expected = sum(_renpy_expected(a) for a in archives)
                actual = _count(ctx.raw_dir).total
                st.data.update({"expected_total": expected, "actual_total": actual,
                                "reconcile_ok": actual == expected,
                                "archives": [{"archive": a.name, "expected": None,
                                              "got": None} for a in archives]})
                if actual != expected:
                    st.detail = f"复用产物对账失败：索引 {expected} vs 落盘 {actual}"
                    st.seconds = time.time() - t0
                    return st
            except Exception as exc:                            # noqa: BLE001
                st.detail += f"（对账跳过：读索引失败 {type(exc).__name__}）"
        st.ok = True
        st.seconds = time.time() - t0
        return st

    if not archives:
        st.detail = "没找到任何 .rpa 归档"
        st.seconds = time.time() - t0
        return st

    expected_total = 0
    per_archive = []
    for arc in archives:
        try:
            expected = _renpy_expected(arc)
        except Exception as exc:                               # noqa: BLE001
            st.detail = f"读索引失败 {arc.name}: {type(exc).__name__}: {exc}"
            st.seconds = time.time() - t0
            return st
        expected_total += expected
        dest = ctx.raw_dir / arc.stem
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "rpa_extract_organized.py"),
             str(arc), str(dest)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        ctx.log("extract", f"$ rpa_extract_organized.py {arc.name} -> {dest}\n"
                           f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        got = _count(dest).total if dest.is_dir() else 0
        per_archive.append({"archive": arc.name, "expected": expected, "got": got,
                            "rc": proc.returncode})
        if proc.returncode != 0 or got != expected:
            st.detail = (f"{arc.name}: 对账失败 期望 {expected} 实得 {got} "
                         f"(rc={proc.returncode})")
            st.data = {"archives": per_archive}
            st.seconds = time.time() - t0
            return st

    actual_total = _count(ctx.raw_dir).total
    st.data = {
        "archives": per_archive,
        "expected_total": expected_total,
        "actual_total": actual_total,
        "reconcile_ok": actual_total == expected_total,
    }
    st.seconds = time.time() - t0
    if actual_total != expected_total:
        st.detail = f"总对账失败：索引 {expected_total} vs 落盘 {actual_total}"
        return st
    st.ok = True
    st.detail = f"{len(archives)} 个归档，{actual_total} 个文件，对账 0 差"
    return st


def _kirikiri_xp3(game_dir: Path) -> list[Path]:
    top = sorted(p for p in game_dir.glob("*.xp3") if p.is_file())
    if top:
        return top
    return sorted(p for p in game_dir.rglob("*.xp3") if p.is_file())


def stage_extract_kirikiri(ctx: Ctx) -> Stage:
    """KiriKiri 提取。

    先探 GARbro：能列目录 = 静态可解，直接 `-x`；
    列不出 = 可能加密（坑 1 提醒 Console 有假阴性，所以这里只是"可能"），
    此时若给了 --allow-gui 就走 krkr_auto_extract.py，否则报建议并停。
    """
    st = Stage("extract")
    t0 = time.time()
    if ctx.reuse_raw:
        # 复用模式：不重新解包，但**仍然算地面真相** —— 对账不能因为跳步就失效。
        # 加密 xp3 列不出条目时 expected 保持 None（manifest 会标 no-index-available）。
        st.skipped = True
        st.ok = True
        st.detail = f"复用已有 raw: {ctx.reuse_raw}"
        actual = _count(ctx.raw_dir).total
        st.data = {"reused_from": str(ctx.reuse_raw), "actual_total": actual}
        xp3s = _kirikiri_xp3(ctx.game_dir)
        if xp3s:
            expected = 0
            listable = True
            per_archive = []
            for xp3 in xp3s:
                ok, entries, _out = tb.garbro_list(xp3)
                if not ok:
                    listable = False
                    per_archive.append({"archive": xp3.name, "expected": None,
                                        "got": None, "listable": False})
                    continue
                expected += entries
                per_archive.append({"archive": xp3.name, "expected": entries,
                                    "got": None, "listable": True})
            st.data["archives"] = per_archive
            if listable:
                st.data["expected_total"] = expected
                if actual != expected:
                    st.detail = f"复用产物对账失败：索引 {expected} vs 落盘 {actual}"
                    st.ok = False
                    st.seconds = time.time() - t0
                    return st
                st.detail = f"复用已有 raw，对账 {expected} == {actual}"
        st.seconds = time.time() - t0
        return st

    xp3s = _kirikiri_xp3(ctx.game_dir)
    if not xp3s:
        st.detail = "没找到任何 .xp3"
        st.seconds = time.time() - t0
        return st

    # 用最大的 xp3 做探针（最大的那个最可能是 data.xp3）
    probe = max(xp3s, key=lambda p: p.stat().st_size)
    ok_probe, n_probe, out_probe = tb.garbro_list(probe)
    ctx.log("extract", f"probe {probe.name}: ok={ok_probe} lines={n_probe}\n{out_probe[:2000]}")
    st.data = {"probe": {"archive": probe.name, "listable": ok_probe, "lines": n_probe}}

    if not ok_probe:
        # 静态读不出 → 可能加密。坑 1：Console 假阴性存在，所以只说"可能"
        if not ctx.allow_gui:
            st.detail = ("GARbro 列不出目录（可能是加密 xp3，也可能是 Console 假阴性）。"
                         "加密链路需 GUI 自动化（约 40 分钟），确认后加 --allow-gui 重跑。")
            st.seconds = time.time() - t0
            return st
        script = Path(__file__).parent / "krkr_auto_extract.py"
        proc = subprocess.run(
            [sys.executable, str(script), str(ctx.game_dir), "--out", str(ctx.out_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        ctx.log("extract", f"$ krkr_auto_extract.py rc={proc.returncode}\n"
                           f"{proc.stdout}\n{proc.stderr}")
        # krkr_auto_extract 产出 <out>/KrkrExtract_Output/{data,png}
        kout = ctx.out_dir / "KrkrExtract_Output"
        if not kout.is_dir():
            st.detail = f"GUI 链路没有产出 KrkrExtract_Output (rc={proc.returncode})"
            st.seconds = time.time() - t0
            return st
        data_dir = kout / "data" if (kout / "data").is_dir() else kout
        if ctx.raw_dir.exists():
            shutil.rmtree(ctx.raw_dir, ignore_errors=True)
        shutil.move(str(data_dir), str(ctx.raw_dir))
        if (kout / "png").is_dir():
            shutil.move(str(kout / "png"), str(ctx.png_dir))
        st.ok = True
        st.data.update({"mode": "gui", "raw_total": _count(ctx.raw_dir).total})
        st.detail = f"GUI 链路完成，raw {st.data['raw_total']} 个文件"
        st.seconds = time.time() - t0
        return st

    # 静态可解：逐包 garbro -x，产出落到 raw/<stem>/
    per_archive = []
    expected_total = 0
    for xp3 in xp3s:
        ok, entries, out = tb.garbro_list(xp3)
        if not ok:
            per_archive.append({"archive": xp3.name, "expected": None, "got": 0,
                                "listable": False})
            continue
        expected_total += entries
        dest = ctx.raw_dir / xp3.stem
        res = tb.garbro_extract(xp3, dest)
        ctx.log("extract", f"$ garbro -x {xp3.name}\n{res.summary()}\n{res.stdout[-2000:]}")
        got = _count(dest).total
        per_archive.append({"archive": xp3.name, "expected": entries, "got": got,
                            "rc": res.returncode, "ok": res.ok})
        if not res.ok:
            st.detail = f"{xp3.name}: GARbro 提取失败 ({res.reason})"
            st.data["archives"] = per_archive
            st.seconds = time.time() - t0
            return st

    actual_total = _count(ctx.raw_dir).total
    st.data.update({"mode": "static", "archives": per_archive,
                    "expected_total": expected_total, "actual_total": actual_total,
                    "reconcile_ok": actual_total == expected_total})
    st.seconds = time.time() - t0
    if actual_total != expected_total:
        st.detail = f"对账失败：GARbro 条目 {expected_total} vs 落盘 {actual_total}"
        return st
    st.ok = True
    st.detail = f"{len(xp3s)} 个 xp3，{actual_total} 个文件，对账 0 差"
    return st


# ---------------------------------------------------------------- RPG Maker / Yu-Ris

def _find_www(game_dir: Path) -> Path | None:
    """定位 www/。与 `_rpgmv_decrypt.find_www()` 同一判据，但这里返回 None 而不是退出。"""
    if (game_dir / "data" / "System.json").is_file():
        return game_dir
    if (game_dir / "www" / "data" / "System.json").is_file():
        return game_dir / "www"
    for p in game_dir.rglob("System.json"):
        if p.parent.name == "data" and p.parent.parent.name == "www":
            return p.parent.parent
    return None


def stage_extract_rpgmaker(ctx: Ctx) -> Stage:
    """RPG Maker MV/MZ：跑 `_rpgmv_decrypt.py`，对账地面真相 = 候选文件数。

    地面真相取自 `rpgmv.expected_total(www)`——**与解包器共用同一个筛选函数**。
    另写一份筛选逻辑的话，一边算 7 个候选、另一边写 6 个文件，谁也说不清谁错。
    """
    st = Stage("extract")
    t0 = time.time()
    www = _find_www(ctx.game_dir)
    if www is None:
        st.detail = "找不到 www/（或 www/data/System.json）"
        st.seconds = time.time() - t0
        return st

    try:
        expected = rpgmv.expected_total(www)
    except Exception as exc:                                   # noqa: BLE001
        st.detail = f"数候选文件失败：{type(exc).__name__}: {exc}"
        st.seconds = time.time() - t0
        return st

    if ctx.reuse_raw:
        st.skipped = True
        st.ok = True
        actual = _count(ctx.raw_dir).total
        st.data = {"reused_from": str(ctx.reuse_raw), "expected_total": expected,
                   "actual_total": actual, "reconcile_ok": actual == expected}
        if actual != expected:
            st.ok = False
            st.detail = f"复用产物对账失败：候选 {expected} vs 落盘 {actual}"
        else:
            st.detail = f"复用已有 raw，对账 {expected} == {actual}"
        st.seconds = time.time() - t0
        return st

    man = ctx.work_dir / "rpgmv.manifest.json"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "_rpgmv_decrypt.py"),
         str(www), str(ctx.raw_dir), "--manifest", str(man)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ctx.log("extract", f"$ _rpgmv_decrypt.py {www} -> {ctx.raw_dir}\n"
                       f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    actual = _count(ctx.raw_dir).total
    st.data = {"www": str(www), "expected_total": expected, "actual_total": actual,
               "reconcile_ok": actual == expected, "rc": proc.returncode,
               "archives": [{"archive": str(www.name), "expected": expected,
                             "got": actual}]}
    st.seconds = time.time() - t0
    if actual != expected:
        st.detail = f"对账失败：候选 {expected} vs 落盘 {actual} (rc={proc.returncode})"
        return st
    st.ok = True
    st.detail = f"{actual} 个文件，对账 0 差"
    return st


def _ypf_archives(game_dir: Path) -> list[Path]:
    top = sorted(p for p in game_dir.glob("*.ypf") if p.is_file())
    if top:
        return top
    return sorted(p for p in game_dir.rglob("*.ypf") if p.is_file())


def stage_extract_yuris(ctx: Ctx) -> Stage:
    """Yu-Ris：逐 .ypf 跑 `_ypf_extract.py`，对账地面真相 = 表内条目数。

    条目数取自 `_ypf_extract.read_index()`——与解包器共用同一份表解析。
    """
    st = Stage("extract")
    t0 = time.time()
    ypfs = _ypf_archives(ctx.game_dir)
    if not ypfs:
        st.detail = "没找到任何 .ypf 归档"
        st.seconds = time.time() - t0
        return st

    expected_total = 0
    per_archive = []
    for arc in ypfs:
        try:
            _ver, entries, _key, _data = ypf.read_index(arc)
        except Exception as exc:                               # noqa: BLE001
            st.detail = f"读索引失败 {arc.name}: {type(exc).__name__}: {exc}"
            st.data = {"archives": per_archive}
            st.seconds = time.time() - t0
            return st
        expected = len(entries)
        expected_total += expected
        per_archive.append({"archive": arc.name, "expected": expected,
                            "got": None, "ok": None})

    if ctx.reuse_raw:
        st.skipped = True
        st.ok = True
        actual = _count(ctx.raw_dir).total
        st.data = {"reused_from": str(ctx.reuse_raw), "archives": per_archive,
                   "expected_total": expected_total, "actual_total": actual,
                   "reconcile_ok": actual == expected_total}
        if actual != expected_total:
            st.ok = False
            st.detail = f"复用产物对账失败：索引 {expected_total} vs 落盘 {actual}"
        else:
            st.detail = f"复用已有 raw，对账 {expected_total} == {actual}"
        st.seconds = time.time() - t0
        return st

    for rec, arc in zip(per_archive, ypfs):
        dest = ctx.raw_dir / arc.stem
        man = ctx.work_dir / f"{arc.stem}.manifest.json"
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "_ypf_extract.py"),
             str(arc), str(dest), "--manifest", str(man)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        ctx.log("extract", f"$ _ypf_extract.py {arc.name} -> {dest}\n"
                           f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        got = _count(dest).total if dest.is_dir() else 0
        rec.update({"got": got, "rc": proc.returncode, "ok": got == rec["expected"]})
        if got != rec["expected"]:
            st.detail = (f"{arc.name}: 对账失败 期望 {rec['expected']} 实得 {got} "
                         f"(rc={proc.returncode})")
            st.data = {"archives": per_archive}
            st.seconds = time.time() - t0
            return st

    actual_total = _count(ctx.raw_dir).total
    st.data = {"archives": per_archive, "expected_total": expected_total,
               "actual_total": actual_total,
               "reconcile_ok": actual_total == expected_total}
    st.seconds = time.time() - t0
    if actual_total != expected_total:
        st.detail = f"总对账失败：索引 {expected_total} vs 落盘 {actual_total}"
        return st
    st.ok = True
    st.detail = f"{len(ypfs)} 个 ypf，{actual_total} 个文件，对账 0 差"
    return st


# ---------------------------------------------------------------- AdvHD

def _advhd_arcs(game_dir: Path) -> list[Path]:
    """顶层 `*.arc` 优先，顶层没有才递归（与 `_kirikiri_xp3` 同一策略）。"""
    top = sorted(p for p in game_dir.glob("*.arc") if p.is_file())
    if top:
        return top
    return sorted(p for p in game_dir.rglob("*.arc") if p.is_file())


def _advhd_loose_movies(game_dir: Path) -> list[tuple[Path, Path]]:
    """游戏根目录的散装 `.dat`（OP/ED）= ASF/WMV 裸流，返回 `[(源, 目标)]`。

    只扫**顶层**：递归会把 `save/`、配置目录里的 `.dat` 一并当视频抓进来。
    目标一律改成 `.wmv` —— `.dat` 不在 `AV_EXT` 白名单里，verify 会当「非媒体文件」
    放过去，交付清单里就留一个谁都验不了的 `.dat`（历史 `_advhd_run.py` 也是复制成 `.wmv`，
    头 GUID `30 26 b2 75` 即 ASF，实测成立）。
    """
    return [(p, p.with_suffix(".wmv")) for p in sorted(game_dir.glob("*.dat")) if p.is_file()]


def stage_extract_advhd(ctx: Ctx) -> Stage:
    """AdvHD：GARbro 逐 `.arc` 提取 + 散装 `.dat` → `.wmv`，按索引条目数对账。

    地面真相 = `tb.garbro_list()` 的条目数（GARbro 列表**无表头**，这条口径由 toolbridge
    统一处理，**别在这里另写解析**——历史上 `len(lines)-1` 让每包少算 1，对账永远不过）
    + 散装 `.dat` 的个数（每个 `.dat` 必然产出且只产出一个 `.wmv`）。

    `.pna`（PNAP 多帧容器）GARbro 不认、原样吐出，交给 postprocess 逐帧 carve。
    """
    st = Stage("extract")
    t0 = time.time()
    arcs = _advhd_arcs(ctx.game_dir)
    movies = _advhd_loose_movies(ctx.game_dir)
    if not arcs and not movies:
        st.detail = "既没有 .arc 也没有 .dat"
        st.seconds = time.time() - t0
        return st

    if ctx.reuse_raw:
        # 复用模式：不重新解包，但**仍然算地面真相** —— 对账不能因为跳步就失效。
        st.skipped = True
        st.ok = True
        st.detail = f"复用已有 raw: {ctx.reuse_raw}"
        actual = _count(ctx.raw_dir).total
        st.data = {"reused_from": str(ctx.reuse_raw), "actual_total": actual,
                   "loose_movies": len(movies)}
        expected, listable, per_archive = _advhd_expected(arcs, reuse_raw=ctx.raw_dir,
                                                          movie_n=len(movies))
        st.data["archives"] = per_archive
        if listable:
            st.data["expected_total"] = expected
            if actual != expected:
                st.detail = f"复用产物对账失败：索引 {expected} vs 落盘 {actual}"
                st.ok = False
                st.seconds = time.time() - t0
                return st
            st.detail = f"复用已有 raw，对账 {expected} == {actual}"
        st.seconds = time.time() - t0
        return st

    # 1) 散装 .dat → raw/*.wmv（在 .arc 之前做，目录先建好）
    ctx.raw_dir.mkdir(parents=True, exist_ok=True)
    for src, dst_name in movies:
        dst = ctx.raw_dir / dst_name.name
        if not dst.exists():
            shutil.copy2(src, dst)
        ctx.log("extract", f"[视频] {src.name} ({src.stat().st_size / 1024 / 1024:.1f}MB)"
                           f" → raw/{dst.name}")

    # 2) 逐 .arc 提取，产出落到 raw/<stem>/
    per_archive: list[dict] = []
    expected_total = len(movies)
    listable = True
    for arc in arcs:
        ok_list, n_idx, out = tb.garbro_list(arc)
        if not ok_list:
            listable = False
            per_archive.append({"archive": arc.name, "expected": None, "got": None,
                                "listable": False})
            ctx.log("extract", f"  {arc.name}: 列不出条目（{out.strip()[:100]}）")
            continue
        expected_total += n_idx
        dest = ctx.raw_dir / arc.stem
        res = tb.garbro_extract(arc, dest)
        ctx.log("extract", f"$ garbro -x {arc.name}\n{res.summary()}")
        got = _count(dest).total
        per_archive.append({"archive": arc.name, "expected": n_idx, "got": got,
                            "rc": res.returncode, "ok": res.ok})
        if not res.ok:
            st.detail = f"{arc.name}: GARbro 提取失败（{res.reason}）"
            st.data = {"archives": per_archive}
            st.seconds = time.time() - t0
            return st

    actual_total = _count(ctx.raw_dir).total
    st.data = {"mode": "static", "archives": per_archive,
               "loose_movies": len(movies), "actual_total": actual_total}
    st.seconds = time.time() - t0
    if not listable:
        # 有包列不出 = 没有完整地面真相，明说，别假装对过账
        st.ok = True
        st.data["reason"] = "有 .arc 列不出条目，无完整地面真相，未对账"
        st.detail = (f"{len(arcs)} 个 arc 中有的列不出条目，落盘 {actual_total} 个文件，未对账")
        return st
    st.data["expected_total"] = expected_total
    if actual_total != expected_total:
        st.detail = f"对账失败：索引 {expected_total} vs 落盘 {actual_total}"
        return st
    st.ok = True
    st.detail = (f"{len(arcs)} 个 arc + {len(movies)} 个 dat，"
                 f"{actual_total} 个文件，对账 0 差")
    return st


def _advhd_expected(arcs: list[Path], *, reuse_raw: Path | None = None,
                    movie_n: int = 0) -> tuple[int, bool, list[dict]]:
    """算 AdvHD 的期望落盘数：`arcs` 条目数之和 + 散装 `.dat` 个数。

    返回 `(期望总数, 是否全部可列, 逐包明细)`。抽出来是因为正常路径与 `--reuse-raw`
    路径都要算同一件事，抄两份必然漂移。
    """
    expected = movie_n
    listable = True
    per_archive: list[dict] = []
    for arc in arcs:
        ok, n_idx, out = tb.garbro_list(arc)
        if not ok:
            listable = False
            per_archive.append({"archive": arc.name, "expected": None, "got": None,
                                "listable": False})
            continue
        expected += n_idx
        got = None
        if reuse_raw is not None:
            dest = reuse_raw / arc.stem
            got = _count(dest).total if dest.is_dir() else 0
        per_archive.append({"archive": arc.name, "expected": n_idx, "got": got,
                            "listable": True})
    return expected, listable, per_archive


# ---------------------------------------------------------------- ExHIBIT（.gyu / .grp）

#: ExHIBIT 的散装媒体后缀（不在 `.grp` 里的裸媒体）。
_EXHIBIT_LOOSE_EXT = (".wav", ".wmv")


def _head(p: Path, n: int = 4) -> bytes:
    """只读文件头 n 字节（**别用 `p.read_bytes()[:4]`**：`.grp` 动辄 400 MB）。"""
    try:
        with p.open("rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def _exhibit_gyu(game_dir: Path) -> list[Path]:
    """游戏目录下全部 `*.gyu`（图片）。

    实测本作 2184 个 = `res/g/` 2154 + `userdata/thumbnail/` 30，两处都要解
    （缩略图也算交付物，§15.4 的 2184 就是这么来的）。
    """
    return sorted(p for p in game_dir.rglob("*.gyu") if p.is_file())


def _exhibit_res_dir(game_dir: Path) -> Path | None:
    """`.grp` 与 TOC 所在的目录（本作是 `res/`）。"""
    for cand in (game_dir / "res", game_dir):
        if cand.is_dir() and list(cand.glob("res[0-9]*.grp")):
            return cand
    return None


def _exhibit_ogg_is_encrypted(p: Path) -> bool:
    """BGM 是否加密未破：**加密的 `.ogg` 头不是 `OggS`**。

    本作 `res/s/m/*.ogg` 的 `[0,3853)` 被加密，所以魔数直接没了（§15.3）。
    用魔数判据而不是写死路径：换一作时路径可能不同，但「加密的认不出 OggS」
    这条不会变，也不会把某个明文 ogg 误当加密丢掉。
    """
    return _head(p) != b"OggS"


def _exhibit_loose_media(game_dir: Path) -> list[tuple[Path, Path]]:
    """散装媒体，返回 `[(源, 相对 raw 的目标)]`。

    目标保持游戏内相对路径（`raw/loose/res/s/e/015.wav`）——出问题时能一眼看出
    它原来在哪，也不会与 `.grp` 切出来的 `raw/audio/` 撞名。
    """
    out: list[tuple[Path, Path]] = []
    for p in sorted(game_dir.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in _EXHIBIT_LOOSE_EXT or (ext == ".ogg" and not _exhibit_ogg_is_encrypted(p)):
            out.append((p, Path("loose") / p.relative_to(game_dir)))
    return out


def _exhibit_encrypted_ogg(game_dir: Path) -> list[Path]:
    """加密未破的 BGM（`res/s/m/*.ogg`，§15.3）。

    解密器挂在 loader 的 `this+0x70` 的 vtable[0]，构造点是**外部安装**，
    静态追不到安装点；内存 dump 需要用户玩到标题画面配合 → 目前无解。

    这些文件**不进 raw**：复制过去只会让 verify 报 N 个失败，而它们不是「解包
    失败」，是「还没解开」。但**必须显式报出来**——`.mos` 那次的教训是：
    无声的漏项最危险，verify 失败数 0 并不代表交付完整。
    """
    return sorted(p for p in game_dir.rglob("*.ogg")
                  if p.is_file() and _exhibit_ogg_is_encrypted(p))


def _exhibit_expected(game_dir: Path, *,
                      raw_dir: Path | None = None) -> tuple[int, bool, list[dict]]:
    """算 ExHIBIT 的期望落盘数：`.gyu` 个数 + `.grp` 条目数 + 散装媒体个数。

    返回 `(期望总数, 是否全部可列, 逐项明细)`。抽出来是因为正常路径与 `--reuse-raw`
    路径都要算同一件事，抄两份必然漂移。地面真相：`.gyu` 是「一个文件必出一张图」，
    `.grp` 是 TOC 里 `size != 0` 的条目数（`grp.expected_counts()`，**唯一出处**），
    散装媒体是「一个文件必出一个文件」。
    """
    per_archive: list[dict] = []
    expected = 0
    listable = True

    gyus = _exhibit_gyu(game_dir)
    got_gyu = None
    if raw_dir is not None:
        img_dir = raw_dir / "img"
        got_gyu = sum(1 for p in img_dir.rglob("*") if p.is_file()) if img_dir.is_dir() else 0
    expected += len(gyus)
    per_archive.append({"archive": "(res/g + userdata/*.gyu)", "expected": len(gyus),
                        "got": got_gyu, "listable": True})

    res_dir = _exhibit_res_dir(game_dir)
    if res_dir is not None:
        exp = grp.expected_counts(res_dir)
        for name, n in exp["by_arc"].items():
            got = None
            if raw_dir is not None:
                dest = raw_dir / "audio" / name[:-4]
                got = sum(1 for p in dest.rglob("*") if p.is_file()) if dest.is_dir() else 0
            expected += n
            per_archive.append({"archive": name, "expected": n, "got": got,
                                "toc": exp["toc"].get(name), "listable": True})
        for name in exp["unlistable"]:
            listable = False
            per_archive.append({"archive": name, "expected": None, "got": None,
                                "listable": False})

    loose = _exhibit_loose_media(game_dir)
    got_loose = None
    if raw_dir is not None:
        got_loose = sum(1 for _src, rel in loose if (raw_dir / rel).exists())
    expected += len(loose)
    per_archive.append({"archive": "(散装 .wav/.wmv/.ogg)", "expected": len(loose),
                        "got": got_loose, "listable": True})
    return expected, listable, per_archive


def stage_extract_exhibit(ctx: Ctx) -> Stage:
    """ExHIBIT / Retouch：`.gyu` 图片解码 + `.grp` 音频切分 + 散装媒体复制。

    三条来源，对账口径由 `_exhibit_expected()` 统一给出：
      * `.gyu` → `_gyu_tool`（C# 源码随包、首启现编）递归解码成 PNG，落 `raw/img/`
      * `.grp` → `_grp_extract.py` 按 AiFS TOC 切成 ogg，落 `raw/audio/<包名>/`
      * `.wav`/`.wmv`/明文 `.ogg` → 复制到 `raw/loose/<游戏内相对路径>`

    图片是**解码后即成品**（磁盘上不残留 `.gyu`），所以 raw == final、converted 为空。

    加密未破的 BGM 不进 raw，但写进 `st.data["unsupported"]` 并在 detail 里显式报出。
    """
    st = Stage("extract")
    t0 = time.time()
    gyus = _exhibit_gyu(ctx.game_dir)
    loose = _exhibit_loose_media(ctx.game_dir)
    res_dir = _exhibit_res_dir(ctx.game_dir)
    encrypted = _exhibit_encrypted_ogg(ctx.game_dir)
    if not gyus and not loose and res_dir is None:
        st.detail = "既没有 .gyu，也没有 .grp，也没有散装 .wav/.wmv/.ogg"
        st.seconds = time.time() - t0
        return st

    unsupported = ([{"pattern": "*.ogg（魔数不是 OggS → 加密）", "count": len(encrypted),
                     "reason": "BGM 加密未解密（verified-findings §15.3）"}]
                   if encrypted else [])
    skipped_note = (f"另有 {len(encrypted)} 个 BGM 因加密未解密，未纳入交付"
                    if encrypted else "")

    # 先算地面真相：失败路径也要能报出「期望多少」，否则对账失败时看不出差在哪。
    expected, listable, per_archive = _exhibit_expected(ctx.game_dir)

    if ctx.reuse_raw:
        # 复用模式：不重新解包，但**仍然算地面真相** —— 对账不能因为跳步就失效。
        st.skipped = True
        st.ok = True
        st.detail = f"复用已有 raw: {ctx.reuse_raw}"
        actual = _count(ctx.raw_dir).total
        expected, listable, per_archive = _exhibit_expected(ctx.game_dir, raw_dir=ctx.raw_dir)
        st.data = {"reused_from": str(ctx.reuse_raw), "actual_total": actual,
                   "archives": per_archive, "unsupported": unsupported}
        st.seconds = time.time() - t0
        if not listable:
            st.data["reason"] = "有 .grp 列不出条目，无完整地面真相，未对账"
            st.detail = f"复用已有 raw，{actual} 个文件；有包列不出条目，未对账"
            if skipped_note:
                st.detail += f"；{skipped_note}"
            return st
        st.data["expected_total"] = expected
        if actual != expected:
            st.detail = f"复用产物对账失败：索引 {expected} vs 落盘 {actual}"
            st.ok = False
            return st
        st.detail = f"复用已有 raw，对账 {expected} == {actual}"
        if skipped_note:
            st.detail += f"；{skipped_note}"
        return st

    ctx.raw_dir.mkdir(parents=True, exist_ok=True)

    # 1) .gyu → raw/img/（保持游戏内相对路径；C# 工具现编，编译失败要看得见原因）
    if gyus:
        dest = ctx.raw_dir / "img"
        try:
            gyu_res = tb.run_csharp("gyu", [str(ctx.game_dir), str(dest)],
                                    product_dir=dest, min_products=len(gyus))
        except Exception as exc:
            st.detail = f"自带 C# 工具 _gyu_tool 无法启用：{exc}"
            st.data = {"archives": per_archive, "unsupported": unsupported}
            st.seconds = time.time() - t0
            return st
        ctx.log("extract", f"$ gyu_tool {ctx.game_dir} {dest}\n{gyu_res.summary()}")
        got_gyu = _count(dest).total if dest.is_dir() else 0
        if not gyu_res.ok:
            st.detail = (f"_gyu_tool 解码失败（期望 {len(gyus)} 张，落盘 {got_gyu}）："
                         f"{gyu_res.reason}")
            st.data = {"archives": per_archive, "unsupported": unsupported}
            st.seconds = time.time() - t0
            return st

    # 2) .grp → raw/audio/<包名>/（TOC 解析在 _grp_extract.py 里，别在这儿重写）
    if res_dir is not None:
        audio_dst = ctx.raw_dir / "audio"
        argv = [str(Path(__file__).parent / "_grp_extract.py"), str(res_dir),
                str(audio_dst), "--manifest", str(ctx.work_dir / "grp.manifest.json")]
        proc = subprocess.run([sys.executable, *argv], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        ctx.log("extract", f"$ {sys.executable} {' '.join(argv)}\n"
                           f"{proc.stdout}\n{proc.stderr}")
        if proc.returncode != 0:
            st.detail = (f"_grp_extract.py 失败（rc={proc.returncode}）："
                         f"{proc.stderr.strip()[:200]}")
            st.data = {"archives": per_archive, "unsupported": unsupported}
            st.seconds = time.time() - t0
            return st

    # 3) 散装媒体 → raw/loose/<游戏内相对路径>
    for src, rel in loose:
        dst = ctx.raw_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(src, dst)
        ctx.log("extract", f"[媒体] {src.relative_to(ctx.game_dir)} → raw/{rel.as_posix()}")

    # 跑完了再算一次，这回把 `got` 填上（期望值与上面同源，不会漂）
    _e, _l, per_archive = _exhibit_expected(ctx.game_dir, raw_dir=ctx.raw_dir)
    actual_total = _count(ctx.raw_dir).total
    n_grp = len([a for a in per_archive if a.get("toc")])
    st.data = {"mode": "static", "archives": per_archive, "loose_media": len(loose),
               "actual_total": actual_total, "unsupported": unsupported}
    st.seconds = time.time() - t0
    if not listable:
        # 有包列不出 = 没有完整地面真相，明说，别假装对过账
        st.ok = True
        st.data["reason"] = "有 .grp 列不出条目，无完整地面真相，未对账"
        st.detail = f"落盘 {actual_total} 个文件，有包列不出条目，未对账"
        if skipped_note:
            st.detail += f"；{skipped_note}"
        return st
    st.data["expected_total"] = expected
    if actual_total != expected:
        st.detail = f"对账失败：索引 {expected} vs 落盘 {actual_total}"
        if skipped_note:
            st.detail += f"；{skipped_note}"
        return st
    st.ok = True
    st.detail = (f"{len(gyus)} 个 .gyu 解码 + {n_grp} 个 .grp 切分 + "
                 f"{len(loose)} 个散装媒体，{actual_total} 个文件，对账 0 差")
    if skipped_note:
        st.detail += f"（{skipped_note}）"
    return st


#: 引擎 → extract 阶段**函数名**（新增引擎只需在这里加一行 + 扩 IMPLEMENTED）。
#: 存名字而不是函数对象：存对象会在 import 时把引用焊死，测试 monkeypatch 模块属性就失效了
#: （实测踩过：3 个 run() 退出码测试全红），也会让热重载拿不到新实现。
# ---------------------------------------------------------------- CatSystem2

def _cs2_sub_dir(game: Path, raw_dir: Path, archive: str) -> Path:
    """`_cs2_int_extract.py` 把 `xxx.int` 解到 `raw/xxx/` —— 逐包对账要按这个约定找。"""
    return raw_dir / Path(archive).stem


def stage_extract_cs2(ctx: Ctx) -> Stage:
    """CatSystem2（KIF `.int` + Blowfish/MT）：地面真相取 `cs2.expected_counts()`。

    对账做**两层**：逐包（`raw/<包名>/` 的文件数 vs 头部声明的条目数）与总计。
    逐包那层是必要的——51 个包里少一个、另一个多一个，总数照样相等。

    `--reuse-raw` 时不重新解包，但**照旧算同一份地面真相并对账**（跳的是解包不是验收）。
    """
    st = Stage("extract")
    t0 = time.time()
    exp = cs2.expected_counts(ctx.game_dir)
    if not exp["arcs"]:
        st.detail = "游戏目录里没有 KIF 格式的 .int"
        st.seconds = time.time() - t0
        return st

    archives = [{"archive": n, "expected": c, "got": None}
                for n, c in sorted(exp["by_arc"].items())]
    expected_total = None if exp["unlistable"] else exp["total"]

    if ctx.reuse_raw is None:
        ctx.raw_dir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(Path(__file__).parent / "_cs2_int_extract.py"),
               str(ctx.game_dir), str(ctx.raw_dir),
               "--manifest", str(ctx.work_dir / "cs2.manifest.json")]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        tail = (proc.stdout or "").strip().splitlines()[-8:]
        for line in tail:
            ctx.log("extract", "  " + line)
        for line in (proc.stderr or "").strip().splitlines()[-5:]:
            ctx.log("extract", "  [stderr] " + line)
        if proc.returncode != 0:
            st.detail = f"_cs2_int_extract.py 失败（rc={proc.returncode}）：{tail[-1] if tail else ''}"
            st.seconds = time.time() - t0
            return st

    actual_total = _count(ctx.raw_dir).total
    mism: list[str] = []
    for a in archives:
        a["got"] = _count(_cs2_sub_dir(ctx.game_dir, ctx.raw_dir, a["archive"])).total
        if a["got"] != a["expected"]:
            mism.append(f"{a['archive']}(索引 {a['expected']} vs 落盘 {a['got']})")

    st.data = {"archives": archives, "actual_total": actual_total,
               "raw_by_ext": _count(ctx.raw_dir).by_ext}
    if expected_total is not None:
        st.data["expected_total"] = expected_total
    if exp["unlistable"]:
        st.data["unlistable"] = exp["unlistable"]
        ctx.log("extract", f"  [WARN] {len(exp['unlistable'])} 个 .int 列不出条目")

    st.seconds = time.time() - t0
    if mism:
        st.detail = "逐包对账失败：" + "；".join(mism[:3])
        return st
    if expected_total is not None and actual_total != expected_total:
        st.detail = f"对账失败：索引 {expected_total} vs 落盘 {actual_total}"
        return st
    st.ok = True
    if expected_total is None:
        st.detail = f"{len(archives)} 个 .int，{actual_total} 个文件，未对账（有包列不出条目）"
    else:
        st.detail = (f"{len(archives)} 个 .int，{actual_total} 个文件，"
                     f"对账 0 差（逐包 {len(archives)}/{len(archives)}）")
    return st


# ---------------------------------------------------------------- 阶段 3: postprocess

EXTRACTORS = {
    "Ren'Py": "stage_extract_renpy",
    "KiriKiri": "stage_extract_kirikiri",
    "RPG Maker": "stage_extract_rpgmaker",
    "Yu-Ris": "stage_extract_yuris",
    "AdvHD": "stage_extract_advhd",
    "ExHIBIT": "stage_extract_exhibit",
    "CatSystem2": "stage_extract_cs2",
}

def _carve_pna(src: Path, out_dir: Path) -> int:
    """把 PNAP 容器内嵌的 PNG 逐帧 carve 到 `out_dir`，返回写出的帧数。

    复用 `_pna_carve.carve()`（纯函数，**单一实现**）：PNG 自定界——8 字节签名起始、
    `IEND` chunk 结束，所以不需要懂 PNAP 的帧索引（AdvHD 的 `.pna` 就是 "PNAP" 头 +
    帧索引 + 若干标准 PNG，GARbro 不认、原样吐出）。
    帧名沿用 `_pna_carve.py` 的 `__fNNN` 约定，两处产物能对得上。
    """
    frames = pna.carve(src.read_bytes())
    if not frames:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for n, fr in enumerate(frames):
        (out_dir / f"{src.stem}__f{n:03d}.png").write_bytes(fr)
    return len(frames)


def _cs2_normalize_exts(raw_dir: Path) -> dict:
    """把 raw 里的扩展名按**魔数**归一（`.KCC`→`.ogg`、`.xyz`→`.hg3`…）。

    CatSystem2 的扩展名是二次混淆过的：实测 pcm_AA 的 3907 个 OggS 里只有 148 个
    恰好还原成 `.ogg`（≈1/26，「按文件轮换、转到 0 才露真名」）。不归一的话这些文件
    既进不了 `IMG_EXT` 也进不了 `AV_EXT`，会被 verify 当「非媒体文件」**静默放过**
    ——`.mos` 那次的教训：少验的东西不会自己报错。

    只改「认得出是什么」的文件（魔数表外的 `.bin` 一律不动，免得把数据文件改得面目全非）；
    目标名已存在时**保留原名**并计数：改名换来的是覆盖，宁可名字难看也不能丢文件。
    """
    renamed = kept = 0
    kinds: dict[str, int] = {}
    examples: list[str] = []
    for p in sorted(raw_dir.rglob("*")):
        if not p.is_file():
            continue
        ext = cs2.sniff_ext(_head(p, 8))
        if ext == ".bin" or ext == p.suffix.lower():
            continue
        kinds[ext] = kinds.get(ext, 0) + 1
        dst = p.with_suffix(ext)
        if dst.exists():
            kept += 1
            examples.append(f"{p.relative_to(raw_dir).as_posix()}: 目标 {dst.name} 已存在，保留原名")
            continue
        p.rename(dst)
        renamed += 1
        if len(examples) < 10:
            examples.append(f"{p.name} → {dst.name}")
    return {"renamed": renamed, "kept": kept, "kinds": kinds, "examples": examples[:10]}


def _cs2_postprocess(ctx: Ctx) -> Stage:
    """CatSystem2 的后处理：① 扩展名按魔数归一 ② HG-3 家族 → png/。

    两步都按**魔数**走：扩展名不可信（见 `_cs2_normalize_exts`），HG-3 又必须整树扫描
    （`_hg3_tool` 的 `IsHg3Magic()` 就是逐文件读 4 字节）。

    `consumed` 记下全部 HG-3 的路径：它们转出的 PNG 才是交付物，raw 里那份不该再算一次
    ——但**不删**（raw 要留着跟 53500 条索引对账）。排除按路径不按扩展名，理由同上。
    """
    st = Stage("postprocess")
    t0 = time.time()
    norm = _cs2_normalize_exts(ctx.raw_dir)
    hg3 = cs2.hg3_expected_png(ctx.raw_dir)
    if norm["renamed"] or norm["kept"]:
        ctx.log("postprocess", f"扩展名归一: 改名 {norm['renamed']}、保留 {norm['kept']}、"
                               f"kinds={norm['kinds']}")

    if not hg3["count"]:
        st.ok = True
        st.data = {"tool": "扩展名归一（无 HG-3 可转）", "in": 0, "ok": 0, "fail": 0,
                   "frames_out": 0, "renamed": norm["renamed"], "collisions": 0}
        st.detail = f"扩展名按魔数归一 {norm['renamed']} 个；无 HG-3 文件"
        st.seconds = time.time() - t0
        return st

    ctx.png_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = tb.run_csharp("hg3", [str(ctx.raw_dir), str(ctx.png_dir)],
                            product_dir=ctx.png_dir, min_products=hg3["png_count"])
    except Exception as exc:                     # 编译失败/找不到 csc 都得说清楚
        st.detail = f"自带 C# 工具 _hg3_tool 无法启用：{exc}"
        st.seconds = time.time() - t0
        return st
    if not res.ok:
        st.detail = f"_hg3_tool 解码失败：{res.reason}"
        st.seconds = time.time() - t0
        return st

    got = res.products.total
    st.seconds = time.time() - t0
    if got != hg3["png_count"]:
        # rc=0、产物也不是 0，只是**比该有的少**（撞车之外的漏解）——最危险的一类，
        # 只有拿产出数跟期望数硬比才看得见。
        st.data = {"tool": "_hg3_tool", "in": hg3["count"], "ok": got, "fail": 0,
                   "renamed": norm["renamed"], "expected_png": hg3["png_count"]}
        st.detail = (f"_hg3_tool 产物数不符：期望 {hg3['png_count']} vs 落盘 {got}"
                     f"（HG-3 文件 {hg3['count']} 个）")
        return st

    ctx.consumed = [Path(p).relative_to(ctx.raw_dir).as_posix() for p in hg3["files"]]
    st.ok = True
    st.data = {"tool": "_hg3_tool", "in": hg3["count"], "ok": got, "fail": 0,
               "frames_out": got, "renamed": norm["renamed"],
               "collisions": hg3["collisions"], "consumed": ctx.consumed}
    st.detail = (f"扩展名按魔数归一 {norm['renamed']} 个；HG-3 {hg3['count']} 个 "
                 f"→ png/ {got} 张")
    if hg3["collisions"]:
        st.detail += f"（同 stem 撞车 {hg3['collisions']} 个，已被 .png 归一化覆盖）"
    return st


def stage_postprocess(ctx: Ctx) -> Stage:
    """把 raw/ 里的中间格式转成 png/ 下的成品。

    两种按**扩展名**分派（都登记在 `manifest.CONVERTIBLE` 里，不按目录猜——坑 5）：
      · `.tlg` → tlg2png 转单个 PNG
      · `.pna` → PNAP 多帧容器，逐帧 carve 成多个 PNG（AdvHD）

    一个 `.pna` 能产出多帧，所以 `in`（输入文件数）与写出帧数**不是一一对应**的，
    两者分开记。

    CatSystem2 走单独一条：它的扩展名被引擎二次混淆过，按扩展名分派根本认不出图片，
    只能按魔数（见 `_cs2_postprocess`）。
    """
    st = Stage("postprocess")
    t0 = time.time()
    if not ctx.raw_dir.is_dir():
        st.detail = "raw/ 不存在，跳过"
        st.ok = True
        st.skipped = True
        st.seconds = time.time() - t0
        return st

    if ctx.engine == "CatSystem2":
        return _cs2_postprocess(ctx)

    targets = sorted(p for p in ctx.raw_dir.rglob("*")
                     if p.is_file() and p.suffix.lower() in CONVERTIBLE)
    if not targets:
        st.ok = True
        st.skipped = True
        st.detail = "无待转格式（.tlg/.pna），无需后处理"
        st.seconds = time.time() - t0
        return st

    ctx.png_dir.mkdir(parents=True, exist_ok=True)
    ok_n = fail_n = 0
    frames_out = 0
    kinds: dict[str, int] = {}
    fails: list[str] = []
    for i, src in enumerate(targets, 1):
        rel = src.relative_to(ctx.raw_dir)
        kind = src.suffix.lower()
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == ".tlg":
            dst = ctx.png_dir / rel.with_suffix(".png")
            dst.parent.mkdir(parents=True, exist_ok=True)
            res = tb.tlg2png(src, dst)
            if res.ok:
                ok_n += 1
                frames_out += 1
            else:
                fail_n += 1
                fails.append(f"{rel}: {res.reason}")
        elif kind == ".pna":
            try:
                n = _carve_pna(src, ctx.png_dir / rel.parent)
            except OSError as exc:
                n = 0
                fails.append(f"{rel}: 读取失败 {exc}")
            else:
                if n <= 0:
                    fails.append(f"{rel}: carve 出 0 帧（不是 PNAP 或没有内嵌 PNG）")
            if n > 0:
                ok_n += 1
                frames_out += n
            else:
                fail_n += 1
        else:  # pragma: no cover - CONVERTIBLE 只有上面两种
            fail_n += 1
            fails.append(f"{rel}: 不认识的可转换格式")
        if i % 200 == 0:
            ctx.log("postprocess", f"  [{i}/{len(targets)}] ok={ok_n} fail={fail_n}")
    ctx.log("postprocess", f"convert: total={len(targets)} ok={ok_n} fail={fail_n} "
                           f"frames={frames_out}")
    for f in fails[:50]:
        ctx.log("postprocess", "  FAIL " + f)

    st.data = {"tool": "tlg2png/_pna_carve", "in": len(targets), "ok": ok_n,
               "fail": fail_n, "frames_out": frames_out, "kinds": kinds,
               "fail_examples": fails[:10]}
    st.seconds = time.time() - t0
    if fail_n:
        st.detail = f"{fail_n}/{len(targets)} 个待转文件转换失败"
        return st
    st.ok = True
    by_kind = "、".join(f"{n} 个 {k}" for k, n in sorted(kinds.items()))
    st.detail = f"{by_kind} → png/ 共 {frames_out} 个成品"
    return st


# ---------------------------------------------------------------- 阶段 4: verify

def _final_files(ctx: Ctx) -> list[tuple[Path, str]]:
    """返回 [(绝对路径, 相对标签)] —— raw 去掉被消费的中间格式，再接上 png/。

    实现在 `manifest.py`（契约的唯一实现），这里只做转发：
    orchestrator 与 krkr_auto_extract 必须对「交付了什么」给出同一个答案，
    两处各写一遍必然漂移。
    """
    return manifest.iter_final_files(ctx.raw_dir, ctx.png_dir, CONVERTIBLE, ctx.consumed)


def stage_verify(ctx: Ctx) -> Stage:
    st = Stage("verify")
    t0 = time.time()
    if not ctx.do_verify:
        st.ok = True
        st.skipped = True
        st.detail = "按 --no-verify 跳过（manifest 会标记未验收）"
        st.data = {"verified": False}
        st.seconds = time.time() - t0
        return st

    files = _final_files(ctx)
    if not files:
        st.detail = "没有可验收的产物"
        st.seconds = time.time() - t0
        return st

    img_ok = img_fail = 0
    audio_ok = audio_fail = 0
    video_ok = video_fail = 0
    nonmedia = 0
    zero_byte: list[str] = []
    audio_seconds = 0.0
    fails: list[str] = []

    for i, (p, label) in enumerate(files, 1):
        ext = p.suffix.lower()
        # 0 字节文件先看是不是源本身声明的空占位（AGENTS.md Ren'Py 段：
        # 「0 字节文件要先查索引」——源包声明 0 长度属正常，不是解包 bug）。
        # 通用链路拿不到索引，所以这里先单列不算失败，末尾用比例护栏兜底。
        try:
            is_empty = p.stat().st_size == 0
        except OSError:
            is_empty = False
        if is_empty:
            zero_byte.append(label)
            continue
        if ext in IMG_EXT:
            try:
                from PIL import Image
                with Image.open(p) as im:
                    im.verify()
                img_ok += 1
            except Exception as exc:                           # noqa: BLE001
                img_fail += 1
                fails.append(f"[image] {label} :: {type(exc).__name__}: {exc}")
        elif ext in AV_EXT:
            info = tb.ffprobe(p)
            if info is None:
                audio_fail += 1
                fails.append(f"[av] {label} :: ffprobe 无结果")
            elif info["kind"] == "video":
                video_ok += 1
                if info.get("dur"):
                    audio_seconds += info["dur"]
            else:
                audio_ok += 1
                if info.get("dur"):
                    audio_seconds += info["dur"]
        else:
            nonmedia += 1
        if i % 500 == 0:
            ctx.log("verify", f"  [{i}/{len(files)}] img={img_ok}/{img_fail} "
                              f"audio={audio_ok}/{audio_fail} video={video_ok}/{video_fail}")
    for f in fails[:50]:
        ctx.log("verify", "  FAIL " + f)
    for z in zero_byte[:50]:
        ctx.log("verify", "  ZERO " + z)

    # 比例护栏：少量 0 字节是源里的占位文件（实测 Swipe Right 有 5 个，
    # 全部与索引声明长度 0 对上）；但如果大面积是 0 字节，那就是解包坏了。
    zero_limit = max(10, int(len(files) * 0.01))
    zero_ok = len(zero_byte) <= zero_limit
    if not zero_ok:
        fails.append(f"[zero] {len(zero_byte)} 个 0 字节文件超过护栏 {zero_limit}"
                     f"（疑似解包损坏）")

    st.data = {
        "verified": True,
        "files_checked": len(files),
        "image_ok": img_ok, "image_fail": img_fail,
        "audio_ok": audio_ok, "audio_fail": audio_fail,
        "video_ok": video_ok, "video_fail": video_fail,
        "nonmedia": nonmedia,
        "zero_byte": len(zero_byte),
        "zero_byte_examples": zero_byte[:10],
        "media_minutes": round(audio_seconds / 60.0, 1),
        "fail_examples": fails[:10],
    }
    st.seconds = time.time() - t0
    total_fail = img_fail + audio_fail + video_fail + (0 if zero_ok else 1)
    if total_fail:
        st.detail = f"{total_fail} 个产物验收失败"
        return st
    st.ok = True
    st.detail = (f"图片 {img_ok}/{img_ok}、音频 {audio_ok}/{audio_ok}、"
                 f"视频 {video_ok}/{video_ok}，失败 0"
                 + (f"（另有 {len(zero_byte)} 个 0 字节占位文件，未计入）"
                    if zero_byte else ""))
    return st


# ---------------------------------------------------------------- 阶段 5: manifest

def build_manifest(ctx: Ctx, stages: list[Stage], engine: str | None) -> dict:
    """按 `manifest.py` 的契约拼 manifest（counts 三段式实现在那边）。"""
    def stage_data(name: str) -> dict:
        for s in stages:
            if s.name == name:
                return s.data
        return {}

    extract_data = stage_data("extract")
    post_data = stage_data("postprocess")
    verify_data = stage_data("verify")

    archives = []
    for a in extract_data.get("archives", []) or []:
        archives.append({"name": a.get("archive"), "entries": a.get("expected"),
                         "extracted": a.get("got")})

    counts_block = manifest.counts(ctx.raw_dir, ctx.png_dir, CONVERTIBLE, ctx.consumed)
    rec = manifest.reconcile(extract_data.get("expected_total"),
                             counts_block["raw"]["total"])

    # 「有意排除、没进交付」的东西必须出现在 source 里，不能只躺在某个 stage 的 data 里：
    # 读 manifest 的下游（人也好程序也好）看的是 `source.archives`，不会去翻 stages。
    # 空列表不写，免得别的链路凭空多一个字段。
    source: dict = {"game_dir": str(ctx.game_dir), "archives": archives}
    unsupported = extract_data.get("unsupported") or []
    if unsupported:
        source["unsupported"] = unsupported

    return manifest.build(
        tool="orchestrator.py",
        engine=engine,
        source=source,
        counts_block=counts_block,
        reconcile_block=rec,
        verify={
            "verified": verify_data.get("verified", False),
            "image_ok": verify_data.get("image_ok"),
            "image_fail": verify_data.get("image_fail"),
            "audio_ok": verify_data.get("audio_ok"),
            "audio_fail": verify_data.get("audio_fail"),
            "video_ok": verify_data.get("video_ok"),
            "video_fail": verify_data.get("video_fail"),
            "zero_byte": verify_data.get("zero_byte"),
            "media_minutes": verify_data.get("media_minutes"),
        },
        postprocess=([dict({"tool": post_data.get("tool"), "in": post_data.get("in"),
                            "ok": post_data.get("ok"), "fail": post_data.get("fail")},
                           **({"consumed": len(post_data["consumed"])}
                              if post_data.get("consumed") else {}))]
                     if post_data and not post_data.get("_skipped") else []),
        png_dir=manifest.scan_png(ctx.png_dir),
        stages=[s.as_dict() for s in stages],
    )


# ---------------------------------------------------------------- 主流程

def run(ctx: Ctx) -> tuple[int, dict]:
    stages: list[Stage] = []
    t_all = time.time()

    # 1. detect
    if ctx.engine:
        st = Stage("detect", ok=True, detail=f"由 --engine 强制指定: {ctx.engine}",
                   data={"engine": ctx.engine, "forced": True})
        stages.append(st)
        engine = ctx.engine
    else:
        st = stage_detect(ctx)
        stages.append(st)
        engine = st.data.get("engine")
        if not st.ok:
            return 3, {"error": "detect-failed", "stages": [s.as_dict() for s in stages]}

    # 引擎是否已实现链路
    ctx.engine = engine          # 后处理按引擎分派（CatSystem2 走魔数那条），必须回填
    chain_ok = engine in IMPLEMENTED
    if not chain_ok:
        st = Stage("extract", ok=False,
                   detail=f"引擎 {engine} 已判出，但本阶段尚未实现链路（已实现: "
                          f"{', '.join(IMPLEMENTED)}）")
        stages.append(st)
        return 2, {"error": "chain-not-implemented", "engine": engine,
                   "stages": [s.as_dict() for s in stages]}

    # 2. extract
    extractor_name = EXTRACTORS.get(engine)
    if extractor_name is None:                                  # pragma: no cover
        st = Stage("extract", ok=False,
                   detail=f"引擎 {engine} 在 IMPLEMENTED 里但没有对应 extract 函数")
        stages.append(st)
        return 2, {"error": "no-extractor-mapped", "engine": engine,
                   "stages": [s.as_dict() for s in stages]}
    st = globals()[extractor_name](ctx)
    stages.append(st)
    if not st.ok:
        return 1, {"error": "extract-failed", "engine": engine,
                   "stages": [s.as_dict() for s in stages]}

    # 3. postprocess
    st = stage_postprocess(ctx)
    stages.append(st)
    if not st.ok:
        return 1, {"error": "postprocess-failed", "engine": engine,
                   "stages": [s.as_dict() for s in stages]}

    # 4. verify
    st = stage_verify(ctx)
    stages.append(st)
    if not st.ok:
        man = build_manifest(ctx, stages, engine)
        return 1, {"error": "verify-failed", "engine": engine, "manifest": man,
                   "stages": [s.as_dict() for s in stages]}

    # 5. manifest
    t0 = time.time()
    man = build_manifest(ctx, stages, engine)
    ctx.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.manifest_path.write_text(
        json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    mst = Stage("manifest", ok=True, seconds=time.time() - t0,
                detail=f"写入 {ctx.manifest_path}", data={"path": str(ctx.manifest_path)})
    stages.append(mst)
    man["stages"] = [s.as_dict() for s in stages]

    # 对账不为 0 即失败（纪律 2）
    diff = man["reconcile"]["diff"]
    rc = 0 if (diff in (0, None)) else 1
    man["ok"] = rc == 0
    man["total_seconds"] = round(time.time() - t_all, 1)
    ctx.manifest_path.write_text(
        json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return rc, man


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="galgame 解包编排器：detect → extract → postprocess → verify → manifest")
    ap.add_argument("game_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--engine", default=None,
                    help=f"跳过 detect 强制指定引擎（已实现: {', '.join(IMPLEMENTED)}）")
    ap.add_argument("--reuse-raw", default=None,
                    help="跳过 extract，直接复用已有 raw 产物（断点续传）")
    ap.add_argument("--allow-gui", action="store_true",
                    help="允许 GUI 自动化链路（加密 KiriKiri，慢）")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--strict", action="store_true", help="保留：对账/验收非 0 一律退出 1")
    ap.add_argument("--json", default=None, help="把完整结果另存一份 JSON")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    game_dir = Path(a.game_dir).resolve()
    out_dir = Path(a.out).resolve()
    if not game_dir.is_dir():
        print(f"[错误] 游戏目录不存在: {game_dir}", file=sys.stderr)
        return 3
    work_dir = Path(a.work).resolve() if a.work else out_dir / "_work"
    manifest_path = Path(a.manifest).resolve() if a.manifest else out_dir / "manifest.json"
    reuse = Path(a.reuse_raw).resolve() if a.reuse_raw else None

    ctx = Ctx(game_dir=game_dir, out_dir=out_dir, work_dir=work_dir,
              manifest_path=manifest_path, reuse_raw=reuse,
              allow_gui=a.allow_gui, do_verify=not a.no_verify, engine=a.engine)

    if a.dry_run:
        st = stage_detect(ctx)
        print(json.dumps({"game_dir": str(game_dir), "out": str(out_dir),
                          "detect": st.as_dict()}, ensure_ascii=False, indent=2))
        return 0 if st.ok else 3

    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    for f in work_dir.glob("*.log"):
        f.unlink()

    if reuse:
        # 复用模式：把已有产物搬/链到 raw/
        if not reuse.is_dir():
            print(f"[错误] --reuse-raw 目录不存在: {reuse}", file=sys.stderr)
            return 1
        if reuse == ctx.raw_dir:
            print(f"[reuse] 源与目标同一目录，跳过复制: {reuse}")
        else:
            if ctx.raw_dir.exists():
                shutil.rmtree(ctx.raw_dir, ignore_errors=True)
            shutil.copytree(reuse, ctx.raw_dir, symlinks=True, dirs_exist_ok=False)
            print(f"[reuse] {reuse} -> {ctx.raw_dir}")

    t0 = time.time()
    rc, res = run(ctx)
    el = time.time() - t0

    print("=" * 66)
    for s in res.get("stages", []):
        flag = "SKIP" if s.get("skipped") else ("OK  " if s.get("ok") else "FAIL")
        print(f"[{flag}] {s['stage']:<12} {s['seconds']:>7.2f}s  {s.get('detail', '')}")
    print("=" * 66)

    man = res.get("manifest") or (json.loads(manifest_path.read_text(encoding="utf-8"))
                                  if manifest_path.exists() else {})
    if man:
        c = man.get("counts", {})
        raw, fin, conv = c.get("raw", {}), c.get("final", {}), c.get("converted", {})
        print(f"引擎: {man.get('engine')}")
        print(f"raw    : {raw.get('total')} 个文件 {raw.get('bytes', 0)/1048576:.1f} MB  "
              f"{raw.get('by_ext')}")
        print(f"final  : {fin.get('total')} 个文件 {fin.get('bytes', 0)/1048576:.1f} MB  "
              f"{fin.get('by_ext')}")
        print(f"converted: {conv}")
        r = man.get("reconcile", {})
        print(f"对账   : 期望 {r.get('expected')} vs 落盘 {r.get('actual')} "
              f"(diff={r.get('diff')})")
        v = man.get("verify", {})
        if v.get("verified"):
            print(f"验收   : 图片 {v.get('image_ok')}/{v.get('image_fail')}失败、"
                  f"音频 {v.get('audio_ok')}/{v.get('audio_fail')}失败、"
                  f"视频 {v.get('video_ok')}/{v.get('video_fail')}失败、"
                  f"媒体 {v.get('media_minutes')} 分钟")
        else:
            print("验收   : 未执行（--no-verify）")
        print(f"manifest: {manifest_path}")
    print(f"总耗时: {el:.1f}s   退出码: {rc}")

    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2,
                                           default=str), encoding="utf-8")
        print(f"完整结果: {a.json}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
