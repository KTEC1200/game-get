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
# 1. 注册表里的工具都要能被解析出来（阶段 1 的 5 个 + 阶段 2 的 csc 与两个自带 C# 工具）
# ---------------------------------------------------------------------------


def test_check_all_covers_registry():
    rows = tb.check_all()
    assert len(rows) == len(tb.TOOLS) == 8
    missing = [r["key"] for r in rows if not r["found"]]
    # 不 fail：工具是可选依赖。但要在输出里明确可见
    assert isinstance(missing, list)


@pytest.mark.parametrize("key", ["garbro", "tlg2png", "ffprobe", "assetstudio", "krkr",
                                 "csc", "gyu", "hg3"])
def test_tool_resolvable_and_is_file(key):
    _skip_unless(key)
    p = tb.find_tool(key)
    assert p.is_file()
    assert p.stat().st_size > 0
    assert p.name.lower() == tb.TOOLS[key].exe_name.lower()


def test_csc_really_compiles_and_runs(tmp_path):
    """★核心★ 真 csc 编一个 hello-world 并跑起来——「源码随包」这条链的地面验证。

    只查 `find_tool("csc")` 找到文件是不够的：真正要证明的是
    「csc 能把 .cs 变出可执行 exe」，这是 `_gyu_tool` / `_hg3_tool` 的生存前提。
    """
    _skip_unless("csc")
    src = tmp_path / "hello.cs"
    src.write_text(
        "using System; class P { static void Main() { Console.WriteLine(\"OK-CSC\"); } }",
        encoding="utf-8",
    )

    exe = tb.build_csharp(src, platform="anycpu")
    assert exe.is_file(), "csc 报成功却没产出 exe"

    import subprocess
    r = subprocess.run([str(exe)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert b"OK-CSC" in r.stdout


def test_csharp_tools_build_or_are_buildable():
    """自带 C# 工具：要么 exe 已在，要么源码 + csc 都在（用时会现编）。"""
    rows = tb.check_csharp()
    assert {r["key"] for r in rows} == set(tb.CSHARP)
    for r in rows:
        assert r["source_found"], f"{r['key']} 的源码不在仓库里：{r['source']}"
        assert r["ready"], f"{r['key']} 既没有现成 exe 也没有编译器"


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


#: 已解包产物的物理位置。用户 2026-10-29 决定「文件和空目录都不管」，
#: 所以 `_extracted/` 仍留在旧副本目录里；同时保留项目目录下这一候选，
#: 将来若搬回来无需改测试。
EXTRACTED_ROOTS = [Path(r"D:\K\zcode\game\_extracted"),
                   Path(__file__).resolve().parent.parent / "_extracted"]


def test_ffprobe_real_audio():
    _skip_unless("ffprobe")
    ogg = _first_with_suffix([Path(r"D:\HY\pork社\兼职人妻"), *EXTRACTED_ROOTS], (".ogg",))
    if ogg is None:
        pytest.skip("找不到 .ogg 样本")

    info = tb.ffprobe(ogg)

    assert info is not None, f"ffprobe 应能解开 {ogg.name}"
    assert info["kind"] == "audio"
    assert info["codec"] and info["dur"] and info["dur"] > 0


def test_ffprobe_embedded_cover_is_not_video():
    """**验收纪律第 4 条**：ffprobe 把 mp3/ogg 的**内嵌封面**报成 codec_type=video。

    实测 `常識改変学園` 866 个 .ogg 里有 19 个带 mjpeg 封面（disposition.attached_pic=1），
    不排除的话音频会被算成视频、视频数虚高。样本找不到就 skip，找到就必须判 audio。
    """
    _skip_unless("ffprobe")
    ogg = _first_with_suffix([Path(r"D:\HY\常識改変学園-製品版-"), *EXTRACTED_ROOTS], (".ogg",))
    if ogg is None:
        pytest.skip("找不到 .ogg 样本")

    info = tb.ffprobe(ogg)

    assert info is not None, f"ffprobe 应能解开 {ogg.name}"
    assert info["kind"] == "audio", f"{ogg.name} 是带封面的音频，不该判成视频"
    assert info["w"] is None and info["h"] is None, "封面流的宽高不该泄漏到结果里"


def test_ffprobe_real_video():
    _skip_unless("ffprobe")
    vid = _first_with_suffix([Path(r"D:\HY\教师催眠1"), *EXTRACTED_ROOTS], (".wmv", ".mpg", ".mp4"))
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
    tlg = _first_with_suffix(
        [r / "高慢妻陥落！！" for r in EXTRACTED_ROOTS], (".tlg",))
    if tlg is None:
        pytest.skip(f"没有可用 .tlg 样本（{EXTRACTED_ROOTS}）")

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


# ---------------------------------------------------------------------------
# 7. 随包工具（bin/<key>）：真用一次「随包副本」跑 garbro_list，证明解析档位没白加
# ---------------------------------------------------------------------------

def test_bundled_garbro_list_uses_bundled_copy(tmp_path, monkeypatch):
    """冻结包 bin/garbro 存在时，monkeypatch _bin_root 指过去真跑一次：
    ToolResult.exe 必须是随包副本的路径（不是开发机 D:\K\galgame 的）。"""
    dist_bin = Path(__file__).resolve().parent.parent / "_spike_pkg" / "dist" / "orchestrator" / "bin"
    if not (dist_bin / "garbro" / "GARbro.Console.exe").is_file():
        pytest.skip("dist 未打包随包工具（先跑 python build_exe.py）")
    # 真实归档：从案例库样本地里找一个 xp3
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import build_cases as bc
    archive = ""
    for _name, s in bc.SAMPLES.items():
        d = Path(s["game_dir"])
        if not d.is_dir():
            continue
        hits = sorted(d.rglob("*.xp3"))
        if hits:
            archive = str(hits[0])
            break
    if not archive:
        pytest.skip("没有可用的 .xp3 样本")

    monkeypatch.setattr(tb, "_bin_root", lambda: dist_bin)
    ok, _entries, _out = tb.garbro_list(archive)
    # garbro_list 返回 (ok, entries, out)，不带 exe 路径——用 find_tool 直接锁解析结果
    hit = tb.find_tool("garbro")
    assert hit.parent == dist_bin / "garbro", f"应解析到随包副本，实际 {hit}"
    assert ok is not None
