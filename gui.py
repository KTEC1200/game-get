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
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:                                        # noqa: BLE001
    HAS_DND = False

#: 应用根：冻结态 = exe 所在目录（安装到 {localappdata}\Programs\GalgameUnpacker，可写）；
#: 源码态 = 仓库根（产物按纪律落 <仓库>/_extracted/<游戏名>/）。
APP_ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent


def default_out_dir(game_dir: Path) -> Path:
    """产物默认落 <应用根>/_extracted/<游戏名>/（与 CLI/planner 同一约定）。"""
    return APP_ROOT / "_extracted" / game_dir.name


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
        self.root.after(100, self._poll)

    # ---- 交互回调（主线程） ----

    def _on_drop(self, event) -> None:                      # noqa: ANN001
        game = pick_game_dir(event.data)
        if game is None:
            messagebox.showwarning("Galgame Unpacker", "拖进来的不是存在的目录")
            return
        self.var_game.set(str(game))
        self._autofill_out()

    def _autofill_out(self) -> None:
        game = Path(self.var_game.get().strip().strip('"'))
        if game.is_dir():
            self.var_out.set(str(default_out_dir(game)))

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
        if self._last_out and self._last_out.is_dir():
            os.startfile(self._last_out)                     # noqa: S606

    def _start(self) -> None:
        game = Path(self.var_game.get().strip().strip('"'))
        if not game.is_dir():
            messagebox.showerror("Galgame Unpacker", "游戏目录不存在")
            return
        out = Path(self.var_out.get().strip().strip('"') or default_out_dir(game))
        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_open.configure(state="disabled")
        self.var_status.set(f"运行中：{game.name}")
        self._log_clear()
        self._last_out = out
        threading.Thread(target=self._worker,
                         args=(game, out, bool(self.var_gui.get())),
                         daemon=True).start()

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
                    self.btn_open.configure(state="normal")
                    self.var_status.set(f"完成，退出码 {rc}")
                    self._summarize(rc, man)
                elif kind == "crash":
                    self.running = False
                    self.btn_run.configure(state="normal")
                    self.var_status.set("运行异常（看日志）")
                    self._log(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _summarize(self, rc: int, man: dict) -> None:
        """跑完弹一行人话：交付了多少、验了多少、对账有没有差。"""
        counts = man.get("counts") or {}
        final = counts.get("final") or {}
        rec = man.get("reconcile") or {}
        ver = man.get("verify") or {}
        lines = [
            f"引擎：{man.get('engine')}    退出码：{rc}",
            f"交付（final）：{final.get('total', '?')} 个文件",
        ]
        if rec.get("method") != "no-index-available" and rec.get("diff") is not None:
            lines.append(f"对账：索引 {rec.get('expected')} vs 落盘 {rec.get('actual')} "
                         f"（diff={rec.get('diff')}）")
        else:
            lines.append("对账：无索引地面真相，未对账")
        lines.append(f"验收：图片 {ver.get('image_ok')}/{ver.get('image_fail')}失败 · "
                     f"音频 {ver.get('audio_ok')}/{ver.get('audio_fail')}失败 · "
                     f"视频 {ver.get('video_ok')}/{ver.get('video_fail')}失败 · "
                     f"{ver.get('media_minutes', 0):.1f} 分钟")
        detail = "\n".join(lines)
        self._log("\n" + detail)
        if self._last_out:
            self._log(f"manifest：{self._last_out / 'manifest.json'}")
        (messagebox.showinfo if rc == 0 else messagebox.showwarning)(
            "Galgame Unpacker", detail)

    # ---- 工作线程（不碰任何 Tk） ----

    def _worker(self, game: Path, out: Path, allow_gui: bool) -> None:
        try:
            import orchestrator as orch
            ctx = orch.Ctx(game_dir=game, out_dir=out,
                           work_dir=out / "_work",
                           manifest_path=out / "manifest.json",
                           allow_gui=allow_gui)
            orig_log = ctx.log

            def sink(stage: str, msg: str) -> None:
                orig_log(stage, msg)
                for line in msg.rstrip("\n").splitlines():
                    self.q.put(("log", f"[{stage}] {line}"))
                self.q.put(("stage", stage))

            ctx.log = sink                                  # type: ignore[method-assign]
            rc, man = orch.run(ctx)
            self.q.put(("done", rc, man))
        except Exception:                                    # noqa: BLE001
            self.q.put(("crash", traceback.format_exc()))


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
