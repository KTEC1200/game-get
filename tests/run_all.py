#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑全量测试，并**用 junit 判定成败**——不看 pytest 的退出码。

背景（2026-11-03 实测）：本机有一个批量删除守卫，pytest 退出清理
`%TEMP%\\pytest-of-<user>\\` 时它会抛 `BaseException`（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`
/ `SAFE_DELETE_FAIL_CLOSED`），于是**测试全绿、进程退出码却是 1**。
自动化里「绿」和「红」分不开比测试真的挂了更危险：人一旦开始忽略红色，红色就不再有信息量。
所以基线的唯一判据是 junit XML 里的 tests/failures/errors。

用法：
    python tests/run_all.py                 # 跑 tests/，全绿退 0，否则退 1
    python tests/run_all.py -k verify       # 其余参数原样透传给 pytest
    python tests/run_all.py -x --maxfail=1

注意：**不要**自己加 `--basetemp` 指到仓库所在盘——守卫会把测试内部的清理动作也拦掉，
制造一批与代码无关的假失败。临时目录交给 pytest 默认（系统 temp），xml 也放系统 temp。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def summarize(xml: Path) -> dict | None:
    """读 junit 的 testsuite 计数；文件不存在 / 不是合法 XML 返回 None（= 没跑起来）。"""
    try:
        root = ET.parse(xml).getroot()
    except (OSError, ET.ParseError):
        return None
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return None
    a = suite.attrib
    return {"tests": int(a.get("tests", 0)), "failures": int(a.get("failures", 0)),
            "errors": int(a.get("errors", 0)), "skipped": int(a.get("skipped", 0))}


def main(argv: list[str] | None = None) -> int:
    extra = list(sys.argv[1:] if argv is None else argv)
    tmpdir = Path(tempfile.mkdtemp(prefix="galunpack-junit-"))
    xml = tmpdir / "junit.xml"
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", f"--junitxml={xml}", *extra]
    print("$ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    info = summarize(xml)

    # 清掉临时文件（单文件删除，远低于守卫的批量阈值；失败就算了，系统 temp 会自己回收）
    try:
        xml.unlink()
        tmpdir.rmdir()
    except OSError:
        pass

    if info is None:
        print(f"junit: 没有产出 XML（pytest 早退或崩溃，rc={proc.returncode}）→ FAIL",
              flush=True)
        return proc.returncode or 1

    ok = info["failures"] == 0 and info["errors"] == 0
    print("junit: tests={tests} failures={failures} errors={errors} skipped={skipped} → {v}"
          .format(v="PASS" if ok else "FAIL", **info), flush=True)
    if ok and proc.returncode != 0:
        print(f"注意：pytest 退出码 {proc.returncode} 非 0，但 junit 里 0 失败 0 错误 —— "
              f"本机删除守卫拦住了 pytest 退出时的临时目录清理，以 junit 为准。", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
