# -*- coding: utf-8 -*-
"""环境自检（`doctor.py`）的测试。

锁三件事：
  1. 探针成功/失败都要**如实写成文字**（弹窗与报告都靠这句话）；
  2. 报告必须有那五个小节 —— 少了任何一节，用户发回来就缺证据；
  3. 全灭时的结论要指向「进程级拦截」，不能写成「请换个目录」（那是把人送上弯路）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import doctor  # noqa: E402


def test_probe_ok_creates_and_cleans(tmp_path):
    """探针成功不留痕：探针文件删掉，原本不存在的目录也不留在盘上。"""
    target = tmp_path / "out"
    assert doctor.probe(target) == "可写"
    assert not target.exists(), "自检是诊断，不该顺手造空目录"
    assert not (target / "write-probe.txt").exists()


def test_probe_reports_permission_error(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise PermissionError(13, "拒绝访问")

    monkeypatch.setattr(doctor.Path, "mkdir", boom)

    got = doctor.probe(tmp_path / "x")

    assert got.startswith("不可写") and "PermissionError" in got


def test_candidate_dirs_puts_app_dir_first(tmp_path):
    items = doctor.candidate_dirs(tmp_path / "game", tmp_path / "app")

    assert items[0] == ("程序目录 output", tmp_path / "app" / "output")
    assert ("游戏目录 output", tmp_path / "game" / "output") in items


def test_candidate_dirs_without_game(tmp_path):
    """没选游戏目录时也要能出报告（--doctor 单独跑的场景）。"""
    labels = [label for label, _p in doctor.candidate_dirs(None, tmp_path)]

    assert "游戏目录 output" not in labels


def test_report_contains_all_sections(tmp_path):
    report = doctor.doctor_report(tmp_path / "game", tmp_path / "app", version="9.9.9")

    for section in ("[程序]", "[身份与权限]", "[终端防护 / 安全软件]", "[写探针]", "[结论]"):
        assert section in report
    assert "9.9.9" in report


def test_report_concludes_process_level_block_when_nothing_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "probe", lambda p: "不可写 —— PermissionError: 拒绝访问。")

    report = doctor.doctor_report(None, tmp_path, version="0")

    assert "连程序自身目录都写不进去" in report
    assert "进程级" in report


def test_report_points_at_app_dir_when_only_it_is_writable(tmp_path, monkeypatch):
    app = tmp_path / "app"

    def fake(p: Path) -> str:
        return "可写" if p.parent == app else "不可写 —— PermissionError: 拒绝访问。"

    monkeypatch.setattr(doctor, "probe", fake)

    report = doctor.doctor_report(tmp_path / "game", app, version="0")

    assert "只有程序自身目录可写" in report
    assert "按进程 + 按目录" in report


def test_running_processes_returns_mapping():
    """枚举进程是 ctypes 手写的，容易写错类型 —— 至少要能返回 dict 且键是小写名。"""
    got = doctor.running_processes()

    assert isinstance(got, dict)
    for name in got:
        assert name == name.lower()


def test_integrity_level_is_a_string():
    assert isinstance(doctor.integrity_level(), str) and doctor.integrity_level()
