#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""krkr 链路的**进程身份**判定（批次 C5，2026-11-03）。

为什么要专门一套测试：旧实现按进程名 `game.exe` 找目标，然后 `taskkill /F /PID`。
这在一个装了十几个 galgame 的机器上等于「随机杀别人的游戏进程」——名字根本不是身份。
现在只认「镜像绝对路径与 stage 里那份一致」，而这条判据判错就是误杀/漏杀，
所以判据本身（`_same_exe_path`）与筛选逻辑（`pids_by_exe_path`）都必须被锁住。

纯逻辑测试：不枚举真进程、不开进程句柄（ctypes 那层用 monkeypatch 掉）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import krkr_auto_extract as kae  # noqa: E402


# ---------------------------------------------------------------------------
# _same_exe_path：Windows 路径语义
# ---------------------------------------------------------------------------

def test_same_exe_path_ignores_case():
    """★C5★ NTFS 大小写不敏感：同一个 exe 换个大小写写法还是同一个。"""
    assert kae._same_exe_path(r"D:\K\deepseek\_krkr_stage\auto\game.exe",
                              r"d:\k\DEEPSEEK\_krkr_stage\auto\GAME.EXE") is True


def test_same_exe_path_ignores_slash_style():
    """★C5★ 正斜杠与反斜杠混用（os.path 里两者等价）。"""
    assert kae._same_exe_path(r"D:\K\deepseek\_krkr_stage\auto\game.exe",
                              "D:/K/deepseek/_krkr_stage/auto/game.exe") is True


def test_same_exe_path_normalises_dot_segments():
    """★C5★ `..` / `.` 段要先归一化再比，否则同一路径换个写法就匹配不上（漏杀）。"""
    assert kae._same_exe_path(r"D:\K\deepseek\_krkr_stage\auto\game.exe",
                              r"D:\K\deepseek\_krkr_stage\auto\sub\..\game.exe") is True
    assert kae._same_exe_path(r"D:\K\deepseek\game.exe",
                              r"D:\K\deepseek\.\\game.exe") is True


def test_same_exe_path_rejects_different_paths():
    """★C5★ 同名不同目录**必须**判不等——这正是旧实现杀掉别人进程的原因。"""
    assert kae._same_exe_path(r"D:\K\deepseek\_krkr_stage\auto\game.exe",
                              r"D:\other\game\game.exe") is False
    assert kae._same_exe_path("", r"D:\x\game.exe") is False
    assert kae._same_exe_path(r"D:\x\game.exe", "") is False


# ---------------------------------------------------------------------------
# pids_by_exe_path：只按路径匹配，绝不按名字兜底
# ---------------------------------------------------------------------------

def test_pids_by_exe_path_filters_by_image_path(tmp_path, monkeypatch):
    """★C5★ 只返回镜像路径匹配的 pid；读不到路径的跳过；自己的 pid 排除。

    这台的进程表里可能有一堆 game.exe（别的 galgame、模拟器），它们**一个都不该**
    进返回值——返回值唯一的用途就是 taskkill。
    """
    want = str(tmp_path / "auto" / "game.exe")
    table = {
        100: want,                                    # 命中
        200: str(tmp_path / "other" / "game.exe"),    # 同名不同目录 → 不许命中
        300: None,                                    # 读不到路径 → 跳过，不猜
        400: want.upper(),                            # 同一路径的大写写法 → 命中
    }
    monkeypatch.setattr(kae, "_enum_pids", lambda: [100, 200, 300, 400, 999])
    monkeypatch.setattr(kae, "_process_image_path", lambda pid: table.get(pid, want))

    class FakeKernel32:
        @staticmethod
        def GetCurrentProcessId() -> int:
            return 999                                # 代表自己：即使路径相同也不杀

    monkeypatch.setattr(kae, "kernel32", FakeKernel32)

    assert kae.pids_by_exe_path(want) == [100, 400]


def test_pids_by_exe_path_returns_empty_when_nothing_matches(tmp_path, monkeypatch):
    """★C5★ 没有一个匹配时返回空列表（而不是退回「按名字找 game.exe」）。"""
    monkeypatch.setattr(kae, "_enum_pids", lambda: [11, 22])
    monkeypatch.setattr(kae, "_process_image_path",
                        lambda pid: r"D:\elsewhere\game.exe")

    class FakeKernel32:
        @staticmethod
        def GetCurrentProcessId() -> int:
            return 999

    monkeypatch.setattr(kae, "kernel32", FakeKernel32)

    assert kae.pids_by_exe_path(tmp_path / "auto" / "game.exe") == []


def test_pids_by_exe_path_survives_enumeration_failure(tmp_path, monkeypatch):
    """★C5★ 枚举本身失败（权限/系统状态异常）只记日志、返回空，不能炸掉整条链路。"""
    logs: list[str] = []
    monkeypatch.setattr(kae, "log", lambda msg: logs.append(str(msg)))

    def boom() -> list[int]:
        raise OSError("EnumProcesses 失败")

    monkeypatch.setattr(kae, "_enum_pids", boom)

    assert kae.pids_by_exe_path(tmp_path / "game.exe") == []
    assert any("枚举进程失败" in line for line in logs)


# ---------------------------------------------------------------------------
# 窗口收拾范围（2026-11-04）
# ---------------------------------------------------------------------------

def test_close_all_explorers_requires_hint():
    """★核心★ 不许无差别关资源管理器窗口 —— 用户可能正在拷文件，那是数据损失。

    hint 不设默认值就是护栏：想改回「全关」必须先改签名，这条测试会拦住。
    """
    import inspect
    p = inspect.signature(kae.close_all_explorers).parameters["hint"]
    assert p.default is inspect.Parameter.empty


def test_all_cabinets_filters_by_window_title(monkeypatch):
    """只收标题含 stage 名的窗口；用户自己的资源管理器不在名单里。"""
    titles = {101: "_krkr_stage", 102: "我的文档"}

    class FakeUser32:
        def EnumWindows(self, cb, _lp):
            for h in titles:
                if not cb(h, 0):
                    break

        def GetClassNameW(self, _h, buf, _n):
            buf.value = "CabinetWClass"

        def GetWindowTextLengthW(self, h):
            return len(titles[h])

        def GetWindowTextW(self, h, buf, _n):
            buf.value = titles[h]

    monkeypatch.setattr(kae, "user32", FakeUser32())

    assert kae.all_cabinets("_krkr_stage") == [101]
    assert kae.all_cabinets() == [101, 102], "不给 hint 时仍可枚举全部（供调试）"
    assert kae.find_explorer_by_title_hint("我的文档") == 102
    assert kae.find_explorer_by_title_hint("") is None
