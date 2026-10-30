#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator 的测试。

重心不是「真游戏能不能跑通」（那靠 tests/test_orchestrator_smoke.py 与本机样本），
而是**编排契约有没有被守住**：

  1. 退出码语义：0 全通过 / 1 阶段失败或对账有差 / 2 引擎判出但没链路 / 3 未命中
  2. 对账必须到 0（纪律 2）：diff != 0 一律 rc=1，不许「差不多」
  3. counts 三段式（software-plan §2 定案）：raw / final / converted 各是什么口径
  4. final 必须**吃掉** raw 里的中间格式（.tlg），并接上 png/ 的成品
  5. verify 的 0 字节比例护栏：少量占位放行，大面积 0 字节必须判失败

不依赖任何外部 exe 或真实游戏：图片用 Pillow 现造，ffprobe 用 monkeypatch，
extract 阶段用 monkeypatch 注入（真解包链路由 smoke 测试覆盖）。

跑法：`python -m pytest tests/test_orchestrator.py -q`
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402

FIXTURES = ROOT / "_fixtures"


# ---------------------------------------------------------------------------
# 脚手架
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path, **kw) -> orch.Ctx:
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    return orch.Ctx(
        game_dir=kw.pop("game_dir", tmp_path / "game"),
        out_dir=out,
        work_dir=out / "_work",
        manifest_path=out / "manifest.json",
        **kw,
    )


def _write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _png(path: Path, size=(4, 4)) -> Path:
    """造一个**真** PNG（Pillow verify() 能过的）。"""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def _fake_stage(name: str, **data) -> orch.Stage:
    return orch.Stage(name, ok=True, seconds=0.01, detail="fake", data=data)


# ---------------------------------------------------------------------------
# 1. _final_files：final 口径（吃掉中间格式 + 接上 png/）
# ---------------------------------------------------------------------------


def test_final_files_drops_convertible_and_adds_png(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.png")
    _write(ctx.raw_dir / "b.tlg")
    _write(ctx.raw_dir / "sub" / "c.ogg")
    _png(ctx.png_dir / "b.png")

    labels = sorted(label for _p, label in orch._final_files(ctx))
    # .tlg 被 postprocess 消费掉 → 不进 final；转出的 png/ 进 final
    assert labels == sorted(["raw/a.png", "raw/sub/c.ogg", "png/b.png"])


def test_final_files_tlg_excluded_even_without_png(tmp_path):
    """转换失败时 .tlg 仍然不算成品 —— 它没被消费成功，但也不是交付物。

    这种情况由 postprocess 阶段判失败，_final_files 只负责口径。
    """
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "b.tlg")
    assert orch._final_files(ctx) == []


def test_final_files_missing_dirs_is_empty(tmp_path):
    ctx = _ctx(tmp_path)
    assert orch._final_files(ctx) == []


def test_final_files_ignores_directories(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.raw_dir / "emptydir").mkdir(parents=True)
    _write(ctx.raw_dir / "a.ogg")
    assert [lbl for _p, lbl in orch._final_files(ctx)] == ["raw/a.ogg"]


# ---------------------------------------------------------------------------
# 2. build_manifest：counts 三段式
# ---------------------------------------------------------------------------


def test_manifest_counts_three_sections(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.png")
    _write(ctx.raw_dir / "b.tlg")
    _write(ctx.raw_dir / "c.ogg")
    _png(ctx.png_dir / "b.png")

    stages = [
        _fake_stage("extract", archives=[
            {"archive": "data.xp3", "expected": 3, "got": 3}], expected_total=3),
        _fake_stage("postprocess", tool="tlg2png", **{"in": 1}, ok=1, fail=0),
        _fake_stage("verify", verified=True, image_ok=2, image_fail=0,
                    audio_ok=1, audio_fail=0, video_ok=0, video_fail=0,
                    zero_byte=0, media_minutes=1.5),
    ]
    man = orch.build_manifest(ctx, stages, "KiriKiri")

    assert man["counts"]["raw"]["total"] == 3
    assert man["counts"]["raw"]["by_ext"] == {".ogg": 1, ".png": 1, ".tlg": 1}

    # final = raw 去掉 .tlg(1) + png/ 的成品(1) = 3，且不含 .tlg
    assert man["counts"]["final"]["total"] == 3
    assert ".tlg" not in man["counts"]["final"]["by_ext"]
    assert man["counts"]["final"]["by_ext"] == {".ogg": 1, ".png": 2}

    # converted 解释 raw 与 final 的差额来源
    assert man["counts"]["converted"] == {".tlg": 1}

    # 图片成品数 = raw 里的 png + 转换出来的 png（交付口径，不是 raw 的 1）
    assert man["counts"]["final"]["by_ext"][".png"] == 2

    # reconcile 现在带 method：能区分「真对过账」与「没有地面真相」，
    # 不许把「没验」伪装成「验过了」
    assert man["reconcile"] == {"expected": 3, "actual": 3, "diff": 0,
                               "method": "archive-index"}
    assert man["source"]["archives"] == [
        {"name": "data.xp3", "entries": 3, "extracted": 3}]
    assert man["engine"] == "KiriKiri"
    assert man["png_dir"]["total"] == 1


def test_manifest_reconcile_diff_reported(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    _write(ctx.raw_dir / "b.ogg")
    stages = [_fake_stage("extract", archives=[
        {"archive": "data.xp3", "expected": 3, "got": 2}], expected_total=3)]
    man = orch.build_manifest(ctx, stages, "KiriKiri")
    assert man["reconcile"]["diff"] == -1


def test_manifest_reconcile_none_when_expected_unknown(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    man = orch.build_manifest(ctx, [_fake_stage("extract")], "Ren'Py")
    assert man["reconcile"]["expected"] is None
    assert man["reconcile"]["diff"] is None
    # 必须留下「为什么没对账」的痕迹
    assert man["reconcile"]["method"] == "no-index-available"


def test_manifest_no_postprocess_when_skipped(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    stages = [_fake_stage("postprocess", _skipped=True)]
    man = orch.build_manifest(ctx, stages, "Ren'Py")
    assert man["postprocess"] == []


def test_manifest_is_json_serialisable(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    man = orch.build_manifest(ctx, [_fake_stage("extract", expected_total=1)], "Ren'Py")
    json.dumps(man, ensure_ascii=False)  # 不抛就是过


def test_manifest_source_carries_unsupported_when_present(tmp_path):
    """有意排除的东西要写进 `source.unsupported`——下游看 source，不会翻 stages。"""
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    unsupported = [{"pattern": "*.ogg", "count": 22, "reason": "加密未解密"}]
    stages = [_fake_stage("extract", expected_total=1, unsupported=unsupported)]
    man = orch.build_manifest(ctx, stages, "ExHIBIT")
    assert man["source"]["unsupported"] == unsupported


def test_manifest_source_omits_unsupported_when_empty(tmp_path):
    """没有排除项时不留空字段（别的链路 manifest 形状不变）。"""
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    man = orch.build_manifest(ctx, [_fake_stage("extract", expected_total=1)], "Ren'Py")
    assert "unsupported" not in man["source"]


# ---------------------------------------------------------------------------
# 3. verify：0 字节护栏 + 成败判据
# ---------------------------------------------------------------------------


def test_verify_skipped_by_flag(tmp_path):
    ctx = _ctx(tmp_path, do_verify=False)
    _write(ctx.raw_dir / "a.ogg")
    st = orch.stage_verify(ctx)
    assert st.ok and st.skipped
    assert st.data == {"verified": False}


def test_verify_empty_output_is_failure(tmp_path):
    ctx = _ctx(tmp_path)
    st = orch.stage_verify(ctx)
    assert not st.ok
    assert "没有可验收的产物" in st.detail


def test_verify_good_png_passes(tmp_path):
    ctx = _ctx(tmp_path)
    _png(ctx.raw_dir / "a.png")
    st = orch.stage_verify(ctx)
    assert st.ok, st.detail
    assert st.data["image_ok"] == 1 and st.data["image_fail"] == 0


def test_verify_corrupt_png_fails(tmp_path):
    """扩展名是 .png 但内容不是图 → 必须判失败，不能靠退出码蒙混。"""
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "bad.png", b"this is definitely not a png")
    st = orch.stage_verify(ctx)
    assert not st.ok
    assert st.data["image_fail"] == 1


def test_verify_zero_byte_within_limit_is_tolerated(tmp_path):
    """少量 0 字节是源包声明的占位（Swipe Right 实测 5 个），不算失败。"""
    ctx = _ctx(tmp_path)
    _png(ctx.raw_dir / "ok.png")
    for i in range(3):
        _write(ctx.raw_dir / f"empty{i}.ogg", b"")
    st = orch.stage_verify(ctx)
    assert st.ok, st.detail
    assert st.data["zero_byte"] == 3
    assert st.data["image_ok"] == 1


def test_verify_zero_byte_over_limit_fails(tmp_path):
    """大面积 0 字节 = 解包坏了，比例护栏必须拦住。"""
    ctx = _ctx(tmp_path)
    _png(ctx.raw_dir / "ok.png")
    for i in range(12):                       # limit = max(10, 1% ) = 10
        _write(ctx.raw_dir / f"empty{i}.ogg", b"")
    st = orch.stage_verify(ctx)
    assert not st.ok
    assert st.data["zero_byte"] == 12


def test_verify_zero_limit_scales_with_file_count(tmp_path):
    """1% 的护栏：200 个文件时上限是 max(10, 2) = 10，不是死写 10。"""
    ctx = _ctx(tmp_path)
    _png(ctx.raw_dir / "ok.png")
    for i in range(11):
        _write(ctx.raw_dir / f"empty{i}.ogg", b"")
    st = orch.stage_verify(ctx)
    assert not st.ok


def test_verify_uses_ffprobe_for_av_and_counts_minutes(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg", b"OggS" + b"0" * 100)
    _write(ctx.raw_dir / "b.mp4", b"...." + b"0" * 100)

    def fake_ffprobe(path, **_kw):
        if path.suffix.lower() == ".ogg":
            return {"kind": "audio", "codec": "vorbis", "dur": 60.0}
        return {"kind": "video", "codec": "h264", "dur": 30.0, "w": 640, "h": 480}

    monkeypatch.setattr(orch.tb, "ffprobe", fake_ffprobe)
    st = orch.stage_verify(ctx)
    assert st.ok, st.detail
    assert st.data["audio_ok"] == 1 and st.data["video_ok"] == 1
    assert st.data["media_minutes"] == 1.5


def test_verify_ffprobe_none_is_failure(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg", b"OggS" + b"0" * 100)
    monkeypatch.setattr(orch.tb, "ffprobe", lambda p, **k: None)
    st = orch.stage_verify(ctx)
    assert not st.ok
    assert st.data["audio_fail"] == 1


def test_verify_nonmedia_files_are_counted_not_failed(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "script.ks", b"*start")
    _write(ctx.raw_dir / "a.dll", b"MZ")
    st = orch.stage_verify(ctx)
    assert st.ok, st.detail
    assert st.data["nonmedia"] == 2


def test_verify_mos_is_treated_as_image(tmp_path):
    """AdvHD 的 `.mos` 内容就是**裸 PNG**（2026-10-30 实测 677/677 全部以
    `89 50 4E 47 0D 0A 1A 0A` 开头），所以必须按图片验收。

    为什么不放进 `IMG_EXT` 很危险：`.mos` 会落进 `nonmedia` 分支**被静默放过**，
    而 verify 照样报「失败 0」——交付清单凭空少验 677 张图，且从输出上看不出来。
    这是 `ラブラブお痴験バイト性活` 全链跑完后才发现的验收口径漏洞。
    """
    ctx = _ctx(tmp_path)
    ctx.raw_dir.mkdir(parents=True, exist_ok=True)
    # 注意不能直接 `_png(ctx.raw_dir / "cg.mos")`：Pillow 的 `save()` 靠扩展名
    # 选格式，`.mos` 不认识会 ValueError。真实场景里图片是解包出来的字节，
    # 所以这里显式指定 format="PNG"，正好也模拟「内容是 PNG、名字叫 .mos」。
    from PIL import Image
    Image.new("RGB", (4, 4), (10, 20, 30)).save(ctx.raw_dir / "cg.mos", format="PNG")
    _png(ctx.raw_dir / "bg.png")
    st = orch.stage_verify(ctx)
    assert st.ok, st.detail
    assert st.data["image_ok"] == 2
    assert st.data["image_fail"] == 0
    assert st.data["nonmedia"] == 0


# ---------------------------------------------------------------------------
# 4. postprocess：无 .tlg 是空操作
# ---------------------------------------------------------------------------


def test_postprocess_no_raw_dir_is_skipped(tmp_path):
    ctx = _ctx(tmp_path)
    st = orch.stage_postprocess(ctx)
    assert st.ok and st.skipped


def test_postprocess_without_tlg_is_skipped(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.png")
    st = orch.stage_postprocess(ctx)
    assert st.ok and st.skipped
    # 2026-10-30 起 CONVERTIBLE 有 .tlg/.pna 两种，提示文案随之改成「无待转格式」
    assert "无待转格式" in st.detail


def test_postprocess_failure_is_reported(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "b.tlg")
    monkeypatch.setattr(
        orch.tb, "tlg2png",
        lambda s, d, **k: orch.tb.ToolResult(
            key="tlg2png", exe=Path("x"), argv=[], returncode=0,
            stdout="", stderr="", seconds=0.0, timed_out=False,
            products=orch.tb.Products(), product_dir=None,
            ok=False, reason="产物不是合法 PNG"))
    st = orch.stage_postprocess(ctx)
    assert not st.ok
    assert st.data["fail"] == 1


# ---------------------------------------------------------------------------
# 5. 归档发现：顶层优先，顶层没有才递归
# ---------------------------------------------------------------------------


def test_renpy_archives_prefers_top_level(tmp_path):
    _write(tmp_path / "top.rpa")
    _write(tmp_path / "game" / "nested.rpa")
    got = orch._renpy_archives(tmp_path)
    assert [p.name for p in got] == ["top.rpa"]


def test_renpy_archives_falls_back_to_recursive(tmp_path):
    """Swipe Right 实测：4 个包全在 game/ 子目录，只 glob 顶层会 0 个。"""
    _write(tmp_path / "game" / "archive.rpa")
    _write(tmp_path / "game" / "img_resource.rpa")
    got = orch._renpy_archives(tmp_path)
    assert sorted(p.name for p in got) == ["archive.rpa", "img_resource.rpa"]


def test_renpy_archives_empty(tmp_path):
    assert orch._renpy_archives(tmp_path) == []


def test_kirikiri_xp3_prefers_top_level(tmp_path):
    _write(tmp_path / "data.xp3")
    _write(tmp_path / "sub" / "movie.xp3")
    assert [p.name for p in orch._kirikiri_xp3(tmp_path)] == ["data.xp3"]


def test_kirikiri_xp3_recursive_fallback(tmp_path):
    _write(tmp_path / "a" / "data.xp3")
    _write(tmp_path / "a" / "movie.xp3")
    assert sorted(p.name for p in orch._kirikiri_xp3(tmp_path)) == ["data.xp3", "movie.xp3"]


# ---------------------------------------------------------------------------
# 5b. --reuse-raw：跳过解包 ≠ 跳过对账
# ---------------------------------------------------------------------------


def test_kirikiri_reuse_raw_still_reconciles(tmp_path, monkeypatch):
    """★回归护栏★ 复用 raw 时必须仍用索引算地面真相并对账。

    实测 bug（2026-10-29）：复跑时 extract 直接 return，没填 expected_total，
    导致 manifest 的 reconcile 变成 `期望 None vs 落盘 2562 (diff=None)`
    —— 明明 GARbro 能列出条目，却把「没对账」当成结果。
    """
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "out" / "raw")
    _write(ctx.raw_dir / "a.ogg")
    _write(ctx.raw_dir / "b.ogg")
    _write(ctx.game_dir / "data.xp3")

    monkeypatch.setattr(orch, "_kirikiri_xp3", lambda _d: [ctx.game_dir / "data.xp3"])
    monkeypatch.setattr(orch.tb, "garbro_list", lambda _p, **_kw: (True, 2, ""))

    st = orch.stage_extract_kirikiri(ctx)

    assert st.ok is True
    assert st.skipped is True
    assert st.data["expected_total"] == 2
    assert st.data["actual_total"] == 2
    assert "对账 2 == 2" in st.detail


def test_kirikiri_reuse_raw_fails_on_mismatch(tmp_path, monkeypatch):
    """复用产物与索引对不上 → 必须判失败（不是静默通过）。"""
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "out" / "raw")
    _write(ctx.raw_dir / "a.ogg")           # 只有 1 个，索引说 2 个
    _write(ctx.game_dir / "data.xp3")

    monkeypatch.setattr(orch, "_kirikiri_xp3", lambda _d: [ctx.game_dir / "data.xp3"])
    monkeypatch.setattr(orch.tb, "garbro_list", lambda _p, **_kw: (True, 2, ""))

    st = orch.stage_extract_kirikiri(ctx)

    assert st.ok is False
    assert "对账失败" in st.detail


def test_kirikiri_reuse_raw_leaves_expected_none_when_unlistable(tmp_path, monkeypatch):
    """加密 xp3 列不出条目 → expected 保持 None（manifest 标 no-index-available）。"""
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "out" / "raw")
    _write(ctx.raw_dir / "a.ogg")
    _write(ctx.game_dir / "data.xp3")

    monkeypatch.setattr(orch, "_kirikiri_xp3", lambda _d: [ctx.game_dir / "data.xp3"])
    monkeypatch.setattr(orch.tb, "garbro_list", lambda _p, **_kw: (False, 0, "unknown format"))

    st = orch.stage_extract_kirikiri(ctx)

    assert st.ok is True, "列不出条目不是失败，只是没对账"
    assert "expected_total" not in st.data
    assert st.data["archives"][0]["listable"] is False


# ---------------------------------------------------------------------------
# 6. run()：退出码语义与对账闸门
# ---------------------------------------------------------------------------


def test_run_rc2_when_engine_has_no_chain(tmp_path):
    """引擎判得出但没实现链路 → rc=2（不是 0，也不是 1）。"""
    ctx = _ctx(tmp_path, engine="Unity")
    rc, res = orch.run(ctx)
    assert rc == 2
    assert res["error"] == "chain-not-implemented"
    assert res["engine"] == "Unity"


def test_run_rc3_when_detect_fails(tmp_path):
    """unknown_game fixture 里没有任何引擎特征 → rc=3。"""
    game = FIXTURES / "unknown_game"
    if not game.is_dir():
        pytest.skip("缺 _fixtures/unknown_game")
    ctx = _ctx(tmp_path, game_dir=game)
    rc, res = orch.run(ctx)
    assert rc == 3
    assert res["error"] == "detect-failed"


def test_run_rc1_when_reconcile_has_diff(tmp_path, monkeypatch):
    """对账有差就是失败 —— 纪律 2 的闸门，不许「差不多」。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def fake_extract(c):
        _write(c.raw_dir / "a.ogg")
        _write(c.raw_dir / "b.ogg")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 3, "got": 2}], expected_total=3)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))
    monkeypatch.setattr(orch, "stage_verify",
                        lambda c: _fake_stage("verify", verified=True,
                                              image_ok=0, image_fail=0,
                                              audio_ok=0, audio_fail=0,
                                              video_ok=0, video_fail=0,
                                              zero_byte=0, media_minutes=0.0))
    rc, man = orch.run(ctx)
    assert rc == 1
    assert man["reconcile"]["diff"] == -1


def test_run_rc0_when_everything_reconciles(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def fake_extract(c):
        _png(c.raw_dir / "a.png")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 1, "got": 1}], expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))
    rc, man = orch.run(ctx)
    assert rc == 0, man
    assert man["ok"] is True
    assert man["reconcile"]["diff"] == 0
    assert ctx.manifest_path.exists()
    assert json.loads(ctx.manifest_path.read_text(encoding="utf-8"))["engine"] == "Ren'Py"


def test_run_rc1_when_verify_fails(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def fake_extract(c):
        _write(c.raw_dir / "bad.png", b"nope")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 1, "got": 1}], expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))
    rc, res = orch.run(ctx)
    assert rc == 1
    assert res["error"] == "verify-failed"


def test_run_forced_engine_skips_detect(tmp_path, monkeypatch):
    """--engine 强制指定时不该再调 detect（省时间、也避开样本缺失）。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")
    called = {"n": 0}

    def boom(c):
        called["n"] += 1
        raise AssertionError("不该调 detect")

    monkeypatch.setattr(orch, "stage_detect", boom)
    monkeypatch.setattr(orch, "stage_extract_renpy",
                        lambda c: _fake_stage("extract", expected_total=0))
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))
    orch.run(ctx)
    assert called["n"] == 0


def test_run_rc3_when_detect_raises_does_not_crash(tmp_path, monkeypatch):
    """detect 内部异常要变成 rc=3，不能把整个编排器炸掉。"""
    ctx = _ctx(tmp_path)

    def boom(c):
        raise RuntimeError("scan 挂了")

    monkeypatch.setattr(orch.gd, "scan", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("scan 挂了")))
    rc, res = orch.run(ctx)
    assert rc == 3


# ---------------------------------------------------------------------------
# 7. Ctx / CLI 契约
# ---------------------------------------------------------------------------


def test_ctx_paths(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.raw_dir == ctx.out_dir / "raw"
    assert ctx.png_dir == ctx.out_dir / "png"


def test_ctx_log_writes_file(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.log("detect", "hello")
    ctx.log("detect", "world")
    text = (ctx.work_dir / "detect.log").read_text(encoding="utf-8")
    assert text.splitlines() == ["hello", "world"]


def test_stage_as_dict_flattens_data():
    st = orch.Stage("extract", ok=True, seconds=1.234, detail="d", data={"a": 1})
    d = st.as_dict()
    assert d["stage"] == "extract" and d["a"] == 1
    assert d["seconds"] == 1.23


def test_implemented_engines_are_detectable():
    """IMPLEMENTED 里每个引擎都必须能被 dispatch 真判出来。

    否则就是「声称支持但永远不会触发」——和 dispatch 那条 ADVICE 护栏同理。
    """
    import galgame_dispatch as gd

    for engine in orch.IMPLEMENTED:
        assert engine in gd.ADVICE, f"{engine} 没有 ADVICE 条目"


def test_main_dry_run_unknown_fixture_returns_3(tmp_path):
    game = FIXTURES / "unknown_game"
    if not game.is_dir():
        pytest.skip("缺 _fixtures/unknown_game")
    rc = orch.main([str(game), "--out", str(tmp_path / "o"), "--dry-run"])
    assert rc == 3


def test_main_dry_run_known_fixture_returns_0(tmp_path):
    game = FIXTURES / "renpy_game"
    if not game.is_dir():
        pytest.skip("缺 _fixtures/renpy_game")
    rc = orch.main([str(game), "--out", str(tmp_path / "o"), "--dry-run"])
    assert rc == 0


def test_main_missing_game_dir_returns_3(tmp_path):
    rc = orch.main([str(tmp_path / "nope"), "--out", str(tmp_path / "o")])
    assert rc == 3


def test_main_requires_out(tmp_path):
    with pytest.raises(SystemExit):
        orch.main([str(FIXTURES / "renpy_game")])


# ---------------------------------------------------------------------------
# RPG Maker / Yu-Ris 链路（阶段 2 新增）
# ---------------------------------------------------------------------------

def _make_www(tmp_path: Path) -> Path:
    """造一个最小 www/：System.json + 2 个加密媒体 + 1 个明文媒体 + 1 个非媒体。"""
    www = tmp_path / "game" / "www"
    (www / "data").mkdir(parents=True, exist_ok=True)
    # 必须带 encryptionKey 且声明加密，否则解包器会（正确地）报错退出
    (www / "data" / "System.json").write_text(
        '{"encryptionKey": "d41d8cd98f00b204e9800998ecf8427e",'
        ' "hasEncryptedImages": true, "hasEncryptedAudio": true}',
        encoding="utf-8")
    # 加密体：假头 16B + 原[0:16] XOR key（这里内容不重要，只要走 decrypt 分支）
    (www / "img").mkdir(parents=True, exist_ok=True)
    (www / "img" / "a.rpgmvp").write_bytes(b"RPGMV" + b"\x00" * 11 + b"\x11" * 16 + b"tail")
    (www / "audio").mkdir(parents=True, exist_ok=True)
    (www / "audio" / "b.rpgmvo").write_bytes(b"RPGMV" + b"\x00" * 11 + b"\x22" * 16 + b"tail")
    # 明文媒体：照收
    (www / "img" / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    # 非媒体：不进候选
    (www / "notes.txt").write_text("hi", encoding="utf-8")
    return www


def test_find_www_locates_nested(tmp_path):
    www = _make_www(tmp_path)
    assert orch._find_www(tmp_path / "game") == www


def test_find_www_returns_none_when_absent(tmp_path):
    (tmp_path / "game").mkdir()
    assert orch._find_www(tmp_path / "game") is None


def test_rpgmaker_extract_reconciles_against_candidate_count(tmp_path):
    """地面真相 = 候选文件数（与解包器共用 iter_candidates，别各写一套）。"""
    _make_www(tmp_path)
    ctx = _ctx(tmp_path)
    st = orch.stage_extract_rpgmaker(ctx)
    assert st.ok, st.detail
    # 2 个加密 + 1 个明文 png = 3（notes.txt 不算）
    assert st.data["expected_total"] == 3
    assert st.data["actual_total"] == 3
    assert st.data["reconcile_ok"] is True


def test_rpgmaker_extract_fails_when_www_missing(tmp_path):
    (tmp_path / "game").mkdir()
    st = orch.stage_extract_rpgmaker(_ctx(tmp_path))
    assert not st.ok
    assert "www" in st.detail


def test_rpgmaker_reuse_raw_still_reconciles(tmp_path):
    """复用模式跳解包但**不跳对账**（KiriKiri 侧踩过这个坑）。"""
    _make_www(tmp_path)
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "out" / "raw")
    _write(ctx.raw_dir / "a.png")
    _write(ctx.raw_dir / "b.ogg")
    _write(ctx.raw_dir / "c.png")
    st = orch.stage_extract_rpgmaker(ctx)
    assert st.skipped and st.ok
    assert st.data["expected_total"] == 3
    assert "对账 3 == 3" in st.detail


def test_rpgmaker_reuse_raw_fails_on_mismatch(tmp_path):
    _make_www(tmp_path)
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "out" / "raw")
    _write(ctx.raw_dir / "a.png")  # 只有 1 个，期望 3
    st = orch.stage_extract_rpgmaker(ctx)
    assert not st.ok
    assert "对账失败" in st.detail


def test_yuris_extract_fails_without_ypf(tmp_path):
    (tmp_path / "game").mkdir()
    st = orch.stage_extract_yuris(_ctx(tmp_path))
    assert not st.ok
    assert "ypf" in st.detail.lower()


def test_yuris_extract_reconciles_per_archive(tmp_path, monkeypatch):
    """逐包对账：地面真相来自 _ypf_extract.read_index()（与解包器共用表解析）。"""
    game = tmp_path / "game"
    game.mkdir()
    (game / "cg.ypf").write_bytes(b"YPF\x00")
    (game / "data.ypf").write_bytes(b"YPF\x00")

    class _E:
        def __init__(self, n):
            self.n = n

    monkeypatch.setattr(orch.ypf, "read_index",
                        lambda p: (0x1EE, [_E(0)] * (2 if p.name == "cg.ypf" else 3), 0xFF, b""))

    def _fake_run(argv, **kw):
        # argv = [python, _ypf_extract.py, <ypf>, <dest>, --manifest, <man>]
        dest = Path(argv[3])
        n = 2 if "cg.ypf" in argv[2] else 3
        dest.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (dest / f"f{i}.png").write_bytes(b"x")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    monkeypatch.setattr(orch.subprocess, "run", _fake_run)

    st = orch.stage_extract_yuris(_ctx(tmp_path))
    assert st.ok, st.detail
    assert st.data["expected_total"] == 5
    assert st.data["actual_total"] == 5
    assert len(st.data["archives"]) == 2


def test_yuris_reuse_raw_fails_on_mismatch(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    (game / "cg.ypf").write_bytes(b"YPF\x00")

    class _E:
        pass

    monkeypatch.setattr(orch.ypf, "read_index", lambda p: (0x1EE, [_E(), _E()], 0xFF, b""))
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "out" / "raw")
    _write(ctx.raw_dir / "only.png")  # 1 vs 期望 2
    st = orch.stage_extract_yuris(ctx)
    assert not st.ok
    assert "对账失败" in st.detail


def test_extractors_map_covers_every_implemented_engine():
    """IMPLEMENTED 与 EXTRACTORS 必须同步——漏一个就会在运行时才炸。"""
    assert set(orch.EXTRACTORS) == set(orch.IMPLEMENTED)


def test_extractors_stores_names_not_functions():
    """存名字而不是函数对象：存对象会在 import 时把引用焊死，monkeypatch 就失效。"""
    for engine, name in orch.EXTRACTORS.items():
        assert isinstance(name, str), f"{engine} 存的不是函数名"
        assert callable(getattr(orch, name, None)), f"{name} 在模块里不存在"


# ---------------------------------------------------------------------------
# 9. AdvHD 链路：逐 .arc 提取 + 散装 .dat→.wmv + .pna 逐帧 carve
# ---------------------------------------------------------------------------

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_frame(payload: bytes = b"body") -> bytes:
    """造一个 carve() 认得的「PNG 帧」：签名 … `IEND` + 4 字节 CRC。

    `_pna_carve.carve()` 只按签名起、`IEND` 止来切，不做 CRC 校验，
    所以这里不需要合法 PNG。真要能过 Pillow 的图另有 `_png()`。
    """
    return PNG_SIG + payload + b"IEND" + b"\x00\x00\x00\x00"


def _fake_tool_result(ok: bool = True, n: int = 0, reason: str = "") -> orch.tb.ToolResult:
    return orch.tb.ToolResult(
        key="garbro", exe=Path("GARbro.Console.exe"), argv=[], returncode=0 if ok else 1,
        stdout="", stderr="", seconds=0.0, timed_out=False,
        products=orch.tb.Products(total=n, by_ext={".ogg": n}, size=0),
        product_dir=None, ok=ok, reason=reason)


def test_advhd_arcs_prefers_top_level(tmp_path):
    game = tmp_path / "game"
    _write(game / "a.arc")
    _write(game / "sub" / "b.arc")
    got = [p.name for p in orch._advhd_arcs(game)]
    assert got == ["a.arc"], "顶层有 .arc 就不该递归"


def test_advhd_arcs_recursive_fallback(tmp_path):
    game = tmp_path / "game"
    _write(game / "sub" / "b.arc")
    got = [p.name for p in orch._advhd_arcs(game)]
    assert got == ["b.arc"]


def test_advhd_loose_movies_only_top_level_and_renamed_wmv(tmp_path):
    """散装 .dat 只在顶层找、并且必须改名 .wmv。

    递归会把 save/ 下的 .dat 也当视频；不改名则 .dat 不在 AV_EXT 白名单里，
    verify 会当「非媒体文件」放过去，交付清单留一个谁都验不了的扩展名。
    """
    game = tmp_path / "game"
    _write(game / "op.dat")
    _write(game / "save" / "sys.dat")
    got = orch._advhd_loose_movies(game)
    assert [src.name for src, _ in got] == ["op.dat"]
    assert got[0][1].name == "op.wmv"


def test_advhd_extract_reconciles_and_converts_dat(tmp_path, monkeypatch):
    game = tmp_path / "game"
    _write(game / "a.arc")
    _write(game / "b.arc")
    _write(game / "op.dat", b"\x30\x26\xb2\x75")

    entries = {"a.arc": 3, "b.arc": 2}
    monkeypatch.setattr(orch.tb, "garbro_list",
                        lambda p, **k: (True, entries[p.name], ""))
    monkeypatch.setattr(orch.tb, "garbro_extract",
                        lambda arc, dest, **k: (_write_n(dest, entries[arc.name]),
                                                _fake_tool_result(True, entries[arc.name]))[1])

    ctx = _ctx(tmp_path, game_dir=game)
    st = orch.stage_extract_advhd(ctx)
    assert st.ok, st.detail
    # 地面真相 = 3 + 2 个 arc 条目 + 1 个散装 .dat
    assert st.data["expected_total"] == 6
    assert st.data["actual_total"] == 6
    assert st.data["loose_movies"] == 1
    assert (ctx.raw_dir / "op.wmv").is_file()
    assert not (ctx.raw_dir / "op.dat").exists(), ".dat 必须改名成 .wmv，别两个都留"


def _write_n(dest: Path, n: int, ext: str = ".ogg") -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (dest / f"f{i}{ext}").write_bytes(b"x")


def test_advhd_extract_fails_when_short(tmp_path, monkeypatch):
    game = tmp_path / "game"
    _write(game / "a.arc")
    monkeypatch.setattr(orch.tb, "garbro_list", lambda p, **k: (True, 3, ""))
    monkeypatch.setattr(orch.tb, "garbro_extract",
                        lambda arc, dest, **k: (_write_n(dest, 2), _fake_tool_result(True, 2))[1])
    st = orch.stage_extract_advhd(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "对账失败" in st.detail


def test_advhd_extract_reports_garbro_extract_failure(tmp_path, monkeypatch):
    game = tmp_path / "game"
    _write(game / "a.arc")
    monkeypatch.setattr(orch.tb, "garbro_list", lambda p, **k: (True, 3, ""))
    monkeypatch.setattr(orch.tb, "garbro_extract",
                        lambda arc, dest, **k: _fake_tool_result(False, 0, "产物不足"))
    st = orch.stage_extract_advhd(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "GARbro 提取失败" in st.detail


def test_advhd_reuse_raw_still_reconciles(tmp_path, monkeypatch):
    """跳过解包 ≠ 跳过对账：复用模式照样要拿索引比落盘数。"""
    game = tmp_path / "game"
    _write(game / "a.arc")
    monkeypatch.setattr(orch.tb, "garbro_list", lambda p, **k: (True, 2, ""))
    ctx = _ctx(tmp_path, game_dir=game, reuse_raw=tmp_path / "out" / "raw")
    _write_n(ctx.raw_dir / "a", 2)
    st = orch.stage_extract_advhd(ctx)
    assert st.ok, st.detail
    assert st.data["expected_total"] == 2
    assert "对账 2 == 2" in st.detail


def test_advhd_reuse_raw_fails_on_mismatch(tmp_path, monkeypatch):
    game = tmp_path / "game"
    _write(game / "a.arc")
    monkeypatch.setattr(orch.tb, "garbro_list", lambda p, **k: (True, 2, ""))
    ctx = _ctx(tmp_path, game_dir=game, reuse_raw=tmp_path / "out" / "raw")
    _write_n(ctx.raw_dir / "a", 1)
    st = orch.stage_extract_advhd(ctx)
    assert not st.ok
    assert "复用产物对账失败" in st.detail


def test_advhd_unlistable_archive_marks_unverified(tmp_path, monkeypatch):
    """有 .arc 列不出条目 = 没有完整地面真相，不许把「没验」当「验过了」。"""
    game = tmp_path / "game"
    _write(game / "a.arc")
    monkeypatch.setattr(orch.tb, "garbro_list",
                        lambda p, **k: (False, 0, "unknown format"))
    st = orch.stage_extract_advhd(_ctx(tmp_path, game_dir=game))
    assert st.ok
    assert "expected_total" not in st.data
    assert st.data["archives"][0]["listable"] is False


def test_advhd_no_archive_at_all_is_error(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    st = orch.stage_extract_advhd(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "既没有 .arc 也没有 .dat" in st.detail


def test_postprocess_carves_pna_into_multiple_frames(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "anime.pna",
           b"PNAP" + _png_frame(b"a") + _png_frame(b"b") + _png_frame(b"c"))
    st = orch.stage_postprocess(ctx)
    assert st.ok, st.detail
    assert st.data["kinds"] == {".pna": 1}
    assert st.data["frames_out"] == 3, "一个 .pna 要能产出多帧，不是一对一"
    names = sorted(p.name for p in (ctx.png_dir).glob("*.png"))
    assert names == ["anime__f000.png", "anime__f001.png", "anime__f002.png"]


def test_postprocess_pna_without_frames_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "empty.pna", b"PNAP" + b"no png here")
    st = orch.stage_postprocess(ctx)
    assert not st.ok
    assert st.data["fail"] == 1


def test_convertible_has_single_source_of_truth():
    """orchestrator 的 CONVERTIBLE 必须引用 manifest 的，不许各写一份。

    两处各写一份，一边按 .tlg 算 final、另一边按 .tlg+.pna 算，交付数字就对不上。
    """
    import manifest

    assert orch.CONVERTIBLE == manifest.CONVERTIBLE
    assert {".tlg", ".pna"} <= orch.CONVERTIBLE


# ---------------------------------------------------------------------------
# 10. ExHIBIT 链路：.gyu 解码 + .grp 切分 + 散装媒体 + 加密 BGM 如实上报
# ---------------------------------------------------------------------------

def _aifs_toc(entries: list[tuple[int, int]], *, arc_num: int = 1) -> bytes:
    """造一个最小 AiFS TOC：1 个块，块的 `num` = `arc_num`（数据包在 TOC 里排第几）。

    布局（`_grp_extract.py` 与 GARbro ArcGRP.cs 一致）：`AiFS` 头 4 字节、
    `res_count` 在 0xC、块自 0x10 起 `{i32 num, u32 start_index, u32 _, u32 count}`
    + `count × (u32 offset, u32 size)`。
    """
    head = bytearray(b"AiFS" + b"\x00" * 12)   # 头 4 字节 + 填充到 0x10，res_count 在 0xC
    struct.pack_into("<i", head, 0xC, 1)
    head += struct.pack("<iIII", arc_num, 1, 0, len(entries))
    for offset, size in entries:
        head += struct.pack("<II", offset, size)
    return bytes(head)


def _exhibit_game(tmp_path: Path, *, gyu_n: int = 2, ogg_n: int = 2,
                  encrypted_n: int = 1) -> Path:
    """造一个最小 ExHIBIT 目录：1 个数据包 + TOC + .gyu + 散装媒体 + 加密 BGM。

    每个 ogg 条目 12 字节（`OggS` + 8 字节载荷），所以 offset 按 12 递进——
    真跑 `_grp_extract` 时切出来的头必须还是 `OggS`，否则它自己会判「头异常」。
    """
    game = tmp_path / "game"
    res = game / "res"
    entries = [(i * 12, 12) for i in range(ogg_n)]
    _write(res / "res2001.grp", b"".join(b"OggS" + bytes([i]) * 8 for i in range(ogg_n)))
    _write(res / "res2000.grp", _aifs_toc(entries))
    for i in range(gyu_n):
        _write(res / "g" / f"{i:08d}.gyu", b"GYU\x1a")
    for i in range(encrypted_n):
        # 加密 BGM：头不是 OggS（§15.3 实测：前 3853 字节被加密，魔数直接没了）
        _write(res / "s" / "m" / f"m{i:02d}.ogg", b"\x00\x01encrypted")
    _write(res / "s" / "e" / "001.wav", b"RIFF")
    _write(res / "g" / "ev" / "op.wmv", b"\x30\x26\xb2\x75")
    return game


class _FakeProc:
    def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, err


def _fake_grp_run(n_ogg: int, rc: int = 0, seen: list | None = None):
    """冒充 `subprocess.run` 跑 `_grp_extract.py`：造 n_ogg 个产物，返回假 proc。"""
    def _run(cmd, **_kw):
        if seen is not None:
            seen.append(list(cmd))
        if rc == 0:
            _write_n(Path(cmd[3]) / "res2001", n_ogg)
        return _FakeProc(rc, "ok", "boom" if rc else "")
    return _run


def _fake_run_csharp(n_png: int, seen: list | None = None, raises: Exception | None = None):
    def _run(key, argv=(), *, build=None, **kw):
        if seen is not None:
            seen.append({"key": key, "argv": list(argv), "kw": dict(kw)})
        if raises is not None:
            raise raises
        dest = Path(kw.get("product_dir") or argv[1])
        _write_n(dest, n_png, ext=".png")
        return _fake_tool_result(n_png > 0, n_png)
    return _run


def test_exhibit_res_dir_finds_res_and_returns_none_without_grp(tmp_path):
    game = _exhibit_game(tmp_path)
    assert orch._exhibit_res_dir(game) == game / "res"
    bare = tmp_path / "bare"
    bare.mkdir()
    assert orch._exhibit_res_dir(bare) is None


def test_exhibit_ogg_encryption_is_judged_by_magic(tmp_path):
    """加密判据必须是魔数，不是路径——换一作路径会变，魔数不会。"""
    plain = _write(tmp_path / "a.ogg", b"OggS\x00\x02")
    enc = _write(tmp_path / "b.ogg", b"\x00\x01\x02\x03")
    assert not orch._exhibit_ogg_is_encrypted(plain)
    assert orch._exhibit_ogg_is_encrypted(enc)


def test_exhibit_loose_media_excludes_encrypted_ogg(tmp_path):
    game = _exhibit_game(tmp_path, encrypted_n=1)
    rels = sorted(rel.as_posix() for _src, rel in orch._exhibit_loose_media(game))
    assert rels == ["loose/res/g/ev/op.wmv", "loose/res/s/e/001.wav"], \
        "加密 ogg 不能进 loose（它解不开），明文 wav/wmv 必须进"
    enc = orch._exhibit_encrypted_ogg(game)
    assert [p.name for p in enc] == ["m00.ogg"]


def test_exhibit_expected_sums_three_sources(tmp_path):
    game = _exhibit_game(tmp_path, gyu_n=3, ogg_n=2, encrypted_n=1)
    expected, listable, per_archive = orch._exhibit_expected(game)
    assert expected == 3 + 2 + 2, "3 个 gyu + 2 条 grp + 2 个散装（wav + wmv）"
    assert listable
    assert [a["archive"] for a in per_archive][:2] == ["(res/g + userdata/*.gyu)",
                                                       "res2001.grp"]
    assert per_archive[1]["toc"] == "res2000.grp"


def test_exhibit_extract_reconciles_and_calls_both_tools(tmp_path, monkeypatch):
    game = _exhibit_game(tmp_path, gyu_n=2, ogg_n=2, encrypted_n=1)
    gyu_calls: list = []
    grp_calls: list = []
    monkeypatch.setattr(orch.tb, "run_csharp",
                        _fake_run_csharp(2, seen=gyu_calls))
    monkeypatch.setattr(orch.subprocess, "run",
                        _fake_grp_run(2, seen=grp_calls))

    ctx = _ctx(tmp_path, game_dir=game)
    st = orch.stage_extract_exhibit(ctx)
    assert st.ok, st.detail
    assert st.data["expected_total"] == st.data["actual_total"] == 6, \
        "2 个 gyu + 2 条 grp + 2 个散装媒体（001.wav + op.wmv）"
    # 接线：gyu 工具扫的是**游戏目录**，产物落 raw/img
    assert gyu_calls[0]["key"] == "gyu"
    assert gyu_calls[0]["argv"] == [str(game), str(ctx.raw_dir / "img")]
    # 接线：grp 工具拿 res 目录，产物落 raw/audio，并带 --manifest
    assert grp_calls[0][2] == str(game / "res")
    assert grp_calls[0][3] == str(ctx.raw_dir / "audio")
    assert "--manifest" in grp_calls[0]
    # 加密 BGM 如实上报，且**不在 raw 里**
    assert st.data["unsupported"][0]["count"] == 1
    assert "加密未解密" in st.detail
    assert not list(ctx.raw_dir.rglob("*.ogg")) or \
        all("m00" not in p.name for p in ctx.raw_dir.rglob("*.ogg"))


def test_exhibit_extract_fails_when_gyu_short(tmp_path, monkeypatch):
    """`.gyu` 少解了几张 → 工具判失败 → extract 不许假装成功。"""
    game = _exhibit_game(tmp_path, gyu_n=3, ogg_n=2)
    monkeypatch.setattr(orch.tb, "run_csharp", _short_csharp)
    monkeypatch.setattr(orch.subprocess, "run", _fake_grp_run(2))
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "_gyu_tool 解码失败" in st.detail


def _short_csharp(key, argv=(), **kw):
    """只写 1 张图但判失败（模拟「工具少产出、产物判定拦住」）。"""
    dest = Path(kw.get("product_dir") or argv[1])
    _write_n(dest, 1, ext=".png")
    return _fake_tool_result(False, 1, "产物不足：期望 3 实际 1")


def test_exhibit_extract_fails_on_count_mismatch(tmp_path, monkeypatch):
    """工具**没报错**但少产出（1 张 vs 期望 2 张）→ 对账必须拦住。

    这是最危险的一类：退出码 0、工具自认成功，只有数产物才能发现。
    """
    game = _exhibit_game(tmp_path, gyu_n=2, ogg_n=2, encrypted_n=0)
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(1))
    monkeypatch.setattr(orch.subprocess, "run", _fake_grp_run(2))
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "对账失败" in st.detail
    assert st.data["expected_total"] == 6


def test_exhibit_extract_reports_csharp_build_failure(tmp_path, monkeypatch):
    """C# 编译失败必须把原因带出来（`CSharpBuildError` 里有 csc 路径与 stderr）。"""
    game = _exhibit_game(tmp_path, gyu_n=1)
    monkeypatch.setattr(orch.tb, "run_csharp",
                        _fake_run_csharp(0, raises=orch.tb.CSharpBuildError(
                            "编译失败：\n命令：csc.exe\nstderr：boom")))
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "无法启用" in st.detail and "boom" in st.detail


def test_exhibit_extract_fails_when_grp_rc_nonzero(tmp_path, monkeypatch):
    game = _exhibit_game(tmp_path, gyu_n=1, ogg_n=2)
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(1))
    monkeypatch.setattr(orch.subprocess, "run", _fake_grp_run(0, rc=2))
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "_grp_extract.py 失败" in st.detail


def test_exhibit_reuse_raw_still_reconciles(tmp_path, monkeypatch):
    """跳过解包 ≠ 跳过对账：复用模式照样按三条来源重算期望。"""
    game = _exhibit_game(tmp_path, gyu_n=2, ogg_n=2, encrypted_n=0)
    ctx = _ctx(tmp_path, game_dir=game, reuse_raw=tmp_path / "out" / "raw")
    _write_n(ctx.raw_dir / "img", 2, ext=".png")
    _write_n(ctx.raw_dir / "audio" / "res2001", 2)
    _write(ctx.raw_dir / "loose" / "res" / "s" / "e" / "001.wav")
    _write(ctx.raw_dir / "loose" / "res" / "g" / "ev" / "op.wmv")
    monkeypatch.setattr(orch.tb, "run_csharp",
                        lambda *a, **k: pytest.fail("复用模式不该再调工具"))
    monkeypatch.setattr(orch.subprocess, "run",
                        lambda *a, **k: pytest.fail("复用模式不该再调工具"))
    st = orch.stage_extract_exhibit(ctx)
    assert st.ok, st.detail
    assert st.data["expected_total"] == 6
    assert "对账 6 == 6" in st.detail


def test_exhibit_reuse_raw_fails_on_mismatch(tmp_path, monkeypatch):
    game = _exhibit_game(tmp_path, gyu_n=2, ogg_n=2, encrypted_n=0)
    ctx = _ctx(tmp_path, game_dir=game, reuse_raw=tmp_path / "out" / "raw")
    _write_n(ctx.raw_dir / "img", 1, ext=".png")
    monkeypatch.setattr(orch.tb, "run_csharp", lambda *a, **k: None)
    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: None)
    st = orch.stage_extract_exhibit(ctx)
    assert not st.ok
    assert "复用产物对账失败" in st.detail


def test_exhibit_no_source_at_all_is_error(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "既没有 .gyu" in st.detail


def test_exhibit_unlistable_grp_marks_unverified(tmp_path):
    """有 .grp 找不到 TOC = 没有完整地面真相，明说，别假装对过账。"""
    game = tmp_path / "game"
    _write(game / "res" / "res2001.grp", b"OggS" + b"\x00" * 8)
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert st.ok
    assert "expected_total" not in st.data
    assert any(a["listable"] is False for a in st.data["archives"])


# ---------------------------- _grp_extract.py 本体（真解析真落盘） ----------

def test_grp_expected_counts_matches_toc_entries(tmp_path):
    import _grp_extract as grp

    game = _exhibit_game(tmp_path, ogg_n=3)
    exp = grp.expected_counts(game / "res")
    assert exp["total"] == 3
    assert exp["by_arc"] == {"res2001.grp": 3}
    assert exp["unlistable"] == []
    assert exp["arcs"] == ["res2001.grp"], "AiFS 文件本身是 TOC，不是数据包"


def test_grp_zero_size_entries_are_not_counted(tmp_path):
    """`size == 0` 是占位，不算条目——与切分时的 `if size` 必须同一口径。"""
    import _grp_extract as grp

    res = tmp_path / "res"
    _write(res / "res2001.grp", b"OggS" + b"\x00" * 20)
    _write(res / "res2000.grp", _aifs_toc([(0, 12), (12, 0), (12, 12)]))
    exp = grp.expected_counts(res)
    assert exp["total"] == 2


def test_grp_main_writes_manifest_and_reconciles(tmp_path):
    """真跑一遍 `_grp_extract.main`：切出来的 ogg 头合法、manifest 对账为 0。"""
    import json as _json

    import _grp_extract as grp

    game = _exhibit_game(tmp_path, ogg_n=3)
    out = tmp_path / "audio"
    man = tmp_path / "grp.manifest.json"
    rc = grp.main([str(game / "res"), str(out), "--manifest", str(man)])
    assert rc == 0
    assert sorted(p.name for p in (out / "res2001").iterdir()) == \
        ["00001.ogg", "00002.ogg", "00003.ogg"]
    rec = _json.loads(man.read_text(encoding="utf-8"))
    assert rec["counts"]["raw"]["total"] == 3
    assert rec["reconcile"] == {"expected": 3, "actual": 3, "diff": 0,
                               "method": "archive-index"}
    assert rec["engine"] == "ExHIBIT"


def test_grp_main_reports_bad_ogg_head_as_failure(tmp_path):
    """切出来的头不是 OggS/RIFF → 算失败（别把噪声当音频交付）。"""
    import _grp_extract as grp

    res = tmp_path / "res"
    _write(res / "res2001.grp", b"XXXX" + b"\x00" * 8)
    _write(res / "res2000.grp", _aifs_toc([(0, 12)]))
    rc = grp.main([str(res), str(tmp_path / "out")])
    assert rc == 1


# ---------------------------------------------------------------------------
# 11. CatSystem2 链路
# ---------------------------------------------------------------------------


def _cs2_exp(by_arc: dict, unlistable: list | None = None) -> dict:
    """冒充 `cs2.expected_counts()` 的返回（真解析由 tests/test_cs2_int_extract.py 覆盖）。"""
    return {"total": sum(by_arc.values()), "by_arc": dict(by_arc),
            "unlistable": list(unlistable or []), "arcs": sorted(by_arc)}


def _fake_cs2_extract(per_arc: dict, rc: int = 0, seen: list | None = None):
    """冒充 `subprocess.run` 跑 `_cs2_int_extract.py`：按 `raw/<包名>/` 造产物。

    argv 形状 = `[python, _cs2_int_extract.py, <game>, <out>, --manifest, <path>]`，
    所以输出目录是 `cmd[3]`。
    """
    def _run(cmd, **_kw):
        if seen is not None:
            seen.append(list(cmd))
        if rc == 0:
            for name, n in per_arc.items():
                dest = Path(cmd[3]) / Path(name).stem
                for i in range(n):
                    _write(dest / f"f{i:03d}.ogg", b"OggS" + b"x" * 8)
        return _FakeProc(rc, "ok", "boom" if rc else "")
    return _run


def test_cs2_extract_reconciles_per_archive(tmp_path, monkeypatch):
    """★核心★ 两层对账：逐包（raw/<包名> vs 索引声明）+ 总计。"""
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts",
                        lambda root: _cs2_exp({"pcm_AA.int": 2, "pcm_BB.int": 3}))
    seen: list = []
    monkeypatch.setattr(orch.subprocess, "run",
                        _fake_cs2_extract({"pcm_AA.int": 2, "pcm_BB.int": 3}, seen=seen))

    st = orch.stage_extract_cs2(ctx)

    assert st.ok, st.detail
    assert st.data["expected_total"] == 5
    assert st.data["actual_total"] == 5
    assert [a["got"] for a in st.data["archives"]] == [2, 3]
    assert "对账 0 差（逐包 2/2）" in st.detail
    assert "2 个 .int" in st.detail
    assert seen[0][1].endswith("_cs2_int_extract.py")
    assert seen[0][3] == str(ctx.raw_dir)
    assert "--manifest" in seen[0]


def test_cs2_extract_fails_on_per_archive_mismatch_even_when_total_matches(tmp_path, monkeypatch):
    """★核心★ 总数对得上、逐包错位 —— 只看总数就漏了，必须逐包比。"""
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts",
                        lambda root: _cs2_exp({"a.int": 2, "b.int": 3}))
    monkeypatch.setattr(orch.subprocess, "run",
                        _fake_cs2_extract({"a.int": 3, "b.int": 2}))

    st = orch.stage_extract_cs2(ctx)

    assert not st.ok
    assert "逐包对账失败" in st.detail
    assert "a.int(索引 2 vs 落盘 3)" in st.detail


def test_cs2_extract_fails_when_total_mismatches(tmp_path, monkeypatch):
    """逐包都对，但 raw 里多了 [[不属任何包]] 的东西 → 总计对不上，仍然判失败。

    （`expected_total` 是各包之和，所以「逐包全对」时只可能因为**多出来的散落文件**而总计不符。）
    """
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts", lambda root: _cs2_exp({"a.int": 2}))
    monkeypatch.setattr(orch.subprocess, "run", _fake_cs2_extract({"a.int": 2}))
    _write(ctx.raw_dir / "stray.ogg", b"OggS" + b"x" * 8)      # 不属于任何包

    st = orch.stage_extract_cs2(ctx)

    assert not st.ok
    assert "对账失败：索引 2 vs 落盘 3" in st.detail


def test_cs2_extract_fails_when_tool_rc_nonzero(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts", lambda root: _cs2_exp({"a.int": 1}))
    monkeypatch.setattr(orch.subprocess, "run",
                        _fake_cs2_extract({}, rc=1))

    st = orch.stage_extract_cs2(ctx)

    assert not st.ok
    assert "_cs2_int_extract.py 失败（rc=1）" in st.detail


def test_cs2_reuse_raw_still_reconciles(tmp_path, monkeypatch):
    """`--reuse-raw` 跳的是解包，不是验收：地面真相照算、仍对账，工具不许被调用。"""
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "elsewhere")
    monkeypatch.setattr(orch.cs2, "expected_counts", lambda root: _cs2_exp({"a.int": 2}))
    for i in range(2):
        _write(ctx.raw_dir / "a" / f"f{i}.ogg", b"OggS" + b"x" * 8)

    def _boom(*_a, **_kw):
        pytest.fail("--reuse-raw 时不该再调 _cs2_int_extract.py")

    monkeypatch.setattr(orch.subprocess, "run", _boom)
    st = orch.stage_extract_cs2(ctx)

    assert st.ok, st.detail
    assert "对账 0 差" in st.detail


def test_cs2_reuse_raw_fails_on_mismatch(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "elsewhere")
    monkeypatch.setattr(orch.cs2, "expected_counts", lambda root: _cs2_exp({"a.int": 3}))
    _write(ctx.raw_dir / "a" / "f0.ogg", b"OggS" + b"x" * 8)

    st = orch.stage_extract_cs2(ctx)

    assert not st.ok
    assert "对账失败" in st.detail


def test_cs2_extract_unlistable_grp_marks_unverified(tmp_path, monkeypatch):
    """有包列不出条目 → 地面真相不完整，**不写 expected_total**、明说「未对账」。"""
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts",
                        lambda root: _cs2_exp({"a.int": 2}, unlistable=["weird.int"]))
    monkeypatch.setattr(orch.subprocess, "run", _fake_cs2_extract({"a.int": 2}))

    st = orch.stage_extract_cs2(ctx)

    assert st.ok, st.detail
    assert "expected_total" not in st.data
    assert st.data["unlistable"] == ["weird.int"]
    assert "未对账" in st.detail


def test_cs2_extract_no_int_is_error(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts", lambda root: _cs2_exp({}))

    st = orch.stage_extract_cs2(ctx)

    assert not st.ok
    assert "没有 KIF 格式的 .int" in st.detail


# ---------------------------------------------------------------- 后处理

def test_cs2_normalize_exts_renames_by_magic(tmp_path):
    """`.KCC` 的 OggS 要变成 `.ogg`，认不出的 `.bin` 一律不动。"""
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "pcm" / "aa_01.ogg", b"OggS" + b"\x00" * 8)      # 名字对，不动
    _write(ctx.raw_dir / "pcm" / "aa_02.KCC", b"OggS" + b"\x00" * 8)      # 名字骗人
    _write(ctx.raw_dir / "pcm" / "aa_03.HLx", b"LPD\x00" + b"\x00" * 8)   # 数据文件
    _write(ctx.raw_dir / "pcm" / "aa_04.xyz", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)

    info = orch._cs2_normalize_exts(ctx.raw_dir)

    assert info["renamed"] == 2
    assert info["kept"] == 0
    assert sorted(p.name for p in (ctx.raw_dir / "pcm").iterdir()) == \
        ["aa_01.ogg", "aa_02.ogg", "aa_03.HLx", "aa_04.png"]
    assert info["kinds"][".ogg"] == 1 and info["kinds"][".png"] == 1


def test_cs2_normalize_exts_keeps_name_when_target_exists(tmp_path):
    """★不许因为改名而覆盖已有文件★：目标是别人的名字时保留原名（宁可名字难看）。"""
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "aa.KCC", b"OggS" + b"\x00" * 8)      # 想改成 aa.ogg
    _write(ctx.raw_dir / "aa.ogg", b"OggS" + b"\x00" * 8)      # 但它已经被占了

    info = orch._cs2_normalize_exts(ctx.raw_dir)

    assert info["renamed"] == 0
    assert info["kept"] == 1
    assert (ctx.raw_dir / "aa.KCC").is_file()      # 原文件还在
    assert (ctx.raw_dir / "aa.ogg").read_bytes() == b"OggS" + b"\x00" * 8


def test_cs2_postprocess_without_hg3_normalizes_and_is_not_skipped(tmp_path):
    """没有 HG-3 要转，但扩展名归一是**真做了工作** —— `ok` 但**不算 skip**。"""
    ctx = _ctx(tmp_path, engine="CatSystem2")
    _write(ctx.raw_dir / "a.KCC", b"OggS" + b"\x00" * 8)

    st = orch.stage_postprocess(ctx)

    assert st.ok
    assert st.skipped is False          # 归一改了一个文件，不是「无事可做」
    assert st.data["renamed"] == 1
    assert "无 HG-3" in st.detail
    assert ctx.consumed == []


def test_cs2_postprocess_converts_hg3_and_records_consumed(tmp_path, monkeypatch):
    """★核心★ HG-3 → png/，并把 raw 里那些中间产物记进 `consumed`（按路径排除，不删）。"""
    ctx = _ctx(tmp_path, engine="CatSystem2")
    _write(ctx.raw_dir / "ch" / "a.hg3", b"HG-3" + b"\x00" * 8)
    _write(ctx.raw_dir / "ch" / "a.nm3", b"HG-3" + b"\x00" * 8)   # 与 a.hg3 同 stem → 撞车
    _write(ctx.raw_dir / "ch" / "c.ogg", b"OggS" + b"\x00" * 8)
    seen: list = []
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(1, seen=seen))

    st = orch.stage_postprocess(ctx)

    assert st.ok, st.detail
    assert seen[0]["key"] == "hg3"
    assert seen[0]["argv"] == [str(ctx.raw_dir), str(ctx.png_dir)]
    assert seen[0]["kw"]["min_products"] == 1          # 去重后的张数，不是 2
    assert st.data["collisions"] == 1
    assert st.data["consumed"] == ["ch/a.hg3", "ch/a.nm3"]
    assert ctx.consumed == ["ch/a.hg3", "ch/a.nm3"]
    assert (ctx.raw_dir / "ch" / "a.hg3").is_file()    # 不删：raw 还要对账
    assert "HG-3 2 个 → png/ 1 张" in st.detail
    assert "撞车 1 个" in st.detail


def test_cs2_postprocess_fails_when_png_count_short(tmp_path, monkeypatch):
    """★核心★ rc=0、产物也不是 0，只是比该有的少 —— 只有拿产出数跟期望数硬比才看得见。"""
    ctx = _ctx(tmp_path, engine="CatSystem2")
    _write(ctx.raw_dir / "a.hg3", b"HG-3" + b"\x00" * 8)
    _write(ctx.raw_dir / "b.hg3", b"HG-3" + b"\x00" * 8)
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(1))

    st = orch.stage_postprocess(ctx)

    assert not st.ok
    assert "产物数不符：期望 2 vs 落盘 1" in st.detail
    assert ctx.consumed == []          # 判失败就不认领交付口径


def test_cs2_postprocess_reports_csharp_build_failure(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, engine="CatSystem2")
    _write(ctx.raw_dir / "a.hg3", b"HG-3" + b"\x00" * 8)
    monkeypatch.setattr(orch.tb, "run_csharp",
                        _fake_run_csharp(0, raises=orch.tb.CSharpBuildError(
                            "编译失败：csc 路径 …；stderr：boom")))

    st = orch.stage_postprocess(ctx)

    assert not st.ok
    assert "无法启用" in st.detail and "boom" in st.detail


def test_postprocess_dispatches_to_cs2_only_for_catsystem2(tmp_path):
    """分派按 `ctx.engine`：别的引擎不该走 CatSystem2 那条魔数路线。"""
    ctx = _ctx(tmp_path, engine="AdvHD")
    _write(ctx.raw_dir / "a.hg3", b"HG-3" + b"\x00" * 8)
    st = orch.stage_postprocess(ctx)
    assert st.ok and st.skipped                 # AdvHD 分支：无 .tlg/.pna → 跳过
    assert "无待转格式" in st.detail


def test_run_sets_ctx_engine_so_postprocess_can_dispatch(tmp_path, monkeypatch):
    """★ `run()` 必须回填 `ctx.engine`：否则自动判出的引擎在后处理里是 None，分派失效。"""
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch, "stage_detect",
                        lambda c: orch.Stage("detect", ok=True, detail="CatSystem2 (score=100)",
                                             data={"engine": "CatSystem2"}))
    monkeypatch.setattr(orch, "stage_extract_cs2",
                        lambda c: orch.Stage("extract", ok=True, data={"expected_total": 0}))
    monkeypatch.setattr(orch, "stage_verify",
                        lambda c: orch.Stage("verify", ok=True, detail="无产物",
                                             data={"verified": True}))
    monkeypatch.setattr(orch, "build_manifest", lambda *a, **k: {"reconcile": {"diff": 0}})
    monkeypatch.setattr(orch.manifest, "write", lambda *a, **k: None)

    rc, info = orch.run(ctx)

    assert ctx.engine == "CatSystem2"
    assert rc == 0, info


# ---------------------------------------------------------------- manifest

def test_manifest_carries_consumed_count_from_postprocess(tmp_path):
    """被消费掉多少中间产物要进 manifest（下游看 postprocess，不会去翻 stage data）。"""
    ctx = _ctx(tmp_path)
    stages = [
        _fake_stage("extract", expected_total=1),
        _fake_stage("postprocess", tool="_hg3_tool", **{"in": 2, "ok": 2, "fail": 0},
                    consumed=["a.hg3", "b.nm3"]),
    ]
    man = orch.build_manifest(ctx, stages, "CatSystem2")
    assert man["postprocess"][0]["consumed"] == 2


def test_manifest_omits_consumed_for_other_engines(tmp_path):
    ctx = _ctx(tmp_path)
    stages = [
        _fake_stage("extract", expected_total=1),
        _fake_stage("postprocess", tool="tlg2png", **{"in": 1, "ok": 1, "fail": 0}),
    ]
    man = orch.build_manifest(ctx, stages, "KiriKiri")
    assert "consumed" not in man["postprocess"][0]


def test_final_files_excludes_consumed(tmp_path):
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.hg3", b"HG-3" + b"\x00" * 8)
    _write(ctx.raw_dir / "a.ogg", b"OggS" + b"\x00" * 8)
    _png(ctx.png_dir / "a.png")
    ctx.consumed = ["a.hg3"]
    labels = [lab for _, lab in orch._final_files(ctx)]
    assert labels == ["raw/a.ogg", "png/a.png"]

