#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SPITE（Electron 自研引擎）资源解密器。

逆向自 app.asar 内 dist-electron/services/media-crypto.cjs / media-protocol.cjs / media-pack.cjs：
  * 文件名 = sha256(mediaPath).hex[:16]（mediaPath 为 URL 去掉开头 `/` 后的路径）；
  * key/nonce = HKDF-SHA256(ikm=48 字节硬编码常量, salt="spite-media-salt",
                             info="spite-media-chacha20:" + mediaPath, L=44) → key32 + nonce12；
  * 密文体 = 原始文件 ⊕ ChaCha20 流（noble/ciphers 的 chacha20，无 Poly1305 标签，
    计数器起点实测为 0，即 RFC 8439 原版）；
  * 资源两处存放：data/<hash>.dat 单文件，或 data/_dafab9efd603f53.dat（SPAK 打包：
    12 字节头 "SPAK"+ver+count，count×28 字节条目 [16B ascii hash + u32 offset + u32 length]，
    数据区从 12 + count*28 开始，条目同样加密）；
  * mediaPath 的来源是 asar 内的文本（渲染层 JS 字符串、Ink 剧情裸路径），
    以及 Spine .atlas 解出后自带的贴图页相对路径 —— 故采用多轮「解密→反哺路径」。

用法:
  python _spite_decrypt.py <游戏目录> <asar解包根目录> <输出目录>
只读游戏目录；输出按扩展名归类到 <输出>/Media_<ext>/。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import struct
import sys
from pathlib import Path

from Crypto.Cipher import ChaCha20

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ---- media-crypto.cjs 里的硬编码常量 ----
IKM_A = [0xe0, 0x2c, 0x7e, 0xde, 0xb7, 0xe1, 0x64, 0x2b, 0xb1, 0xb1, 0x39, 0x5f, 0x1c, 0x88, 0x27, 0xa0]
IKM_B = [0x88, 0x8a, 0x5c, 0xc7, 0x04, 0x45, 0x0d, 0xef, 0x36, 0x6e, 0xe5, 0xca, 0x3b, 0x63, 0xe1, 0x30]
IKM_C = [0xae, 0x03, 0x3d, 0x6c, 0x73, 0x6c, 0x5e, 0x88, 0xfd, 0xf5, 0x30, 0x9f, 0xe2, 0x2c, 0x39, 0x81]
IKM = bytes(IKM_A + IKM_B + IKM_C)
SALT = b"spite-media-salt"
INFO_PREFIX = "spite-media-chacha20:"
PACK_NAME = "_dafab9efd603f53"

MEDIA_EXTS = ("png", "webp", "jpg", "jpeg", "ogg", "mp3", "wav", "webm", "mp4",
              "skel", "atlas")
EXT_ALT = "|".join(MEDIA_EXTS)

MAGICS = {
    b"\x89PNG": ".png", b"OggS": ".ogg", b"ID3": ".mp3", b"\x1a\x45\xdf\xa3": ".webm",
}


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF（extract + expand），与 node:crypto hkdfSync 等价。"""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out = b""
    t = b""
    i = 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def derive(media_path: str) -> tuple[bytes, bytes]:
    d = hkdf_sha256(IKM, SALT, (INFO_PREFIX + media_path).encode(), 44)
    return d[:32], d[32:44]


def decrypt(buf: bytes, media_path: str) -> bytes:
    key, nonce = derive(media_path)
    return ChaCha20.new(key=key, nonce=nonce).encrypt(buf)  # 流密码：encrypt 即 XOR


def sniff(buf: bytes) -> str:
    for magic, ext in MAGICS.items():
        if buf.startswith(magic):
            return ext
    if buf[:4] == b"RIFF":
        return "." + buf[8:12].decode("ascii", "replace").strip().lower()
    if buf[:3] in (b"\xff\xfb", b"\xff\xf3"):
        return ".mp3"
    if buf[:4] == b"ftyp":
        return ".mp4"
    return ""


def parse_spak(p: Path) -> dict[str, tuple[int, int]]:
    with p.open("rb") as fh:
        hdr = fh.read(12)
        if hdr[:4] != b"SPAK":
            raise ValueError(f"SPAK 魔数不对: {hdr[:4]!r}")
        ver, count = struct.unpack("<2I", hdr[4:12])
        idx = fh.read(count * 28)
        if len(idx) != count * 28:
            raise ValueError(f"SPAK 索引不完整: 要 {count*28}，读到 {len(idx)}")
    out: dict[str, tuple[int, int]] = {}
    for i in range(count):
        e = idx[i * 28:(i + 1) * 28]
        out[e[:16].decode("ascii")] = struct.unpack("<2I", e[16:24])
    return out


def collect_refs(scan_roots: list[Path]) -> set[str]:
    """收集路径引用。引号无关：Ink 文本里的路径是裸写的，不一定有引号。"""
    refs: set[str] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or "node_modules" in p.parts:
                continue
            # 注意：.map（source map）必须扫——里面的 sourcesContent 是压缩前源码，
            # 路径引用比压缩后的 bundle 全得多（实测 2026-10-25）
            if p.stat().st_size > 64 << 20:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.findall(rf"[\w./\-]+\.(?:{EXT_ALT})\b", text):
                refs.add(m.strip("./"))
    return refs


def atlas_pages(atlas_bytes: bytes, atlas_path: str) -> set[str]:
    """Spine .atlas 文本里的贴图页文件名（相对 atlas 所在目录）。"""
    pages: set[str] = set()
    base = "/".join(atlas_path.replace("\\", "/").split("/")[:-1])
    for line in atlas_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if re.fullmatch(rf"[\w./\-]+\.(?:{EXT_ALT})", line):
            pages.add(f"{base}/{line}" if base else line)
    return pages


def main() -> int:
    game_dir = Path(sys.argv[1])
    asar_root = Path(sys.argv[2])
    out_dir = Path(sys.argv[3])
    data_dir = game_dir / "data"

    individual = {f.stem: f for f in data_dir.iterdir()
                  if f.suffix == ".dat" and f.stem != PACK_NAME}
    packed = parse_spak(data_dir / f"{PACK_NAME}.dat")
    pack_data_start = 12 + len(packed) * 28
    print(f"data/: {len(individual)} 个独立 .dat + SPAK 包 {len(packed)} 条目")

    refs = collect_refs([asar_root])
    hash_to_path: dict[str, str] = {}
    for r in refs:
        h = hashlib.sha256(r.lstrip("/").encode()).hexdigest()[:16]
        hash_to_path.setdefault(h, r.lstrip("/"))
    print(f"文本引用: {len(refs)} 条 → 唯一 hash {len(hash_to_path)}")

    stats: dict[str, int] = {}
    fails: list[str] = []
    matched: set[str] = set()
    first = True

    def read_blob(h: str, path: str) -> bytes:
        if h in individual:
            return individual[h].read_bytes()
        off, ln = packed[h]
        with (data_dir / f"{PACK_NAME}.dat").open("rb") as fh:
            fh.seek(pack_data_start + off)
            return fh.read(ln)

    for round_no in (1, 2, 3):
        todo = [(h, p) for h, p in hash_to_path.items()
                if (h in individual or h in packed) and h not in matched]
        if not todo:
            break
        print(f"\n==== 第 {round_no} 轮：{len(todo)} 个待解 ====")
        new_atlas_refs: set[str] = set()
        for n, (h, path) in enumerate(sorted(todo), 1):
            try:
                plain = decrypt(read_blob(h, path), path)
                ext = Path(path).suffix.lower() or "." + (sniff(plain) or "bin").lstrip(".")
                if first and not sniff(plain):
                    print(f"[警告] 首个文件 {path} 解不出已知魔数，前 16 字节: {plain[:16].hex(' ')}")
                    first = False
                target = out_dir / f"Media_{ext.lstrip('.')}" / path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(plain)
                stats[ext] = stats.get(ext, 0) + 1
                matched.add(h)
                if ext == ".atlas":
                    new_atlas_refs |= atlas_pages(plain, path)
            except Exception as exc:
                fails.append(f"{path}: {type(exc).__name__}: {exc}")
            if n % 50 == 0 or n == len(todo):
                print(f"  [{n}/{len(todo)}] {dict(stats)}", flush=True)
        fresh = new_atlas_refs - refs
        if fresh:
            print(f"atlas 反哺: {len(fresh)} 条新路径")
            refs |= fresh
            for r in fresh:
                h = hashlib.sha256(r.lstrip("/").encode()).hexdigest()[:16]
                hash_to_path.setdefault(h, r.lstrip("/"))

    no_path = sorted((set(individual) | set(packed)) - matched)
    print("\n==== 汇总 ====")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k:<8} {v}")
    print(f"  合计     {sum(stats.values())} / {len(individual) + len(packed)}")
    print(f"  无路径   {len(no_path)}")
    if fails:
        print(f"  解密失败 {len(fails)}（前 5）:")
        for f in fails[:5]:
            print("    " + f)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_no_path_hashes.txt").write_text("\n".join(no_path), encoding="utf-8")
    print(f"\n无路径 hash 清单: {out_dir / '_no_path_hashes.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
