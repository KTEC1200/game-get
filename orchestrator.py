#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator.py —— detect → case-lookup → preflight → extract → postprocess → verify → manifest 一条命令跑完。

`case-lookup`（阶段 1.5）按指纹签名查 `cases/` 案例库，**只报告历史解法与坑，不接管决策**：
对账的地面真相永远是编排器自己从归档索引算出来的数，案例里的 expected_total 不参与对账。
命中写进 `manifest.source.case_match`；三种结局（命中/无匹配/案例库缺失）都是 ok=True。

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
  6. 跑之前先问盘（preflight）：解包体积≈原包，盘不够会在中途炸并留下几 GB 半成品；
     宁可一开始就说「需要 X GB、可用 Y GB」。
  7. 失败的运行也写 manifest（`ok:false` + `error`）：交付记录必须能看出「这次没成」，
     不许让磁盘上留着上一次成功那份、被下游当成结论。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))

import galgame_dispatch as gd          # noqa: E402
import case_lib                        # noqa: E402  （案例库查表：签名算法唯一出处）
import manifest                        # noqa: E402
import manual                          # noqa: E402  （人工介入方案：失败时给可执行步骤，见 manual.py）
import faillog                         # noqa: E402  （失败日志：写软件根目录，与产物解耦）
import rpa_tool                        # noqa: E402
import toolbridge as tb                # noqa: E402
import rpa_extract_organized           # noqa: E402  （兄弟链路一律 in-process 调 main()，见 _run_sibling）
import krkr_auto_extract               # noqa: E402  （同上；静态 import 也是 PyInstaller 打包清单的依据，§19.2）
import _rpgmv_decrypt as rpgmv         # noqa: E402  （复用它的筛选常量，别抄第二份）
import _ypf_extract as ypf             # noqa: E402  （复用它的表解析，别抄第二份）
import _pna_carve as pna               # noqa: E402  （复用它的 carve()，别抄第二份）
import _grp_extract as grp             # noqa: E402  （复用它的 TOC 解析，别抄第二份）
import _cs2_int_extract as cs2         # noqa: E402  （复用它的地面真相/魔数识别，别抄第二份）
import _unity_extract as unity         # noqa: E402  （复用它的 JSON 枚举/Convert 导出，别抄第二份）
import _as_audio_collect2              # noqa: E402  （冻结包少了它音频只剩 ~30%，§19.1）
import _pfs_extract as pfs              # noqa: E402  （Artemis 的索引解析/落地，地面真相唯一出处）

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
               "CatSystem2", "Unity", "Artemis")

#: verify 的默认并发度（批次 C1）。瓶颈是子进程启动与磁盘头读取，不是 CPU：
#: 实测单文件 ffprobe ≈114ms，8 路把等待重叠掉就够；再加只会让同一块盘互相抢。
#: 环境变量 `GALUNPACK_VERIFY_WORKERS` 可覆盖，`--verify-jobs 1` 则完全串行。
VERIFY_WORKERS = 8


# ---------------------------------------------------------------- 结构

def _run_sibling(mod, argv: list[str]) -> tuple[int, str]:
    """In-process 跑兄弟模块的 `main(argv)`，返回 (rc, stdout+stderr 全文)。

    **为什么不用 `subprocess.run([sys.executable, "xxx.py", ...])`**：PyInstaller 冻结后
    `sys.executable` 是冻结点自己，那条通路从根上不存在（rc=2 `unknown mode`，
    verified-findings §19.1）；in-process 还顺带解决「错误信息跨进程丢失」。
    兄弟模块统一接口 `main(argv: list[str] | None = None) -> int`（内部不 sys.exit）。

    stdout/stderr 重定向收进返回值，由调用方写 ctx.log —— 与子进程时代 `capture_output`
    的日志形态一致。异常降级：`SystemExit` 按其 code 折算 rc（兜底个别 usage 路径）、
    其他异常按子进程时代的语义记 rc=1 并把 traceback 写进输出（对应当年的 stderr）。
    KeyboardInterrupt 不拦 —— 用户 Ctrl+C 要能打断整条链。
    """
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = mod.main(list(argv))
    except SystemExit as exc:                               # noqa: BLE001
        code = exc.code
        rc = 0 if code in (None, 0) else (code if isinstance(code, int) else 1)
    except Exception:                                       # noqa: BLE001
        traceback.print_exc(file=buf)
        rc = 1
    return int(rc or 0), buf.getvalue()


def _never_stop() -> bool:
    """`Ctx.should_stop` 的默认实现：CLI 与测试永远不取消。

    用命名函数而不是 `lambda: False`：dataclass 的默认值在类创建时求值，写 lambda
    会让每个实例共享同一个匿名对象，报错时看到的是 `<function <lambda> at 0x...>`
    —— 排查「谁把 should_stop 换掉了」时完全没用。
    """
    return False


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
    # 取消钩子（GUI 的「取消」按钮）：返回 True = 用户要求中止。
    # 默认永不取消，CLI 与测试完全不受影响。run() 只在**阶段边界**和 verify 的文件循环里
    # 检查 —— 解包器内部没法半途安全中断（外部工具正在跑、产物正写到一半），
    # 硬中断只会留下没对账的半成品，比「再等一会儿」更糟。
    should_stop: Callable[[], bool] = _never_stop
    #: verify 的并发度（`--verify-jobs`）。None = 走 `resolve_verify_jobs()` 的
    #: 「环境变量 → 默认 8」链路；1 = 完全串行（回退档，行为与并行化之前一致）。
    verify_jobs: int | None = None
    #: `--strict`：对账没有地面真相、或验收没执行，也算失败（见 run() 里的说明）。
    strict: bool = False
    #: `--overwrite`：输出目录已有上一轮产物时先清空 raw/ 与 png/ 再跑。
    #: 默认 False = 遇到残留**直接失败**。理由：残留混进本轮时产物数照样能自洽，
    #: 只是数字全错（上一轮 3500 + 本轮 3500 会报成 7000 且 diff=0）——这是最难查的假绿。
    overwrite: bool = False

    @property
    def raw_dir(self) -> Path:
        return self.out_dir / "raw"

    @property
    def png_dir(self) -> Path:
        return self.out_dir / "png"

    def log(self, stage: str, text: str) -> None:
        """把一行写进 `_work/<stage>.log`。**写不进去也不许把整轮跑挂掉。**

        2026-11-04 用户实测：默认输出目录落在被终端防护拦的路径上，`mkdir` 抛
        `PermissionError`，异常从 `stage_detect` 一路穿到 GUI 的 `_worker`，
        变成 `worker-aborted` —— 一次「日志写不了」被放大成「功能不可用」。
        日志是诊断，不是正确性；降级到 stderr 并只提示一次，别刷屏。
        """
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            with (self.work_dir / f"{stage}.log").open("a", encoding="utf-8") as fh:
                fh.write(text.rstrip("\n") + "\n")
        except OSError as exc:
            if not getattr(self, "_log_broken", False):
                self._log_broken = True
                print(f"[WARN] 阶段日志写不进去（{type(exc).__name__}: {exc}），"
                      f"后续日志丢弃：{self.work_dir}", file=sys.stderr)


def _count(root: Path, exts: set[str] | None = None) -> tb.Products:
    return tb.count_products(root, exts)


def _by_ext_round(prod: tb.Products) -> dict:
    return {k: v for k, v in sorted(prod.by_ext.items())}


#: 「尽力清理」的唯一实现在 toolbridge（批次 B3，2026-11-03）。这里只做外观别名：
#: 本文件内部以及测试都用 `orch.drop_tree(...)` 这个名字，别再抄第二份实现——
#: 抄出来的第二份一定会和第一份在「吞什么、重抛什么」上分叉
#: （现在的契约：只重抛 KeyboardInterrupt，SystemExit 也算「没删干净 → False」）。
drop_tree = tb.drop_tree


def _move_dir_clean(src: Path, dst: Path) -> str | None:
    """把 `src` 整目录搬成 `dst`，**保证不会嵌层**；成功返回 None，失败返回原因。

    坑：`shutil.move(src, dst)` 在 `dst` 已存在时不会报错，而是把 `src` 塞成
    `dst/<src.name>/...`。对 KiriKiri GUI 链路来说结果就是 `png/png/*.png`：
    交付清单多一层路径、对账总数照样自洽 —— 属于「无声的错」。
    所以搬之前一律先把目标清掉；清不掉就明确失败，不硬搬。

    单独一个函数是因为这条路径有两处要用（`data → raw/`、`png → png/`），
    而「目标已存在」这个坑已经踩过两次。
    """
    if not drop_tree(dst):
        return (f"目标目录已存在且删不掉，放弃搬移以免嵌层: {dst}"
                f"（可能是受保护目录或安全删除守卫拦住了）")
    try:
        shutil.move(str(src), str(dst))
    except OSError as exc:
        return f"搬移失败 {src} -> {dst}: {type(exc).__name__}: {exc}"
    return None


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
        # 命中信号 id 集合：案例库指纹签名的原料（case_lib.signature）。
        # 只放在这个 stage 的 data 里，**不进 rules 的 facts** —— 那会动 golden 基线。
        "fired_ids": sorted(rep.fired_ids),
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


# ---------------------------------------------------------------- 阶段 1.5: 案例库查表

def stage_case_lookup(ctx: Ctx, detect_data: dict | None = None,
                      cases_dir: Path | str | None = None) -> Stage:
    """按指纹签名查 `cases/` 案例库 —— **只读报告层，永不让解包失败**。

    案例库回答「这个引擎的这个变体上次怎么解出来的、踩过什么坑」，
    不是「这次该怎么解」：提取计划仍由本编排器按归档索引自己算，
    案例里的 `expected_total` **不参与对账**（编排器自己的索引才是地面真相）。

    三种结局都 `ok=True`：命中 N 个 / 无匹配 / 案例库缺失或损坏。
    区别只在 `detail` 与 `data`：把它们混成同一种「空」就等于把
    「看过案例库，没有」和「根本没有案例库」说成同一件事。
    """
    st = Stage("case-lookup")
    t0 = time.time()
    root = Path(cases_dir) if cases_dir else case_lib.DEFAULT_CASES_DIR

    engine = (detect_data or {}).get("engine")
    signals = (detect_data or {}).get("fired_ids")
    if engine is None or signals is None:
        # `--engine` 强制模式没跑 detect：为查表补一次只读扫描（结论不参与判定）。
        try:
            rep = gd.scan(ctx.game_dir)
        except Exception as exc:                            # noqa: BLE001
            st.ok = True
            st.skipped = True
            st.detail = f"为案例查表做的指纹扫描失败：{type(exc).__name__}: {exc}"
            st.data = {"index_present": case_lib.load_index(root) is not None,
                       "signature": None, "candidates": []}
            st.seconds = time.time() - t0
            return st
        best = rep.best
        engine = (best.engine if best else None) or engine
        signals = sorted(rep.fired_ids) if signals is None else signals

    res = case_lib.lookup(engine, signals, root)
    st.data = {**res, "engine": engine, "signals": sorted(signals or [])}
    st.seconds = time.time() - t0
    st.ok = True
    if res["signature"] is None:
        st.skipped = True
        st.detail = "未判出引擎，算不出指纹签名，跳过案例查表"
    elif not res["index_present"]:
        st.skipped = True
        st.detail = "cases/index.json 不存在或不可读，跳过案例查表"
    elif not res["candidates"]:
        st.detail = f"无匹配案例（签名 {res['signature']}）"
    else:
        names = "、".join(
            f"{c['sample']}" + (f"（{c['discriminator']}）" if c.get("discriminator") else "")
            for c in res["candidates"])
        st.detail = (f"命中 {len(res['candidates'])} 个案例"
                     f"（签名 {res['signature']}）：{names}")
        ctx.log("case-lookup", json.dumps(res, ensure_ascii=False, indent=2))
    return st


# ---------------------------------------------------------------- 阶段 1.8: 磁盘预检

#: 预检的估算系数（批次 B1，2026-11-03）。
#: 为什么是 1.15 + 512MiB：RPA/XP3 这类包多是裸存，解包体积≈原包，但 `.tlg`→PNG、
#: `.hg3`→PNG 转换后通常变大，还要留 manifest/日志/AssetStudio 临时目录；
#: 15% 是转换膨胀的余量，512MiB 是「小样本也有地方折腾」的固定地板。
#: 加密 KiriKiri 再叠加一倍（`--allow-gui` 要在 ASCII stage 里放第二份，`krkr_auto_extract` 段）。
PREFLIGHT_OVERHEAD_RATIO = 1.15
PREFLIGHT_RESERVE_BYTES = 512 * 1024 * 1024

#: 可用空间低于「需要量」的这个比例就判失败（不是「差不多就行」：写满盘的后果是
#: 半成品 + 退出码 1，用户得先猜是哪一步炸的）。
PREFLIGHT_MIN_FREE_RATIO = 0.5


def _tree_bytes(root: Path) -> int:
    """递归求目录体积（字节）。单项 `OSError` 跳过，不让坏链接/权限拒炸掉预检。

    用 `os.scandir` 手写而不是 `rglob`：真实样本里 CJK 长路径、杀软占用的文件、
    断掉的符号链接都是常态，任何一个 OSError 都不该让编排在**开始解包之前**崩掉。
    数出来的是**下限**（跳过的项不计），预检只用它做量级判断，不需要精确。
    """
    total = 0
    stack = [str(root)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:                        # 单项坏掉就跳过这一项
                        continue
        except OSError:                                    # 整个目录读不了就跳过
            continue
    return total


def _gb(n: int | None) -> str:
    """字节 → 人话（GB，两位小数）。`None` 显示成「未知」，不装作 0。"""
    if n is None:
        return "未知"
    return f"{n / (1024 ** 3):.2f} GB"


def stage_preflight(ctx: Ctx) -> Stage:
    """解包前的磁盘余量预检（software-plan 风险表承诺过、代码里一直缺的那一条）。

    为什么值得一个阶段：大样本解包体积≈原包，盘不够时会在**中途**失败，
    留下几 GB 半成品；用户看到的是一句工具报错，而不是「你的 D 盘只剩 3 GB」。
    预检把这件事提前到「还没动一个文件」的时候说清楚。

    三档结论：
      · 可用 < 需要的一半      → `ok=False`（继续跑必然写到中途炸）
      · 一半 ≤ 可用 < 需要     → `ok=True` 但标「余量偏紧」并 WARN（也许能跑完，别赌）
      · 可用 ≥ 需要            → 正常放行

    游戏目录不存在/为空时**直接放行**：测试与 `--engine` 强制指定都大量使用这种 ctx，
    预检不该成为「没样本就不能跑」的新门槛。
    `--reuse-raw` 复用时也直接放行：不重新解包，就不该按整份源体积卡盘（见函数内注释）。
    """
    st = Stage("preflight")
    t0 = time.time()
    # 1) 重跑口径（放在体积统计**之前**）：raw 非空又没说要覆盖，后面几十秒的体积统计
    #    和余量判断全是白做，用户拿到的还是一句「跑完了但数字不对」。先快问快答。
    if not ctx.reuse_raw:
        stray = sum(1 for p in ctx.raw_dir.rglob("*") if p.is_file()) \
            if ctx.raw_dir.is_dir() else 0
        if stray and not ctx.overwrite:
            st.ok = False
            st.detail = (f"输出目录已有上一轮产物（raw/ 里 {stray} 个文件）：{ctx.out_dir}。"
                         f"直接重跑会把新旧产物混在一起——产物数照样能自洽，但数字是假的。"
                         f"要清空重跑加 --overwrite；只想复用/验收已有产物用 --reuse-raw。")
            ctx.log("preflight", f"[ERROR] raw 非空且未指定 --overwrite: "
                                 f"{ctx.raw_dir}（{stray} 个文件）")
            st.seconds = time.time() - t0
            return st

    # 先说一句再干活：`_tree_bytes` 整段没有逐文件输出，大样本/机械盘要几十秒，
    # 不打招呼的话 GUI 上看起来就像「卡死在 preflight」（2026-11-04 用户实测 SUMMER）。
    ctx.log("preflight", "正在统计游戏目录体积（大样本可能要几十秒，期间无逐文件输出）…")
    source_bytes = _tree_bytes(ctx.game_dir)
    if ctx.reuse_raw:
        # 复用模式**不重新解包**：磁盘只需要放 raw 的复制与对账产物，不该按整份源体积卡。
        # 而「拿着已解好的 raw 在空间紧张的盘上复跑」恰恰是想省空间的场景，
        # 拿 1.15 倍源体积去挡它等于把最需要复用的人挡在门外。
        st.ok = True
        st.detail = "复用模式，跳过余量预检"
        st.data = {"source_bytes": source_bytes, "required_bytes": None, "free_bytes": None,
                   "reused_from": str(ctx.reuse_raw)}
        st.seconds = time.time() - t0
        return st
    if source_bytes <= 0:
        st.ok = True
        st.detail = "游戏目录为空或不可读，跳过余量预检"
        st.data = {"source_bytes": source_bytes, "required_bytes": None, "free_bytes": None}
        st.seconds = time.time() - t0
        return st

    required = int(source_bytes * PREFLIGHT_OVERHEAD_RATIO) + PREFLIGHT_RESERVE_BYTES
    if ctx.allow_gui:
        # 加密 KiriKiri：ASCII stage 里要放第二份（xp3 优先硬链接，跨卷时才真拷）
        required += source_bytes

    # 输出目录此时可能还不存在：往上找到第一个存在的祖先再问磁盘。
    probe = ctx.out_dir
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        st.ok = True
        st.detail = f"读不到输出盘余量（{type(exc).__name__}: {exc}），跳过预检"
        st.data = {"source_bytes": source_bytes, "required_bytes": required,
                   "free_bytes": None}
        st.seconds = time.time() - t0
        return st

    st.data = {"source_bytes": source_bytes, "required_bytes": required, "free_bytes": free}
    if free < required * PREFLIGHT_MIN_FREE_RATIO:
        st.ok = False
        st.detail = (f"输出盘余量不足：需要约 {_gb(required)}（游戏 {_gb(source_bytes)}，"
                     f"含转换与临时开销），可用 {_gb(free)}。"
                     f"请换到更大的盘，或清出空间后重跑。")
        ctx.log("preflight", f"[ERROR] free={free} required={required} "
                             f"source={source_bytes} out={ctx.out_dir}")
    elif free < required:
        st.ok = True
        st.detail = (f"余量偏紧：需要约 {_gb(required)}，可用 {_gb(free)}"
                     f"（游戏 {_gb(source_bytes)}），大样本可能中途写满")
        ctx.log("preflight", f"[WARN] 余量偏紧 free={free} required={required}")
    else:
        st.ok = True
        st.detail = (f"磁盘余量充足：需要约 {_gb(required)}，可用 {_gb(free)}"
                     f"（游戏 {_gb(source_bytes)}）")
        ctx.log("preflight", f"free={free} required={required} source={source_bytes}")
    st.seconds = time.time() - t0
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
        rc, out = _run_sibling(rpa_extract_organized, [str(arc), str(dest)])
        ctx.log("extract", f"$ rpa_extract_organized.py {arc.name} -> {dest}\n"
                           f"rc={rc}\n{out}")
        got = _count(dest).total if dest.is_dir() else 0
        per_archive.append({"archive": arc.name, "expected": expected, "got": got,
                            "rc": rc})
        if rc != 0 or got != expected:
            st.detail = (f"{arc.name}: 对账失败 期望 {expected} 实得 {got} "
                         f"(rc={rc})")
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
            unlistable: list[str] = []
            per_archive = []
            for xp3 in xp3s:
                ok, entries, _out = tb.garbro_list(xp3)
                if not ok:
                    listable = False
                    unlistable.append(xp3.name)
                    per_archive.append({"archive": xp3.name, "expected": None,
                                        "got": None, "listable": False})
                    continue
                expected += entries
                per_archive.append({"archive": xp3.name, "expected": entries,
                                    "got": None, "listable": True})
            st.data["archives"] = per_archive
            if unlistable:
                # 复用模式下不重导，所以这里不判失败（产物是既有事实），但**必须显式报出**
                # 哪些包没对上地面真相 —— 靠 manifest.source.unsupported 落盘，别只躺在日志里。
                st.data["unsupported"] = [
                    {"archive": n, "reason": "GARbro 列不出条目（地面真相缺失，未对账）"}
                    for n in unlistable]
                ctx.log("extract", f"  [WARN] {len(unlistable)} 个 xp3 列不出条目，未对账: "
                                   f"{', '.join(unlistable)}")
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
        rc, out = _run_sibling(krkr_auto_extract,
                               [str(ctx.game_dir), "--out", str(ctx.out_dir)])
        ctx.log("extract", f"$ krkr_auto_extract.py rc={rc}\n{out}")
        # krkr_auto_extract 产出 <out>/KrkrExtract_Output/{data,png}
        kout = ctx.out_dir / "KrkrExtract_Output"
        if rc != 0 or not kout.is_dir():
            st.detail = f"GUI 链路失败或没有产出 KrkrExtract_Output (rc={rc})"
            st.seconds = time.time() - t0
            return st
        data_dir = kout / "data" if (kout / "data").is_dir() else kout
        # 搬之前先清目标（`_move_dir_clean` 内部保证「不会嵌层」）。两条搬移共用同一个
        # 失败出口：任一条搬不干净就判失败，不让产物停在「搬了一半」的状态。
        err = _move_dir_clean(data_dir, ctx.raw_dir)
        if err is None and (kout / "png").is_dir():
            err = _move_dir_clean(kout / "png", ctx.png_dir)
        if err:
            st.detail = f"GUI 链路产物落盘失败：{err}"
            st.data["move_error"] = err
            st.seconds = time.time() - t0
            return st
        st.ok = True
        st.data.update({"mode": "gui", "raw_total": _count(ctx.raw_dir).total})
        st.detail = f"GUI 链路完成，raw {st.data['raw_total']} 个文件"
        st.seconds = time.time() - t0
        return st

    # 静态可解：逐包 garbro -x，产出落到 raw/<stem>/
    per_archive = []
    expected_total = 0
    unlistable: list[str] = []
    for xp3 in xp3s:
        ok, entries, out = tb.garbro_list(xp3)
        if not ok:
            # 列不出条目 = 这个包的地面真相缺失。绝不能「跳过它、只拿其余包对账」：
            # 那样 expected 少算了却仍然 0 差，等于把漏导洗成通过（2026-11-03 审计 A4）。
            unlistable.append(xp3.name)
            ctx.log("extract", f"$ garbro -l {xp3.name}\n{out[:2000]}")
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
    if unlistable:
        # 已导出的包照旧留在 raw 里（重跑很贵，别白扔），但**本轮判失败并点名是哪个包**：
        # 「有意排除」必须显式报出，而且要走 manifest.source.unsupported 落盘。
        st.data["unsupported"] = [{"archive": n, "reason": "GARbro 列不出条目（地面真相缺失）"}
                                  for n in unlistable]
        st.detail = (f"{len(unlistable)}/{len(xp3s)} 个 xp3 列不出条目："
                     f"{', '.join(unlistable)}；这些包无法对账，本轮判失败")
        st.seconds = time.time() - t0
        return st
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
    rc, out = _run_sibling(rpgmv, [str(www), str(ctx.raw_dir),
                                   "--manifest", str(man)])
    ctx.log("extract", f"$ _rpgmv_decrypt.py {www} -> {ctx.raw_dir}\n"
                       f"rc={rc}\n{out}")
    actual = _count(ctx.raw_dir).total
    st.data = {"www": str(www), "expected_total": expected, "actual_total": actual,
               "reconcile_ok": actual == expected, "rc": rc,
               "archives": [{"archive": str(www.name), "expected": expected,
                             "got": actual}]}
    st.seconds = time.time() - t0
    if actual != expected:
        st.detail = f"对账失败：候选 {expected} vs 落盘 {actual} (rc={rc})"
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
        rc, out = _run_sibling(ypf, [str(arc), str(dest), "--manifest", str(man)])
        ctx.log("extract", f"$ _ypf_extract.py {arc.name} -> {dest}\n"
                           f"rc={rc}\n{out}")
        got = _count(dest).total if dest.is_dir() else 0
        rec.update({"got": got, "rc": rc, "ok": got == rec["expected"]})
        if got != rec["expected"]:
            st.detail = (f"{arc.name}: 对账失败 期望 {rec['expected']} 实得 {got} "
                         f"(rc={rc})")
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
        rc, out = _run_sibling(grp, [str(res_dir), str(audio_dst),
                                     "--manifest",
                                     str(ctx.work_dir / "grp.manifest.json")])
        ctx.log("extract", f"$ _grp_extract.py {res_dir} -> {audio_dst}\n{out}")
        if rc != 0:
            st.detail = f"_grp_extract.py 失败（rc={rc}）：{out.strip()[:200]}"
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
        rc, out = _run_sibling(cs2, [str(ctx.game_dir), str(ctx.raw_dir),
                                     "--manifest",
                                     str(ctx.work_dir / "cs2.manifest.json")])
        tail = out.strip().splitlines()[-8:]
        for line in tail:
            ctx.log("extract", "  " + line)
        if rc != 0:
            st.detail = f"_cs2_int_extract.py 失败（rc={rc}）：{tail[-1] if tail else ''}"
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


# ---------------------------------------------------------------- Unity

#: Texture2D 已知缺口的放行阈值（审计 A3，2026-11-03 定案）。
#: AssetStudio 的 JSON 枚举会列出引用型资产、Convert 不导出，所以「导出数 < 枚举数」是常态
#: （Happiness Double Room 实测 460/455）。但常态不等于可以无限放过：
#: 比例超 2% 或绝对数超 20 就必须红灯（AssetStudio 换版本、纹理被裁、路径写错都会先表现在这里）。
#: 两个条件是**或**：小样本游戏（几十张图）靠比例拦，大样本靠绝对数拦。
UNITY_TEXTURE2D_GAP_RATIO = 0.02
UNITY_TEXTURE2D_GAP_ABS = 20


def _unity_data_dir(game_dir: Path) -> Path | None:
    """找 Unity 的 `<游戏名>_Data` 目录。

    找不到返回 None（不像其他引擎那样直接 SystemExit）。
    """
    for p in game_dir.iterdir():
        if p.is_dir() and p.name.endswith("_Data"):
            return p
    return None


def stage_extract_unity(ctx: Ctx) -> Stage:
    """Unity AssetStudio Convert 导出：图片 + 音频。

    地面真相 = AssetStudio JSON 枚举计数（`_unity_extract.expected_counts()`，唯一出处）。
    对每种类型跑一次 Convert 导出，复制产物到 `raw/<category>/`，对账。

    AudioClip 若是 FSB5 容器，单次 Convert 只能导出约 30%，
    需要多轮 `--names` 分组累积（`_as_audio_collect2.py`）。
    """
    st = Stage("extract")
    t0 = time.time()
    data_dir = _unity_data_dir(ctx.game_dir)
    if data_dir is None:
        st.detail = "没找到 <游戏名>_Data 目录"
        return st

    as_exe = tb.find_tool("assetstudio")
    # 临时目录根必须显式给：裸默认会退到系统 temp，而**绝不能**落回游戏目录
    # （2026-11-02 Happiness Double Room 实测 WinError 5，见 _unity_extract._scratch_root()）
    # 先打招呼：JSON 枚举、单次 Convert、逐条枚举这三段都是「分钟级且无中间输出」，
    # 不打招呼 GUI 上就是三连「卡死」（2026-11-04 用户实测 SUMMER，5627 条音频）。
    ctx.log("extract", "正在用 AssetStudio 枚举资产清单（JSON 口径；大样本 1-3 分钟）…")
    exp = unity.expected_counts(data_dir, as_exe, tmp_root=ctx.work_dir / "unity")
    if exp["total"] == 0:
        # 把子进程诊断拼进失败原因：AssetStudio 起不来（DLL 缺/被拦）和「游戏真没资产」
        # 在计数上都是 0，只有 rc 与 stderr 能区分这两件事。
        extra = "；".join(exp.get("errors") or [])
        st.detail = ("AssetStudio JSON 枚举到 0 个资产"
                     + (f"（子进程诊断：{extra}）" if extra else ""))
        return st

    expected_total = exp["total"]
    archives: list[dict] = []

    if ctx.reuse_raw is None:
        ctx.log("extract", f"开始单次 Convert 导出（JSON 口径 {expected_total} 个资产，"
                           f"图片+音频第一遍；大样本要几分钟，无中间输出）…")
        got = unity.extract_all(data_dir, ctx.raw_dir, as_exe, tmp_root=ctx.work_dir / "unity")
        archives = got.get("archives", [])
        for e in got.get("errors") or []:
            # stderr 在冻结包里不进 GUI 日志，所以把子进程诊断再抄一份到阶段日志
            ctx.log("extract", f"  [WARN] Convert {e}")

        # Audio：单次 Convert 必然丢一批（FSB5 静默丢失，rc 仍是 0），
        # 一律走「枚举名字 → 按名对账 → 只补缺的」（2026-11-02 Happiness Double Room 实测：
        # 446/1441 → 补齐；同一批名字重复跑每次落盘子集不同，故补跑能收敛）。
        audio_got = got["by_type"].get("AudioClip", 0)
        audio_exp = exp["by_type"].get("AudioClip", 0)
        audio_dir = ctx.raw_dir / "Audio"
        # `enumerate_names` 的三种结局必须分开处理（批次 C11）：
        #   None  = 枚举失败（超时/工具没起来）→ 地面真相未知；
        #   []    = 枚举成功但一个名字都没有 → 与「JSON 说有 N 个」自相矛盾；
        #   [...] = 正常，可按名字对账。
        # 旧实现把前两种都变成 []，于是 expected 被算成 0、对账 0 差、验收 0 失败——
        # 一作 1441 条音频没解出来，交付记录却是全绿的。
        if audio_exp > 0:
            ctx.log("extract", f"正在逐条枚举音频名字（ByType + 逐条两遍，JSON 说 "
                               f"{audio_exp} 条；这一步几分钟没有进度输出）…")
        names = (_as_audio_collect2.enumerate_names(data_dir, as_exe,
                                                    ctx.work_dir / "unity")
                 if audio_exp > 0 else [])
        if names is None:
            st.ok = False
            st.detail = (f"音频名字枚举超时/失败，地面真相未知（ByType JSON 说有 "
                         f"{audio_exp} 个 AudioClip）；对账不可信，判失败")
            st.data["audio_enum"] = "failed"
            st.seconds = time.time() - t0
            return st
        if not names and audio_exp > 0:
            st.ok = False
            st.detail = (f"音频名字枚举返回 0 条，但 JSON 枚举说有 {audio_exp} 个 AudioClip"
                         f"（互相矛盾）；对账不可信，判失败")
            st.data["audio_enum"] = "empty-but-expected"
            st.seconds = time.time() - t0
            return st
        if names:
            # 逐条枚举才是真地面真相：ByType 的 JSON 导出会让同名资产互相覆盖而少数
            if len(names) != audio_exp:
                ctx.log("extract",
                        f"音频口径不一致：ByType JSON {audio_exp} vs 逐条枚举 {len(names)}"
                        f"（同名覆盖），以逐条为准")
            audio_exp = len(names)
            exp["by_type"]["AudioClip"] = audio_exp
            exp["total"] = sum(exp["by_type"].values())
            expected_total = exp["total"]
            ctx.log("extract", f"音频单次导出 {audio_got}/{audio_exp}，按名字补齐...")
            res = _as_audio_collect2.collect(data_dir, audio_dir, names, as_exe,
                                             work_root=ctx.work_dir,
                                             log=lambda m: ctx.log("extract", m))
            audio_got = len(list(audio_dir.glob("*.wav")))
            st.data["audio_missing"] = len(res["missing"])
            ctx.log("extract", f"音频补齐后 {audio_got}/{audio_exp}，"
                               f"runs={res['runs']}，缺 {len(res['missing'])}")
        # 旧的「退回前缀分组多轮累积」分支已删（C11）：它只在枚举失败时有用，而枚举失败
        # 现在直接判失败。留着它等于留一条「静默降级」的后门——正是这次要堵的东西。
        if audio_exp > 0:
            got["by_type"]["AudioClip"] = audio_got
            got["total"] = sum(got["by_type"].values())

        # 更新 archives（键名与其它链路一致：manifest 的 source.archives 读 archive/expected/got，
        # 用 name/entries 会落成三个 null——2026-11-02 实测踩到）
        archives = [{"archive": t, "expected": got["by_type"][t], "got": got["by_type"][t]}
                    for t in unity.UNITY_TYPES]
        actual_total = got["total"]
    else:
        # --reuse-raw：不跑 Convert，但仍算地面真相并对账。
        # 逐类落盘数是**扫盘实测**（不给 None，免得交付记录里查不到「每类多少」）；
        # expected 留 None = 本轮没重导，不假装验过（manifest.reconcile 的同一口径）。
        actual_total = _count(ctx.raw_dir).total
        archives = []
        for t in unity.UNITY_TYPES:
            d = ctx.raw_dir / unity.UNITY_CATEGORIES[t]
            got_n = sum(1 for f in d.rglob("*") if f.is_file()) if d.is_dir() else 0
            archives.append({"archive": t, "expected": None, "got": got_n})

    # Texture2D 已知缺口：AssetStudio 的 JSON 枚举会列出所有资产（含引用型），
    # 但 Convert 只导出可直接使用的资产（Happiness Double Room 实测 460 枚举 / 455 导出）。
    #
    # 2026-11-03 修（审计 A3）：缺口**绝不参与 expected 的削减**。原实现
    # `expected = 总数 − 缺口`，等于让缺口自己迁就自己：导出少 5 个就把期望也减 5，
    # 无论少多少都 0 差 —— 这正是「无声的漏验」。现在改成两条硬约束：
    #   1. 缺口只允许出现在 Texture2D 这一类，其它类必须逐类严格相等；
    #   2. Texture2D 缺口必须在阈值内（比例 ≤ 2% 且绝对数 ≤ 20），超了判失败
    #      —— 常态 5 个放行但**显式报出**，AssetStudio 行为一变就立刻红灯。
    got_by_type = {a["archive"]: a["got"] for a in archives}
    texture2d_exp = exp["by_type"].get("Texture2D", 0)
    texture2d_actual = got_by_type.get("Texture2D", 0)
    texture2d_gap = texture2d_exp - texture2d_actual
    texture2d_ratio = (texture2d_gap / texture2d_exp) if texture2d_exp else 0.0
    gap_over = texture2d_gap > 0 and (texture2d_ratio > UNITY_TEXTURE2D_GAP_RATIO
                                      or texture2d_gap > UNITY_TEXTURE2D_GAP_ABS)

    # 非 Texture2D 的类不允许有任何差：否则「图片少 5 张」会被记成 Texture2D 缺口混过去。
    type_mism = [f"{t}：枚举 {exp['by_type'].get(t, 0)} vs 落盘 {got_by_type.get(t, 0)}"
                 for t in unity.UNITY_TYPES
                 if t != "Texture2D"
                 and got_by_type.get(t, 0) != exp["by_type"].get(t, 0)]
    # 总账：落盘比枚举少的部分必须**恰好**等于 Texture2D 缺口，多出来的短缺无处解释。
    shortfall = expected_total - actual_total

    st.data["json_total"] = expected_total
    st.data["expected_total"] = expected_total      # 缺口不削减期望值（见上）
    st.data["actual_total"] = actual_total
    st.data["archives"] = archives
    st.data["json_counts"] = exp["by_type"]
    st.data["texture2d_gap"] = texture2d_gap

    if gap_over:
        st.ok = False
        st.detail = (f"对账失败：AssetStudio 只导出了 {texture2d_actual}/{texture2d_exp} 个 "
                     f"Texture2D（缺口 {texture2d_gap} 个，占 {texture2d_ratio:.1%}，超过阈值 "
                     f"{UNITY_TEXTURE2D_GAP_RATIO:.0%}/{UNITY_TEXTURE2D_GAP_ABS} 个）")
    elif type_mism:
        st.ok = False
        st.detail = ("对账失败：缺口只允许出现在 Texture2D，但 " + "；".join(type_mism[:3]))
    elif shortfall != texture2d_gap:
        st.ok = False
        st.detail = (f"对账失败：JSON 枚举 {expected_total} vs 落盘 {actual_total}"
                     f"（差 {shortfall}，但 Texture2D 缺口只能解释 {texture2d_gap}）")
    else:
        st.ok = True
        gap_note = (f"，Texture2D 已知缺口 {texture2d_gap} 个"
                    f"（{texture2d_actual}/{texture2d_exp}）" if texture2d_gap > 0 else "")
        st.detail = (f"JSON 枚举 {expected_total} 个资产，Convert 导出 {actual_total} 个文件"
                     f"{gap_note}，对账 0 差")
    st.seconds = time.time() - t0
    return st


# ---------------------------------------------------------------- Artemis（pf8 / .pfs）

#: Artemis 的散装媒体后缀（不在 .pfs 里的裸媒体：特典 mp3/图、电影）。
_ARTEMIS_LOOSE_EXT = IMG_EXT | AV_EXT

#: ASF/WMV 容器头 GUID（同 AdvHD 的 .dat）：Artemis 把开场电影存成 movie/*.dat。
_ASF_GUID = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")


def _artemis_loose_media(game_dir: Path) -> list[tuple[Path, Path]]:
    """散装媒体，返回 [(源, 相对 raw 的目标)]（目标一律落在 raw/loose/ 下）。

    媒体本体按**扩展名**认（特典目录下就是裸 mp3/jpg）；另外 .dat 若以 ASF GUID 开头
    （开场电影）也收，落盘改后缀 .wmv——**只改扩展名，不转码**（与 AdvHD 的 .dat 同款）。
    目标保持游戏内相对路径，出问题时能一眼看出它原来在哪。
    """
    out: list[tuple[Path, Path]] = []
    for p in sorted(game_dir.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in _ARTEMIS_LOOSE_EXT:
            out.append((p, Path("loose") / p.relative_to(game_dir)))
        elif ext == ".dat" and _head(p, 16) == _ASF_GUID:
            out.append((p, (Path("loose") / p.relative_to(game_dir)).with_suffix(".wmv")))
    return out


def _artemis_expected(game_dir: Path, *,
                      raw_dir: Path | None = None) -> tuple[int, bool, list[dict]]:
    """算 Artemis 的期望落盘数：Σ 归档条目数 + 散装媒体个数。

    条目数来自 pfs.expected_counts()（**地面真相唯一出处**，别在这儿重解析索引）。
    每项明细带上 identity_ok（字节恒等式 7+index_size+Σsize==文件大小）——索引偏移
    或 key 传输错了它先炸，对账只是第二道闸。
    raw_dir 给了就同时把 got 填上（按 raw/<归档文件名>/ 数文件）。
    """
    exp = pfs.expected_counts(game_dir)
    per_archive: list[dict] = []
    expected = 0
    listable = True
    for name, n in sorted(exp["by_arc"].items()):
        got = None
        if raw_dir is not None:
            dest = raw_dir / name
            got = _count(dest).total if dest.is_dir() else 0
        expected += n
        per_archive.append({"archive": name, "expected": n, "got": got,
                            "identity_ok": exp["identity"].get(name), "listable": True})
    for name in exp["unlistable"]:
        listable = False
        per_archive.append({"archive": name, "expected": None, "got": None,
                            "listable": False})
    loose = _artemis_loose_media(game_dir)
    got_loose = None
    if raw_dir is not None:
        got_loose = sum(1 for _src, rel in loose if (raw_dir / rel).exists())
    expected += len(loose)
    per_archive.append({"archive": "(散装 mp3/jpg/ASF .dat)", "expected": len(loose),
                        "got": got_loose, "listable": True})
    return expected, listable, per_archive


def stage_extract_artemis(ctx: Ctx) -> Stage:
    """Artemis Engine（pf8/pf6/pf2）：索引 + SHA1(索引) 循环 XOR 解密 + 散装媒体复制。

    地面真相 = pfs.expected_counts()（自研 _pfs_extract.py 逆向后解析）。
    对账做**两层**：逐包（raw/<归档文件名>/ 的文件数 vs 索引条目数）与总计——
    三个包之间**有重名**（本作实测 70 个），总数对上也可能互相盖掉，
    所以每个归档各落一个子目录：平铺会让后一个包覆盖前一个包（落盘 3977 变 3907，
    而总数看着「对」）。

    解密是内联在落盘里的：**raw 就是成品**（png/ogg 原样），所以 raw == final、converted 为空。
    --reuse-raw 时不重新解包，但**照旧算同一份地面真相并对账**（跳的是解包不是验收）。
    """
    st = Stage("extract")
    t0 = time.time()
    exp = pfs.expected_counts(ctx.game_dir)
    loose = _artemis_loose_media(ctx.game_dir)
    if not exp["arcs"] and not loose:
        st.detail = "顶层既没有 pf8/pf6/pf2 归档，也没有散装媒体"
        st.seconds = time.time() - t0
        return st

    # 先算地面真相：失败路径也要能报出「期望多少」，否则对账失败时看不出差在哪。
    expected, listable, per_archive = _artemis_expected(ctx.game_dir)

    if ctx.reuse_raw:
        # 复用模式：不重新解包，但**仍然算地面真相** —— 对账不能因为跳步就失效。
        st.skipped = True
        st.ok = True
        st.detail = f"复用已有 raw: {ctx.reuse_raw}"
        actual = _count(ctx.raw_dir).total
        expected, listable, per_archive = _artemis_expected(ctx.game_dir, raw_dir=ctx.raw_dir)
        st.data = {"reused_from": str(ctx.reuse_raw), "actual_total": actual,
                   "archives": per_archive}
        st.seconds = time.time() - t0
        if not listable:
            st.ok = False
            st.data["reason"] = "有归档索引解析失败，无完整地面真相，未对账"
            st.detail = f"复用已有 raw，{actual} 个文件；有归档列不出条目，未对账"
            return st
        st.data["expected_total"] = expected
        if actual != expected or any(a["expected"] != a["got"] for a in per_archive):
            st.detail = f"复用产物对账失败：索引 {expected} vs 落盘 {actual}，请检查逐包明细"
            st.ok = False
            return st
        st.detail = f"复用已有 raw，对账 {expected} == {actual}"
        return st

    ctx.raw_dir.mkdir(parents=True, exist_ok=True)
    rc, out = _run_sibling(pfs, [str(ctx.game_dir), str(ctx.raw_dir),
                                 "--manifest",
                                 str(ctx.work_dir / "pfs.manifest.json")])
    tail = out.strip().splitlines()[-8:]
    for line in tail:
        ctx.log("extract", "  " + line)
    if rc != 0:
        st.detail = f"_pfs_extract.py 失败（rc={rc}）：{tail[-1] if tail else ''}"
        st.data = {"archives": per_archive}
        st.seconds = time.time() - t0
        return st

    # 散装媒体 → raw/loose/<游戏内相对路径>
    for src, rel in loose:
        dst = ctx.raw_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(src, dst)
        ctx.log("extract", f"[媒体] {src.relative_to(ctx.game_dir)} → raw/{rel.as_posix()}")

    # 跑完了再算一次，这回把 got 填上（期望值与上面同源，不会漂）
    _e, _l, per_archive = _artemis_expected(ctx.game_dir, raw_dir=ctx.raw_dir)
    actual_total = _count(ctx.raw_dir).total
    mism = [f"{a['archive']}(索引 {a['expected']} vs 落盘 {a['got']})"
            for a in per_archive
            if a.get("listable") and a.get("got") is not None and a["got"] != a["expected"]]
    st.data = {"mode": "static", "archives": per_archive, "loose_media": len(loose),
               "actual_total": actual_total, "identity": exp["identity"],
               "raw_by_ext": _count(ctx.raw_dir).by_ext}
    st.seconds = time.time() - t0
    if not listable:
        # 有归档列不出，不能将不完整提取报为成功。
        st.ok = False
        st.data["reason"] = "有归档索引解析失败，无完整地面真相，未对账"
        st.detail = f"落盘 {actual_total} 个文件，有归档列不出条目，未对账"
        return st
    st.data["expected_total"] = expected
    if mism:
        st.detail = "逐包对账失败：" + "；".join(mism[:3])
        return st
    if actual_total != expected:
        st.detail = f"对账失败：索引 {expected} vs 落盘 {actual_total}"
        return st
    st.ok = True
    st.detail = (f"{len(exp['arcs'])} 个 .pfs {exp['total']} 条 + {len(loose)} 个散装媒体，"
                 f"{actual_total} 个文件，对账 0 差")
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
    "Unity": "stage_extract_unity",
    "Artemis": "stage_extract_artemis",
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
    before = tb.count_products(ctx.png_dir).total     # --reuse-raw 复跑时 png/ 已有上一轮成品
    try:
        # `min_products=0`：产物数一律由下面按「目录总量 vs 期望」判。
        # 不能按**增量**判——复跑时上一轮的成品都还在，增量天然是 0，
        # 会在一次完全正确的解包上报「产物不足」（甜蜜女友2+ 复跑实测撞上过）。
        res = tb.run_csharp("hg3", [str(ctx.raw_dir), str(ctx.png_dir)],
                            product_dir=ctx.png_dir, min_products=0)
    except Exception as exc:                     # 编译失败/找不到 csc 都得说清楚
        st.detail = f"自带 C# 工具 _hg3_tool 无法启用：{exc}"
        st.seconds = time.time() - t0
        return st
    if not res.ok:
        st.detail = f"_hg3_tool 解码失败：{res.reason}"
        st.seconds = time.time() - t0
        return st

    got = tb.count_products(ctx.png_dir).total        # 目录总量，不是本轮增量
    st.seconds = time.time() - t0
    if got != hg3["png_count"]:
        # rc=0、产物也不是 0，只是**比该有的少**（撞车之外的漏解）——最危险的一类，
        # 只有拿产出数跟期望数硬比才看得见。
        st.data = {"tool": "_hg3_tool", "in": hg3["count"], "ok": got, "fail": 0,
                   "renamed": norm["renamed"], "expected_png": hg3["png_count"],
                   "new": got - before}
        st.detail = (f"_hg3_tool 产物数不符：期望 {hg3['png_count']} vs 落盘 {got}"
                     f"（HG-3 文件 {hg3['count']} 个；本轮新增 {got - before}）")
        return st

    ctx.consumed = [Path(p).relative_to(ctx.raw_dir).as_posix() for p in hg3["files"]]
    st.ok = True
    st.data = {"tool": "_hg3_tool", "in": hg3["count"], "ok": got, "fail": 0,
               "frames_out": got, "renamed": norm["renamed"], "new": got - before,
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


def _probe_one(p: Path, label: str) -> dict:
    """探**一个**产物，返回一条不可变的事实（kind / ok / fail / duration）。

    抽出来是为了并行化时「串行 = 并行」在实现上就是同一段代码 —— 两条路径不可能漂移
    （这是结果能进回归的前提）。约束：**纯函数**，不碰 ctx、不写日志、不改任何全局状态；
    worker 线程只负责算，写日志与聚合留给主线程。

    kind 取值：zero / image / audio / video / nonmedia / probe-error。
    """
    ext = p.suffix.lower()
    # 0 字节文件先看是不是源本身声明的空占位（AGENTS.md Ren'Py 段：
    # 「0 字节文件要先查索引」——源包声明 0 长度属正常，不是解包 bug）。
    # 通用链路拿不到索引，所以这里先单列不算失败，末尾用比例护栏兜底。
    try:
        is_empty = p.stat().st_size == 0
    except OSError:
        is_empty = False
    if is_empty:
        return {"kind": "zero", "ok": True, "fail": None, "duration": 0.0}
    if ext in IMG_EXT:
        try:
            from PIL import Image
            with Image.open(p) as im:
                im.verify()
            return {"kind": "image", "ok": True, "fail": None, "duration": 0.0}
        except Exception as exc:                               # noqa: BLE001
            return {"kind": "image", "ok": False, "duration": 0.0,
                    "fail": f"[image] {label} :: {type(exc).__name__}: {exc}"}
    if ext in AV_EXT:
        info, why = tb.ffprobe_ex(p)
        if info is None:
            # 带上原因：`ffprobe 无结果` 把「文件真坏」「子进程没起来/超时」
            # 「JSON 里没有音视频流」混成一句，看日志的人无从判断该不该慌。
            return {"kind": "audio", "ok": False, "duration": 0.0,
                    "fail": f"[av] {label} :: ffprobe 无结果——{why}"}
        return {"kind": "video" if info["kind"] == "video" else "audio",
                "ok": True, "fail": None, "duration": info.get("dur") or 0.0}
    return {"kind": "nonmedia", "ok": True, "fail": None, "duration": 0.0}


def _probe_one_safe(p: Path, label: str) -> dict:
    """`_probe_one` 的兜底版：探测本身抛异常 → 降级成一条失败事实。

    为什么必须在 worker 里兜住：线程池里一个 future 抛异常，`future.result()` 会把异常
    重新抛到主线程，整个 verify 阶段就没了——一个坏文件不该让 3499 个文件白验。
    """
    try:
        return _probe_one(p, label)
    except Exception as exc:                                   # noqa: BLE001
        return {"kind": "probe-error", "ok": False, "duration": 0.0,
                "fail": f"[probe] {label} :: {type(exc).__name__}: {exc}"}


def resolve_verify_jobs(ctx: Ctx) -> int:
    """决定 verify 的并发度：`--verify-jobs` > 环境变量 > 默认 8。

    为什么默认 8：瓶颈是**子进程启动 + 磁盘**（实测单文件 ffprobe ≈114ms，几乎全是
    `CreateProcess` 与文件头读），8 路足够把等待重叠掉；再往上加对机械硬盘只会互相抢。
    `1` 是保底档：完全不进线程池，行为与并行化之前逐字一致（用作回退与回归基准）。
    """
    if ctx.verify_jobs is not None:
        return max(1, int(ctx.verify_jobs))
    raw = os.environ.get("GALUNPACK_VERIFY_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            ctx.log("verify", f"[WARN] GALUNPACK_VERIFY_WORKERS={raw!r} 不是整数，用默认值")
    return VERIFY_WORKERS


def stage_verify(ctx: Ctx) -> Stage:
    st = Stage("verify")
    t0 = time.time()
    if not ctx.do_verify:
        st.ok = True
        st.skipped = True
        st.detail = "按 --no-verify 跳过（manifest 会标记未验收）"
        # reason 是 `manifest.verify_status()` 区分「没验」与「验失败」的唯一依据：
        # verified=False 但 reason=disabled 属于**主动跳过**，报 failed 会冤枉一次正常运行。
        st.data = {"verified": False, "reason": "disabled"}
        st.seconds = time.time() - t0
        return st

    files = _final_files(ctx)
    if not files:
        st.detail = "没有可验收的产物"
        # 带一个显式 reason：run() 要靠它把 error 码从笼统的 verify-failed 细分成
        # verify-no-products。否则复盘时看到 verify-failed，分不清是「产物坏了」
        # 还是「压根没有产物」—— 24 个坏文件和一个都没产出，处置方式完全不同。
        st.data = {"verified": False, "reason": "no-products"}
        st.seconds = time.time() - t0
        return st

    # ---- 探测：串行（jobs=1）或线程池，结果按下标写回预分配数组 ----
    jobs = resolve_verify_jobs(ctx)
    results: list[dict | None] = [None] * len(files)
    cancelled = False
    if jobs <= 1:
        for i, (p, label) in enumerate(files, 1):
            results[i - 1] = _probe_one_safe(p, label)
            if i % 200 == 0 and ctx.should_stop():
                cancelled = True
                break
    else:
        with ThreadPoolExecutor(max_workers=min(jobs, len(files))) as pool:
            pending = {pool.submit(_probe_one_safe, p, label): i
                       for i, (p, label) in enumerate(files)}
            done = 0
            for fut in as_completed(pending):
                results[pending[fut]] = fut.result()
                done += 1
                if done % 200 == 0 and ctx.should_stop():
                    # 已在跑的探测拦不住（ffprobe 是阻塞子进程），但没开始的可以撤掉；
                    # 撤掉之后不再收结果 → files_checked 只会算真正验过的那些。
                    cancelled = True
                    for f2 in pending:
                        f2.cancel()
                    break
    ctx.log("verify", f"probe: files={len(files)} jobs={min(jobs, len(files))}"
                      f"{'（串行）' if jobs <= 1 else ''}")

    # ---- 聚合：**必须按 files 原顺序**遍历 ----
    # 并行只影响「谁先算完」，不能影响「计数与 fails 的书写顺序」：否则同一份产物两次
    # 跑出两份顺序不同的 manifest，diff 起来全是噪声，也没法拿串行档当回归基准。
    img_ok = img_fail = 0
    audio_ok = audio_fail = 0
    video_ok = video_fail = 0
    nonmedia = 0
    probe_fail = 0
    nonmedia_by_ext: dict[str, int] = {}
    zero_byte: list[str] = []
    audio_seconds = 0.0
    fails: list[str] = []
    checked = 0

    for i, (_p, label) in enumerate(files, 1):
        res = results[i - 1]
        if res is None:                       # 取消后没验的部分
            continue
        checked += 1
        kind = res["kind"]
        if kind == "zero":
            zero_byte.append(label)
        elif kind == "image":
            if res["ok"]:
                img_ok += 1
            else:
                img_fail += 1
                fails.append(res["fail"])
        elif kind in ("audio", "video"):
            if not res["ok"]:
                audio_fail += 1
                fails.append(res["fail"])
            elif kind == "video":
                video_ok += 1
                audio_seconds += res["duration"]
            else:
                audio_ok += 1
                audio_seconds += res["duration"]
        elif kind == "nonmedia":
            nonmedia += 1
            ext = _p.suffix.lower()
            nonmedia_by_ext[ext] = nonmedia_by_ext.get(ext, 0) + 1
        else:                                  # probe-error：探测本身炸了，算失败但要能区分
            probe_fail += 1
            fails.append(res["fail"])
        if i % 500 == 0:
            ctx.log("verify", f"  [{i}/{len(files)}] img={img_ok}/{img_fail} "
                              f"audio={audio_ok}/{audio_fail} video={video_ok}/{video_fail}")

    if cancelled:
        st.ok = False
        st.detail = f"用户取消：已验收 {checked}/{len(files)} 个文件"
        st.data = {
            "cancelled": True, "verified": False, "files_checked": checked,
            "image_ok": img_ok, "image_fail": img_fail,
            "audio_ok": audio_ok, "audio_fail": audio_fail,
            "video_ok": video_ok, "video_fail": video_fail,
            "nonmedia": nonmedia,
            "nonmedia_by_ext": dict(sorted(nonmedia_by_ext.items())),
            "zero_byte": len(zero_byte),
            "media_minutes": round(audio_seconds / 60.0, 1),
            "fail_examples": fails[:10],
        }
        st.seconds = time.time() - t0
        return st

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

    # 非媒体文件必须**显式报出**（批次 B4）。它们不计失败（.txt/.dat 确实不是媒体），
    # 但「没验」和「验过了没问题」是两件事：`.mos` 那次就是媒体落进这条分支被静默放过，
    # 验收照样报「失败 0」。按扩展名聚合，detail/log/manifest 三处都写清楚。
    nonmedia_ranked = sorted(nonmedia_by_ext.items(), key=lambda kv: (-kv[1], kv[0]))
    for ext, n in nonmedia_ranked[:10]:
        ctx.log("verify", f"  NONMEDIA {ext or '(无扩展名)'} x{n}")
    nonmedia_note = ""
    if nonmedia:
        shown = "、".join(f"{ext or '(无扩展名)'} {n}" for ext, n in nonmedia_ranked[:5])
        more = "…" if len(nonmedia_ranked) > 5 else ""
        nonmedia_note = f"；另有 {nonmedia} 个非媒体文件未验收（{shown}{more}）"

    st.data = {
        "verified": True,
        "files_checked": len(files),
        "jobs": min(jobs, len(files)),
        "image_ok": img_ok, "image_fail": img_fail,
        "audio_ok": audio_ok, "audio_fail": audio_fail,
        "video_ok": video_ok, "video_fail": video_fail,
        "nonmedia": nonmedia,
        "nonmedia_by_ext": dict(sorted(nonmedia_by_ext.items())),
        "zero_byte": len(zero_byte),
        "zero_byte_examples": zero_byte[:10],
        "media_minutes": round(audio_seconds / 60.0, 1),
        "fail_examples": fails[:10],
        "probe_fail": probe_fail,
    }
    st.seconds = time.time() - t0
    total_fail = img_fail + audio_fail + video_fail + probe_fail + (0 if zero_ok else 1)
    # `fail_total` 是 manifest.verify.status 的判定依据（单值结论的输入）。
    # 它必须由阶段自己写：把所有失败维度加总的规则只有这里知道，下游再拼一次必然漏。
    st.data["fail_total"] = total_fail
    if total_fail:
        st.detail = f"{total_fail} 个产物验收失败" + nonmedia_note
        return st
    st.ok = True
    st.detail = (f"图片 {img_ok}/{img_ok}、音频 {audio_ok}/{audio_ok}、"
                 f"视频 {video_ok}/{video_ok}，失败 0"
                 + (f"（另有 {len(zero_byte)} 个 0 字节占位文件，未计入）"
                    if zero_byte else "")
                 + nonmedia_note)
    return st


# ---------------------------------------------------------------- 阶段 5: manifest

def build_manifest(ctx: Ctx, stages: list[Stage], engine: str | None) -> dict:
    """按 `manifest.py` 的契约拼 manifest（counts 三段式实现在那边）。"""
    def stage_data(name: str) -> dict:
        for s in stages:
            if s.name == name:
                return s.data
        return {}

    def stage_skipped(name: str) -> bool:
        """「这个阶段跳过了吗」的唯一判据是 `Stage.skipped`。

        批次 C3 删掉了旧的 `data["_skipped"]` 判据：生产代码从来没人写这个 key
        （跳过一律用 `Stage.skipped` 表达），只有测试在手工塞——一个只存在于测试里的
        字段最容易骗人：真跳过时它不在，读代码的人却以为它在。
        """
        for s in stages:
            if s.name == name:
                return bool(s.skipped)
        return False

    extract_data = stage_data("extract")
    post_data = stage_data("postprocess")
    verify_data = stage_data("verify")
    # verify 阶段**根本没跑**（前面 extract/postprocess 就失败了）时补 reason=not-run：
    # stage_verify 自己会给 `--no-verify` 补 disabled，但它没跑过就没人补，
    # 于是 manifest.verify.status 会把「压根没验」判成 failed —— 冤枉一次提前失败的运行。
    if "reason" not in verify_data and not any(s.name == "verify" for s in stages):
        verify_data = {**verify_data, "reason": "not-run"}

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

    # 案例库命中也要进 source：跟 unsupported 同理 —— 读 manifest 的人看的是 source，
    # 不会去翻 stages 里某一项的 data。**没命中就不写**，不给每条链路凭空加字段。
    case_data = stage_data("case-lookup")
    candidates = case_data.get("candidates") or []
    if candidates:
        source["case_match"] = {
            "signature": case_data.get("signature"),
            "candidates": [{
                "case_id": c.get("case_id"),
                "sample": c.get("sample"),
                "engine_label": c.get("engine_label"),
                "discriminator": c.get("discriminator"),
                "provenance": c.get("provenance"),
                "decision": c.get("decision"),
                "failures": c.get("failures", 0),
                **({"missing": True} if c.get("missing") else {}),
            } for c in candidates],
        }

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
            # status 的判定依据（`manifest.verify_status` 优先读它）。阶段自己算的总失败数
            # 比下游再拼一次可靠：零字节超护栏这类结论只有阶段知道。
            "fail_total": verify_data.get("fail_total"),
            **({"reason": verify_data["reason"]} if verify_data.get("reason") else {}),
            "media_minutes": verify_data.get("media_minutes"),
            # 非媒体文件也要进交付记录（批次 B4）：它们是「没验」的文件，
            # 只躺在 stage 的 data 里等于只有翻日志的人才知道。按扩展名聚合，
            # 让读 manifest 的人一眼看出「这里面有多少 .txt/.dat 其实没人看过」。
            "nonmedia": verify_data.get("nonmedia"),
            "nonmedia_by_ext": verify_data.get("nonmedia_by_ext") or {},
        },
        postprocess=([dict({"tool": post_data.get("tool"), "in": post_data.get("in"),
                            "ok": post_data.get("ok"), "fail": post_data.get("fail")},
                           **({"consumed": len(post_data["consumed"])}
                              if post_data.get("consumed") else {}))]
                     if post_data and not stage_skipped("postprocess") else []),
        png_dir=manifest.scan_png(ctx.png_dir),
        stages=[s.as_dict() for s in stages],
    )


# ---------------------------------------------------------------- 主流程

def _write_manifest(ctx: Ctx, man: dict) -> Path | None:
    """manifest 的**唯一**落盘出口：成功与失败都走这里。

    为什么必须收成一个出口（审计 A1，2026-11-03）：verify/extract/postprocess 失败时
    原先直接 return，manifest 不落盘，于是磁盘上留着**上一次**成功的结果。
    CLI 又拿「文件存在」当「本轮的结论」，用户看到的 counts / 对账 / 验收全是旧的
    ——实测在 Happiness Double Room 上把 `png/` 改名重跑，退出码 1、屏幕却报 2500 个
    文件 0 失败。交付记录失真比崩溃更坏，因为它看起来是绿的。

    写失败不抛：manifest 写不下去时返回值给 None，由调用方把「没写成功」报出去，
    别让一次 IO 失败盖掉原本的阶段错误。
    """
    try:
        # 「这份文件是完整写出来的」这个事实由**写盘这个动作本身**保证，所以标在这里：
        # 磁盘那份没法用 stages 里的 manifest 阶段表达它（那是自我指涉）。
        # 读 manifest 的人不必靠「stages 少一条」推断这次写没写成（批次 C16）。
        man["manifest_written"] = True
        ctx.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.manifest_path.write_text(
            json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:                                  # noqa: BLE001
        ctx.log("manifest", f"[ERROR] 写 manifest 失败: {type(exc).__name__}: {exc}")
        return None
    return ctx.manifest_path


def _prog_name() -> str:
    """给人工方案里的命令用：冻结包是 exe，源码态是 python 脚本。"""
    return "orchestrator.exe" if getattr(sys, "frozen", False) else "python orchestrator.py"


def _manual_tools() -> dict[str, str]:
    """人工方案里要写「随包工具的绝对路径」—— 找不到就留空，让方案用兜底文案。

    只解析两个真正会用到 GUI 的工具：krkr（加密 xp3）与 assetstudio（Unity 兜底）。
    解析失败绝不能连累失败路径本身（那会把「给建议」变成「又炸一次」）。
    """
    out: dict[str, str] = {}
    for key in ("krkr", "assetstudio"):
        try:
            out[key] = str(tb.find_tool(key))
        except Exception:                                   # noqa: BLE001
            continue
    return out


def _finish_failure(ctx: Ctx, stages: list[Stage], engine: str | None,
                    rc: int, error: str, t_all: float) -> tuple[int, dict]:
    """非 0 退出路径的统一收尾：本轮 manifest 落盘（`ok=False` + `error`）并返回包装结果。

    `counts` / `verify` 一律是**本轮真实数据**：没跑到的阶段就是 null / 0，
    绝不回填上一轮的数字（伪造一份「看起来完成了」的交付记录是本项目最贵的错）。

    半自动协作（2026-11-04）：失败不是终点。这里同时产出一份**人工介入方案**
    （`manual` 块），明确告诉用户做什么能把这一轮救回来 —— 有些障碍人工 3 分钟，
    自动绕 40 分钟还不一定成（见 manual.py 的模块说明）。
    """
    man = build_manifest(ctx, stages, engine)
    man["ok"] = False
    man["error"] = error
    man["total_seconds"] = round(time.time() - t_all, 1)
    man["stages"] = [s.as_dict() for s in stages]

    plan = manual.plan_for(error, engine=engine, game_dir=ctx.game_dir,
                           out_dir=ctx.out_dir, raw_dir=ctx.raw_dir,
                           png_dir=ctx.png_dir, prog=_prog_name(),
                           tools=_manual_tools(), stages=man["stages"])
    if plan is not None:
        man["manual"] = plan.as_dict()
        # 终端区块 GUI 用户看不到（worker 的 stdout 不进日志面板），
        # 所以完整方案再落一份到 `_work/manual.log`：摘要只显示前 3 步，
        # 用户要照着做完时得能看到全部步骤。
        ctx.log("manual", plan.render())

    _write_manifest(ctx, man)

    # 失败日志写**软件根目录**（与产物解耦）：输出目录本身可能就是建不出来的那个，
    # `_work/*.log` 靠不住。这条永不抛，写不进去顶多 stderr 一行（见 faillog.py）。
    faillog.log_failure(error=error, engine=engine, game_dir=ctx.game_dir,
                        out_dir=ctx.out_dir, stages=man["stages"], rc=rc)
    res = {"error": error, "engine": engine, "manifest": man, "stages": man["stages"]}
    if plan is not None:
        # 同一份数据两处消费：main() 打终端区块、GUI 摘要取前几步。
        # 存 dict 而不是对象：res 有时会被 --json 写盘（对象不可序列化）。
        res["manual"] = man["manual"]
    return rc, res


def _run_stage(name: str, fn, ctx: Ctx) -> Stage:
    """跑一个阶段函数，把**非预期**异常收敛成一个 `ok=False` 的 Stage。

    为什么必须兜住（审计 A2）：`run()` 是 CLI 和 GUI 工作线程的直接入口。异常逃出去，
    调用方拿到的是 traceback 而不是「哪一步、因为什么失败了」；GUI 只显示一句
    「运行异常（看日志）」，manifest 也不落盘 —— 等于把一次失败变成一次失联。
    兜住之后失败照样是一等公民：阶段明细 + 日志里的完整 traceback + 落盘 manifest。

    只吞 `Exception`：`KeyboardInterrupt`/`SystemExit` 必须穿透，否则跑了几十分钟的解包
    按 Ctrl+C 停不下来。
    """
    t0 = time.time()
    try:
        return fn(ctx)
    except Exception as exc:                                # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        ctx.log(name, f"[异常] {detail}\n{traceback.format_exc()}")
        return Stage(name, ok=False, seconds=time.time() - t0,
                     detail=f"阶段异常 {detail}",
                     data={"exception": type(exc).__name__, "message": str(exc)})


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
            return _finish_failure(ctx, stages, engine, 3, "detect-failed", t_all)

    # 1.5 案例库查表（只读报告层）
    # 放在「引擎是否实现链路」检查**之前**：未接链路的引擎（如 Tyrano-Electron）
    # 也能看到历史案例——SPITE 的 ChaCha20 路径与坑就记在案例里，退出码 2 也值得报出来。
    stages.append(stage_case_lookup(ctx, st.data))

    # 引擎是否已实现链路
    ctx.engine = engine          # 后处理按引擎分派（CatSystem2 走魔数那条），必须回填
    chain_ok = engine in IMPLEMENTED
    if not chain_ok:
        st = Stage("extract", ok=False,
                   detail=f"引擎 {engine} 已判出，但本阶段尚未实现链路（已实现: "
                          f"{', '.join(IMPLEMENTED)}）")
        stages.append(st)
        return _finish_failure(ctx, stages, engine, 2, "chain-not-implemented", t_all)

    # 1.8 磁盘余量预检（链路已确认可跑才做：没链路时不必谈盘）
    st = _run_stage("preflight", stage_preflight, ctx)
    stages.append(st)
    if not st.ok:
        return _finish_failure(ctx, stages, engine, 1, "preflight-failed", t_all)

    # 1.9 清场（--overwrite）：preflight 已经拦过「raw 非空又没说要覆盖」的情况，
    #     走到这里只可能是用户明确要求覆盖。png/ 一起清——只清 raw 会让上一轮的
    #     转换成品混进本轮交付（final 口径直接多出一批不该有的图）。
    if ctx.overwrite and not ctx.reuse_raw:
        cleared: dict[str, int] = {}
        for name, d in (("raw", ctx.raw_dir), ("png", ctx.png_dir)):
            if not d.is_dir():
                continue
            n = sum(1 for p in d.rglob("*") if p.is_file())
            if not drop_tree(d):
                stages.append(Stage("reset", ok=False,
                                    detail=f"--overwrite 清空 {name}/ 失败：{d}（受保护目录或"
                                           f"安全删除守卫拦住）"))
                return _finish_failure(ctx, stages, engine, 1, "reset-failed", t_all)
            cleared[name] = n
        if cleared:
            detail = "、".join(f"{k}/ {v} 个文件" for k, v in cleared.items())
            stages.append(Stage("reset", ok=True, detail=f"--overwrite 已清空 {detail}"))
            ctx.log("reset", f"--overwrite 清空 {cleared}")

    def cancel_now(next_stage: str) -> tuple[int, dict] | None:
        """阶段边界检查取消；命中就收尾（manifest 照写，`error="cancelled"`）。

        为什么只在边界检查：外部工具（GARbro/AssetStudio/KrkrExtract）正在跑的时候
        中断它，产物停在写到一半的状态，比跑完更难收拾。边界上停下来，
        上一阶段的产物是完整可续跑的（`--reuse-raw`）。
        """
        if not ctx.should_stop():
            return None
        stages.append(Stage(next_stage, ok=False,
                            detail=f"用户取消：停在 {next_stage} 之前，已完成阶段的产物保留",
                            data={"cancelled": True}))
        return _finish_failure(ctx, stages, engine, 1, "cancelled", t_all)

    # 2. extract
    extractor_name = EXTRACTORS.get(engine)
    if extractor_name is None:                                  # pragma: no cover
        st = Stage("extract", ok=False,
                   detail=f"引擎 {engine} 在 IMPLEMENTED 里但没有对应 extract 函数")
        stages.append(st)
        return _finish_failure(ctx, stages, engine, 2, "no-extractor-mapped", t_all)

    # 2. extract
    out = cancel_now("extract")
    if out is not None:
        return out
    st = _run_stage("extract", globals()[extractor_name], ctx)
    stages.append(st)
    if not st.ok:
        return _finish_failure(ctx, stages, engine, 1, "extract-failed", t_all)

    # 3. postprocess
    out = cancel_now("postprocess")
    if out is not None:
        return out
    st = _run_stage("postprocess", stage_postprocess, ctx)
    stages.append(st)
    if not st.ok:
        return _finish_failure(ctx, stages, engine, 1, "postprocess-failed", t_all)

    # 4. verify
    out = cancel_now("verify")
    if out is not None:
        return out
    st = _run_stage("verify", stage_verify, ctx)
    stages.append(st)
    if not st.ok:
        # 取消是「用户主动停」，不是「验收失败」；而「没有可验收的产物」也不是「产物坏了」。
        # 三种结局给三个 error 码，复盘时一眼能分辨（见 stage_verify 里的 reason）。
        if st.data.get("cancelled"):
            err = "cancelled"
        elif st.data.get("reason") == "no-products":
            err = "verify-no-products"
        else:
            err = "verify-failed"
        return _finish_failure(ctx, stages, engine, 1, err, t_all)

    # 5. manifest —— **一次写盘**（批次 C2）
    #
    # 旧实现写两次：先写一份还没有 ok/total_seconds 的，补完再整份重写。中间被 Ctrl+C
    # 就留下一个「没有 ok 字段」的 manifest —— 下游读到它既不能说成功也不能说失败，
    # 而这正是本文件最想避免的形态（交付记录必须能一眼判断成没成）。
    # 新顺序：先把 man 算完整（ok / error / total_seconds 全部就位）→ 写一次 →
    # 再把「manifest 阶段」补进**内存里的副本**返回。磁盘那份不含描述自己的那条 stage
    # （否则就是自我指涉：写入结果要先知道写入结果），但它自身是自洽的。
    man = build_manifest(ctx, stages, engine)
    diff = man["reconcile"]["diff"]
    rc = 0 if (diff in (0, None)) else 1
    man["ok"] = rc == 0
    if rc != 0:
        man["error"] = "reconcile-diff"

    # `--strict`（批次 C3）：这个开关此前是纯空转（argparse 收了、代码里没人读），
    # 现在给它真语义 —— 「没验」不再能混成「验过了」：
    #   · 对账没有地面真相（加密包列不出条目、引擎没索引可数）→ 交付记录里那个 0 差
    #     其实没被验证过；
    #   · 验收没执行（--no-verify，或没有可验收产物）→ 一个文件都没打开过。
    # 默认关（跑得通的常规链路要能出产物），strict 下这两种都判失败。
    if ctx.strict and rc == 0:
        if man["reconcile"].get("method") == "no-index-available":
            rc, man["error"] = 1, "strict-no-ground-truth"
        elif not man["verify"].get("verified"):
            rc, man["error"] = 1, "strict-not-verified"
        man["ok"] = rc == 0

    man["total_seconds"] = round(time.time() - t_all, 1)

    t0 = time.time()
    wrote = _write_manifest(ctx, man) is not None
    mst = Stage("manifest", ok=wrote, seconds=time.time() - t0,
                detail=(f"写入 {ctx.manifest_path}" if wrote
                        else f"写 manifest 失败: {ctx.manifest_path}"),
                data={"path": str(ctx.manifest_path)})
    stages.append(mst)
    man["stages"] = [s.as_dict() for s in stages]
    if not wrote:
        # 写不成就以内存里的结论为准降级，但**不再重试**：已经失败一次的 IO，
        # 再写一次只是赌运气；返回值把失败带给调用方才是可靠的。
        rc = 1
        man["ok"] = False
        man["error"] = man.get("error") or "manifest-write-failed"
    return rc, man


def _result_manifest(res: dict) -> dict | None:
    """从 `run()` 的返回值里取**本轮**的 manifest；取不到就是 None。

    `run()` 有两种返回形态（历史原因，别处测试与 GUI 都按这两种在用）：
      · 全链跑完 → 直接返回 manifest 本身（`rc, man = run(ctx)`）；
      · 中途失败 → 返回带 `error` / `stages` 的包装，manifest 挂在 `manifest` 键上。

    调用方统一走这里。**关键纪律**：取不到就返回 None，绝不「去看看磁盘上有没有
    manifest.json」——那正是审计 A1 里 CLI 读到上一轮旧结果的原因。
    """
    if not isinstance(res, dict):
        return None
    if "manifest_version" in res or "counts" in res:      # 已经是 manifest 本身
        return res
    man = res.get("manifest")
    return man if isinstance(man, dict) and man else None


def _launch_gui(argv: list[str]) -> int:
    """GUI 壳入口（--gui / --gui-smoke）。函数内 import：PyInstaller 静态扫描看得见，
    CLI 路径不为 Tk 多付启动成本；gui.py 里 TkinterDnD 是可选增强。"""
    import gui
    return gui.main(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # GUI 分流在 argparse 之前：--gui/--gui-smoke 显式进 GUI；**无参数（双击 exe）也进 GUI**
    # ——桌面工具的第一眼体验不该是「argparse 报缺参数」闪退（2026-11-02 用户实测踩到）。
    if "--gui" in argv or "--gui-smoke" in argv or not argv:
        return _launch_gui(argv)
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
    ap.add_argument("--overwrite", action="store_true",
                    help="输出目录已有上一轮产物时先清空 raw/ 与 png/ 再跑"
                         "（默认遇到残留直接失败，避免新旧产物混成假数字）")
    ap.add_argument("--allow-gui", action="store_true",
                    help="允许 GUI 自动化链路（加密 KiriKiri，慢）")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--verify-jobs", type=int, default=None, metavar="N",
                    help=f"verify 并发探测数（默认 {VERIFY_WORKERS}，也可用环境变量 "
                         f"GALUNPACK_VERIFY_WORKERS；1 = 完全串行，便于对比与回退）")
    ap.add_argument("--strict", action="store_true",
                    help="严格模式：对账没有地面真相（列不出索引条目）或验收未执行，"
                         "也算失败（rc=1；manifest.error = strict-no-ground-truth / "
                         "strict-not-verified）")
    ap.add_argument("--json", default=None, help="把完整结果另存一份 JSON")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    game_dir = Path(a.game_dir).resolve()
    out_dir = Path(a.out).resolve()
    if not game_dir.is_dir():
        print(f"[错误] 游戏目录不存在: {game_dir}", file=sys.stderr)
        faillog.log_failure(error="game-dir-missing", game_dir=game_dir, out_dir=out_dir,
                            rc=3, extra={"detail": "传给工具的游戏目录不存在"})
        return 3
    work_dir = Path(a.work).resolve() if a.work else out_dir / "_work"
    manifest_path = Path(a.manifest).resolve() if a.manifest else out_dir / "manifest.json"
    reuse = Path(a.reuse_raw).resolve() if a.reuse_raw else None

    ctx = Ctx(game_dir=game_dir, out_dir=out_dir, work_dir=work_dir,
              manifest_path=manifest_path, reuse_raw=reuse,
              allow_gui=a.allow_gui, do_verify=not a.no_verify, engine=a.engine,
              verify_jobs=a.verify_jobs, strict=a.strict, overwrite=a.overwrite)

    if a.dry_run:
        st = stage_detect(ctx)
        payload = {"game_dir": str(game_dir), "out": str(out_dir),
                   "detect": st.as_dict()}
        plan = None
        if st.ok:
            # dry-run 也把案例库查表带上：这正是「先看有没有现成解法」的场合
            payload["case_lookup"] = stage_case_lookup(ctx, st.data).as_dict()
            # 半自动协作的「提前告知」（2026-11-04）：KiriKiri 先探一次 GARbro 能不能
            # 列目录。列不出 → 正式跑大概率要人工介入，别让用户等 40 分钟才知道。
            # 代价是 dry-run 对 KiriKiri 样本多几秒（一次 garbro -l），值得。
            engine = st.data.get("engine")
            probe: tuple[bool, str] | None = None
            if engine == "KiriKiri":
                xp3s = _kirikiri_xp3(ctx.game_dir)
                if xp3s:
                    biggest = max(xp3s, key=lambda p: p.stat().st_size)
                    print(f"[dry-run] 探针：garbro -l {biggest.name}（几秒）", file=sys.stderr)
                    ok_list, _n, _out = tb.garbro_list(biggest)
                    probe = (ok_list, biggest.name)
                    payload["auto_feasible"] = ok_list
            plan = manual.dry_run_plan(engine, game_dir=ctx.game_dir, out_dir=ctx.out_dir,
                                       raw_dir=ctx.raw_dir, png_dir=ctx.png_dir,
                                       xp3_probe=probe, prog=_prog_name(),
                                       tools=_manual_tools())
            if plan is not None:
                payload["manual"] = plan.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if plan is not None:
            # stdout 保持纯 JSON（可能有脚本在解析），人看的区块走 stderr
            print(file=sys.stderr)
            print(manual.render_dict(payload["manual"]), file=sys.stderr)
        if not st.ok:
            faillog.log_failure(error="dry-run-detect-failed", game_dir=game_dir,
                                out_dir=out_dir, stages=[st.as_dict()], rc=3)
        return 0 if st.ok else 3

    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    for f in work_dir.glob("*.log"):
        f.unlink()

    if reuse:
        # 复用模式：把已有产物搬/链到 raw/
        if not reuse.is_dir():
            print(f"[错误] --reuse-raw 目录不存在: {reuse}", file=sys.stderr)
            faillog.log_failure(error="reuse-raw-missing", game_dir=game_dir,
                                out_dir=out_dir, rc=1,
                                extra={"reuse": reuse, "detail": "--reuse-raw 指向的目录不存在"})
            return 1
        if reuse == ctx.raw_dir:
            print(f"[reuse] 源与目标同一目录，跳过复制: {reuse}")
        else:
            # 清不掉就明确退出：copytree 往残留目录上叠会变成 raw/raw/...，
            # 那样对账数照样能自洽，属于「无声的错」。
            if not drop_tree(ctx.raw_dir):
                print(f"[错误] 清理 {ctx.raw_dir} 失败（受保护目录或安全删除守卫拦住），"
                      f"放弃复制以免产物叠层", file=sys.stderr)
                faillog.log_failure(error="reuse-raw-clean-failed", game_dir=game_dir,
                                    out_dir=out_dir, rc=1,
                                    extra={"reuse": reuse, "raw": ctx.raw_dir,
                                           "detail": "清空 raw/ 失败，放弃复制以免产物叠层"})
                return 1
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

    man = _result_manifest(res)
    if man is None:
        # 本轮没有 manifest（detect 前就失败、或写盘失败）。**不许**回退去读磁盘上的
        # manifest.json：那是上一次运行的结论，拿来当本轮结果等于伪造交付记录（审计 A1）。
        print("manifest: 本轮未产出（不读上一轮遗留的 manifest.json）")
    else:
        c = man.get("counts", {})
        raw, fin, conv = c.get("raw", {}), c.get("final", {}), c.get("converted", {})
        print(f"引擎: {man.get('engine')}")
        print(f"raw    : {raw.get('total')} 个文件 {raw.get('bytes', 0)/1048576:.1f} MB  "
              f"{raw.get('by_ext')}")
        print(f"final  : {fin.get('total')} 个文件 {fin.get('bytes', 0)/1048576:.1f} MB  "
              f"{fin.get('by_ext')}")
        print(f"converted: {conv}")
        # 没进提取阶段就不要打印「期望 None vs 落盘 0」：那句话看起来像「跑完全程、对账 0 差」，
        # 而事实是本轮一个文件都没解（rc=2 没链路 / rc=3 没判出引擎 / 预检失败 / 取消在 extract 前）。
        # 交付记录最怕的就是「看起来绿」——这里用一句话把阶段讲清楚。
        stages_of_run = res.get("stages", [])
        ext_stage = next((s for s in stages_of_run if s.get("stage") == "extract"), None)
        # 「提取跑完了」= 有 extract 阶段且它 ok（复用模式是 skipped+ok，也算跑完）
        extract_done = bool(ext_stage) and bool(ext_stage.get("ok") or ext_stage.get("skipped"))
        if extract_done or man.get("source", {}).get("archives"):
            r = man.get("reconcile", {})
            print(f"对账   : 期望 {r.get('expected')} vs 落盘 {r.get('actual')} "
                  f"(diff={r.get('diff')})")
        elif ext_stage is None:
            print("对账   : 未进入提取阶段（本轮没有产物可对账）")
        else:
            print("对账   : 提取未完成，本轮无可信的对账结果（详见上面的 FAIL 行）")
        v = man.get("verify", {})
        vstage = next((s for s in stages_of_run if s.get("stage") == "verify"), None)
        if v.get("verified"):
            # 注意：verify **有失败文件**时 verified 仍为 True（计数才是结论），
            # 这条分支照样要打印，别把它当成「没验」。
            # status 是单值枚举（manifest.verify_status 算的），有失败文件时是 partial。
            print(f"验收   : [{v.get('status')}] 图片 {v.get('image_ok')}/{v.get('image_fail')}失败、"
                  f"音频 {v.get('audio_ok')}/{v.get('audio_fail')}失败、"
                  f"视频 {v.get('video_ok')}/{v.get('video_fail')}失败、"
                  f"媒体 {v.get('media_minutes')} 分钟")
        elif vstage is None:
            print("验收   : 未执行（本轮在验收前就失败了）")
        elif vstage.get("skipped"):
            # `--no-verify` 是**唯一**会把 verify 置 skipped=True 的地方
            print("验收   : 未执行（--no-verify）")
        elif vstage.get("cancelled"):
            print(f"验收   : 已取消（已完成 {vstage.get('files_checked')} 个文件，"
                  f"未验完不算通过）")
        else:
            print("验收   : 没有可验收的产物（raw/ 与 png/ 都是空的）")
        if man.get("error"):
            print(f"失败原因: {man.get('error')}")
        print(f"manifest: {manifest_path}")
    # 人工介入方案独立成块、放在最后：失败时用户最需要的不是统计数字，而是「我现在干什么」。
    # 数据来源与 GUI/manifest 同一份（res["manual"] 或 man["manual"]），不另拼文案。
    plan = res.get("manual") or (man or {}).get("manual")
    if plan:
        print()
        print(manual.render_dict(plan))
    print(f"总耗时: {el:.1f}s   退出码: {rc}")

    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2,
                                           default=str), encoding="utf-8")
        print(f"完整结果: {a.json}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
