#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 最小壳（software-plan 阶段 3 第 3 条）：选/拖一个游戏目录 → 跑全链 → 出 manifest 报告。

**单 exe 双模式**：入口还是 `orchestrator.py`（冻结后一个 exe），`--gui` 才进本模块
（orchestrator.main 里函数内 `import gui` —— PyInstaller 静态扫描看得见函数内 import，
CLI 路径不为此多付启动成本）。不造第二个 exe：GUI 与 CLI 共用同一份 in-process 代码。

设计纪律：
  * **工作线程跑 `orch.run(ctx)`**——GUI 线程只碰 Tk，工作线程只往队列里塞；
    `root.after` 轮询队列（Tk 非线程安全，直接跨线程改控件会炸）。
  * **日志回流**：包一层 `ctx.log`（实例属性遮蔽同名方法），工作线程的日志同时进
    `_work/` 文件与 GUI 队列——两条消费路径不互相依赖。
  * **拖拽是增强不是依赖**：tkinterdnd2 可用就启用 Explorer 拖目录，不可用退化为
    「浏览 + 粘贴路径」；冻结构建按 `--collect-all tkinterdnd2` 打包（build_exe.py 探测）。
  * 纯逻辑（路径默认值、拖拽串解析、运行参数）拆成模块级函数，tests/test_gui.py 锁住；
    Tk 部分只做构造冒烟，不测交互。

用法：
  orchestrator.exe --gui          # 打开窗口
  orchestrator.exe --gui-smoke    # 构建窗口 600ms 后自毁（冻结包验证 Tk 可用，内部用）
"""
from __future__ import annotations

import contextlib
import math
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import faillog                    # 失败日志：无依赖，可安全在模块级导入（也便于测试替换）

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:                                        # noqa: BLE001
    HAS_DND = False

#: 应用根（冻结态 = exe 所在目录）。只在需要「相对程序自己的路径」时用；
#: 产物目录**不**基于它 —— 见 `default_out_dir`。
FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent


def app_version() -> str:
    """版本号：取 `version.py`（唯一出处）。取不到也不该影响界面启动。"""
    try:
        from version import APP_VERSION
        return str(APP_VERSION)
    except Exception:                                        # noqa: BLE001
        return "未知"


def ensure_writable(path: Path) -> str | None:
    """目录能不能写：None = 可以，否则返回原因（给弹窗用）。

    探针用**正常的文件名和扩展名**（`write-probe.txt`）。早前用的是点开头的无扩展名
    文件（`.galunpack-write-test`），那正是终端防护最容易判成「可疑行为」的形状 ——
    结果所有目录都被判成不可写，用户「浏览哪个位置都没用」。
    探针本身被拦时也可能误报，所以调用方必须允许「仍然尝试」（见 `_start`）。
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / "write-probe.txt"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def fallback_out_dirs(app_root: Path | None = None) -> list[Path]:
    """默认输出目录写不进去时，按顺序自动试的位置。

    **口径改过（2026-11-06）**：早前一律弹框让用户自己挑，理由是「自动跳到程序目录
    用户找不到」。实测推翻了这个假设 —— 用户机器上**除程序自身目录外，桌面、文档、
    游戏目录全被拦**（见 `antivirus-false-positives.md` §8），让用户挑等于让他反复撞墙。
    程序目录是他自己解压/构建出来的位置，产物落在 `<程序目录>\\output` 既找得到，
    删程序时也一起删干净。

    顺序：程序目录 → LOCALAPPDATA → 临时目录。第一个可写就用它，**不再中断运行**。
    """
    root = Path(app_root) if app_root else APP_ROOT
    cands = [root / "output"]
    for env in ("LOCALAPPDATA", "TEMP", "TMP"):
        base = os.environ.get(env)
        if base:
            cands.append(Path(base) / "GalgameUnpacker" / "output")
    uniq: list[Path] = []
    seen: set[str] = set()
    for c in cands:
        key = str(c).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def pick_writable(cands: list[Path]) -> tuple[Path | None, list[tuple[Path, str | None]]]:
    """依次试，返回（第一个可写的；没有则 None，以及每个候选的探测结果）。

    探测结果要给用户看：一张「哪能写、哪不能写、报什么错」的表，比「请换个目录」
    有用得多 —— 它同时也是 `--doctor` 报告里最关键的那一段。
    """
    table: list[tuple[Path, str | None]] = []
    for c in cands:
        why = ensure_writable(c)
        table.append((c, why))
        if why is None:
            return c, table
    return None, table


def restricted_environment() -> str | None:
    """当前进程是否被降权运行（Low/Untrusted）。是则返回一句人话原因，否则 None。

    为什么要在**启动时**就查（2026-11-06 实测）：把程序放在 `D:\\K\\…\\packaging\\Output`
    这类目录下，进程会被系统以 **Low 完整性**创建；而 Low 令牌被 Windows 强制
    「禁止向上写」，桌面/文档/游戏目录/%TEMP% 全部 `WinError 5`，程序只能缩在
    「自己的 output」里干活 —— 界面上却一切正常，产物默默换了地方，用户毫不知情。
    这条提示把「事后翻自检报告」提前到「一打开就知道」。

    只读、不阻断：降级路径本身已经能跑，这里只是把原因说清楚。
    """
    try:
        import doctor                      # 函数内 import：Tk 启动不为它多付成本
        level = doctor.integrity_level()
    except Exception:                                        # noqa: BLE001
        return None
    if level.startswith(("Low", "Untrusted")):
        return f"进程完整性级别为 {level}"
    return None


def restricted_tip() -> str:
    """降权时的完整建议（状态栏放不下，日志区/自检弹窗用）。"""
    return (
        "检测到程序被以「低权限」运行：只能写入它自己的目录，"
        "桌面 / 文档 / 游戏目录 / 临时目录都写不进去。\n"
        "常见原因是程序放在受管控或带特殊权限的目录里"
        "（例如仓库的 packaging\\Output 下面）。\n"
        "建议：把整个 orchestrator 文件夹移到 D:\\GalgameUnpacker 之类的普通目录后重开，"
        "产物就能直接落到 <游戏目录>\\output。\n"
        "要证据：点「环境自检」，里面每一项都带完整错误码。"
    )


#: Windows 文件名非法字符。`【PC】… | Ore o Hoshigaru…` 这种目录名在 NTFS 里**能存在**
#: （从压缩包/别的系统带来的），但**不能在里面创建子目录**：`CreateDirectory` 直接报
#: 「文件名、目录名或卷标语法不正确」（2026-11-04 实测）。
_ILLEGAL = set('<>:"/\\|?*') | {chr(i) for i in range(32)}


def _legal_component(name: str) -> str:
    """把目录名清洗成能在 Windows 上安全当目录名的字符串。"""
    cleaned = "".join("_" if ch in _ILLEGAL else ch for ch in name).strip(" .")
    return cleaned or "game"


def default_out_dir(game_dir: Path) -> Path:
    """产物默认落 **`<游戏目录>/output`**（2026-11-04 用户要求）。

    但如果游戏目录名里有 Windows 非法字符（`|` `?` `*` 等），就没法在里面建子目录 ——
    这时退到**父目录**下一个清洗过名字的目录，形如 `<父目录>/【PC】…_…-output`。
    父目录名通常合法（它是由资源管理器正常创建的）。

    游戏目录不可写（只读安装、光盘、受保护目录、被终端防护拦）时由 `_start` 接管：
    先按 `fallback_out_dirs()` 依次试可写位置，**试到就继续跑**（2026-11-06 起）；
    全都不可写才弹窗 —— 那时说明是进程级拦截，换目录没用，让用户跑「环境自检」。
    """
    name = game_dir.name
    if any(ch in _ILLEGAL for ch in name):
        return game_dir.parent / f"{_legal_component(name)}-output"
    return game_dir / "output"


def has_stale_products(out_dir: Path) -> bool:
    """输出目录里是否已有上一轮产物（判据与 orchestrator 的 preflight 一致：数文件）。

    有残留就必须问用户：静默叠跑的产物数照样能自洽，但数字是假的。
    """
    for sub in ("raw", "png"):
        d = out_dir / sub
        if d.is_dir() and any(p.is_file() for p in d.rglob("*")):
            return True
    return False


def normalize_dropped(raw: str) -> list[Path]:
    """tkdnd 的文件列表解析：**括号感知**切分——带空格的路径被 `{...}` 包住，
    花括号里的空格不算分隔符。例：`{D:\\My Game} D:\\other` → 两个路径。"""
    out: list[Path] = []
    token = ""
    in_brace = False
    for ch in raw.strip():
        if ch == "{":
            in_brace = True
            token = ""
        elif ch == "}":
            in_brace = False
            if token:
                out.append(Path(token))
                token = ""
        elif ch.isspace() and not in_brace:
            if token:
                out.append(Path(token))
                token = ""
        else:
            token += ch
    if token:
        out.append(Path(token))
    return out


def pick_game_dir(raw: str) -> Path | None:
    """从拖拽串/手输串里取第一个**存在的目录**；不存在的（比如拖了文件）返回 None。"""
    for p in normalize_dropped(raw):
        if p.is_dir():
            return p
    return None


def should_confirm_close(running: bool) -> bool:
    """关窗时要不要先弹确认：**只在运行中**才问。

    为什么问：工作线程是 daemon，直接 destroy 会把解包掐死在写文件的中间
    （留下几 GB 半截 raw，且没有 manifest 说明它是什么）。运行中关窗的正确动作是
    「置取消位 → 等当前阶段边界停下 → manifest 落盘 → 再关」，用户点确定只是在授权
    这个流程，不是立刻杀进程。空闲时关窗当然不该多问一句（那只是烦人）。
    """
    return bool(running)


def summarize_text(rc: int, man: dict) -> str | None:
    """把一轮结果拼成「交付了多少 / 对账有没有差 / 验收结果」的人话摘要。

    抽成模块级纯函数的原因（批次 C 收口，2026-11-03）：摘要里任何一个数字格式化
    抛异常，都会顺着 `_poll` 把 Tk 轮询器打死——表现为摘要不弹、日志不再滚动、
    再点「开始」跑完了也永远看不到结果，只能重启程序。实测触发点：
    `verify.media_minutes` 在「没验成」的结局里是 **null**（key 存在、值为 None），
    `f"{ver.get('media_minutes', 0):.1f}"` 的默认值 0 对 None 不生效 → TypeError。
    所以这里必须显式区分「验过（有分钟数）」和「没验成（未统计）」，
    **数据侧保持 null 不动**：null = 没测过，0.0 = 测过、是 0，两者不能混。

    `man` 可能是 run() 的**包装 dict**（失败形态 `{error, stages, manifest}`），
    先过 `orch._result_manifest` 取本轮 manifest；取不到就返回 None，
    由调用方（`_summarize`）决定「本轮失败」怎么展示。
    """
    import orchestrator as orch

    real = orch._result_manifest(man or {})
    if real is None:
        return None
    man = real
    counts = man.get("counts") or {}
    final = counts.get("final") or {}
    rec = man.get("reconcile") or {}
    ver = man.get("verify") or {}
    lines = [
        f"引擎：{man.get('engine')}    退出码：{rc}",
        f"交付（final）：{final.get('total', '?')} 个文件",
    ]
    if man.get("error"):
        # 失败原因排在对账/验收之前：用户第一眼要知道「为什么红」
        why = {"cancelled": "用户取消"}.get(man.get("error"), man.get("error"))
        lines.append(f"失败原因：{why}（详见日志与 manifest 的 stages）")
    org = man.get("organize") or {}
    if org:
        # 归档是附加产物：用户最想知道「三类各多少、在哪」，一句话带过
        kinds = "、".join(f"{k} {v}" for k, v in (org.get("kinds") or {}).items() if v)
        lines.append(f"分类：{kinds}（视图 {Path(str(org.get('view', ''))).name}/，"
                     f"硬链接 {org.get('linked', '?')} 个，失败 {org.get('failed', 0)}）")
    if rec.get("method") != "no-index-available" and rec.get("diff") is not None:
        lines.append(f"对账：索引 {rec.get('expected')} vs 落盘 {rec.get('actual')} "
                     f"（diff={rec.get('diff')}）")
    else:
        lines.append("对账：无索引地面真相，未对账")
    # media_minutes 为 None（没验成）时显示「未统计」而不是 0.0：
    # 0.0 分钟会被读成「验了、真的 0 分钟」，与「没验」是两种事实。
    minutes = ver.get("media_minutes")
    media = (f"{minutes:.1f} 分钟" if isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
             else "媒体未统计")
    lines.append(f"验收[{ver.get('status') or 'unknown'}]："
                 f"图片 {ver.get('image_ok')}/{ver.get('image_fail')}失败 · "
                 f"音频 {ver.get('audio_ok')}/{ver.get('audio_fail')}失败 · "
                 f"视频 {ver.get('video_ok')}/{ver.get('video_fail')}失败 · {media}")
    if ver.get("nonmedia"):
        # 「没验」也是信息：非媒体文件不计失败，但要让用户知道有多少没看
        lines.append(f"另有 {ver.get('nonmedia')} 个非媒体文件未验收"
                     f"（按扩展名见 manifest.verify.nonmedia_by_ext）")
    # 人工介入方案放最后：失败时用户最需要的是「我现在干什么」，不是统计数字。
    # 只显示前 3 步 —— 弹窗再长就没人读了，完整步骤在日志与 manifest.manual 里。
    plan = man.get("manual") or {}
    if plan:
        steps = plan.get("steps") or []
        lines.append("")
        lines.append(f"需要人工介入：{plan.get('summary', '')}")
        for i, s in enumerate(steps[:3], 1):
            lines.append(f"  {i}) {s}")
        if len(steps) > 3:
            lines.append(f"  …还有 {len(steps) - 3} 步，完整步骤看日志 / manifest 的 manual 块")
        if plan.get("then"):
            lines.append(f"做完后：{plan['then']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 外观（design tokens）
#
# 设计口径（2026-11-06 改版，参考 Linear / Vercel Dashboard / GitHub Desktop / HandBrake）：
#   1. **用留白和 1px 发丝线分区**，不用 3D 凸起按钮、不用凹陷状态栏 —— 那两样是
#      Windows 7 时代的视觉语言，会让界面看着比实际功能旧十年。
#   2. **天空蓝只做点缀**：全窗口只有三处出现 —— 主按钮、输入框聚焦环、状态点。
#      面积占比 < 3%，其余全是冷中性灰（#F5F7FA 背景 / 纯白卡片 / 灰阶文字）。
#      大面积铺蓝会让工具类软件显得「玩具感」，也压掉日志的可读性。
#   3. **层级靠字号与字色**，不靠加粗和边框：标题 #0F172A、正文 #475569、辅助 #94A3B8。
#   4. 圆角 12（卡片）/ 9（按钮），间距 24/16/10 三档，视觉节奏统一。
class UI:
    BG = "#F5F7FA"          # 页面底色：微冷中性灰，不偏蓝
    CARD = "#FFFFFF"
    LINE = "#E5EAF1"        # 卡片描边
    LINE_SOFT = "#EEF2F7"   # 卡片内分隔线
    TEXT = "#0F172A"
    TEXT_2 = "#475569"
    TEXT_3 = "#94A3B8"
    SKY = "#0EA5E9"         # 点缀色（sky-500）
    SKY_D = "#0284C7"       # hover
    SKY_L = "#E0F2FE"       # 选中/浅底
    OK = "#10B981"
    WARN = "#F59E0B"
    ERR = "#EF4444"
    DOT_IDLE = "#CBD5E1"

    FONT = "Microsoft YaHei UI"
    F_TITLE = (FONT, 13, "bold")
    F_BOLD = (FONT, 10, "bold")
    F_BODY = (FONT, 10)
    F_LABEL = (FONT, 9)
    F_SMALL = (FONT, 8)
    F_MONO = ("Consolas", 9)


#: 按钮三态色板：常态 / hover / 禁用。（主按钮是唯一实心色块）
_BTN_STYLE = {
    "primary": dict(bg=UI.SKY, bd=UI.SKY, fg="#FFFFFF",
                    hbg=UI.SKY_D, hbd=UI.SKY_D,
                    dbg="#E2E8F0", dbd="#E2E8F0", dfg="#94A3B8"),
    "secondary": dict(bg=UI.CARD, bd=UI.LINE, fg=UI.TEXT_2,
                      hbg="#F1F5F9", hbd="#CBD5E1",
                      dbg="#FBFCFE", dbd="#EDF1F6", dfg="#A6B1C2"),
    "ghost": dict(bg=None, bd=None, fg=UI.TEXT_3,
                  hbg="#EDF2F7", hbd="#EDF2F7",
                  dbg=None, dbd=None, dfg="#94A3B8"),
}


def _round_pts(x1: float, y1: float, x2: float, y2: float, r: float,
               n: int = 8) -> list[float]:
    """圆角矩形的顶点（每角 n 段圆弧）。

    **不用 `smooth=True`**：Tk 的平滑是对顶点做样条近似，圆角处会生成疏密不均的
    短线段，浅色 1px 边框在截图里直接断成虚线（2026-11-06 实测）。显式算圆弧点，
    边缘连续、半径也准；`create_line` 加 `dash` 时还能画出**真正的虚线圆角**。
    """
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts: list[float] = []
    for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                       (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return pts


def _poly(cv: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
          r: float, color: str, tags=()) -> int:
    return cv.create_polygon(_round_pts(x1, y1, x2, y2, r), smooth=False,
                             fill=color, outline="", tags=tags)


def _round_rect(cv: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                r: float, fill: str, outline: str | None = None,
                width: float = 1, tags=()) -> None:
    """圆角矩形 —— **用两层填充多边形画边框，不用 outline 描边**。

    为什么（2026-11-06 实测）：`smooth=True` 的多边形本质是一串短线段，
    给它加 `outline` 时圆角处会断成虚线（放大看是虚线弧），浅色描边尤其明显。
    改成「先填边框色、再内缩 fill 色填一层」，边缘连续，颜色也准。
    """
    if outline:
        _poly(cv, x1, y1, x2, y2, r, outline, tags)
        _poly(cv, x1 + width, y1 + width, x2 - width, y2 - width,
              max(1, r - width), fill, tags)
    else:
        _poly(cv, x1, y1, x2, y2, r, fill, tags)


class Card(tk.Frame):
    """白卡片：Canvas 只当**背景层**（place 铺满），内容用 pack 放 normal Frame。

    踩过的坑（第一版）：把 body 塞进 canvas 的 `create_window` 并让它撑满 → 卡片的
    高度被 canvas 的默认高（≈276px）锁死，内容只有 100px 高却在下面留一大片空白。
    现在 body 走 pack，卡片高度由内容决定；canvas 用 place 跟随，纯做圆角背景。
    """

    def __init__(self, parent: tk.Misc, pad: int = 18, radius: int = 12,
                 bg: str = UI.BG, fill: str = UI.CARD) -> None:
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self._fill, self._r = fill, radius
        self.cv = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.cv.bind("<Configure>", self._resize)

    def _resize(self, event) -> None:                             # noqa: ANN001
        self.cv.delete("card")
        _round_rect(self.cv, 0.5, 0.5, event.width - 0.5, event.height - 0.5,
                    self._r, fill=self._fill, outline=UI.LINE, width=1, tags="card")
        self.cv.tag_lower("card")


class PillButton(tk.Canvas):
    """圆角按钮，接口刻意兼容 ttk：`.configure(state=...)` / `.configure(text=...)`。

    为什么不用 ttk.Button：ttk 在 Windows 上画的仍是系统主题的三维边框，
    换成 clam 也只是变平、做不出圆角和 hover 变色；主按钮要「一个实心色块」的质感，
    只能自己画。代价是要自己实现 state/text/hover，且必须兼容既有调用点
    （`_start` / `_poll` 里都是 `btn.configure(state="disabled")`）。
    """

    def __init__(self, parent: tk.Misc, text: str, command=None, kind: str = "secondary",
                 bg: str = UI.CARD, height: int = 34, padx: int = 16, radius: int = 9,
                 font=None, state: str = "normal") -> None:
        self._kind, self._bg, self._h, self._padx, self._r = kind, bg, height, padx, radius
        self._font = font or UI.F_BODY
        self._text, self._cmd, self._state = text, command, state
        self._hover = False
        width = tkfont.Font(font=self._font).measure(text) + padx * 2
        super().__init__(parent, width=width, height=height, bg=bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    # -- 状态色 --
    def _colors(self) -> tuple[str, str, str]:
        st = dict(_BTN_STYLE[self._kind])
        if st["bg"] is None:                       # ghost：底色跟随父容器
            st["bg"] = st["dbg"] = self._bg
            st["bd"] = st["dbd"] = self._bg
        if self._state == "disabled":
            return st["dbg"], st["dbd"], st["dfg"]
        if self._hover:
            return st["hbg"], st["hbd"], st["fg"]
        return st["bg"], st["bd"], st["fg"]

    def _draw(self) -> None:
        self.delete("all")
        w = int(self.winfo_width() or self.winfo_reqwidth())
        h = int(self.winfo_height() or self._h)
        fill, border, fg = self._colors()
        _round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, self._r,
                    fill=fill, outline=border, width=1)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

    # -- 事件 --
    def _on_enter(self, _e=None) -> None:
        if self._state != "disabled":
            self._hover = True
            self._draw()

    def _on_leave(self, _e=None) -> None:
        self._hover = False
        self._draw()

    def _on_press(self, _e=None) -> None:
        if self._state != "disabled":
            self.move("all", 0, 1)                 # 1px 下沉，给一点物理反馈

    def _on_release(self, e=None) -> None:                       # noqa: ANN001
        if self._state == "disabled":
            return
        self._hover = True
        self._draw()
        inside = 0 <= getattr(e, "x", 0) <= self.winfo_width() and \
            0 <= getattr(e, "y", 0) <= self.winfo_height()
        if inside and self._cmd:
            self._cmd()

    # -- 兼容 ttk 接口 --
    def configure(self, cnf=None, **kw):                          # noqa: ANN001
        for key in ("state", "text", "command"):
            if key in kw:
                val = kw.pop(key)
                if key == "state":
                    self._state = val
                    self.configure_cursor()
                elif key == "text":
                    self._text = val
                else:
                    self._cmd = val
        if kw or cnf:
            super().configure(cnf, **kw)
        self._draw()
        return None

    config = configure

    def configure_cursor(self) -> None:
        with contextlib.suppress(tk.TclError):
            self.configure(cursor="hand2" if self._state != "disabled" else "arrow")

    def cget(self, key: str):
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        return super().cget(key)


#: 阶段 → 进度位置。粗粒度**故意的**：用户要的是「在动、大概到哪」，
#: 不是精确百分比 —— 各阶段耗时差几十倍（extract 几分钟、manifest 几十毫秒），
#: 按真实耗时换算反而会让进度条长时间卡住不动。
_STAGE_FRACTION = {
    "detect": 0.08, "case-lookup": 0.13, "preflight": 0.17,
    "extract": 0.55, "postprocess": 0.78, "verify": 0.93,
    "organize": 0.97, "manifest": 1.0,
}


class RoundedEntry(tk.Canvas):
    """圆角输入框：Canvas 画 8px 圆角边框，真实 Entry 内嵌并居中。

    为什么不用 tk.Entry 直接加边框：Entry 的 relief 只有 sunken/ridge 这些三维档，
    没有「1px 发丝线 + 圆角」这一档，和圆角卡片放一起会明显不搭。
    `.ent` 才是真正接收键盘的 Entry（绑定 Return / 拖拽都挂在它身上）。
    """

    def __init__(self, parent: tk.Misc, textvariable: tk.StringVar, bg: str = UI.CARD,
                 height: int = 38, radius: int = 8, font=None) -> None:
        super().__init__(parent, height=height, bg=bg, bd=0, highlightthickness=0)
        self._r, self._focused, self._drag = radius, False, False
        self.ent = tk.Entry(self, textvariable=textvariable, bd=0, relief="flat",
                            bg=UI.CARD, fg=UI.TEXT, font=font or UI.F_BODY,
                            highlightthickness=0, insertbackground=UI.SKY)
        self._win = self.create_window(12, height / 2, window=self.ent, anchor="w")
        self.bind("<Configure>", lambda e: self._redraw(e.width, e.height))
        self.bind("<Button-1>", lambda _e: self.ent.focus_set())
        self.ent.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.ent.bind("<FocusOut>", lambda _e: self._set_focus(False))

    def _set_focus(self, on: bool) -> None:
        self._focused = on
        self._redraw()

    def set_highlight(self, on: bool) -> None:
        """拖拽悬停时的「放这儿」提示：浅蓝底 + 天空蓝虚线描边。

        为什么用虚线：实线会跟「聚焦态」撞车 —— 聚焦也是天空蓝 1px 实线，
        用户分不清「我点的」还是「可以放」。虚线是拖拽语义里最通用的约定。
        """
        if self._drag == on:
            return
        self._drag = on
        with contextlib.suppress(tk.TclError):
            self.ent.configure(bg="#F7FCFF" if on else UI.CARD)
        self._redraw()

    def _redraw(self, w: int | None = None, h: int | None = None) -> None:
        w = max(1, w if w is not None else self.winfo_width())
        h = max(1, h if h is not None else self.winfo_height())
        if w <= 2 or h <= 2:
            return
        self.delete("bd")
        if self._drag:
            _poly(self, 0.5, 0.5, w - 0.5, h - 0.5, self._r, "#F7FCFF", tags="bd")
            pts = _round_pts(1.5, 1.5, w - 1.5, h - 1.5, self._r)
            self.create_line(pts + [pts[0], pts[1]], fill=UI.SKY, width=2,
                             dash=(5, 4), capstyle="round", joinstyle="round",
                             tags="bd")
        else:
            _round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, self._r, fill=UI.CARD,
                        outline=UI.SKY if self._focused else UI.LINE, width=1,
                        tags="bd")
        self.tag_lower("bd")
        self.coords(self._win, 12, h / 2)
        self.itemconfigure(self._win, width=max(1, w - 24), height=max(1, h - 16))


class Check(tk.Canvas):
    """自绘勾选框：15px 圆角方框，选中时天空蓝填充 + 白勾。

    原生 tk.Checkbutton 在 Windows 上是系统控件，勾选态是深色边框的黑勾，
    和「浅灰卡片 + 单一强调色」的语汇不搭；自绘之后它成了点缀色的第三处露面。
    """

    def __init__(self, parent: tk.Misc, text: str, variable: tk.BooleanVar,
                 bg: str = UI.CARD, size: int = 15, font=None) -> None:
        self._size, self._text, self._font = size, text, font or UI.F_LABEL
        self.var = variable
        width = tkfont.Font(font=self._font).measure(text) + size + 9
        super().__init__(parent, width=width, height=22, bg=bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e=None) -> None:
        self.var.set(not self.var.get())

    def _draw(self) -> None:
        self.delete("all")
        s = self._size
        y1 = (22 - s) / 2
        on = bool(self.var.get())
        _round_rect(self, 0.5, y1 + 0.5, s + 0.5, y1 + s + 0.5, 4,
                    fill=UI.SKY if on else UI.CARD,
                    outline=UI.SKY if on else "#CBD5E1", width=1)
        if on:   # 白勾：两段折线，圆头圆角，比文字符号「✓」清晰
            self.create_line(3.5, y1 + s / 2, s / 2 - 0.5, y1 + s - 4.5,
                             s - 3, y1 + 4.5, fill="#FFFFFF", width=2,
                             capstyle="round", joinstyle="round")
        self.create_text(s + 9, 11, text=self._text, anchor="w",
                         fill=UI.TEXT_2, font=self._font)


class App:
    """主窗口。`poll()` 只在主线程跑（root.after 驱动），worker 只往 self.q 塞。"""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.running = False
        root.title("Galgame Unpacker")
        root.configure(bg=UI.BG)
        root.minsize(760, 560)
        with contextlib.suppress(tk.TclError):
            root.geometry("960x700")
        self._init_style()

        # ---- 品牌栏：靠留白分层，不加边框（Linear / Vercel 的做法）----
        outer = tk.Frame(root, bg=UI.BG)
        outer.pack(fill="both", expand=True, padx=24, pady=(18, 18))
        head = tk.Frame(outer, bg=UI.BG)
        head.pack(fill="x", pady=(0, 14))
        brand = tk.Frame(head, bg=UI.BG)
        brand.pack(side="left")
        tk.Label(brand, text="Galgame Unpacker", bg=UI.BG, fg=UI.TEXT,
                 font=UI.F_TITLE).pack(anchor="w")
        tk.Label(brand, text=f"解包 · 验收 · 归类      v{app_version()}", bg=UI.BG,
                 fg=UI.TEXT_3, font=UI.F_SMALL).pack(anchor="w", pady=(3, 0))
        PillButton(head, "环境自检", command=self._doctor, kind="ghost",
                   bg=UI.BG, height=30).pack(side="right")

        # ---- 输入卡片 ----
        card = Card(outer)
        card.pack(fill="x")
        body = card.body
        body.columnconfigure(1, weight=1)
        self.var_game = tk.StringVar()
        self.ent_game = self._field(body, 0, "游戏目录", self.var_game, self._browse_game)
        self.ent_game.ent.bind("<Return>", lambda _e: self._autofill_out())
        self.var_out = tk.StringVar()
        self.ent_out = self._field(body, 1, "输出目录", self.var_out, self._browse_out)

        bar = tk.Frame(body, bg=UI.CARD)
        bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        self.var_gui = tk.BooleanVar(value=False)
        self.var_organize = tk.BooleanVar(value=True)
        # 用 tk.Checkbutton 而不是 ttk：clam 主题把选中态画成「方框加叉」，像禁用符号；
        # 原生勾选框虽朴素，但语义一眼可辨（勾 = 开）。
        for text, var in (("用于加密的 krkr", self.var_gui),
                          ("按类型整理", self.var_organize)):
            Check(bar, text, var).pack(side="left", padx=(0, 18))
        # 主操作只有一个实心色块 —— 天空蓝在全窗口的露面都集中在这里
        self.btn_run = PillButton(bar, "开始解包", command=self._start, kind="primary",
                                  bg=UI.CARD, height=38, padx=24, font=UI.F_BOLD)
        self.btn_run.pack(side="right")
        self.btn_open = PillButton(bar, "打开输出目录", command=self._open_out,
                                   kind="secondary", bg=UI.CARD, state="disabled")
        self.btn_open.pack(side="right", padx=(0, 8))
        self.btn_cancel = PillButton(bar, "取消", command=self._cancel,
                                     kind="secondary", bg=UI.CARD, state="disabled")
        self.btn_cancel.pack(side="right", padx=(0, 8))

        # ---- 日志卡片 ----
        logcard = Card(outer)
        logcard.pack(fill="both", expand=True, pady=(14, 0))
        lb = logcard.body
        top = tk.Frame(lb, bg=UI.CARD)
        top.pack(fill="x")
        tk.Label(top, text="运行日志", bg=UI.CARD, fg=UI.TEXT_2,
                 font=(UI.FONT, 9, "bold")).pack(side="left")
        self._dot = tk.Canvas(top, width=8, height=8, bg=UI.CARD,
                              highlightthickness=0, bd=0)
        self._dot.pack(side="right", padx=(7, 2))
        self._dot_id = self._dot.create_oval(1, 1, 7, 7, fill=UI.DOT_IDLE, outline="")
        self.var_status = tk.StringVar(value="就绪")
        tk.Label(top, textvariable=self.var_status, bg=UI.CARD, fg=UI.TEXT_3,
                 font=UI.F_SMALL, anchor="e").pack(side="right")
        self.var_status.trace_add("write", lambda *_: self._sync_dot())
        self._divider = tk.Frame(lb, bg=UI.LINE_SOFT, height=1)
        self._divider.pack(fill="x", pady=(12, 0))

        # 进度线：4px 细条，默认不占位；运行时插在分隔线下面，跑到 100% 再收起。
        # 为什么不做成进度条控件：这里只有「在动/大概到哪」这一个语义，
        # 用 stage 事件驱动一条线足够，不必引进度框架或百分比数字。
        self._prog_f = self._prog_target = 0.0
        self._prog_job = None
        self._prog = tk.Canvas(lb, height=4, bg=UI.CARD, bd=0, highlightthickness=0)
        self._prog.bind("<Configure>", lambda _e: self._draw_progress())

        self._logbox = tk.Frame(lb, bg=UI.CARD)
        box = self._logbox
        box.pack(fill="both", expand=True, pady=(12, 0))
        self.txt = tk.Text(box, height=10, wrap="none", state="disabled",
                           font=UI.F_MONO, bg=UI.CARD, fg=UI.TEXT_2, bd=0,
                           highlightthickness=0, padx=0, pady=0,
                           spacing1=2, spacing3=3, insertbackground=UI.SKY,
                           selectbackground=UI.SKY_L, selectforeground=UI.TEXT)
        self.txt.pack(side="left", fill="both", expand=True)
        self._sb = ttk.Scrollbar(box, command=self.txt.yview,
                                 style="Card.Vertical.TScrollbar")
        self._sb.pack(side="right", fill="y", padx=(10, 0))
        # 内容不满一屏时把滚动条收起来：常驻一根空槽是「网页 2003」的做法
        self.txt.configure(yscrollcommand=self._on_scroll)
        self.txt.tag_configure("hint", foreground=UI.TEXT_3)
        self._hint()

        # 拖拽看 **root 能力** 不看模块 import：普通 tk.Tk() 根没有 drop_target_register，
        # 只有 TkinterDnD.Tk() 根有（tests 里的冒烟用的就是普通根）
        if hasattr(root, "drop_target_register"):
            for w in (root, self.ent_game):
                w.drop_target_register(DND_FILES)           # type: ignore[attr-defined]
                w.dnd_bind("<<Drop>>", self._on_drop)        # type: ignore[attr-defined]
            # 拖拽悬停：整个窗口都是投放区，但「放哪儿」要靠输入框自己说
            root.dnd_bind("<<DropEnter>>",                      # type: ignore[attr-defined]
                          lambda _e: self._drag_over(True))
            root.dnd_bind("<<DropLeave>>",                      # type: ignore[attr-defined]
                          lambda _e: self._drag_over(False))
        if not hasattr(root, "drop_target_register") and not HAS_DND:
            self.var_status.set("就绪（未装 tkinterdnd2，拖拽不可用：浏览或粘贴路径）")

        self._last_out: Path | None = None
        #: 取消位（每次运行换一个新的 Event；传给 run 的是 is_set 而不是 Event 本身，
        #: 免得编排层为了「读一个标志」依赖 threading）
        self._cancel_ev = threading.Event()
        self._close_when_done = False        # 关窗时点了「确定」→ 跑完再 destroy
        self._crashed = False                # 工作线程挂了（状态条别被后续 done 覆盖）

        # 启动守卫：被降权时先把话说清楚（不阻断，降级路径仍能跑）。
        warn = restricted_environment()
        if warn:
            self.var_status.set("受限环境：只能写入程序目录（建议整体移到 D:\\GalgameUnpacker）")
            self._log(f"[warn] {warn}")
            for line in restricted_tip().splitlines():
                self._log(f"[warn] {line}")

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll)

    # ---- 外观辅助 ----

    def _init_style(self) -> None:
        """把 ttk 拉平成卡片配色（clam 是唯一能改背景/边框的内置主题）。"""
        st = ttk.Style(self.root)
        with contextlib.suppress(tk.TclError):
            st.theme_use("clam")
        st.configure("Card.TCheckbutton", background=UI.CARD, foreground=UI.TEXT_2,
                     focuscolor=UI.CARD, font=UI.F_LABEL, padding=0, borderwidth=0)
        st.map("Card.TCheckbutton", background=[("active", UI.CARD)],
               indicatorcolor=[("selected", UI.SKY), ("!selected", UI.CARD)])
        st.configure("Card.Vertical.TScrollbar", background="#DCE3EC",
                     troughcolor=UI.CARD, bordercolor=UI.CARD, arrowcolor=UI.CARD,
                     relief="flat", borderwidth=0, arrowsize=1, width=8)
        st.map("Card.Vertical.TScrollbar", background=[("active", "#C3CDDA")])
        # 去掉两端的箭头：现代滚动条是「一根细条」，箭头是 90 年代的记忆
        with contextlib.suppress(tk.TclError):
            st.layout("Card.Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])

    def _field(self, parent: tk.Misc, row: int, label: str, var: tk.StringVar,
               browse_cmd) -> "RoundedEntry":                          # noqa: ANN001
        """一行表单：小标签 + 圆角输入框 + 次级按钮。"""
        tk.Label(parent, text=label, bg=UI.CARD, fg=UI.TEXT_3, font=UI.F_LABEL,
                 width=7, anchor="w").grid(row=row, column=0, sticky="w",
                                           pady=(0 if row == 0 else 12, 0))
        ent = RoundedEntry(parent, var, bg=UI.CARD)
        ent.grid(row=row, column=1, sticky="ew", padx=(10, 10),
                 pady=(0 if row == 0 else 12, 0))
        PillButton(parent, "浏览", command=browse_cmd, kind="secondary",
                   bg=UI.CARD, height=34).grid(row=row, column=2, sticky="e",
                                               pady=(0 if row == 0 else 12, 0))
        return ent

    def _hint(self) -> None:
        """空状态提示：日志区一打开不该是一片白。"""
        self.txt.configure(state="normal")
        self.txt.insert("end", "把游戏文件夹拖进窗口，或点「浏览」选择目录。\n"
                               "解包产物默认落在 <游戏目录>\\output。\n", "hint")
        self.txt.configure(state="disabled")

    def _on_scroll(self, first: str, last: str) -> None:
        """滚动条：**内容装得下就隐藏**，装不下才出现。"""
        self._sb.set(first, last)
        fits = float(first) <= 0.0 and float(last) >= 1.0
        if fits and self._sb.winfo_ismapped():
            self._sb.pack_forget()
        elif not fits and not self._sb.winfo_ismapped():
            self._sb.pack(side="right", fill="y", padx=(10, 0))

    # ---- 进度线 / 拖拽悬停 ----

    def _drag_over(self, on: bool) -> None:
        """拖拽悬停：输入框转虚线高亮，状态条给一句「松开即导入」。"""
        self.ent_game.set_highlight(on)
        if self.running:
            return
        self.var_status.set("松开鼠标 → 用这个目录开始" if on else "就绪")

    def _prog_ready(self) -> bool:
        """进度线存在才画：只造了部分属性的测试替身不该被装饰性代码搞崩。"""
        return getattr(self, "_prog", None) is not None and hasattr(self, "_prog_job")

    def _draw_progress(self) -> None:
        if not self._prog_ready():
            return
        cv = self._prog
        cv.delete("all")
        w = cv.winfo_width()
        if w <= 4:
            return
        y = 2.5
        cv.create_line(2, y, w - 2, y, fill=UI.LINE_SOFT, width=3, capstyle="round")
        if self._prog_f <= 0:
            return
        x = 2 + max(0.0, min(1.0, self._prog_f)) * (w - 4)
        cv.create_line(2, y, max(3.0, x), y, fill=UI.SKY, width=3, capstyle="round")

    def _progress_show(self) -> None:
        if not self._prog_ready():
            return
        if not self._prog.winfo_ismapped():
            self._prog.pack(fill="x", pady=(6, 0), before=self._logbox)
            # 进度线自带轨道，上方那条 1px 分隔线就多余了 —— 并排两条横线显得脏
            with contextlib.suppress(tk.TclError):
                self._divider.configure(bg=UI.CARD)

    def _progress_to(self, stage: str) -> None:
        """按阶段推进；**单调不回退**（事件乱序也不会倒退）。"""
        if not self._prog_ready():
            return
        frac = _STAGE_FRACTION.get(stage)
        if frac is None or frac <= self._prog_target:
            return
        self._prog_target = frac
        self._progress_show()
        self._progress_tick()

    def _progress_tick(self) -> None:
        if not self._prog_ready():
            return
        if self._prog_job is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._prog_job)
            self._prog_job = None

        def step() -> None:
            delta = self._prog_target - self._prog_f
            if abs(delta) < 0.004:
                self._prog_f = self._prog_target
                self._draw_progress()
                self._prog_job = None
                return
            self._prog_f += delta * 0.3            # 缓动到位，不做匀速跳变
            self._draw_progress()
            self._prog_job = self.root.after(24, step)

        step()

    def _progress_finish(self) -> None:
        if not self._prog_ready():
            return
        self._prog_target = 1.0
        self._progress_tick()

        def hide() -> None:
            self._prog.pack_forget()
            self._prog_f = self._prog_target = 0.0
            self._draw_progress()
            with contextlib.suppress(tk.TclError):
                self._divider.configure(bg=UI.LINE_SOFT)

        with contextlib.suppress(tk.TclError):
            self.root.after(900, hide)

    def _progress_reset(self) -> None:
        if not self._prog_ready():
            return
        if self._prog_job is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._prog_job)
            self._prog_job = None
        self._prog_f = self._prog_target = 0.0
        self._prog.pack_forget()
        self._draw_progress()
        with contextlib.suppress(tk.TclError):
            self._divider.configure(bg=UI.LINE_SOFT)

    def _sync_dot(self) -> None:
        """状态点：颜色跟状态文字走，一眼分出「在跑 / 通过 / 出错 / 受限」。"""
        text = self.var_status.get()
        color = UI.DOT_IDLE
        if text.startswith("运行中") or "正在取消" in text:
            color = UI.SKY
        elif "完成" in text or "通过" in text:
            color = UI.OK
        elif "异常" in text or "失败" in text or "不可写" in text or "错误" in text:
            color = UI.ERR
        elif "受限" in text or "取消" in text:
            color = UI.WARN
        with contextlib.suppress(tk.TclError):
            self._dot.itemconfigure(self._dot_id, fill=color)

    # ---- 交互回调（主线程） ----

    def _on_close(self) -> None:
        """关窗：运行中先确认，再走「取消 → 收尾 → 关窗」。"""
        if should_confirm_close(self.running):
            if not messagebox.askyesno(
                    "Galgame Unpacker",
                    "正在解包，确定要中止吗？\n\n"
                    "已完成的产物会保留，本轮 manifest 仍会写出（error=cancelled）。"):
                return
            self._close_when_done = True
            self._cancel()
            return
        self.root.destroy()

    def _on_drop(self, event) -> None:                      # noqa: ANN001
        self._drag_over(False)
        game = pick_game_dir(event.data)
        if game is None:
            messagebox.showwarning("Galgame Unpacker", "拖进来的不是存在的目录")
            return
        self.var_game.set(str(game))
        self._autofill_out()

    def _autofill_out(self) -> None:
        game = Path(self.var_game.get().strip().strip('"')).expanduser()
        if game.is_dir():
            self.var_out.set(str(default_out_dir(game.resolve())))

    def _browse_game(self) -> None:
        d = filedialog.askdirectory(title="选游戏目录")
        if d:
            self.var_game.set(d)
            self._autofill_out()

    def _browse_out(self) -> None:
        d = filedialog.askdirectory(title="选输出目录")
        if d:
            self.var_out.set(d)

    def _open_out(self) -> None:
        """打开输出目录。**任何失败都要说话**——静默无反应会让人以为按钮坏了。

        三种情况：目录在 → 打开；目录没建成（解包在 preflight/extract 就失败）→
        退到最近存在的上级并说明；`os.startfile` 本身失败 → 把错误显示出来。
        """
        if not self._last_out:
            return
        target = self._last_out
        note = ""
        if not target.is_dir():
            parent = next((p for p in target.parents if p.is_dir()), None)
            if parent is None:
                messagebox.showwarning(
                    "输出目录不存在",
                    f"{target}\n\n本轮可能没有产出，或该目录已被清理。\n"
                    f"完整原因看软件目录的 failures.log。")
                return
            note = f"（{target} 尚未创建，已打开它的上级：{parent}）"
            target = parent
        try:
            os.startfile(target)                             # noqa: S606
        except OSError as exc:
            messagebox.showerror("打不开目录", f"{target}\n\n{exc}")
            return
        if note:
            messagebox.showinfo("输出目录尚未创建", note)

    def _doctor(self) -> None:
        """只读自检（不跑解包、不改配置）：把「为什么写不进去」摊开，并可一键复制发回。"""
        game = Path(self.var_game.get().strip().strip('"')).expanduser()
        try:
            import doctor
            report = doctor.doctor_report(game if game.is_dir() else None,
                                          version=app_version())
        except Exception:                                    # noqa: BLE001
            # 自检自己崩了也要给东西看 —— 否则用户只能描述「点了一下没反应」
            report = "环境自检运行出错：\n\n" + traceback.format_exc()

        win = tk.Toplevel(self.root)
        win.title("环境自检")
        win.geometry("780x560")
        txt = tk.Text(win, wrap="none", font=("Consolas", 9))
        txt.insert("1.0", report)
        txt.configure(state="disabled")
        sb = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        bar = ttk.Frame(win, padding=6)
        bar.pack(fill="x", side="bottom")

        def _copy() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            self.var_status.set("自检报告已复制到剪贴板")

        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="复制到剪贴板", command=_copy).pack(side="right", padx=(0, 6))

    def _start(self) -> None:
        # 一律 resolve 成绝对路径：相对路径会让 `is_dir()` / `os.startfile`
        # 依赖当前工作目录 —— 「解包完打开输出目录没反应」就是这么来的。
        game = Path(self.var_game.get().strip().strip('"')).expanduser()
        if not game.is_dir():
            messagebox.showerror("Galgame Unpacker", "游戏目录不存在")
            return
        game = game.resolve()
        raw_out = self.var_out.get().strip().strip('"')
        out = (Path(raw_out).expanduser() if raw_out else default_out_dir(game)).resolve()
        # 输出目录不可写就别启动线程：默认目录可能被终端防护按进程信誉拦
        # （未签名 exe 写「文档」实测 WinError 5）。但在拦死之前先找一个真能写的位置
        # ——「浏览哪个位置都没用」说明是进程级拦截，让用户继续试目录是浪费时间。
        why = ensure_writable(out)
        if why:
            # 记一笔：用户下次发 failures.log 时能直接看到「哪一步、哪个路径、什么错」，
            # 不用再靠截图猜（这条失败发生在起跑之前，不走 _finish_failure）。
            faillog.log_failure(error="output-not-writable", game_dir=game, out_dir=out,
                                extra={"detail": why, "stage": "pre-start-write-probe"},
                                rc=1)
            # 先自己找一条能走的路：实测「桌面/文档/游戏目录全被拦、程序目录能写」，
            # 所以把程序目录排第一。找到就继续跑，别为了「路径好看」把活儿停掉。
            alt, table = pick_writable(fallback_out_dirs())
            if alt is not None:
                self._log(f"[warn] 原输出目录不可写：{out} —— {why}")
                self._log(f"[warn] 已自动改用：{alt}")
                messagebox.showwarning(
                    "已自动改用可写目录",
                    f"这个位置写不进去：\n{out}\n\n{why}\n\n"
                    f"已自动改用：\n{alt}\n\n"
                    "产物会落在这里（「打开输出目录」指向的就是它）。\n"
                    "想固定用别的位置，可以在上面的「输出目录」里手动填。")
                out = alt
            else:
                # 连程序目录都写不进去 = 进程级拦截，让用户继续挑目录是浪费时间。
                detail = "\n".join(f"  {p}\n      {'可写' if w is None else w}"
                                   for p, w in table)
                faillog.log_failure(error="no-writable-location", game_dir=game,
                                    out_dir=out,
                                    extra={"detail": detail, "stage": "fallback-exhausted"},
                                    rc=1)
                messagebox.showerror(
                    "找不到任何可写的位置",
                    f"{out}\n\n{why}\n\n"
                    "按 程序目录 → 本地应用数据 → 临时目录 依次试过，全部不可写：\n\n"
                    f"{detail}\n\n"
                    "这不是目录选错了，是拦截发生在进程级。\n"
                    "请点「环境自检」把报告发回；或退出全部安全软件后重试。")
                # 探针本身也可能误报（守卫只拦「这个形状的写入」）。给一条「我知道
                # 有风险，但先跑跑看」的路 —— 比把人堵死在这里强；真失败会进 failures.log。
                if not messagebox.askyesno(
                        "仍然尝试运行？",
                        "自检可能是误报（拦的是探针形状，不一定是真实写入）。\n\n"
                        "仍然要按上面这个目录跑一次吗？失败会写进 failures.log。"):
                    return
            self.var_out.set(str(out))
        # 已有产物必须先问：默认 auto 会静默叠跑（产物数虚高但对账自洽），
        # 拒绝则让用户换个目录 —— 两条路都比「跑完给一个假数字」强。
        overwrite = False
        if has_stale_products(out):
            if not messagebox.askyesno(
                    "输出目录已有产物",
                    f"{out}\n\n里面已经有上一轮的产物。\n\n"
                    f"是：清空 raw/ 与 png/ 后重新解包（旧产物会删除）\n"
                    f"否：取消本次运行，请换一个输出目录",
                    icon="warning"):
                return
            overwrite = True
        self._cancel_ev = threading.Event()      # 每次运行一个新位，别带上一轮的状态
        self._close_when_done = False
        self._crashed = False
        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_open.configure(state="disabled")
        self.var_status.set(f"运行中：{game.name}")
        self._progress_reset()
        self._progress_to("detect")      # 立刻给一条线，别等第一个阶段事件
        self._log_clear()
        self._last_out = out
        # 第一行就告诉用户产物落在哪：跑十几分钟的活儿，最常被问的就是这个
        self._log(f"输出目录：{out}")
        threading.Thread(target=self._worker,
                         args=(game, out, bool(self.var_gui.get()), self._cancel_ev,
                               overwrite, bool(self.var_organize.get())),
                         daemon=True).start()

    def _cancel(self) -> None:
        """置取消位。编排层在**阶段边界**停下，已完成阶段的产物保留可续跑。"""
        if not self.running:
            return
        self._cancel_ev.set()
        self.btn_cancel.configure(state="disabled")
        self.var_status.set("正在取消…（停在当前阶段边界）")

    # ---- 日志/队列（poll 在主线程） ----

    def _log(self, line: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", line.rstrip("\n") + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _log_clear(self) -> None:
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "stage":
                    self.var_status.set(f"运行中 · {item[1]}")
                    self._progress_to(item[1])
                elif kind == "done":
                    rc, man = item[1], item[2]
                    self.running = False
                    self.btn_run.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")
                    self.btn_open.configure(state="normal")
                    if not self._crashed:
                        # 崩溃时别再写「完成，退出码 1」——那会把「线程挂了」说成「跑完了」
                        self.var_status.set(f"完成，退出码 {rc}")
                    self._progress_finish()
                    self._summarize(rc, man)
                    if self._close_when_done:
                        # 关窗请求已经等在这里：manifest 写完、摘要弹过，现在才真关。
                        self.root.destroy()
                        return
                elif kind == "crash":
                    # 只记日志与状态，**不**在这里 destroy：worker 保证随后一定补一条
                    # ("done", 1, {"error": "worker-aborted"})，由它统一收敛（按钮恢复、
                    # 摘要照常弹、关窗请求也照常执行）。两个分支都 destroy 会漏掉摘要。
                    self.running = False
                    self._crashed = True
                    self.btn_run.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")
                    self.var_status.set("运行异常（看日志）")
                    self._log(item[1])
        except queue.Empty:
            pass
        except Exception:                                   # noqa: BLE001
            # 单条事件处理失败**不许**杀死轮询器（批次 C 收口，2026-11-03 实测）：
            # `_summarize` 遇到 `media_minutes=None` 抛 TypeError，原来 `after()`
            # 在 try 末尾、异常先冲出函数 → `after` 永远执行不到 → 轮询停摆、队列
            # 从此没人消费（摘要不弹、再点开始也看不到结果，只能重启程序）。
            # 吞掉并写日志，下一条事件照常处理；异常细节进日志面板便于复盘。
            try:
                self._log("[错误] 界面事件处理失败（轮询继续）：\n"
                          + traceback.format_exc())
            except Exception:                               # noqa: BLE001
                pass
        finally:
            try:
                self.root.after(100, self._poll)
            except tk.TclError:
                # 窗口已销毁（用户关窗）：轮询自然终止，别让收尾再抛一次。
                pass

    def _summarize(self, rc: int, man: dict) -> None:
        """跑完弹一行人话：交付了多少、验了多少、对账有没有差。

        文案拼装全部在模块级 `summarize_text`（纯函数，tests 锁得住、不依赖显示）；
        这里只负责「写进日志面板 + 弹窗」。取不到本轮 manifest 时明确说失败，
        别装成 0 个文件。
        """
        text = summarize_text(rc, man)
        if text is None:
            res = man or {}
            err = res.get("error") or "未知（本轮未产出 manifest）"
            detail = f"本轮失败：{err}（本轮未产出 manifest，详见日志）"
            self._log("\n" + detail)
            messagebox.showwarning("Galgame Unpacker", detail)
            return
        self._log("\n" + text)
        if self._last_out:
            self._log(f"manifest：{self._last_out / 'manifest.json'}")
        (messagebox.showinfo if rc == 0 else messagebox.showwarning)(
            "Galgame Unpacker", text)

    # ---- 工作线程（不碰任何 Tk） ----

    def _worker(self, game: Path, out: Path, allow_gui: bool,
                cancel_ev: threading.Event, overwrite: bool = False,
                organize: bool = False) -> None:
        """跑一次全链，并**保证**最后一定有一条结果入队。

        为什么是 `except BaseException` + `finally` 兜一条 `done`（批次 C7，2026-11-03）：
        工作线程是 daemon，它一旦异常退出，`("done", …)` 就永远不会入队 —— GUI 停在
        「运行中」、开始/取消按钮全灰、取消键也点不动。实测就是这么死的：
        `toolbridge.drop_tree` 重抛 `SystemExit`（删除守卫拒绝删除时抛它），
        `except Exception` 拦不住，线程静默消失。
        所以这里兜 BaseException，并且**无论走哪条路**都补一条 `done` 让主线程收敛。
        （`KeyboardInterrupt` 同样兜住：它是主线程的事，工作线程里没人接。）
        """
        crashed = False
        try:
            import orchestrator as orch
            ctx = orch.Ctx(game_dir=game, out_dir=out,
                           work_dir=out / "_work",
                           manifest_path=out / "manifest.json",
                           allow_gui=allow_gui,
                           overwrite=overwrite,
                           organize=organize,
                           should_stop=cancel_ev.is_set)
            orig_log = ctx.log

            def sink(stage: str, msg: str) -> None:
                orig_log(stage, msg)
                for line in msg.rstrip("\n").splitlines():
                    self.q.put(("log", f"[{stage}] {line}"))
                self.q.put(("stage", stage))

            ctx.log = sink                                  # type: ignore[method-assign]
            rc, res = orch.run(ctx)
            # 原样把 run() 的返回交给主线程：成功是 manifest 本身、失败是带 error 的包装，
            # 由 `_summarize` 统一走 `_result_manifest` 拆（拆不出来才说「本轮未产出」）。
            self.q.put(("done", rc, res))
        except BaseException:                                # noqa: BLE001 —— 见 docstring
            crashed = True
            text = traceback.format_exc()
            # 工作线程崩了不走 `_finish_failure`（那条路连 rc 都拿不到），
            # 失败日志得在这里补一笔，否则最严重的一类失败反而没有记录。
            try:
                faillog.log_failure(error="worker-crashed", game_dir=game, out_dir=out,
                                    exc_text=text, rc=1)
            except Exception:                                # noqa: BLE001
                pass
            self.q.put(("crash", text))
        finally:
            if crashed:
                # 兜底：哪怕上面拿不到 rc/manifest，也要让主线程把「运行中」收敛掉。
                self.q.put(("done", 1, {"error": "worker-aborted", "manifest": None,
                                        "stages": []}))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = "--gui-smoke" in argv

    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()          # noqa: F841 (root 被窗口持有)
    app = App(root)
    if smoke:
        root.after(600, root.destroy)                       # 冻结包 Tk 冒烟：能建窗即过
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
