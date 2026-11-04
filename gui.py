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

import os
import os
import queue
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

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


def writable_fallback(game_dir: Path) -> tuple[Path | None, list[str]]:
    """默认位置写不进去时，找一个**真的能写**的产物目录。

    返回 `(可用路径, 每个候选的失败说明)`。全部不行时第一项为 None ——
    那说明终端防护是按进程拦的，换目录解决不了，只能加白名单（弹窗会说清楚）。

    候选顺序按「用户会不会去翻」排：用户目录 → 本地应用数据 → 系统临时目录。
    前两个是给人看的，最后一个只保证能跑（临时目录可能被清理）。
    """
    home = Path.home()
    bases = [
        home / "GalgameUnpacker",
        Path(os.environ.get("LOCALAPPDATA") or home) / "GalgameUnpacker",
        Path(tempfile.gettempdir()) / "GalgameUnpacker",
    ]
    tried: list[str] = []
    for base in bases:
        cand = base / "_extracted" / game_dir.name
        why = ensure_writable(cand)
        if why is None:
            return cand, tried
        tried.append(f"{cand}  ← {why}")
    return None, tried


def default_out_dir(game_dir: Path) -> Path:
    """产物默认落 **`<游戏目录>/output`**（2026-11-04 用户要求）。

    为什么放游戏旁边：测试时产物跑到程序目录下（相对路径 + 默认根算错），回头根本找不到。
    放在游戏旁边最符合直觉——解完就在原地，换盘/换机器跟着走，也不用去 C 盘翻。

    游戏目录不可写（只读安装、光盘、受保护目录）时由 `_start` 的可写预检接管，
    退到 `writable_fallback`（用户目录 / LOCALAPPDATA / TEMP），不会因此卡死。
    """
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


class App:
    """主窗口。`poll()` 只在主线程跑（root.after 驱动），worker 只往 self.q 塞。"""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.running = False
        root.title("Galgame Unpacker")
        root.minsize(680, 460)

        frm = ttk.Frame(root, padding=8)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(4, weight=1)

        ttk.Label(frm, text="游戏目录：").grid(row=0, column=0, sticky="w")
        self.var_game = tk.StringVar()
        self.ent_game = ttk.Entry(frm, textvariable=self.var_game)
        self.ent_game.grid(row=0, column=1, sticky="ew")
        self.ent_game.bind("<Return>", lambda _e: self._autofill_out())
        ttk.Button(frm, text="浏览…", command=self._browse_game).grid(row=0, column=2, padx=(4, 0))

        ttk.Label(frm, text="输出目录：").grid(row=1, column=0, sticky="w")
        self.var_out = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_out).grid(row=1, column=1, sticky="ew")
        ttk.Button(frm, text="浏览…", command=self._browse_out).grid(row=1, column=2, padx=(4, 0))

        opt = ttk.Frame(frm)
        opt.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.var_gui = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="允许 GUI 自动化（加密 KiriKiri，约 40 分钟）",
                        variable=self.var_gui).pack(side="left")
        self.btn_run = ttk.Button(opt, text="开始解包", command=self._start)
        self.btn_run.pack(side="right")
        self.btn_cancel = ttk.Button(opt, text="取消", command=self._cancel,
                                     state="disabled")
        self.btn_cancel.pack(side="right", padx=(0, 6))
        self.btn_open = ttk.Button(opt, text="打开输出目录", command=self._open_out,
                                   state="disabled")
        self.btn_open.pack(side="right", padx=(0, 6))

        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(frm, textvariable=self.var_status, relief="sunken",
                  anchor="w").grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self.txt = tk.Text(frm, height=16, wrap="none", state="disabled",
                           font=("Consolas", 9))
        self.txt.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        sb = ttk.Scrollbar(frm, command=self.txt.yview)
        sb.grid(row=4, column=3, sticky="ns")
        self.txt.configure(yscrollcommand=sb.set)

        # 拖拽看 **root 能力** 不看模块 import：普通 tk.Tk() 根没有 drop_target_register，
        # 只有 TkinterDnD.Tk() 根有（tests 里的冒烟用的就是普通根）
        if hasattr(root, "drop_target_register"):
            for w in (root, self.ent_game):
                w.drop_target_register(DND_FILES)           # type: ignore[attr-defined]
                w.dnd_bind("<<Drop>>", self._on_drop)        # type: ignore[attr-defined]
        if not hasattr(root, "drop_target_register") and not HAS_DND:
            self.var_status.set("就绪（未装 tkinterdnd2，拖拽不可用：浏览或粘贴路径）")

        self._last_out: Path | None = None
        #: 取消位（每次运行换一个新的 Event；传给 run 的是 is_set 而不是 Event 本身，
        #: 免得编排层为了「读一个标志」依赖 threading）
        self._cancel_ev = threading.Event()
        self._close_when_done = False        # 关窗时点了「确定」→ 跑完再 destroy
        self._crashed = False                # 工作线程挂了（状态条别被后续 done 覆盖）
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll)

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
        """打开输出目录。**目录不存在要明确说一句**——静默无反应最伤：
        用户会以为按钮坏了，实际是路径没指对（相对路径 + cwd 变化）或被清理了。
        """
        if not self._last_out:
            return
        if self._last_out.is_dir():
            os.startfile(self._last_out)                     # noqa: S606
        else:
            messagebox.showwarning(
                "输出目录不存在",
                f"{self._last_out}\n\n本轮可能没有产出，或该目录已被清理。\n"
                f"完整原因看输出目录里的 manifest.json 或软件目录的 failures.log。")

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
            alt, tried = writable_fallback(game)
            if alt is None:
                messagebox.showerror(
                    "所有位置都写不进去",
                    "试过这些位置全部失败：\n\n"
                    + "\n".join(tried)
                    + "\n\n这不是目录选错了，是安全软件在拦这个程序的写入。\n"
                      "请把解压目录加入火绒/EDR 的信任区（或联系管理员放行）后重试。")
                return
            if not messagebox.askyesno(
                    "输出目录不可写，已找到替代位置",
                    f"原位置：{out}\n{why}\n\n"
                    f"改用这个位置继续吗？\n{alt}\n\n"
                    f"（这是程序自动探测到可写的地方；不想用就点「否」再手动选一个）",
                    icon="warning"):
                return
            out = alt
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
        self._log_clear()
        self._last_out = out
        # 第一行就告诉用户产物落在哪：跑十几分钟的活儿，最常被问的就是这个
        self._log(f"输出目录：{out}")
        threading.Thread(target=self._worker,
                         args=(game, out, bool(self.var_gui.get()), self._cancel_ev,
                               overwrite),
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
                elif kind == "done":
                    rc, man = item[1], item[2]
                    self.running = False
                    self.btn_run.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")
                    self.btn_open.configure(state="normal")
                    if not self._crashed:
                        # 崩溃时别再写「完成，退出码 1」——那会把「线程挂了」说成「跑完了」
                        self.var_status.set(f"完成，退出码 {rc}")
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
                cancel_ev: threading.Event, overwrite: bool = False) -> None:
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
