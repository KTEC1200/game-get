# -*- coding: utf-8 -*-
"""产物按类型归档（organize.py）的测试。

锁四件事：
  1. 分类**扩展名优先**（坑 5：按目录判会把 282 个 jpg 分进视频）；
  2. 视图用硬链接、**不复制**；链接失败要如实计数而不是静默；
  3. 清单是给人看的（UTF-8 BOM，Excel 双击不乱码）；
  4. 重复跑不能互相覆盖（顺延成 `分类-2`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import organize  # noqa: E402


def test_kind_of_prefers_extension():
    assert organize.kind_of("raw/a.png") == organize.IMAGE
    assert organize.kind_of("raw/sub/a.OGG") == organize.AUDIO
    assert organize.kind_of("png/movie.webm") == organize.VIDEO


def test_kind_of_falls_back_to_directory_hint():
    """扩展名认不出时看目录名 —— `bgm/` 下的 `.snd` 该算音频。"""
    assert organize.kind_of("raw/bgm/track01.snd") == organize.AUDIO
    assert organize.kind_of("raw/movie/opening.dat") == organize.VIDEO


def test_kind_of_defaults_to_other():
    assert organize.kind_of("raw/script.ks") == organize.OTHER
    assert organize.kind_of("raw/noext") == organize.OTHER


def test_plan_carries_size_and_ext(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"1234")

    rows = organize.plan([(f, "raw/a.png")])

    assert rows[0]["kind"] == organize.IMAGE
    assert rows[0]["ext"] == "png"
    assert rows[0]["size"] == 4


def test_plan_keeps_missing_files_with_negative_size(tmp_path):
    """枚举后文件消失也要留一行：静默丢掉会让「清单总数」和交付数对不上。"""
    rows = organize.plan([(tmp_path / "gone.ogg", "raw/gone.ogg")])

    assert rows[0]["kind"] == organize.AUDIO
    assert rows[0]["size"] == -1


def test_organize_links_without_copying(tmp_path):
    src = tmp_path / "out" / "raw"
    src.mkdir(parents=True)
    (src / "cg.png").write_bytes(b"x" * 10)
    (src / "bgm.ogg").write_bytes(b"y" * 10)
    out = tmp_path / "out"

    res = organize.organize([(src / "cg.png", "raw/cg.png"),
                             (src / "bgm.ogg", "raw/bgm.ogg")], out)

    assert res["total"] == 2
    assert res["kinds"][organize.IMAGE] == 1
    assert res["kinds"][organize.AUDIO] == 1
    assert res["linked"] == 2 and res["failed"] == 0
    view = Path(res["view"])
    assert (view / organize.IMAGE / "raw" / "cg.png").exists()
    # 硬链接：同一 inode（Windows 上 st_ino 相同）
    assert (view / organize.IMAGE / "raw" / "cg.png").stat().st_ino == (src / "cg.png").stat().st_ino


def test_organize_writes_csv_with_bom(tmp_path):
    (tmp_path / "out").mkdir()
    src = tmp_path / "a.mp4"
    src.write_bytes(b"z")

    res = organize.organize([(src, "raw/a.mp4")], tmp_path / "out")

    raw = Path(res["csv"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "不带 BOM 的 CSV 在 Excel 里是乱码"
    text = Path(res["csv"]).read_text(encoding="utf-8-sig")
    assert "类目,相对路径" in text and "视频" in text


def test_organize_counts_link_failures(tmp_path, monkeypatch):
    src = tmp_path / "b.ogg"
    src.write_bytes(b"q")
    out = tmp_path / "out"
    out.mkdir()

    def boom(*_a, **_k):
        raise OSError("cross-device link")

    monkeypatch.setattr(organize.os, "link", boom)

    res = organize.organize([(src, "raw/b.ogg")], out)

    assert res["linked"] == 0 and res["failed"] == 1
    assert not (out / organize.AUDIO / "raw" / "b.ogg").exists(), "失败不能偷偷改成复制"


def test_organize_suffixes_when_view_exists(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / organize.VIEW_NAME / "旧").mkdir(parents=True)
    (out / organize.VIEW_NAME / "旧" / "keep.txt").write_text("keep", encoding="utf-8")
    src = tmp_path / "c.png"
    src.write_bytes(b"1")

    res = organize.organize([(src, "png/c.png")], out)

    assert Path(res["view"]).name == f"{organize.VIEW_NAME}-2"
    assert (out / organize.VIEW_NAME / "旧" / "keep.txt").exists(), "旧视图不能被覆盖"
