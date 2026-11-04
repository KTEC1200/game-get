#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""失败日志：把每次失败追加写进**软件根目录**的 `failures.log`。

## 为什么不复用 `_work/<stage>.log`

阶段日志在**输出目录**里，跟着产物走。可输出目录本身可能是第一个失效的东西
（2026-11-04 实测：未签名 exe 写 `Documents` 被终端防护拒，`mkdir` 就炸了）——
把失败记录放在一个「可能建不出来」的目录里，等于下雨天才发现伞在屋里。
失败日志必须与产物解耦，落在软件自己旁边。

## 格式

纯文本块、追加写。第一读者是**人**：出问题时用户直接打开文件、截图发过来就够了。
JSONL 机器友好但一行能拉到几百字符，人读不了。

```
[2026-11-04 22:41:58 +0800] extract-failed  engine=KiriKiri  rc=1
  game  : D:\HY\高慢妻陥落！！
  out   : D:\out\高慢妻陥落！！
  stage : extract  GARbro 列不出目录（可能是加密 xp3）
  python: 3.14.6  win32
  ---
```

## 健壮性（这是本模块存在的前提）

`log_failure()` **永不抛异常**：目录不存在就建，建不出来换备用位置，
备用也写不了就往 stderr 说一句然后放弃。失败日志写不进去绝不能变成新的失败。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence

#: 单个日志文件的上限。超过就把旧的改名成 `failures.log.1`（只留一份历史）。
#: 不轮转的话，天天失败的用户迟早得到一个几百 MB 的文本文件。
MAX_BYTES = 2 * 1024 * 1024

#: 文件头（只在新建时写一次）。说明降级行为，省得用户以为「只有这一份」。
HEADER = (
    "# Galgame Unpacker 失败日志（追加写，UTF-8）\n"
    "# 如果软件目录不可写，会退到 %LOCALAPPDATA%\\GalgameUnpacker\\failures.log\n"
    "\n"
)


def app_root() -> Path:
    """软件根目录：冻结态 = exe 旁；源码态 = 仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def fallback_path() -> Path:
    """备用位置：用户本地应用数据目录（一定可写，只是不显眼）。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / "GalgameUnpacker" / "failures.log"


def _one_line(value) -> str:
    """把字段压成一行：换行会破坏「一条失败一块」的可读性。"""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _render(*, error: str, engine: str | None, game_dir, out_dir,
            stages: Sequence[Mapping] | None, exc_text: str | None,
            extra: Mapping | None, rc: int | None) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S %z")
    head = f"[{ts}] {error or 'unknown'}"
    if engine:
        head += f"  engine={engine}"
    if rc is not None:
        head += f"  rc={rc}"
    lines = [head]
    if game_dir:
        lines.append(f"  game  : {_one_line(game_dir)}")
    if out_dir:
        lines.append(f"  out   : {_one_line(out_dir)}")
    # 失败阶段：只报 ok=False 的那几个（跳过/成功的没人关心）
    for s in stages or ():
        try:
            if s.get("ok") or s.get("skipped"):
                continue
            detail = _one_line(s.get("detail") or "")
            lines.append(f"  stage : {s.get('stage')}  {detail}")
            if s.get("exception"):
                lines.append(f"  exc   : {s.get('exception')}: {_one_line(s.get('message') or '')}")
        except AttributeError:
            continue
    for k, v in (extra or {}).items():
        lines.append(f"  {str(k):<6}: {_one_line(v)}")
    lines.append(f"  python: {sys.version.split()[0]}  {sys.platform}")
    if exc_text:
        lines.append("  traceback:")
        for ln in exc_text.rstrip().splitlines()[-40:]:      # 只留末尾 40 行，够定位
            lines.append("    " + ln)
    lines.append("  ---")
    return "\n".join(lines) + "\n"


def _write(path: Path, block: str) -> bool:
    """往 path 追加一块；成功返回 True。目录不存在就建，超限就轮转。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    if not fresh:
        try:
            if path.stat().st_size > MAX_BYTES:
                path.replace(path.with_suffix(path.suffix + ".1"))
                fresh = True
        except OSError:
            pass                                              # 轮转失败不致命，继续追加
    with path.open("a", encoding="utf-8", errors="replace") as fh:
        if fresh:
            fh.write(HEADER)
        fh.write(block)
    return True


def log_failure(*, error: str, engine: str | None = None, game_dir=None, out_dir=None,
                stages: Sequence[Mapping] | None = None, exc_text: str | None = None,
                extra: Mapping | None = None, rc: int | None = None,
                root: Path | None = None) -> Path | None:
    """记一条失败。返回实际写入的文件；返回 None 表示两处都写不了（已提示到 stderr）。

    **永不抛异常**——这是它对调用方的唯一承诺。任何写盘问题都降级成 stderr 一行。
    """
    block = _render(error=error, engine=engine, game_dir=game_dir, out_dir=out_dir,
                    stages=stages, exc_text=exc_text, extra=extra, rc=rc)
    primary = (Path(root) if root is not None else app_root()) / "failures.log"
    tried: list[str] = []
    for path in (primary, fallback_path()):
        if path in {Path(t) for t in tried}:                  # 两者可能是同一个位置
            continue
        tried.append(str(path))
        try:
            if _write(path, block):
                return path
        except OSError as exc:
            tried[-1] = f"{path}（{type(exc).__name__}: {exc}）"
            continue
        except Exception as exc:                              # noqa: BLE001 —— 兜底，见 docstring
            tried[-1] = f"{path}（{type(exc).__name__}: {exc}）"
            continue
    try:
        print("[WARN] 失败日志写不进去：" + "；".join(tried), file=sys.stderr)
    except Exception:                                         # noqa: BLE001
        pass
    return None
