#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SPITE 缺失路径暴力枚举：用 asar 里的字符串 token 组合出候选媒体路径，
sha256[:16] 对撞 data/ 里还没匹配上的 .dat / SPAK 条目，命中即试解密验魔数。

背景（2026-10-25 实测）：_spite_decrypt.py 靠文本引用能对上 228/365，
剩下的资源路径是 JS 动态拼接（`"/audio/sfx/"+t+".ogg"` 之类），没有完整字面量。
本脚本按「目录 × 名字 × 扩展名」穷举组合补齐。

用法:
  python _spite_bruteforce_paths.py <游戏目录> <asar解包根目录> <输出目录>
"""
from __future__ import annotations

import hashlib
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _spite_decrypt import (PACK_NAME, decrypt, parse_spak, sniff,  # noqa: E402
                            collect_refs, atlas_pages)

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

MEDIA_EXTS = ("png", "webp", "jpg", "jpeg", "ogg", "mp3", "wav", "webm", "mp4",
              "skel", "atlas")

CURATED_DIRS = [
    "", "images/", "/images/", "ev/", "/ev/", "cg/", "/cg/", "bg/", "/bg/",
    "bgimage/", "scenes/", "/scenes/", "characters/", "audio/voice/",
    "/audio/voice/", "voice/", "spine/", "video/", "map/", "ui/", "sprites/",
    "hscenes/", "/hscenes/", "audio/", "/audio/", "story/", "data/",
]

TOKEN_RE = (
    r'"(?:[^"\\\n]|\\.)*"'      # "..."
    r"|'(?:[^'\\\n]|\\.)*'"     # '...'
    r"|`(?:[^`\\]|\\.)*`"       # `...`（含 ${} 的整段，后面再切）
)


def extract_tokens(asar_root: Path) -> set[str]:
    toks: set[str] = set()
    for p in asar_root.rglob("*"):
        if not p.is_file() or "node_modules" in p.parts:
            continue
        if p.suffix.lower() in (".png", ".jpg", ".webp", ".ico", ".woff", ".woff2",
                                ".ttf", ".otf", ".node", ".dll", ".exe", ".pak",
                                ".bin", ".dat", ".svg"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.findall(TOKEN_RE, text):
            body = m[1:-1]
            # 模板字符串按 ${...} 切开，静态段都算候选
            for part in re.split(r"\$\{[^}]*\}", body):
                if 0 < len(part) <= 120:
                    toks.add(part)
                    if "\\u" in part or "\\x" in part:
                        try:
                            toks.add(part.encode("ascii").decode("unicode_escape"))
                        except Exception:
                            pass
    return toks


def main() -> int:
    game_dir = Path(sys.argv[1])
    asar_root = Path(sys.argv[2])
    out_dir = Path(sys.argv[3])
    data_dir = game_dir / "data"

    individual = {f.stem: f for f in data_dir.iterdir()
                  if f.suffix == ".dat" and f.stem != PACK_NAME}
    packed = parse_spak(data_dir / f"{PACK_NAME}.dat")
    known = (set(individual) | set(packed))

    # 已匹配的（复用主脚本逻辑，简单重算）
    refs = collect_refs([asar_root])
    matched: set[str] = set()
    hash_to_path: dict[str, str] = {}
    for r in refs:
        h = hashlib.sha256(r.lstrip("/").encode()).hexdigest()[:16]
        hash_to_path.setdefault(h, r.lstrip("/"))
    for h, p in hash_to_path.items():
        if h in known:
            matched.add(h)
    # 已解出 atlas 的反哺
    for atlas_file in (out_dir / "Media_atlas").rglob("*.atlas") if (out_dir / "Media_atlas").exists() else []:
        rel = str(atlas_file.relative_to(out_dir / "Media_atlas")).replace("\\", "/")
        for page in atlas_pages(atlas_file.read_bytes(), rel):
            h = hashlib.sha256(page.lstrip("/").encode()).hexdigest()[:16]
            hash_to_path.setdefault(h, page.lstrip("/"))
            if h in known:
                matched.add(h)

    missing = known - matched
    print(f"缺失 hash: {len(missing)}（独立 {len(set(individual) & missing)} / 包内 {len(set(packed) & missing)}）")

    toks = extract_tokens(asar_root)
    print(f"asar 字符串 token: {len(toks)}")
    names = [t for t in toks if "/" not in t and "." not in t and 1 <= len(t) <= 60]
    dirs = sorted({t for t in toks if t.endswith("/") and len(t) <= 60} | set(CURATED_DIRS))
    dirs = [d.replace("\\", "/").lstrip("/").lstrip("./") for d in dirs]
    dirs = sorted({d for d in dirs if not d.startswith("..")})
    print(f"名字候选 {len(names)} × 目录候选 {len(dirs)} × 扩展名 {len(MEDIA_EXTS)}")

    found: dict[str, str] = {}

    def check(cand: str) -> bool:
        h = hashlib.sha256(cand.encode()).hexdigest()[:16]
        if h in missing and h not in found:
            found[h] = cand
            return True
        return False

    # Pass A：token 本体 / 去前导斜杠 / +扩展名
    for t in toks:
        for base in (t, t.lstrip("/").lstrip("./")):
            check(base)
            if "." not in base:
                for e in MEDIA_EXTS:
                    check(f"{base}.{e}")
    print(f"Pass A（token 及 +扩展名）命中: {len(found)}")

    # Pass B：目录 × 名字 × 扩展名
    budget = len(dirs) * len(names) * len(MEDIA_EXTS)
    print(f"Pass B 组合数: {budget:,}")
    if budget > 400_000_000:
        print("[中止] 组合数超预算，先缩小区集")
        return 2
    for d in dirs:
        for nm in names:
            base = d + nm
            for e in MEDIA_EXTS:
                check(f"{base}.{e}")
    print(f"Pass B 后累计命中: {len(found)}")

    # Pass C：角色级二级路径（characters/ev/images/audio/voice/<char>/<name>.<ext>）
    chars = {"apus", "bonnie", "cherin", "helena", "jinny", "julienne", "sia", "zmm",
             "mc", "player"}
    bases2 = ["characters/", "ev/", "images/", "audio/voice/", "voice/", "scenes/",
              "hscenes/", "sprites/", "cg/", "audio/sfx/"]
    exts2 = ("webp", "png", "jpg", "ogg", "mp4", "skel", "atlas")
    print(f"Pass C 组合数: {len(bases2) * len(chars) * len(names) * len(exts2):,}")
    for b in bases2:
        for c in chars:
            base = b + c + "/"
            for nm in names:
                cand = base + nm
                for e in exts2:
                    check(f"{cand}.{e}")
    print(f"Pass C 后累计命中: {len(found)}")

    # Pass D：角色名前缀/后缀组合 + 数字编号 + ui_sfx 目录补漏
    for c in chars:
        for nm in names:
            for stem in (f"{c}_{nm}", f"{nm}_{c}"):
                for e in MEDIA_EXTS:
                    check(f"characters/{c}/{stem}.{e}")
        for n in range(1000):
            for stem in (f"{c}_{n}", str(n)):
                check(f"audio/voice/{c}/{stem}.ogg")
    for n in range(10000):
        check(f"audio/voice/{n}.ogg")
        check(f"audio/ui_sfx/{n}.ogg")
    for nm in names:
        check(f"audio/ui_sfx/{nm}.ogg")
        check(f"audio/ui_sfx/{nm}.wav")
    print(f"Pass D 后累计命中: {len(found)}")

    if not found:
        print("没有新命中。")
        return 1

    # 命中的试解密验魔数
    pack_start = 12 + len(packed) * 28
    ok = bad = 0
    results: list[str] = []
    for h, path in sorted(found.items(), key=lambda x: x[1]):
        try:
            if h in individual:
                buf = individual[h].read_bytes()
            else:
                off, ln = packed[h]
                with (data_dir / f"{PACK_NAME}.dat").open("rb") as fh:
                    fh.seek(pack_start + off)
                    buf = fh.read(ln)
            plain = decrypt(buf, path)
            magic = sniff(plain[:16]) or ("(skel?)" if path.endswith(".skel") else "?")
            if magic not in ("?", "(skel?)"):
                ok += 1
            else:
                bad += 1
            results.append(f"{h}  {magic:<10} {path}")
            ext = Path(path).suffix.lower()
            target = out_dir / f"Media_{ext.lstrip('.')}" / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(plain)
        except Exception as exc:
            bad += 1
            results.append(f"{h}  ERROR      {path}  ({exc})")
    print(f"\n试解密: 魔数正常 {ok}，异常/无魔数 {bad}")
    report = out_dir / "_bruteforce_hits.txt"
    report.write_text("\n".join(results), encoding="utf-8")
    print(f"命中清单: {report}")
    still = missing - set(found)
    (out_dir / "_no_path_hashes.txt").write_text("\n".join(sorted(still)), encoding="utf-8")
    print(f"仍缺路径: {len(still)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
