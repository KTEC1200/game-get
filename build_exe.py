#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结构建：把 orchestrator 冻成 onedir exe（软件化阶段 3，verified-findings §19.2 第 2 条）。

数据文件清单 —— **唯一出处**。新增任何「代码要读的数据文件」时同步改这里
（与 `manifest.CONVERTIBLE` 同理：清单只写一份，漏一个不是降级而是**启动即崩**）：
  rules/                          engines.json（引擎指纹规则表，rules/__init__.py 按 __file__ 定位）
  cases/                          案例库（index.json + case JSON，case_lib.DEFAULT_CASES_DIR 按 __file__ 定位）
  _gyu_tool.cs / _hg3_tool.cs     自带 C# 解码器源码（exe 不入库，首用 csc 现编，编出的 exe 落源码旁）
  _uia_item_rect.ps1              krkr GUI 链路的 UIA 矩形辅助脚本（krkr_auto_extract 按 __file__ 调）
  toolbridge.json（若存在）        工具路径覆盖配置（可选；缺失时走内置候选 + PATH）

不需要 --hidden-import：orchestrator 对 7 条链路的兄弟模块全部**顶部静态 import**
（tests/test_orchestrator.py §8.5 护栏锁着），PyInstaller 静态分析跟得全。
不进包的：asar_tool / _advhd_run / _spite_* 等（orchestrator 链路够不着的独立脚本，
进包只会变大；§19.1 的「14/14 可 import」是探针口径，不是产品口径）。

环境：Python 3.14.6 + PyInstaller 6.22.3 实测可冻（§19.1）。
教训（§19.3）：--add-data 的相对路径相对 **spec 目录**解析（不是 cwd）——这里一律传绝对路径。

用法：
  python build_exe.py                 # 冻结 + 出便携 zip（唯一交付形态，2026-11-04 定）
  python build_exe.py --check         # 只校验清单文件是否齐全，不构建
  python build_exe.py --portable      # 跳过冻结，用现有 dist 重新出便携 zip
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DIST = REPO / "_spike_pkg" / "dist"
BUILD = REPO / "_spike_pkg" / "build"
SPEC = REPO / "_spike_pkg"
EXE = DIST / "orchestrator" / "orchestrator.exe"
PACKAGING = REPO / "packaging"

#: 应用版本号 —— 便携包文件名与收尾摘要都从这里来（软件还没有 GUI/关于页，
#: 等要展示版本的地方多了再挪进独立 VERSION 文件）。
APP_VERSION = "0.4.0"

#: (源相对路径, 包内目标目录)。目标目录 "." = _internal 根（与仓库根布局镜像，
#: 各模块的 `Path(__file__).parent` 定位才能命中）。
DATA_FILES: list[tuple[str, str]] = [
    ("rules", "rules"),
    ("cases", "cases"),
    ("_gyu_tool.cs", "."),
    ("_hg3_tool.cs", "."),
    ("_uia_item_rect.ps1", "."),
]


def data_args() -> tuple[list[str], list[str]]:
    """返回 (--add-data 参数列表, 缺失文件列表)。toolbridge.json 可选，缺了不算错。"""
    args: list[str] = []
    missing: list[str] = []
    for src, dst in DATA_FILES:
        p = REPO / src
        if not p.exists():
            missing.append(src)
            continue
        args += ["--add-data", f"{p};{dst}"]
    opt = REPO / "toolbridge.json"
    if opt.exists():
        args += ["--add-data", f"{opt};."]
    return args, missing


def check() -> int:
    args, missing = data_args()
    for a in DATA_FILES:
        mark = "OK " if (REPO / a[0]).exists() else "MISS"
        print(f"[{mark}] {a[0]} -> _internal/{a[1] if a[1] != '.' else ''}")
    if (REPO / "toolbridge.json").exists():
        print("[OK ] toolbridge.json（可选）")
    else:
        print("[opt] toolbridge.json 不存在（可选，缺失走内置候选 + PATH）")
    if missing:
        print("\n缺失：", ", ".join(missing), file=sys.stderr)
        return 1
    print(f"\n清单齐全，--add-data 共 {args.count('--add-data')} 项")
    return 0


def build(no_bundle_tools: bool = False) -> int:
    args, missing = data_args()
    if missing:
        print("数据文件缺失，先补齐再构建：", ", ".join(missing), file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onedir", "--name", "orchestrator",
           "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(SPEC),
           *args, str(REPO / "orchestrator.py")]
    # GUI 壳（--gui）的拖拽增强：tkinterdnd2 带原生 tkdnd 二进制，必须 collect-all；
    # 没装也能构建（gui.py 探测后退化成浏览+粘贴）。
    import importlib.util
    if importlib.util.find_spec("tkinterdnd2") is not None:
        cmd += ["--collect-all", "tkinterdnd2"]
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"PyInstaller 失败 rc={r.returncode}", file=sys.stderr)
        return r.returncode
    if not no_bundle_tools:
        print("\n== 随包外部工具 ==", flush=True)
        for line in bundle_tools(DIST / "orchestrator"):
            print(line, flush=True)
    n = sum(1 for p in DIST.joinpath("orchestrator").rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in DIST.joinpath("orchestrator").rglob("*") if p.is_file())
    print(f"\n产物：{EXE}\n  {n} 个文件，{size / 1024 / 1024:.1f} MiB")
    print("冒烟：", f'"{EXE}" <游戏目录> --out <输出目录> --dry-run')
    return 0


# ---------------------------------------------------------------- 便携包

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def portable() -> int:
    """便携版 zip（**唯一交付形态**，2026-11-04 用户定：不做安装器）。

    为什么放弃安装器：安装器在本机被火绒 + 深信服 EDR 按进程信誉拦截
    （%TEMP%\\is-*.tmp 写不进去，证据见 antivirus-false-positives.md §5），
    而它的价值只有「卸载键 + 开始菜单快捷方式」——对一个私人工具毫无必要。
    便携 zip 解压即用、不写注册表、不碰敏感目录，杀软拦截面小得多。
    """
    if not EXE.is_file():
        print(f"冻结包不存在：{EXE}\n先跑 python build_exe.py", file=sys.stderr)
        return 1
    readme = REPO / "README.md"
    if readme.is_file():
        shutil.copy2(readme, DIST / "orchestrator" / "README.md")
    out = PACKAGING / "Output" / f"GalgameUnpacker-{APP_VERSION}-portable.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["powershell", "-NoProfile", "-Command",
           f"Compress-Archive -Path '{(DIST / 'orchestrator')}' "
           f"-DestinationPath '{out}' -Force"]
    r = subprocess.run(cmd)
    if r.returncode != 0 or not out.is_file():
        print("便携包打包失败", file=sys.stderr)
        return 1
    print(f"便携包：{out}（{out.stat().st_size / 1024 / 1024:.1f} MiB）")
    print(f"  SHA256: {sha256(out)}")
    return 0


# ---------------------------------------------------------------- 外部工具随包

#: 随包外部工具（用户 2026-11-02 要求「所需外部工具一并集成」）。
#: key = toolbridge TOOLS 的 key（解析时找 `bin/<key>/<exe_name>`）；krkrz 不在
#: toolbridge 注册表里（KrkrzExtract 是 KrkrExtract 报 Unknown chunk 时的手动兜底），
#: 照 bin 子目录约定打进去即可。pattern: "*" 整目录；或 glob 列表
#: （ffprobe 是共享构建，只带 exe + av* DLL，不带 ffmpeg.exe/ffplay.exe）。
BUNDLE_TOOLS: list[tuple[str, str, str | list[str]]] = [
    ("garbro", r"D:\K\galgame\GARbro", "*"),
    ("assetstudio", r"D:\K\galgame\unity\AssetStudio", "*"),
    ("tlg2png", r"D:\K\galgame\tlg2png", "*"),
    ("krkr", r"D:\K\galgame\krkr\krkr", "*"),
    ("krkrz", r"D:\K\galgame\krkr\krkrz", "*"),
    ("ffprobe", r"D:\ffmpeg\bin",
     ["ffprobe.exe", "avcodec-*.dll", "avdevice-*.dll", "avfilter-*.dll",
      "avformat-*.dll", "avutil-*.dll", "swresample-*.dll", "swscale-*.dll"]),
]

#: 随包工具的许可证状态（蓝图 §5.2：聚合分发 ≠ 补许可证义务的豁免）。
#: 2026-11-04 逐项核实（证据随条目写清，换构建/换工具时必须重核）：
#:   · 结论来源：上游仓库 README / GitHub API license 字段 / 本机 exe 版本信息 /
#:     `ffprobe -version` 的 configuration 行。
#:   · 「无许可证」= 仓库没有 LICENSE 文件 → 默认保留所有权利，**不能**当它可分发。
TOOL_LICENSES: list[tuple[str, str, str]] = [
    ("garbro", "MIT（已核实：morkt/GARbro）",
     "https://github.com/morkt/GARbro"),
    ("assetstudio", "MIT（上游 Perfare/AssetStudio 为 MIT；本 CLI 分支的具体 fork 未核实）",
     "https://github.com/Perfare/AssetStudio"),
    ("tlg2png", "⚠ 无许可证（已核实：vn-tools/tlg2png 仓库无 LICENSE 文件，"
                "GitHub API license=null，仓库已归档）——默认保留所有权利，"
                "未经权利人许可不得随包对外分发；自用不受此限",
     "https://github.com/vn-tools/tlg2png"),
    ("krkr", "GPL-3.0（已核实：xmoezzz/KrkrExtract，README 明示全部源码 GPLv3；"
             "本目录 KrkrExtract.Lite.exe 版本信息 Copyright © 2020 对应其 lite 分支）。"
             "对外分发须随包提供对应源码或书面报价，并附 GPL-3.0 全文",
     "https://github.com/xmoezzz/KrkrExtract"),
    ("krkrz", "GPL-3.0（已核实：xmoezzz/KrkrzExtract，GitHub license=GPL-3.0；"
              "本目录 KrkrzExtract.exe 版本信息 Copyright X'moe (C) 2018 v1.0.0.0 对应其 release）。"
              "对外分发须随包提供对应源码或书面报价，并附 GPL-3.0 全文",
     "https://github.com/xmoezzz/KrkrzExtract"),
    ("ffprobe", "GPL-3.0-or-later（已核实：本机构建 `ffprobe -version` 的 configuration "
                "含 --enable-gpl --enable-version3，BtbN/FFmpeg-Builds 风格）。"
                "对外分发须随包提供对应源码或书面报价（蓝图 §5.2）",
     "https://ffmpeg.org"),
]


def _write_tool_notice(bin_root: Path) -> None:
    lines = ["随包外部工具清单与许可证状态（生成于 build_exe.py，勿手改）", ""]
    for key, lic, url in TOOL_LICENSES:
        lines.append(f"* {key}")
        lines.append(f"    许可证: {lic}")
        if url:
            lines.append(f"    上游:   {url}")
    lines += [
        "",
        "分发前必须处理（2026-11-04 逐项核实后的结论）:",
        "  * krkr / krkrz / ffprobe 是 GPL-3.0 组件：对外分发时必须随包提供对应源码",
        "    （或书面报价）、GPL-3.0 全文与版权声明。",
        "  * tlg2png 上游仓库无许可证（默认保留所有权利）：对外分发前必须换掉",
        "    （例如改用 GARbro 的 TLG 转换或自研解码器），否则属于未经授权分发。",
        "  * 工具本体不修改、以独立进程调用（toolbridge argv 数组）——聚合而非衍生；",
        "    但这**不豁免**各工具自身的许可证义务。",
        "  * 当前定位是个人自用，未对外分发。",
    ]
    (bin_root / "NOTICE.txt").write_text("\n".join(lines), encoding="utf-8")


def bundle_tools(dest_root: Path, entries: list[tuple[str, str, str | list[str]]] | None = None) -> list[str]:
    """把外部工具拷进 `<dest_root>/bin/<key>/`，返回报告行。

    缺来源**只警告不失败**——软件对缺失工具会如实报错（toolbridge 解析落到下一档），
    不该让「打包机上少个工具」把整个构建炸掉。
    """
    reports: list[str] = []
    bin_root = dest_root / "bin"
    bin_root.mkdir(parents=True, exist_ok=True)
    for key, src, pattern in (entries if entries is not None else BUNDLE_TOOLS):
        s = Path(os.path.expandvars(src))
        if not s.is_dir():
            reports.append(f"[SKIP] {key}: 来源不存在 {s}")
            continue
        dst = bin_root / key
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        if pattern == "*":
            for p in s.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(s)
                    (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dst / rel)
                    n += 1
        else:
            for pat in pattern:
                for p in s.glob(pat):
                    shutil.copy2(p, dst / p.name)
                    n += 1
        if key == "garbro":
            config = dst / "GARbro.Console.exe.config"
            if config.is_file():
                from xml.dom import minidom

                doc = minidom.parse(str(config))
                root = doc.documentElement
                runtimes = root.getElementsByTagName("runtime")
                runtime = runtimes[0] if runtimes else doc.createElement("runtime")
                if not runtimes:
                    root.appendChild(runtime)
                settings = runtime.getElementsByTagName("loadFromRemoteSources")
                setting = settings[0] if settings else doc.createElement("loadFromRemoteSources")
                if not settings:
                    runtime.appendChild(setting)
                setting.setAttribute("enabled", "true")
                config.write_bytes(doc.toxml(encoding="utf-8"))
        size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
        reports.append(f"[OK]   {key}: {n} 个文件，{size / 1048576:.1f} MiB ← {s}")
    _write_tool_notice(bin_root)
    return reports


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只校验清单，不构建")
    ap.add_argument("--portable", action="store_true",
                    help="跳过冻结构建，用现有 dist 重新出便携 zip")
    ap.add_argument("--no-bundle-tools", action="store_true",
                    help="跳过外部工具随包（默认按 BUNDLE_TOOLS 尽力打包，缺来源只警告）")
    a = ap.parse_args(argv)
    if a.check:
        return check()
    if a.portable:
        return portable()
    # 默认 = 冻结 + 便携 zip：2026-11-04 用户定「只保留便携版」，安装器已删除。
    rc = build(no_bundle_tools=a.no_bundle_tools)
    if rc != 0:
        return rc
    return portable()


if __name__ == "__main__":
    sys.exit(main())
