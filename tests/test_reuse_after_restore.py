# -*- coding: utf-8 -*-
"""QA 独立验证：从「分类」硬链接视图恢复 raw/ + png/ 后，`--reuse-raw --organize` 能否 rc=0。

现场（2026-11-07 教师催眠2）：旧 `--overwrite` 直接删掉 raw/ 与 png/，GUI 链路随后失败；
`分类/` 硬链接视图里的 9818 个**交付文件**完好，`tools/restore_from_view.py` 只重建硬链接。
原 raw/ 里的 .tlg/.pna 中间格式不在视图内、恢复不回来。本文件在 **tmp_path 临时目录**
复刻这个现场，锁住四个容易踩的点（绝不在真实输出目录上跑）：

  1. `stage_postprocess` 扫不到 .tlg/.pna 时是 skipped + ok，不重转、不失败；
  2. `verify` 的 final 计数 = raw 交付 + png 成品，图片数不因源 tlg 缺失而变；
  3. `manifest.stages[].ok` 全是布尔（不被 data["ok"] 覆盖成数字），加密 xp3
     列不出索引时 reconcile 如实标 no-index-available，不伪装成 0 差；
  4. 视图已存在时 `--organize` 原地重建，不删视图条目，也不动 raw/ 与 png/。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402
import organize  # noqa: E402
import manifest  # noqa: E402


def _png_bytes() -> bytes:
    """现生成一张合法 PNG —— 手抄的 base64 常量曾因 IDAT 校验和坏掉把 verify 判失败。"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


def _files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


def _restored_scene(tmp_path: Path) -> tuple[orch.Ctx, int]:
    """复刻「恢复后」现场：raw 只有交付文件、png 是成品、视图与清单已存在。"""
    game = tmp_path / "game"
    out = tmp_path / "output"
    game.mkdir()
    # 加密 xp3：garbro -l 全部列不出 → 无索引地面真相（教师催眠2 的真实情形）
    (game / "image02.xp3").write_bytes(b"NOT-A-REAL-XP3")

    raw, png = out / "raw", out / "png"
    (raw / "scenario").mkdir(parents=True)
    (raw / "voice").mkdir(parents=True)
    (png / "image02").mkdir(parents=True)
    image = _png_bytes()
    (raw / "scenario" / "00_共通.ks").write_text("; scenario\n", encoding="utf-8")
    (raw / "voice" / "a.ks").write_text("; voice index\n", encoding="utf-8")
    (raw / "voice" / "b.ks").write_text("; voice index\n", encoding="utf-8")
    (png / "image02" / "A.png").write_bytes(image)
    (png / "image02" / "B.png").write_bytes(image)
    (png / "image02" / "C.png").write_bytes(image)

    # 用户现场已有 分类/ 视图 + 类目清单.csv（恢复前就完好）
    files = manifest.iter_final_files(raw, png, orch.CONVERTIBLE, [])
    organize.organize(files, out)
    assert (out / "分类" / ".galunpack-view").is_file()

    ctx = orch.Ctx(
        game_dir=game, out_dir=out, work_dir=out / "_work",
        manifest_path=out / "manifest.json", engine="KiriKiri",
        reuse_raw=raw, organize=True, do_verify=True, verify_jobs=1,
    )
    return ctx, len(files)


def test_reuse_raw_after_view_restore_is_clean(tmp_path, monkeypatch):
    ctx, expected_final = _restored_scene(tmp_path)
    raw_before = _files(ctx.raw_dir)
    png_before = _files(ctx.png_dir)
    view_before = _files(ctx.out_dir / "分类") - 1  # 减掉 .galunpack-view 标记

    # 模拟 11 个加密 xp3 全部 `unknown format`；同时锁死「不许重转 .tlg」。
    monkeypatch.setattr(orch.tb, "garbro_list",
                        lambda _p: (False, 0, "unknown format"))

    def must_not_convert(*_a, **_kw):
        raise AssertionError("恢复后 raw 里没有 .tlg/.pna，postprocess 不该调用转换器")

    monkeypatch.setattr(orch.tb, "tlg2png", must_not_convert)

    rc, man = orch.run(ctx)
    assert rc == 0, f"恢复后复跑应当 rc=0，实际 rc={rc} man={man}"

    stages = {s["stage"]: s for s in man["stages"]}
    pp = stages["postprocess"]
    assert pp["ok"] is True and pp["skipped"] is True
    assert "无待转格式" in pp["detail"], "源 .tlg 缺失应跳过转换，不是重转或报错"

    ver = man["verify"]
    assert ver["image_ok"] == 3 and ver["image_fail"] == 0, \
        "PNG 成品数不因源 tlg 缺失而变"
    assert man["counts"]["final"]["total"] == expected_final
    assert all(isinstance(s["ok"], bool) for s in man["stages"]), \
        "stages[].ok 必须是布尔（v0.7.1 的 data['ok'] 覆盖事故别回潮）"
    assert man["reconcile"]["method"] == "no-index-available"
    assert man["reconcile"]["diff"] is None, "没验不许伪装成 0 差"
    assert man.get("error") in (None, ""), man

    # 归档只加视图：原始数据一个不少，视图条目也没被 prune 掉
    assert _files(ctx.raw_dir) == raw_before
    assert _files(ctx.png_dir) == png_before
    assert _files(ctx.out_dir / "分类") - 1 == view_before
    assert (ctx.out_dir / "分类" / ".galunpack-view").is_file()


def test_reuse_raw_with_listable_index_flags_missing_intermediates(tmp_path, monkeypatch):
    """边界：**只有加密包（无索引）**才适用「恢复后 rc=0」。

    若 GARbro 列得出索引，复用分支会拿索引条目数对着 raw/ 数；恢复后的 raw/
    少了 .tlg/.pna 中间格式，必然对账失败。这不是回归，是如实报出「数据不齐」——
    这类样本只能重新解包，不能靠视图恢复后半路复用。
    """
    ctx, _ = _restored_scene(tmp_path)
    monkeypatch.setattr(orch.tb, "garbro_list", lambda _p: (True, 5, "5 entries"))
    rc, res = orch.run(ctx)
    assert rc == 1
    stages = {s["stage"]: s for s in res["stages"]}
    assert stages["extract"]["ok"] is False
    assert "复用产物对账失败" in stages["extract"]["detail"]
    assert orch._result_manifest(res)["error"] == "extract-failed"


def test_reuse_raw_strict_still_flags_missing_ground_truth(tmp_path, monkeypatch):
    """加密包没有索引时 strict 模式应明确判失败；默认模式放行是既有契约。"""
    ctx, _ = _restored_scene(tmp_path)
    ctx.strict = True
    monkeypatch.setattr(orch.tb, "garbro_list",
                        lambda _p: (False, 0, "unknown format"))
    monkeypatch.setattr(orch.tb, "tlg2png",
                        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("不该重转")))
    rc, man = orch.run(ctx)
    assert rc == 1
    assert man["error"] == "strict-no-ground-truth"
