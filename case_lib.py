#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cases/ 案例库查表实现 —— 指纹签名与查表的**唯一出处**。

为什么单独一个模块
------------------
`build_cases.py`（建库）与 `orchestrator.py`（用库）必须算同一种签名。
两处各写一遍哈希，改一处忘另一处 → 案例库静默失配：查不到不报错，
只是「报告命中」永远空着，最坏的一类 bug（无声的漏验）。

诚实边界
--------
- **没判出引擎 → 返回 None**，不许用空串哈希出一个「看起来合法」的假签名
  （`sha1("|")` 也是个漂亮的 12 位十六进制，肉眼分辨不出来）。
- **索引缺失/损坏 → `load_index()` 返回 None**，查表结果是「没有案例库」，
  与「有案例库但没命中」是两件事，不能混成同一个空列表。
- **索引登记了 case 但文件没了 → 候选里标 `missing: True`** 并继续列出：
  案例库自己缺文件是必须看得见的缺口，不是「没命中」。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: 默认案例库目录（仓库根的 cases/）。测试可传别的目录。
DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"


def _sha1(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def signature(engine: str | None, signals) -> str | None:
    """指纹签名 = sha1(engine|信号集排序后逗号拼接)[:12]。

    信号集必须**排序**：规则表里信号的书写顺序会随快照 JSON 变化，
    不排序会让同一种游戏在不同时间算出不同签名（案例库就查不到了）。
    """
    if not engine:
        return None
    return _sha1(engine, ",".join(sorted(signals)))[:12]


def slug(name: str) -> str:
    """样本/引擎名 → 文件名安全的短标识（保留 CJK，去掉路径分隔符与空格）。"""
    return name.replace("/", "-").replace("\\", "-").replace(" ", "-").strip("-")


#: 旧名保留（build_cases 的调用点已改用 slug，此处只是别处手滑时少一次 ImportError）
_slug = slug


def case_id(engine: str, signals, sample: str,
            discriminator: str | None = None) -> str:
    """case_id = sha1(engine + 信号集 + 样本 slug + discriminator)[:12]。

    纯指纹哈希在「兼职人妻 vs 高慢妻」这类**同签名**场景会撞车，
    所以把样本 slug 与 discriminator 一并入哈希，保证唯一且确定性。
    """
    parts = [engine or "", ",".join(sorted(signals)), slug(sample)]
    if discriminator:
        parts.append(discriminator)
    return _sha1(*parts)[:12]


def load_index(cases_dir: Path | str | None = None) -> dict | None:
    """读 `cases/index.json`。不存在或解析失败一律返回 None（调用方按「无案例库」处理）。"""
    path = Path(cases_dir or DEFAULT_CASES_DIR) / "index.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def load_case(case_id_: str, cases_dir: Path | str | None = None) -> dict | None:
    """按 case_id 找案例文件（文件名是 `<case_id>-<engine>.json`）。"""
    root = Path(cases_dir or DEFAULT_CASES_DIR)
    for p in sorted(root.glob(f"{case_id_}-*.json")):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


def lookup(engine: str | None, signals, cases_dir: Path | str | None = None) -> dict:
    """按指纹查案例库，返回候选清单（**只读、不判定**）。

    返回::

        {
          "signature": str | None,     # 算不出（没引擎）时为 None
          "index_present": bool,       # False = 案例库本身不在，不是「没命中」
          "candidates": [              # 同签名可能多个变体，全部列出，别挑一个
            {"case_id", "engine", "engine_label", "sample", "discriminator",
             "provenance", "decision": {...}, "failures": int,
             "case_path": str | None, "missing": bool(可选)}
          ]
        }
    """
    root = Path(cases_dir or DEFAULT_CASES_DIR)
    sig = signature(engine, signals)
    index = load_index(root)
    out: dict = {"signature": sig, "index_present": index is not None,
                 "candidates": []}
    if not sig or not index:
        return out

    entries = ((index.get("by_signature") or {}).get(sig)) or []
    for e in entries:
        cid = e.get("case_id")
        cand = {k: e.get(k) for k in
                ("case_id", "engine", "engine_label", "sample",
                 "discriminator", "provenance")}
        case = load_case(cid, root) if cid else None
        if case is None:
            cand["decision"] = None
            cand["failures"] = 0
            cand["case_path"] = None
            cand["missing"] = True
        else:
            dec = case.get("decision") or {}
            cand["decision"] = {
                "extractor": dec.get("extractor"),
                "expected_total": dec.get("expected_total"),
                "archive_count": dec.get("archive_count"),
            }
            cand["failures"] = len(case.get("failures") or [])
            cand["case_path"] = str(root / f"{cid}-{slug(case.get('engine') or '')}.json")
        out["candidates"].append(cand)
    return out


if __name__ == "__main__":                       # 手工查表：python case_lib.py <引擎> <信号,逗号分隔>
    import sys

    if len(sys.argv) < 3:
        print("用法: python case_lib.py <engine> <signal1,signal2>")
        raise SystemExit(2)
    res = lookup(sys.argv[1], [s for s in sys.argv[2].split(",") if s])
    print(json.dumps(res, ensure_ascii=False, indent=2))
