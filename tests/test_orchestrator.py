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
import time
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
    """跳过的后处理不该在 manifest 里留一条空记录。

    判据是 `Stage.skipped`（生产代码就是这么表达的）；批次 C3 删掉了旧的
    `data["_skipped"]` 判据 —— 那个 key 只有这条测试在手工塞，生产代码从来不写，
    属于「只存在于测试里的字段」，读代码的人会被骗。
    """
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg")
    stages = [orch.Stage("postprocess", ok=True, skipped=True, detail="跳过")]
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
    # reason=disabled 让 manifest.verify.status 判成 skipped 而不是 failed：
    # 「主动没验」和「验失败」必须能分开，否则 --no-verify 的正常运行会被记成失败。
    assert st.data == {"verified": False, "reason": "disabled"}


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
            return {"kind": "audio", "codec": "vorbis", "dur": 60.0}, "ok"
        return {"kind": "video", "codec": "h264", "dur": 30.0, "w": 640, "h": 480}, "ok"

    monkeypatch.setattr(orch.tb, "ffprobe_ex", fake_ffprobe)
    st = orch.stage_verify(ctx)
    assert st.ok, st.detail
    assert st.data["audio_ok"] == 1 and st.data["video_ok"] == 1
    assert st.data["media_minutes"] == 1.5


def test_verify_ffprobe_none_is_failure(tmp_path, monkeypatch):
    """★核心★ 探不出来要判失败，**且把原因写进 fail_examples**。

    `ffprobe 无结果` 一句话把「文件真坏」「子进程没起来/超时」「JSON 里没有
    音视频流」混成同一件事——看日志的人无从判断该不该慌。实测依据：
    `甜蜜女友2+` 全量验收里 `pcm_DD/dd_02_ch08_019.OGG` 报过一次无结果，
    同一份字节随后稳定探得 vorbis 流（Ogg 页 CRC 也对得上），是偶发不是坏文件。
    """
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "a.ogg", b"OggS" + b"0" * 100)
    monkeypatch.setattr(orch.tb, "ffprobe_ex",
                        lambda p, **k: (None, "rc=1：Invalid data found（重试 1 次仍失败）"))
    st = orch.stage_verify(ctx)
    assert not st.ok
    assert st.data["audio_fail"] == 1
    ex = st.data["fail_examples"]
    assert len(ex) == 1
    assert "ffprobe 无结果" in ex[0]
    assert "Invalid data found" in ex[0], "原因必须带出来，否则这句话等于没说"
    assert "重试 1 次仍失败" in ex[0]


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
    ctx = _ctx(tmp_path, engine="Tyrano/Electron")
    rc, res = orch.run(ctx)
    assert rc == 2
    assert res["error"] == "chain-not-implemented"
    assert res["engine"] == "Tyrano/Electron"


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

    def _fake_main(argv=None):
        # in-process：orchestrator 把 [ypf, dest, --manifest, man] 直接传给 main(argv)
        argv = list(argv or [])
        dest = Path(argv[1])
        n = 2 if "cg.ypf" in argv[0] else 3
        dest.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (dest / f"f{i}.png").write_bytes(b"x")
        return 0

    monkeypatch.setattr(orch.ypf, "main", _fake_main)

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
# 8.5 兄弟链路 in-process 护栏（PyInstaller 冻结，verified-findings §19.2）
# ---------------------------------------------------------------------------

#: 与解包器同级的 7 个兄弟模块（orchestrator 以 `_run_sibling(mod, argv)` in-process 调用）。
#: **别只在这里加**：orchestrator 顶部必须同时静态 import（PyInstaller 静态分析
#: 看不到动态 import，漏一个冻结包里就没有、启动即崩）。
SIBLING_MODULES = ("rpa_extract_organized", "krkr_auto_extract", "rpgmv", "ypf",
                   "grp", "cs2", "_as_audio_collect2")


def test_sibling_modules_statically_imported_and_no_py_spawn():
    """★冻结护栏★ ① orchestrator 代码里不许出现 `sys.executable` 取值或 subprocess 调用
    ——冻结后 `sys.executable` 是冻结点自己，`[sys.executable, "xxx.py"]` 变成
    「冻结点跑自己」（rc=2 unknown mode）；② 7 个兄弟模块必须在 orchestrator 顶部
    静态 import（hasattr 即证明）。

    用 AST 而不是文本匹配：docstring/注释里的「subprocess」字样是给人看的说明，不算违例。
    """
    import ast
    tree = ast.parse(Path(orch.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess", \
                    "orchestrator 不该再 import subprocess（外部 exe 一律走 toolbridge）"
        if isinstance(node, ast.Attribute):
            if (node.attr == "executable" and isinstance(node.value, ast.Name)
                    and node.value.id == "sys"):
                pytest.fail("orchestrator 又出现 sys.executable——冻结后会拿自己当解释器")
            if isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                pytest.fail(f"orchestrator 又出现 subprocess.{node.attr}——兄弟链路走 _run_sibling")
    for name in SIBLING_MODULES:
        assert hasattr(orch, name), f"orchestrator 没有静态 import {name}（冻结包会缺它）"


def test_sibling_main_uniform_interface():
    """兄弟模块统一 `main(argv: list[str] | None = None) -> int`（内部不 sys.exit）——
    `_run_sibling` 的降级逻辑全靠这个约定：argv=None 收 CLI、list 收编排器，
    返回 int 当 rc。签名漂移（比如又改回读 sys.argv）在这里先红。"""
    import inspect
    for name in SIBLING_MODULES:
        mod = getattr(orch, name)
        sig = inspect.signature(mod.main)
        params = list(sig.parameters.values())
        assert params and params[0].name == "argv" and params[0].default is None, \
            f"{name}.main 首参必须是 argv=None（现在是 {sig}）"
        assert sig.return_annotation in (int, "int"), \
            f"{name}.main 返回注解必须是 int（现在是 {sig.return_annotation!r}）"


def test_run_sibling_captures_output_rc_and_degrades():
    """`_run_sibling` 契约：正常 → (rc, 收进来的 stdout)；异常 → rc=1 + traceback 进输出；
    SystemExit 按其 code 折算。与子进程时代「rc + capture_output」的日志形态对齐。"""
    import types

    ok = types.SimpleNamespace(main=lambda argv: (print("hi"), 0)[1])
    assert orch._run_sibling(ok, ["a"]) == (0, "hi\n")

    boom = types.SimpleNamespace(
        main=lambda argv: (_ for _ in ()).throw(RuntimeError("xxx")))
    rc, out = orch._run_sibling(boom, [])
    assert rc == 1 and "RuntimeError" in out and "xxx" in out

    exit2 = types.SimpleNamespace(
        main=lambda argv: (_ for _ in ()).throw(SystemExit(2)))
    assert orch._run_sibling(exit2, [])[0] == 2

    exit_none = types.SimpleNamespace(
        main=lambda argv: (_ for _ in ()).throw(SystemExit(None)))
    assert orch._run_sibling(exit_none, [])[0] == 0

    silent = types.SimpleNamespace(main=lambda argv: None)   # 老式 main 忘了 return
    assert orch._run_sibling(silent, [])[0] == 0


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


def _fake_grp_main(n_ogg: int, rc: int = 0, seen: list | None = None):
    """冒充 `_grp_extract.main`：argv=[<res>, <audio_dst>, --manifest, <man>]，造 n_ogg 个产物。"""
    def _main(argv=None):
        argv = list(argv or [])
        if seen is not None:
            seen.append(argv)
        if rc == 0:
            _write_n(Path(argv[1]) / "res2001", n_ogg)
        return rc
    return _main


def _fake_run_csharp(n_png: int, seen: list | None = None, raises: Exception | None = None):
    def _run(key, argv=(), *, build=None, **kw):
        if seen is not None:
            seen.append({"key": key, "argv": list(argv), "kw": dict(kw)})
        if raises is not None:
            raise raises
        dest = Path(kw.get("product_dir") or argv[1])
        _write_n(dest, n_png, ext=".png")
        # 与 `toolbridge._run_exe` 同构：增量必须够 `min_products` 才算 ok
        # （min_products=0 时 0 个新增也算成功——复跑场景就靠它）
        return _fake_tool_result(n_png >= kw.get("min_products", 1), n_png)
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
    monkeypatch.setattr(orch.grp, "main",
                        _fake_grp_main(2, seen=grp_calls))

    ctx = _ctx(tmp_path, game_dir=game)
    st = orch.stage_extract_exhibit(ctx)
    assert st.ok, st.detail
    assert st.data["expected_total"] == st.data["actual_total"] == 6, \
        "2 个 gyu + 2 条 grp + 2 个散装媒体（001.wav + op.wmv）"
    # 接线：gyu 工具扫的是**游戏目录**，产物落 raw/img
    assert gyu_calls[0]["key"] == "gyu"
    assert gyu_calls[0]["argv"] == [str(game), str(ctx.raw_dir / "img")]
    # 接线：grp 工具拿 res 目录，产物落 raw/audio，并带 --manifest
    assert grp_calls[0][0] == str(game / "res")
    assert grp_calls[0][1] == str(ctx.raw_dir / "audio")
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
    monkeypatch.setattr(orch.grp, "main", _fake_grp_main(2))
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "_gyu_tool 解码失败" in st.detail


def _short_csharp(key, argv=(), **kw):
    """只写 1 张图但判失败（模拟「工具少产出、产物判定拦住」）。"""
    dest = Path(kw.get("product_dir") or argv[1])
    _write_n(dest, 1, ext=".png")
    return _fake_tool_result(False, 1, "产物不足：期望 3 实际 1")


def test_exhibit_extract_fails_on_count_mismatch(tmp_path, monkeypatch):
    """工具**没报错**但少产出 → 落盘对账必须拦住。

    这是最危险的一类：退出码 0、工具自认成功，只有**数产物**才能发现。
    两条网各管一段：gyu 的产物数由 `run_csharp(min_products=张数)` 拦；
    grp 的条目数只有落盘对账看得见（脚本 rc=0 却少切了几条）。
    """
    game = _exhibit_game(tmp_path, gyu_n=2, ogg_n=2, encrypted_n=0)
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(2))
    monkeypatch.setattr(orch.grp, "main", _fake_grp_main(1))    # 少切 1 条
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "对账失败" in st.detail
    assert st.data["expected_total"] == 6


def test_exhibit_extract_gyu_shortfall_is_caught_by_product_count(tmp_path, monkeypatch):
    """gyu 少产出时由 `run_csharp` 的产物计数先拦（`min_products` = 期望张数）。"""
    game = _exhibit_game(tmp_path, gyu_n=2, ogg_n=2, encrypted_n=0)
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(1))
    monkeypatch.setattr(orch.grp, "main", _fake_grp_main(2))
    st = orch.stage_extract_exhibit(_ctx(tmp_path, game_dir=game))
    assert not st.ok
    assert "_gyu_tool 解码失败" in st.detail


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
    monkeypatch.setattr(orch.grp, "main", _fake_grp_main(0, rc=2))
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
    monkeypatch.setattr(orch.grp, "main",
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
    monkeypatch.setattr(orch.grp, "main", lambda *a, **k: None)
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


def _fake_cs2_main(per_arc: dict, rc: int = 0, seen: list | None = None):
    """冒充 `_cs2_int_extract.main`：按 `raw/<包名>/` 造产物。

    argv 形状 = `[<game>, <out>, --manifest, <path>]`（in-process 直接传给 main），
    所以输出目录是 `argv[1]`。
    """
    def _main(argv=None):
        argv = list(argv or [])
        if seen is not None:
            seen.append(argv)
        if rc == 0:
            for name, n in per_arc.items():
                dest = Path(argv[1]) / Path(name).stem
                for i in range(n):
                    _write(dest / f"f{i:03d}.ogg", b"OggS" + b"x" * 8)
        return rc
    return _main


def test_cs2_extract_reconciles_per_archive(tmp_path, monkeypatch):
    """★核心★ 两层对账：逐包（raw/<包名> vs 索引声明）+ 总计。"""
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts",
                        lambda root: _cs2_exp({"pcm_AA.int": 2, "pcm_BB.int": 3}))
    seen: list = []
    monkeypatch.setattr(orch.cs2, "main",
                        _fake_cs2_main({"pcm_AA.int": 2, "pcm_BB.int": 3}, seen=seen))

    st = orch.stage_extract_cs2(ctx)

    assert st.ok, st.detail
    assert st.data["expected_total"] == 5
    assert st.data["actual_total"] == 5
    assert [a["got"] for a in st.data["archives"]] == [2, 3]
    assert "对账 0 差（逐包 2/2）" in st.detail
    assert "2 个 .int" in st.detail
    assert seen[0][0] == str(ctx.game_dir)
    assert seen[0][1] == str(ctx.raw_dir)
    assert "--manifest" in seen[0]


def test_cs2_extract_fails_on_per_archive_mismatch_even_when_total_matches(tmp_path, monkeypatch):
    """★核心★ 总数对得上、逐包错位 —— 只看总数就漏了，必须逐包比。"""
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts",
                        lambda root: _cs2_exp({"a.int": 2, "b.int": 3}))
    monkeypatch.setattr(orch.cs2, "main",
                        _fake_cs2_main({"a.int": 3, "b.int": 2}))

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
    monkeypatch.setattr(orch.cs2, "main", _fake_cs2_main({"a.int": 2}))
    _write(ctx.raw_dir / "stray.ogg", b"OggS" + b"x" * 8)      # 不属于任何包

    st = orch.stage_extract_cs2(ctx)

    assert not st.ok
    assert "对账失败：索引 2 vs 落盘 3" in st.detail


def test_cs2_extract_fails_when_tool_rc_nonzero(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(orch.cs2, "expected_counts", lambda root: _cs2_exp({"a.int": 1}))
    monkeypatch.setattr(orch.cs2, "main",
                        _fake_cs2_main({}, rc=1))

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

    monkeypatch.setattr(orch.cs2, "main", _boom)
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
    monkeypatch.setattr(orch.cs2, "main", _fake_cs2_main({"a.int": 2}))

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
    assert seen[0]["kw"]["min_products"] == 0, \
        "产物数由目录总量判，不能按增量判（复跑时增量天然是 0）"
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


def test_cs2_postprocess_rerun_with_existing_png_is_not_a_failure(tmp_path, monkeypatch):
    """★核心★ 复跑（png/ 里已有上一轮成品、本轮增量 0）不能判失败。

    真样本上撞到的坑：`--reuse-raw` 复跑时上一轮的 PNG 都还在，增量天然是 0；
    按增量判会在一次**完全正确**的解包上报「产物不足」。交付口径是「png/ 里的成品数
    等于去重后的期望数」，与「本轮新增了几个」无关。
    """
    ctx = _ctx(tmp_path, engine="CatSystem2")
    _write(ctx.raw_dir / "a.hg3", b"HG-3" + b"\x00" * 8)
    ctx.png_dir.mkdir(parents=True)
    _write(ctx.png_dir / "a.png", b"\x89PNG\r\n\x1a\n")     # 上一轮的成品
    seen: list = []
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(0, seen=seen))

    st = orch.stage_postprocess(ctx)

    assert st.ok, st.detail
    assert seen[0]["kw"]["min_products"] == 0
    assert st.data["new"] == 0              # 本轮没新增
    assert st.data["ok"] == 1               # 但目录总量是够的
    assert ctx.consumed == ["a.hg3"]        # 照样认领交付口径
    assert "png/ 1 张" in st.detail


def test_cs2_postprocess_case_only_collision_counts_once(tmp_path, monkeypatch):
    """只差大小写的两个 HG-3 在 NTFS 上是同一张 PNG（真样本里正好有 3 组）。"""
    ctx = _ctx(tmp_path, engine="CatSystem2")
    _write(ctx.raw_dir / "J_WJNu17n_0h.hg3", b"HG-3" + b"\x00" * 8)
    _write(ctx.raw_dir / "j_wjnU17N_0H.ml3", b"HG-3" + b"\x00" * 8)
    monkeypatch.setattr(orch.tb, "run_csharp", _fake_run_csharp(1))

    st = orch.stage_postprocess(ctx)

    assert st.ok, st.detail
    assert st.data["collisions"] == 1, "只差大小写 → 一张，不是两张"
    assert "png/ 1 张" in st.detail


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


# ==========================================================================
# 第 12 节：Unity 链路
# ==========================================================================

def _stub_audio_enum(monkeypatch, names=("clip_a", "clip_b"), collect_writes=True):
    """把「按名字枚举 + 补齐」换成不碰 AssetStudio 的确定路径。

    批次 C11 之后 `enumerate_names` 的语义是：`None`=枚举失败、`[]`=确认没有音频、
    非空=正常。这套 fixture 模拟的是**正常**那一支 —— 之前那些测试没管音频枚举，
    于是恰好落进「说有 N 个却一个名字都枚举不出来」的矛盾态，现在会（正确地）判失败。
    """
    monkeypatch.setattr(orch._as_audio_collect2, "enumerate_names",
                        lambda *a, **k: list(names))

    def fake_collect(src, dest, names_in, exe=None, batch=None, max_rounds=None,
                     log=None, work_root=None):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        if collect_writes:
            for n in names_in:
                (dest / f"{n}.wav").write_text("RIFF")
        return {"expected": len(names_in), "unique": len(names_in),
                "collected": len(names_in), "missing": [], "runs": 1}

    monkeypatch.setattr(orch._as_audio_collect2, "collect", fake_collect)


def test_unity_data_dir_finds_data_subdir(tmp_path):
    """`<游戏名>_Data` 目录是 Unity 的标志。"""
    game = tmp_path / "My Game"
    game.mkdir()
    data = game / "My Game_Data"
    data.mkdir()
    assert orch._unity_data_dir(game) == data


def test_unity_data_dir_returns_none_without_data(tmp_path):
    game = tmp_path / "NotUnity"
    game.mkdir()
    assert orch._unity_data_dir(game) is None


def test_unity_extract_reconciles_json_vs_convert(tmp_path, monkeypatch):
    """Unity 链路：JSON 枚举计数 vs Convert 导出文件数。"""
    # 造 _Data 目录
    game = tmp_path / "My Game"
    game.mkdir()
    data = game / "My Game_Data"
    data.mkdir()
    ctx = _ctx(tmp_path, game_dir=game)

    # Mock subprocess.run to create output dirs
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        # JSON export: create json files
        if "--export_type" in cmd and "JSON" in cmd:
            for f in cmd:
                if "json" in str(f) and Path(f).is_dir():
                    for t in orch.unity.UNITY_TYPES:
                        pass
                    # Create some json files
                    json_dir = Path(cmd[2])
                    json_dir.mkdir(parents=True, exist_ok=True)
                    # Create 2 json files per type
                    for i in range(2):
                        (json_dir / f"asset_{i}.json").write_text("{}")
                    break
        # Convert export: create png/wav files
        if "--export_type" in cmd and "Convert" in cmd:
            conv_dir = Path(cmd[2])
            conv_dir.mkdir(parents=True, exist_ok=True)
            sub = conv_dir / cmd[5]  # --types value
            sub.mkdir(parents=True, exist_ok=True)
            for i in range(2):
                (sub / f"asset_{i}.png").write_text("x")
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    # Mock tb.find_tool to return a fake path
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))
    _stub_audio_enum(monkeypatch)

    st = orch.stage_extract_unity(ctx)
    assert st.ok is True
    assert st.data["expected_total"] == 6  # 3 types × 2
    assert st.data["actual_total"] == 6
    assert "对账 0 差" in st.detail


def test_unity_scratch_never_writes_into_game_dir(tmp_path, monkeypatch):
    """回归（2026-11-02 Happiness Double Room，WinError 5）：临时目录**绝不能**落在游戏目录里。

    实测：`data_dir.parent / "_json_Texture2D"` 在只读/受保护的游戏目录下 mkdir 直接
    `PermissionError: [WinError 5]`，Unity 链路在「数 JSON」之前就崩（与 AssetStudio、Unity
    版本无关）。本测试锁死「所有传给 AssetStudio 的临时目录都在 work_dir 下、且不在 game_dir 下」。
    """
    game = tmp_path / "My Game"
    game.mkdir()
    data = game / "My Game_Data"
    data.mkdir()
    ctx = _ctx(tmp_path, game_dir=game)

    seen = []

    def fake_run(cmd, **kw):
        import subprocess
        seen.append(Path(cmd[2]))
        if "--export_type" in cmd and "JSON" in cmd:
            d = Path(cmd[2])
            d.mkdir(parents=True, exist_ok=True)
            (d / "a.json").write_text("{}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))

    orch.stage_extract_unity(ctx)
    assert seen, "没有跑到 AssetStudio（测试本身失效）"
    for p in seen:
        assert game not in p.parents and p != game, "临时目录落进游戏目录: %s" % p
        name = p.name.lower()
        if name.startswith("_json_") or name.startswith("_conv_"):
            assert ctx.out_dir in p.parents or ctx.work_dir in p.parents, "AssetStudio 暂存目录应在输出/work 侧: %s" % p


def test_unity_extract_fails_on_mismatch(tmp_path, monkeypatch):
    """JSON 枚举到但 Convert 没导出 → 对账失败。"""
    game = tmp_path / "My Game"
    game.mkdir()
    data = game / "My Game_Data"
    data.mkdir()
    ctx = _ctx(tmp_path, game_dir=game)

    def fake_run(cmd, **kw):
        import subprocess
        if "--export_type" in cmd and "JSON" in cmd:
            json_dir = Path(cmd[2])
            json_dir.mkdir(parents=True, exist_ok=True)
            for i in range(2):
                (json_dir / f"asset_{i}.json").write_text("{}")
        elif "--export_type" in cmd and "Convert" in cmd:
            conv_dir = Path(cmd[2])
            conv_dir.mkdir(parents=True, exist_ok=True)
            sub = conv_dir / cmd[5]
            sub.mkdir(parents=True, exist_ok=True)
            # Only 1 file instead of 2
            (sub / "asset_0.png").write_text("x")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))
    _stub_audio_enum(monkeypatch)

    st = orch.stage_extract_unity(ctx)
    assert st.ok is False
    assert "对账失败" in st.detail


def test_unity_extract_fails_without_data_dir(tmp_path):
    game = tmp_path / "NotUnity"
    game.mkdir()
    ctx = _ctx(tmp_path, game_dir=game)
    st = orch.stage_extract_unity(ctx)
    assert st.ok is False
    assert "没找到" in st.detail


def test_unity_extract_reuse_raw_still_reconciles(tmp_path, monkeypatch):
    """--reuse-raw：跳过 Convert，但仍算地面真相并对账。"""
    game = tmp_path / "My Game"
    game.mkdir()
    data = game / "My Game_Data"
    data.mkdir()
    ctx = _ctx(tmp_path, game_dir=game, reuse_raw=data)

    # Create some files in raw (in the right subdirectory)
    tex_dir = ctx.raw_dir / "Image_Texture2D"
    tex_dir.mkdir(parents=True, exist_ok=True)
    _write(tex_dir / "a.png")
    _write(tex_dir / "b.png")

    def fake_run(cmd, **kw):
        import subprocess
        if "--export_type" in cmd and "JSON" in cmd:
            json_dir = Path(cmd[2])
            json_dir.mkdir(parents=True, exist_ok=True)
            for i in range(2):
                (json_dir / f"asset_{i}.json").write_text("{}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))

    st = orch.stage_extract_unity(ctx)
    assert st.data["expected_total"] == 6
    assert st.data["actual_total"] == 2
    assert st.ok is False
    assert "对账失败" in st.detail



def test_unity_extract_merges_into_existing_raw(tmp_path, monkeypatch):
    """断点续跑：raw/<cat> 已存在时必须**合并**，不能把本轮新产物当临时文件丢掉。

    回归（2026-11-02）：extract_all 改成「改名代替复制」后，若目标目录已存在还去改名，
    os.replace 会失败、产物落回临时目录，随后被清理——等于静默丢文件。
    """
    game = tmp_path / "My Game"
    game.mkdir()
    (game / "My Game_Data").mkdir()
    ctx = _ctx(tmp_path, game_dir=game)
    old = ctx.raw_dir / "Image_Texture2D"
    old.mkdir(parents=True, exist_ok=True)
    (old / "keep.png").write_text("old")

    def fake_run(cmd, **kw):
        import subprocess
        out = Path(cmd[2])
        out.mkdir(parents=True, exist_ok=True)
        if "JSON" in cmd:
            for i in range(2):
                (out / f"asset_{i}.json").write_text("{}")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        sub = out / cmd[cmd.index("--types") + 1]
        sub.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            ext = "wav" if cmd[cmd.index("--types") + 1] == "AudioClip" else "png"
            (sub / f"asset_{i}.{ext}").write_text("x")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))
    _stub_audio_enum(monkeypatch, collect_writes=False)   # wav 已由 fake_run 写出

    orch.stage_extract_unity(ctx)
    got = sorted(p.name for p in (ctx.raw_dir / "Image_Texture2D").glob("*"))
    assert got == ["asset_0.png", "asset_1.png", "keep.png"], got


def test_unity_audio_shortfall_is_filled_by_name_reconciliation(tmp_path, monkeypatch):
    """单次 Convert 少音频时，必须按名字补齐并对账到 0 差（2026-11-02 Happiness Double Room）。

    这作的音频是 FSB5：一次 Convert 只落一部分且 rc=0，只有「枚举名字 → 对账 → 补缺」能收全。
    """
    game = tmp_path / "My Game"
    game.mkdir()
    (game / "My Game_Data").mkdir()
    ctx = _ctx(tmp_path, game_dir=game)
    names = ["clip_a", "clip_b"]
    export_calls = []

    def fake_run(cmd, **kw):
        import subprocess
        out = Path(cmd[2])
        out.mkdir(parents=True, exist_ok=True)
        export_type = cmd[cmd.index("--export_type") + 1]
        group = cmd[cmd.index("--group_assets") + 1]
        if export_type == "JSON" and group == "BySource":          # 逐条枚举
            d = out / "resources.assets_export"
            d.mkdir(parents=True, exist_ok=True)
            for i, n in enumerate(names):
                (d / f"clip_{i}.json").write_text(json.dumps({"m_Name": n}))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if export_type == "JSON":                                  # 计数枚举
            for i in range(2):
                (out / f"asset_{i}.json").write_text("{}")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        type_name = cmd[cmd.index("--types") + 1]
        sub = out / type_name
        sub.mkdir(parents=True, exist_ok=True)
        if type_name == "AudioClip":
            export_calls.append(cmd)
            if "--names" in cmd:                                   # 按名字补跑：全给
                pat = cmd[cmd.index("--names") + 1]
                for n in names:
                    if n in pat:
                        (sub / f"{n}.wav").write_text("RIFF")
            else:                                                  # 单次导出：只给一个
                (sub / f"{names[0]}.wav").write_text("RIFF")
        else:
            for i in range(2):
                (sub / f"asset_{i}.png").write_text("x")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))

    st = orch.stage_extract_unity(ctx)
    assert len(list((ctx.raw_dir / "Audio").glob("*.wav"))) == 2
    assert st.data["audio_missing"] == 0
    assert st.data["expected_total"] == 6 and st.data["actual_total"] == 6
    assert st.ok is True and "对账 0 差" in st.detail
    assert sum(1 for c in export_calls if "--names" in c) == 1, "补齐只该补缺的那批"


def test_unity_archives_reach_manifest_with_names(tmp_path, monkeypatch):
    """回归（2026-11-02）：Unity 阶段的 archives 曾用 name/entries 键，
    build_manifest 只认 archive/expected/got → manifest 里三个 null（交付记录失真）。

    注：这条函数此前被**定义了两次**（同名，第二个覆盖第一个），实际只有一份在跑。
    2026-11-03 批次 C3 去重（不是删测试），保留唯一一份。
    """
    game = tmp_path / "My Game"
    game.mkdir()
    (game / "My Game_Data").mkdir()
    ctx = _ctx(tmp_path, game_dir=game)

    def fake_run(cmd, **kw):
        import subprocess
        out = Path(cmd[2])
        out.mkdir(parents=True, exist_ok=True)
        if "JSON" in cmd:
            for i in range(2):
                (out / f"asset_{i}.json").write_text("{}")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        t = cmd[cmd.index("--types") + 1]
        sub = out / t
        sub.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            ext = "wav" if t == "AudioClip" else "png"
            (sub / f"asset_{i}.{ext}").write_text("x")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))
    _stub_audio_enum(monkeypatch, collect_writes=False)   # wav 已由 fake_run 写出

    st = orch.stage_extract_unity(ctx)
    man = orch.build_manifest(ctx, [st], "Unity")
    names = [a["name"] for a in man["source"]["archives"]]
    assert names == ["Texture2D", "Sprite", "AudioClip"]
    assert [a["entries"] for a in man["source"]["archives"]] == [2, 2, 2]


# ==========================================================================
# 第 13 节：批次 A（2026-11-03 审计）——交付正确性回归
#   每条测试名开头都写明防的是哪一类回归，删掉它之前先想清楚为什么。
# ==========================================================================

def _failing_verify_run(tmp_path, monkeypatch):
    """造一个「对账 0 差但验收失败」的 ctx（A1 的最小复现）。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def fake_extract(c):
        _write(c.raw_dir / "bad.png", b"not a png")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 1, "got": 1}], expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))
    return ctx


def test_run_writes_manifest_even_when_verify_fails(tmp_path, monkeypatch):
    """★A1 回归★ verify 失败也必须落盘 manifest，且里面写着「这次失败了」。

    实测（Happiness Double Room，把 png/ 改名后 --reuse-raw）：退出码 1，但
    out/manifest.json 还是上一次成功那份，CLI 照着它打印「对账 0、验收 0 失败」。
    交付记录失真比崩溃更坏——它看起来是绿的。
    """
    ctx = _failing_verify_run(tmp_path, monkeypatch)

    rc, res = orch.run(ctx)

    assert rc == 1 and res["error"] == "verify-failed"
    assert ctx.manifest_path.exists(), "失败的运行也必须留下本轮 manifest"
    man = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    assert man["ok"] is False
    assert man["error"] == "verify-failed"
    # counts / verify 都是本轮真实数据（不许是空白，也不许是上一轮的 0 失败）
    assert man["counts"]["final"]["total"] == 1
    assert man["verify"]["image_fail"] >= 1


def test_run_failure_overwrites_stale_manifest_on_disk(tmp_path, monkeypatch):
    """★A1 回归★ 磁盘上留有上一次成功那份 manifest 时，失败的一轮必须覆盖它。

    光断言 `ok is False` 不够——旧文件根本没有 ok 字段。所以预置一份「final 3500、
    对账 0」的旧记录，要求落盘内容是本轮实测值（1 个文件），而不是旧数字。
    """
    ctx = _failing_verify_run(tmp_path, monkeypatch)
    ctx.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.manifest_path.write_text(json.dumps({
        "manifest_version": 1, "engine": "Ren'Py", "ok": True,
        "counts": {"raw": {"total": 3500}, "final": {"total": 3500}, "converted": {}},
        "reconcile": {"expected": 3500, "actual": 3500, "diff": 0},
        "verify": {"verified": True, "image_fail": 0},
    }, ensure_ascii=False), encoding="utf-8")

    rc, _res = orch.run(ctx)

    man = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    assert rc == 1
    assert man["ok"] is False
    assert man["counts"]["final"]["total"] == 1, "上一轮的 3500 被写回来了"
    assert man["reconcile"]["actual"] == 1


def test_cli_never_reports_a_manifest_it_did_not_produce(tmp_path, monkeypatch, capsys):
    """★A1 回归★ CLI 只信本轮 `run()` 的返回；没有就直说「本轮未产出」。

    旧代码 `res.get("manifest") or (manifest_path.exists() and read_text(...))`
    —— 拿「文件存在」当「本轮的结论」，于是任何早期失败都会打印上一轮的数字。
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps({
        "counts": {"final": {"total": 3500}, "raw": {"total": 3500}},
        "reconcile": {"expected": 3500, "actual": 3500, "diff": 0},
    }, ensure_ascii=False), encoding="utf-8")
    game = tmp_path / "game"
    game.mkdir()

    monkeypatch.setattr(orch, "run", lambda ctx: (1, {"error": "extract-failed",
                                                      "stages": [], "manifest": None}))

    rc = orch.main([str(game), "--out", str(out)])

    txt = capsys.readouterr().out
    assert rc == 1
    assert "本轮未产出" in txt
    assert "3500" not in txt, "CLI 读到了上一轮的 manifest"


def test_run_turns_extractor_exception_into_failed_stage(tmp_path, monkeypatch):
    """★A2 回归★ extract 抛非预期异常 → rc=1、阶段 ok=False、manifest 落盘。

    旧行为：`globals()[name](ctx)` 裸调用，异常直接穿透给 CLI/GUI；GUI 只显示
    「运行异常（看日志）」，manifest 不落盘——一次失败变成一次失联。
    """
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def boom(c):
        raise RuntimeError("模拟解包器崩了")

    monkeypatch.setattr(orch, "stage_extract_renpy", boom)

    rc, res = orch.run(ctx)

    assert rc == 1
    man = res["manifest"]
    assert man["ok"] is False and man["error"] == "extract-failed"
    ext = [s for s in man["stages"] if s["stage"] == "extract"][0]
    assert ext["ok"] is False
    assert "RuntimeError" in ext["detail"]
    assert ctx.manifest_path.exists()
    log = (ctx.work_dir / "extract.log").read_text(encoding="utf-8")
    assert "RuntimeError" in log and "Traceback" in log, "日志里要留完整 traceback"


def test_run_turns_verify_exception_into_failed_stage(tmp_path, monkeypatch):
    """★A2 回归★ verify 抛异常同样收敛成阶段失败（不只是 extract）。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")
    monkeypatch.setattr(orch, "stage_extract_renpy",
                        lambda c: _fake_stage("extract", expected_total=0))
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))

    def boom(c):
        raise ValueError("Pillow 炸了")

    monkeypatch.setattr(orch, "stage_verify", boom)

    rc, res = orch.run(ctx)

    assert rc == 1 and res["error"] == "verify-failed"
    ver = [s for s in res["manifest"]["stages"] if s["stage"] == "verify"][0]
    assert ver["ok"] is False and "ValueError" in ver["detail"]


def test_run_stage_guard_does_not_swallow_keyboard_interrupt(tmp_path, monkeypatch):
    """★A2 回归★ Ctrl+C 必须能打断：阶段兜底只吞 Exception。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def interrupt(c):
        raise KeyboardInterrupt

    monkeypatch.setattr(orch, "stage_extract_renpy", interrupt)

    with pytest.raises(KeyboardInterrupt):
        orch.run(ctx)


def _unity_stub(tmp_path, monkeypatch, *, tex_exp: int, tex_actual: int, other: int = 2):
    """假 Unity 链路：JSON 枚举 tex_exp 张 Texture2D，Convert 只落 tex_actual 张。

    直接替换 `expected_counts` / `extract_all` 两个地面真相入口（它们各自有单测），
    这里只验编排层的对账判定，不碰 AssetStudio。
    """
    game = tmp_path / "My Game"
    game.mkdir()
    (game / "My Game_Data").mkdir()
    ctx = _ctx(tmp_path, game_dir=game)

    by_type = {"Texture2D": tex_exp, "Sprite": other, "AudioClip": other}
    monkeypatch.setattr(orch.unity, "expected_counts",
                        lambda data_dir, as_exe=None, tmp_root=None: {
                            "by_type": dict(by_type), "total": sum(by_type.values()),
                            "unlistable": [], "types": list(orch.unity.UNITY_TYPES)})

    def fake_extract_all(data_dir, out_dir, as_exe=None, tmp_root=None):
        got = {"Texture2D": tex_actual, "Sprite": other, "AudioClip": other}
        for t, n in got.items():
            d = out_dir / orch.unity.UNITY_CATEGORIES[t]
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                (d / f"a{i}.{'wav' if t == 'AudioClip' else 'png'}").write_text("x")
        return {"by_type": dict(got), "total": sum(got.values()), "archives": []}

    monkeypatch.setattr(orch.unity, "extract_all", fake_extract_all)
    monkeypatch.setattr(orch.tb, "find_tool", lambda key: Path("/fake/assetstudio.exe"))
    # 音频枚举会真的去跑 AssetStudio：换成「枚举成功、名字数正好等于 AudioClip 期望」
    _stub_audio_enum(monkeypatch, names=[f"clip{i}" for i in range(other)],
                     collect_writes=False)          # wav 已由假 extract_all 写出
    return ctx


def test_unity_texture2d_small_gap_passes_and_is_reported(tmp_path, monkeypatch):
    """★A3 回归★ 常态小缺口（本作 5 个）必须通过，但 detail 要显式报出缺口。

    旧实现把缺口从 expected 里减掉，等于「少导 5 个就把期望也减 5」，永远 0 差。
    新实现：缺口不削减期望，只在阈值内放行并报数。
    """
    ctx = _unity_stub(tmp_path, monkeypatch, tex_exp=460, tex_actual=455)

    st = orch.stage_extract_unity(ctx)

    assert st.ok is True, st.detail
    assert st.data["texture2d_gap"] == 5
    assert "已知缺口 5 个" in st.detail
    # 期望值**没有**被缺口削减：460 + 2 + 2
    assert st.data["expected_total"] == 464
    assert st.data["actual_total"] == 459


def test_unity_texture2d_huge_gap_fails_instead_of_self_adjusting(tmp_path, monkeypatch):
    """★A3 回归★ 缺口超阈值（这里 50%）必须判失败，而不是「缺口自己迁就自己」。"""
    ctx = _unity_stub(tmp_path, monkeypatch, tex_exp=100, tex_actual=50)

    st = orch.stage_extract_unity(ctx)

    assert st.ok is False
    assert "对账失败" in st.detail
    assert "只导出了 50/100" in st.detail


def test_unity_non_texture2d_shortfall_is_not_excused_by_gap(tmp_path, monkeypatch):
    """★A3 回归★ 缺口只能出现在 Texture2D：别的类少导出不能拿缺口盖过去。

    造 Sprite 少 1 张、Texture2D 正常：旧实现只看总数，Sprite 的漏导会被
    Texture2D 的「缺口」空间吞掉。
    """
    ctx = _unity_stub(tmp_path, monkeypatch, tex_exp=460, tex_actual=455)

    def fake_extract_all(data_dir, out_dir, as_exe=None, tmp_root=None):
        """Texture2D 如常少 5 张，但 Sprite 只落 1 张（枚举 2）——总短缺 6 ≠ 缺口 5。"""
        tex = out_dir / "Image_Texture2D"
        tex.mkdir(parents=True, exist_ok=True)
        for i in range(455):
            (tex / f"t{i}.png").write_text("x")
        spr = out_dir / "Image_Sprite"
        spr.mkdir(parents=True, exist_ok=True)
        (spr / "s0.png").write_text("x")
        aud = out_dir / "Audio"
        aud.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            (aud / f"a{i}.wav").write_text("x")
        return {"by_type": {"Texture2D": 455, "Sprite": 1, "AudioClip": 2},
                "total": 458, "archives": []}

    monkeypatch.setattr(orch.unity, "extract_all", fake_extract_all)

    st = orch.stage_extract_unity(ctx)

    assert st.ok is False
    assert "Sprite" in st.detail


def test_kirikiri_unlistable_archive_fails_instead_of_silent_skip(tmp_path, monkeypatch):
    """★A4 回归★ 有 .xp3 列不出条目时必须判失败并点名是哪个包。

    旧实现对这个包只 append 一条记录就 continue：expected 只算列得出的包，
    总数照样 0 差 —— 一个包根本没验却被洗成「通过」。
    """
    ctx = _ctx(tmp_path)
    good = _write(ctx.game_dir / "data.xp3", b"XP3")
    bad = _write(ctx.game_dir / "patch.xp3", b"XP3")
    monkeypatch.setattr(orch, "_kirikiri_xp3", lambda _d: [good, bad])

    def fake_list(p, **_kw):
        if Path(p).name == "patch.xp3":
            return False, 0, "unknown format"
        return True, 2, ""

    monkeypatch.setattr(orch.tb, "garbro_list", fake_list)

    def fake_extract(arc, dest, **_kw):
        Path(dest).mkdir(parents=True, exist_ok=True)
        for i in range(2):
            (Path(dest) / f"f{i}.ogg").write_text("x")
        return orch.tb.ToolResult(key="garbro", exe="garbro", argv=[], returncode=0,
                                  stdout="", ok=True)

    monkeypatch.setattr(orch.tb, "garbro_extract", fake_extract)

    st = orch.stage_extract_kirikiri(ctx)

    assert st.ok is False
    assert "patch.xp3" in st.detail
    assert [u["archive"] for u in st.data["unsupported"]] == ["patch.xp3"]
    # 「有意排除」必须进 manifest.source，不能只躺在日志里
    man = orch.build_manifest(ctx, [st], "KiriKiri")
    assert man["source"]["unsupported"][0]["archive"] == "patch.xp3"


def test_move_dir_clean_never_nests_when_target_exists(tmp_path):
    """★A5 回归★ 目标已存在时必须先清空 —— `shutil.move` 会静默造成 png/png/。"""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    _write(src / "a.png")
    _write(src / "sub" / "b.png")
    dst = tmp_path / "dst"
    _write(dst / "stale.png")

    assert orch._move_dir_clean(src, dst) is None
    assert sorted(p.name for p in dst.rglob("*") if p.is_file()) == ["a.png", "b.png"]
    assert not (dst / "src").exists(), "搬成了 dst/src/ —— 嵌层"
    assert not src.exists()


def test_kirikiri_gui_move_does_not_nest_png_into_existing_png(tmp_path, monkeypatch):
    """★A5 回归★ GUI 链路把 png/ 搬进**已存在**的 out/png 时不许嵌层。

    嵌层的后果不是报错，而是交付清单变成 png/png/*.png、对账数照样能自洽——
    属于无声的错，所以这条必须锁死。
    """
    ctx = _ctx(tmp_path, allow_gui=True)
    _write(ctx.game_dir / "data.xp3")
    _png(ctx.png_dir / "stale.png")            # 上一次运行留下的目标目录
    monkeypatch.setattr(orch, "_kirikiri_xp3", lambda _d: [ctx.game_dir / "data.xp3"])
    monkeypatch.setattr(orch.tb, "garbro_list", lambda _p, **_k: (False, 0, "unknown format"))

    def fake_sibling(mod, argv):
        kout = Path(argv[argv.index("--out") + 1]) / "KrkrExtract_Output"
        (kout / "data").mkdir(parents=True, exist_ok=True)
        _write(kout / "data" / "a.ogg")
        _png(kout / "png" / "b.png")
        return 0, ""

    monkeypatch.setattr(orch, "_run_sibling", fake_sibling)

    st = orch.stage_extract_kirikiri(ctx)

    assert st.ok is True, st.detail
    assert (ctx.png_dir / "b.png").is_file()
    assert not (ctx.png_dir / "png").exists(), "png/ 被搬成了 png/png/"
    assert not (ctx.png_dir / "stale.png").exists(), "旧产物应被清掉，不是叠在一起"
    assert (ctx.raw_dir / "a.ogg").is_file()


# ==========================================================================
# 第 14 节：批次 B（2026-11-03）——可用性与安全
# ==========================================================================

# ---- B1 磁盘余量预检 -----------------------------------------------------

def test_preflight_passes_when_plenty_of_free_space(tmp_path, monkeypatch):
    """★B1★ 余量充足：ok=True，data 里三个字节数都要有（报告能直接用）。"""
    ctx = _ctx(tmp_path)
    _write(ctx.game_dir / "data.xp3", b"x" * (1024 * 1024))     # 1 MiB
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 100 * 1024 ** 3})())

    st = orch.stage_preflight(ctx)

    assert st.ok is True, st.detail
    assert st.data["source_bytes"] == 1024 * 1024
    assert st.data["required_bytes"] > st.data["source_bytes"]
    assert st.data["free_bytes"] == 100 * 1024 ** 3
    assert "余量充足" in st.detail


def _sparse_file(path: Path, size: int) -> Path:
    """造一个**逻辑上** size 字节的文件，但不真的写数据（truncate 只改 EOF）。

    为什么不用 `write_bytes(b"x" * 1GiB)`：那会真的占 1 GiB 内存 + 磁盘，
    CI 上跑一次预检测试就把机器拖垮。预检只看 `st_size`，truncate 足够。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.truncate(size)
    return path


def test_preflight_fails_when_free_is_under_half_of_required(tmp_path, monkeypatch):
    """★B1★ 可用不足需要量的一半 → 判失败（继续跑必然写到中途炸）。"""
    ctx = _ctx(tmp_path)
    _sparse_file(ctx.game_dir / "data.xp3", 1024 ** 3)          # 1 GiB
    # 需要 ≈ 1.65 GiB（1.15 GiB + 512 MiB），一半是 0.82 GiB；只给 0.49 GiB
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 500 * 1024 ** 2})())

    st = orch.stage_preflight(ctx)

    assert st.ok is False
    assert "余量不足" in st.detail and "需要约" in st.detail and "可用" in st.detail


def test_preflight_tight_space_passes_with_warning(tmp_path, monkeypatch):
    """★B1★ 一半 ≤ 可用 < 需要 → 放行但标「余量偏紧」，日志留 WARN。"""
    ctx = _ctx(tmp_path)
    _write(ctx.game_dir / "data.xp3", b"x" * (1024 * 1024))          # 1 MiB
    # required = 1MiB*1.15 + 512MiB ≈ 0.5011 GiB：给 0.4997 GiB（> 一半、< 需要）
    free = int(orch.PREFLIGHT_RESERVE_BYTES * 0.995)
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": free})())

    st = orch.stage_preflight(ctx)

    assert st.ok is True, st.detail
    assert "余量偏紧" in st.detail
    log = (ctx.work_dir / "preflight.log").read_text(encoding="utf-8")
    assert "[WARN]" in log


def test_preflight_adds_a_stage_copy_for_gui_chain(tmp_path, monkeypatch):
    """★B1★ `--allow-gui` 要在 ASCII stage 里再放一份 → 需要量翻倍。"""
    ctx = _ctx(tmp_path)
    _write(ctx.game_dir / "data.xp3", b"x" * 1000)
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 10 * 1024 ** 3})())

    plain = orch.stage_preflight(ctx)
    ctx.allow_gui = True
    gui = orch.stage_preflight(ctx)

    assert gui.data["required_bytes"] - plain.data["required_bytes"] == plain.data["source_bytes"]


def test_preflight_survives_oserror_during_walk(tmp_path, monkeypatch):
    """★B1★ 遍历时某个目录抛 OSError（坏链接/权限拒绝）不能让预检崩掉。"""
    import os as _os

    ctx = _ctx(tmp_path)
    _write(ctx.game_dir / "a.bin", b"x" * 1000)
    locked = ctx.game_dir / "locked"
    locked.mkdir()
    real_scandir = _os.scandir

    def fake_scandir(p):
        if Path(p) == locked:
            raise PermissionError("拒绝访问")
        return real_scandir(p)

    monkeypatch.setattr(orch.os, "scandir", fake_scandir)
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 10 * 1024 ** 3})())

    st = orch.stage_preflight(ctx)

    assert st.ok is True
    assert st.data["source_bytes"] == 1000, "读不了的部分跳过，读到多少算多少"


def test_preflight_skips_when_game_dir_is_missing(tmp_path):
    """★B1★ 目录不存在/为空 → 直接放行（测试与 --engine 强制指定大量用这种 ctx）。"""
    ctx = _ctx(tmp_path)                    # game_dir 不存在
    st = orch.stage_preflight(ctx)
    assert st.ok is True
    assert "跳过余量预检" in st.detail
    assert st.data["required_bytes"] is None


# ---- B2 取消 -------------------------------------------------------------

def test_run_cancels_at_stage_boundary(tmp_path, monkeypatch):
    """★B2★ should_stop 一上来就为真 → 停在 extract 之前，rc=1、error=cancelled、manifest 落盘。"""
    ctx = _ctx(tmp_path, engine="Ren'Py", should_stop=lambda: True)
    called = {"extract": 0}

    def fake_extract(c):
        called["extract"] += 1
        return _fake_stage("extract", expected_total=0)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)

    rc, res = orch.run(ctx)

    assert rc == 1
    assert res["error"] == "cancelled"
    assert called["extract"] == 0, "取消要在阶段边界生效，不能再进解包"
    man = res["manifest"]
    assert man["ok"] is False and man["error"] == "cancelled"
    assert ctx.manifest_path.exists()
    ext = [s for s in man["stages"] if s["stage"] == "extract"][0]
    assert ext["ok"] is False and ext["cancelled"] is True


def test_verify_loop_stops_within_200_files(tmp_path, monkeypatch):
    """★B2★ verify 循环里也要能取消（大样本验收要跑几分钟），且判定不算「验收失败」。"""
    ctx = _ctx(tmp_path)
    for i in range(250):
        _png(ctx.raw_dir / f"p{i}.png")
    # 第一次读到取消位（i=200 的那个边界）就停：护栏就是「两百个文件内必须有反应」
    ctx.should_stop = lambda: True

    st = orch.stage_verify(ctx)

    assert st.ok is False
    assert st.data["cancelled"] is True
    assert st.data["files_checked"] == 200, st.data
    assert "用户取消" in st.detail


def test_run_maps_cancelled_verify_to_cancelled_error(tmp_path, monkeypatch):
    """★B2★ verify 里的取消要报 error=cancelled，别混成 verify-failed。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")
    monkeypatch.setattr(orch, "stage_extract_renpy",
                        lambda c: _fake_stage("extract", expected_total=0))
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))
    monkeypatch.setattr(orch, "stage_verify",
                        lambda c: orch.Stage("verify", ok=False, detail="用户取消：已验收 200/999",
                                             data={"cancelled": True, "verified": False}))

    rc, res = orch.run(ctx)

    assert rc == 1
    assert res["manifest"]["error"] == "cancelled"


# ---- B4 非媒体文件必须显式报出 ------------------------------------------

def test_verify_reports_nonmedia_by_ext_in_detail_and_manifest(tmp_path):
    """★B4★ 非媒体文件不计失败，但必须显式报出「有 N 个没验」。

    `.mos` 那次的翻版：媒体落进 nonmedia 分支被静默放过，验收照样报「失败 0」。
    通用形态是任何非媒体扩展名都在悄悄漏验，所以按扩展名聚合写进 detail/manifest。
    """
    ctx = _ctx(tmp_path)
    _png(ctx.raw_dir / "bg.png")
    _write(ctx.raw_dir / "readme.txt")
    _write(ctx.raw_dir / "sub" / "also.txt")
    _write(ctx.raw_dir / "movie.dat")

    st = orch.stage_verify(ctx)

    assert st.ok is True, st.detail
    assert st.data["nonmedia"] == 3
    assert st.data["nonmedia_by_ext"] == {".dat": 1, ".txt": 2}
    assert "3 个非媒体" in st.detail and ".txt 2" in st.detail
    man = orch.build_manifest(ctx, [st], "Ren'Py")
    assert man["verify"]["nonmedia"] == 3
    assert man["verify"]["nonmedia_by_ext"] == {".dat": 1, ".txt": 2}


# ==========================================================================
# 第 15 节：批次 C（2026-11-03）——verify 并行化 / manifest 单写 / --strict
# ==========================================================================

def _seed_audio_files(ctx: orch.Ctx, n: int) -> None:
    """造 n 个 .ogg 占位（内容无所谓：ffprobe 在本节一律 monkeypatch）。"""
    for i in range(n):
        _write(ctx.raw_dir / f"a_{i:03d}.ogg", b"OggS")


def _fake_ffprobe_by_index(p, **_kw):
    """按文件下标决定好坏，并**故意让完成顺序与提交顺序不同**。

    sleep 与下标成模运算关系（不是单调递增），这样线程池里「谁先算完」和「谁先提交」
    是两回事——如果聚合不是按下标写回，fails 的顺序就会散。
    """
    idx = int(p.stem.split("_")[1])
    time.sleep(((idx * 7919) % 11) / 1000.0)
    if idx % 3 == 0:
        return None, f"合成坏文件 {p.name}"
    return {"kind": "audio", "dur": 1.0}, ""


def _verify_with_jobs(ctx, jobs: int) -> orch.Stage:
    ctx.verify_jobs = jobs
    return orch.stage_verify(ctx)


def test_verify_parallel_matches_serial_even_when_completion_is_shuffled(tmp_path, monkeypatch):
    """★C1★ 乱序完成时，并行与串行的计数、fails 顺序必须**逐字一致**。

    这是并行化能进代码的前提：结果若依赖「谁先算完」，同一份产物两次跑出两份不同的
    manifest，diff 全是噪声，也没法拿串行档当回归基准。
    """
    ctx = _ctx(tmp_path)
    _seed_audio_files(ctx, 24)                    # 下标 %3==0 的 8 个坏
    monkeypatch.setattr(orch.tb, "ffprobe_ex", _fake_ffprobe_by_index)

    serial = _verify_with_jobs(ctx, 1)
    parallel = _verify_with_jobs(ctx, 8)

    def norm(st: orch.Stage) -> dict:
        # jobs 是配置回显，不属于「结论」；其余字段必须一模一样
        return {k: v for k, v in st.data.items() if k != "jobs"}

    assert norm(serial) == norm(parallel)
    assert serial.detail == parallel.detail
    assert len(serial.data["fail_examples"]) == 8
    assert serial.data["fail_examples"] == parallel.data["fail_examples"], "fails 顺序被打乱了"
    assert serial.ok is False and parallel.ok is False


def test_verify_jobs_one_equals_jobs_eight_on_good_files(tmp_path):
    """★C1★ 全好文件时 jobs=1 与 jobs=8 结论相同（且都是「失败 0」）。"""
    ctx = _ctx(tmp_path)
    for i in range(6):
        _png(ctx.raw_dir / f"p{i}.png")

    serial = _verify_with_jobs(ctx, 1)
    parallel = _verify_with_jobs(ctx, 8)

    assert serial.ok is True and parallel.ok is True
    assert serial.data["jobs"] == 1 and parallel.data["jobs"] == 6
    for key in ("image_ok", "image_fail", "files_checked", "verified"):
        assert serial.data[key] == parallel.data[key]


def test_verify_cancel_works_in_serial_mode_too(tmp_path):
    """★C1★ 取消两条路径都要生效：jobs=1（串行档）也要在 200 个内停下。"""
    ctx = _ctx(tmp_path)
    for i in range(250):
        _png(ctx.raw_dir / f"p{i}.png")
    ctx.should_stop = lambda: True
    ctx.verify_jobs = 1

    st = orch.stage_verify(ctx)

    assert st.ok is False and st.data["cancelled"] is True
    assert st.data["files_checked"] == 200


def test_verify_probe_exception_becomes_failure_not_crash(tmp_path, monkeypatch):
    """★C1★ 单个探测抛异常 → 降级成一条失败记录，不能把整段 verify 炸掉。

    线程池里一个 future 抛出去，`future.result()` 会在主线程重抛，3499 个好文件白验。
    """
    ctx = _ctx(tmp_path)
    for i in range(4):
        _png(ctx.raw_dir / f"ok{i}.png")
    _png(ctx.raw_dir / "boom.png")
    real_probe = orch._probe_one

    def boom_probe(p, label):
        if p.name == "boom.png":
            raise RuntimeError("模拟 Pillow 底层崩了")
        return real_probe(p, label)

    monkeypatch.setattr(orch, "_probe_one", boom_probe)

    st = orch.stage_verify(ctx)

    assert st.ok is False, "有探测异常就必须判失败"
    assert st.data["probe_fail"] == 1
    assert st.data["image_ok"] == 4
    assert any("[probe]" in f and "RuntimeError" in f for f in st.data["fail_examples"])


def test_resolve_verify_jobs_precedence(tmp_path, monkeypatch):
    """★C1★ 并发度的优先级：显式 ctx 值 > 环境变量 > 默认值。"""
    ctx = _ctx(tmp_path)
    monkeypatch.delenv("GALUNPACK_VERIFY_WORKERS", raising=False)
    assert orch.resolve_verify_jobs(ctx) == orch.VERIFY_WORKERS

    monkeypatch.setenv("GALUNPACK_VERIFY_WORKERS", "3")
    assert orch.resolve_verify_jobs(ctx) == 3

    monkeypatch.setenv("GALUNPACK_VERIFY_WORKERS", "不是数字")   # 坏值退回默认，不崩
    assert orch.resolve_verify_jobs(ctx) == orch.VERIFY_WORKERS

    ctx.verify_jobs = 2                                          # 显式值最大
    monkeypatch.setenv("GALUNPACK_VERIFY_WORKERS", "8")
    assert orch.resolve_verify_jobs(ctx) == 2


# ---- C2 manifest 单次写盘 -------------------------------------------------

def test_run_writes_manifest_exactly_once(tmp_path, monkeypatch):
    """★C2★ 成功路径只能写一次盘，且写下去的那份自带 ok / total_seconds。

    旧实现写两次（先一份没有 ok 的，再补完重写）：中间被 Ctrl+C 就留下一个
    「既不能说成功也不能说失败」的 manifest —— 下游无从判断。
    """
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def fake_extract(c):
        _png(c.raw_dir / "a.png")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 1, "got": 1}], expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))

    writes: list[dict] = []
    real_write = orch._write_manifest

    def counting_write(c, man):
        writes.append(json.loads(json.dumps(man, ensure_ascii=False)))
        return real_write(c, man)

    monkeypatch.setattr(orch, "_write_manifest", counting_write)

    rc, man = orch.run(ctx)

    assert rc == 0
    assert len(writes) == 1, f"manifest 被写了 {len(writes)} 次"
    on_disk_first = writes[0]
    assert on_disk_first["ok"] is True, "落盘那一份必须自带 ok"
    assert "total_seconds" in on_disk_first
    # 落盘那份不含描述「写manifest」的自我指涉阶段，但返回给调用方的有
    assert "manifest" not in [s["stage"] for s in on_disk_first["stages"]]
    assert "manifest" in [s["stage"] for s in man["stages"]]
    on_disk = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    assert on_disk["ok"] is True
    # C16：盘上那份没法用 stages 表达「自己写成了」，所以给显式字段，
    # 下游不必靠「stages 少一条」去推断。
    assert on_disk["manifest_written"] is True


# ---- C3 --strict 真语义 --------------------------------------------------

def test_strict_fails_when_reconcile_has_no_ground_truth(tmp_path, monkeypatch):
    """★C3★ `--strict`：对账没有地面真相（expected=None）也算失败。

    这个开关此前是纯空转（argparse 收了、没人读）。它的价值就是把「没验」与「验过了」
    分开：加密包列不出条目时 diff=None，非 strict 下是绿的，但那 0 差其实没人验过。
    """
    ctx = _ctx(tmp_path, engine="Ren'Py", strict=True)

    def fake_extract(c):
        _png(c.raw_dir / "a.png")
        return _fake_stage("extract", archives=[{"archive": "x.rpa", "expected": None,
                                                 "got": 1}])      # 没有 expected_total

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))

    rc, man = orch.run(ctx)

    assert rc == 1
    assert man["error"] == "strict-no-ground-truth"
    assert man["ok"] is False


def test_strict_fails_when_verify_did_not_run(tmp_path, monkeypatch):
    """★C3★ `--strict`：验收没执行（--no-verify）也算失败。"""
    ctx = _ctx(tmp_path, engine="Ren'Py", strict=True, do_verify=False)

    def fake_extract(c):
        _png(c.raw_dir / "a.png")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 1, "got": 1}], expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))

    rc, man = orch.run(ctx)

    assert rc == 1
    assert man["error"] == "strict-not-verified"


def test_non_strict_still_passes_when_verification_skipped(tmp_path, monkeypatch):
    """★C3 反面对照★ 不带 --strict 时，--no-verify 仍是绿的（默认行为没被改坏）。"""
    ctx = _ctx(tmp_path, engine="Ren'Py", do_verify=False)

    def fake_extract(c):
        _png(c.raw_dir / "a.png")
        return _fake_stage("extract", archives=[
            {"archive": "x.rpa", "expected": 1, "got": 1}], expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))

    rc, man = orch.run(ctx)

    assert rc == 0, man.get("error")
    assert man["ok"] is True


# ---- C15 CLI 的「验收」措辞：三条分支各一个断言 --------------------------

def _cli_with_verify_stage(tmp_path, monkeypatch, capsys, *, verify_block, stage):
    """用一份手工拼的 manifest 驱动 CLI 输出（不跑真链路）。"""
    game = tmp_path / "game"
    game.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    man = {
        "manifest_version": 1, "engine": "Ren'Py", "ok": False, "error": "cancelled",
        "counts": {"raw": {"total": 0, "by_ext": {}},
                   "final": {"total": 0, "by_ext": {}}, "converted": {}},
        "reconcile": {"expected": None, "actual": 0, "diff": None,
                      "method": "no-index-available"},
        "verify": verify_block,
        # stages 里必须有 seconds：CLI 的阶段摘要按 `{seconds:>7.2f}` 对齐打印
        "stages": ([{"seconds": 0.0, **stage}] if stage else [])
                  + [{"stage": "extract", "ok": True, "seconds": 0.0}],
    }
    monkeypatch.setattr(orch, "run", lambda ctx: (1, man))
    rc = orch.main([str(game), "--out", str(out)])
    return rc, capsys.readouterr().out


def test_cli_says_no_verify_only_when_flag_was_used(tmp_path, monkeypatch, capsys):
    """★C15★ 只有 `--no-verify`（stage.skipped=True）才许打「未执行（--no-verify）」。"""
    rc, txt = _cli_with_verify_stage(
        tmp_path, monkeypatch, capsys, verify_block={"verified": False},
        stage={"stage": "verify", "ok": True, "skipped": True})
    assert rc == 1
    assert "未执行（--no-verify）" in txt


def test_cli_says_cancelled_when_verify_was_cancelled(tmp_path, monkeypatch, capsys):
    """★C15★ 验收被取消 → 说「已取消」，不许冒充「--no-verify」。"""
    rc, txt = _cli_with_verify_stage(
        tmp_path, monkeypatch, capsys, verify_block={"verified": False},
        stage={"stage": "verify", "ok": False, "skipped": False, "cancelled": True,
               "files_checked": 200})
    assert rc == 1
    assert "已取消" in txt and "200" in txt
    assert "--no-verify" not in txt, "取消被说成了用户自己关掉验收"


def test_cli_says_no_products_when_there_was_nothing_to_verify(tmp_path, monkeypatch, capsys):
    """★C15★ 没有可验收产物 → 直说，不许冒充「--no-verify」。"""
    rc, txt = _cli_with_verify_stage(
        tmp_path, monkeypatch, capsys, verify_block={"verified": False},
        stage={"stage": "verify", "ok": False, "skipped": False,
               "detail": "没有可验收的产物"})
    assert rc == 1
    assert "没有可验收的产物" in txt
    assert "--no-verify" not in txt


def test_cli_reports_verify_failures_instead_of_saying_not_run(tmp_path, monkeypatch, capsys):
    """★C15 对照★ verify **有失败文件**时 verified 仍为 True（计数才是结论）→ 正常打印。"""
    rc, txt = _cli_with_verify_stage(
        tmp_path, monkeypatch, capsys,
        verify_block={"verified": True, "image_ok": 0, "image_fail": 3,
                      "audio_ok": 0, "audio_fail": 0, "video_ok": 0, "video_fail": 0,
                      "media_minutes": 0.0},
        stage={"stage": "verify", "ok": False, "skipped": False})
    assert rc == 1
    assert "图片 0/3失败" in txt
    assert "未执行" not in txt


# ---- C17 并行验收的确定性锚 ---------------------------------------------

def test_parallel_verify_matches_serial_byte_for_byte(tmp_path, monkeypatch):
    """★C17★ 删了这条测试 = 放弃并行验收的正确性。

    并行化后唯一的正确性保证是「结果按下标写回 + 聚合按原顺序遍历」这一条实现细节。
    谁把它改成 `results.append(...)`，功能测试可能全绿，而 manifest 从此每次顺序都不同
    （diff 全是噪声、也没法拿串行档当基准）——**这类回归不会自己报错**，只能靠这条钉住。

    断言口径：除 `jobs`（配置回显）与耗时外，`st.data` 必须完全相等，包含
    `fail_examples` 的**逐条顺序**（它直接反映「按下标聚合」有没有被破坏）。
    """
    ctx = _ctx(tmp_path)
    # 3 个截断 png（真 Pillow 失败，错误消息来自 Pillow 本身）
    for i in range(3):
        _write(ctx.raw_dir / f"bad_{i}.png", b"\x89PNG\r\n\x1a\n" + b"truncated")
    # 1 个好 png
    _png(ctx.raw_dir / "good_0.png")
    # 2 个坏 wav：用假 ffprobe 并让完成顺序与提交顺序相反
    _write(ctx.raw_dir / "bad_0.wav", b"RIFF")
    _write(ctx.raw_dir / "bad_1.wav", b"RIFF")
    # 2 个非媒体
    _write(ctx.raw_dir / "readme.txt")
    _write(ctx.raw_dir / "notes.txt")

    def fake_ffprobe(p, **_kw):
        idx = int(p.stem.split("_")[1])
        time.sleep(0.02 * (2 - idx))          # 先提交的后完成
        return None, f"合成坏音频 {p.name}"

    monkeypatch.setattr(orch.tb, "ffprobe_ex", fake_ffprobe)

    serial = _verify_with_jobs(ctx, 1)
    parallel_a = _verify_with_jobs(ctx, 8)
    parallel_b = _verify_with_jobs(ctx, 8)

    def norm(st: orch.Stage) -> dict:
        return {k: v for k, v in st.data.items() if k != "jobs"}

    assert norm(serial) == norm(parallel_a) == norm(parallel_b)
    assert serial.detail == parallel_a.detail == parallel_b.detail
    # fail_examples 的顺序是不变量的一部分：串行与并行必须逐条一致
    assert serial.data["fail_examples"] == parallel_a.data["fail_examples"]
    assert parallel_a.data["fail_examples"] == parallel_b.data["fail_examples"], \
        "同一个 jobs=8 跑两次顺序都不同 → 聚合不是按下标做的"
    assert len(serial.data["fail_examples"]) == 5
    # 非媒体统计与零字节计数也在不变量里
    assert serial.data["nonmedia_by_ext"] == {".txt": 2}
    assert serial.data["zero_byte"] == 0


# ---- C11 音频名字枚举的三种结局 -----------------------------------------

def test_unity_audio_enum_failure_is_a_stage_failure(tmp_path, monkeypatch):
    """★C11★ 枚举超时 → stage 失败并说「地面真相未知」，不许把 expected 算成 0。

    旧行为：`enumerate_names` 返回 `[]` —— 调用方据此认为「这作没有音频」，
    对账 0 差、验收 0 失败，一作 1441 条音频没解出来而交付记录全绿。
    """
    ctx = _unity_stub(tmp_path, monkeypatch, tex_exp=2, tex_actual=2)
    monkeypatch.setattr(orch._as_audio_collect2, "enumerate_names",
                        lambda *a, **k: None)          # None = 枚举失败

    st = orch.stage_extract_unity(ctx)

    assert st.ok is False
    assert "地面真相未知" in st.detail
    assert st.data["audio_enum"] == "failed"


def test_unity_audio_enum_empty_but_expected_is_a_stage_failure(tmp_path, monkeypatch):
    """★C11★ 枚举成功却返回 0 条、而 JSON 说有 N 个 → 自相矛盾，判失败。"""
    ctx = _unity_stub(tmp_path, monkeypatch, tex_exp=2, tex_actual=2)
    monkeypatch.setattr(orch._as_audio_collect2, "enumerate_names",
                        lambda *a, **k: [])

    st = orch.stage_extract_unity(ctx)

    assert st.ok is False
    assert "互相矛盾" in st.detail
    assert st.data["audio_enum"] == "empty-but-expected"


# ---- 预检：复用模式不该按整份源体积卡盘 --------------------------------

def test_preflight_skips_in_reuse_mode(tmp_path, monkeypatch):
    """★B1 补丁★ `--reuse-raw` 不重新解包，就不该按 1.15× 源体积卡盘。

    「拿着已解好的 raw 在空间紧张的盘上复跑」正是想省空间的场景，
    拿整份源体积去挡它等于把最需要复用的人挡在门外。
    """
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "old_raw")
    _sparse_file(ctx.game_dir / "data.xp3", 200 * 1024 ** 2)     # 200 MiB
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 1024 ** 2})())   # 只剩 1 MiB

    st = orch.stage_preflight(ctx)

    assert st.ok is True
    assert "复用模式" in st.detail
    assert st.data["source_bytes"] == 200 * 1024 ** 2
    assert st.data["required_bytes"] is None


# ==========================================================================
# 第 15 节：重跑口径（2026-11-04，v0.1.2）—— raw 非空不许静默叠跑
# ==========================================================================

def test_preflight_fails_on_stale_raw_without_overwrite(tmp_path):
    """★核心★ raw 非空 + 没说要覆盖 → 提取前就失败，且**不许删**用户产物。

    静默叠跑的后果不是报错，而是产物数虚高、对账照样 diff=0 ——
    「上一轮 3500 + 本轮 3500 = 7000」看起来像一个完美的交付记录。
    """
    ctx = _ctx(tmp_path)
    _write(ctx.raw_dir / "old.ogg", b"old")

    st = orch.stage_preflight(ctx)

    assert st.ok is False
    assert "--overwrite" in st.detail and "--reuse-raw" in st.detail
    assert (ctx.raw_dir / "old.ogg").is_file(), "预检是只读的，不能顺手清盘"


def test_preflight_allows_stale_raw_when_overwrite_is_set(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, overwrite=True)
    _write(ctx.raw_dir / "old.ogg", b"old")
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 100 * 1024 ** 3})())

    st = orch.stage_preflight(ctx)

    assert st.ok is True, st.detail


def test_preflight_does_not_block_reuse_raw(tmp_path):
    """--reuse-raw 的 raw 本来就非空——守卫不能把复用模式自己挡在门外。"""
    ctx = _ctx(tmp_path, reuse_raw=tmp_path / "old_raw")
    _write(ctx.raw_dir / "old.ogg", b"old")

    st = orch.stage_preflight(ctx)

    assert st.ok is True
    assert "复用模式" in st.detail


def test_run_stops_before_extract_when_stale_raw(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, engine="Ren'Py")
    _write(ctx.raw_dir / "old.ogg", b"old")
    called = {"n": 0}

    def fake_extract(c):
        called["n"] += 1
        return _fake_stage("extract", expected_total=0)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    rc, res = orch.run(ctx)
    assert rc == 1
    assert res["error"] == "preflight-failed"
    assert called["n"] == 0, "预检失败后不该进解包"


def test_run_overwrite_clears_raw_and_png_then_extracts(tmp_path, monkeypatch):
    """--overwrite：raw/ 与 png/ 都清（只清 raw 会让上一轮的图混进 final 口径）。"""
    ctx = _ctx(tmp_path, engine="Ren'Py", overwrite=True)
    _write(ctx.raw_dir / "old.ogg", b"old")
    _png(ctx.png_dir / "old.png")

    def fake_extract(c):
        _png(c.raw_dir / "new.png")
        return _fake_stage("extract",
                           archives=[{"archive": "x.rpa", "expected": 1, "got": 1}],
                           expected_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _fake_stage("postprocess"))

    rc, man = orch.run(ctx)
    assert rc == 0, man
    assert not (ctx.raw_dir / "old.ogg").exists(), "旧 raw 必须被清掉"
    assert not (ctx.png_dir / "old.png").exists(), "旧 png 必须被清掉"
    assert (ctx.raw_dir / "new.png").is_file()
    reset = [s for s in man["stages"] if s["stage"] == "reset"]
    assert reset and reset[0]["ok"] is True, "清场要留下可复盘的一条 stage"


def test_manifest_verify_status_skipped_when_stage_never_ran(tmp_path, monkeypatch):
    """★核心★ extract 就失败了 → verify 根本没跑 → status 必须是 skipped，不是 failed。

    `verify.status` 的三种「没验」来源要分清：
      · --no-verify         → stage 存在、skipped=True、reason=disabled（阶段自己补）
      · 加密 krkr           → 工具自己写 reason=not-run
      · 前面阶段就失败       → **阶段不存在**，没人补 → 由 build_manifest 补 not-run
    """
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def boom(c):
        return orch.Stage("extract", ok=False, detail="模拟解包失败")

    monkeypatch.setattr(orch, "stage_extract_renpy", boom)

    rc, res = orch.run(ctx)
    man = orch._result_manifest(res)

    assert rc == 1
    assert man["ok"] is False
    assert man["verify"]["status"] == "skipped", "没验过的事不能被记成「验失败」"
    assert man["verify"]["reason"] == "not-run"


# ==========================================================================
# 第 16 节：半自动协作（2026-11-04）—— 失败时给可执行的人工方案
# ==========================================================================

def test_failure_carries_manual_plan_for_encrypted_kirikiri(tmp_path, monkeypatch):
    """★核心★ 加密 KiriKiri 失败必须带「做什么 + 放哪 + 之后跑什么」三条。

    只报一句「提取失败」等于把用户扔在半路：他不知道该用哪个工具、
    产物该放哪、放完怎么继续。这三件事缺一件，半自动模式就是空话。
    """
    ctx = _ctx(tmp_path, engine="KiriKiri")

    def fake_extract(c):
        return orch.Stage("extract", ok=False,
                          detail="GARbro 列不出目录（可能是加密 xp3，也可能是 Console 假阴性）")

    monkeypatch.setattr(orch, "stage_extract_kirikiri", fake_extract)

    rc, res = orch.run(ctx)
    man = orch._result_manifest(res)

    assert rc == 1
    plan = man["manual"]
    assert plan["code"] == "kirikiri-encrypted"
    assert plan["steps"], "没有步骤就不是方案"
    assert plan["target"].endswith("raw")
    assert "--reuse-raw" in plan["then"]
    assert res["manual"] == plan, "CLI 与 manifest 必须消费同一份，别各拼一遍"
    # GUI 用户看不到终端：完整方案必须落进 _work/manual.log（摘要只给前 3 步）
    log = (ctx.work_dir / "manual.log").read_text(encoding="utf-8")
    assert "需要人工介入" in log and plan["steps"][0] in log


def test_failure_without_a_usable_hint_does_not_invent_manual_block(tmp_path, monkeypatch):
    """没有合适的人工方案时不许硬凑（编出来的指引比错误码更害人）。"""
    ctx = _ctx(tmp_path, engine="Ren'Py")

    def fake_extract(c):
        return orch.Stage("extract", ok=False, detail="索引坏了")

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)

    rc, res = orch.run(ctx)
    man = orch._result_manifest(res)

    assert rc == 1
    assert "manual" not in man


def test_dry_run_predicts_manual_intervention_for_kirikiri(tmp_path, monkeypatch, capsys):
    """★半自动协作★ --dry-run 就要说清楚「会不会需要人工」，别等跑完 40 分钟。"""
    game = tmp_path / "game"
    game.mkdir()
    (game / "data.xp3").write_bytes(b"xp3" + b"\x00" * 64)
    out = tmp_path / "out"

    monkeypatch.setattr(orch.tb, "garbro_list", lambda p: (False, 0, "unknown format"))
    monkeypatch.setattr(orch, "stage_case_lookup",
                        lambda c, d: orch.Stage("case-lookup", ok=True, data={}))

    rc = orch.main([str(game), "--out", str(out), "--dry-run"])
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)          # stdout 必须仍是纯 JSON
    assert payload["auto_feasible"] is False
    assert payload["manual"]["code"] == "kirikiri-encrypted"
    assert "需要人工介入" in captured.err        # 人看的区块走 stderr
