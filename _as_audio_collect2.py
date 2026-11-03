#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 AssetStudio.CLI 导不全的 AudioClip 收全（按名字对账 + 只补跑缺的）。

背景（实测 2026-10-12 / 2026-11-02，详见 verified-findings.md §8）:
  本类作品的音频是 FSB5(FMOD Sample Bank 5) 容器，数据在外置 resources.resource 里。
  AssetStudio.CLI 一次导出 1441 个 AudioClip 时**只落盘一部分**，且：
    - 逐条日志照打 "Exporting AudioClip: X"，**没有任何报错**；
    - 退出码仍然是 **0**（不是崩溃，除非批量极大时偶发 access violation）。
  → 退出码与日志都不能当成功判据，只有「按名字数产物」能。

  同一批名字重复跑，每次落盘的子集**不同**（实测同样 80 个名字：一次 80/80，一次 28/80），
  所以「跑一次 + 把缺的再跑一遍」能收敛。**单名导出实测稳定成功**。

策略（2026-11-02 重写，替代「盲目前缀分组多轮」）:
  ① 先用 JSON 枚举拿到**全部 AudioClip 名字**（地面真相，`--group_assets BySource`
     避免同名 JSON 互相覆盖）；
  ② 把名字按批（默认 50）用 `--names "^(a|b|c)$"` 导出，落盘后**逐个名字核对**；
  ③ 只把缺的名字收进下一轮，批量逐轮减半，直到补齐或轮数用尽；
  ④ 缺的照样报出来（`missing`），不静默放过——对账在 orchestrator 侧仍会 diff≠0。

  拿不到名字清单时（JSON 枚举失败/为空）退回旧的 `rounds()` 前缀分组逻辑。

用法:
  python _as_audio_collect2.py <输入目录> <累积输出目录> [--names-file FILE]
"""
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import toolbridge

#: 本次进程内开过的临时目录序号（见 `_fresh()`）。
_SEQ = itertools.count(1)

VOICE_PREFIXES = ["VA", "VB", "VC", "FE", "SEX", "ADD", "SE", "bgm", "SYASEI",
                  "sexyvoice", "ding", "punch", "camera", "door", "cross", "sex"]

# 单次 `--names` 的批量。实测 50 名一批时补跑 1~2 轮即可补齐 200 名（35s）；
# 再大并不会更快（丢失比例随批量上升），再小则进程启动开销占主导。
BATCH = 50
MAX_ROUNDS = 5
TIMEOUT = 900


def rounds() -> list[tuple[str, list[str]]]:
    """无名字清单时的兜底：前缀分组多轮（旧策略，覆盖不全但总能捞到东西）。"""
    out: list[tuple[str, list[str]]] = []

    r1 = []
    for p in VOICE_PREFIXES:
        alts = "|".join(f"{p}{d}" for d in "0123456789")
        r1.append(f"^({alts})")
    r1.append(r"^[0-9]")
    for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
        r1.append(f"^{c}")
    out.append(("round1", r1))

    r2 = []
    for p in ("VA", "VB", "VC"):
        pairs = [f"{p}{a}{b}" for a in "0123456789" for b in "0123456789"]
        for i in range(0, len(pairs), 2):
            alts = "|".join(pairs[i:i + 2])
            r2.append(f"^({alts})")
    r2.extend(f"^{a}" for a in "0123456789")
    out.append(("round2", r2))

    r3 = []
    for p in ("VA", "VB", "VC"):
        for a in "0123456789":
            for b in "0123456789":
                r3.append(f"^{p}{a}{b}")
    r3.extend(f"^{a}{b}" for a in "0123456789" for b in "0123456789")
    out.append(("round3", r3))
    return out


def digest(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _drop(p: Path) -> None:
    """尽力清理临时目录；删不掉就留着（清理不能成为失败原因）。

    实现走 `toolbridge.drop_tree`（唯一出处）：它吞 BaseException 系（删除守卫拦
    `ignore_errors=True` 是拦不住的）并返回是否真删干净；这里的清理是优化，
    删不掉只提醒，不阻断解包。
    """
    if not toolbridge.drop_tree(p):
        print(f"[WARN] 临时目录删不掉，已留着: {p}", file=sys.stderr)


def _fresh(root: Path, name: str) -> Path:
    """本次专用临时目录（唯一名）——残留的旧 JSON 会把计数算虚高，唯一名可免疫。"""
    d = root / f"{name}_{os.getpid()}_{next(_SEQ)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enumerate_names(src: Path, exe: Path, work: Path) -> list[str] | None:
    """JSON 枚举 AudioClip 的名字（地面真相）。**失败返回 None**，成功返回名字列表。

    `--group_assets BySource`：每个 CAB 一个子目录，避免同名资产在 JSON 阶段就互相覆盖
    （ByType 时同名 JSON 会覆盖，等于把「同名多条」错当成一条）。

    为什么失败返回 None 而不是 `[]`（批次 C11，2026-11-03）：空列表的意思是
    「这个游戏确实没有音频」，调用方会据此把 expected 算成 0、对账 0 差、验收 0 失败
    ——**全绿**。而超时/工具没起来根本不代表没有音频，那是最典型的「无声的绿」。
    所以两种结局必须用两种值区分，让调用方有机会判失败。
    """
    tmp = _fresh(Path(work), "_names")
    try:
        subprocess.run(
            [str(exe), str(src), str(tmp), "--game", "Normal",
             "--types", "AudioClip", "--export_type", "JSON",
             "--group_assets", "BySource"],
            capture_output=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[WARN] 音频名字枚举失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        _drop(tmp)
        return None

    names: list[str] = []
    for p in tmp.rglob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = d.get("m_Name")
        if name:
            names.append(name)
    _drop(tmp)
    return names


def _name_pattern(names: list[str]) -> str:
    """把一批名字编成一条锚定正则（锚定很关键：前缀匹配会重复导出、批量失真）。"""
    import re
    return "^(" + "|".join(re.escape(n) for n in names) + ")$"


def _export(exe: Path, src: Path, tmp: Path, pattern: str,
            export_type: str = "Convert") -> int:
    """跑一次 AssetStudio 导出。返回退出码（**只作诊断，不当成功判据**）。"""
    _drop(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [str(exe), str(src), str(tmp), "--game", "Normal",
             "--types", "AudioClip", "--names", pattern,
             "--export_type", export_type, "--group_assets", "ByType"],
            capture_output=True, timeout=TIMEOUT)
        return proc.returncode
    except subprocess.TimeoutExpired:
        return -1


def _merge(dest: Path, tmp: Path) -> int:
    """把 tmp 里的 wav 搬进 dest。同名不同内容 = 真冲突，直接报错（不许静默覆盖）。"""
    moved = 0
    for w in list(tmp.rglob("*.wav")):
        tgt = dest / w.name
        if tgt.exists():
            if digest(tgt) == digest(w):
                continue                      # 同一份内容，重复导出，跳过
            raise ValueError(f"AudioClip filename conflict: {w.name}")
        shutil.move(str(w), str(tgt))
        moved += 1
    return moved


def collect(src: Path, dest: Path, names: list[str], exe: Path | None = None,
            batch: int = BATCH, max_rounds: int = MAX_ROUNDS, log=print,
            work_root: Path | None = None) -> dict:
    """按名字对账收音频。返回 {expected, unique, collected, missing, runs}。

    work_root: 临时目录放哪。**默认 dest.parent**（= raw/）能用但会污染交付目录
    （清理失败时残留的 wav 会被对账数进去），orchestrator 一律显式传 `_work/`。
    """
    exe = exe or toolbridge.find_tool("assetstudio")
    dest.mkdir(parents=True, exist_ok=True)

    unique = sorted(set(names))
    have = {p.stem for p in dest.glob("*.wav")}
    pending = [n for n in unique if n not in have]
    log(f"音频对账：枚举 {len(names)} 条（唯一名 {len(unique)}），已落盘 {len(have)}，"
        f"待补 {len(pending)}")

    root = Path(work_root) if work_root is not None else dest.parent
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=dest.name + "_work_", dir=root))
    runs = 0
    try:
        cur_batch = batch
        for rnd in range(1, max_rounds + 1):
            if not pending:
                break
            log(f"第 {rnd} 轮：待补 {len(pending)}，批量 {cur_batch}")
            gained = 0
            for i in range(0, len(pending), cur_batch):
                chunk = pending[i:i + cur_batch]
                runs += 1
                rc = _export(exe, src, work / "cur", _name_pattern(chunk))
                added = _merge(dest, work / "cur")
                gained += added
                if added < len(chunk):
                    log(f"  [{i + len(chunk)}/{len(pending)}] rc={rc} "
                        f"+{added}/{len(chunk)} 缺 {len(chunk) - added}")
            have = {p.stem for p in dest.glob("*.wav")}
            pending = [n for n in unique if n not in have]
            log(f"  本轮 +{gained}，累计 {len(have)}，仍缺 {len(pending)}")
            cur_batch = max(1, cur_batch // 2)
    finally:
        _drop(work)

    have = {p.stem for p in dest.glob("*.wav")}
    missing = [n for n in unique if n not in have]
    total = list(dest.glob("*.wav"))
    mb = sum(p.stat().st_size for p in total) / 1024 / 1024
    log(f"完成: {len(total)} 个 wav, {mb:.1f} MB -> {dest}；runs={runs}，"
        f"枚举 {len(names)} / 唯一 {len(unique)} / 缺 {len(missing)}")
    if missing:
        log(f"仍缺（前 10）：{missing[:10]}")
    return {"expected": len(names), "unique": len(unique),
            "collected": len(total), "missing": missing, "runs": runs}


def _collect_by_rounds(src: Path, dest: Path, exe: Path, log=print,
                       work_root: Path | None = None) -> None:
    """兜底：拿不到名字清单时按前缀分组多轮累积（旧策略）。"""
    seen = {(p.name.casefold(), digest(p)) for p in dest.rglob("*.wav")}
    log(f"无名字清单，退回前缀分组：起始已累积 {len(seen)}")
    root = Path(work_root) if work_root is not None else dest.parent
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=dest.name + "_work_", dir=root))
    try:
        for rname, pats in rounds():
            log(f"=== {rname}: {len(pats)} 个模式 ===")
            gained_total = 0
            for i, pat in enumerate(pats, 1):
                rc = _export(exe, src, work / "cur", pat)
                added = 0
                for w in list((work / "cur").rglob("*.wav")):
                    key = (w.name.casefold(), digest(w))
                    if key in seen:
                        continue
                    tgt = dest / w.name
                    if tgt.exists():
                        raise ValueError(f"AudioClip filename conflict: {w.name}")
                    shutil.move(str(w), str(tgt))
                    seen.add(key)
                    added += 1
                gained_total += added
                if added:
                    log(f"  [{i}/{len(pats)}] +{added:<4} 累计={len(seen)}   {pat[:46]}")
            log(f"  {rname} 共新增 {gained_total}，累计 {len(seen)}")
    finally:
        _drop(work)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    names_file = None
    if "--names-file" in argv:
        k = argv.index("--names-file")
        names_file = Path(argv[k + 1])
        del argv[k:k + 2]
    work_root = None
    if "--work-dir" in argv:
        k = argv.index("--work-dir")
        work_root = Path(argv[k + 1])
        work_root.mkdir(parents=True, exist_ok=True)
        del argv[k:k + 2]
    if len(argv) < 2:
        print("用法: _as_audio_collect2.py <输入目录> <累积输出目录>"
              " [--names-file FILE] [--work-dir DIR]", flush=True)
        return 2
    src, dest = Path(argv[0]), Path(argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    exe = toolbridge.find_tool("assetstudio")
    root = work_root or dest.parent
    root.mkdir(parents=True, exist_ok=True)

    if names_file is not None:
        names = [n for n in names_file.read_text(encoding="utf-8").splitlines() if n]
        enum_failed = False
    else:
        work = Path(tempfile.mkdtemp(prefix=dest.name + "_enum_", dir=root))
        try:
            names = enumerate_names(src, exe, work)
        finally:
            _drop(work)
        # None = 枚举失败（超时/工具没起来），**不等于**「这作没有音频」。
        # 退化到旧的按前缀分组仍能收一部分，但必须把「地面真相未知」说出口。
        enum_failed = names is None
        names = names or []

    if enum_failed:
        print("[WARN] 音频名字枚举失败：无法按名字对账，退回前缀分组建模"
              "（覆盖不全，请核对 missing）", file=sys.stderr)
    if names:
        collect(src, dest, names, exe, work_root=root)
    else:
        _collect_by_rounds(src, dest, exe, work_root=root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
