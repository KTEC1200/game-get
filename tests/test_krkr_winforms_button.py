# -*- coding: utf-8 -*-
"""2026-11-07 真机回归：WinForms 主窗口/按钮判据 + UIA 兜底 + 原始窗口诊断。

现场（教师催眠2，15:07 与 15:22 两轮，同样位置失败）：
  `injected pid / ui / rect=(812,282,2068,1422)` 注入成功、窗口可见，
  但 `主窗口=[]；Button 文本=[]；全部子控件=[]；诊断异常=None`，
  在「点 Full Unpack」前置检查处主动失败、交付 0 文件。

根因：`KrkrExtract.Lite.exe` 是 .NET WinForms（PE 里带 `System.Windows.Forms`），
主窗口类名形如 `WindowsForms10.Window.8.app...`、按钮类名也不是标准 `Button`；
旧实现两处都硬要求 `#32770` / `Button`，于是枚举恒为空。本文件锁住放宽后的判据、
点击后状态复核、UIA 兜底，以及「失败日志必须带上原始窗口清单」这条诊断纪律。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import krkr_auto_extract as kae  # noqa: E402

PID = 4242
UI_HWND = 8101
INFO_HWND = 8102
WF_CLASS = "WindowsForms10.Window.8.app.0.34f5582_r6_ad1"
WF_BUTTON = "WindowsForms10.BUTTON.app.0.34f5582_r6_ad1"
TITLE = "KrkrExtract(local 5.0.0.2) - built on 2020-01-01"


class WinFormsUser32:
    """只建模本次要用到的 Win32 调用；BM_GETCHECK 返回已勾选。"""

    def __init__(self, windows, children, *, check_state=kae.BST_CHECKED):
        self.windows = list(windows)          # (hwnd, 类名, 标题, pid)
        self.children = {k: list(v) for k, v in children.items()}
        self.sent: list[tuple[int, int, int, int]] = []
        self.cursor = None
        self.check_state = check_state
        self._cls = {h: c for h, c, _t, _p in self.windows}
        self._title = {h: t for h, _c, t, _p in self.windows}
        self._pid = {h: p for h, _c, _t, p in self.windows}
        for ctrls in self.children.values():
            for ch, cls, text in ctrls:
                self._cls[ch], self._title[ch], self._pid[ch] = cls, text, PID

    def EnumWindows(self, cb, lp):
        for h, _c, _t, _p in self.windows:
            cb(h, 0)
        return 1

    def EnumChildWindows(self, hwnd, cb, lp):
        for ch, _c, _t in self.children.get(hwnd, []):
            cb(ch, 0)
        return 1

    def GetClassNameW(self, hwnd, buf, n):
        buf.value = self._cls.get(hwnd, "Unknown")[: max(0, n - 1)]
        return len(buf.value)

    def GetWindowTextLengthW(self, hwnd):
        return len(self._title.get(hwnd, ""))

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = self._title.get(hwnd, "")[: max(0, n - 1)]
        return len(buf.value)

    def GetWindowThreadProcessId(self, hwnd, ptr):
        ptr._obj.value = self._pid.get(hwnd, 0)
        return self._pid.get(hwnd, 0)

    def SendMessageW(self, hwnd, msg, wp, lp):
        self.sent.append((hwnd, msg, wp, lp))
        return self.check_state if msg == kae.BM_GETCHECK else 1

    def SetCursorPos(self, x, y):
        self.cursor = (x, y)
        return 1

    def GetSystemMetrics(self, n):
        return 1920


@pytest.fixture
def fake_ui(monkeypatch):
    def install(windows, children, **kw):
        fake = WinFormsUser32(windows, children, **kw)
        monkeypatch.setattr(kae, "user32", fake)
        return fake
    return install


@pytest.fixture(autouse=True)
def _no_real_powershell(monkeypatch):
    """默认不碰真 PowerShell；测 UIA 分支的用例显式覆盖 _uia_ps。"""
    monkeypatch.setattr(kae, "_uia_ps", lambda *a, **kw: ([], None))


def _winforms_windows():
    return [(UI_HWND, WF_CLASS, TITLE, PID),
            (INFO_HWND, "#32770", "Information", PID)]


def test_main_dialog_accepts_winforms_class_and_rejects_modal(fake_ui):
    """★真因回归★ 旧实现要求 #32770，会把 WinForms 主窗口整个过滤掉。"""
    fake_ui(_winforms_windows(), {UI_HWND: [], INFO_HWND: []})
    assert kae._main_dialogs(PID) == [(UI_HWND, WF_CLASS, TITLE)]


def test_click_button_ex_clicks_winforms_button_and_verifies_check(fake_ui):
    fake = fake_ui(_winforms_windows(),
                   {UI_HWND: [(9001, WF_BUTTON, "&Full Unpack")]})
    ok, state = kae.click_button_ex(PID, "Full Unpack")
    assert ok is True
    assert "已勾选" in state
    assert (9001, kae.BM_CLICK, 0, 0) in fake.sent
    assert (9001, kae.BM_GETCHECK, 0, 0) in fake.sent
    assert kae.click_button(PID, "Full Unpack") is True


def test_button_candidates_prefers_button_class_over_static_label(fake_ui):
    """同名静态标签不能抢走点击；WinForms BUTTON 类名优先。"""
    fake = fake_ui(_winforms_windows(), {UI_HWND: [
        (9001, "WindowsForms10.STATIC.app.0", "Full Unpack"),
        (9002, WF_BUTTON, "Full Unpack"),
    ]})
    assert kae.click_button(PID, "Full Unpack") is True
    assert (9001, kae.BM_CLICK, 0, 0) not in fake.sent
    assert (9002, kae.BM_CLICK, 0, 0) in fake.sent


def test_describe_includes_raw_windows_and_control_classes(fake_ui):
    """失败日志必须能看到「窗口其实在、只是类名不同」，别再只打印空列表。"""
    fake_ui(_winforms_windows(),
            {UI_HWND: [(9001, WF_BUTTON, "&Full Unpack"), (9002, "Static", "Mode")]})
    diag = kae.describe_unpack_controls(PID)
    assert diag["error"] is None
    assert (UI_HWND, WF_CLASS, TITLE) in diag["raw_windows"]
    assert (INFO_HWND, "#32770", "Information") in diag["raw_windows"]
    assert diag["buttons"] == ["&Full Unpack"]
    assert diag["matched"] == ["&Full Unpack"]
    assert diag["global_title_matches"] == []


def test_uia_fallback_when_win32_finds_no_button(fake_ui, monkeypatch):
    fake_ui(_winforms_windows(), {UI_HWND: [(9001, "Static", "Mode")]})
    monkeypatch.setattr(kae, "uia_click_button",
                        lambda hwnd, label: (True, "InvokePattern 已触发（Button|Full Unpack）"))
    ok, state = kae.click_button_ex(PID, "Full Unpack")
    assert ok is True and state.startswith("UIA 兜底：")


def test_uia_click_button_invoke_and_toggle(monkeypatch):
    monkeypatch.setattr(kae, "_uia_ps", lambda *a, **kw: (
        ["SCR 1920 1080", "ITEM ControlType.Button|Full Unpack", "RECT 10 10 90 40", "INVOKED"],
        (10, 10, 90, 40)))
    ok, state = kae.uia_click_button(UI_HWND, "Full Unpack")
    assert ok is True and "InvokePattern" in state

    monkeypatch.setattr(kae, "_uia_ps", lambda *a, **kw: (
        ["SCR 1920 1080", "ITEM ControlType.CheckBox|Full Unpack",
         "RECT 10 10 90 40", "TOGGLED", "TOGGLESTATE On"], (10, 10, 90, 40)))
    ok, state = kae.uia_click_button(UI_HWND, "Full Unpack")
    assert ok is True and "TogglePattern" in state and "TOGGLESTATE On" in state


def test_uia_click_button_falls_back_to_mouse_when_no_pattern(fake_ui, monkeypatch):
    fake = fake_ui(_winforms_windows(), {})
    monkeypatch.setattr(kae, "mouse", lambda flags: None)
    monkeypatch.setattr(kae.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(kae, "_uia_ps", lambda *a, **kw: (
        ["SCR 1920 1080", "ITEM ControlType.CheckBox|Full Unpack",
         "RECT 100 100 200 140", "NO_PATTERN"], (100, 100, 200, 140)))
    ok, state = kae.uia_click_button(UI_HWND, "Full Unpack")
    assert ok is True and "鼠标点击" in state
    assert fake.cursor == (150, 120)


def test_uia_click_button_reports_controls_when_item_missing(monkeypatch):
    monkeypatch.setattr(kae, "_uia_ps", lambda *a, **kw: (
        ["SCR 1920 1080", "NOITEM",
         "CTRL ControlType.Button|Decompile Script",
         "CTRL ControlType.CheckBox|Text Decryption"], None))
    ok, state = kae.uia_click_button(UI_HWND, "Full Unpack")
    assert ok is False
    assert "可见控件" in state and "Text Decryption" in state
