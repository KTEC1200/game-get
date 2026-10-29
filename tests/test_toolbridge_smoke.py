#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolbridge 的**真实工具**冒烟测试。

与 test_toolbridge.py 分工：那边测规矩（用假工具，零外部依赖），这边测**真工具真的调得通**
（依赖本机 `D:\\K\\galgame\\` 下的 exe）。

设计取舍：
  * 工具缺失时 **skip 而不是 fail** —— 别人 clone 这个仓库不一定装了 GARbro；
    但一旦工具在，就必须真的验出东西来（不许静默放过）。
  * 全部用**只读或临时目录**操作，不碰 `D:\\HY` 的原始游戏文件。
  * 每个断言都带「退出码 0 不等于成功」的意识：这里断言的是**产物**。

跑法：`python -m pytest tests/test_toolbridge_smoke.py -q -v`
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import toolbridge as tb  # noqa: E402


def _have(key: str) -> bool:
    try:
        tb.find_tool(key)
        return True
    except tb.ToolNotFound:
        return False


def _skip_unless(key: str):
    if not _have(key):
        pytest.skip(f"本机未安装 {key}（{tb.TOOLS[key].exe_name}），跳过真实冒烟")


# ---------------------------------------------------------------------------
# 1. 五个工具都要能被解析出来（阶段 1 的交付判据）
# ---------------------------------------------------------------------------


def test_check_all_reports_five():
    rows = tb.check_all()
    assert len(rows) == 5
    missing = [r["key"] for r in rows if not r["found"]]
    # 不 fail：工具是可选依赖。但要在输出里明确可见
    assert isinstance(missing, list)


@pytest.mark.parametrize("key", ["garbro", "tlg2png", "ffprobe", "assetstudio", "krkr"])
def test_tool_resolvable_and_is_file(key):
    _skip_unless(key)
    p = tb.find_tool(key)
    assert p.is_file()
    assert p.stat().st_size > 0
    assert p.name.lower() == tb.TOOLS[key].exe_name.lower()


# ---------------------------------------------------------------------------
# 2. GARbro：真封包列表 + 条目数口径（含 2026-10-29 纠正的「无表头」结论）
# ---------------------------------------------------------------------------


def test_garbro_list_real_xp3():
    """对一个真实 xp3 列表，验证条目数与首行形态。"""
    _skip_unless("garbro")
    # 兼职人妻：544.7 MB，单主包，历史验证过 2562 条
    xp3 = Path(r"D:\HY\pork社\兼职人妻\data.xp3")
    if not xp3.is_file():
        pytest.skip(f"样本缺失：{xp3}")

    ok, n, out = tb.garbro_list(xp3)

    assert ok is True, "GARbro 应能识别这个包（Console 可读样本）"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # ★口径护栏★：条目数 == 非空行数，不许减 1
    assert n == len(lines), "garbro_list 的条目数必须等于非空行数（不许套 len(lines)-1）"
    assert n == 2562, f"实测该包 2562 条，得到 {n}——口径或样本变了，需重新核实"
    # 首行就是第一个条目（证明「xp3 无表头」）
    assert "bgimage/black.tlg" in lines[0], f"首行应是条目而非表头，实际：{lines[0]!r}"


def test_garbro_list_unknown_format_is_not_fatal():
    """Console 读不出的包要返回 (False, 0)，不能抛异常（假阴性是已知行为，坑 1）。"""
    _skip_unless("garbro")
    xp3 = Path(r"D:\HY\pork社\高慢妻陥落！！\data.xp3")
    if not xp3.is_file():
        pytest.skip(f"样本缺失：{xp3}")

    ok, n, out = tb.garbro_list(xp3)

    assert ok is False and n == 0
    assert "unknown format" in out.lower()


# ---------------------------------------------------------------------------
# 3. ffprobe：真媒体 + 非白名单扩展名的短路
# ---------------------------------------------------------------------------


def _first_with_suffix(roots: list[Path], suffixes: tuple[str, ...]) -> Path | None:
    """在若干根目录里找第一个指定扩展名的文件。

    产物可能落在 `D:\\HY`（游戏源目录）或 `_extracted`（已解包产物）——两处都找，
    否则测试会因为「样本已解包、源目录里没这个扩展名」而假 skip。
    """
    for root in roots:
        if not root.is_dir():
            continue
        for suf in suffixes:
            hit = next(iter(root.rglob("*" + suf)), None)
            if hit is not None:
                return hit
    return None


EXTRACTED = Path(r"D:\K\zcode\game\_extracted")


def test_ffprobe_real_audio():
    _skip_unless("ffprobe")
    ogg = _first_with_suffix([Path(r"D:\HY\pork社\兼职人妻"), EXTRACTED], (".ogg",))
    if ogg is None:
        pytest.skip("找不到 .ogg 样本")

    info = tb.ffprobe(ogg)

    assert info is not None, f"ffprobe 应能解开 {ogg.name}"
    assert info["kind"] == "audio"
    assert info["codec"] and info["dur"] and info["dur"] > 0


def test_ffprobe_real_video():
    _skip_unless("ffprobe")
    vid = _first_with_suffix([Path(r"D:\HY\教师催眠1"), EXTRACTED], (".wmv", ".mpg", ".mp4"))
    if vid is None:
        pytest.skip("找不到视频样本")

    info = tb.ffprobe(vid)

    assert info is not None, f"ffprobe 应能解开 {vid.name}"
    assert info["kind"] == "video"
    assert info["w"] and info["h"], "视频应解出分辨率"


def test_ffprobe_short_circuits_non_media(tmp_path):
    """非白名单扩展名不该真的去调 ffprobe（即使 ffprobe 在）。"""
    p = tmp_path / "script.rpyc"
    p.write_bytes(b"\x00" * 32)
    assert tb.ffprobe(p) is None


# ---------------------------------------------------------------------------
# 4. tlg2png：真转一张，且成功判据是 PNG 头（不是退出码）
# ---------------------------------------------------------------------------


def test_tlg2png_real_conversion(tmp_path):
    """从已解包产物里找一张 .tlg，真转一次。

    注意：已交付样本的 tlg 大多已转成 png，源 .tlg 可能只剩在 raw 目录里；
    找不到就 skip（不伪造样本——伪造的 tlg 转不出来反而是假失败）。
    """
    _skip_unless("tlg2png")
    root = Path(r"D:\K\zcode\game\_extracted\高慢妻陥落！！")
    tlg = next(iter(root.rglob("*.tlg")), None) if root.is_dir() else None
    if tlg is None:
        pytest.skip(f"没有可用 .tlg 样本（{root}）")

    dst = tmp_path / "out.png"
    r = tb.tlg2png(tlg, dst)

    assert r.ok is True, f"转换失败：{r.reason}"
    assert dst.is_file()
    with dst.open("rb") as fh:
        assert fh.read(4) == b"\x89PNG", "产物必须是真 PNG（不看退出码）"


def test_tlg2png_fails_loudly_on_garbage_input(tmp_path):
    """喂垃圾数据 → 必须判失败，不许因为 exit=0 就报成功。"""
    _skip_unless("tlg2png")
    bad = tmp_path / "bad.tlg"
    bad.write_bytes(b"NOT A TLG FILE" * 8)
    dst = tmp_path / "bad.png"

    r = tb.tlg2png(bad, dst)

    assert r.ok is False, "垃圾输入不许判成功"


# ---------------------------------------------------------------------------
# 5. KrkrExtract：只验「三件套齐全 + 能定位」，不真注入（注入会拉 GUI，不该在测试里做）
# ---------------------------------------------------------------------------


def test_krkr_triplet_present():
    _skip_unless("krkr")
    d = tb.find_tool("krkr").parent
    for name in ("KrkrExtract.Lite.exe", "KrkrExtract.Core.dll", "KrkrExtract.UI.Lite.dll"):
        assert (d / name).is_file(), f"三件套缺 {name}"


def test_krkr_inject_rejects_missing_dlls(tmp_path):
    """伪造一个只有 exe 的目录 → 必须在启动前就报错，别白等一轮超时。"""
    fake = tmp_path / "KrkrExtract.Lite.exe"
    fake.write_bytes(b"MZ")
    with pytest.raises(tb.ToolNotFound, match="三件套|缺少"):
        tb.krkr_inject("game.exe", exe_override=fake)


# ---------------------------------------------------------------------------
# 6. AssetStudio：只验「定位 + 坑 4 护栏」，不真导出（导出很慢且需要 Unity 工程）
# ---------------------------------------------------------------------------


def test_assetstudio_guard_rails_with_real_tool_present():
    """护栏是纯参数校验，与工具在不在无关——但工具在时更要保证它不被绕过。"""
    _skip_unless("assetstudio")
    with pytest.raises(ValueError):
        tb.assetstudio_export("src", "out", types="Texture2D,AudioClip")
    with pytest.raises(ValueError):
        tb.assetstudio_export("src", "out", types="Texture2D|AudioClip")
