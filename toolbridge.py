#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部工具桥（toolbridge）—— 找工具 / 调工具 / 数产物 / 退出码不信任。

设计目标（software-plan §3 阶段1 第 4 条 + 阶段2 第 2 条）：
  统一「找工具（注册表化路径）+ 调用 + 数产物 + 退出码不信任」，
  覆盖 GARbro / tlg2png / ffprobe / AssetStudio / KrkrExtract / csc / gyu / hg3 八个。
  其中 gyu / hg3 是**本仓库自带的 C# 工具**：源码随包，exe 缺失或比源码旧时用 csc 现编（`ensure_csharp`）。

四条硬规矩（每条都是踩坑换来的，见 AGENTS.md「坑」与 verified-findings）：
  1. **退出码 0 毫无意义**（坑 4）：AssetStudio `--types A,B,C` 会静默归零且 exit=0。
     → 成功判据一律是「产物数」或「产物谓词」，returncode 只作诊断信息记录。
  2. **外部工具路径不许硬编码**：查找顺序 = 显式 override → 环境变量 → 配置文件
     → 内置候选 → PATH。找不到就抛 ToolNotFound，并把所有尝试过的路径列出来。
  3. **子进程环境要洗干净**（蓝图 §4.3）：PyInstaller 冻结后 `_MEIPASS` 会进 PATH，
     子进程继承后会优先加载包内同名 DLL 而崩溃；同时清 `SetDllDirectoryW`。
  4. **判「有没有视频」不能靠魔数扫描**（坑 3）：本模块只负责调工具与数产物，
     不做任何内容级猜测——那属于各引擎 extractor 的职责。
  5. **C# 工具源码随包、首启现编**（software-plan §3 阶段2 第 2 条）：`_gyu_tool` / `_hg3_tool`
     的 exe 不作为交付物入库，由 `ensure_csharp()` 用 csc 现场编译并缓存（源码更新则重编）。
     编译失败必须把 **csc 路径 + stderr 原文**一起抛出来，不许静默退化成「工具不存在」——
     否则用户看到的会是「.gyu 解不出来」，而真因是编译器没找到。

用法（库）::

    import toolbridge as tb
    r = tb.run("garbro", ["-x", str(xp3)], cwd=outdir, product_dir=outdir)
    if not r.ok:                      # r.ok 由产物数决定，不是 returncode
        print(r.reason)

用法（CLI，自检）::

    python toolbridge.py check              # 列出注册表里全部工具的解析结果（含自带 C# 工具）
    python toolbridge.py check --json       # 机器可读
    python toolbridge.py csharp             # 自带 C# 工具编译状态（源码/exe/过期/编译器）
    python toolbridge.py where garbro       # 只查一个
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

__all__ = [
    "ToolSpec", "Products", "ToolResult", "ToolNotFound",
    "TOOLS", "find_tool", "run", "count_products", "snapshot",
    "garbro_list", "garbro_extract", "tlg2png", "ffprobe", "ffprobe_ex",
    "assetstudio_export", "krkr_inject", "check_all", "check_csharp",
    "CSharpSource", "CSHARP", "CSharpBuildError",
    "repo_root", "build_csharp", "ensure_csharp", "run_csharp",
]

# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------
# 每条的 candidates 只放「本机已知的安装位置」，全部可被环境变量/配置文件覆盖。
# 环境变量名统一 TOOLBRIDGE_<KEY>，避免和游戏自己的环境变量撞车。

_REPO = Path(__file__).resolve().parent
"""本仓库根目录。自带工具（_gyu_tool.exe 等）与它们的 .cs 源码都在这里。"""


@dataclass(frozen=True)
class ToolSpec:
    """一个外部工具的描述。纯数据，不含行为。"""

    key: str
    exe_name: str
    purpose: str
    candidates: tuple[str, ...] = ()
    """内置候选绝对路径（可含 %VAR%）。按顺序尝试。"""

    sync: bool = True
    """True = 调用后同步产出文件；False = 只负责启动（如 KrkrExtract 注入后走 GUI）。"""

    notes: str = ""
    """已知坑，打印在 ToolNotFound / check 输出里，省得下次再踩。"""

    @property
    def env_var(self) -> str:
        return "TOOLBRIDGE_" + self.key.upper()


TOOLS: dict[str, ToolSpec] = {
    "garbro": ToolSpec(
        key="garbro",
        exe_name="GARbro.Console.exe",
        purpose="KiriKiri(.xp3)/AdvHD(.arc) 等封包的列出与提取（`-x` 就地解到 cwd）",
        candidates=(
            r"D:\K\galgame\GARbro\GARbro.Console.exe",
            r"%ProgramFiles%\GARbro\GARbro.Console.exe",
        ),
        notes=(
            "Console 对 GUI 能解的游戏会**假阴性**报 `unknown format`（坑 1）："
            "「读不出」不可作为否定证据，只能把「可识别」当正面证据。"
            "列目录时输出**无表头**（每行一条），条目数 = 行数，不要 len(lines)-1（xp3 除外，xp3 有表头）。"
        ),
    ),
    "tlg2png": ToolSpec(
        key="tlg2png",
        exe_name="tlg2png.exe",
        purpose="KiriKiri 的 .tlg → .png 单文件转换（argv: <in.tlg> <out.png>）",
        candidates=(
            r"D:\K\galgame\tlg2png\tlg2png.exe",
        ),
        notes="成功判据必须查产物：exit=0 + 文件存在 + size>8 + 头 4 字节 `\\x89PNG`。",
    ),
    "ffprobe": ToolSpec(
        key="ffprobe",
        exe_name="ffprobe.exe",
        purpose="音视频验收（argv: -v error -print_format json -show_format -show_streams <file>）",
        candidates=(
            r"D:\ffmpeg\bin\ffprobe.exe",
            r"%ProgramFiles%\ffmpeg\bin\ffprobe.exe",
        ),
        notes=(
            "**只对白名单扩展名调用**（见 _verify_media.AV_EXT）——把 .rpyc/.otf/.json 送去只会得到 "
            "`Invalid data found`，把验收结果搅浑（verified-findings §9.4）。"
            "数视频按**文件扩展名**，不要按 stream 数（内嵌封面会被算成 video 流，坑见纪律 4）。"
        ),
    ),
    "assetstudio": ToolSpec(
        key="assetstudio",
        exe_name="AssetStudio.CLI.exe",
        purpose="Unity 资产导出（分批按类型导出，见 unity_unpack.ps1）",
        candidates=(
            r"D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe",
        ),
        notes=(
            "**坑 4**：`--types A,B,C` 逗号会静默归零（exit 仍是 0）；`--types 'A|B|C'` 会让过滤器"
            "整体失效退化成全导。只能用单类型 `--types A` 或不写。"
            "大工程一次性全导会 `0xC0000374` 堆损坏 → 必须按类型分批。"
        ),
    ),
    "krkr": ToolSpec(
        key="krkr",
        exe_name="KrkrExtract.Lite.exe",
        purpose="加密 KiriKiri 的 xp3 动态提取（CLI 注入 + Explorer 真拖拽，见 krkr_auto_extract.py）",
        candidates=(
            r"D:\K\galgame\krkr\krkr\KrkrExtract.Lite.exe",
        ),
        sync=False,
        notes=(
            "**非同步工具**：`KrkrExtract.Lite.exe <game.exe>` 只是注入启动，产物由 GUI 拖拽产生，"
            "本桥只负责启动与进程管理；产物计数由调用方在 stage 目录里做。"
            "三件套必须同目录（.Lite.exe + .Core.dll + .UI.Lite.dll）。"
            "游戏路径**必须纯 ASCII**（CJK 会弹 `ANSI 文字列を UNICODE 文字列に変換できません`）。"
        ),
    ),
    "csc": ToolSpec(
        key="csc",
        exe_name="csc.exe",
        purpose="把本仓库自带的 C# 解码器现场编译成 exe（argv: /nologo /target:exe /platform:X /out:X.exe <src.cs>）",
        candidates=(
            r"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
            r"%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe",
        ),
        notes=(
            "系统自带的 .NET Framework 编译器（Framework 目录下那个），**不需要装 .NET SDK**。"
            "**平台要对齐**：要 `LoadLibrary` 载 32 位游戏 DLL 时必须 `/platform:x86`，"
            "否则运行时 `BadImageFormatException`；纯独立的转换器用 anycpu 即可。"
            "编译产物缓存到源码旁边，只在**源码 mtime 比 exe 新**或显式 force 时才重编。"
        ),
    ),
    "gyu": ToolSpec(
        key="gyu",
        exe_name="_gyu_tool.exe",
        purpose="ExHIBIT/Retouch 的 .gyu 图片批量解码成 PNG（argv: <root> <outdir>）",
        candidates=(str(_REPO / "_gyu_tool.exe"),),
        notes=(
            "**源码随包**（`_gyu_tool.cs`）：exe 不在或比源码旧时由 `ensure_csharp(\"gyu\")` 用 csc 现编。"
            "CLI 是「递归扫 root 下的 *.gyu → 按相同相对路径另存到 outdir」的批量式，不是单文件转换；"
            "含 7 种变体 / MT 去混淆 / 双 LZ / 调色板 / alpha，**成功判据一律数产物，不看 rc**。"
        ),
    ),
    "hg3": ToolSpec(
        key="hg3",
        exe_name="_hg3_tool.exe",
        purpose="CatSystem2 的 HG-3 家族（.hg3/.nm3/.gf3 等）批量转 PNG（argv: <root> <outdir>）",
        candidates=(str(_REPO / "_hg3_tool.exe"),),
        notes=(
            "**源码随包**（`_hg3_tool.cs`）：exe 不在或比源码旧时由 `ensure_csharp(\"hg3\")` 用 csc 现编。"
            "**必须按魔数筛选**：引擎会二次混淆扩展名，任意扩展名的文件都可能是 HG-3，"
            "所以它扫 `*.*` 全部文件（`IsHg3Magic`）。"
            "改 bpp 支持时记得 row 要按 `w * (bpp/8)` 算——硬编码 `w*4` 在 24bpp 上越界（§16.5）。"
        ),
    ),
}


# ---------------------------------------------------------------------------
# 自带 C# 工具：源码随包，exe 现编现用
# ---------------------------------------------------------------------------
# 交付物里**不带 exe**（二进制不入库，也不受杀软待见），只带 .cs；
# 首次用到时用系统自带的 csc 编一次，编好的 exe 就放在源码旁边缓存。


@dataclass(frozen=True)
class CSharpSource:
    """一个「源码随包」的 C# 工具。"""

    key: str
    source_name: str
    exe_name: str
    purpose: str
    platform: str = "anycpu"

    @property
    def source(self) -> Path:
        return _REPO / self.source_name

    @property
    def exe(self) -> Path:
        return _REPO / self.exe_name


CSHARP: dict[str, CSharpSource] = {
    "gyu": CSharpSource(
        key="gyu",
        source_name="_gyu_tool.cs",
        exe_name="_gyu_tool.exe",
        purpose="ExHIBIT .gyu → PNG（含 7 变体/MT 去混淆/双 LZ/调色板/alpha）",
    ),
    "hg3": CSharpSource(
        key="hg3",
        source_name="_hg3_tool.cs",
        exe_name="_hg3_tool.exe",
        purpose="CatSystem2 HG-3 家族 → PNG（按魔数扫描，不看扩展名）",
    ),
}


class CSharpBuildError(RuntimeError):
    """C# 编译失败。消息里必须带 **csc 路径 + 源码路径 + stderr 原文**。

    只报「工具不存在」是把用户往错方向引：真因是编译器找不到或源码有语法错，
    而用户看到的会是「.gyu 解不出来」。
    """


# 配置文件：优先仓库根，其次用户目录。两者可同时存在，后者覆盖前者。
CONFIG_NAME = "toolbridge.json"




class ToolNotFound(RuntimeError):
    """工具找不到。消息里带全部尝试过的路径 + 该工具的已知坑。"""


# ---------------------------------------------------------------------------
# 找工具
# ---------------------------------------------------------------------------


def _expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def _bin_root() -> Path | None:
    """随包工具目录 `<应用根>/bin`（build_exe.py 把外部工具拷到冻结包这里）。

    冻结态 = exe 旁；源码态 = 仓库根（一般不存在 → 返回 None，解析直接跳过这一档）。
    独立成函数：测试好 monkeypatch（锁解析顺序用）。
    """
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else _REPO
    p = base / "bin"
    return p if p.is_dir() else None


def _load_config() -> dict:
    """读 toolbridge.json。找不到/坏掉都静默返回 {}——配置是可选增强，不能拖垮主流程。"""
    here = Path(__file__).resolve().parent
    merged: dict = {}
    def _home_dir() -> Path:
        """用户主目录；当前 DSH 会话下 expanduser('~') 可能抛 RuntimeError，兜底到 %USERPROFILE% / ~ 字符串本身。"""
        try:
            h = Path.home()
            if str(h) != "~":
                return h
        except Exception:
            pass
        up = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        return Path(up) if up else Path("~")
    for cand in (here / CONFIG_NAME, _home_dir() / ".toolbridge.json"):
        try:
            if cand.is_file():
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    merged.update(data)
        except Exception:
            continue
    return merged


def find_tool(key: str, override: str | os.PathLike | None = None) -> Path:
    """解析工具绝对路径。找不到抛 ToolNotFound（消息含全部尝试记录）。

    查找顺序：显式 override → 环境变量 TOOLBRIDGE_<KEY> → 配置文件 paths.<key>
    → 内置 candidates → PATH 里同名 exe。
    """
    spec = TOOLS.get(key)
    if spec is None:
        raise KeyError(f"unknown tool key: {key!r} (known: {sorted(TOOLS)})")

    tried: list[str] = []

    def _try(cand: str | os.PathLike | None, origin: str) -> Path | None:
        if not cand:
            return None
        p = Path(_expand(str(cand)))
        tried.append(f"{origin}: {p}")
        return p if p.is_file() else None

    hit = _try(override, "override")
    if hit:
        return hit

    hit = _try(os.environ.get(spec.env_var), f"env {spec.env_var}")
    if hit:
        return hit

    cfg = _load_config().get("paths") or {}
    if isinstance(cfg, Mapping):
        hit = _try(cfg.get(key), f"config paths.{key}")
        if hit:
            return hit

    # 随包工具（bin/<key>/<exe>）：冻结包 build_exe.py 打进去的副本，优先于内置候选
    # ——装机即用、不依赖开发机的目录布局；仍让位给 override/env/config 显式配置。
    bin_root = _bin_root()
    if bin_root is not None:
        hit = _try(bin_root / spec.key / spec.exe_name, f"bundled bin/{spec.key}")
        if hit:
            return hit

    # 内置候选放在配置文件之后：用户显式配置永远优先于我们的猜测
    for c in spec.candidates:
        hit = _try(c, "candidate")
        if hit:
            return hit

    # PATH 兜底：只认同名 exe，避免误抓别的工具
    which = shutil.which(spec.exe_name)
    tried.append(f"PATH: {which or '(not found)'}")
    if which:
        return Path(which)

    raise ToolNotFound(
        f"找不到工具 {key!r}（{spec.exe_name}）——用途：{spec.purpose}\n"
        f"已尝试：\n  " + "\n  ".join(tried) + "\n"
        f"设置办法（任选其一）：\n"
        f"  * 环境变量 {spec.env_var}=<exe 绝对路径>\n"
        f"  * {Path(__file__).resolve().parent / CONFIG_NAME} 里写 "
        f'{{"paths": {{"{key}": "<exe 绝对路径>"}}}}\n'
        f"  * 把 {spec.exe_name} 放进 PATH\n"
        + (f"已知坑：{spec.notes}" if spec.notes else "")
    )


# ---------------------------------------------------------------------------
# 自带 C# 工具：编译（源码随包 → csc → exe 缓存）
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """本仓库根目录。自带工具（`_gyu_tool` 等）与它们的 .cs 源码都在这里。"""
    return _REPO


def build_csharp(
    source: str | os.PathLike,
    *,
    out_dir: str | os.PathLike | None = None,
    exe_name: str | None = None,
    platform: str = "anycpu",
    force: bool = False,
    compiler: Sequence[str] | None = None,
    timeout: float = 300,
) -> Path:
    """把一个 .cs 编成 exe，返回 exe 路径（编不动就抛 `CSharpBuildError`）。

    缓存规则：exe 已存在、且 **mtime 不比源码旧**，就直接复用（不重编）；
    否则（或 `force=True`）跑一次 csc。这套「源码随包 + 现编 + 复用」是为了让
    交付包里**不带二进制**，同时开发机上编过一次就不再等编译器。

    参数
      compiler   **命令前缀列表**（默认 `[csc]`）。测试可注入假编译器，
                 也允许传 `["dotnet", "exec", ...]` 之类的替代前端。
      platform   `/platform:` 的值。带 `DllImport`/`LoadLibrary` 载 32 位游戏 DLL 的
                 工具必须 `x86`（否则运行时 `BadImageFormatException`）。
    """
    src = Path(source)
    if not src.is_file():
        raise CSharpBuildError(f"C# 源码不存在：{src}")

    out = Path(out_dir) if out_dir is not None else src.parent
    out.mkdir(parents=True, exist_ok=True)
    exe = out / (exe_name or (src.stem + ".exe"))

    if exe.is_file() and not force and exe.stat().st_mtime >= src.stat().st_mtime:
        return exe

    cmd = list(compiler) if compiler is not None else [str(find_tool("csc"))]
    cmd += ["/nologo", "/target:exe", f"/platform:{platform}",
            f"/out:{exe}", str(src)]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              env=_sanitize_env())
    except FileNotFoundError:
        raise CSharpBuildError(
            f"找不到 C# 编译器：{cmd[0]}\n"
            f"（系统自带的是 %WINDIR%\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe）"
        ) from None
    except subprocess.TimeoutExpired:
        raise CSharpBuildError(f"C# 编译超时（>{timeout:g}s）：{src.name}") from None

    if proc.returncode != 0 or not exe.is_file():
        raise CSharpBuildError(
            f"C# 编译失败：{src.name}\n"
            f"命令：{' '.join(cmd)}\n"
            f"退出码：{proc.returncode}（exe 是否存在：{exe.is_file()}）\n"
            f"stderr：\n{_decode(proc.stderr) or '(空)'}\n"
            f"stdout：\n{_decode(proc.stdout) or '(空)'}"
        )
    return exe


def ensure_csharp(key: str, **kw) -> Path:
    """拿到自带 C# 工具的 exe：仓库里已有且不旧就直接用，否则用 csc 现编。

    注册表见 `CSHARP`。这是「源码随包」的落地点——发布包可以不带 exe，
    用户机器上第一次用到时才编（编好的 exe 落在源码旁边，之后直接复用）。
    """
    spec = CSHARP.get(key)
    if spec is None:
        raise KeyError(f"unknown csharp key: {key!r} (known: {sorted(CSHARP)})")
    return build_csharp(spec.source, exe_name=spec.exe_name,
                        platform=spec.platform, **kw)


def run_csharp(key: str, argv: Sequence[str] = (), *, build: dict | None = None,
               **run_kw) -> ToolResult:
    """确保自带 C# 工具编好了，然后调它。

    判定逻辑与 `run()` **完全一致**（数产物，不看退出码）：这两个工具都是
    「扫一棵树 → 另存一棵树」，rc=0 但 0 产物完全可能发生。

    `build` 透传给 `ensure_csharp`（`force` / `compiler` / `platform` 等），
    其余关键字透传给 `_run_exe`（`product_dir` / `min_products` / `timeout` 等）。
    """
    if key not in CSHARP:
        raise KeyError(f"unknown csharp key: {key!r} (known: {sorted(CSHARP)})")
    exe = ensure_csharp(key, **(build or {}))
    return _run_exe(exe, key=key, argv=argv, **run_kw)


# ---------------------------------------------------------------------------
# 数产物
# ---------------------------------------------------------------------------


@dataclass
class Products:
    """一次目录快照。total/by_ext 只统计**文件**（目录不算）。"""

    total: int = 0
    by_ext: dict[str, int] = field(default_factory=dict)
    size: int = 0

    def delta_from(self, before: "Products") -> "Products":
        by_ext = {
            k: self.by_ext.get(k, 0) - before.by_ext.get(k, 0)
            for k in set(self.by_ext) | set(before.by_ext)
        }
        return Products(
            total=self.total - before.total,
            by_ext={k: v for k, v in by_ext.items() if v},
            size=self.size - before.size,
        )

    def as_dict(self) -> dict:
        return {"total": self.total, "by_ext": dict(sorted(self.by_ext.items())),
                "size": self.size}


def count_products(root: str | os.PathLike, exts: Iterable[str] | None = None) -> Products:
    """递归统计 root 下的文件数 / 按扩展名分布 / 总字节。

    exts 给出时只统计这些扩展名（大小写不敏感，需带点，如 {".png"}）。
    root 不存在返回全 0（不抛异常——调用方常在产物目录尚未创建时先取 before 快照）。
    """
    root = Path(root)
    want = {e.lower() for e in exts} if exts else None
    out = Products()
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        ext = p.suffix.lower()
        if want is not None and ext not in want:
            continue
        out.total += 1
        out.by_ext[ext] = out.by_ext.get(ext, 0) + 1
        try:
            out.size += p.stat().st_size
        except OSError:
            pass
    return out


def snapshot(root: str | os.PathLike, exts: Iterable[str] | None = None) -> Products:
    """count_products 的别名，用于 before/after 配对书写。"""
    return count_products(root, exts)


# ---------------------------------------------------------------------------
# 调工具
# ---------------------------------------------------------------------------


def _sanitize_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """给子进程一份干净环境。

    为什么要洗：PyInstaller `--onedir` 冻结后会把 `sys._MEIPASS` 塞进 PATH，
    子进程继承后加载同名的 Qt/SSL DLL 就崩（蓝图 §4.3 高风险项）。
    PYTHONHOME/PYTHONPATH 同理——外部 exe 不需要，留着只会让某些 Python 包装器错乱。
    """
    e = dict(env if env is not None else os.environ)
    parts = [p for p in e.get("PATH", "").split(os.pathsep)
             if p and "_MEI" not in p.upper()]
    e["PATH"] = os.pathsep.join(parts)
    for k in ("PYTHONHOME", "PYTHONPATH"):
        e.pop(k, None)
    return e


def _clear_dll_dir() -> None:
    """调外部 exe 前清掉本进程的 DLL 搜索目录（蓝图 §4.3）。

    冻结环境里 Python 自己会把 _MEIPASS 设成 DLL 目录，子进程继承该设置后
    会优先从包内找 DLL。SetDllDirectoryW(None) 恢复默认搜索顺序。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    except Exception:
        pass


def _decode(b: bytes | None) -> str:
    return (b or b"").decode("utf-8", "replace")


@dataclass
class ToolResult:
    """一次工具调用结果。**ok 的判据是产物，不是 returncode**。"""

    key: str
    exe: str
    argv: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0.0
    timed_out: bool = False
    products: Products = field(default_factory=Products)
    """产物（若给了 product_dir，这里是**增量**；否则是全 0）。"""

    product_dir: str | None = None
    ok: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "exe": self.exe, "argv": self.argv,
            "returncode": self.returncode, "seconds": round(self.seconds, 2),
            "timed_out": self.timed_out,
            "products": self.products.as_dict(),
            "product_dir": self.product_dir,
            "ok": self.ok, "reason": self.reason,
            "stderr_tail": self.stderr.strip().splitlines()[-1][:200] if self.stderr.strip() else "",
        }

    def summary(self) -> str:
        mark = "OK  " if self.ok else "FAIL"
        extra = f" {self.reason}" if self.reason else ""
        return (f"[{mark}] {self.key} rc={self.returncode} "
                f"{self.seconds:.1f}s products={self.products.total}{extra}")


def run(
    key: str,
    argv: Sequence[str] = (),
    *,
    cwd: str | os.PathLike | None = None,
    timeout: float = 1800,
    product_dir: str | os.PathLike | None = None,
    min_products: int = 1,
    product_check: Callable[[Path], bool] | None = None,
    env: Mapping[str, str] | None = None,
    exe_override: str | os.PathLike | None = None,
    stdin_text: str | None = None,
) -> ToolResult:
    """调用一个已注册工具，并用**产物**判定成败。

    参数
      key            注册表里的工具名（TOOLS 的 key）
      argv           除 exe 之外的参数（list，绝不用字符串拼接——含空格路径会碎）
      cwd            工作目录（GARbro `-x` 是**就地解到 cwd**，必须给）
      product_dir    产物目录。给出时先做 before 快照，调用后算增量
      min_products   增量文件数达到多少才算成功（默认 1）
      product_check  逐产物谓词（如「是合法 PNG」）。给出时对增量文件全过才 ok
      exe_override   临时指定 exe（测试/多版本用）

    成功判据（依次）：
      1. 未超时
      2. 若给 product_dir：增量 >= min_products；若还给了 product_check，每个增量文件都要过
      3. 未给 product_dir：退回 returncode==0，但 reason 里标注「未验证产物」

    ⚠️ 规矩 1：**returncode 只作诊断**。GARbro 假阴性、AssetStudio 静默归零都证明了这一点。
    """
    exe = find_tool(key, exe_override)
    return _run_exe(
        exe, key=key, argv=argv, cwd=cwd, timeout=timeout,
        product_dir=product_dir, min_products=min_products,
        product_check=product_check, env=env, stdin_text=stdin_text,
    )


def _run_exe(
    exe: Path,
    *,
    key: str,
    argv: Sequence[str] = (),
    cwd: str | os.PathLike | None = None,
    timeout: float = 1800,
    product_dir: str | os.PathLike | None = None,
    min_products: int = 1,
    product_check: Callable[[Path], bool] | None = None,
    env: Mapping[str, str] | None = None,
    stdin_text: str | None = None,
) -> ToolResult:
    """`run()` 的执行体：exe 已确定，这里只管调用与判定。

    抽出来是为了让**自带 C# 工具**（exe 是现编的、不在任何注册路径上）走同一套
    「按产物判定」逻辑——判定口径只写一份，别为 C# 工具另立一套。
    """
    spec = TOOLS.get(key) or ToolSpec(key=key, exe_name=Path(exe).name,
                                      purpose="(仓库自带 C# 工具)")
    cmd = [str(exe), *[str(a) for a in argv]]

    before = count_products(product_dir) if product_dir is not None else None
    before_paths = _path_set(product_dir) if (product_dir is not None and product_check) else None

    _clear_dll_dir()
    t0 = time.time()
    timed_out = False
    rc: int | None = None
    out_b = err_b = b""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            timeout=timeout,
            env=_sanitize_env(env),
            input=stdin_text.encode("utf-8") if stdin_text is not None else None,
        )
        rc, out_b, err_b = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out_b, err_b = exc.stdout or b"", exc.stderr or b""
    except FileNotFoundError:
        raise ToolNotFound(f"exe 存在但无法执行：{exe}") from None
    except OSError as exc:
        # 权限/占用/架构不匹配（32/64 位）等
        res = ToolResult(key=key, exe=str(exe), argv=cmd, returncode=None,
                         seconds=time.time() - t0,
                         ok=False, reason=f"启动失败 {type(exc).__name__}: {exc}")
        return res

    res = ToolResult(key=key, exe=str(exe), argv=cmd, returncode=rc,
                     stdout=_decode(out_b), stderr=_decode(err_b),
                     seconds=time.time() - t0, timed_out=timed_out,
                     product_dir=str(product_dir) if product_dir is not None else None)

    # ---- 判定 ----
    if timed_out:
        res.ok, res.reason = False, f"超时（>{timeout:g}s）"
        return res

    if before is not None:
        after = count_products(product_dir)
        res.products = after.delta_from(before)
        if res.products.total < min_products:
            res.ok = False
            tail = res.stderr.strip().splitlines()
            res.reason = (f"产物不足：增量 {res.products.total} < 期望 {min_products}"
                          f"（rc={rc}）" + (f"；stderr: {tail[-1][:160]}" if tail else ""))
            return res
        if product_check is not None:
            new_files = sorted(_path_set(Path(product_dir)) - (before_paths or set()))
            bad = [p for p in new_files if not _safe_check(product_check, p)]
            if bad:
                res.ok = False
                res.reason = (f"{len(bad)}/{len(new_files)} 个产物未通过校验"
                              f"（首个：{bad[0].name}）")
                return res
        res.ok = True
        res.reason = f"产物 {res.products.total} 个"
        if spec.sync is False:
            res.reason += "（注意：该工具非同步，产物由后续 GUI 流程产生）"
        return res

    # 没有产物目录：只能看退出码，但明确标注「未验证」
    res.ok = rc == 0
    res.reason = "未提供 product_dir，仅凭退出码（不可信，建议补产物校验）" if res.ok \
        else f"rc={rc}"
    return res


def _path_set(root: str | os.PathLike | None) -> set[Path]:
    """目录下全部文件的路径集合。只在需要逐产物校验时取（会占内存，别在万级目录滥用）。"""
    if root is None:
        return set()
    root = Path(root)
    if not root.is_dir():
        return set()
    out: set[Path] = set()
    for p in root.rglob("*"):
        try:
            if p.is_file():
                out.add(p)
        except OSError:
            continue
    return out


def _safe_check(fn: Callable[[Path], bool], p: Path) -> bool:
    try:
        return bool(fn(p))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 各工具的具体调用（薄封装，让 orchestrator 不必记 argv 形状）
# ---------------------------------------------------------------------------


def garbro_list(archive: str | os.PathLike, *, timeout: float = 600) -> tuple[bool, int, str]:
    """列封包条目。返回 (可识别, 条目数, 原始输出)。

    ⚠️ 条目数口径：**输出无表头**，条目数 = 非空行数（xp3 也是每行一条，
    不要 len(lines)-1——那是 _batch_A_extract.py 的旧 bug，AdvHD 的 .arc 因此每包差 1）。
    首行含 `unknown format` 即不可识别（但**不可据此否定**，见坑 1）。
    """
    exe = find_tool("garbro")
    try:
        r = subprocess.run([str(exe), str(archive)], capture_output=True, timeout=timeout,
                           env=_sanitize_env())
    except subprocess.TimeoutExpired:
        return False, 0, f"超时（>{timeout:g}s）"
    except OSError as exc:
        return False, 0, f"启动失败 {type(exc).__name__}: {exc}"
    out = _decode(r.stdout) + _decode(r.stderr)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines or "unknown format" in lines[0].lower():
        return False, 0, out
    return True, len(lines), out


def garbro_extract(
    archive: str | os.PathLike,
    outdir: str | os.PathLike,
    *,
    timeout: float = 1800,
) -> ToolResult:
    """`GARbro.Console.exe -x <archive>`，**就地解到 cwd**，所以 cwd=outdir。"""
    Path(outdir).mkdir(parents=True, exist_ok=True)
    return run("garbro", ["-x", str(archive)], cwd=outdir, product_dir=outdir,
               timeout=timeout, min_products=1)


def _is_png(p: Path) -> bool:
    try:
        if p.suffix.lower() != ".png" or p.stat().st_size <= 8:
            return False
        with p.open("rb") as fh:
            return fh.read(4) == b"\x89PNG"
    except OSError:
        return False


def tlg2png(src: str | os.PathLike, dst: str | os.PathLike,
            *, timeout: float = 120) -> ToolResult:
    """单文件 .tlg → .png。成功判据 = **目标文件是合法 PNG**（不看退出码）。

    注意 product_dir 用 dst 的父目录，但 product_check 只认 dst 本身——
    同目录批量转换时，别的文件不该影响这一张的判定。

    **幂等**：`dst` 已经是合法 PNG 就直接返回 ok=True（reason 标注「已存在」），
    不再调工具。否则 `--reuse-raw` 这类复跑场景里 png/ 已有上次的产物，
    `run()` 会看到产物增量 0 而判失败 —— 实测把 507 张图全判成失败（2026-10-29）。
    「本次没新增」不等于「失败」，可能只是**已经干过了**。
    """
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _is_png(dst):
        return ToolResult(
            key="tlg2png", exe="(skipped)", argv=[], returncode=0,
            stdout="", stderr="", seconds=0.0, timed_out=False,
            products=Products(total=0, by_ext={}, size=0),
            product_dir=str(dst.parent), ok=True,
            reason=f"产物已存在且是合法 PNG，跳过转换：{dst.name}")
    r = run("tlg2png", [str(src), str(dst)], timeout=timeout, product_dir=dst.parent,
            min_products=1)
    if r.ok and not _is_png(dst):
        r.ok = False
        r.reason = f"产物不是合法 PNG：{dst.name}（size={dst.stat().st_size if dst.exists() else 0}）"
    return r


# 只有这些扩展名才值得送 ffprobe（与 _verify_media.AV_EXT 保持一致）。
AV_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".mpg", ".mpeg",
          ".mp3", ".ogg", ".wav", ".opus", ".flac", ".m4a", ".aac", ".wma"}


def _is_cover_stream(s: dict) -> bool:
    """ffprobe 会把 mp3/ogg 的**内嵌封面**报成 codec_type=video。

    验收纪律第 4 条：数视频按文件扩展名/真实视频流，别被封面骗了
    （实测 `常識改変学園` 866 个 .ogg 里有 19 个带 mjpeg 封面，全部 attached_pic=1）。
    """
    return bool((s.get("disposition") or {}).get("attached_pic"))


def parse_ffprobe_json(j: dict) -> dict | None:
    """把 ffprobe 的 JSON 规整成 {codec, kind, w, h, sr, dur, has_cover}。

    抽成纯函数是为了能直接喂构造数据测封面分支——真调 ffprobe 测不出
    「刚好挑中带封面的那个 ogg」，那种测试迟早退化成 skip。
    """
    streams = j.get("streams") or []
    if not streams:
        return None
    v = next((s for s in streams
              if s.get("codec_type") == "video" and not _is_cover_stream(s)), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    s = v or a
    if s is None:  # 只有封面、没有音轨也没有真视频流
        return None
    dur = j.get("format", {}).get("duration") or s.get("duration")
    return {
        "codec": s.get("codec_name"),
        "kind": "video" if v else "audio",
        "w": v.get("width") if v else None,
        "h": v.get("height") if v else None,
        "sr": a.get("sample_rate") if a else None,
        "dur": float(dur) if dur else None,
        "has_cover": any(_is_cover_stream(x) for x in streams),
    }


def ffprobe_ex(path: str | os.PathLike, *, timeout: float = 120,
               retries: int = 1) -> tuple[dict | None, str]:
    """探一个媒体文件，返回 `(信息, 原因)`；探得出来时原因恒为 `"ok"`。

    **为什么要带原因**：原来 `ffprobe()` 把三种完全不同的失败折成同一个 `None`——
    ①文件真坏 ②子进程没起来/超时 ③JSON 里压根没有音视频流，日志里一律写
    「ffprobe 无结果」。全量验收里冒出这么一条时，看日志的人无法判断该不该慌
    （实测：`甜蜜女友2+` 的 `pcm_DD/dd_02_ch08_019.OGG` 报无结果，但同一份字节
    现在能稳定探出 vorbis 流、Ogg 页 CRC 也对得上——是偶发，不是文件坏）。

    **为什么要重试**：偶发失败往往只差重跑一次（进程启动失败、机器吃紧时被拖超时）。
    重试只花在失败路径上，正常路径没有额外开销。
    """
    p = Path(path)
    if p.suffix.lower() not in AV_EXT:
        return None, f"扩展名 {p.suffix or '(无)'} 不在 ffprobe 白名单"
    why = "未知原因"
    for attempt in range(retries + 1):
        r = run("ffprobe", ["-v", "error", "-print_format", "json",
                            "-show_format", "-show_streams", str(p)], timeout=timeout)
        if r.timed_out:
            why = f"超时（>{timeout:g}s）"
        elif r.returncode != 0:
            lines = [ln for ln in (r.stderr or "").splitlines() if ln.strip()]
            why = f"rc={r.returncode}" + (f"：{lines[-1].strip()[:160]}"
                                          if lines else "（stderr 为空）")
        else:
            try:
                j = json.loads(r.stdout)
            except Exception as exc:
                why = f"JSON 解析失败：{exc}"
            else:
                info = parse_ffprobe_json(j)
                if info is not None:
                    return info, "ok"
                why = "没有任何音视频流（只有封面，或流列表为空）"
        if attempt >= retries:
            break
    if retries:
        why += f"（重试 {retries} 次仍失败）"
    return None, why


def ffprobe(path: str | os.PathLike, *, timeout: float = 120) -> dict | None:
    """探一个媒体文件，返回规整后的信息 dict；不可解返回 None。

    非白名单扩展名直接返回 None（**不要**把 .rpyc/.otf 送去 ffprobe，
    只会得到 `Invalid data found` 把验收搅浑）。

    只要结论、不要原因时用它；要判断「该不该慌」请用 `ffprobe_ex()`。
    """
    return ffprobe_ex(path, timeout=timeout)[0]


def assetstudio_export(
    src: str | os.PathLike,
    outdir: str | os.PathLike,
    *,
    types: str | None = None,
    names: str | None = None,
    export_type: str = "Convert",
    group_assets: str = "ByType",
    timeout: float = 3600,
) -> ToolResult:
    """AssetStudio 单类型分批导出。

    **坑 4 内置护栏**：
      * `types` 含逗号 → 直接抛 ValueError（逗号会被静默忽略、导 0 个文件且 exit=0）
      * `types` 含 `|` → 抛 ValueError（会让过滤器整体失效、退化成全导）
    正确做法：一次只导一个类型，多类型就多调几次。
    """
    if types is not None:
        if "," in types:
            raise ValueError(
                f"AssetStudio 的 --types 不接受逗号（会静默导 0 个文件且 exit=0，见坑 4）：{types!r}。"
                "一次只导一个类型，多类型就多调几次。")
        if "|" in types:
            raise ValueError(
                f"AssetStudio 的 --types 不接受竖线（会让过滤器整体失效、退化成全导）：{types!r}。")
    Path(outdir).mkdir(parents=True, exist_ok=True)
    argv = [str(src), str(outdir), "--game", "Normal"]
    if types:
        argv += ["--types", types]
    if names:
        argv += ["--names", names]
    argv += ["--export_type", export_type, "--group_assets", group_assets]
    return run("assetstudio", argv, product_dir=outdir, timeout=timeout, min_products=1)


def krkr_inject(game_exe: str | os.PathLike, *, cwd: str | os.PathLike | None = None,
                exe_override: str | os.PathLike | None = None) -> subprocess.Popen:
    """启动 KrkrExtract 注入。**非同步**——产物由后续 Explorer 拖拽产生。

    三件套必须在同目录（.Lite.exe / .Core.dll / .UI.Lite.dll），先自检再启动，
    免得启动了才发现少 DLL、白等一轮超时。
    """
    exe = find_tool("krkr", exe_override)
    missing = [n for n in ("KrkrExtract.Core.dll", "KrkrExtract.UI.Lite.dll")
               if not (exe.parent / n).is_file()]
    if missing:
        raise ToolNotFound(f"{exe.parent} 缺少 {missing}——三件套必须同目录")
    _clear_dll_dir()
    return subprocess.Popen([str(exe), str(game_exe)],
                            cwd=str(cwd) if cwd is not None else str(exe.parent),
                            env=_sanitize_env())


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------


def _csc_path() -> Path | None:
    """csc 编译器路径；找不到返回 None（不抛）。"""
    try:
        return find_tool("csc")
    except ToolNotFound:
        return None


def check_all() -> list[dict]:
    """逐个解析注册表里的工具，返回可序列化的状态表（不调用、只查在不在）。

    自带 C# 工具（`CSHARP` 那两条）特殊处理：exe 不在、但**源码在且 csc 在**时
    记为可用（`buildable=True`，用时会现编）——否则「源码随包」的干净检出
    会被误报成缺工具。
    """
    rows = []
    for key, spec in TOOLS.items():
        row = {"key": key, "exe_name": spec.exe_name, "purpose": spec.purpose,
               "sync": spec.sync, "notes": spec.notes}
        try:
            p = find_tool(key)
            row.update(found=True, path=str(p), size=p.stat().st_size)
        except ToolNotFound as exc:
            src = CSHARP.get(key)
            if src is not None and src.source.is_file() and _csc_path() is not None:
                row.update(found=True, buildable=True,
                           path=f"(源码随包，用 csc 现编) {src.source}",
                           size=src.source.stat().st_size)
            else:
                row.update(found=False, path=None, size=0,
                           error=str(exc).splitlines()[0])
        rows.append(row)
    return rows


def check_csharp() -> list[dict]:
    """自带 C# 工具的状态表：源码/exe 在不在、exe 是否过期、编译器在不在。"""
    csc = _csc_path()
    rows = []
    for key, spec in CSHARP.items():
        src, exe = spec.source, spec.exe
        src_ok, exe_ok = src.is_file(), exe.is_file()
        stale = exe_ok and src_ok and exe.stat().st_mtime < src.stat().st_mtime
        rows.append({
            "key": key,
            "source": str(src), "source_found": src_ok,
            "exe": str(exe), "exe_found": exe_ok, "stale": stale,
            "compiler": str(csc) if csc else None,
            "ready": src_ok and ((exe_ok and not stale) or csc is not None),
            "purpose": spec.purpose, "platform": spec.platform,
        })
    return rows


def _main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd in ("check", "list"):
        rows = check_all()
        if "--json" in argv:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                mark = "OK  " if r["found"] else "MISS"
                size = f"{r['size']:>12,} B" if r["found"] else " " * 14
                print(f"[{mark}] {r['key']:<12} {size}  {r['path'] or r.get('error', '')}")
            print()
            for r in check_csharp():
                if not r["ready"]:
                    mark = "MISS"
                elif r["stale"]:
                    mark = "OLD "
                elif not r["exe_found"]:
                    mark = "SRC "
                else:
                    mark = "OK  "
                print(f"[{mark}] {r['key']:<12} 源码随包；编译器：{r['compiler'] or '缺失'}")
        return 0 if all(r["found"] for r in rows) else 1
    if cmd == "csharp":
        rows = check_csharp()
        if "--json" in argv:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(f"{r['key']}: 源码 {'有' if r['source_found'] else '无'} / "
                      f"exe {'有' if r['exe_found'] else '无'}"
                      f"{'（过期）' if r['stale'] else ''} / "
                      f"编译器 {r['compiler'] or '缺失'} / "
                      f"{'可用' if r['ready'] else '不可用'}")
        return 0 if all(r["ready"] for r in rows) else 1
    if cmd == "where":
        if len(argv) < 2:
            print("usage: python toolbridge.py where <key>", file=sys.stderr)
            return 2
        try:
            print(find_tool(argv[1]))
            return 0
        except (ToolNotFound, KeyError) as exc:
            print(exc, file=sys.stderr)
            return 1
    print(__doc__)
    return 0 if cmd in ("-h", "--help", "help") else 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
