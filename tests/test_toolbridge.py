#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolbridge 的测试。

测试重心不是「能不能调通真工具」（那靠 tests/test_toolbridge_smoke.py 与本机环境），
而是**四条硬规矩有没有被守住**——尤其规矩 1「退出码 0 毫无意义」：
这是坑 4（AssetStudio `--types A,B,C` 静默导 0 个文件且 exit=0）的直接回归护栏。

假工具一律用 `sys.executable` 当 exe + 一个临时 .py 当脚本，通过 exe_override 注入，
这样不需要任何外部 exe，也能精确控制「退出码 / 产物 / 超时」三个维度。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import toolbridge as tb  # noqa: E402


# ---------------------------------------------------------------------------
# 假工具工厂
# ---------------------------------------------------------------------------


def make_fake_tool(tmp_path: Path, name: str, body: str) -> Path:
    """在 tmp_path 下写一个假工具脚本，返回脚本路径。"""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def run_fake(tmp_path: Path, script: Path, argv=(), **kw):
    """用 python.exe 当 exe、script 当第一个参数，走 toolbridge.run。

    key 借 "garbro" 一用——run() 只用它去查 spec（找 exe 会被 override 顶掉），
    不需要该工具真的存在。
    """
    return tb.run("garbro", [str(script), *argv], exe_override=sys.executable, **kw)


# ---------------------------------------------------------------------------
# 规矩 1：退出码 0 毫无意义，产物说了算
# ---------------------------------------------------------------------------


def test_exit0_but_no_product_is_failure(tmp_path):
    """★核心护栏★ 退出码 0 但一个产物都没有 → 必须判失败。

    这正是 AssetStudio 坑 4 的形态：`--types A,B,C` 导 0 个文件，exit code 仍是 0。
    如果这条测试红了，说明 toolbridge 退化成了「信退出码」，坑 4 会复活。
    """
    out = tmp_path / "out"
    out.mkdir()
    script = make_fake_tool(tmp_path, "silent.py", "raise SystemExit(0)\n")

    r = run_fake(tmp_path, script, product_dir=out, min_products=1)

    assert r.returncode == 0, "前提：假工具确实返回了 0"
    assert r.ok is False, "退出码 0 + 0 产物必须判失败"
    assert "产物不足" in r.reason


def test_nonzero_exit_but_products_is_success(tmp_path):
    """反过来也要对：退出码非 0 但产物齐了 → 判成功（GARbro 系工具常有这种噪声）。"""
    out = tmp_path / "out"
    out.mkdir()
    script = make_fake_tool(
        tmp_path, "noisy.py",
        "import pathlib,sys\n"
        f"pathlib.Path({str(out / 'a.ogg')!r}).write_bytes(b'x'*16)\n"
        "sys.stderr.write('warning: something harmless\\n')\n"
        "raise SystemExit(3)\n")

    r = run_fake(tmp_path, script, product_dir=out, min_products=1)

    assert r.returncode == 3
    assert r.ok is True, "产物齐了就该判成功，退出码只是诊断信息"
    assert r.products.total == 1


def test_min_products_threshold(tmp_path):
    """产物数没到 min_products 也算失败（部分成功 ≠ 成功）。"""
    out = tmp_path / "out"
    out.mkdir()
    script = make_fake_tool(
        tmp_path, "one.py",
        "import pathlib\n"
        f"pathlib.Path({str(out / 'a.png')!r}).write_bytes(b'x')\n")

    assert run_fake(tmp_path, script, product_dir=out, min_products=1).ok is True
    assert run_fake(tmp_path, script, product_dir=out, min_products=2).ok is False


def test_timeout_is_failure(tmp_path):
    """超时必须判失败，且不能把上一次的产物算进来。"""
    out = tmp_path / "out"
    out.mkdir()
    script = make_fake_tool(tmp_path, "slow.py", "import time; time.sleep(30)\n")

    r = run_fake(tmp_path, script, product_dir=out, timeout=0.7)

    assert r.timed_out is True
    assert r.ok is False
    assert "超时" in r.reason


def test_product_check_rejects_bad_products(tmp_path):
    """逐产物谓词：产出的是垃圾文件（不是合法 PNG）→ 判失败。"""
    out = tmp_path / "out"
    out.mkdir()
    script = make_fake_tool(
        tmp_path, "fake_png.py",
        "import pathlib\n"
        f"pathlib.Path({str(out / 'a.png')!r}).write_bytes(b'NOTAPNG')\n")

    r = run_fake(tmp_path, script, product_dir=out, min_products=1,
                 product_check=tb._is_png)

    assert r.ok is False
    assert "未通过校验" in r.reason


def test_product_check_accepts_good_products(tmp_path):
    """正例：真 PNG 头 + 足够长度 → 通过。"""
    out = tmp_path / "out"
    out.mkdir()
    script = make_fake_tool(
        tmp_path, "real_png.py",
        "import pathlib\n"
        f"pathlib.Path({str(out / 'a.png')!r}).write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + b'x'*16)\n")

    r = run_fake(tmp_path, script, product_dir=out, min_products=1,
                 product_check=tb._is_png)

    assert r.ok is True


def test_no_product_dir_marks_unverified(tmp_path):
    """不给 product_dir 时只能看退出码，但 reason 必须明确标注「不可信」。"""
    script = make_fake_tool(tmp_path, "ok.py", "raise SystemExit(0)\n")
    r = run_fake(tmp_path, script)
    assert r.ok is True
    assert "未验证" in r.reason or "不可信" in r.reason


# ---------------------------------------------------------------------------
# 规矩 1 的推论：幂等重跑 ≠ 失败（tlg2png 专项）
# ---------------------------------------------------------------------------


def test_tlg2png_skips_when_dst_already_valid_png(tmp_path):
    """★回归护栏★ 目标已是合法 PNG 时，不调工具也判成功。

    这是 `--reuse-raw` 复跑时 507 张图全被判失败的真 bug（2026-10-29）：
    png/ 里已有上次转好的产物 → `run()` 看到产物增量 0 → ok=False。
    「本次没新增」不等于「失败」，可能只是**已经干过了**。
    """
    src = tmp_path / "a.tlg"
    src.write_bytes(b"NOT A TLG")          # 源故意是垃圾：证明这次根本没调工具
    dst = tmp_path / "a.png"
    dst.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)

    r = tb.tlg2png(src, dst)

    assert r.ok is True, f"已存在的合法 PNG 不该判失败：{r.reason}"
    assert "已存在" in r.reason
    assert r.exe == "(skipped)"


def test_tlg2png_still_fails_when_dst_is_bad(tmp_path):
    """反向：dst 存在但不是合法 PNG → 不能跳过，必须真跑工具并判失败。"""
    try:
        tb.find_tool("tlg2png")
    except tb.ToolNotFound:
        pytest.skip("本机未安装 tlg2png，跳过（该断言依赖真工具）")
    src = tmp_path / "a.tlg"
    src.write_bytes(b"NOT A TLG")
    dst = tmp_path / "a.png"
    dst.write_bytes(b"GARBAGE")             # 有文件但没 PNG 头

    r = tb.tlg2png(src, dst, timeout=30)

    assert r.ok is False
    assert r.exe != "(skipped)", "dst 不合法时不许走跳过分支"


# ---------------------------------------------------------------------------
# 规矩 2：找工具（不许硬编码路径）
# ---------------------------------------------------------------------------


def test_unknown_key_raises_keyerror():
    with pytest.raises(KeyError):
        tb.find_tool("no-such-tool")


def test_tool_not_found_message_lists_attempts(monkeypatch):
    """找不到工具时，异常消息必须列出所有尝试过的位置 + 该工具的已知坑。"""
    monkeypatch.setenv("TOOLBRIDGE_GARBRO", r"Z:\nope\GARbro.Console.exe")
    # 把内置候选和 PATH 都打断，逼出 ToolNotFound
    monkeypatch.setattr(tb, "TOOLS", {
        "garbro": tb.ToolSpec(key="garbro", exe_name="GARbro.Console.exe",
                              purpose="test", candidates=(), notes="已知坑：假阴性"),
    })
    monkeypatch.setattr(tb.shutil, "which", lambda _n: None)

    with pytest.raises(tb.ToolNotFound) as ei:
        tb.find_tool("garbro")

    msg = str(ei.value)
    assert "TOOLBRIDGE_GARBRO" in msg
    assert "已尝试" in msg
    assert "已知坑：假阴性" in msg


def test_env_var_overrides_candidates(tmp_path, monkeypatch):
    """环境变量优先于内置候选。"""
    fake = tmp_path / "my-garbro.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("TOOLBRIDGE_GARBRO", str(fake))
    assert tb.find_tool("garbro") == fake


def test_explicit_override_beats_everything(tmp_path, monkeypatch):
    """显式 override 优先级最高（测试与多版本共存靠它）。"""
    env = tmp_path / "env.exe"
    ovr = tmp_path / "ovr.exe"
    env.write_bytes(b"MZ")
    ovr.write_bytes(b"MZ")
    monkeypatch.setenv("TOOLBRIDGE_GARBRO", str(env))
    assert tb.find_tool("garbro", override=ovr) == ovr


def test_config_file_is_honored(tmp_path, monkeypatch):
    """toolbridge.json 的 paths.<key> 也要生效。"""
    fake = tmp_path / "cfg.exe"
    fake.write_bytes(b"MZ")
    cfg = tmp_path / "toolbridge.json"
    cfg.write_text(json.dumps({"paths": {"garbro": str(fake)}}), encoding="utf-8")
    monkeypatch.delenv("TOOLBRIDGE_GARBRO", raising=False)
    monkeypatch.setattr(tb, "_load_config", lambda: json.loads(cfg.read_text("utf-8")))
    assert tb.find_tool("garbro") == fake


def test_all_tools_registered():
    """注册表必须覆盖：阶段 1 的 5 个外部工具 + 阶段 2 的 csc 与两个自带 C# 工具。

    这条断言故意写死集合——注册表少一条、或悄悄多一条没人管的工具，都要在这里红。
    """
    assert set(tb.TOOLS) == {"garbro", "tlg2png", "ffprobe", "assetstudio", "krkr",
                             "csc", "gyu", "hg3"}
    for spec in tb.TOOLS.values():
        assert spec.purpose, f"{spec.key} 缺 purpose"
        assert spec.notes, f"{spec.key} 缺 notes（已知坑要随工具走）"


# ---------------------------------------------------------------------------
# 规矩 3：子进程环境要洗干净
# ---------------------------------------------------------------------------


def test_sanitize_env_strips_meipass():
    """PyInstaller 冻结后 _MEI 路径不许进子进程 PATH（蓝图 §4.3）。"""
    dirty = {"PATH": os.pathsep.join([r"C:\Windows", r"C:\Users\x\_MEI12345", r"C:\bin"]),
             "PYTHONHOME": r"C:\PyInstaller\home", "PYTHONPATH": r"C:\x", "KEEP": "yes"}
    clean = tb._sanitize_env(dirty)

    assert "_MEI" not in clean["PATH"].upper()
    assert clean["PATH"].split(os.pathsep) == [r"C:\Windows", r"C:\bin"]
    assert "PYTHONHOME" not in clean and "PYTHONPATH" not in clean
    assert clean["KEEP"] == "yes", "无关变量不该被动"


def test_sanitize_env_does_not_mutate_caller_dict():
    """洗环境必须返回副本——改坏 os.environ 会污染整个进程。"""
    src = {"PATH": r"C:\a;_MEI_b", "X": "1"}
    tb._sanitize_env(src)
    assert src["PATH"] == r"C:\a;_MEI_b"


# ---------------------------------------------------------------------------
# 规矩 4：数产物
# ---------------------------------------------------------------------------


def test_count_products_recursive_and_by_ext(tmp_path):
    (tmp_path / "a.png").write_bytes(b"1" * 10)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.PNG").write_bytes(b"2" * 5)   # 大小写要归一
    (tmp_path / "sub" / "c.ogg").write_bytes(b"3" * 3)
    (tmp_path / "empty_dir").mkdir()

    p = tb.count_products(tmp_path)

    assert p.total == 3, "目录不算文件"
    assert p.by_ext == {".png": 2, ".ogg": 1}
    assert p.size == 18


def test_count_products_ext_filter(tmp_path):
    (tmp_path / "a.png").write_bytes(b"1")
    (tmp_path / "b.ogg").write_bytes(b"2")
    assert tb.count_products(tmp_path, exts=[".png"]).total == 1


def test_count_products_missing_dir_is_zero(tmp_path):
    """目录不存在返回全 0，不抛异常（before 快照常在目录尚未创建时取）。"""
    p = tb.count_products(tmp_path / "nope")
    assert (p.total, p.by_ext, p.size) == (0, {}, 0)


def test_delta_from(tmp_path):
    before = tb.Products(total=2, by_ext={".tlg": 2}, size=100)
    after = tb.Products(total=5, by_ext={".tlg": 2, ".png": 3}, size=400)
    d = after.delta_from(before)
    assert d.total == 3
    assert d.by_ext == {".png": 3}, "没变化的扩展名不该出现在增量里"
    assert d.size == 300


def test_run_reports_delta_not_total(tmp_path):
    """run 报的必须是**增量**：目录里原有文件不能算成本次产物。"""
    out = tmp_path / "out"
    out.mkdir()
    (out / "old.png").write_bytes(b"x" * 100)          # 已有产物
    script = make_fake_tool(
        tmp_path, "newone.py",
        "import pathlib\n"
        f"pathlib.Path({str(out / 'new.ogg')!r}).write_bytes(b'y')\n")

    r = run_fake(tmp_path, script, product_dir=out, min_products=1)

    assert r.ok is True
    assert r.products.total == 1, "只该数新增的那 1 个"
    assert r.products.by_ext == {".ogg": 1}


def test_run_with_zero_new_products_but_dir_populated(tmp_path):
    """★同坑变体★ 目录里本来就有东西、这次一个没新增 → 仍然必须失败。

    这正是「工具静默 0 产出」最难发现的形态：事后看目录非空，误以为成功。
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.png").write_bytes(b"x" * 100)
    script = make_fake_tool(tmp_path, "noop.py", "raise SystemExit(0)\n")

    r = run_fake(tmp_path, script, product_dir=out, min_products=1)

    assert r.products.total == 0
    assert r.ok is False, "目录非空 ≠ 本次成功"


# ---------------------------------------------------------------------------
# AssetStudio 坑 4 的护栏
# ---------------------------------------------------------------------------


def test_assetstudio_rejects_comma_types():
    """逗号必须当场拒绝，绝不能放行去导 0 个文件。"""
    with pytest.raises(ValueError, match="逗号"):
        tb.assetstudio_export("src", "out", types="Texture2D,AudioClip")


def test_assetstudio_rejects_pipe_types():
    with pytest.raises(ValueError, match="竖线"):
        tb.assetstudio_export("src", "out", types="Texture2D|AudioClip")


def test_assetstudio_accepts_single_type(tmp_path, monkeypatch):
    """单类型要放行，且 argv 形状正确。"""
    captured = {}

    def fake_run(key, argv=(), **kw):
        captured["key"] = key
        captured["argv"] = list(argv)
        return tb.ToolResult(key=key, exe="x", argv=list(argv), returncode=0, ok=True)

    monkeypatch.setattr(tb, "run", fake_run)
    tb.assetstudio_export("SRC", "OUT", types="Texture2D")

    assert captured["key"] == "assetstudio"
    a = captured["argv"]
    assert a[0] == "SRC" and a[1] == "OUT"
    assert a[a.index("--types") + 1] == "Texture2D"
    assert "--export_type" in a and "--group_assets" in a


# ---------------------------------------------------------------------------
# ffprobe 白名单
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["script.rpyc", "font.otf", "a.json", "b.txt", "noext"])
def test_ffprobe_skips_non_media_extensions(tmp_path, name):
    """非媒体扩展名直接返回 None，不许调用 ffprobe（否则 `Invalid data found` 搅浑验收）。"""
    p = tmp_path / name
    p.write_bytes(b"x")
    assert tb.ffprobe(p) is None


def test_av_ext_whitelist_nonempty():
    assert ".ogg" in tb.AV_EXT and ".wmv" in tb.AV_EXT and ".png" not in tb.AV_EXT


# ---------------------------------------------------------------------------
# ffprobe 内嵌封面（验收纪律第 4 条）
# ---------------------------------------------------------------------------
#
# 真调 ffprobe 测不出「刚好挑中带封面的那个 ogg」，那种测试迟早退化成 skip，
# 所以把 JSON 解析抽成 parse_ffprobe_json() 直接喂构造数据。

_COVER = {"codec_type": "video", "codec_name": "mjpeg", "width": 500, "height": 500,
          "disposition": {"attached_pic": 1}}
_AUDIO = {"codec_type": "audio", "codec_name": "vorbis", "sample_rate": "44100",
          "duration": "12.5", "disposition": {"attached_pic": 0}}
_REAL_VIDEO = {"codec_type": "video", "codec_name": "wmv3", "width": 1280, "height": 720,
               "duration": "124.0", "disposition": {"attached_pic": 0}}


def test_ogg_with_embedded_cover_is_audio_not_video():
    """★核心★ 带 mjpeg 封面的 ogg 必须判 audio，且封面宽高不许泄漏。"""
    info = tb.parse_ffprobe_json({"streams": [_AUDIO, _COVER],
                                  "format": {"duration": "12.5"}})
    assert info["kind"] == "audio"
    assert info["codec"] == "vorbis"
    assert info["w"] is None and info["h"] is None
    assert info["has_cover"] is True
    assert info["dur"] == 12.5


def test_real_video_with_cover_still_counts_as_video():
    """有真视频流 + 封面时，仍应判 video（别把修复做过头）。"""
    info = tb.parse_ffprobe_json({"streams": [_AUDIO, _REAL_VIDEO, _COVER],
                                  "format": {"duration": "124.0"}})
    assert info["kind"] == "video"
    assert (info["w"], info["h"]) == (1280, 720)
    assert info["has_cover"] is True


def test_cover_only_file_is_not_a_video():
    """只有封面流、没有音轨也没有真视频 → None，不是「一个视频」。"""
    assert tb.parse_ffprobe_json({"streams": [_COVER]}) is None


def test_ffprobe_json_without_streams_is_none():
    assert tb.parse_ffprobe_json({"streams": []}) is None
    assert tb.parse_ffprobe_json({}) is None


# ---------------------------------------------------------------------------
# ffprobe 失败原因 + 重试（`ffprobe 无结果` 不该是一句糊弄话）
# ---------------------------------------------------------------------------
#
# 实测依据：甜蜜女友2+ 全量验收里 `pcm_DD/dd_02_ch08_019.OGG` 报过一次
# 「ffprobe 无结果」，但同一份字节随后稳定探得 vorbis 流、Ogg 页 CRC 也对得上
# ——是偶发（子进程没起来/被拖超时），不是文件坏。所以：①失败要重试一次
# ②重试仍失败必须说清是哪种失败。

_FFPROBE_OK = json.dumps({"streams": [_AUDIO], "format": {"duration": "12.5"}})


class _ProbeRun:
    """按顺序吐出预设结果，并记录调用次数（假的 tb.run）。"""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, key, argv=(), **kw):
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]


class _R:
    """够用的 ToolResult 替身。"""

    def __init__(self, rc=0, out="", err="", timed_out=False):
        self.returncode, self.stdout, self.stderr = rc, out, err
        self.timed_out = timed_out
        self.ok = rc == 0


def test_ffprobe_ex_retries_transient_failure(tmp_path, monkeypatch):
    """★核心★ 第一次没起来、第二次成功 → 算成功，别把偶发报成坏文件。"""
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    r = _ProbeRun(_R(rc=-1, err="Failed to start"), _R(rc=0, out=_FFPROBE_OK))
    monkeypatch.setattr(tb, "run", r)

    info, why = tb.ffprobe_ex(p)

    assert r.calls == 2, "失败后必须重试一次"
    assert why == "ok"
    assert info["codec"] == "vorbis" and info["dur"] == 12.5


def test_ffprobe_ex_reports_rc_and_stderr_tail(tmp_path, monkeypatch):
    """重试仍失败 → 说清 rc 与 stderr 末行（文件真坏长这样）。"""
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    r = _ProbeRun(_R(rc=1, err="junk\nInvalid data found when processing input\n"))
    monkeypatch.setattr(tb, "run", r)

    info, why = tb.ffprobe_ex(p)

    assert info is None
    assert r.calls == 2
    assert "rc=1" in why and "Invalid data found" in why
    assert "重试 1 次仍失败" in why


def test_ffprobe_ex_reports_timeout(tmp_path, monkeypatch):
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    monkeypatch.setattr(tb, "run", _ProbeRun(_R(rc=None, timed_out=True)))
    info, why = tb.ffprobe_ex(p, timeout=7)
    assert info is None and "超时" in why and "7" in why


def test_ffprobe_ex_reports_missing_streams(tmp_path, monkeypatch):
    """rc=0 但 JSON 里没有可用流（只有封面）→ 也要说清，别只回一个 None。"""
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    monkeypatch.setattr(tb, "run",
                        _ProbeRun(_R(rc=0, out=json.dumps({"streams": [_COVER]}))))
    info, why = tb.ffprobe_ex(p)
    assert info is None and "没有任何音视频流" in why


def test_ffprobe_ex_reports_json_error(tmp_path, monkeypatch):
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    monkeypatch.setattr(tb, "run", _ProbeRun(_R(rc=0, out="not json at all")))
    info, why = tb.ffprobe_ex(p)
    assert info is None and "JSON 解析失败" in why


def test_ffprobe_ex_non_media_extension_costs_no_subprocess(tmp_path, monkeypatch):
    r = _ProbeRun()
    monkeypatch.setattr(tb, "run", r)
    info, why = tb.ffprobe_ex(tmp_path / "script.rpyc")
    assert info is None and "白名单" in why and r.calls == 0


def test_ffprobe_wrapper_still_returns_info_only(tmp_path, monkeypatch):
    """`ffprobe()` 是老接口，行为不许变（只回信息）。"""
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    monkeypatch.setattr(tb, "run", _ProbeRun(_R(rc=0, out=_FFPROBE_OK)))
    assert tb.ffprobe(p)["kind"] == "audio"
    monkeypatch.setattr(tb, "run", _ProbeRun(_R(rc=1, err="boom")))
    assert tb.ffprobe(p) is None


# ---------------------------------------------------------------------------
# 阶段 2 第 2 条：自带 C# 工具「源码随包 + csc 现编」
# ---------------------------------------------------------------------------
# 假编译器用 python.exe 顶替：compiler 参数是**命令前缀列表**，所以
# `[sys.executable, <脚本>]` 就能冒充一个 csc，且能精确控制「编译几次 / 失败 / 不产 exe」。

FAKE_CSC = '''
import os, pathlib, sys

log = pathlib.Path(os.environ["FAKE_CSC_LOG"])
n = int(log.read_text()) if log.exists() else 0
log.write_text(str(n + 1))

if os.environ.get("FAKE_CSC_FAIL"):
    sys.stderr.write("fake error: boom\\n")
    raise SystemExit(1)

out = None
for a in sys.argv[1:]:
    if a.startswith("/out:"):
        out = a[len("/out:"):]
if not out:
    sys.stderr.write("no /out: argument\\n")
    raise SystemExit(2)
pathlib.Path(out).write_bytes(b"MZfake")
'''

FAKE_DECODER = '''
import pathlib, sys

root, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
for p in sorted(root.rglob("*")):
    if p.is_file():
        (out / (p.stem + ".png")).write_bytes(b"PNG")
'''


def fake_csc(tmp_path: Path, monkeypatch, *, fail: bool = False):
    """造一个假 csc，返回 (compiler 前缀, 调用计数文件)。"""
    script = make_fake_tool(tmp_path, "fake_csc.py", FAKE_CSC)
    log = tmp_path / "csc_calls.txt"
    monkeypatch.setenv("FAKE_CSC_LOG", str(log))
    if fail:
        monkeypatch.setenv("FAKE_CSC_FAIL", "1")
    return [sys.executable, str(script)], log


def csc_calls(log: Path) -> int:
    return int(log.read_text(encoding="utf-8")) if log.exists() else 0


def test_build_csharp_compiles_and_returns_exe(tmp_path, monkeypatch):
    src = tmp_path / "_t.cs"
    src.write_text("class P { static void Main() {} }", encoding="utf-8")
    prefix, log = fake_csc(tmp_path, monkeypatch)

    exe = tb.build_csharp(src, compiler=prefix)

    assert exe == tmp_path / "_t.exe"
    assert exe.is_file()
    assert csc_calls(log) == 1


def test_build_csharp_reuses_fresh_exe(tmp_path, monkeypatch):
    """exe 不比源码旧 → 直接复用，不再调编译器（否则每次解包都白等几秒）。"""
    src = tmp_path / "_t.cs"
    src.write_text("// x", encoding="utf-8")
    prefix, log = fake_csc(tmp_path, monkeypatch)

    first = tb.build_csharp(src, compiler=prefix)
    second = tb.build_csharp(src, compiler=prefix)

    assert first == second and first.is_file()
    assert csc_calls(log) == 1


def test_build_csharp_rebuilds_when_source_newer(tmp_path, monkeypatch):
    """改了 .cs 就该重编——否则用户改了解码器却还在跑旧 exe，最难查的那种错。"""
    src = tmp_path / "_t.cs"
    src.write_text("// x", encoding="utf-8")
    prefix, log = fake_csc(tmp_path, monkeypatch)
    tb.build_csharp(src, compiler=prefix)

    os.utime(src, (time.time() + 10, time.time() + 10))
    tb.build_csharp(src, compiler=prefix)

    assert csc_calls(log) == 2


def test_build_csharp_force_rebuilds(tmp_path, monkeypatch):
    src = tmp_path / "_t.cs"
    src.write_text("// x", encoding="utf-8")
    prefix, log = fake_csc(tmp_path, monkeypatch)
    tb.build_csharp(src, compiler=prefix)

    tb.build_csharp(src, compiler=prefix, force=True)

    assert csc_calls(log) == 2


def test_build_csharp_failure_includes_stderr(tmp_path, monkeypatch):
    """★核心★ 编译失败必须把 stderr 原文、源码名、编译器路径一起抛出。

    只报「工具不存在」会把用户引到错方向：真因是语法错/编译器缺失。
    """
    src = tmp_path / "_t.cs"
    src.write_text("// x", encoding="utf-8")
    prefix, _ = fake_csc(tmp_path, monkeypatch, fail=True)

    with pytest.raises(tb.CSharpBuildError) as ei:
        tb.build_csharp(src, compiler=prefix)

    msg = str(ei.value)
    assert "fake error: boom" in msg
    assert "_t.cs" in msg
    assert "退出码：1" in msg
    assert prefix[0] in msg


def test_build_csharp_missing_source_raises(tmp_path, monkeypatch):
    prefix, _ = fake_csc(tmp_path, monkeypatch)

    with pytest.raises(tb.CSharpBuildError) as ei:
        tb.build_csharp(tmp_path / "nope.cs", compiler=prefix)

    assert "nope.cs" in str(ei.value)


def test_build_csharp_missing_compiler_raises(tmp_path):
    src = tmp_path / "_t.cs"
    src.write_text("// x", encoding="utf-8")

    with pytest.raises(tb.CSharpBuildError) as ei:
        tb.build_csharp(src, compiler=[str(tmp_path / "no_such_csc.exe")])

    assert "编译器" in str(ei.value)


def test_ensure_csharp_prefers_prebuilt_exe(tmp_path, monkeypatch):
    """仓库里已有新鲜 exe 时不该动编译器（发布包带 exe 也能直接跑）。"""
    src = tmp_path / "_gyu_tool.cs"
    src.write_text("// x", encoding="utf-8")
    exe = tmp_path / "_gyu_tool.exe"
    exe.write_bytes(b"MZprebuilt")
    os.utime(src, (1_000_000, 1_000_000))
    os.utime(exe, (2_000_000, 2_000_000))
    monkeypatch.setattr(tb, "CSHARP", {"gyu": tb.CSharpSource(
        key="gyu", source_name="_gyu_tool.cs", exe_name="_gyu_tool.exe",
        purpose="fake")})
    monkeypatch.setattr(tb, "_REPO", tmp_path)
    prefix, log = fake_csc(tmp_path, monkeypatch)

    got = tb.ensure_csharp("gyu", compiler=prefix)

    assert got == exe
    assert csc_calls(log) == 0


def test_csharp_and_tools_registries_agree():
    """CSHARP 与 TOOLS 不能各说各话；源码必须真在仓库里（防拼错文件名）。"""
    for key, spec in tb.CSHARP.items():
        assert key in tb.TOOLS, f"{key} 在 CSHARP 里但没进 TOOLS"
        assert tb.TOOLS[key].exe_name == spec.exe_name
        assert spec.exe_name.endswith(".exe")
        assert (tb.repo_root() / spec.source_name).is_file(), \
            f"{spec.source_name} 不在仓库根（CSHARP 里拼错了？）"
        assert spec.platform in {"anycpu", "x86", "x64"}


def test_ensure_csharp_unknown_key_raises():
    with pytest.raises(KeyError):
        tb.ensure_csharp("no-such-key")
    with pytest.raises(KeyError):
        tb.run_csharp("no-such-key")


def test_run_csharp_judges_by_products(tmp_path, monkeypatch):
    """★核心★ run_csharp 端到端：现编拿 exe → 调用 → **按产物判定成败**。

    自带工具都是「扫一棵树 → 另存一棵树」，rc=0 而 0 产物完全可能发生，
    所以它必须走和 run() 同一套判定。
    """
    # 用 python.exe 冒充编好的 exe（复制成 <stem>.exe，ensure_csharp 就会直接复用）
    exe = tmp_path / "_gyu_tool.exe"
    shutil.copy2(sys.executable, exe)
    src = tmp_path / "_gyu_tool.cs"
    src.write_text("// x", encoding="utf-8")
    os.utime(src, (1_000_000, 1_000_000))
    monkeypatch.setattr(tb, "CSHARP", {"gyu": tb.CSharpSource(
        key="gyu", source_name="_gyu_tool.cs", exe_name="_gyu_tool.exe",
        purpose="fake")})
    monkeypatch.setattr(tb, "_REPO", tmp_path)
    decoder = make_fake_tool(tmp_path, "decoder.py", FAKE_DECODER)
    root = tmp_path / "game"
    root.mkdir()
    (root / "a.gyu").write_bytes(b"GYU")
    (root / "b.gyu").write_bytes(b"GYU")
    out = tmp_path / "out"
    out.mkdir()

    r = tb.run_csharp("gyu", [str(decoder), str(root), str(out)],
                      product_dir=out, min_products=2)

    assert r.ok, r.reason
    assert r.products.total == 2
    assert r.key == "gyu"
    assert sorted(p.name for p in out.iterdir()) == ["a.png", "b.png"]


# ---------------------------------------------------------------------------
# 自检 CLI
# ---------------------------------------------------------------------------


def test_check_all_shape():
    rows = tb.check_all()
    assert len(rows) == len(tb.TOOLS)
    for r in rows:
        assert set(r) >= {"key", "exe_name", "found", "sync", "notes"}
        assert r["found"], f"{r['key']} 在本机找不到：{r.get('error')}"


def test_check_all_counts_source_shipped_tool_as_usable(tmp_path, monkeypatch):
    """★核心★ 自带 C# 工具 exe 缺失、但源码在且 csc 在 → 算可用（用时会现编）。

    否则「源码随包」的干净检出会被 check 误报成缺工具，用户会去到处找 exe。
    """
    src = tmp_path / "_gyu_tool.cs"
    src.write_text("// fake\n", encoding="utf-8")
    monkeypatch.setattr(tb, "CSHARP", {"gyu": tb.CSharpSource(
        key="gyu", source_name="_gyu_tool.cs", exe_name="_gyu_tool.exe",
        purpose="fake")})
    monkeypatch.setattr(tb, "_REPO", tmp_path)
    monkeypatch.setattr(tb, "_csc_path", lambda: Path(r"C:\fake\csc.exe"))
    real_find = tb.find_tool

    def fake_find(key, override=None):
        if key == "gyu":                      # 模拟「干净检出，exe 还没编出来」
            raise tb.ToolNotFound("找不到工具 'gyu'（_gyu_tool.exe）")
        return real_find(key, override)

    monkeypatch.setattr(tb, "find_tool", fake_find)

    row = next(r for r in tb.check_all() if r["key"] == "gyu")

    assert row["found"] is True
    assert row.get("buildable") is True
    assert "现编" in row["path"]


def test_check_csharp_reports_stale_exe(tmp_path, monkeypatch):
    src = tmp_path / "_hg3_tool.cs"
    src.write_text("// fake\n", encoding="utf-8")
    exe = tmp_path / "_hg3_tool.exe"
    exe.write_bytes(b"MZ")
    os.utime(exe, (1_000_000, 1_000_000))          # exe 比源码旧
    os.utime(src, (2_000_000, 2_000_000))
    monkeypatch.setattr(tb, "CSHARP", {"hg3": tb.CSharpSource(
        key="hg3", source_name="_hg3_tool.cs", exe_name="_hg3_tool.exe",
        purpose="fake")})
    monkeypatch.setattr(tb, "_REPO", tmp_path)

    row = tb.check_csharp()[0]

    assert row["stale"] is True
    assert row["ready"] is True, "过期但编译器在 → 仍算可用（会重编）"


def test_check_csharp_ready_requires_compiler_or_fresh_exe(tmp_path, monkeypatch):
    src = tmp_path / "_hg3_tool.cs"
    src.write_text("// fake\n", encoding="utf-8")
    monkeypatch.setattr(tb, "CSHARP", {"hg3": tb.CSharpSource(
        key="hg3", source_name="_hg3_tool.cs", exe_name="_hg3_tool.exe",
        purpose="fake")})
    monkeypatch.setattr(tb, "_REPO", tmp_path)
    monkeypatch.setattr(tb, "_csc_path", lambda: None)

    row = tb.check_csharp()[0]

    assert row["exe_found"] is False and row["compiler"] is None
    assert row["ready"] is False


def test_cli_where_unknown_returns_nonzero(capsys):
    assert tb._main(["where", "no-such-tool"]) == 1


# ---------------------------------------------------------------------------
# 随包工具解析（bin/<key>/<exe>，2026-11-02 用户要求外部工具随包集成）
# ---------------------------------------------------------------------------

def test_bundled_bin_wins_over_builtin_candidates(tmp_path, monkeypatch):
    """随包 bin/<key>/<exe> 在内置候选**之前**命中——装机即用，不依赖开发机布局。"""
    bundled = tmp_path / "bin" / "garbro"
    bundled.mkdir(parents=True)
    (bundled / "GARbro.Console.exe").write_bytes(b"fake")
    monkeypatch.setattr(tb, "_bin_root", lambda: tmp_path / "bin")

    assert tb.find_tool("garbro") == bundled / "GARbro.Console.exe"


def test_bundled_bin_missing_falls_through_to_candidates(tmp_path, monkeypatch):
    """bin 档没有 → 落到内置候选，不能抛、也不能返回 bin 下的坏路径。"""
    monkeypatch.setattr(tb, "_bin_root", lambda: tmp_path / "emptybin")

    hit = tb.find_tool("garbro")          # 本机内置候选存在；换机器找不到则 ToolNotFound
    assert str(hit).lower() != str(tmp_path / "emptybin").lower()


def test_bin_root_none_when_absent(tmp_path, monkeypatch):
    """源码态仓库根没有 bin/ → 返回 None，解析顺序直接跳过这一档。"""
    monkeypatch.setattr(tb, "_REPO", tmp_path)   # tmp 下没有 bin/
    assert tb._bin_root() is None
