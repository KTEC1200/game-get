#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「落盘即成品」类工具的 manifest 测试（2026-10-30）。

`rpa_extract_organized.py` / `_rpgmv_decrypt.py` / `_ypf_extract.py` 三个工具的格式转换
都做在**落盘之前**：磁盘上从来不存在 `.tlg`/`.ycg`/`.rpgmvp` 这类中间格式。
所以它们走 `manifest.counts_flat()`，语义是 `raw == final`、`converted == {}`。

关键断言：
  * 扁平工具**不许**伪造一个带中间格式的 raw 段（那是编数据）；
  * `converted` 必须是 `{}`，因为确实没有东西被「吃掉」；
  * 转换明细必须出现在 `postprocess`，不能丢；
  * 对账以各自的地面真相为准（RPA=索引去重条目数、YPF=表内条目数、
    RPGMV=工具自己数的 decrypt+plain_copy），且 `--dry` 时**不许假装对过账**。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import manifest as mf  # noqa: E402
import rpa_extract_organized as rpa  # noqa: E402
import _rpgmv_decrypt as rpg  # noqa: E402
import _ypf_extract as ypf  # noqa: E402


def _write(p: Path, data: bytes = b"x" * 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _png(p: Path) -> Path:
    return _write(p, b"\x89PNG\r\n\x1a\n" + b"x" * 16)


# ------------------------------------------------------------------ counts_flat


def test_counts_flat_raw_equals_final(tmp_path):
    out = tmp_path / "out"
    _png(out / "img" / "a.png")
    _write(out / "Audio_SFX" / "b.ogg")
    _write(out / "img" / "c.jpg")

    c = mf.counts_flat(out)
    assert c["raw"]["total"] == 3
    assert c["final"] == c["raw"], "落盘即成品 → raw 与 final 必须是同一份"
    assert c["converted"] == {}


def test_counts_flat_does_not_apply_convertible(tmp_path):
    """★核心★ 扁平工具不套 CONVERTIBLE：若输出目录真留着 .tlg，它就该被数进去。

    套了 CONVERTIBLE 会把它当「待转中间格式」悄悄从 final 里抹掉，
    于是 final 少了文件却没人报警 —— 这正是扁平语义与 raw/png 两目录语义的分界。
    """
    out = tmp_path / "out"
    _write(out / "a.ogg")
    _write(out / "b.tlg")           # 扁平工具没转它，那它就是成品

    c = mf.counts_flat(out)
    assert c["raw"]["total"] == 2
    assert c["final"]["total"] == 2
    assert ".tlg" in c["final"]["by_ext"]
    assert c["converted"] == {}


def test_counts_flat_missing_dir_is_zero(tmp_path):
    c = mf.counts_flat(tmp_path / "nope")
    assert c["raw"]["total"] == 0
    assert c["final"]["total"] == 0


# ------------------------------------------------------------------ Ren'Py


def test_rpa_manifest_counts_and_reconcile(tmp_path):
    dest = tmp_path / "out"
    _write(dest / "Audio_SFX" / "sound" / "se01.ogg")
    _write(dest / "Scripts" / "game" / "script.rpyc")
    cats = {"Audio_SFX": [1, 10], "Scripts": [1, 20]}

    man = rpa.write_manifest(dest, tmp_path / "a.rpa", "RPA-3.0", 0x42424242,
                             2, cats, tmp_path / "m.json")

    assert man["tool"] == "rpa_extract_organized.py"
    assert man["engine"] == "Ren'Py"
    assert man["counts"]["raw"]["total"] == 2
    assert man["counts"]["final"]["total"] == 2
    assert man["counts"]["converted"] == {}
    assert man["reconcile"] == {"expected": 2, "actual": 2, "diff": 0,
                               "method": "archive-index"}
    assert man["source"]["xor_key"] == "0x42424242"
    assert man["verify"]["verified"] is False


def test_rpa_manifest_reconcile_catches_missing_file(tmp_path):
    """索引说 3 个、落盘只有 2 个 → diff 必须是 -1，不许当成功。"""
    dest = tmp_path / "out"
    _write(dest / "a.ogg")
    _write(dest / "b.ogg")

    man = rpa.write_manifest(dest, tmp_path / "a.rpa", "RPA-3.0", 0x42424242,
                             3, {}, tmp_path / "m.json")
    assert man["reconcile"]["diff"] == -1


def test_rpa_manifest_records_classification(tmp_path):
    dest = tmp_path / "out"
    _write(dest / "a.ogg")
    cats = {"Audio_SFX": [7, 1234]}

    man = rpa.write_manifest(dest, tmp_path / "a.rpa", "RPA-3.0", 1,
                             1, cats, tmp_path / "m.json")
    detail = man["postprocess"][0]["detail"]
    assert detail["Audio_SFX"] == {"files": 7, "bytes": 1234}


# ------------------------------------------------------------------ RPG Maker


def _rpg_stats() -> Counter:
    s = Counter()
    s["decrypt"] = 3
    s["decrypt/.png"] = 2
    s["decrypt/.ogg"] = 1
    s["plain-copy"] = 1
    s["skip/nonmedia.json"] = 4
    return s


def test_rpgmv_manifest_counts_and_reconcile(tmp_path):
    out = tmp_path / "out"
    _png(out / "img" / "pictures" / "a.png")
    _png(out / "img" / "pictures" / "b.png")
    _write(out / "audio" / "se" / "c.ogg")
    _write(out / "img" / "pictures" / "d.png")   # plain-copy 那个

    man = rpg.write_manifest(out, tmp_path / "www", b"\x11" * 16,
                             _rpg_stats(), [], tmp_path / "m.json", dry=False)

    assert man["tool"] == "_rpgmv_decrypt.py"
    assert man["engine"] == "RPG Maker"
    assert man["counts"]["raw"]["total"] == 4
    assert man["counts"]["final"] == man["counts"]["raw"]
    assert man["counts"]["converted"] == {}
    # 地面真相 = decrypt(3) + plain-copy(1) = 4
    assert man["reconcile"] == {"expected": 4, "actual": 4, "diff": 0,
                               "method": "archive-index"}
    assert man["source"]["encryption_key"] == ("11" * 16)


def test_rpgmv_manifest_dry_run_is_explicitly_unverified(tmp_path):
    """★核心★ `--dry` 不落盘，产物数必然是 0；此时不许报「对账 0 差」。"""
    out = tmp_path / "out"          # 故意不存在
    man = rpg.write_manifest(out, tmp_path / "www", b"\x00" * 16,
                             _rpg_stats(), [], tmp_path / "m.json", dry=True)

    r = man["reconcile"]
    assert r["expected"] is None
    assert r["diff"] is None
    assert r["method"] == "no-index-available"
    assert r["actual"] == 0
    assert man["source"]["dry_run"] is True


def test_rpgmv_manifest_keeps_conversion_detail_and_magic_fails(tmp_path):
    out = tmp_path / "out"
    _write(out / "a.png")
    fails = ["img/x.png -> .png: magic=00 01 02"]

    man = rpg.write_manifest(out, tmp_path / "www", b"\x00" * 16,
                             _rpg_stats(), fails, tmp_path / "m.json", dry=False)

    detail = man["postprocess"][0]["detail"]
    assert detail["decrypt"] == 3
    assert detail["plain_copy"] == 1
    assert detail["by_target_ext"] == {".ogg": 1, ".png": 2}
    assert man["magic_fail_count"] == 1
    assert man["magic_fail"] == fails
    assert man["skipped"] == {"skip/nonmedia.json": 4}


# ------------------------------------------------------------------ Yu-Ris


def test_ypf_manifest_counts_and_reconcile(tmp_path):
    out = tmp_path / "out"
    _png(out / "cg" / "a.png")
    _write(out / "sound" / "b.ogg")

    man = ypf.write_manifest(out, tmp_path / "cg.ypf", 0x1EE, 0x5A,
                             2, n_zlib=1, n_ycg=1, n_plain=1, fails=[],
                             path=tmp_path / "m.json")

    assert man["tool"] == "_ypf_extract.py"
    assert man["engine"] == "Yu-Ris"
    assert man["counts"]["raw"]["total"] == 2
    assert man["counts"]["final"] == man["counts"]["raw"]
    assert man["counts"]["converted"] == {}
    assert man["reconcile"] == {"expected": 2, "actual": 2, "diff": 0,
                               "method": "archive-index"}
    assert man["source"]["entries"] == 2
    assert man["source"]["ypf_version"] == 0x1EE
    assert man["source"]["name_xor_key"] == 0x5A


def test_ypf_manifest_records_ycg_conversion(tmp_path):
    out = tmp_path / "out"
    _png(out / "a.png")

    man = ypf.write_manifest(out, tmp_path / "cg.ypf", 0x1EE, 1,
                             1, n_zlib=1, n_ycg=1, n_plain=0, fails=[],
                             path=tmp_path / "m.json")
    detail = man["postprocess"][0]["detail"]
    assert detail == {"zlib_inflate": 1, "ycg_to_png": 1, "plain_copy": 0}


def test_ypf_manifest_reconcile_catches_shortfall(tmp_path):
    """表说 10 个、落盘 2 个（比如全失败了）→ diff 必须暴露。"""
    out = tmp_path / "out"
    _write(out / "a.ogg")
    _write(out / "b.ogg")

    man = ypf.write_manifest(out, tmp_path / "cg.ypf", 0x1EE, 1,
                             10, n_zlib=0, n_ycg=0, n_plain=2,
                             fails=["x: boom"], path=tmp_path / "m.json")
    assert man["reconcile"]["diff"] == -8
    assert man["fail_count"] == 1


# ------------------------------------------------------------------ 共通契约


def test_all_three_tools_write_readable_json(tmp_path):
    """三份 manifest 都必须能原样读回、CJK 路径不转义、版本号一致。"""
    out = tmp_path / "出力"
    _write(out / "a.ogg")

    paths = [tmp_path / "rpa.json", tmp_path / "rpg.json", tmp_path / "ypf.json"]
    rpa.write_manifest(out, tmp_path / "ゲーム.rpa", "RPA-3.0", 1, 1, {}, paths[0])
    rpg.write_manifest(out, tmp_path / "ゲーム", b"\x00" * 16, Counter(
        {"decrypt": 1, "plain-copy": 0}), [], paths[1], dry=False)
    ypf.write_manifest(out, tmp_path / "cg.ypf", 0x1EE, 1, 1,
                       0, 0, 1, [], paths[2])

    for p in paths:
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        # 三份都必须记下「产物写到哪了」—— 交付清单缺输出目录就没法交付
        assert "出力" in text, f"{p.name} 没记录输出目录"
        assert "\\u51fa" not in text, "CJK 不许被转义成 \\uXXXX"
        back = json.loads(text)
        assert back["manifest_version"] == 1
        assert set(back["counts"]) == {"raw", "final", "converted"}
        assert back["source"]["out_root"] == str(out)


def test_all_three_tools_record_output_dir(tmp_path):
    """★回归护栏★ 只有输入路径、没有输出路径的 manifest 是不可交付的。"""
    out = tmp_path / "out"
    _write(out / "a.ogg")

    man_rpa = rpa.write_manifest(out, tmp_path / "a.rpa", "RPA-3.0", 1, 1, {},
                                 tmp_path / "m1.json")
    man_rpg = rpg.write_manifest(out, tmp_path / "www", b"\x00" * 16, Counter(
        {"decrypt": 1, "plain-copy": 0}), [], tmp_path / "m2.json", dry=False)
    man_ypf = ypf.write_manifest(out, tmp_path / "cg.ypf", 0x1EE, 1, 1,
                                 0, 0, 1, [], tmp_path / "m3.json")

    for man in (man_rpa, man_rpg, man_ypf):
        assert man["source"]["out_root"] == str(out)
