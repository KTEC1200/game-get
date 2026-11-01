#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取计划生成器：把 dispatch 的判定结果翻译成「该跑哪个工具 + 具体命令行」。

为什么单独一个模块
------------------
`galgame_dispatch.py` 的职责是**判定**（这个游戏是什么引擎），本模块的职责是
**分派**（下一步该敲什么命令）。两件事的生命周期不同：判定要稳定到能进 golden
基线逐字比对，分派则会随着工具增多、参数改名而频繁变动。混在一个文件里，
每次改个参数名都要重刷 golden。

三条硬规矩
----------
1. **只写「怎么跑」，不写「跑不跑得通」**。计划里的 `implemented` 字段只表示
   `orchestrator.py` 有没有接这条链（那是代码事实，可查）；至于这个具体游戏
   能不能解出来，一律由实跑决定——坑 2：别静态预测能否解包。
2. **参数只从实测事实拼**。归档路径取自 `Report.archives`（真遍历出来的文件），
   绝不靠「猜包名」或「猜哪个是加密的」。
3. **`argv` 是列表，不是字符串**。含空格的路径（`Swipe Right for Sugar Mama Sensei`）
   用 shell 字符串拼必然出错——AGENTS.md 里已经栽过一次
   （`Start-Process -ArgumentList` 把路径拆碎）。`cmdline` 只用于人眼复制，
   带引号，不参与执行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Plan:
    """一个可执行的提取计划。

    `argv` 是**列表**（交给 subprocess，不经 shell）；`cmdline` 是给人看的带引号
    字符串。两者同源生成，但执行只用 `argv`。
    """

    engine: str
    extractor: str
    argv: list[str] = field(default_factory=list)
    kind: str = "whole_dir"          # whole_dir / per_archive / orchestrator
    implemented: bool = False        # orchestrator.py 是否已接这条链
    reason: str = ""
    notes: list[str] = field(default_factory=list)
    extras: list["Plan"] = field(default_factory=list)  # 同引擎的补充步骤（如 .pna carve）

    @property
    def cmdline(self) -> str:
        return " ".join(_q(a) for a in self.argv)

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "extractor": self.extractor,
            "kind": self.kind,
            "implemented": self.implemented,
            "argv": list(self.argv),
            "cmdline": self.cmdline,
            "reason": self.reason,
            "notes": list(self.notes),
            "extras": [e.as_dict() for e in self.extras],
        }


def _q(s: str) -> str:
    """给人看的引号包装。执行一律走 argv 列表，这里只为复制粘贴方便。"""
    return f'"{s}"' if (" " in s or "\t" in s) else s


def _out_dir(game_dir: Path, name: str | None = None) -> Path:
    """默认输出目录：`<项目>/_extracted/<游戏目录名>`。

    按 AGENTS.md 的约定，产物一律落在项目的 `_extracted/` 下（该目录已在
    .gitignore 里），**不写进游戏目录**——把解包产物倒进游戏目录会污染原包，
    加密 KiriKiri 那条链还要 stage 出纯 ASCII 副本，混在一起排查时很难分清
    哪个文件是谁产生的。
    """
    return _repo_root() / "_extracted" / (name or game_dir.name or "out")


def _py(tool: str) -> list[str]:
    """Python 工具的调用前缀。用 `sys.executable` 而不是裸 `python`——
    用户机器上 `python` 可能指向 3.8 或 Microsoft Store 的假 python。"""
    import sys

    return [sys.executable, str(_repo_root() / tool)]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# 各引擎的提取器定义
# --------------------------------------------------------------------------
# kind:
#   orchestrator —— 直接跑 orchestrator.py（detect→extract→postprocess→verify→manifest）
#   per_archive  —— 每个归档跑一次工具
#   whole_dir    —— 整个目录跑一次工具
#
# 这里的每一项都必须对应**真实存在的工具与真实存在的参数**（2026-10-30 逐个核过
# `--help`/docstring/源码）。凭想象写参数等于给用户一条必然失败的命令。

IMPLEMENTED_CHAINS = ("Ren'Py", "KiriKiri", "RPG Maker", "Yu-Ris", "AdvHD", "ExHIBIT",
                      "CatSystem2", "Unity")


def build(rep: Any) -> Plan | None:
    """从 `galgame_dispatch.Report` 生成提取计划；判不出引擎则返回 None。"""
    best = rep.best
    if best is None or best.score < 60:
        return None

    engine = best.engine
    game = Path(rep.path)
    archives = getattr(rep, "archives", {}) or {}
    out = _out_dir(game)

    builder = _BUILDERS.get(engine)
    if builder is None:
        return Plan(
            engine=engine,
            extractor="(无)",
            kind="whole_dir",
            reason=f"{engine} 判出来了，但还没有对应的提取器定义",
            notes=["这是规则表里有、planner 里没接的引擎——先按 ADVICE 的失败预案人工处理"],
        )
    return builder(engine, game, archives, out)


def _plan_orchestrator(engine: str, game: Path, archives: dict, out: Path,
                       fallback_tool: str, fallback_argv: list[str],
                       fallback_reason: str) -> Plan:
    """已接 orchestrator 的引擎：首选一条命令跑完整链，附单工具兜底。"""
    argv = _py("orchestrator.py") + [str(game), "--out", str(out)]
    p = Plan(
        engine=engine,
        extractor="orchestrator.py",
        argv=argv,
        kind="orchestrator",
        implemented=True,
        reason="一条命令走完 detect → extract → postprocess → verify → manifest，"
               "对账不为 0 就退出码 1（不会假装成功）",
        notes=[
            "复跑时加 `--reuse-raw` 可跳过解包，但仍会用索引重新对账",
            "验收要单独跑或看 manifest 的 verify 段；本计划不含内容级验收之外的人工复核",
        ],
    )
    p.extras.append(Plan(
        engine=engine,
        extractor=fallback_tool.split(" ")[0],
        argv=fallback_argv,
        kind="per_archive" if archives else "whole_dir",
        implemented=False,
        reason=fallback_reason,
    ))
    return p


def _renpy(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    rpas = archives.get(".rpa", [])
    single: list[str] = []
    if rpas:
        single = _py("rpa_extract_organized.py") + [
            str(rpas[0]), str(out / rpas[0].stem),
            "--manifest", str(out / f"{rpas[0].stem}.manifest.json"),
        ]
    p = _plan_orchestrator(
        engine, game, archives, out,
        "rpa_extract_organized.py", single,
        "只想解某一个包时用它（逐包对账用 RPA 索引去重条目数）",
    )
    if not rpas:
        p.notes.append("没找到 .rpa —— 可能是散装资源（媒体裸放），只需验收无需解包")
    else:
        p.notes.append(f"找到 {len(rpas)} 个 .rpa：" + "、".join(x.name for x in rpas[:6]))
    return p


def _kirikiri(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    xp3s = archives.get(".xp3", [])
    gui_argv = _py("krkr_auto_extract.py") + [str(game), "--out", str(out)]
    p = _plan_orchestrator(
        engine, game, archives, out,
        "krkr_auto_extract.py", gui_argv,
        "GARbro 读不出时（加密 xp3，或 Console 假阴性）走动态注入；"
        "游戏路径会自动 stage 成纯 ASCII",
    )
    if xp3s:
        big = max(xp3s, key=lambda f: f.stat().st_size)
        p.notes.append(
            f"找到 {len(xp3s)} 个 .xp3，最大的是 {big.name}"
            f"（{big.stat().st_size / 1024 / 1024:.1f} MB）——它最可能是加密的那个"
        )
    if not p.implemented:  # pragma: no cover - 目前恒为 True，留作契约
        p.notes.append("orchestrator 未接 KiriKiri，需手工跑")
    return p


def _unity(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    p = _plan_orchestrator(engine, game, archives, out,
                           "_unity_extract.py",
                           _py("_unity_extract.py") + [str(game), str(out / "raw")],
                           "单工具兜底：只想单独导出 AssetStudio 资产时的命令")
    p.notes.extend([
        "**不要用逗号分隔 --types**：`--types A,B,C` 会静默归零且退出码仍是 0（坑 4）",
        "音频若是 FSB5(FMOD) 容器，CLI 单次只出极少数且静默失败 → 用 _as_audio_collect2.py 多轮累积",
        "数产物才算成功，退出码 0 毫无意义",
        "Unity 6000 系改过 Shader 序列化，若报 EndOfStreamException 请改用 AssetStudioNext",
        "IL2CPP 后端需要先跑 Il2CppDumper（GameAssembly.dll + il2cpp_data/global-metadata.dat）",
    ])
    return p


def _electron(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    asars = archives.get(".asar", [])
    target = asars[0] if asars else None
    if target is None:
        # 没在顶层找到就找 app.asar
        cand = list(game.rglob("app.asar"))
        target = cand[0] if cand else None
    argv = _py("asar_tool.py") + (["extract", str(target), str(out)] if target else [])
    p = Plan(
        engine=engine,
        extractor="asar_tool.py",
        argv=argv,
        kind="per_archive",
        implemented=False,
        reason="自研 asar 解析器，直接读索引，比 AsarKit/WinASAR 快且可控",
        notes=[
            "asar 里通常只有引擎代码（dist/ + node_modules），媒体多半在外面的 data/ 且可能加密",
            "有 `<同名>.unpacked/` 旁路目录时记得一起看",
        ],
    )
    if target is None:
        p.notes.append("没找到 .asar —— 可能只是 Electron 壳，资源在别处")
    return p


def _rpgmaker(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    single = _py("_rpgmv_decrypt.py") + [
        str(game), str(out), "--manifest", str(out / "manifest.json"),
    ]
    p = _plan_orchestrator(
        engine, game, archives, out,
        "_rpgmv_decrypt.py", single,
        "单独跑解密器：自动找 www/、自动读 System.json 的 encryptionKey；只 XOR 前 16 字节",
    )
    p.notes.extend([
        "先看 System.json 的 hasEncryptedImages/hasEncryptedAudio——都是 false 就无需解密",
        "后缀还原：.rpgmvp→png / .rpgmvo→ogg / .rpgmvm→m4a（MZ 是 .png_/.ogg_ 风格）",
        "MV 视频在 www/movies/*.webm|mp4（明文）；目录没有就是没有",
    ])
    return p


def _advhd(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    arcs = archives.get(".arc", [])
    pnas = sorted(game.rglob("*.pna"))
    p = _plan_orchestrator(
        engine, game, archives, out,
        fallback_tool="GARbro.Console.exe",
        fallback_argv=["GARbro.Console.exe", "-x", str(arcs[0])] if arcs else [],
        fallback_reason="单工具兜底：GARbro 原生支持 .arc，一个工具通吃；"
                        "`-x` 就地解到 cwd，所以必须逐包换 cwd",
    )
    p.notes.extend([
        "**.arc 列表输出无表头**（xp3 也没有）：条目数 = 非空行数，别用 len(lines)-1",
        "对账地面真相是 GARbro 列出的条目数 + 散装 .dat 个数（.dat 改成 .wmv 才算视频）",
    ])
    if arcs:
        p.notes.append(f"找到 {len(arcs)} 个 .arc，orchestrator 会逐包提取到 raw/<包名>/")
    else:
        p.notes.append("没找到 .arc —— 检查游戏目录层级")
    if pnas:
        p.notes.append(f"另有 {len(pnas)} 个 .pna（PNAP 多帧容器），GARbro 不认；"
                       f"orchestrator 的 postprocess 会逐帧 carve 成 png/")
    return p


def _yuris(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    ypfs = archives.get(".ypf", [])
    single = _py("_ypf_extract.py") + (
        [str(ypfs[0]), str(out / ypfs[0].stem),
         "--manifest", str(out / f"{ypfs[0].stem}.manifest.json")] if ypfs else []
    )
    p = _plan_orchestrator(
        engine, game, archives, out,
        "_ypf_extract.py", single,
        "单独跑 YPF 提取器（格式已完整逆向）；GARbro 不支持 YPF",
    )
    p.notes.extend([
        "**每个 .ypf 单独跑一次**，输出目录别混（同名文件跨包会互相覆盖）",
        "arc_unpacker 可作备选：`--out=DIR` 必须等号形式，大包疑似卡死",
    ])
    if ypfs:
        p.notes.append(f"找到 {len(ypfs)} 个 .ypf：" + "、".join(x.name for x in ypfs[:6]))
    else:
        p.notes.append("没找到 .ypf —— 检查 pac/ 目录")
    return p


def _exhibit(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    gyus = archives.get(".gyu", [])
    grps = archives.get(".grp", [])
    p = _plan_orchestrator(
        engine, game, archives, out,
        "_gyu_tool.exe",
        [str(_repo_root() / "_gyu_tool.exe"), str(game), str(out / "raw" / "img")],
        "单工具兜底：`_gyu_tool.exe` 递归解 `.gyu`；源码 `_gyu_tool.cs` 在仓库根，"
        "exe 缺失时 orchestrator 会调 csc 现编（`python toolbridge.py csharp` 可查状态）",
    )
    p.notes.extend([
        "`.gyu` 密钥在文件头（Key≠0xFFFFFFFF 时 MT 交换 10 对字节去混淆）",
        "Gyu-LZ 位流与字节流**共享游标**——移植大坑",
        "**BGM（res/s/m/*.ogg）加密未解**：只有头两页 3853B 被加密，密钥疑在 cluu/GUID/DPMODE。"
        "orchestrator 会把这 22 个**排除在交付之外并显式报出**（不静默丢，也不当成 22 个失败）",
    ])
    if gyus:
        p.notes.insert(0, f"找到 {len(gyus)} 个 .gyu")
    if grps:
        p.extras.append(Plan(
            engine=engine,
            extractor="_grp_extract.py",
            argv=_py("_grp_extract.py") + [
                str(grps[0].parent), str(out / "raw" / "audio"),
                "--manifest", str(out / "grp.manifest.json"),
            ],
            kind="whole_dir",
            implemented=False,
            reason=f"另有 {len(grps)} 个 .grp（AiFS TOC 切 ogg）：orchestrator 会自动跑它，"
                   f"这里给的是「只想单独切音频」时的命令",
        ))
    return p


def _catsystem2(engine: str, game: Path, archives: dict, out: Path) -> Plan:
    ints = archives.get(".int", [])
    p = _plan_orchestrator(
        engine, game, archives, out,
        "_cs2_int_extract.py",
        _py("_cs2_int_extract.py") + [str(game), str(out / "raw")],
        "单工具兜底：`_cs2_int_extract.py` 一次解目录下所有 .int（MT 名字混淆 + 小端 Blowfish）；"
        "orchestrator 会自动跑它，这里给的是「只想单独解密」时的命令",
    )
    p.notes.extend([
        "**扩展名不可信**：引擎对扩展名做了二次轮换（实测 3907 个 OggS 里只有 148 个恰好叫 `.ogg`，"
        "≈1/26）→ 交付前必须按**魔数**归一，否则乱扩展名的媒体会被当成「非媒体文件」静默放过",
        "`.int` 里约一半是 `LPD\\x00` 数据（float32，ffprobe 读不了，不是音频）——归数据文件，不算缺失",
        "图片是 HG-3 家族（`.hg3`/`.nm3`/`.gf3` **及任意扩展名**）→ 解完还要跑 "
        "`_hg3_tool.exe <root> <outdir>` 按魔数扫描；orchestrator 已内置这一步（`run_csharp(\"hg3\", …)`）",
        "HG-3 的 row 必须按 `w*(bpp/8)` 算，硬编码 `w*4` 在 24bpp 越界（verified-findings §16.5）",
        "同目录同 stem 的 `.hg3`/`.nm3` 会被 `Path.ChangeExtension('.png')` 归一化到同一张图，"
        "所以「解码数」≥「PNG 数」——orchestrator 按去重后的张数判产物，并把撞车数写进 manifest",
    ])
    if ints:
        p.notes.insert(0, f"找到 {len(ints)} 个 .int")
    else:
        p.notes.append("没找到 .int —— 确认游戏根目录（.int 与 exe 同级）")
    return p


_BUILDERS = {
    "Ren'Py": _renpy,
    "KiriKiri": _kirikiri,
    "Unity": _unity,
    "Tyrano/Electron": _electron,
    "RPG Maker": _rpgmaker,
    "AdvHD": _advhd,
    "Yu-Ris": _yuris,
    "ExHIBIT": _exhibit,
    "CatSystem2": _catsystem2,
}


def render(plan: Plan | None) -> str:
    """把计划渲染成人读文本（dispatch 的 `--plan` 段用）。"""
    if plan is None:
        return ""
    out: list[str] = ["", "提取计划："]

    tag = "" if plan.implemented else "（orchestrator 未接，需单独跑）"
    out.append(f"  提取器：{plan.extractor}{tag}")
    if plan.cmdline:
        out.append(f"  命令：  {plan.cmdline}")
    if plan.reason:
        out.append(f"  说明：  {plan.reason}")
    for n in plan.notes:
        if n:
            out.append(f"    - {n}")
    for e in plan.extras:
        out.append(f"  补充：{e.extractor}")
        if e.cmdline:
            out.append(f"    {e.cmdline}")
        if e.reason:
            out.append(f"    {e.reason}")
    return "\n".join(out)
