"""`_rpgmv_decrypt.load_key()` 的三种情形。

这条分支值得单独测，因为它决定「一个游戏是被正确解出来，还是被工具判死」：

- 显式 key      → 用它
- 无 key + 未加密 → **不许报错**，走原样复制（这正是最常见的 MV/MZ 发行形态之一）
- 无 key + 声明加密 → 报错，并提示 `--key`

早期实现把后两种一律当错误退出，等于把「没加密的好游戏」判成「解不了」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _rpgmv_decrypt as rpgmv  # noqa: E402


def _www(tmp_path: Path, system: dict) -> Path:
    www = tmp_path / "www"
    (www / "data").mkdir(parents=True)
    (www / "data" / "System.json").write_text(
        json.dumps(system), encoding="utf-8")
    return www


def test_explicit_key_is_used(tmp_path):
    www = _www(tmp_path, {"encryptionKey": "0" * 32})
    assert rpgmv.load_key(www, None) == b"\x00" * 16


def test_override_wins_over_system_json(tmp_path):
    www = _www(tmp_path, {"encryptionKey": "0" * 32})
    assert rpgmv.load_key(www, "ff" * 16) == b"\xff" * 16


def test_no_key_and_not_encrypted_does_not_raise(tmp_path):
    """★核心★ 未加密的游戏必须能跑通（原样复制），不能被判死。"""
    www = _www(tmp_path, {"hasEncryptedImages": False, "hasEncryptedAudio": False})
    key = rpgmv.load_key(www, None)
    assert key == bytes.fromhex(rpgmv.MD5_EMPTY)


def test_no_key_but_declared_encrypted_raises(tmp_path):
    www = _www(tmp_path, {"hasEncryptedImages": True})
    with pytest.raises(SystemExit) as ei:
        rpgmv.load_key(www, None)
    assert "--key" in str(ei.value)


def test_bad_length_raises(tmp_path):
    www = _www(tmp_path, {"encryptionKey": "abcd"})
    with pytest.raises(SystemExit) as ei:
        rpgmv.load_key(www, None)
    assert "32" in str(ei.value)


def test_default_key_constant_is_md5_of_empty():
    """MD5("") 就是 RPG Maker 的默认口令——实测 `常識改変学園` 写的就是它。"""
    import hashlib
    assert rpgmv.MD5_EMPTY == hashlib.md5(b"").hexdigest()


# ---------------------------------------------------------------------------
# iter_candidates / expected_total：落盘与对账共用的唯一地面真相
# ---------------------------------------------------------------------------


def test_iter_candidates_skips_junk_and_nonmedia(tmp_path):
    www = _www(tmp_path, {"encryptionKey": "0" * 32})
    (www / "img").mkdir()
    (www / "img" / "a.rpgmvp").write_bytes(b"RPGMV" + b"\x00" * 11 + b"x" * 16)
    (www / "img" / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (www / "notes.txt").write_text("no")
    (www / "免责声明" / "junk").mkdir(parents=True)
    (www / "免责声明" / "junk" / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (www / "icon").mkdir()
    (www / "icon" / "d.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    got = sorted(rel.as_posix() for _p, rel, _e in rpgmv.iter_candidates(www))

    assert got == ["img/a.rpgmvp", "img/b.png"]


def test_expected_total_matches_iteration(tmp_path):
    www = _www(tmp_path, {"encryptionKey": "0" * 32})
    for i in range(4):
        (www / f"{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert rpgmv.expected_total(www) == 4
