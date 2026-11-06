# -*- coding: utf-8 -*-
"""`stage_organize` 与后处理「复用已转产物」的阶段级测试。

两条都是 2026-11-06 实跑 `教师催眠2`（9818 文件）时踩出来的：
  1. `Stage.ok` 默认 **False**，归档阶段漏赋值 → 「硬链接 9818、失败 0」被判成 `[FAIL]`，
     交付记录自相矛盾；
  2. 后处理不认已转好的 png，重跑会把 2748 张 tlg 再解一遍（20 分钟）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402


def _ctx(tmp_path: Path, organize: bool = True) -> orch.Ctx:
    out = tmp_path / "out"
    (out / "raw").mkdir(parents=True)
    return orch.Ctx(game_dir=tmp_path / "game", out_dir=out, work_dir=out / "_work",
                    manifest_path=out / "manifest.json", organize=organize)


def test_stage_organize_ok_when_disabled(tmp_path):
    st = orch.stage_organize(_ctx(tmp_path, organize=False))

    assert st.ok, "未启用是「跳过」，不是「失败」"
    assert st.skipped


def test_stage_organize_ok_and_reports_kinds(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.raw_dir / "a.png").write_bytes(b"x")
    (ctx.raw_dir / "b.ogg").write_bytes(b"y")

    st = orch.stage_organize(ctx)

    assert st.ok, "★实测踩过★ Stage.ok 默认 False，忘赋值会把成功判成 [FAIL]"
    assert st.data["kinds"]["图片"] == 1
    assert st.data["kinds"]["音频"] == 1
    assert st.data["failed"] == 0
    assert (ctx.out_dir / "类目清单.csv").is_file()


def test_stage_organize_ok_even_if_link_fails(tmp_path, monkeypatch):
    """个别链接失败不该把阶段判红 —— 失败数已经写在 detail/data 里。"""
    from organize import os as org_os
    ctx = _ctx(tmp_path)
    (ctx.raw_dir / "c.ogg").write_bytes(b"z")
    monkeypatch.setattr(org_os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))

    st = orch.stage_organize(ctx)

    assert st.ok
    assert st.data["failed"] == 1


def test_converted_fresh_uses_mtime(tmp_path):
    src = tmp_path / "a.tlg"
    dst = tmp_path / "a.png"
    src.write_bytes(b"1")
    assert not orch._converted_fresh(dst, src), "产物不存在 → 不算新鲜"

    dst.write_bytes(b"2")
    now = time.time()
    os.utime(dst, (now + 5, now + 5))
    assert orch._converted_fresh(dst, src)

    os.utime(dst, (now - 100, now - 100))          # 产物比源旧 → 必须重转
    assert not orch._converted_fresh(dst, src)

    dst.write_bytes(b"")                            # 空文件 → 必须重转
    os.utime(dst, (now + 5, now + 5))
    assert not orch._converted_fresh(dst, src)


def test_stage_as_dict_keeps_ok_boolean():
    """★实测踩过★ 后处理 data 里也有 `ok`（转换成功数），别把阶段结论盖成数字。

    2026-11-06：`manifest.stages[].ok` 里出现 `2748`，读的人以为「ok 不是布尔」。
    """
    st = orch.Stage("postprocess", ok=True, detail="x")
    st.data = {"ok": 2748, "fail": 0}

    d = st.as_dict()

    assert d["ok"] is True, "阶段结论必须是布尔，不能被 data 里的同名键盖掉"
    assert st.data["ok"] == 2748, "原始计数仍留在 data 里，别丢"
