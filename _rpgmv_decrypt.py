#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPG Maker MV/MZ 资源解密器（自建，替代 RPGMakerDecrypter）。

原理（实测自 rpg_core.js `Decrypter.decryptArrayBuffer`，MV/MZ 同源）：
  加密文件 = 假头 16B ("RPGMV"/"RPGMZ" + VER + REMAIN)
           + 原[0:16] XOR key     <- 只有这 16 字节被加密
           + 原[16:]              <- 原样明文
  key 为 32 位 hex，来自 www/data/System.json 的 "encryptionKey"。

用法:
  python _rpgmv_decrypt.py <www_root> <out_root> [--key <32hex>] [--dry] [--manifest PATH]
  python _rpgmv_decrypt.py <game_root> <out_root>          # 自动找 www/ 或 www/data/System.json
  --manifest 不给就不写；给了则按 software-plan §2 契约落一份 manifest.json。

行为:
  *.rpgmvp -> *.png   *.rpgmvo -> *.ogg   *.rpgmvm -> *.m4a
  *.png_/.ogg_/.m4a_  -> 去尾下划线（MZ 命名风格）
  明文媒体（png/jpg/ogg/m4a/webm/mp4）原样复制
  非媒体（js/json/ttf/rpgsave...）跳过
  名字以「免责声明」开头的目录视为分发垃圾，整体跳过
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

MEDIA_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".webm", ".mp4"}
REN = {".rpgmvp": ".png", ".rpgmvo": ".ogg", ".rpgmvm": ".m4a",
       ".png_": ".png", ".ogg_": ".ogg", ".m4a_": ".m4a"}
JUNK_PREFIX = "免责声明"
SIGS = (b"RPGMV", b"RPGMZ")


def find_www(root: Path) -> Path:
    if (root / "data" / "System.json").exists():
        return root
    if (root / "www" / "data" / "System.json").exists():
        return root / "www"
    raise SystemExit(f"在 {root} 下找不到 www/（或 data/System.json）")


def load_key(www: Path, override: str | None) -> bytes:
    if override:
        h = override.strip()
    else:
        sj = www / "data" / "System.json"
        s = json.loads(sj.read_text(encoding="utf-8-sig"))
        h = s.get("encryptionKey") or ""
        if not h:
            raise SystemExit(f"System.json 无 encryptionKey（游戏可能未加密），或用 --key 提供")
    h = h.strip().strip('"')
    if len(h) != 32:
        raise SystemExit(f"encryptionKey 长度应为 32 hex，得到 {len(h)}: {h!r}")
    return bytes.fromhex(h)


def magic_ok(ext: str, b: bytes) -> bool:
    if ext == ".png":
        return b[:4] == b"\x89PNG"
    if ext == ".jpg":
        return b[:2] == b"\xff\xd8"
    if ext == ".ogg":
        return b[:4] == b"OggS"
    if ext == ".m4a":
        return b[4:8] == b"ftyp"
    return True  # webm/mp4 等交给验收工具


def write_manifest(out_root: Path, www: Path, key: bytes, stats: Counter,
                   magic_fails: list[str], path: Path, dry: bool) -> dict | None:
    """按 software-plan §2 契约写 manifest（raw/final/converted 三段式）。

    这个工具的转换是**内联**的：`.rpgmvp` 落盘时直接叫 `.png`，磁盘上从不存在中间格式，
    所以走 `manifest.counts_flat()`（raw == final，converted 为空）。
    转换明细写进 postprocess —— 那里才是「干了什么」该待的地方。

    地面真相 = 「本该写出的文件数」= decrypt + plain-copy。这两个计数是工具自己数的，
    不是猜的：每处理一个候选文件必然落在且只落在这两类之一（其余进 skip/*）。
    """
    import manifest as mf
    counts_block = mf.counts_flat(out_root)
    expected = stats["decrypt"] + stats["plain-copy"]
    per_ext = {k.split("/", 1)[1]: v for k, v in stats.items()
               if k.startswith("decrypt/") and "/" in k}
    post = [{"tool": "内联解密（假头 16B + 前 16B XOR key）",
             "detail": {"decrypt": stats["decrypt"], "plain_copy": stats["plain-copy"],
                        "by_target_ext": dict(sorted(per_ext.items()))}}]
    man = mf.build(
        tool="_rpgmv_decrypt.py",
        engine="RPG Maker",
        source={"www_root": str(www), "out_root": str(out_root),
                "encryption_key": key.hex(), "dry_run": dry},
        counts_block=counts_block,
        reconcile_block=mf.reconcile(None if dry else expected, counts_block["raw"]["total"]),
        verify={"verified": False,
                "note": "本工具只查魔数（magic_ok），不做内容级验收；"
                        "请用 orchestrator.py 或 _verify_media.py"},
        postprocess=post,
        extra={"magic_fail": magic_fails[:50], "magic_fail_count": len(magic_fails),
               "skipped": {k: v for k, v in stats.items() if k.startswith("skip/")}},
    )
    mf.write(path, man)
    return man


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    key_hex = sys.argv[sys.argv.index("--key") + 1] if "--key" in sys.argv else None
    man_path = Path(sys.argv[sys.argv.index("--manifest") + 1]) if "--manifest" in sys.argv else None
    if len(args) < 2:
        raise SystemExit(__doc__)
    www = find_www(Path(args[0]))
    out_root = Path(args[1])
    key = load_key(www, key_hex)
    print(f"www = {www}")
    print(f"out = {out_root}")
    print(f"key = {key.hex()}")

    stats = Counter()
    magic_fails: list[str] = []

    for p in sorted(www.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(www)
        if any(part.startswith(JUNK_PREFIX) for part in rel.parts):
            stats["skip/junk-disclaimer"] += 1
            continue
        if rel.parts[0] in ("icon", "save"):
            stats["skip/icon-save"] += 1
            continue
        ext = p.suffix.lower()
        if ext in REN:
            target_ext = REN[ext]
        elif ext in MEDIA_EXT:
            target_ext = ext
        else:
            stats[f"skip/nonmedia{ext or '-noext'}"] += 1
            continue

        data = p.read_bytes()
        if data[:5] in SIGS:  # 加密体：去假头 + 前 16B XOR key
            body = bytearray(data[16:])
            for i in range(16):
                if i < len(body):
                    body[i] ^= key[i]
            out = bytes(body)
            stats["decrypt"] += 1
            stats[f"decrypt/{target_ext}"] += 1
        else:  # 未加密（明文媒体，或假头不匹配）
            out = data
            stats["plain-copy"] += 1
            if ext in REN:
                stats["plain-renamed"] += 1
                print(f"  [明文但用加密后缀] {rel}")

        if not magic_ok(target_ext, out):
            magic_fails.append(f"{rel} -> {target_ext}: magic={out[:8].hex(' ')}")
            stats["magic-fail"] += 1

        dst = out_root / rel.with_suffix(target_ext)
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(out)

    print()
    print("=" * 60)
    print("decrypt :", stats["decrypt"])
    for k in sorted(stats):
        if k.startswith(("decrypt/", "plain", "skip/", "magic")):
            print(f"  {k:<28} {stats[k]}")
    if magic_fails:
        print(f"\n魔数异常 {len(magic_fails)} 个:")
        for m in magic_fails[:20]:
            print("  " + m)

    if man_path is not None:
        try:
            write_manifest(out_root, www, key, stats, magic_fails, man_path, dry)
            print(f"\nmanifest -> {man_path}")
        except Exception as exc:  # manifest 失败不该毁掉已落盘的产物
            print(f"\n[WARN] manifest 写入失败（产物不受影响）：{exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
