# -*- coding: utf-8 -*-
"""Full Unpack 前置条件 + 日志中文编码的替身测试（2026-11-06 第二次实跑）。

现场证据：`WARNING: ??? 'Full Unpack' ?????` —— 按钮没点上，旧代码只警告一声
就继续拖 11 个 xp3，产物会缺图/缺音频而完成判定照样「通过」。同时中文日志被
`ascii/replace` 打成问号，真实报错读不出来。

这里用 FakeUser32 把 Win32 窗口/子控件枚举建模成纯数据，锁住四件事：
  1. `click_button` 的标签归一化（& 助记符、大小写、尾随空格）与「遍历全部主窗口」；
  2. `describe_unpack_controls` 能区分「按钮枚举失败」与「BM_CLICK 没生效」；
  3. main 把「没点上 Full Unpack」当成**明确失败前置条件**，绝不拖包；
  4. 日志 stdout / 文件都保留中文，编码异常时也不把链路打断。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import krkr_auto_extract as kae  # noqa: E402

UI_HWND = 1001
DLG2_HWND = 1002
INFO_HWND = 1003
EXPLORER_HWND = 3003
PID = 111
BM_CLICK = 0x00F5
RECT = (100, 100, 500, 400)


class DialogUser32:
    """建模 KrkrExtract 进程的顶层窗口与子控件。

    windows: [(hwnd, 类名, 标题, pid)]
    children: {hwnd: [(child_hwnd, 类名, 文本)]}
    另外提供 main 里直接调用的 GetWindowRect / WindowFromPoint / SetForegroundWindow，
    这样 main 的替身测试不需要第二套 fake。
    """

    def __init__(self, windows, children, *, send_raises=False):
        self.windows = list(windows)
        self.children = {k: list(v) for k, v in children.items()}
        self.send_raises = send_raises
        self.sent: list[tuple[int, int, int, int]] = []
        self.classes: dict[int, str] = {}
        self.titles: dict[int, str] = {}
        self.pids: dict[int, int] = {}
        for hwnd, cls, title, pid in self.windows:
            self.classes[hwnd] = cls
            self.titles[hwnd] = title
            self.pids[hwnd] = pid
        for controls in self.children.values():
            for ch, cls, text in controls:
                self.classes[ch] = cls
                self.titles[ch] = text
                self.pids[ch] = PID
        self.classes[EXPLORER_HWND] = "CabinetWClass"
        self.titles[EXPLORER_HWND] = "auto"

    # --- 枚举 ---
    def EnumWindows(self, cb, lp):
        for hwnd, _cls, _title, _pid in self.windows:
            if not cb(hwnd, 0):
                break
        return 1

    def EnumChildWindows(self, hwnd, cb, lp):
        for ch, _cls, _text in self.children.get(hwnd, []):
            if not cb(ch, 0):
                break
        return 1

    # --- 窗口信息 ---
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

    # --- 点击 ---
    def SendMessageW(self, hwnd, msg, wparam, lparam):
        if self.send_raises:
            raise OSError("BM_CLICK 目标窗口已无响应")
        self.sent.append((hwnd, msg, wparam, lparam))
        return 1

    # --- main 直接调用的其它 Win32 ---
    def GetWindowRect(self, hwnd, ptr):
        rc = ptr._obj
        rc.left, rc.top, rc.right, rc.bottom = RECT
        return 1

    def WindowFromPoint(self, pt):
        return EXPLORER_HWND

    def SetForegroundWindow(self, hwnd):
        return 1


@pytest.fixture
def dialogs(monkeypatch):
    """安装一个 fake user32，返回它，便于断言 BM_CLICK 记录。"""
    def install(windows, children, **kw):
        fake = DialogUser32(windows, children, **kw)
        monkeypatch.setattr(kae, "user32", fake)
        return fake
    return install


def _main_windows():
    return [(UI_HWND, "#32770", "KrkrExtract(local 5.0.0.2) - built on ...", PID)]


# ---------------------------------------------------------------------------
# 1) click_button：标签归一化 / 遍历全部主窗口 / 不碰 Information 弹窗
# ---------------------------------------------------------------------------

def test_norm_button_label_strips_ampersand_case_and_space():
    assert kae._norm_button_label("&Full Unpack ") == "full unpack"
    assert kae._norm_button_label("FULL UNPACK") == "full unpack"
    assert kae._norm_button_label("  Full &Unpack\t") == "full unpack"
    assert kae._norm_button_label("") == ""


def test_click_button_matches_ampersand_label(dialogs):
    """现场最可能的原因之一：GetWindowTextW 拿到的是带 & 的原串。"""
    fake = dialogs(_main_windows(), {UI_HWND: [(2001, "Button", "&Full Unpack")]})

    assert kae.click_button(PID, "Full Unpack") is True
    assert fake.sent == [(2001, BM_CLICK, 0, 0)]


def test_click_button_checks_every_main_dialog(dialogs):
    """旧实现在第一个主窗口就 return bool(hit)，第二个窗口的按钮永远点不到。"""
    windows = _main_windows() + [
        (DLG2_HWND, "#32770", "KrkrExtract(local 5.0.0.2) - second", PID),
    ]
    children = {
        UI_HWND: [(2101, "Button", "Decompile Script")],
        DLG2_HWND: [(2201, "Button", "  full UNPACK  ")],
    }
    fake = dialogs(windows, children)

    assert kae.click_button(PID, "Full Unpack") is True
    assert fake.sent == [(2201, BM_CLICK, 0, 0)]


def test_click_button_ignores_non_main_dialogs(dialogs):
    """Information 提示框里同名按钮不算数：绝不能把模态框当主界面点。"""
    windows = _main_windows() + [(INFO_HWND, "#32770", "Information", PID)]
    children = {
        UI_HWND: [(2101, "Button", "OK")],
        INFO_HWND: [(2301, "Button", "Full Unpack")],
    }
    fake = dialogs(windows, children)

    assert kae.click_button(PID, "Full Unpack") is False
    assert fake.sent == []


def test_click_button_returns_false_on_send_failure(dialogs):
    """BM_CLICK 抛异常时返回 False，但按钮本身是枚举得到的（诊断要能区分）。"""
    fake = dialogs(_main_windows(),
                   {UI_HWND: [(2001, "Button", "&Full Unpack")]},
                   send_raises=True)

    assert kae.click_button(PID, "Full Unpack") is False
    assert kae.describe_unpack_controls(PID)["matched"] == ["&Full Unpack"]


# ---------------------------------------------------------------------------
# 2) describe_unpack_controls：把「枚举失败」与「点击失败」分开
# ---------------------------------------------------------------------------

def test_describe_unpack_controls_reports_enumeration_failure(dialogs):
    dialogs(_main_windows(), {UI_HWND: [
        (2001, "Button", "Decompile Script"),
        (2002, "Static", "Mode"),
    ]})

    diag = kae.describe_unpack_controls(PID)

    assert diag["error"] is None
    assert diag["matched"] == []
    assert diag["buttons"] == ["Decompile Script"]
    assert ("Static", "Mode") in diag["controls"]
    assert diag["dialogs"] == [(UI_HWND, _main_windows()[0][2])]


def test_describe_unpack_controls_marks_matched_button(dialogs):
    dialogs(_main_windows(), {UI_HWND: [(2001, "Button", "&Full Unpack")]})

    diag = kae.describe_unpack_controls(PID)

    assert diag["matched"] == ["&Full Unpack"]
    assert diag["error"] is None


def test_describe_unpack_controls_never_raises(monkeypatch):
    """诊断本身失败也不能把失败路径再炸一次（user32 缺方法时如实记 error）。"""
    class Bare:
        pass

    monkeypatch.setattr(kae, "user32", Bare())

    diag = kae.describe_unpack_controls(PID)

    assert diag["matched"] == []
    assert diag["error"] is not None


# ---------------------------------------------------------------------------
# 3) main：没点上 Full Unpack = 明确失败前置条件，绝不拖包
# ---------------------------------------------------------------------------

def _prepare_main(tmp_path, monkeypatch, *, click_ok: bool, allow_no: bool,
                  children=None):
    """把 main 里所有真实桌面/进程调用替换成替身，只留 Full Unpack 判定这条路径。"""
    stage = tmp_path / "stage" / "auto"
    stage.mkdir(parents=True)
    (stage / "game.exe").write_bytes(b"fake")
    (stage / "data.xp3").write_bytes(b"a")
    game = tmp_path / "game"
    game.mkdir()

    fake = DialogUser32(
        _main_windows(),
        children or {UI_HWND: [(2001, "Button", "Decompile Script")]},
    )
    monkeypatch.setattr(kae, "user32", fake)
    monkeypatch.setattr(kae, "STAGE_ROOT", str(stage.parent))
    monkeypatch.setattr(kae, "ALLOW_NO_FULL_UNPACK", allow_no)
    logs: list[str] = []
    monkeypatch.setattr(kae, "log", lambda msg: logs.append(str(msg)))
    monkeypatch.setattr(kae, "pids_by_exe_path", lambda target: [123])
    monkeypatch.setattr(kae.subprocess, "Popen", lambda *a, **kw: None)
    monkeypatch.setattr(kae.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(kae.time, "sleep", lambda *a: None)
    monkeypatch.setattr(kae, "wait_ui_window", lambda pid: (UI_HWND, 0.0))
    monkeypatch.setattr(kae, "dismiss_dialogs", lambda pid: [])
    monkeypatch.setattr(kae, "click_button", lambda pid, label: click_ok)
    monkeypatch.setattr(kae, "close_all_explorers", lambda hint: None)
    monkeypatch.setattr(kae, "find_explorer_by_title_hint", lambda hint: EXPLORER_HWND)
    monkeypatch.setattr(kae, "uia_item_rect", lambda hwnd, name: (10, 10, 50, 50))
    monkeypatch.setattr(kae, "find_drop_point_ex",
                        lambda hwnd, attempts=None: (UI_HWND, (106, 106)))
    monkeypatch.setattr(kae, "ensure_drop_point", lambda hwnd, point: point)
    monkeypatch.setattr(kae, "wait_task_done", lambda outdir, ui: (2, {}, 0))
    calls: dict = {"drag": []}
    monkeypatch.setattr(kae, "drag", lambda *a: calls["drag"].append(a))
    return game, logs, calls


def test_main_aborts_before_dragging_when_full_unpack_missing(tmp_path, monkeypatch):
    """★核心★ 没点上 Full Unpack 必须硬失败：带病拖包会交付缺图/缺音频的半份产物。"""
    game, logs, calls = _prepare_main(tmp_path, monkeypatch,
                                      click_ok=False, allow_no=False)

    with pytest.raises(RuntimeError) as exc:
        kae.main([str(game), "--reuse-stage", "--keep-stage"])

    msg = str(exc.value)
    assert "没点上 'Full Unpack'" in msg
    assert "按钮枚举失败" in msg
    assert "半份产物" in msg
    assert "KRKR_ALLOW_NO_FULL_UNPACK=1" in msg, "要给可操作的降级开关，不能把用户锁死"
    assert calls["drag"] == [], "绝不能带病继续拖包"
    assert any("ERROR:" in line for line in logs)


def test_main_names_click_failure_when_button_was_enumerated(tmp_path, monkeypatch):
    """按钮枚举到了但没点上：报错要说 BM_CLICK，不能说「找不到按钮」。"""
    game, _logs, calls = _prepare_main(
        tmp_path, monkeypatch, click_ok=False, allow_no=False,
        children={UI_HWND: [(2001, "Button", "&Full Unpack")]})

    with pytest.raises(RuntimeError) as exc:
        kae.main([str(game), "--reuse-stage", "--keep-stage"])

    assert "BM_CLICK 没生效" in str(exc.value)
    assert calls["drag"] == []


def test_main_guard_can_be_explicitly_overridden(tmp_path, monkeypatch):
    """降级必须是显式 opt-in，且日志明确写出风险（默认仍然硬失败）。"""
    game, logs, calls = _prepare_main(tmp_path, monkeypatch,
                                      click_ok=False, allow_no=True)

    assert kae.main([str(game), "--reuse-stage", "--keep-stage"]) == 0
    assert len(calls["drag"]) == 1
    assert any("风险自负" in line for line in logs)


def test_main_proceeds_when_full_unpack_clicked(tmp_path, monkeypatch):
    game, logs, calls = _prepare_main(tmp_path, monkeypatch,
                                      click_ok=True, allow_no=False)

    assert kae.main([str(game), "--reuse-stage", "--keep-stage"]) == 0
    assert len(calls["drag"]) == 1
    assert any("Full Unpack 已开启" in line for line in logs)


# ---------------------------------------------------------------------------
# 4) 日志编码：中文必须可读（现场所有中文都变成了 ?）
# ---------------------------------------------------------------------------

def test_log_keeps_chinese_in_stdout_and_file(tmp_path, monkeypatch, capsys):
    """orchestrator 把这段 stdout 收进 _work/extract.log —— 中文变问号就没法排障。"""
    monkeypatch.setattr(kae, "LOG", str(tmp_path / "krkr_auto_extract.log"))
    monkeypatch.setattr(kae, "STAGE_ROOT", str(tmp_path))

    kae.log("拖拽落点被遮挡：重试 6 轮仍未在 KrkrExtract 窗口内找到可见空白点。")

    out = capsys.readouterr().out
    assert "拖拽落点被遮挡" in out
    assert "??????" not in out
    assert "重试 6 轮" in out
    assert "拖拽落点被遮挡" in (tmp_path / "krkr_auto_extract.log").read_text(encoding="utf-8")


def test_print_log_survives_unencodable_stdout(monkeypatch):
    """控制台编码写不了中文时降级到 ASCII 安全串，但绝不抛异常打断解包链。"""
    class BadStdout:
        def write(self, _s):
            raise UnicodeEncodeError("ascii", "中", 0, 1, "not representable")

        def flush(self):
            return None

    monkeypatch.setattr(sys, "stdout", BadStdout())

    kae._print_log("拖拽落点被遮挡")     # 不抛就是达标
