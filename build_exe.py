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
  python build_exe.py                 # 构建 → _spike_pkg/dist/orchestrator/orchestrator.exe
  python build_exe.py --check         # 只校验清单文件是否齐全，不构建
  python build_exe.py --installer     # 冻结 + Inno Setup 单文件安装包（packaging/installer.iss）
  python build_exe.py --installer-only  # 跳过冻结，用现有 dist 出安装包
  python build_exe.py --installer-only --testmode  # Uninstallable=no 的会话内验证构建
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

#: 应用版本号 —— 安装器文件名与 /DVERSION 都从这里来（软件还没有 GUI/关于页，
#: 等要展示版本的地方多了再挪进独立 VERSION 文件）。
APP_VERSION = "0.1.0"

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


# ---------------------------------------------------------------- 安装器

#: Inno Setup 编译器的候选安装位（winget 用户级装 %LocalAppData%\Programs，机器级装
#: Program Files；6/7 两个主版本都收）。覆盖顺序与 toolbridge 同构：env → 内置候选 → PATH。
ISCC_CANDIDATES = [
    r"%LocalAppData%\Programs\Inno Setup 6\ISCC.exe",
    r"%LocalAppData%\Programs\Inno Setup 7\ISCC.exe",
    r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe",
    r"%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe",
    r"%ProgramFiles%\Inno Setup 6\ISCC.exe",
    r"%ProgramFiles%\Inno Setup 7\ISCC.exe",
]


def find_iscc() -> Path | None:
    env = os.environ.get("TOOLBRIDGE_ISCC")
    if env and Path(env).is_file():
        return Path(env)
    for cand in ISCC_CANDIDATES:
        p = Path(os.path.expandvars(cand))
        if p.is_file():
            return p
    which = shutil.which("ISCC")
    return Path(which) if which else None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def installer(skip_build: bool = False, testmode: bool = False) -> int:
    """冻结 + Inno Setup 单文件安装包（蓝图 §4.2：单文件安装需求交给安装器满足）。

    testmode：出 `Uninstallable=no` 的验证构建（配 /NOICONS）——自动化会话对未知
    镜像过滤敏感面写入（卸载键/开始菜单），这两步在会话里装不完；见 installer.iss 注释。
    """
    if not skip_build:
        rc = build()
        if rc != 0:
            return rc
    iscc = find_iscc()
    if iscc is None:
        print("找不到 Inno Setup 编译器（ISCC.exe）。", file=sys.stderr)
        print("  装法：winget install JRSoftware.InnoSetup", file=sys.stderr)
        print("  或设环境变量 TOOLBRIDGE_ISCC 指向 ISCC.exe", file=sys.stderr)
        return 1
    out_dir = PACKAGING / "Output"
    tag = "-testmode" if testmode else ""
    cmd = [str(iscc), f"/DVERSION={APP_VERSION}", f"/DDIST={DIST / 'orchestrator'}"]
    if testmode:
        cmd.append("/DTESTMODE=yes")
    cmd += [f"/O{out_dir}",
            f"/FGalgameUnpacker-{APP_VERSION}{tag}-setup",
            str(PACKAGING / "installer.iss")]
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"ISCC 失败 rc={r.returncode}", file=sys.stderr)
        return r.returncode
    setup = out_dir / f"GalgameUnpacker-{APP_VERSION}{tag}-setup.exe"
    if not setup.is_file():
        print(f"ISCC 成功但没找到安装包：{setup}", file=sys.stderr)
        return 1
    print(f"\n安装包：{setup}（{setup.stat().st_size / 1024 / 1024:.1f} MiB）")
    print(f"  SHA256: {sha256(setup)}")
    return 0


def portable() -> int:
    """便携版 zip（杀软文档 §3 备用渠道）：dist 整目录 + README，不碰安装器的敏感写入。"""
    if not EXE.is_file():
        print(f"冻结包不存在：{EXE}\n先跑 python build_exe.py", file=sys.stderr)
        return 1
    readme = REPO / "README.md"
    if readme.is_file():
        shutil.copy2(readme, DIST / "orchestrator" / "README.md")
    out = PACKAGING / "Output" / f"GalgameUnpacker-{APP_VERSION}-portable.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    base = DIST.parent                                   # zip 里顶层是 orchestrator/
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
#: 「蓝图已核实」= galgame-ai-unpack-workflow-plan.md §3 的核对结论；
#: 「未核实」= 别在对外分发前当它是有许可证的。
TOOL_LICENSES: list[tuple[str, str, str]] = [
    ("garbro", "MIT（蓝图已核实：morkt/GARbro）",
     "https://github.com/morkt/GARbro"),
    ("assetstudio", "MIT（上游 Perfare/AssetStudio 为 MIT；本 CLI 分支的具体 fork 未核实）",
     "https://github.com/Perfare/AssetStudio"),
    ("tlg2png", "未核实（分发前必须补）", ""),
    ("krkr", "未核实（KrkrExtract，分发前必须补）", ""),
    ("krkrz", "未核实（KrkrzExtract，分发前必须补）", ""),
    ("ffprobe", "LGPL/GPL 视构建配置而定，本共享构建未核实；GPL 构建对外分发须提供对应源码（蓝图 §5.2）",
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
        "注意:",
        "  * 当前定位是个人自用，暂未对外分发；一旦对外分发，必须把每个工具的",
        "    许可证全文放进本目录，并履行 GPL 组件（如 ffprobe GPL 构建）的源码义务。",
        "  * 工具本体不修改、以独立进程调用（toolbridge argv 数组）——聚合而非衍生。",
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
        size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
        reports.append(f"[OK]   {key}: {n} 个文件，{size / 1048576:.1f} MiB ← {s}")
    _write_tool_notice(bin_root)
    return reports


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只校验清单，不构建")
    ap.add_argument("--installer", action="store_true",
                    help="构建后跑 Inno Setup 出单文件安装包（需 ISCC）")
    ap.add_argument("--installer-only", action="store_true",
                    help="跳过冻结构建，直接用现有 dist 出安装包")
    ap.add_argument("--testmode", action="store_true",
                    help="配合 --installer：出 Uninstallable=no 的会话内验证构建")
    ap.add_argument("--portable", action="store_true",
                    help="出便携版 zip（现有 dist + README；杀软拦安装器时的备用渠道）")
    ap.add_argument("--no-bundle-tools", action="store_true",
                    help="跳过外部工具随包（默认按 BUNDLE_TOOLS 尽力打包，缺来源只警告）")
    a = ap.parse_args(argv)
    if a.check:
        return check()
    if a.portable:
        return portable()
    if a.installer_only:
        return installer(skip_build=True, testmode=a.testmode)
    if a.installer:
        return installer(testmode=a.testmode)
    return build(no_bundle_tools=a.no_bundle_tools)


if __name__ == "__main__":
    sys.exit(main())
