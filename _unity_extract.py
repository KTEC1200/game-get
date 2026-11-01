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
import json
import shutil
import subprocess
import sys
from pathlib import Path

UNITY_TYPES = ("Texture2D", "Sprite", "AudioClip")
UNITY_CATEGORIES = {
    "Texture2D": "Image_Texture2D",
    "Sprite": "Image_Sprite",
    "AudioClip": "Audio",
}


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


def expected_counts(data_dir: Path, as_exe: Path | None = None) -> dict:
    """AssetStudio JSON 枚举 = 地面真相（唯一出处）。

    每种类型跑一次 JSON 导出，数 JSON 文件数。
    返回 {'by_type': {type: count}, 'total': sum, 'unlistable': [], 'types': [...]}
    """
    as_exe = as_exe or _as_exe()
    by_type = {}
    for t in UNITY_TYPES:
        tmp = data_dir.parent / f"_json_{t}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        proc = _run_as(data_dir, tmp, t, "JSON", as_exe)
        by_type[t] = len(list(tmp.rglob("*.json")))
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "by_type": by_type,
        "total": sum(by_type.values()),
        "unlistable": [],
        "types": list(UNITY_TYPES),
    }


def extract_all(data_dir: Path, out_dir: Path, as_exe: Path | None = None) -> dict:
    """Convert 导出 + 复制到 out_dir/<category>/。

    返回 {'by_type': {type: count}, 'total': sum, 'archives': [...]}
    """
    as_exe = as_exe or _as_exe()
    by_type = {}
    archives = []
    for t in UNITY_TYPES:
        cat = UNITY_CATEGORIES[t]
        tmp = out_dir.parent / f"_conv_{t}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        proc = _run_as(data_dir, tmp, t, "Convert", as_exe)
        # AssetStudio 产物在 <tmp>/<TypeName>/
        subs = [p for p in tmp.iterdir() if p.is_dir()]
        src = subs[0] if subs else tmp
        dst = out_dir / cat
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in src.rglob("*"):
            if f.is_file():
                shutil.copy2(f, dst / f.relative_to(src).name)
                n += 1
        by_type[t] = n
        archives.append({"name": t, "entries": n})
        shutil.rmtree(tmp, ignore_errors=True)
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
            proc = subprocess.run(
                [sys.executable, str(script), str(data_dir), str(audio_dir)],
                capture_output=True, timeout=3600)
            if proc.returncode == 0:
                audio_files = list(audio_dir.rglob("*.wav"))
                got["by_type"]["AudioClip"] = len(audio_files)
                got["total"] = sum(got["by_type"].values())
                print(f"[音频] 多轮累积后：{len(audio_files)} 个 wav", flush=True)
            else:
                print(f"[WARN] _as_audio_collect2.py 失败（rc={proc.returncode}）", flush=True)

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
