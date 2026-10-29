#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部工具桥（toolbridge）—— 找工具 / 调工具 / 数产物 / 退出码不信任。

设计目标（software-plan §3 阶段1 第 4 条）：
  统一「找工具（注册表化路径）+ 调用 + 数产物 + 退出码不信任」，
  先覆盖 GARbro / tlg2png / ffprobe / AssetStudio / KrkrExtract 五个。

四条硬规矩（每条都是踩坑换来的，见 AGENTS.md「坑」与 verified-findings）：
  1. **退出码 0 毫无意义**（坑 4）：AssetStudio `--types A,B,C` 会静默归零且 exit=0。
     → 成功判据一律是「产物数」或「产物谓词」，returncode 只作诊断信息记录。
  2. **外部工具路径不许硬编码**：查找顺序 = 显式 override → 环境变量 → 配置文件
     → 内置候选 → PATH。找不到就抛 ToolNotFound，并把所有尝试过的路径列出来。
  3. **子进程环境要洗干净**（蓝图 §4.3）：PyInstaller 冻结后 `_MEIPASS` 会进 PATH，
     子进程继承后会优先加载包内同名 DLL 而崩溃；同时清 `SetDllDirectoryW`。
  4. **判「有没有视频」不能靠魔数扫描**（坑 3）：本模块只负责调工具与数产物，
     不做任何内容级猜测——那属于各引擎 extractor 的职责。

用法（库）::

    import toolbridge as tb
    r = tb.run("garbro", ["-x", str(xp3)], cwd=outdir, product_dir=outdir)
    if not r.ok:                      # r.ok 由产物数决定，不是 returncode
        print(r.reason)

用法（CLI，自检）::

    python toolbridge.py check              # 列出 5 个工具的解析结果
    python toolbridge.py check --json       # 机器可读
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
    "garbro_list", "garbro_extract", "tlg2png", "ffprobe",
    "assetstudio_export", "krkr_inject", "check_all",
]

# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------
# 每条的 candidates 只放「本机已知的安装位置」，全部可被环境变量/配置文件覆盖。
# 环境变量名统一 TOOLBRIDGE_<KEY>，避免和游戏自己的环境变量撞车。


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
}

# 配置文件：优先仓库根，其次用户目录。两者可同时存在，后者覆盖前者。
CONFIG_NAME = "toolbridge.json"


class ToolNotFound(RuntimeError):
    """工具找不到。消息里带全部尝试过的路径 + 该工具的已知坑。"""


# ---------------------------------------------------------------------------
# 找工具
# ---------------------------------------------------------------------------


def _expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def _load_config() -> dict:
    """读 toolbridge.json。找不到/坏掉都静默返回 {}——配置是可选增强，不能拖垮主流程。"""
    here = Path(__file__).resolve().parent
    merged: dict = {}
    for cand in (here / CONFIG_NAME, Path.home() / ".toolbridge.json"):
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
    spec = TOOLS[key]
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
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = run("tlg2png", [str(src), str(dst)], timeout=timeout, product_dir=dst.parent,
            min_products=1)
    if r.ok and not _is_png(dst):
        r.ok = False
        r.reason = f"产物不是合法 PNG：{dst.name}（size={dst.stat().st_size if dst.exists() else 0}）"
    return r


# 只有这些扩展名才值得送 ffprobe（与 _verify_media.AV_EXT 保持一致）。
AV_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".mpg", ".mpeg",
          ".mp3", ".ogg", ".wav", ".opus", ".flac", ".m4a", ".aac", ".wma"}


def ffprobe(path: str | os.PathLike, *, timeout: float = 120) -> dict | None:
    """探一个媒体文件，返回规整后的信息 dict；不可解返回 None。

    非白名单扩展名直接返回 None（**不要**把 .rpyc/.otf 送去 ffprobe，
    只会得到 `Invalid data found` 把验收搅浑）。
    """
    p = Path(path)
    if p.suffix.lower() not in AV_EXT:
        return None
    r = run("ffprobe", ["-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(p)], timeout=timeout)
    if r.returncode != 0:
        return None
    try:
        j = json.loads(r.stdout)
    except Exception:
        return None
    streams = j.get("streams") or []
    if not streams:
        return None
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    s = v or a
    dur = j.get("format", {}).get("duration") or s.get("duration")
    return {
        "codec": s.get("codec_name"),
        "kind": "video" if v else "audio",
        "w": v.get("width") if v else None,
        "h": v.get("height") if v else None,
        "sr": a.get("sample_rate") if a else None,
        "dur": float(dur) if dur else None,
    }


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


def check_all() -> list[dict]:
    """逐个解析 5 个工具，返回可序列化的状态表（不调用、只查在不在）。"""
    rows = []
    for key, spec in TOOLS.items():
        row = {"key": key, "exe_name": spec.exe_name, "purpose": spec.purpose,
               "sync": spec.sync, "notes": spec.notes}
        try:
            p = find_tool(key)
            row.update(found=True, path=str(p), size=p.stat().st_size)
        except ToolNotFound as exc:
            row.update(found=False, path=None, size=0, error=str(exc).splitlines()[0])
        rows.append(row)
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
        return 0 if all(r["found"] for r in rows) else 1
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
