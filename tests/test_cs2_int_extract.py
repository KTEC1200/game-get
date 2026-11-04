#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`_cs2_int_extract.py` 的地面真相与魔数识别 —— CatSystem2 链路的护栏。

为什么要单独测这一段：CatSystem2 有**两个反直觉的坑**，两个都是「不测就必然踩」：

1. **扩展名不可信**。引擎对扩展名做了二次轮换（实测 3907 个 OggS 里只有 148 个
   恰好叫 `.ogg`，≈1/26），所以「这个文件是什么」只能问魔数。判错方向的代价是
   `.mos` 那次的翻版：认不出来的媒体落进 `nonmedia` 被**静默放过**，验收照样报「失败 0」。
2. **`HG-3` 判据只能恰好 4 字节**。放宽成 `HG-` 前缀就会把别的家族成员误当 HG-3，
   而 `_hg3_tool.cs:IsHg3Magic()` 是严格 4 字节 —— 工具与判据必须逐字节一致。

地面真相（`expected_counts` / `hg3_expected_png`）是**唯一出处**：`main()` 的收尾对账和
`orchestrator.py` 的期望值都调它。它算错，两边就一起错，而且错得自洽（对账 0 差）。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _cs2_int_extract as cs2  # noqa: E402


# ---------------------------------------------------------------- 脚手架

def _kif(path: Path, entries: int = 5) -> Path:
    """最小 KIF 头：`KIF\\0` + u32 声明条目数；头长必须 ≥ 0x50（`_head(p, 0x50)`）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"KIF\x00" + struct.pack("<I", entries) + b"\x00" * (0x50 - 8))
    return path


def _hg3(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"HG-3" + b"\x00" * 24)
    return path


# ---------------------------------------------------------------- sniff_ext

@pytest.mark.parametrize("data,expected", [
    (b"HG-3\x00\x00", ".hg3"),
    (b"OggS\x00\x02\x00\x00", ".ogg"),
    (b"RIFF\x00\x00\x00\x00WAVE", ".wav"),
    (b"\x89PNG\r\n\x1a\n\x00\x00", ".png"),
    (b"DDST\x00\x00", ".dds"),
    (b"BM\x00\x00", ".bmp"),
    (b"\xff\xd8\xff\xe0\x00\x10", ".jpg"),
    (b"\x00\x00\x01\xba\x44\x00", ".mpg"),
    (b"\x00\x00\x01\xb3\x00\x00", ".mpg"),
    (b"\x30\x26\xb2\x75\x8e\x66", ".wmv"),
    (b"KIF\x00\x00\x00\x00", ".int"),
    (b"\x00\x00\x00\x20ftypisom", ".mp4"),
    (b"ID3\x04\x00\x00", ".mp3"),
    (b"\x78\x9c\x00\x00", ".zz"),
    (b"PK\x03\x04", ".zip"),
])
def test_sniff_ext_reads_magic_not_name(data: bytes, expected: str):
    assert cs2.sniff_ext(data) == expected


def test_sniff_ext_hg3_must_be_exactly_four_bytes():
    """判据是 `HG-3` 四个字节 —— `HG-x`/`HG-4` 都不算（与 IsHg3Magic() 逐字节一致）。"""
    assert cs2.sniff_ext(b"HG-4\x00\x00") == ".bin"
    assert cs2.sniff_ext(b"HG-\x00\x00\x00") == ".bin"


def test_sniff_ext_unknown_and_short_are_bin():
    assert cs2.sniff_ext(b"\x4c\x50\x44\x00\x3c\x00\x00\x00") == ".bin"   # LPD\0：数据，不是媒体
    assert cs2.sniff_ext(b"") == ".bin"
    assert cs2.sniff_ext(b"O") == ".bin"


# ---------------------------------------------------------------- 地面真相

def test_int_files_lists_by_suffix_so_bad_ones_get_reported(tmp_path: Path):
    """`int_files` **按扩展名**收候选（不是按魔数）——这是有意的：

    魔数不对的 `.int` 必须仍然被收进来，好让 `expected_counts` 把它列进 `unlistable`
    **报出来**；在这里就按魔数筛掉，它只会静默消失（正是我们要防的那种漏）。
    真正按魔数分类的是 `is_int()` / `expected_counts()`。
    """
    _kif(tmp_path / "a.int", 3)
    (tmp_path / "b.int").write_bytes(b"XXXX" + b"\x00" * 0x50)     # 扩展名像，魔数不对
    (tmp_path / "c.bin").write_bytes(b"KIF\x00" + b"\x00" * 0x50)  # 魔数像，扩展名不对
    assert [p.name for p in cs2.int_files(tmp_path)] == ["a.int", "b.int"]
    assert cs2.is_int(tmp_path / "a.int") is True
    assert cs2.is_int(tmp_path / "b.int") is False
    assert cs2.is_int(tmp_path / "c.bin") is True          # 魔数对，但不是 .int 候选
    assert cs2.expected_counts(tmp_path)["unlistable"] == ["b.int"]


def test_expected_counts_declares_count_minus_one(tmp_path: Path):
    """头部声明的是「含索引自己在内的条数」，真条目数要减 1。"""
    _kif(tmp_path / "a.int", 5)
    _kif(tmp_path / "b.int", 1)
    exp = cs2.expected_counts(tmp_path)
    assert exp["by_arc"] == {"a.int": 4, "b.int": 0}
    assert exp["total"] == 4
    assert exp["arcs"] == ["a.int", "b.int"]
    assert exp["unlistable"] == []


def test_expected_counts_marks_short_or_foreign_as_unlistable(tmp_path: Path):
    _kif(tmp_path / "good.int", 3)
    (tmp_path / "short.int").write_bytes(b"KIF\x00" + b"\x00" * 10)     # 头不足 0x50
    (tmp_path / "foreign.int").write_bytes(b"NOPE" + b"\x00" * 0x50)
    exp = cs2.expected_counts(tmp_path)
    assert exp["by_arc"] == {"good.int": 2}
    assert exp["total"] == 2
    assert sorted(exp["unlistable"]) == ["foreign.int", "short.int"]
    assert exp["arcs"] == ["good.int"]          # 列不出的不进 arcs（不参与对账）


def test_expected_counts_empty_dir(tmp_path: Path):
    exp = cs2.expected_counts(tmp_path)
    assert exp == {"total": 0, "by_arc": {}, "unlistable": [], "arcs": []}


# ---------------------------------------------------------------- HG-3 期望

def test_hg3_files_scans_whole_tree_by_magic(tmp_path: Path):
    """扩展名任意（`.KCC` 也算），只要内容以 `HG-3` 开头。"""
    _hg3(tmp_path / "g" / "a.hg3")
    _hg3(tmp_path / "g" / "deep" / "b.KCC")
    (tmp_path / "g" / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    names = [Path(p).name for p in cs2.hg3_files(tmp_path)]
    assert names == ["a.hg3", "b.KCC"]          # 排序稳定，别用「两种都行」放过断言
    assert cs2.is_hg3(tmp_path / "g" / "deep" / "b.KCC") is True


def test_hg3_expected_png_dedupes_same_stem(tmp_path: Path):
    """同目录同 stem 的两个 HG-3 会被 `.png` 归一化撞在一起：解码 3 个、成品 2 张。"""
    _hg3(tmp_path / "a.hg3")
    _hg3(tmp_path / "a.nm3")      # 与 a.hg3 同 stem → 同一张 a.png
    _hg3(tmp_path / "b.hg3")
    exp = cs2.hg3_expected_png(tmp_path)
    assert exp["count"] == 3
    assert exp["png"] == ["a.png", "b.png"]
    assert exp["png_count"] == 2
    assert exp["collisions"] == 1


def test_hg3_expected_png_keeps_subdirs_apart(tmp_path: Path):
    """不同目录的同名文件不撞车（相对路径不同）。"""
    _hg3(tmp_path / "x" / "a.hg3")
    _hg3(tmp_path / "y" / "a.nm3")
    exp = cs2.hg3_expected_png(tmp_path)
    assert exp["png_count"] == 2
    assert exp["collisions"] == 0


def test_hg3_expected_png_dedupes_case_insensitively(tmp_path: Path):
    """★核心★ 只差大小写的两个目标在 NTFS 上是同一个文件 —— 必须只算一张。

    真样本（甜蜜女友2+）实测：4502 个 HG-3 里有 3 组只差大小写（`J_WJNu17n_0h.hg3`
    与 `j_wjnU17N_0H.ml3` 等），工具落盘 4499 张。按大小写敏感去重会算成 4501 张，
    于是把一次完全正确的解包判成「产物不足」——护栏算错比不设护栏更坏。
    """
    _hg3(tmp_path / "J_WJNu17n_0h.hg3")
    _hg3(tmp_path / "j_wjnU17N_0H.ml3")
    _hg3(tmp_path / "plain.hg3")
    exp = cs2.hg3_expected_png(tmp_path)

    assert exp["count"] == 3
    assert exp["png_count"] == 2, "两个只差大小写 → 同一张 PNG"
    assert exp["collisions"] == 1
    assert len({p.lower() for p in exp["png"]}) == exp["png_count"], \
        "返回的路径里也不能有两个只差大小写的"


# ---------------------------------------------------------------- write_manifest

def test_write_manifest_records_ground_truth(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.ogg").write_bytes(b"OggS" + b"\x00" * 20)
    (out / "b.ogg").write_bytes(b"OggS" + b"\x00" * 20)
    exp = {"total": 2, "by_arc": {"pcm.int": 2}, "unlistable": [], "arcs": ["pcm.int"]}
    man = cs2.write_manifest(out, tmp_path, exp, 2, 0, 0x212C5F31, None, [],
                             tmp_path / "m.json")

    assert man["engine"] == "CatSystem2"
    assert man["tool"] == "_cs2_int_extract.py"
    assert man["reconcile"] == {"expected": 2, "actual": 2, "diff": 0,
                               "method": "archive-index"}
    assert man["source"]["main_key"] == "212C5F31"
    assert man["source"]["passphrase_found"] is False
    # 规范三键（2026-11-04）：entries=地面真相，extracted=实测。这里没有实测数就填 None，
    # 不许把「索引声明 2 条」同时当成「落盘了 2 条」—— 那让没对过账看起来像对上了。
    assert man["source"]["archives"] == [
        {"name": "pcm.int", "entries": 2, "extracted": None}]
    assert man["counts"]["raw"]["total"] == 2
    assert man["verify"]["verified"] is False          # 不信口开河说自己验过了
    assert (tmp_path / "m.json").is_file()


def test_write_manifest_accepts_str_paths(tmp_path: Path):
    """契约函数要 Path，但 main() 传进来的是 str —— 必须自己转（曾因此丢过清单）。"""
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.ogg").write_bytes(b"OggS" + b"\x00" * 20)
    exp = {"total": 1, "by_arc": {"pcm.int": 1}, "unlistable": [], "arcs": ["pcm.int"]}
    man = cs2.write_manifest(str(out), str(tmp_path), exp, 1, 0, 0x212C5F31, None,
                             [], tmp_path / "m.json")
    assert man["reconcile"]["diff"] == 0


def test_write_manifest_notes_unlistable_archives(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exp = {"total": 0, "by_arc": {}, "unlistable": ["weird.int"], "arcs": []}
    man = cs2.write_manifest(out, tmp_path, exp, 0, 0, 0x212C5F31, None, [],
                             tmp_path / "m.json")
    assert man["source"]["unlistable"] == ["weird.int"]
    assert man["source"]["archives"][0]["entries"] is None
    assert "列不出条目" in man["source"]["archives"][0]["note"]
    assert man["reconcile"]["diff"] == 0        # 0 vs 0：确实没有落盘产物


# ---------------------------------------------------------------- 内存：分块解密

def _blowfish():
    """造一个真实的小 Blowfish（密钥随便取，测的是**分块等价性**不是密钥推导）。"""
    return cs2.Blowfish(b"\x01\x02\x03\x04")


def test_decipher_fast_chunking_is_equivalent(monkeypatch):
    """★核心★ 分块解密必须与「整段一次」逐字节相同。

    分块是为了控内存（本作最大条目几百 MB，整段 numpy 变换会吃 4~5 倍内存，
    13.8 GiB 的机器上实测被压死）。但 Blowfish-ECB 逐块独立、半块反转也是每 8 字节一次，
    所以按 8 的整数倍切段**结果完全一致** —— 这条测试就是那个「所以」的凭据。
    """
    pytest.importorskip("numpy")
    pytest.importorskip("Crypto")

    bf = _blowfish()
    plain = bytes(range(256)) * 8          # 2048 字节
    whole = bytearray(plain)
    cs2.decipher_fast(bf, whole, len(whole))

    monkeypatch.setattr(cs2, "_CHUNK", 16)  # 逼它走 128 次分块
    chunked = bytearray(plain)
    cs2.decipher_fast(bf, chunked, len(chunked))

    assert bytes(chunked) == bytes(whole)
    assert bytes(whole) != plain           # 确实解密过，不是「两边都没动」的假绿


def test_decipher_fast_respects_length_boundary(monkeypatch):
    """只解前 `length` 字节（尾部不足一块的要原样留着）。"""
    pytest.importorskip("numpy")
    pytest.importorskip("Crypto")

    bf = _blowfish()
    plain = bytes(range(64))
    full = bytearray(plain)
    cs2.decipher_fast(bf, full, 64)
    partial = bytearray(plain)
    cs2.decipher_fast(bf, partial, 32)

    assert bytes(partial[:32]) == bytes(full[:32])
    assert bytes(partial[32:]) == plain[32:]      # 尾部没被动过


def test_chunk_constant_is_aligned():
    """分块大小必须是 8 的整数倍（Blowfish 块 = 8 字节），否则会切碎块、解出错数据。"""
    assert cs2._CHUNK % 8 == 0
    assert cs2._CHUNK >= 8 * 1024


# ---------------------------------------------------------------- main 参数

def test_main_without_args_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["_cs2_int_extract.py"])
    assert cs2.main() == 2
    assert "usage" in capsys.readouterr().out


def test_main_manifest_without_path_returns_2(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setattr(sys, "argv",
                        ["_cs2_int_extract.py", str(tmp_path), str(tmp_path / "o"),
                         "--manifest"])
    assert cs2.main() == 2
    assert "--manifest 需要一个路径参数" in capsys.readouterr().err


def test_main_dir_without_int_returns_1(monkeypatch, capsys, tmp_path: Path):
    """没有 KIF `.int` 时报错退出，且**不改动**任何东西。"""
    (tmp_path / "readme.txt").write_text("hi")
    monkeypatch.setattr(sys, "argv",
                        ["_cs2_int_extract.py", str(tmp_path), str(tmp_path / "o")])
    assert cs2.main() == 1
    err = capsys.readouterr().err
    assert "没有 KIF 格式的 .int" in err
    assert not (tmp_path / "o").exists()
