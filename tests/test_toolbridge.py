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
import sys
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


def test_all_five_tools_registered():
    """阶段 1 要求覆盖 5 个工具，少一个就红。"""
    assert set(tb.TOOLS) == {"garbro", "tlg2png", "ffprobe", "assetstudio", "krkr"}
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
# 自检 CLI
# ---------------------------------------------------------------------------


def test_check_all_shape():
    rows = tb.check_all()
    assert len(rows) == 5
    for r in rows:
        assert set(r) >= {"key", "exe_name", "found", "sync", "notes"}


def test_cli_where_unknown_returns_nonzero(capsys):
    assert tb._main(["where", "no-such-tool"]) == 1
