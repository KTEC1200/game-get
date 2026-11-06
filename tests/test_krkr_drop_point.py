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
REBUILT_HWND = 5005          # 窗口重建后的新主窗口句柄（自恢复测试用）

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
      - hwnd               整块被这个窗口盖住（0 = WindowFromPoint 返回 0）
      - callable(x, y)     按坐标决定（模拟子控件、Explorer 盖住局部）
    lift_works=False 表示连 TOPMOST 都压不过遮挡者（对方也是置顶窗口）。
    foreground_lock=True 模拟 Windows 前台锁：SetForegroundWindow 静默失败。

    2026-11-06 第二次实跑补的诊断维度（全部可选，缺省时行为与旧替身一致）：
      rect             tuple 或 {hwnd: tuple}，模拟最小化/句柄失效后的退化矩形；
      window_alive     IsWindow 的返回值（bool 或 callable(hwnd)）；
      window_visible   IsWindowVisible 的返回值；
      ancestors        {hwnd: GA_ROOT 结果}，用于把子控件认出来；
      parents          {hwnd: 父窗口句柄}，GetAncestor 不可用时的回退；
      enum_titles      {hwnd: 标题}，给了才模拟 EnumWindows（重绑主窗口）。
    """

    def __init__(self, overlay=None, lift_works=True, foreground_lock=False,
                 rect=RECT, window_alive=True, window_visible=True,
                 ancestors=None, parents=None, enum_titles=None):
        self.overlay = overlay
        self.lift_works = lift_works
        self.foreground_lock = foreground_lock
        self.setpos_calls = []
        self.show_calls = []
        self.foreground = CHROME_HWND if foreground_lock else None
        self._raised = overlay is None
        self.rect = rect
        self.window_alive = window_alive
        self.window_visible = window_visible
        self.ancestors = dict(ancestors or {})
        self.parents = dict(parents or {})
        self.enum_titles = enum_titles
        self.titles = dict(TITLES)
        self.classes = dict(CLASSES)
        self.pids = dict(PIDS)
        if enum_titles:
            self.titles.update(enum_titles)

    @staticmethod
    def _value(value, hwnd):
        return bool(value(hwnd)) if callable(value) else bool(value)

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

    # --- 窗口存活 / 层级 ---
    def IsWindow(self, hwnd):
        return self._value(self.window_alive, hwnd)

    def IsWindowVisible(self, hwnd):
        return self._value(self.window_visible, hwnd)

    def GetAncestor(self, hwnd, flag):
        return self.ancestors.get(hwnd, hwnd)

    def GetParent(self, hwnd):
        return self.parents.get(hwnd, 0)

    def EnumWindows(self, cb, lp):
        if self.enum_titles is None:
            return 1                       # 没实现枚举 = 重绑不到新窗口
        for hwnd in self.enum_titles:
            if not cb(hwnd, 0):
                break
        return 1

    # --- 几何 / 命中 ---
    def GetWindowRect(self, hwnd, ptr):
        rc = ptr._obj
        box = self.rect.get(hwnd, RECT) if isinstance(self.rect, dict) else self.rect
        rc.left, rc.top, rc.right, rc.bottom = box
        return 1

    def WindowFromPoint(self, pt):
        if callable(self.overlay):
            return self.overlay(pt.x, pt.y)
        if self.overlay is None or self._raised:
            return UI_HWND
        return self.overlay

    # --- 窗口信息（describe_window 用）---
    def GetClassNameW(self, hwnd, buf, n):
        buf.value = self.classes.get(hwnd, "Unknown")[: max(0, n - 1)]
        return len(buf.value)

    def GetWindowTextLengthW(self, hwnd):
        return len(self.titles.get(hwnd, ""))

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = self.titles.get(hwnd, "")[: max(0, n - 1)]
        return len(buf.value)

    def GetWindowThreadProcessId(self, hwnd, ptr):
        ptr._obj.value = self.pids.get(hwnd, 0)
        return self.pids.get(hwnd, 0)


@pytest.fixture
def fake_ui(monkeypatch):
    def install(**kwargs):
        fake = FakeUser32(**kwargs)
        monkeypatch.setattr(kae, "user32", fake)
        monkeypatch.setattr(kae.time, "sleep", lambda *a: None)
        # 自恢复分支会写诊断日志；测试不许往仓库里的 _krkr_stage 落文件
        monkeypatch.setattr(kae, "log", lambda *a, **kw: None)
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

    calls = {"find": 0, "ensure": 0, "drag": [], "ensure_hwnd": [], "wait_hwnd": []}

    def fake_find(hwnd, attempts=None):
        calls["find"] += 1
        return (REBUILT_HWND, (106, 106))   # 模拟落点阶段重绑到了新主窗口

    def fake_ensure(hwnd, point):
        calls["ensure"] += 1
        calls["ensure_hwnd"].append(hwnd)
        return point

    def fake_wait(outdir, ui):
        calls["wait_hwnd"].append(ui)
        return (2, {}, 0)

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
    monkeypatch.setattr(kae, "wait_task_done", fake_wait)
    monkeypatch.setattr(kae, "find_drop_point_ex", fake_find)
    monkeypatch.setattr(kae, "ensure_drop_point", fake_ensure)
    monkeypatch.setattr(kae, "drag", lambda *a: calls["drag"].append(a))

    assert kae.main([str(game), "--reuse-stage", "--keep-stage"]) == 0

    assert len(calls["drag"]) == 2, "两个 xp3 都要拖"
    assert calls["find"] == 3, "循环外早失败检查 1 次 + 每包 1 次"
    assert calls["ensure"] == 2, "每包拖拽前都要复核终点"
    # 重绑后的新句柄必须一路传下去：旧句柄会让 ensure / wait_task_done 全判失败
    assert calls["ensure_hwnd"] == [REBUILT_HWND, REBUILT_HWND]
    assert calls["wait_hwnd"] == [REBUILT_HWND, REBUILT_HWND]


# ---------------------------------------------------------------------------
# 2026-11-06 第二次实跑：报错必须如实反映真实情况
#
# 现场：`find_drop_point` 6 轮全失败，但错误里写「(无可见遮挡窗口)」——
# blockers 统计为空 = 扫描循环一次都没跑（rect 退化 / WindowFromPoint 返回 0 /
# 采样点全是子控件），却被统一翻译成「没人挡着」。以下用例逐一把这三种情况拆开。
# ---------------------------------------------------------------------------

def test_no_window_hits_are_not_reported_as_no_blocker(fake_ui):
    """WindowFromPoint 全返回 0：是「窗口不可见」，不是「没有遮挡」。"""
    fake_ui(overlay=lambda x, y: 0)

    point, blockers = kae.scan_drop_point(UI_HWND, _rect())
    assert point is None
    assert any("WindowFromPoint 返回 0" in k for k in blockers)

    with pytest.raises(RuntimeError) as exc:
        kae.find_drop_point(UI_HWND, attempts=2)
    msg = str(exc.value)
    assert "窗口不可见" in msg
    assert "重试 2 轮" in msg
    assert "(无可见遮挡窗口)" not in msg, "空 blockers 不许再被翻译成「没人挡」"


def test_all_child_controls_are_reported_as_such(fake_ui):
    """采样点全是子控件：明确说「全是子控件」，不能说「被遮挡」或「没人挡」。"""
    fake_ui(overlay=lambda x, y: CHILD_HWND,
            ancestors={CHILD_HWND: UI_HWND})       # GetAncestor(GA_ROOT) == 主窗口

    point, blockers = kae.scan_drop_point(UI_HWND, _rect())
    assert point is None, "子控件不作落点：口径不放宽"
    assert any("子控件" in k and "Button" in k for k in blockers)

    with pytest.raises(RuntimeError) as exc:
        kae.find_drop_point(UI_HWND, attempts=1)
    msg = str(exc.value)
    assert "全是子控件" in msg
    assert "(无可见遮挡窗口)" not in msg


def test_degenerate_rect_reports_window_invisible(fake_ui):
    """最小化/窗口关闭导致 rect 退化（扫描循环空转）——就是现场那一句误判。"""
    fake_ui(rect=(-32000, -32000, -31840, -31976))

    with pytest.raises(RuntimeError) as exc:
        kae.find_drop_point(UI_HWND, attempts=1)
    msg = str(exc.value)
    assert "不可见" in msg
    assert "rect" in msg
    assert "(无可见遮挡窗口)" not in msg


def test_real_blocker_still_named_and_not_relaxed(fake_ui):
    """真被别的窗口压住时仍要点名；且子控件依旧不能当落点。"""
    fake_ui(overlay=CHROME_HWND, lift_works=False)
    with pytest.raises(RuntimeError) as exc:
        kae.find_drop_point(UI_HWND, attempts=2)
    msg = str(exc.value)
    assert "Chrome_RenderWidgetHostHWND" in msg
    assert "关闭/最小化" in msg
    assert "采样" in msg, "报错要带分类统计，方便真机定位"


def test_find_drop_point_ex_rebinds_rebuilt_window(fake_ui):
    """旧句柄失效 + rect 退化 → 重新枚举主窗口并刷新 rect，返回新句柄与落点。"""
    fake = fake_ui(
        overlay=lambda x, y: REBUILT_HWND,
        rect={UI_HWND: (-32000, -32000, -31840, -31976), REBUILT_HWND: RECT},
        window_alive=lambda h: h != UI_HWND,
        enum_titles={REBUILT_HWND: "KrkrExtract(local 5.0.0.2) - rebuilt"},
    )

    hwnd, point = kae.find_drop_point_ex(UI_HWND, attempts=1)

    assert hwnd == REBUILT_HWND, "必须把新句柄交还调用方，否则后续比较全失效"
    assert _inside(point)
    assert fake.setpos_calls, "重绑之后仍要抬窗"


def test_ensure_drop_point_names_dead_window(fake_ui):
    """拖拽前主窗口已关闭：明确说窗口不可见，而不是「资源管理器盖住了」。"""
    fake_ui(window_alive=False)

    with pytest.raises(RuntimeError) as exc:
        kae.ensure_drop_point(UI_HWND, (RECT[0] + 6, RECT[1] + 6))
    assert "已关闭/不可见" in str(exc.value)
