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
