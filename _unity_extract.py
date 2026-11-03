#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unity AssetStudio 导出：JSON 枚举（地面真相）+ Convert 导出。

用法: python _unity_extract.py <data_dir> <out_dir> [--manifest PATH]

三种类型分批导出（坑 4：--types 不能用逗号分隔，单类型才有效）：
  Texture2D → Image_Texture2D/  (PNG)
  Sprite    → Image_Sprite/     (PNG)
  AudioClip → Audio/            (WAV)

地面真相 = AssetStudio JSON 枚举的计数（唯一出处）。
Convert 导出数对账都走 expected_counts()，别另写一份。

AudioClip 若是 FSB5 容器，单次 Convert 只能导出约 30%，
需要多轮 --names 分组累积（复用 _as_audio_collect2.py 的思路）。
"""
import importlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import toolbridge as tb   # 只借 `drop_tree`（「尽力清理」的唯一实现，见 toolbridge 注释）

UNITY_TYPES = ("Texture2D", "Sprite", "AudioClip")
UNITY_CATEGORIES = {
    "Texture2D": "Image_Texture2D",
    "Sprite": "Image_Sprite",
    "AudioClip": "Audio",
}

#: 本次进程内开过的临时目录序号（见 `_fresh()`）。
_SEQ = itertools.count(1)


def _as_exe() -> Path:
    """AssetStudio.CLI 路径（可用环境变量 TOOLBRIDGE_ASSETSTUDIO 覆盖）。"""
    import os
    env = os.environ.get("TOOLBRIDGE_ASSETSTUDIO")
    if env:
        return Path(env)
    return Path(r"D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe")


def _run_as(data_dir: Path, tmp: Path, type_name: str, export_type: str,
            as_exe: Path | None = None) -> subprocess.CompletedProcess:
    """跑一次 AssetStudio 导出。"""
    as_exe = as_exe or _as_exe()
    cmd = [str(as_exe), str(data_dir), str(tmp),
           "--game", "Normal", "--types", type_name,
           "--export_type", export_type, "--group_assets", "ByType"]
    return subprocess.run(cmd, capture_output=True, timeout=1800)


def _run_audio_collect(script: Path, data_dir: Path, audio_dir: Path) -> int:
    """in-process 调用 `_as_audio_collect2.py`（它已是 `main(argv)->int` 形态，§19.2）。

    原来走 `subprocess.run([sys.executable, script, ...])`：冻结包里 sys.executable 是
    orchestrator.exe，等于拿未知参数重启自身（§19.2 第 1 条禁的就是这个）。
    """
    try:
        try:
            mod = importlib.import_module("_as_audio_collect2")   # orchestrator 已静态 import
        except ImportError:
            spec = importlib.util.spec_from_file_location("_as_audio_collect2", script)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["_as_audio_collect2"] = mod
            spec.loader.exec_module(mod)
        return int(mod.main([str(data_dir), str(audio_dir)]))
    except Exception as exc:                                       # noqa: BLE001
        print(f"[WARN] _as_audio_collect2 in-process 失败：{type(exc).__name__}: {exc}",
              flush=True)
        return 1


def _scratch_root(tmp_root: Path | None, default: Path) -> Path:
    """临时目录根：**绝不能落在游戏目录里**（2026-11-02 Happiness Double Room 实测）。

    原实现把 `_json_<T>` 建在 `data_dir.parent`（= 游戏根目录），遇到只读/受保护的游戏目录
    直接 `PermissionError: [WinError 5]`，Unity 链路在「数 JSON」这一步就崩，
    与 AssetStudio / Unity 版本无关。调用方显式传 `ctx.work_dir` 下的子目录；
    裸调用退到 `default`。
    """
    return Path(tmp_root) if tmp_root is not None else Path(default)


def _fresh(root: Path, name: str) -> Path:
    """在 root 下开一个**本次专用**的临时目录（唯一名）。

    为什么不复用固定名 + 先删后建：一是删除守卫（本机 >50 个文件的批量删除要人工确认，
    agent 会话里会直接中断整条链），二是残留的旧 JSON 会把「数 JSON」这一步算虚高
    ——**计数错误比不计数更坏**。唯一名让「上一轮的残留」天然不影响本轮。
    """
    d = root / f"{name}_{os.getpid()}_{next(_SEQ)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _drop(p: Path) -> None:
    """尽力删除临时目录；删不掉就留着（**不能**因为删不掉而中断解包）。

    实现走 `toolbridge.drop_tree`（唯一出处，批次 B3）：它吞 BaseException 系
    （删除守卫抛的不是 Exception，`ignore_errors=True` 拦不住）并返回是否真的删干净。
    这里的清理是优化不是正确性的一部分，所以删不掉只记一笔，不改变流程。
    """
    if not tb.drop_tree(p):
        print(f"[WARN] 临时目录删不掉，已留着: {p}", file=sys.stderr)


def expected_counts(data_dir: Path, as_exe: Path | None = None,
                    tmp_root: Path | None = None) -> dict:
    """AssetStudio JSON 枚举 = 地面真相（唯一出处）。

    每种类型跑一次 JSON 导出，数 JSON 文件数。
    返回 {'by_type': {type: count}, 'total': sum, 'unlistable': [], 'types': [...]}

    tmp_root: 临时目录**根**（裸调用默认系统 temp）。绝不写游戏目录——见 `_scratch_root()`。
    """
    as_exe = as_exe or _as_exe()
    root = _scratch_root(tmp_root, Path(tempfile.gettempdir()) / "unity_extract_json")
    root.mkdir(parents=True, exist_ok=True)
    by_type = {}
    for t in UNITY_TYPES:
        tmp = _fresh(root, f"_json_{t}")
        _run_as(data_dir, tmp, t, "JSON", as_exe)
        by_type[t] = len(list(tmp.rglob("*.json")))
        _drop(tmp)
    return {
        "by_type": by_type,
        "total": sum(by_type.values()),
        "unlistable": [],
        "types": list(UNITY_TYPES),
    }


def extract_all(data_dir: Path, out_dir: Path, as_exe: Path | None = None,
                tmp_root: Path | None = None) -> dict:
    """Convert 导出 + 复制到 out_dir/<category>/。

    返回 {'by_type': {type: count}, 'total': sum, 'archives': [...]}

    tmp_root: 临时目录**根**（裸调用默认 `<out_dir>/../_scratch`：输出侧、不在游戏目录，
    也**不在 out_dir（raw/）里**——否则会被对账当成产物数进去）。
    """
    as_exe = as_exe or _as_exe()
    root = _scratch_root(tmp_root, out_dir.parent / "_scratch")
    root.mkdir(parents=True, exist_ok=True)
    by_type = {}
    archives = []
    for t in UNITY_TYPES:
        cat = UNITY_CATEGORIES[t]
        tmp = _fresh(root, f"_conv_{t}")
        _run_as(data_dir, tmp, t, "Convert", as_exe)
        # AssetStudio 产物在 <tmp>/<TypeName>/
        subs = [p for p in tmp.iterdir() if p.is_dir()]
        src = subs[0] if subs else tmp
        dst = out_dir / cat
        moved = False
        if not dst.exists():
            # 直接改名：省一次全量复制（本样本产物 2 GB），也不产生批量删除。
            # 只在目标**不存在**时改名；目标已存在（断点续跑）必须走合并，否则本轮的
            # 新产物会被后面的清理当临时文件删掉。
            try:
                os.replace(src, dst)
                moved = True
            except OSError:
                pass
        if not moved:
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.rglob("*"):
                if f.is_file():
                    tgt = dst / f.relative_to(src).name
                    if not tgt.exists():
                        shutil.copy2(f, tgt)
        n = sum(1 for f in dst.rglob("*") if f.is_file())
        by_type[t] = n
        archives.append({"name": t, "entries": n})
        _drop(tmp)
    return {"by_type": by_type, "total": sum(by_type.values()), "archives": archives}


def write_manifest(out_dir: Path, exp: dict, got: dict,
                   main_key: str | None = None, path: Path | None = None) -> dict:
    """写 manifest。"""
    import manifest as mf
    counts_block = mf.counts_flat(out_dir)
    reconcile_block = mf.reconcile(exp["total"], counts_block["raw"]["total"])
    source = {
        "data_dir": str(out_dir),
        "archives": got.get("archives", []),
        "json_counts": exp.get("by_type", {}),
    }
    if main_key:
        source["unity_version"] = main_key
    man = mf.build(
        tool="_unity_extract.py",
        engine="Unity",
        source=source,
        counts_block=counts_block,
        reconcile_block=reconcile_block,
        verify={"verified": False,
                "note": "本工具只做 AssetStudio 导出，不做内容级验收；请用 orchestrator.py 或 _verify_media.py"},
        postprocess=[],
        extra={"fail_count": 0, "fails": []},
    )
    if path:
        mf.write(path, man)
    return man


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) < 2:
        print("用法: python _unity_extract.py <data_dir> <out_dir> [--manifest PATH]")
        return 2
    data_dir = Path(argv[0])
    out_dir = Path(argv[1])
    man_path = None
    if "--manifest" in argv:
        idx = argv.index("--manifest")
        if idx + 1 < len(argv):
            man_path = Path(argv[idx + 1])
        else:
            print("[ERROR] --manifest 需要一个路径参数", file=sys.stderr)
            return 2

    as_exe = _as_exe()
    if not as_exe.exists():
        print(f"[ERROR] 找不到 AssetStudio.CLI: {as_exe}", file=sys.stderr)
        return 1

    print(f"AssetStudio: {as_exe}", flush=True)
    exp = expected_counts(data_dir, as_exe)
    print(f"JSON 枚举：{sum(exp['by_type'].values())} 个资产", flush=True)
    for t, n in exp["by_type"].items():
        print(f"  {t}: {n}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    got = extract_all(data_dir, out_dir, as_exe)
    print(f"\nConvert 导出：{got['total']} 个文件", flush=True)
    for t, n in got["by_type"].items():
        print(f"  {t}: {n}", flush=True)

    # Audio multi-round
    audio_got = got["by_type"].get("AudioClip", 0)
    audio_exp = exp["by_type"].get("AudioClip", 0)
    if audio_exp > 0 and audio_got < audio_exp * 0.5:
        print(f"\n[音频] 单次导出 {audio_got}/{audio_exp}（<50%），跑多轮分组累积...", flush=True)
        audio_dir = out_dir / "Audio"
        script = Path(__file__).parent / "_as_audio_collect2.py"
        if script.exists():
            # in-process：冻结包里 sys.executable = orchestrator.exe（§19.2）
            rc = _run_audio_collect(script, data_dir, audio_dir)
            if rc == 0:
                audio_files = list(audio_dir.rglob("*.wav"))
                got["by_type"]["AudioClip"] = len(audio_files)
                got["total"] = sum(got["by_type"].values())
                print(f"[音频] 多轮累积后：{len(audio_files)} 个 wav", flush=True)
            else:
                print(f"[WARN] _as_audio_collect2.py 失败（rc={rc}）", flush=True)

    total_ok = got["total"]
    total_fail = 0
    if exp["total"] != total_ok:
        total_fail += 1
    print(f"\n合计 ok {total_ok} fail {total_fail}", flush=True)
    print(f"对账：期望 {exp['total']} vs 落盘 {total_ok} (diff={total_ok - exp['total']})", flush=True)

    if man_path:
        try:
            write_manifest(out_dir, exp, got, path=man_path)
            print(f"manifest 写入: {man_path}", flush=True)
        except Exception as exc:
            print(f"[WARN] manifest 写入失败（产物不受影响）：{exc}", file=sys.stderr)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
