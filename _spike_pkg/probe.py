#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包可行性 spike 探针 —— 用完即弃（不许进产品代码）。

回答四个问题：
  1. 冻结后 subprocess 还能不能调外部 exe（ffprobe / GARbro .NET）？
  2. 冻结后 `sys.executable` 再拉 Python 兄弟脚本会变成什么？（orchestrator 有 7 处这么干）
  3. 冻结环境的 PATH / DLL 继承会不会污染子进程？
  4. 第三方依赖（Pillow / numpy / pycryptodome）在冻结包里能不能 import？

用法（冻结前后都能跑，输出对照）：
  probe.exe selftest
  probe.exe external <媒体文件> <xp3 归档>
  probe.exe detect <游戏目录>
  probe.exe deps
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

try:                                   # 未冻结时让仓库根可 import；冻结后指向 dist 目录，无害
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
except Exception:                      # noqa: BLE001
    pass


def hdr(tag: str) -> None:
    print(f"\n=== {tag} ===", flush=True)


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "selftest"

    if mode == "selftest":
        hdr("运行环境")
        print(f"python      : {sys.version.split()[0]}")
        print(f"frozen      : {getattr(sys, 'frozen', False)}")
        print(f"sys.exectbl : {sys.executable}")
        print(f"_MEIPASS    : {getattr(sys, '_MEIPASS', None)}")
        print(f"cwd         : {os.getcwd()}")
        print(f"PATH[0:3]   : {os.environ.get('PATH', '').split(os.pathsep)[:3]}")
        print(f"_MEIPASS in PATH: {getattr(sys, '_MEIPASS', '') in os.environ.get('PATH', '')}")

        hdr("① 冻结后 [sys.executable, '-c', ...] 会怎样（模拟 orchestrator 的兄弟脚本调用）")
        t = time.time()
        try:
            r = subprocess.run([sys.executable, "-c", "print('child python ran')"],
                               capture_output=True, text=True, timeout=60)
            print(f"rc={r.returncode}  {time.time()-t:.2f}s")
            print(f"stdout: {r.stdout.strip()[:200]!r}")
            print(f"stderr: {r.stderr.strip()[:300]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"EXC: {type(exc).__name__}: {exc}")

        hdr("② 冻结后 [sys.executable, '兄弟脚本.py', ...] 会怎样")
        try:
            r = subprocess.run([sys.executable, "orchestrator.py", "--help"],
                               capture_output=True, text=True, timeout=60)
            print(f"rc={r.returncode}")
            print(f"stdout: {r.stdout.strip()[:200]!r}")
            print(f"stderr: {r.stderr.strip()[:300]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"EXC: {type(exc).__name__}: {exc}")
        return 0

    if mode == "deps":
        hdr("第三方依赖在冻结包里能不能用")
        try:
            from PIL import Image
            print(f"Pillow      : {Image.__version__}")
        except Exception as exc:  # noqa: BLE001
            print(f"Pillow      : FAIL {type(exc).__name__}: {exc}")
        try:
            import numpy as np
            print(f"numpy       : {np.__version__}")
        except Exception as exc:  # noqa: BLE001
            print(f"numpy       : FAIL {type(exc).__name__}: {exc}")
        try:
            from Crypto.Cipher import Blowfish, ChaCha20
            from Crypto import __version__ as cv
            print(f"pycryptodome: {cv} (Blowfish+ChaCha20 ok)")
        except Exception as exc:  # noqa: BLE001
            print(f"pycryptodome: FAIL {type(exc).__name__}: {exc}")
        return 0

    if mode == "external":
        media = argv[2] if len(argv) > 2 else ""
        archive = argv[3] if len(argv) > 3 else ""
        hdr("③ 冻结后调外部 exe：ffprobe（原生）")
        import toolbridge as tb
        info, reason = tb.ffprobe_ex(media)
        print(f"ffprobe_ex  : info={'<有流>' if info else None} reason={reason!r}")
        if info:
            print(f"  streams   : {len(info.get('streams', []))}")

        hdr("④ 冻结后调外部 exe：GARbro（.NET / .NET 4.6+ 运行时）")
        t = time.time()
        try:
            res = tb.garbro_list(archive)
            if isinstance(res, tuple):
                print(f"garbro_list : ok={res[0]} entries={res[1]}  {time.time()-t:.2f}s")
            else:
                print(f"garbro_list : {res}  {time.time()-t:.2f}s")
        except Exception as exc:  # noqa: BLE001
            print(f"garbro_list : EXC {type(exc).__name__}: {exc}")

        hdr("⑤ 子进程环境是否被冻结污染（PATH / _MEIPASS / PYTHON*）")
        env = dict(os.environ)
        print(f"PATH 含 _MEIPASS: {getattr(sys, '_MEIPASS', '') in env.get('PATH', '')}")
        for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONNOUSERSITE", "_MEIPASS2", "LD_LIBRARY_PATH"):
            if k in env:
                print(f"{k} = {env[k][:120]}")
        return 0

    if mode == "detect":
        game = argv[2] if len(argv) > 2 else ""
        hdr("⑥ 冻结包里跑真实业务代码：detect + case-lookup")
        import case_lib
        import galgame_dispatch as gd
        t = time.time()
        rep = gd.scan(Path(game))
        best = rep.best
        print(f"scan        : engine={best.engine if best else None} "
              f"score={best.score if best else None} {time.time()-t:.2f}s")
        print(f"fired_ids   : {sorted(rep.fired_ids)}")
        cases_dir = argv[3] if len(argv) > 3 else None
        t = time.time()
        res = case_lib.lookup(best.engine if best else None, rep.fired_ids, cases_dir)
        print(f"lookup      : signature={res['signature']} index_present={res['index_present']} "
              f"candidates={len(res['candidates'])} {time.time()-t:.2f}s")
        for c in res["candidates"]:
            print(f"  - {c['case_id']} {c['sample']!r} disc={c.get('discriminator')}")
        return 0

    if mode == "inproc":
        game = argv[2] if len(argv) > 2 else ""
        hdr("⑦ 冻结包里直接 import 兄弟模块（替代 subprocess 的可行性）")
        import importlib
        mods = ["rpa_tool", "rpa_extract_organized", "asar_tool", "_pna_carve", "_rpgmv_decrypt",
                "_ypf_extract", "_grp_extract", "_cs2_int_extract", "_advhd_run", "_spite_decrypt",
                "_as_audio_collect2", "krkr_auto_extract", "_unity_extract", "orchestrator"]
        ok = []
        for m in mods:
            try:
                importlib.import_module(m)
                ok.append(m)
            except Exception as exc:  # noqa: BLE001
                print(f"  {m:<24} FAIL {type(exc).__name__}: {exc}")
        print(f"  import ok: {len(ok)}/{len(mods)} -> {ok}")

        hdr("⑧ 直接调函数（不 subprocess）：_rpgmv_decrypt.iter_candidates")
        if game and Path(game).exists():
            try:
                import _rpgmv_decrypt as rpg
                root = Path(game)
                if (root / "www").is_dir():
                    root = root / "www"
                cands = list(rpg.iter_candidates(root))
                print(f"  iter_candidates -> {len(cands)} 候选: {[str(c[1]) for c in cands][:3]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL {type(exc).__name__}: {exc}")
        else:
            print("  (未给游戏目录，跳过)")
        return 0

    print(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
