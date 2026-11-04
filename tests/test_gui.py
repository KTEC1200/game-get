#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 最小壳的测试：纯逻辑全锁，Tk 部分只做构造冒烟（交互不进测试）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gui                                       # noqa: E402
import orchestrator as orch                      # noqa: E402

tk = pytest.importorskip("tkinter")


# ---------------------------------------------------------------------------
# 纯逻辑（不碰 Tk）
# ---------------------------------------------------------------------------

def test_normalize_dropped_handles_braces_and_spaces():
    """tkdnd 给的串：带空格路径被 {..} 包住，条目间用空白分隔——括号里的空格不算分隔符。"""
    got = gui.normalize_dropped(r'{D:\My Game} D:\other')
    assert [str(p) for p in got] == [r"D:\My Game", r"D:\other"]
    assert [str(p) for p in gui.normalize_dropped(r"D:\a D:\b")] == [r"D:\a", r"D:\b"]


def test_pick_game_dir_takes_first_existing_dir():
    assert gui.pick_game_dir(r"{D:\no such dir}\D:\other") is None
    d = gui.pick_game_dir(str(ROOT))
    assert d == ROOT


def test_default_out_dir_follows_extracted_convention():
    """产物默认落 <应用根>/_extracted/<游戏名>/（与 CLI 同一约定，坑：别散到盘根）。"""
    out = gui.default_out_dir(Path(r"D:\HY\Some Game"))
    assert out == gui.APP_ROOT / "_extracted" / "Some Game"


def test_main_dispatches_gui_before_argparse(monkeypatch):
    """--gui / --gui-smoke / **无参数（双击 exe）** 都在 argparse 前分流进 GUI
    ——桌面工具第一眼不该是「argparse 报缺参数」闪退。"""
    seen: list[list[str]] = []

    def fake_launch(argv):
        seen.append(argv)
        return 7

    monkeypatch.setattr(orch, "_launch_gui", fake_launch)
    assert orch.main(["--gui"]) == 7
    assert orch.main(["--gui-smoke"]) == 7
    assert orch.main([]) == 7
    assert seen == [["--gui"], ["--gui-smoke"], []]


def _fake_manifest() -> dict:
    """orchestrator manifest 的精简形状（gui._summarize 只读这几个键）。"""
    return {
        "engine": "RPG Maker",
        "counts": {"raw": {"total": 1585}, "final": {"total": 1585},
                   "converted": {}},
        "reconcile": {"method": "index", "expected": 1585, "actual": 1585, "diff": 0},
        "verify": {"image_ok": 719, "image_fail": 0, "audio_ok": 866, "audio_fail": 0,
                   "video_ok": 0, "video_fail": 0, "media_minutes": 651.4},
    }


# ---------------------------------------------------------------------------
# Tk 构造冒烟（无显示环境自动跳过；交互不测）
# ---------------------------------------------------------------------------

@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无可用显示")
    root.withdraw()
    yield root
    root.destroy()


def test_app_constructs_and_consumes_queue_events(tk_root, monkeypatch):
    """建窗 + 队列三事件（log/stage/done）一轮 poll 全消化，状态条走到「完成」。"""
    boxes: list[tuple[str, str]] = []
    monkeypatch.setattr(gui.messagebox, "showinfo",
                        lambda title, msg: boxes.append(("info", msg)))
    monkeypatch.setattr(gui.messagebox, "showwarning",
                        lambda title, msg: boxes.append(("warn", msg)))

    app = gui.App(tk_root)
    assert app.running is False

    app.q.put(("log", "[extract] hello"))
    app.q.put(("stage", "extract"))
    app._poll()
    assert "[extract] hello" in app.txt.get("1.0", "end")
    assert "extract" in app.var_status.get()

    app.q.put(("done", 0, _fake_manifest()))
    app._poll()
    assert app.running is False
    assert not app.btn_run["state"] in ("disabled",)      # 跑完按钮恢复
    assert len(boxes) == 1 and boxes[0][0] == "info"
    assert "RPG Maker" in boxes[0][1] and "1585" in boxes[0][1]


def test_app_reconcile_gap_is_reported_not_hidden(tk_root, monkeypatch):
    """对账有差要出现在摘要里——「差不多等于没验」的 GUI 版。"""
    monkeypatch.setattr(gui.messagebox, "showwarning",
                        lambda title, msg: None)
    man = _fake_manifest()
    man["reconcile"] = {"method": "index", "expected": 1585, "actual": 1584, "diff": -1}
    app = gui.App(tk_root)
    app.q.put(("done", 1, man))
    app._poll()
    assert "diff=-1" in app.txt.get("1.0", "end")


# ---------------------------------------------------------------------------
# 批次 B2（2026-11-03）：取消 / 关窗 / 失败摘要
# ---------------------------------------------------------------------------

def test_should_confirm_close_only_while_running():
    """★B2★ 只有运行中关窗才需要确认（空闲时多问一句只是烦人）。

    运行中直接 destroy 会把 daemon 工作线程掐死在写文件的中间，留下几 GB 半截 raw
    且没有 manifest 说明它是什么——所以必须走「置取消位 → 边界停下 → 再关」。
    """
    assert gui.should_confirm_close(True) is True
    assert gui.should_confirm_close(False) is False


def test_summarize_unwraps_run_wrapper_manifest(tk_root, monkeypatch):
    """★B2★ run() 的**包装 dict**（失败形态）也要能读出本轮 manifest 的真实数字。

    回归：`_summarize` 曾直接读 `man.get("counts")`，而失败时 man 是
    `{"error":…, "stages":…, "manifest":…}` → counts 恒为空 → 界面显示
    「交付（final）：? 个文件」，把「失败了」说成「不知道」。
    """
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, msg: None)
    man = _fake_manifest()
    man["ok"] = False
    man["error"] = "extract-failed"                      # _finish_failure 就是这么写的
    app = gui.App(tk_root)
    app.q.put(("done", 1, {"error": "extract-failed", "stages": [], "manifest": man}))
    app._poll()
    txt = app.txt.get("1.0", "end")
    assert "1585" in txt, txt
    assert "extract-failed" in txt


def test_summarize_reports_missing_manifest_explicitly(tk_root, monkeypatch):
    """★B2★ 连 manifest 都没有时要说「本轮失败：<error>（本轮未产出 manifest）」。

    不能显示成 0 个文件 / 0 失败——那是把「什么都没验」伪装成「验过了没问题」。
    """
    boxes: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning",
                        lambda title, msg: boxes.append(msg))
    app = gui.App(tk_root)
    app._summarize(1, {"error": "preflight-failed", "manifest": None, "stages": []})
    assert boxes and "本轮失败" in boxes[0] and "preflight-failed" in boxes[0]
    assert "本轮未产出 manifest" in boxes[0]


def test_summarize_labels_cancelled_in_plain_words(tk_root, monkeypatch):
    """★B2★ 取消在摘要里说人话（「用户取消」），而不是甩一个 error 代号。"""
    boxes: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning",
                        lambda title, msg: boxes.append(msg))
    man = _fake_manifest()
    man["error"] = "cancelled"
    man["ok"] = False
    app = gui.App(tk_root)
    app._summarize(1, man)
    assert boxes and "用户取消" in boxes[0]


# ---------------------------------------------------------------------------
# 批次 C7 / C10 / C14（2026-11-03）：工作线程一定收敛、关窗、SystemExit
# ---------------------------------------------------------------------------

def test_worker_reports_done_even_when_run_raises_systemexit(tmp_path, monkeypatch):
    """★C7+C14★ 工作线程遇到 SystemExit 也要补一条 done，否则界面永远停在「运行中」。

    真实触发链：`toolbridge.drop_tree` 曾经重抛 SystemExit（删除守卫拒绝删除时抛它），
    `_worker` 的 `except Exception` 拦不住 → 线程静默消失 → `("done")` 永不入队 →
    开始/取消按钮永久禁用。现在 drop_tree 改成返回 False，但**兜底必须还在**：
    任何 BaseException 都不能让 worker 不收敛。
    """
    import queue as _queue
    import threading as _threading

    app = object.__new__(gui.App)          # 只造壳，不建 Tk
    app.q = _queue.Queue()
    app.running = True
    app._last_out = None

    def boom(ctx):
        raise SystemExit(1)

    monkeypatch.setattr(orch, "run", boom)
    gui.App._worker(app, tmp_path / "game", tmp_path / "out", False, _threading.Event())

    items = []
    while not app.q.empty():
        items.append(app.q.get_nowait())
    kinds = [it[0] for it in items]

    assert "crash" in kinds, "traceback 必须入队（用户要看日志）"
    assert kinds.count("done") == 1, "无论怎么挂，都必须恰好一条 done 让界面收敛"
    done = items[kinds.index("done")]
    assert done[1] == 1
    assert done[2]["error"] == "worker-aborted"
    assert done[2]["manifest"] is None


def test_worker_passes_through_a_normal_result(tmp_path, monkeypatch):
    """★C7 对照★ 正常返回时只有一条 done（不能因为兜底逻辑多塞一条）。"""
    import queue as _queue
    import threading as _threading

    app = object.__new__(gui.App)
    app.q = _queue.Queue()
    app.running = True
    app._last_out = None

    payload = {"error": "extract-failed", "manifest": None, "stages": []}
    monkeypatch.setattr(orch, "run", lambda ctx: (1, payload))
    gui.App._worker(app, tmp_path / "game", tmp_path / "out", False, _threading.Event())

    items = []
    while not app.q.empty():
        items.append(app.q.get_nowait())
    assert [it[0] for it in items] == ["done"]
    assert items[0][1] == 1 and items[0][2] is payload


def test_on_close_asks_before_interrupting_a_run(tk_root, monkeypatch):
    """★C10★ 运行中关窗要问；点「否」不置取消位，点「是」才置位并等 done 再关。"""
    asked: list[str] = []
    monkeypatch.setattr(gui.messagebox, "askyesno",
                        lambda title, msg: (asked.append(msg), False)[1])
    app = gui.App(tk_root)
    app.running = True

    app._on_close()

    assert asked, "运行中关窗必须先问一句"
    assert app._close_when_done is False
    assert app._cancel_ev.is_set() is False, "用户点了「否」就不该动取消位"

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda title, msg: True)
    app._on_close()

    assert app._close_when_done is True, "点了「是」→ 先取消、跑完再关"
    assert app._cancel_ev.is_set() is True


def test_on_close_without_running_destroys_immediately(tk_root):
    """★C10★ 空闲时关窗不多问（那只是烦人）。"""
    class _FakeRoot:
        destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    app = gui.App(tk_root)
    app.root = _FakeRoot()                 # 别真销毁 fixture 的 Tk
    app.running = False
    app._on_close()
    assert app.root.destroyed is True


# ---------------------------------------------------------------------------
# 批次 C 收口：摘要渲染与轮询器的存活（2026-11-03）
# ---------------------------------------------------------------------------

def test_summarize_text_handles_null_media_minutes():
    """`verify.media_minutes=null`（没验成）不许再炸 TypeError——原来那句
    `f"{ver.get('media_minutes', 0):.1f}"` 的默认值 0 对 None 不生效，而轮询器
    就死在这。渲染层要把它说成「未统计」，**不是** 0.0（0.0 会被读成「验了、
    真的 0 分钟」，与「没验」是两种事实）。"""
    man = {
        "engine": "Ren'Py",
        "counts": {"final": {"total": 3}},
        "reconcile": {"method": "index", "expected": 3, "actual": 3, "diff": 0},
        "verify": {"image_ok": 1, "image_fail": 0, "audio_ok": 0, "audio_fail": 0,
                   "video_ok": 0, "video_fail": 0, "media_minutes": None},
    }
    text = gui.summarize_text(0, man)
    assert text is not None
    assert "未统计" in text
    assert "0.0 分钟" not in text


def test_summarize_text_returns_none_for_wrapper_without_manifest():
    """失败包装 dict 里没有本轮 manifest → None（调用方负责说「本轮失败」）。"""
    assert gui.summarize_text(1, {"error": "extract-failed", "stages": []}) is None


class _FakeRoot:
    """只记录 after 调用次数：_poll 的收尾只依赖 root.after。"""

    def __init__(self):
        self.after_calls = 0

    def after(self, ms, fn):
        self.after_calls += 1


def _shell_app(root):
    """App.__new__ 造壳：只挂 `_poll` 会触碰的属性，不建任何真 Tk 控件。

    为什么不建真 Tk：`tk_root` fixture 在本机约 11/12 的运行会撞上「无可用显示」
    的 skip——给冻结 bug 写的护栏自己先被 skip，等于没写（QA 实测）。"""
    import queue as _q

    class _Btn:
        def configure(self, **kw):
            pass

    class _Var:
        def set(self, v):
            pass

    app = gui.App.__new__(gui.App)
    app.root = root
    app.q = _q.Queue()
    app.running = True
    app._crashed = False
    app._close_when_done = False
    app._last_out = None
    app.var_status = _Var()
    app.btn_run, app.btn_cancel, app.btn_open = _Btn(), _Btn(), _Btn()
    return app


def test_poll_survives_an_event_handler_exception(monkeypatch):
    """任何一条事件的处理抛异常，轮询器都必须活着（after 重挂）。

    修前行为：`_summarize` 抛 TypeError → 冲出 `_poll` → `after()` 永远执行不到
    → 摘要不弹、日志不再滚动、再点「开始」跑完也看不到结果，只能重启程序。"""
    import queue as _q

    app = _shell_app(_FakeRoot())

    def boom(rc, man):
        raise TypeError("unsupported format string passed to NoneType.__format__")

    monkeypatch.setattr(gui, "summarize_text", boom)
    logs: list[str] = []
    monkeypatch.setattr(app, "_log", lambda line: logs.append(line))

    app.q.put(("done", 1, {"verify": {"media_minutes": None}}))
    app.q.put(("log", "tail"))          # 证明后续事件仍会被消费
    app._poll()                          # 修前这里直接 TypeError 逃出

    assert app.root.after_calls == 1, "轮询器没被重挂 → 界面会永久卡死"
    assert any("TypeError" in line for line in logs)

    # 下一轮轮询（真实 Tk 里由 after(100) 触发）继续消费队列：
    app._poll()
    assert app.root.after_calls == 2
    assert any("tail" in line for line in logs), "后续事件没被消费"


# ---------------------------------------------------------------------------
# 输出目录口径（2026-11-04）
# ---------------------------------------------------------------------------

def test_default_out_dir_uses_user_root_when_frozen(monkeypatch, tmp_path):
    """便携版默认落「用户目录\\GalgameUnpacker」，不落程序安装目录。"""
    monkeypatch.setattr(gui, "FROZEN", True)
    monkeypatch.setattr(gui, "user_output_root",
                        lambda: tmp_path / "GalgameUnpacker")

    out = gui.default_out_dir(Path(r"D:/HY/Some Game"))

    assert out == tmp_path / "GalgameUnpacker" / "_extracted" / "Some Game"


def test_default_out_dir_never_lands_in_install_dir_when_frozen(monkeypatch):
    """★核心★ 便携版产物不许落在 exe 所在目录 —— 删程序目录会连产物一起删。"""
    monkeypatch.setattr(gui, "FROZEN", True)

    out = gui.default_out_dir(Path("Some Game"))

    assert gui.APP_ROOT not in out.parents


def test_user_output_root_is_under_home_not_documents(tmp_path, monkeypatch):
    """★实测踩过★ 产物根必须在 home 下、**不进 Documents**。

    2026-11-04 用户实测：未签名 exe 在 `Documents` 下建目录被终端防护拒绝
    （WinError 5），同一个路径用 Python 源码跑却通 —— 拦的是 exe 不是路径。
    """
    (tmp_path / "Documents").mkdir()
    monkeypatch.setattr(gui.Path, "home", staticmethod(lambda: tmp_path))

    root = gui.user_output_root()

    assert root == tmp_path / "GalgameUnpacker"
    assert "Documents" not in root.parts


def test_ensure_writable_passes_and_creates_dir(tmp_path):
    assert gui.ensure_writable(tmp_path / "new-out") is None
    assert (tmp_path / "new-out").is_dir()


def test_ensure_writable_returns_reason_on_permission_error(tmp_path, monkeypatch):
    """不可写要返回原因（弹窗要显示），而不是抛异常把 Tk 打死。"""
    def boom(*_a, **_k):
        raise PermissionError(13, "拒绝访问")

    monkeypatch.setattr(gui.Path, "mkdir", boom)

    why = gui.ensure_writable(tmp_path / "x")

    assert why and "PermissionError" in why


def test_has_stale_products_counts_only_files(tmp_path):
    assert gui.has_stale_products(tmp_path) is False
    (tmp_path / "raw").mkdir()
    assert gui.has_stale_products(tmp_path) is False, "空目录不算残留"
    (tmp_path / "png").mkdir()
    (tmp_path / "png" / "a.png").write_bytes(b"x")
    assert gui.has_stale_products(tmp_path) is True


def test_summarize_text_includes_manual_plan():
    """★半自动协作★ 失败摘要要带「需要人工介入」与前 3 步（弹窗不能长到没人读）。"""
    man = {
        "manifest_version": 1,
        "engine": "KiriKiri",
        "counts": {"final": {"total": 0}},
        "reconcile": {"method": "no-index-available", "diff": None,
                      "expected": None, "actual": 0},
        "verify": {"status": "skipped"},
        "error": "extract-failed",
        "manual": {
            "code": "kirikiri-encrypted",
            "summary": "xp3 自动解不开",
            "steps": ["第一步", "第二步", "第三步", "第四步"],
            "then": 'orchestrator.exe "g" --reuse-raw "r"',
        },
    }

    text = gui.summarize_text(1, man)

    assert "需要人工介入：xp3 自动解不开" in text
    assert "第一步" in text and "第三步" in text
    assert "第四步" not in text, "只显示前 3 步"
    assert "还有 1 步" in text
    assert "--reuse-raw" in text
