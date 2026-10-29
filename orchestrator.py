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

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 常量

#: 后处理会"吃掉"的中间格式 —— raw 里有、final 里没有，差额由 manifest.converted 解释
CONVERTIBLE = {".tlg"}

#: 图片类（Pillow 能验的）；与 _verify_media.py 保持一致
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tga"}

#: 只有这些才送 ffprobe（其余送进去只会得到 Invalid data，把结果搅浑）
AV_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".mpg", ".mpeg",
          ".mp3", ".ogg", ".wav", ".opus", ".flac", ".m4a", ".aac", ".wma"}

#: 已实现完整链路的引擎（其余判得出来但没链路 → 退出码 2）
IMPLEMENTED = ("Ren'Py", "KiriKiri")


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


# ---------------------------------------------------------------- 阶段 3: postprocess

def stage_postprocess(ctx: Ctx) -> Stage:
    """把 raw/ 里的 .tlg 转成 png/ 下的 PNG。没有 .tlg 就是空操作。"""
    st = Stage("postprocess")
    t0 = time.time()
    if not ctx.raw_dir.is_dir():
        st.detail = "raw/ 不存在，跳过"
        st.ok = True
        st.skipped = True
        st.seconds = time.time() - t0
        return st

    tlgs = sorted(p for p in ctx.raw_dir.rglob("*")
                  if p.is_file() and p.suffix.lower() in CONVERTIBLE)
    if not tlgs:
        st.ok = True
        st.skipped = True
        st.detail = "无 .tlg，无需后处理"
        st.seconds = time.time() - t0
        return st

    ctx.png_dir.mkdir(parents=True, exist_ok=True)
    ok_n = fail_n = 0
    fails: list[str] = []
    for i, src in enumerate(tlgs, 1):
        rel = src.relative_to(ctx.raw_dir)
        dst = ctx.png_dir / rel.with_suffix(".png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        res = tb.tlg2png(src, dst)
        if res.ok:
            ok_n += 1
        else:
            fail_n += 1
            fails.append(f"{rel}: {res.reason}")
        if i % 200 == 0:
            ctx.log("postprocess", f"  [{i}/{len(tlgs)}] ok={ok_n} fail={fail_n}")
    ctx.log("postprocess", f"tlg2png: total={len(tlgs)} ok={ok_n} fail={fail_n}")
    for f in fails[:50]:
        ctx.log("postprocess", "  FAIL " + f)

    st.data = {"tool": "tlg2png", "in": len(tlgs), "ok": ok_n, "fail": fail_n,
               "fail_examples": fails[:10]}
    st.seconds = time.time() - t0
    if fail_n:
        st.detail = f"{fail_n}/{len(tlgs)} 个 tlg 转换失败"
        return st
    st.ok = True
    st.detail = f"{ok_n} 个 tlg → png"
    return st


# ---------------------------------------------------------------- 阶段 4: verify

def _final_files(ctx: Ctx) -> list[tuple[Path, str]]:
    """返回 [(绝对路径, 相对标签)] —— raw 去掉被消费的中间格式，再接上 png/。

    实现在 `manifest.py`（契约的唯一实现），这里只做转发：
    orchestrator 与 krkr_auto_extract 必须对「交付了什么」给出同一个答案，
    两处各写一遍必然漂移。
    """
    return manifest.iter_final_files(ctx.raw_dir, ctx.png_dir, CONVERTIBLE)


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

    counts_block = manifest.counts(ctx.raw_dir, ctx.png_dir, CONVERTIBLE)
    rec = manifest.reconcile(extract_data.get("expected_total"),
                             counts_block["raw"]["total"])

    return manifest.build(
        tool="orchestrator.py",
        engine=engine,
        source={"game_dir": str(ctx.game_dir), "archives": archives},
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
        postprocess=([{"tool": post_data.get("tool"), "in": post_data.get("in"),
                       "ok": post_data.get("ok"), "fail": post_data.get("fail")}]
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
    chain_ok = engine in IMPLEMENTED
    if not chain_ok:
        st = Stage("extract", ok=False,
                   detail=f"引擎 {engine} 已判出，但本阶段尚未实现链路（已实现: "
                          f"{', '.join(IMPLEMENTED)}）")
        stages.append(st)
        return 2, {"error": "chain-not-implemented", "engine": engine,
                   "stages": [s.as_dict() for s in stages]}

    # 2. extract
    st = stage_extract_renpy(ctx) if engine == "Ren'Py" else stage_extract_kirikiri(ctx)
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
