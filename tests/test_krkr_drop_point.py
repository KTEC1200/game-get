# -*- coding: utf-8 -*-
"""KrkrExtract 拖拽落点的遮挡恢复（2026-11-06 加固）。

真机 GUI 分支没法在 CI 里跑：这里用 FakeUser32 顶替 user32，把「窗口 Z 序」
抽象成 WindowFromPoint 的返回值，锁住四件事：
  1. 前台锁下 SetForegroundWindow 被拒，TOPMOST→NOTOPMOST 连招仍能把窗口抬到最前；
  2. Chrome 压住窗口时能恢复，压得死时报错要能说出是谁挡的、该怎么办；
  3. 只接受主窗口空白背景，子控件不作落点；
  4. Explorer 前置后复核终点，且 main 里每个包都重新校验（旧代码 11 包共用一个坐标）。
"""
from ctypes import wintypes

import pytest

import krkr_auto_extract as kae

UI_HWND = 1001
CHROME_HWND = 2002
EXPLORER_HWND = 3003
CHILD_HWND = 4004

RECT = (100, 100, 500, 400)          # left, top, right, bottom（物理像素）
CLASSES = {
    UI_HWND: "#32770",
    CHROME_HWND: "Chrome_RenderWidgetHostHWND",
    EXPLORER_HWND: "CabinetWClass",
    CHILD_HWND: "Button",
}
TITLES = {
    UI_HWND: "KrkrExtract(local 5.0.0.2)",
    CHROME_HWND: "某网页 - Google Chrome",
    EXPLORER_HWND: "auto",
    CHILD_HWND: "Full Unpack",
}
PIDS = {UI_HWND: 111, CHROME_HWND: 222, EXPLORER_HWND: 333, CHILD_HWND: 111}


class FakeUser32:
    """只实现抬窗 / 落点链路用到的调用。

    overlay:
      - None               整块 KrkrExtract 可见
      - hwnd               整块被这个窗口盖住
      - callable(x, y)     按坐标决定（模拟子控件、Explorer 盖住局部）
    lift_works=False 表示连 TOPMOST 都压不过遮挡者（对方也是置顶窗口）。
    foreground_lock=True 模拟 Windows 前台锁：SetForegroundWindow 静默失败。
    """

    def __init__(self, overlay=None, lift_works=True, foreground_lock=False):
        self.overlay = overlay
        self.lift_works = lift_works
        self.foreground_lock = foreground_lock
        self.setpos_calls = []
        self.show_calls = []
        self.foreground = CHROME_HWND if foreground_lock else None
        self._raised = overlay is None

    # --- Z 序 ---
    def ShowWindow(self, hwnd, cmd):
        self.show_calls.append((hwnd, cmd))
        return 1

    def SetWindowPos(self, hwnd, after, x, y, cx, cy, flags):
        self.setpos_calls.append((hwnd, after))
        if self.lift_works and after == kae.HWND_TOPMOST:
            self._raised = True
        return 1

    def BringWindowToTop(self, hwnd):
        return 1

    def SetForegroundWindow(self, hwnd):
        if not self.foreground_lock:
            self.foreground = hwnd
            return 1
        return 0

    def GetForegroundWindow(self):
        return self.foreground

    # --- 几何 / 命中 ---
    def GetWindowRect(self, hwnd, ptr):
        rc = ptr._obj
        rc.left, rc.top, rc.right, rc.bottom = RECT
        return 1

    def WindowFromPoint(self, pt):
        if callable(self.overlay):
            return self.overlay(pt.x, pt.y)
        if self.overlay is None or self._raised:
            return UI_HWND
        return self.overlay

    # --- 窗口信息（describe_window 用）---
    def GetClassNameW(self, hwnd, buf, n):
        buf.value = CLASSES.get(hwnd, "Unknown")[: max(0, n - 1)]
        return len(buf.value)

    def GetWindowTextLengthW(self, hwnd):
        return len(TITLES.get(hwnd, ""))

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = TITLES.get(hwnd, "")[: max(0, n - 1)]
        return len(buf.value)

    def GetWindowThreadProcessId(self, hwnd, ptr):
        ptr._obj.value = PIDS.get(hwnd, 0)
        return PIDS.get(hwnd, 0)


@pytest.fixture
def fake_ui(monkeypatch):
    def install(**kwargs):
        fake = FakeUser32(**kwargs)
        monkeypatch.setattr(kae, "user32", fake)
        monkeypatch.setattr(kae.time, "sleep", lambda *a: None)
        return fake
    return install


def _rect():
    rc = wintypes.RECT()
    rc.left, rc.top, rc.right, rc.bottom = RECT
    return rc


def _inside(point):
    x, y = point
    return RECT[0] + 6 <= x < RECT[2] - 6 and RECT[1] + 6 <= y < RECT[3] - 6


def test_topmost_lift_beats_foreground_lock(fake_ui):
    """前台锁让 SetForegroundWindow 返回 0，但置顶连招照样把窗口抬到最前。"""
    fake = fake_ui(overlay=CHROME_HWND, foreground_lock=True)

    assert kae.raise_ui_window(UI_HWND) is False, "前台锁下本就不该拿到焦点"
    assert [after for _, after in fake.setpos_calls] == [
        kae.HWND_TOPMOST, kae.HWND_NOTOPMOST,
    ], "必须 TOPMOST→NOTOPMOST 成对，否则窗口被永久置顶"
    assert _inside(kae.find_drop_point(UI_HWND, attempts=1))


def test_find_drop_point_recovers_from_chrome_overlay(fake_ui):
    """教师催眠2 第四轮现场：Chrome 压住整块窗口。"""
    fake = fake_ui(overlay=CHROME_HWND)

    point = kae.find_drop_point(UI_HWND, attempts=3)

    assert _inside(point)
    assert fake.setpos_calls, "必须先抬窗再扫，只重试不抬窗永远找不到落点"


def test_find_drop_point_error_names_the_blocker(fake_ui):
    """抬不动时不能只丢一句 assert：要说出谁挡着、以及怎么处置。"""
    fake_ui(overlay=CHROME_HWND, lift_works=False)

    with pytest.raises(RuntimeError) as exc:
        kae.find_drop_point(UI_HWND, attempts=2)

    msg = str(exc.value)
    assert "重试 2 轮" in msg
    assert "Chrome_RenderWidgetHostHWND" in msg
    assert "关闭/最小化" in msg
    assert "no blank spot" not in msg


def test_scan_drop_point_skips_child_controls(fake_ui):
    """按钮 / Static 是子窗口，不接受 WM_DROPFILES，不能当落点。"""
    def overlay(x, y):
        return CHILD_HWND if (x, y) == (RECT[0] + 6, RECT[1] + 6) else UI_HWND

    fake_ui(overlay=overlay)
    point, blockers = kae.scan_drop_point(UI_HWND, _rect())

    assert point != (RECT[0] + 6, RECT[1] + 6)
    assert _inside(point)
    assert any("Button" in k for k in blockers)


def test_ensure_drop_point_refreshes_when_explorer_covers_it(fake_ui):
    """Explorer 被前置后盖住原落点：换个仍可见的空白点，且不能重新抬窗。"""
    original = (RECT[0] + 6, RECT[1] + 6)

    def overlay(x, y):
        return EXPLORER_HWND if (x, y) == original else UI_HWND

    fake = fake_ui(overlay=overlay)

    point = kae.ensure_drop_point(UI_HWND, original)

    assert point != original and _inside(point)
    assert fake.setpos_calls == [], "复核阶段绝不能抬窗，否则 Explorer 起点会被压到后面"


def test_ensure_drop_point_raises_when_fully_covered(fake_ui):
    """起点终点无法同时可见时明确报错，而不是把包拖到 Explorer 上静默丢掉。"""
    fake_ui(overlay=EXPLORER_HWND, lift_works=False)

    with pytest.raises(RuntimeError) as exc:
        kae.ensure_drop_point(UI_HWND, (RECT[0] + 6, RECT[1] + 6))

    assert "资源管理器" in str(exc.value)
    assert "缩小" in str(exc.value)


def test_main_revalidates_drop_point_for_every_archive(tmp_path, monkeypatch, fake_ui):
    """11 个包共用一次落点坐标是旧代码的隐性 bug：每包都要重新抬窗 + 复核。"""
    stage = tmp_path / "stage" / "auto"
    stage.mkdir(parents=True)
    (stage / "game.exe").write_bytes(b"fake")
    (stage / "data.xp3").write_bytes(b"a")
    (stage / "image00.xp3").write_bytes(b"b")
    game = tmp_path / "game"
    game.mkdir()

    # 起点 (30,30) 落在 Explorer 上，终点落在 KrkrExtract 上
    def overlay(x, y):
        return EXPLORER_HWND if (x, y) == (30, 30) else UI_HWND

    fake_ui(overlay=overlay)

    calls = {"find": 0, "ensure": 0, "drag": []}

    def fake_find(hwnd, attempts=None):
        calls["find"] += 1
        return (106, 106)

    def fake_ensure(hwnd, point):
        calls["ensure"] += 1
        return point

    monkeypatch.setattr(kae, "STAGE_ROOT", str(stage.parent))
    monkeypatch.setattr(kae, "log", lambda *a: None)
    monkeypatch.setattr(kae, "pids_by_exe_path", lambda target: [123])
    monkeypatch.setattr(kae.subprocess, "Popen", lambda *a, **kw: None)
    monkeypatch.setattr(kae.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(kae.time, "sleep", lambda *a: None)
    monkeypatch.setattr(kae, "WINDOW_WAIT", 0)
    monkeypatch.setattr(kae, "wait_ui_window", lambda pid: (UI_HWND, 0.0))
    monkeypatch.setattr(kae, "dismiss_dialogs", lambda pid: [])
    monkeypatch.setattr(kae, "click_button", lambda pid, label: True)
    monkeypatch.setattr(kae, "close_all_explorers", lambda hint: None)
    monkeypatch.setattr(kae, "find_explorer_by_title_hint", lambda hint: EXPLORER_HWND)
    monkeypatch.setattr(kae, "uia_item_rect", lambda hwnd, name: (10, 10, 50, 50))
    monkeypatch.setattr(kae, "wait_task_done", lambda outdir, ui: (2, {}, 0))
    monkeypatch.setattr(kae, "find_drop_point", fake_find)
    monkeypatch.setattr(kae, "ensure_drop_point", fake_ensure)
    monkeypatch.setattr(kae, "drag", lambda *a: calls["drag"].append(a))

    assert kae.main([str(game), "--reuse-stage", "--keep-stage"]) == 0

    assert len(calls["drag"]) == 2, "两个 xp3 都要拖"
    assert calls["find"] == 3, "循环外早失败检查 1 次 + 每包 1 次"
    assert calls["ensure"] == 2, "每包拖拽前都要复核终点"
