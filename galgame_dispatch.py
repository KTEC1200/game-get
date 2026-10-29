#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
galgame 解包分派器 —— dry-run 版

只判定、只给建议，**不修改、不移动、不删除任何文件**。

用法：
    python galgame_dispatch.py "D:\\Games\\某游戏"
    python galgame_dispatch.py "D:\\Games" --depth 3        # 批量扫描子目录
    python galgame_dispatch.py "D:\\Games" --json out.json  # 额外导出 JSON

判定规则来自 galgame-unpack-decision-tree.md（即用户自己的解包教程）。
评分借鉴 shushui0710/STool 的「证据打分 + 阈值」思路，阈值同样取 60。
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Windows 控制台默认是 GBK 代码页，直接打印中文以外的字符会抛 UnicodeEncodeError。
# 统一切到 UTF-8 代码页，并给输出流加 errors="replace" 兜底。
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

# --------------------------------------------------------------------------
# 魔数（用于校验扩展名是否名副其实）
# --------------------------------------------------------------------------
MAGIC_XP3 = b"XP3\r\n \n\x1a\x8bg\x01"          # KiriKiri xp3
MAGIC_RPA_PREFIX = b"RPA-"                        # Ren'Py RPA-3.0 / RPA-2.0
MAGIC_UNITYFS = b"UnityFS"                        # Unity AssetBundle

# Unity 版本号可从 globalgamemanagers / level0 的串行化文件头里直接读到
UNITY_VER_RE = re.compile(rb"\d+\.\d+\.\d+[a-z]\d+")

THRESHOLD = 60  # 判定阈值


def find_unity_version(data_dir: Path) -> str | None:
    """从 Unity 数据目录读出引擎版本（决定该用 AssetStudio 还是 AssetStudioNext）。"""
    for name in ("globalgamemanagers", "level0"):
        p = data_dir / name
        if p.is_file():
            m = UNITY_VER_RE.search(read_head(p, 4096))
            if m:
                return m.group().decode("ascii", "replace")
    return None


def biggest_files(directory: Path, limit: int = 5) -> list[tuple[float, str]]:
    """列出目录中最大的文件（MB, 名称）——用来指出资源实际落在哪里。"""
    out: list[tuple[float, str]] = []
    try:
        for p in directory.iterdir():
            if p.is_file():
                out.append((p.stat().st_size / 1024 / 1024, p.name))
    except OSError:
        return []
    out.sort(reverse=True)
    return out[:limit]


def demojibake(name: str) -> str | None:
    """还原「Shift-JIS 文件名被按 GBK 解读」的经典乱码。

    例：`僼傽僀儖攋懝僠僃僢僋僣乕儖.exe` → `ファイル破損チェックツール.exe`
    判据：把名字按 GBK 编码回字节、再按 Shift-JIS 解码；若结果含假名，则认定是乱码。
    """
    stem, dot, ext = name.rpartition(".")
    if not stem:
        stem, dot, ext = name, "", ""
    try:
        fixed = stem.encode("gbk").decode("shift_jis")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if not fixed or fixed == stem:
        return None
    if not any("\u3040" <= c <= "\u30ff" for c in fixed):  # 必须有假名
        return None
    return fixed + (dot + ext if dot else "")


def count_subdir_games(game_dir: Path, sub_dirs: list[str]) -> list[str]:
    """找出「本身或其下两层像游戏」的直接子目录——用来识别这个目录其实是游戏集合。

    往下一层找是必要的：有些游戏把本体放在 `7/` 之类的子目录里，只看直接子项会漏。
    """
    def has_game_signature(d: Path, depth: int = 2) -> bool:
        try:
            entries = list(d.iterdir())
        except OSError:
            return False
        for e in entries:
            if e.is_file() and e.suffix.lower() in (".xp3", ".rpa", ".asar"):
                return True
            if e.is_dir() and e.name.endswith("_Data"):
                return True
        if depth > 0:
            for e in entries:
                if e.is_dir() and has_game_signature(e, depth - 1):
                    return True
        return False

    return [name for name in sub_dirs if has_game_signature(game_dir / name)]


# 归档内是否有「明文内容」——用 UTF-16LE 形式的扩展名标记来判断。
# 原理：KiriKiri 脚本(.ks/.tjs)是纯文本，文件名在索引里也是 UTF-16LE。
# 全程搜不到任何标记 => 包内容被加密或整体压缩 => GARbro 静态提取基本会失败。
PLAINTEXT_EXTS = ("ks", "tjs", "png", "jpg", "ogg", "wav", "opus", "mp3", "mp4",
                  "tlg", "pimg", "psb", "dat", "txt", "csv", "webm", "wmv", "mpg")
_CHUNK = 8 * 1024 * 1024


def probe_archive(path: Path) -> Counter:
    """[已废弃，保留仅为兼容] 全文件搜 UTF-16LE 扩展名标记。

    ⚠️ 经实测证伪：本判据**不能**预测 GARbro 能否解包，且两个方向都会出错——
      * 判「明文」的高慢妻陥落！！(1159 标记)  -> GARbro 实际 unknown format
      * 判「已加密」的温泉蒸汽人妻 (0 标记)    -> GARbro 实际读出 3425 个条目
    根因：它测的是「文件里有没有 UTF-16LE 日文文本」，与「索引能否解析」无关。
    请改用 garbro_probe()——直接调用 GARbro.Console 拿地面真相，不要预测。
    """
    pats = {e: ("." + e).encode("utf-16-le") for e in PLAINTEXT_EXTS}
    counter: Counter = Counter()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(_CHUNK)
            if not buf:
                break
            for ext, pat in pats.items():
                start = 0
                while True:
                    i = buf.find(pat, start)
                    if i < 0:
                        break
                    counter[ext] += 1
                    start = i + 2
    return counter


def garbro_probe(archive: Path, garbro_exe: str, timeout: int = 600) -> tuple[str, int]:
    """直接调用 GARbro.Console 获取地面真相。返回 (结论, 条目数)。

    这是唯一可靠的判据：与其猜，不如问。GARbro 认不出来就是认不出来。
    """
    import subprocess
    try:
        r = subprocess.run([garbro_exe, str(archive)],
                           capture_output=True, timeout=timeout)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return f"GARbro 超时（>{timeout}s）", 0
    except Exception as exc:
        return f"GARbro 调用失败: {type(exc).__name__}", 0

    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return "GARbro 无输出", 0
    if "unknown format" in lines[0].lower():
        return "GARbro 无法识别", 0
    return "GARbro 可识别", max(0, len(lines) - 1)

# KiriKiri 包名 → 内容（用于校验产物完整性）
KRKR_PACKS = {
    "data.xp3": "游戏主数据",
    "event.xp3": "事件 CG",
    "evimage.xp3": "事件 CG",
    "fgimage.xp3": "人物立绘",
    "bgimage.xp3": "背景图片",
    "scenario.xp3": "游戏脚本",
    "voice.xp3": "语音",
    "sound.xp3": "音效",
    "bgm.xp3": "背景音乐",
    "system.xp3": "系统界面",
    "patch.xp3": "游戏补丁",
    "adult.xp3": "R18 内容",
}


@dataclass
class Signal:
    """一条证据。"""
    engine: str
    weight: int
    detail: str


@dataclass
class Guess:
    engine: str
    score: int = 0
    evidence: list[str] = field(default_factory=list)


@dataclass
class Report:
    path: Path
    guesses: list[Guess] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    facts: dict[str, object] = field(default_factory=dict)

    @property
    def best(self) -> Guess | None:
        return self.guesses[0] if self.guesses else None


def read_head(p: Path, n: int = 16) -> bytes:
    try:
        with p.open("rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def scan(game_dir: Path, max_files: int = 200_000, deep: bool = False,
         garbro_exe: str | None = None) -> Report:
    """扫描一个游戏目录，返回判定报告。只读。"""
    rep = Report(path=game_dir)
    g: dict[str, Guess] = {}

    def hit(engine: str, weight: int, detail: str) -> None:
        cur = g.setdefault(engine, Guess(engine))
        cur.score += weight
        cur.evidence.append(f"+{weight} {detail}")

    xp3_files: list[Path] = []
    rpa_files: list[Path] = []
    asar_files: list[Path] = []
    bundle_files: list[Path] = []
    seen = 0

    # 顶层目录名先判，命中时可提前收敛
    try:
        top_dirs = [d.name for d in game_dir.iterdir() if d.is_dir()]
    except OSError as exc:
        rep.notes.append(f"无法读取目录：{exc}")
        return rep

    # ---- Unity ----
    data_dirs = [d for d in top_dirs if d.endswith("_Data")]
    for d in data_dirs:
        hit("Unity", 60, f"存在 `{d}/`（Unity 标志性目录）")
        dd = game_dir / d
        if (dd / "StreamingAssets" / "aa").is_dir():
            hit("Unity", 25, f"`{d}/StreamingAssets/aa/` 存在（Addressables 资源包目录）")
        if (dd / "il2cpp_data").is_dir():
            hit("Unity", 15, f"`{d}/il2cpp_data/` 存在 → IL2CPP")
        if (dd / "Managed").is_dir():
            hit("Unity", 10, f"`{d}/Managed/` 存在")
        if (dd / "globalgamemanagers").exists():
            hit("Unity", 10, f"`{d}/globalgamemanagers` 存在")

        # --- 记录决定工具选型的实测事实 ---
        if "unity_data_dir" not in rep.facts:
            rep.facts["unity_data_dir"] = str(dd)
            ver = find_unity_version(dd)
            if ver:
                rep.facts["unity_version"] = ver
            rep.facts["unity_il2cpp"] = (dd / "il2cpp_data").is_dir() or \
                (game_dir / "GameAssembly.dll").exists()
            rep.facts["unity_streaming_assets"] = (dd / "StreamingAssets").is_dir()
            rep.facts["unity_big_files"] = [
                f"{mb:.1f} MB  {n}" for mb, n in biggest_files(dd, 6) if mb >= 1.0
            ]

    if (game_dir / "GameAssembly.dll").exists():
        hit("Unity", 15, "`GameAssembly.dll` 存在（IL2CPP 特征）")

    # ---- 遍历（有上限，避免扫爆） ----
    mojibake: list[tuple[str, str]] = []
    for p in game_dir.rglob("*"):
        seen += 1
        if seen > max_files:
            rep.notes.append(f"文件数超过 {max_files}，已提前停止扫描")
            break
        if not p.is_file():
            continue
        name = p.name
        lower = name.lower()

        if len(mojibake) < 200:
            fixed = demojibake(name)
            if fixed:
                mojibake.append((name, fixed))

        if lower.endswith(".xp3"):
            xp3_files.append(p)
        elif lower.endswith(".rpa"):
            rpa_files.append(p)
        elif lower.endswith(".asar"):
            asar_files.append(p)
        elif lower.endswith(".bundle"):
            bundle_files.append(p)

    # ---- 这个目录其实是「游戏集合」而不是单个游戏？ ----
    sub_games = count_subdir_games(game_dir, top_dirs)
    if len(sub_games) >= 2 and (xp3_files or data_dirs):
        rep.facts["is_collection"] = True
        shown = "、".join(sub_games[:5]) + ("…" if len(sub_games) > 5 else "")
        rep.notes.append(
            f"[注意] 本目录下有 {len(sub_games)} 个子目录各自是独立游戏（{shown}）"
            f" → 这是**游戏集合目录**，不是单个游戏。上面这些 xp3 来自不同子目录，"
            f"请改为对每个子目录分别运行本工具，否则计数会虚高。"
        )

    if mojibake:
        rep.facts["mojibake_count"] = len(mojibake)
        sample = "；".join(f"`{a}` → `{b}`" for a, b in mojibake[:5])
        rep.notes.append(
            f"[注意] 发现 {len(mojibake)} 个**乱码文件名**（Shift-JIS 名被按 GBK 解读）：{sample}"
            f" → 这类名字会让 FFmpeg concat 报 `Invalid argument`，"
            f"正是你教程里那条「另存为 UTF-8」的坑；建议先批量改名再处理音频。"
        )

    # ---- KiriKiri ----
    if xp3_files:
        hit("KiriKiri", 70, f"发现 {len(xp3_files)} 个 `.xp3` 文件")
        known = [f for f in xp3_files if f.name.lower() in KRKR_PACKS]
        if known:
            hit("KiriKiri", 20, f"其中 {len(known)} 个是已知包名（data/event/bgimage…）")

        # 魔数校验：扩展名是 .xp3 但头不对 → 高度可疑（封包头被改）
        for f in xp3_files[:40]:
            head = read_head(f, len(MAGIC_XP3))
            if head and head != MAGIC_XP3:
                rep.notes.append(
                    f"[警告] `{f.name}` 扩展名是 .xp3 但头部不是标准 XP3 魔数"
                    f"（实际 {head[:8].hex(' ')}）→ 可能封包头被修改，"
                    f"对应 KrkrExtract 报 `Unknown chunk in root chunk` 的场景，预案：直接用 KrkrzExtract"
                )
                break

        # ---- GARbro 实调：不再猜测，直接问工具拿地面真相 ----
        # 早先的 --deep「明文/加密」启发式已证伪（两个方向都错），故改为实调。
        if garbro_exe:
            cands = sorted(xp3_files, key=lambda f: f.stat().st_size, reverse=True)[:6]
            probes = []
            for f in cands:
                verdict, n = garbro_probe(f, garbro_exe)
                try:
                    rel = str(f.relative_to(game_dir))
                except ValueError:
                    rel = f.name
                probes.append({
                    "path": rel,
                    "mb": round(f.stat().st_size / 1024 / 1024, 1),
                    "verdict": verdict,
                    "entries": n,
                })
            rep.facts["garbro_probes"] = probes
            ok = sum(1 for p in probes if p["entries"] > 0)
            rep.facts["garbro_ok"] = ok
            rep.facts["garbro_total"] = len(probes)

    # ---- Ren'Py ----
    if rpa_files:
        hit("Ren'Py", 70, f"发现 {len(rpa_files)} 个 `.rpa` 文件")
        for f in rpa_files[:20]:
            head = read_head(f, 8)
            if head and not head.startswith(MAGIC_RPA_PREFIX):
                rep.notes.append(f"[警告] `{f.name}` 头部不是 RPA- 前缀（实际 {head[:8]!r}）")
                break
    if "renpy" in [d.lower() for d in top_dirs]:
        hit("Ren'Py", 20, "存在 `renpy/` 目录")
    if any(p.suffix.lower() in (".rpy", ".rpyc") for p in game_dir.rglob("*") if p.is_file()):
        hit("Ren'Py", 10, "存在 `.rpy` / `.rpyc` 脚本")

    # ---- Tyrano / Electron ----
    if asar_files:
        hit("Tyrano/Electron", 60, f"发现 {len(asar_files)} 个 `.asar` 文件")
        if any(f.name.lower() == "app.asar" for f in asar_files):
            hit("Tyrano/Electron", 30, "其中含 `app.asar`（Electron 典型结构）")
    if any(d.lower() == "tyrano" for d in top_dirs):
        hit("Tyrano/Electron", 25, "存在 `tyrano/` 目录（TyranoScript 特征）")

    # ---- Unity bundle 补充 ----
    if bundle_files:
        hit("Unity", 20, f"发现 {len(bundle_files)} 个 `.bundle` 文件")
        for f in bundle_files[:20]:
            if read_head(f, 7) == MAGIC_UNITYFS:
                hit("Unity", 10, "`.bundle` 头部为 `UnityFS`（已确认）")
                break

    rep.guesses = sorted(g.values(), key=lambda x: -x.score)
    return rep


# --------------------------------------------------------------------------
# 建议（引擎 → 工具链 + 失败预案）
# --------------------------------------------------------------------------
ADVICE: dict[str, dict[str, object]] = {
    "Unity": {
        "tool": "AssetStudio（`File / Load folder` 导入 `*_Data` 目录，可勾选 Enable Advanced Search）",
        "fallback": [
            "报 `EndOfStreamException` 或 Shader 解析失败 → Unity 6000 改了 Shader 序列化 → 改用 AssetStudioNext",
            "若存在 `il2cpp_data/` 或 `GameAssembly.dll` → 先跑 Il2CppDumper（`GameAssembly.dll` + `il2cpp_data/global-metadata.dat`）",
            "报 `Metadata file supplied is not valid metadata file.` → metadata 已加密/混淆，需人工",
            "AssetStudio 解析不了 → 换 AssetRipper",
        ],
        "output": "按 Type 筛选需要的东西（Texture2D 图片 / AudioClip 音频 / VideoClip 视频 / Sprite），再 Export",
    },
    "KiriKiri": {
        "tool": "先用 GARbro-Mod 静态提取（左侧粘贴游戏根目录 → 找体积较大的 .xp3 → 右键 Extract）",
        "fallback": [
            "GARbro 报「无法识别的格式」/「密码错误」/ 导出音频无法播放 → 判定已加密 → 转动态提取",
            "动态提取前提：游戏能正常运行；只能用模拟器启动则回退 GARbro",
            "Steam 版 → Steam 会阻止注入 → 先用 Steamless 脱壳",
            "KrkrExtract 报红字 `Unknown chunk in root chunk : ...` → 封包头被改 → 改用 KrkrzExtract",
            "较新的 .xp3 → 试 KrkrDump 或 krkrzCxdec",
        ],
        "output": "按包名判断内容（见决策树的文件名对照表），用于校验产物是否完整",
    },
    "Ren'Py": {
        "tool": "RPA-Explorer（load file → 解包；也能改/建 rpa、预览编译后的 rpy）",
        "fallback": ["RPA-Explorer 不行 → 试较新的 rpaextract"],
        "output": "rpa 内通常含 images / audio / video 与脚本",
    },
    "Tyrano/Electron": {
        "tool": "AsarKit（安装无依赖）",
        "fallback": ["AsarKit 不行 → 试 WinASAR"],
        "output": "asar 内为完整应用目录，资源通常在 resources/ 或 tyrano/ 下",
    },
}

POST_PROCESS = [
    "`.tlg` → tlg2png（`for %i in (\"路径\\*.tlg\") do tlg2png \"%i\" \"输出\\%~ni.png\"`）",
    "`.pimg` / `.psb` → 先 FreeMote `PsbDecompile.exe`，再用 krkrFgiEditor 合成图层",
    "散碎 `.ogg` 语音 → FFmpeg concat（mylist.txt 若报 Invalid argument，另存为 UTF-8）",
]


def unity_extra(rep: Report) -> tuple[list[str], list[str]]:
    """Unity 专属：报告实测事实，并按事实**裁剪**失败预案（避免列一堆不适用的情况）。"""
    facts = rep.facts
    extra: list[str] = []
    fallback = list(ADVICE["Unity"]["fallback"])  # type: ignore[arg-type]

    ver = facts.get("unity_version")
    if ver:
        extra.append(f"Unity 版本：**{ver}**（读自 globalgamemanagers）")
        if str(ver).startswith(("6000.", "6.")):
            extra.append("  → 属 Unity 6000 系，Shader 序列化已变更，**优先直接上 AssetStudioNext**")
        else:
            extra.append("  → 非 Unity 6000，**AssetStudio 原版即可**")
            fallback = [f for f in fallback if "AssetStudioNext" not in f]

    il2cpp = facts.get("unity_il2cpp")
    if il2cpp is True:
        extra.append("脚本后端：**IL2CPP** → 需先跑 Il2CppDumper")
    elif il2cpp is False:
        extra.append("脚本后端：**Mono** → 无需 Il2CppDumper")
        fallback = [f for f in fallback if "Il2CppDumper" not in f and "Metadata file" not in f]

    if facts.get("unity_streaming_assets") is False:
        extra.append("无 `StreamingAssets/` → 没有 Addressables 资源包，资源在 `.assets` / `.resS` 里，"
                     "**务必勾选 Enable Advanced Search**")
    if facts.get("unity_big_files"):
        extra.append("资源主体（按体积）：")
        for bf in facts["unity_big_files"]:  # type: ignore[union-attr]
            extra.append(f"    {bf}")
        extra.append("  → `.resS` 一般是贴图/音频的流式数据，体积最大的就是你要找的")
    if facts.get("unity_data_dir"):
        extra.append(f"导入路径：AssetStudio 的 **Load folder 选** `{facts['unity_data_dir']}`（不是游戏根目录）")
    return extra, fallback


def render(rep: Report, show_advice: bool = True) -> str:
    out: list[str] = []
    out.append(f"\n{'=' * 68}")
    out.append(f"游戏目录：{rep.path}")
    out.append("=" * 68)

    if not rep.guesses:
        out.append("判定：[未命中] 无可识别特征 —— 未命中任何已知规则")
        out.append("建议：先用 GARbro-Mod 打开，看它能否识别；不行再走「杀手锏」社区检索")
    else:
        best = rep.best
        assert best is not None
        verdict = "[判定]" if best.score >= THRESHOLD else "[推测，未达阈值]"
        out.append(f"判定：{verdict} → **{best.engine}**（得分 {best.score}，阈值 {THRESHOLD}）")
        out.append("")
        out.append("证据：")
        for e in best.evidence:
            out.append(f"  {e}")
        others = [x for x in rep.guesses[1:] if x.score >= THRESHOLD]
        if others:
            out.append("")
            out.append("其它同时达阈值的候选（需人工确认）：")
            for o in others:
                out.append(f"  - {o.engine}（{o.score}）")

        extra: list[str] = []
        fallback: list[str] = []
        if best.engine == "Unity":
            extra, fallback = unity_extra(rep)
            if extra:
                out.append("")
                out.append("实测事实（已据此裁剪预案）：")
                for e in extra:
                    out.append(f"  {e}")

        probes = rep.facts.get("garbro_probes")
        if probes:
            out.append("")
            ok = rep.facts.get("garbro_ok")
            total = rep.facts.get("garbro_total")
            out.append(f"GARbro.Console 实调结果（{ok}/{total} 个可识别）：")
            for p in probes:  # type: ignore[union-attr]
                if p["entries"]:
                    out.append(f"  [可识别] {p['path']}  ({p['mb']} MB) -> {p['entries']} 个条目")
                else:
                    out.append(f"  [读不出] {p['path']}  ({p['mb']} MB) -> {p['verdict']}")
            if ok == total:
                out.append("  -> 全部可被 GARbro.Console 识别，可直接提取")
            else:
                out.append(f"  -> {total - ok}/{total} 个 Console 读不出")
                out.append("  [警告] GARbro.Console 相对 GARbro.GUI 存在【假阴性】：实测 GUI "
                           "能正常提取的游戏，Console 却报 `unknown format`（列表与 -x 均失败）。")
                out.append("     => 【读不出】不能证明静态路线不通，请先用 GARbro.GUI 复核；"
                           "只有 GUI 也失败才走动态提取（KrkrExtract / KrkrzExtract）。")

        if show_advice and best.engine in ADVICE:
            a = ADVICE[best.engine]
            if not fallback:
                fallback = list(a["fallback"])  # type: ignore[arg-type]
            out.append("")
            out.append(f"建议工具：{a['tool']}")
            if fallback:
                out.append("仍适用的失败预案：" if best.engine == "Unity" else "失败预案：")
                for f in fallback:
                    out.append(f"  - {f}")
            out.append(f"预期产物：{a['output']}")

    if rep.notes:
        out.append("")
        out.append("注意：")
        for n in rep.notes:
            out.append(f"  {n}")

    if show_advice:
        out.append("")
        out.append("解包后的后处理（解包成功 ≠ 拿到可用文件）：")
        for p in POST_PROCESS:
            out.append(f"  - {p}")

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="galgame 解包分派器（dry-run，只读）")
    ap.add_argument("paths", nargs="+", help="游戏目录，或包含多个游戏的根目录")
    ap.add_argument("--depth", type=int, default=0,
                    help=">0 时递归查找子目录中的游戏（扫描根目录用），默认 0")
    ap.add_argument("--json", metavar="FILE", help="额外导出 JSON 报告")
    ap.add_argument("--no-advice", action="store_true", help="只输出判定，不输出建议")
    ap.add_argument("--garbro", metavar="EXE",
                    help="GARbro.Console.exe 的路径。给出后对 xp3 逐个实调 GARbro。"
                         "注意：Console 相对 GUI 存在假阴性（GUI 能解的它可能报 unknown format），"
                         "故只能把「可识别」当正面证据，「读不出」须用 GUI 复核。")
    ap.add_argument("--deep", action="store_true",
                    help="[已废弃] 旧的全文件猜测式探测；结果不可靠，请改用 --garbro")
    args = ap.parse_args(argv)

    targets: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if not p.is_dir():
            print(f"[跳过] 不是目录：{p}", file=sys.stderr)
            continue
        targets.append(p)
        if args.depth > 0:
            base_depth = len(p.parts)
            for sub in p.rglob("*"):
                if sub.is_dir() and len(sub.parts) - base_depth == args.depth:
                    targets.append(sub)

    if not targets:
        print("没有可扫描的目录。", file=sys.stderr)
        return 2

    payload = []
    for t in targets:
        rep = scan(t, deep=args.deep, garbro_exe=args.garbro)
        print(render(rep, show_advice=not args.no_advice))
        payload.append({
            "path": str(rep.path),
            "best": rep.best.engine if rep.best else None,
            "score": rep.best.score if rep.best else 0,
            "guesses": [{"engine": x.engine, "score": x.score, "evidence": x.evidence}
                        for x in rep.guesses],
            "facts": rep.facts,
            "notes": rep.notes,
        })

    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写入：{args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
