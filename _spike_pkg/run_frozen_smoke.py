#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结包验证驱动：拿真实样本跑冻结后的 orchestrator.exe。

两个目的（对应 §19.2 第 1、2 条的冻结态实证）：
  1. --dry-run 档：只 detect + case-lookup —— 验证 rules/ 与 cases/ 两个数据文件
     确实进了包、__file__ 相对定位在冻结态能命中；
  2. --full 档：真跑全链 —— 验证 in-process 兄弟调用（_run_sibling）在冻结包里可用
     （子进程拉脚本那条路已经不存在了）。

样本选择不写死 CJK 名（GBK 控制台进不了命令行）：从 build_cases.SAMPLES 的
game_dir 出发，按结构特征挑一个存在的样本。默认挑 RPG Maker（extract 走
in-process 的 _rpgmv_decrypt.main，最能证明第 1 条）；没有就退而求其次拿第一个。

产物落 `_extracted/<样本名>-frozen/`（gitignore 内）。

用法：
  python _spike_pkg/run_frozen_smoke.py            # dry-run 档（秒级）
  python _spike_pkg/run_frozen_smoke.py --full     # 全链（分钟级，真解包）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "_spike_pkg" / "dist" / "orchestrator" / "orchestrator.exe"


def pick_sample() -> tuple[str, Path | None]:
    """返回 (样本名, 游戏目录)。优先 RPG Maker（www/js/rpg_core.js），其次任意存在。"""
    sys.path.insert(0, str(REPO))
    import build_cases as bc
    fallback: tuple[str, Path] | None = None
    for name, s in bc.SAMPLES.items():
        d = Path(s["game_dir"])
        if not d.is_dir():
            continue
        if (d / "www" / "js" / "rpg_core.js").is_file():
            return name, d
        if fallback is None:
            fallback = (name, d)
    return fallback or ("", None)


def run(label: str, argv: list[str], timeout: int) -> int:
    print(f"\n{'#' * 70}\n# {label}\n{'#' * 70}", flush=True)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        out = r.stdout or ""
        # stdout 可能很大（--json 没开时主要是阶段摘要）；打印尾部 30 行
        lines = out.strip().splitlines()
        for line in lines[-30:]:
            print(line, flush=True)
        if r.stderr.strip():
            print(f"[stderr] {r.stderr.strip()[-500:]}", flush=True)
        print(f"[rc={r.returncode}]", flush=True)
        return r.returncode
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT >{timeout}s]", flush=True)
        return 124
    except Exception as exc:  # noqa: BLE001
        print(f"[EXC] {type(exc).__name__}: {exc}", flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    full = "--full" in (argv or [])
    if not EXE.exists():
        print(f"冻结包不存在：{EXE}\n先跑 python build_exe.py", file=sys.stderr)
        return 1
    name, game = pick_sample()
    if game is None:
        print("没有可用的真实样本（build_cases.SAMPLES 里的 game_dir 都不存在）",
              file=sys.stderr)
        return 1
    out = REPO / "_extracted" / f"{game.name}-frozen"
    print(json.dumps({"frozen_exe": str(EXE), "sample": name, "game": str(game),
                      "out": str(out), "mode": "full" if full else "dry-run"},
                     ensure_ascii=False, indent=2))

    rc = run("冻结 dry-run（detect + case-lookup，验数据文件）",
             [str(EXE), str(game), "--out", str(out), "--dry-run"], 180)
    if rc != 0:
        return rc
    if not full:
        return 0
    return run("冻结 全链（extract[in-process] → verify → manifest）",
               [str(EXE), str(game), "--out", str(out)], 3600)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
