#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_exe.py 的纯逻辑测试（不跑 PyInstaller）。

重心：外部工具随包（BUNDLE_TOOLS / bundle_tools）——用户 2026-11-02 要求
「所需的外部工具一并集成」后新增的打包步骤。缺来源只警告不失败：
软件对缺失工具会如实报错，不该让打包机上的环境差异炸掉构建。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_exe as be  # noqa: E402


def _fake_tool(src: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def test_bundle_tools_copies_whole_dir_and_globs(tmp_path):
    """`*` 整目录镜像（含子目录）；glob 列表只挑匹配的文件。"""
    garbro = tmp_path / "src_garbro"
    _fake_tool(garbro, {
        "GARbro.Console.exe": b"a",
        "GameRes.dll": b"b",
        "GameData.txt": b"c",
    })
    (garbro / "sub").mkdir()
    (garbro / "sub" / "natives.dll").write_bytes(b"d")

    ffb = tmp_path / "src_ffb"
    _fake_tool(ffb, {
        "ffprobe.exe": b"p",
        "avcodec-63.dll": b"1",
        "ffmpeg.exe": b"NOT-ME",
        "ffplay.exe": b"NOT-ME",
    })

    dest = tmp_path / "dist" / "app"
    reports = be.bundle_tools(dest, entries=[
        ("garbro", str(garbro), "*"),
        ("ffprobe", str(ffb), ["ffprobe.exe", "avcodec-*.dll"]),
    ])

    assert (dest / "bin" / "garbro" / "GARbro.Console.exe").read_bytes() == b"a"
    assert (dest / "bin" / "garbro" / "sub" / "natives.dll").read_bytes() == b"d"
    assert (dest / "bin" / "ffprobe" / "avcodec-63.dll").read_bytes() == b"1"
    assert not (dest / "bin" / "ffprobe" / "ffmpeg.exe").exists(), "glob 之外不许混进来"
    assert (dest / "bin" / "NOTICE.txt").is_file(), "许可证清单必须随包"
    assert any("[SKIP]" not in r for r in reports)


def test_bundled_garbro_enables_plugin_loading_without_changing_source(tmp_path):
    import xml.etree.ElementTree as ET

    source = tmp_path / "garbro"
    config = b'<configuration><startup/><runtime><assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1"/></runtime></configuration>'
    _fake_tool(source, {"GARbro.Console.exe.config": config})
    dest = tmp_path / "dist"
    be.bundle_tools(dest, entries=[("garbro", str(source), "*")])

    result = ET.parse(dest / "bin" / "garbro" / "GARbro.Console.exe.config").getroot()
    assert result.find("runtime/loadFromRemoteSources").get("enabled") == "true"
    assert result.find("runtime/{urn:schemas-microsoft-com:asm.v1}assemblyBinding") is not None
    assert b'<assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1"' in (dest / "bin" / "garbro" / "GARbro.Console.exe.config").read_bytes()
    assert (source / "GARbro.Console.exe.config").read_bytes() == config


def test_bundle_tools_missing_source_is_warning_not_failure(tmp_path):
    """打包机上少个工具 → [SKIP] 警告，构建继续（toolbridge 会落到下一档并如实报错）。"""
    dest = tmp_path / "dist" / "app"
    reports = be.bundle_tools(dest, entries=[
        ("garbro", str(tmp_path / "not-exist"), "*"),
        ("tlg2png", str(tmp_path), "*"),   # 空目录：0 个文件也算 OK 但空
    ])
    assert any("[SKIP]" in r and "garbro" in r for r in reports)
    assert (dest / "bin" / "NOTICE.txt").is_file(), "即使全 SKIP，NOTICE 也要在"


def test_bundle_tools_matches_toolbridge_keys():
    """BUNDLE_TOOLS 的 key 必须是 toolbridge 的注册 key（bin/<key> 解析按它找），
    krkrz 是手动兜底工具不在注册表里，白名单放行。"""
    import toolbridge as tb
    for key, _src, _pat in be.BUNDLE_TOOLS:
        assert key in tb.TOOLS or key == "krkrz", \
            f"{key} 既不是 toolbridge key 也不是 krkrz——bin/<key> 解析会扑空"
    # 随包里的 toolbridge 可解析 key 必须真的存在 exe_name 对应文件预期
    for key in ("garbro", "assetstudio", "tlg2png", "ffprobe", "krkr"):
        assert tb.TOOLS[key].exe_name, f"{key} 缺 exe_name"


# ---------------------------------------------------------------------------
# exe 身份信息（2026-11-04）
# ---------------------------------------------------------------------------

def test_version_file_carries_real_identity_fields(tmp_path, monkeypatch):
    """★被拦的根因之一★ exe 属性全空 = 「未知程序」。

    PyInstaller 默认不写版本资源，成品在安全软件弹窗里连名字都没有。
    这里要求 8 个关键字段都在，且版本号与 APP_VERSION 一致（不能写死旧值）。
    """
    monkeypatch.setattr(be, "SPEC", tmp_path)
    text = be.version_file().read_text(encoding="utf-8")

    for key in ("CompanyName", "FileDescription", "FileVersion",
                "OriginalFilename", "ProductName", "ProductVersion"):
        assert key in text, f"版本资源缺字段：{key}"
    assert be.APP_VERSION in text
    assert "orchestrator.exe" in text


def test_version_file_pads_version_to_four_numbers(tmp_path, monkeypatch):
    """Windows 的 filevers 必须是四段整数，`0.4` 这种两段写法会让构建直接失败。"""
    monkeypatch.setattr(be, "SPEC", tmp_path)
    monkeypatch.setattr(be, "APP_VERSION", "1.2")
    text = be.version_file().read_text(encoding="utf-8")

    assert "filevers=(1, 2, 0, 0)" in text
    assert "prodvers=(1, 2, 0, 0)" in text


def test_version_file_survives_bad_version_string(tmp_path, monkeypatch):
    """版本号写成 1.0-beta 时不许让构建崩：非数字段按 0 处理。"""
    monkeypatch.setattr(be, "SPEC", tmp_path)
    monkeypatch.setattr(be, "APP_VERSION", "1.0-beta")
    text = be.version_file().read_text(encoding="utf-8")

    assert "filevers=(1, 0, 0, 0)" in text


def test_icon_file_generates_multi_size_ico(tmp_path, monkeypatch):
    """没有图标时 exe 在任务栏/拦截弹窗里是个空白框，用户认不出是自己装的什么。"""
    pytest.importorskip("PIL")
    monkeypatch.setattr(be, "SPEC", tmp_path)

    ico = be.icon_file()

    assert ico is not None and ico.is_file()
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00", "不是合法 ICO 头"


def test_icon_file_returns_none_without_pillow(tmp_path, monkeypatch):
    """没装 Pillow 也要能构建：图标是加分项，不是前置条件。"""
    monkeypatch.setattr(be, "SPEC", tmp_path)
    monkeypatch.setitem(sys.modules, "PIL", None)
    assert be.icon_file() is None


# ---------------------------------------------------------------------------
# 本地加固包标识（2026-11-07）：新 tag 出包，绝不覆盖已发布对照样本
# ---------------------------------------------------------------------------

def test_portable_refuses_to_overwrite_existing_zip(tmp_path, monkeypatch):
    """已发布的 0.8.2 / dropfix1 是对照样本，误覆盖就再也比不了新旧差异。"""
    dist = tmp_path / "dist" / "orchestrator"
    dist.mkdir(parents=True)
    (dist / "orchestrator.exe").write_bytes(b"fake-exe")
    out_root = tmp_path / "Output"
    out_root.mkdir()
    published = out_root / f"GalgameUnpacker-{be.APP_VERSION}-portable.zip"
    published.write_bytes(b"published")

    monkeypatch.setattr(be, "REPO", tmp_path)          # 没有 README，跳过复制
    monkeypatch.setattr(be, "DIST", tmp_path / "dist")
    monkeypatch.setattr(be, "EXE", dist / "orchestrator.exe")
    monkeypatch.setattr(be, "PACKAGING", tmp_path)

    def boom(*_a, **_kw):
        raise AssertionError("拒绝覆盖时不许触发压缩/子进程")

    monkeypatch.setattr(be.subprocess, "run", boom)
    assert be.portable() == 1
    assert published.read_bytes() == b"published"


def test_portable_rejects_unsafe_tag(tmp_path, monkeypatch):
    """tag 会进文件名，路径分隔符/空格一律挡在构建之前。"""
    monkeypatch.setattr(be, "EXE", tmp_path / "orchestrator.exe")
    assert be.portable("../evil") == 1
    assert be.portable("a b") == 1
