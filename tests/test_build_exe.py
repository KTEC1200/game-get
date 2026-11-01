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
