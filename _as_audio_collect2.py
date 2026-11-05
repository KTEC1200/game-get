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

策略（2026-11-02 重写，替代「盲目前缀分组多轮」；2026-11-06 按实测提速）:
  ① 先用 JSON 枚举拿到**全部 AudioClip 名字**（地面真相，`--group_assets BySource`
     避免同名 JSON 互相覆盖）；
  ② 把待补名字按 ≤400 名/片（实测安全点，见下）用 `--names "^(a|b|c)$"` 导出，
     落盘后**逐个名字核对**；并行时多片同时跑（独立临时目录，内存允许才并行）；
  ③ 只把缺的名字收进下一轮，批量逐轮减半，直到补齐或轮数用尽；
  ④ 缺的照样报出来（`missing`），不静默放过——对账在 orchestrator 侧仍会 diff≠0。

  批量与并行（2026-11-06 实测，Happiness Double Room 1441 名，verified-findings §31）：
  - 单次耗时亚线性：50 名 4.5s / 100 名 5.2s / 200 名 6.0s / 400 名 7.3s —— 每进程
    ~4s 的「加载整个游戏」开销主导。**首轮**批量 400 比 50 每秒多收 ~7 倍名字
    （新名字的丢失率与批量无关：50~400 名都在 17%~54% 间随机）。
  - 但**重试轮里剩的是难名字，小批量收益显著更高**（同日实测：批量 50→25→12 的
    收益率 36%→60%→99%，恒定 400 则逐轮恶化 17%→7.5%→5.5%）——「逐轮减半」是
    收敛的承重墙，不能用固定大批量替换（试过，12 轮后仍缺 294/1441）。减半的
    代价（后期碎片多）远小于它的收益（难名字靠小批量收尾）。
  - **1441 名一片实测挂死**（900s 超时、172/1441 后无产出）——400 是安全点，
    别上调去试悬崖。
  - 并行有效：2 进程实测加速 1.99×；单进程内存足迹实测 0.3~0.55 GiB，按 1 GiB/个
    留余量，**并行度按当时可用内存自适应**（不足自动降回串行），环境变量
    `GALUNPACK_AUDIO_WORKERS` 可强制（1=串行）。

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
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import toolbridge

#: 本次进程内开过的临时目录序号（见 `_fresh()`）。
_SEQ = itertools.count(1)

VOICE_PREFIXES = ["VA", "VB", "VC", "FE", "SEX", "ADD", "SE", "bgm", "SYASEI",
                  "sexyvoice", "ding", "punch", "camera", "door", "cross", "sex"]

# 单片名字数上限（首轮）。400 是**实测安全点**：7.3s/片、rc=0；1441 名一片实测挂死
# （900s 超时、172/1441 后无产出，AssetStudio 进程无 CPU 也无退出——「批量极大偶发
# 崩溃」的悬崖就在 400~1441 之间，别去试）。每片有 ~4s 固定进程开销、新名字收益与
# 片大小无关，所以首轮在安全点内尽量装满；之后逐轮减半收难名字（见下）。
BATCH = 400
#: 重试轮数上限。400→200→…→1 共 9 次减半，再留 3 轮给最难的名字做单名重试
# （单名导出实测稳定成功）。旧值 5 是按首轮 50 定的，起点变大后必须跟着变大。
MAX_ROUNDS = 12
TIMEOUT = 900
#: 单条 `--names` 正则的字符预算（CreateProcess 上限 32767 字符，留足余量）。
#: 只在名字数超上限或有超长名字时兜底，正常样本（1441 名 ≈ 10 KB）碰不到。
PATTERN_BUDGET = 24000
#: 并行度（每个 worker 一个 AssetStudio 进程）。会被可用内存收紧，环境变量可强制。
WORKERS = 3
#: 内存门：每个 AssetStudio 进程按 1 GiB 预留（实测足迹 0.3~0.55 GiB，翻倍留余量），
#: 并给系统/父进程留 1.5 GiB —— 工作约定：跑重活前先做内存自检，别把机器压死。
PER_WORKER_GIB = 1.0
RESERVE_GIB = 1.5


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
        toolbridge._clear_dll_dir()
        proc = subprocess.run(
            [str(exe), str(src), str(tmp), "--game", "Normal",
             "--types", "AudioClip", "--export_type", "JSON",
             "--group_assets", "BySource"],
            capture_output=True, timeout=TIMEOUT,
            env=toolbridge._sanitize_env())
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[WARN] 音频名字枚举失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        _drop(tmp)
        return None
    if proc.returncode != 0:
        # 只报不判死：JSON 可能部分落盘（这工具本来就不可靠），
        # 但 rc 与 stderr 是「为什么少了几条」的唯一线索，不能丢。
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        print(f"[WARN] 音频名字枚举 rc={proc.returncode}："
              f"{err[-300:].replace(chr(10), ' ') or '(无输出)'}", file=sys.stderr)

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


def _pattern_len(names: list[str]) -> int:
    """一条 `--names` 锚定正则的字符数（CreateProcess 按 WCHAR 计上限）。"""
    import re
    return 4 + sum(len(re.escape(n)) + 1 for n in names)     # "^( )" + 每名一个分隔符


def _split_chunks(pending: list[str], cap: int) -> list[list[str]]:
    """待补名单 → 片列表：≤cap 名/片；单片正则超字符预算时按预算贪心细分（兜底）。

    正常样本（1441 名 ≈ 10 KB）碰不到预算细分；它保护的是 SUMMER 那种 5627 条
    或超长名字的名单 —— 命令行超限会让 AssetStudio 直接起不来。
    """
    chunks = [pending[i:i + cap] for i in range(0, len(pending), cap)]
    if max(_pattern_len(c) for c in chunks) <= PATTERN_BUDGET:
        return chunks
    out: list[list[str]] = []
    for c in chunks:
        if _pattern_len(c) <= PATTERN_BUDGET:
            out.append(c)
            continue
        cur: list[str] = []
        cur_len = 4
        for n in c:
            w = len(re.escape(n)) + 1
            if cur and cur_len + w > PATTERN_BUDGET:
                out.append(cur)
                cur, cur_len = [], 4
            cur.append(n)
            cur_len += w
        if cur:
            out.append(cur)
    return out


def _export(exe: Path, src: Path, tmp: Path, pattern: str,
            export_type: str = "Convert") -> int:
    """跑一次 AssetStudio 导出。返回退出码（**只作诊断，不当成功判据**）。

    环境走 toolbridge 的清洗版：冻结包里的 `_MEI` 目录混进 PATH 会让 .NET
    子进程优先加载包内同名 DLL（蓝图 §4.3）。
    """
    _drop(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    toolbridge._clear_dll_dir()
    try:
        proc = subprocess.run(
            [str(exe), str(src), str(tmp), "--game", "Normal",
             "--types", "AudioClip", "--names", pattern,
             "--export_type", export_type, "--group_assets", "ByType"],
            capture_output=True, timeout=TIMEOUT,
            env=toolbridge._sanitize_env())
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            print(f"[WARN] 音频导出 rc={proc.returncode}："
                  f"{err[-300:].replace(chr(10), ' ') or '(无输出)'}", file=sys.stderr)
        return proc.returncode
    except subprocess.TimeoutExpired:
        print(f"[WARN] 音频导出超时（{TIMEOUT}s）", file=sys.stderr)
        return -1
    except OSError as exc:
        print(f"[WARN] 音频导出起不来：{type(exc).__name__}: {exc}", file=sys.stderr)
        return -2


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


def _mem_avail_gib() -> float | None:
    """当前可用物理内存（GiB）。非 Windows 或查询失败返回 None（调用方不收紧）。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import ctypes.wintypes

        class _MSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.wintypes.DWORD),
                        ("dwMemoryLoad", ctypes.wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = _MSTAT()
        m.dwLength = ctypes.sizeof(_MSTAT)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
        return m.ullAvailPhys / 1024 ** 3
    except Exception:                                        # noqa: BLE001
        return None


def resolve_workers(workers: int | None = None) -> int:
    """并行度解析：显式参数 > 环境变量 `GALUNPACK_AUDIO_WORKERS` > 默认 `WORKERS`。

    非法值一律退默认（不抛——这是性能旋钮，不该有把它变成失败的路径）。至少 1，
    1 = 完全串行（行为与并行化之前一致）。
    """
    if workers is not None:
        return max(1, int(workers))
    env = os.environ.get("GALUNPACK_AUDIO_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return WORKERS


def cap_workers_by_memory(workers: int, log=print) -> int:
    """按**当时**可用内存收紧并行度（实测足迹 0.3~0.55 GiB/进程，按 1 GiB/个预留）。

    机器被别的活占着时（工作约定的内存纪律）自动降回串行，而不是把机器压死
    （2026-10-30 教训：内存耗尽时进程被杀、连 stdout 都没有）。收紧只影响速度，
    不影响正确性与收敛 —— 对账地面真相始终是名字清单。
    """
    if workers <= 1:
        return workers
    avail = _mem_avail_gib()
    if avail is None:
        return workers
    room = int((avail - RESERVE_GIB) / PER_WORKER_GIB)
    capped = max(1, min(workers, room))
    if capped < workers:
        log(f"[INFO] 可用内存 {avail:.1f} GiB，音频并行度 {workers} -> {capped}"
            f"（每进程按 {PER_WORKER_GIB:g} GiB 预留；GALUNPACK_AUDIO_WORKERS 可强制）")
    return capped


def collect(src: Path, dest: Path, names: list[str], exe: Path | None = None,
            batch: int = BATCH, max_rounds: int = MAX_ROUNDS, log=print,
            work_root: Path | None = None, workers: int | None = None) -> dict:
    """按名字对账收音频。返回 {expected, unique, collected, missing, runs, workers}。

    每轮把待补名字切成 batch 大小的片；workers>1 时用线程池并行跑多个 AssetStudio
    进程（分片名字互不重叠 → merge 不会撞名；每个片一个**独立**临时目录，互不污染）。
    地面真相始终是名字清单：一轮结束按名字重扫，缺的进下一轮、批量减半兜底。

    work_root: 临时目录放哪。**默认 dest.parent**（= raw/）能用但会污染交付目录
    （清理失败时残留的 wav 会被对账数进去），orchestrator 一律显式传 `_work/`。
    """
    exe = exe or toolbridge.find_tool("assetstudio")
    dest.mkdir(parents=True, exist_ok=True)

    unique = sorted(set(names))
    have = {p.stem for p in dest.glob("*.wav")}
    pending = [n for n in unique if n not in have]
    workers = cap_workers_by_memory(resolve_workers(workers), log=log)
    log(f"音频对账：枚举 {len(names)} 条（唯一名 {len(unique)}），已落盘 {len(have)}，"
        f"待补 {len(pending)}，并行 {workers}")

    root = Path(work_root) if work_root is not None else dest.parent
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=dest.name + "_work_", dir=root))
    runs = 0
    merge_lock = threading.Lock()

    def run_chunk(idx: int, total: int, chunk: list[str]) -> int:
        """跑一个分片：独立临时目录导出 + 锁内合并（分片名字不重叠，锁只是保险）。"""
        tmp = work / f"chunk_{os.getpid()}_{next(_SEQ)}"
        rc = _export(exe, src, tmp, _name_pattern(chunk))
        with merge_lock:
            added = _merge(dest, tmp)
        _drop(tmp)
        if added < len(chunk):
            log(f"  [片 {idx + 1}/{total}] rc={rc} +{added}/{len(chunk)} "
                f"缺 {len(chunk) - added}")
        return added

    try:
        cur_batch = batch
        for rnd in range(1, max_rounds + 1):
            if not pending:
                break
            chunks = _split_chunks(pending, cur_batch)
            runs += len(chunks)          # 计数在主线程做：工作线程里的 += 有竞态
            log(f"第 {rnd} 轮：待补 {len(pending)}，{len(chunks)} 片"
                f"（≤{cur_batch} 名/片），并行 {workers}")
            if workers <= 1 or len(chunks) == 1:
                gained = sum(run_chunk(i, len(chunks), c)
                             for i, c in enumerate(chunks))
            else:
                tasks = ((i, len(chunks), c) for i, c in enumerate(chunks))
                with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as pool:
                    gained = sum(pool.map(lambda t: run_chunk(*t), tasks))
            have = {p.stem for p in dest.glob("*.wav")}
            pending = [n for n in unique if n not in have]
            log(f"  本轮 +{gained}，累计 {len(have)}，仍缺 {len(pending)}")
            # 逐轮减半是收敛的承重墙（§31 同日实测：难名字的收益率随批量变小急剧上升
            # 36%→60%→99%；恒定大批量则逐轮恶化）。固定 ~4s 的进程开销让小片「浪费」，
            # 但没有它们最难的那批名字永远出不来。
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
            "collected": len(total), "missing": missing, "runs": runs,
            "workers": workers}


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
