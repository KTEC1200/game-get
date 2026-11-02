#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 detect 黄金基线：对 _fixtures/ 每个样本 + D:\\HY 真实样本跑
galgame_dispatch.scan()，把「引擎 + 得分 + 是否有警告」固化成 JSON。

用途：后续重构 scan()（指纹外置 rules/engines.json）时，
      用它逐字段比对，确保行为不变。

两类基线分开存：
  - `fixtures`：_fixtures/ 下的合成样本，**必须全部通过**（随仓库走，永远在）。
  - `real`：D:\\HY 下的真实样本，**缺失即跳过**（样本可能被删，不能因此判失败；
            已知 `My Best Deal` 已于 2026-10 从磁盘消失）。

用法：
    python tests/make_golden.py          # 生成/更新基线
    python tests/make_golden.py --check  # 只比对，不一致则 exit 1
    python tests/make_golden.py --check --strict-real   # 真实样本缺失也算失败
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import galgame_dispatch as gd  # noqa: E402

FIXTURES = ROOT / "_fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden_detect.json"

# 真实样本：(路径, 期望引擎)。路径不存在时默认跳过。
# 12 个已跑通样本里 `My Best Deal` 已从磁盘消失，用 Swipe Right 覆盖 Ren'Py 分支。
REAL_SAMPLES: list[tuple[str, str]] = [
    (r"D:\HY\pork社\兼职人妻", "KiriKiri"),
    (r"D:\HY\My Wife Wants to Be a Professional Cosplayer", "Unity"),
    (r"D:\HY\Swipe Right for Sugar Mama Sensei", "Ren'Py"),
    (r"D:\HY\SPITE", "Tyrano/Electron"),
    (r"D:\HY\常識改変学園-製品版-", "RPG Maker"),
    (r"D:\HY\tm\ラブラブお痴験バイト性活", "AdvHD"),
    (r"D:\HY\あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-", "Yu-Ris"),
    (r"D:\HY\夕凪荘的S级的女朋友们", "ExHIBIT"),
    (r"D:\HY\甜蜜女友\【PC电脑】甜蜜女友2+", "CatSystem2"),
    (r"D:\HY\pork社\高慢妻陥落！！", "KiriKiri"),
    (r"D:\HY\教师催眠1", "KiriKiri"),
    (r"D:\HY\Toshiue Kanojo", "Artemis"),
]


def _snap_one(rep) -> dict[str, object]:
    """把一份 Report 折成可稳定比对的快照。

    记录 `evidence` 与 `facts` 是**故意**的（2026-10-30 加固）：只比得分的话，
    把某条规则的说明文字改错、或把某个 fact 悄悄丢掉，基线依然全绿——那样它就不配
    用来守护「指纹外置」这种纯重构。证据串里的数字（文件数、目录名）和 facts 里的
    实测值（Unity 版本、封包计数）都是确定性的，适合逐字比对。

    唯一保留宽松处理的是 `notes`：只记条数与是否含 `[警告]`/`[注意]`，
    因为 notes 里会拼进真实路径与文件体积，跨机器不稳。
    """
    best = rep.best
    return {
        "engine": best.engine if best else None,
        "score": best.score if best else 0,
        "above_threshold": bool(best and best.score >= gd.THRESHOLD),
        "guesses": [
            {"engine": g.engine, "score": g.score, "evidence": g.evidence}
            for g in rep.guesses
        ],
        "facts": rep.facts,
        "note_count": len(rep.notes),
        "has_warning": any("[警告]" in n for n in rep.notes),
        "has_attention": any("[注意]" in n for n in rep.notes),
    }


def snapshot_fixtures() -> dict[str, object]:
    out: dict[str, object] = {}
    for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        out[d.name] = _snap_one(gd.scan(d))
    return out


def snapshot_real() -> dict[str, object]:
    """真实样本快照。缺失的样本记为 {"missing": true}，让基线自解释。"""
    out: dict[str, object] = {}
    for path, want in REAL_SAMPLES:
        p = Path(path)
        name = p.name
        if not p.exists():
            out[name] = {"missing": True, "expect": want, "path": path}
            continue
        snap = _snap_one(gd.scan(p))
        snap["expect"] = want
        snap["path"] = path
        out[name] = snap
    return out


def snapshot() -> dict[str, object]:
    return {"fixtures": snapshot_fixtures(), "real": snapshot_real()}


def _diff(label: str, want: object, cur: object) -> bool:
    """逐 key 比对一个分区，返回是否有差异。"""
    ok = True
    want_d = want if isinstance(want, dict) else {}
    cur_d = cur if isinstance(cur, dict) else {}
    for k in sorted(set(want_d) | set(cur_d)):
        a, b = want_d.get(k), cur_d.get(k)
        if a != b:
            print(f"[DIFF] {label}/{k}")
            print(f"   基线: {json.dumps(a, ensure_ascii=False)}")
            print(f"   当前: {json.dumps(b, ensure_ascii=False)}")
            ok = False
    return ok


def main(argv: list[str]) -> int:
    cur = snapshot()

    if "--check" in argv:
        if not GOLDEN.exists():
            print(f"[FAIL] 基线不存在：{GOLDEN}，先跑不带 --check 的版本")
            return 1
        want = json.loads(GOLDEN.read_text(encoding="utf-8"))
        strict_real = "--strict-real" in argv

        ok = _diff("fixtures", want.get("fixtures"), cur["fixtures"])

        # 真实样本：缺失默认跳过；--strict-real 时才算失败
        want_real = want.get("real") or {}
        cur_real = cur["real"]
        missing: list[str] = []
        for k in sorted(set(want_real) | set(cur_real)):
            a, b = want_real.get(k), cur_real.get(k)
            is_missing = (b or {}).get("missing") or (a or {}).get("missing")
            if is_missing:
                missing.append(k)
                if strict_real:
                    print(f"[MISS] real/{k} 样本不在磁盘上（--strict-real 下算失败）")
                    ok = False
                continue
            if a != b:
                print(f"[DIFF] real/{k}")
                print(f"   基线: {json.dumps(a, ensure_ascii=False)}")
                print(f"   当前: {json.dumps(b, ensure_ascii=False)}")
                ok = False

        # 真实样本的「期望引擎」必须与实测一致——这是 detect 覆盖率的硬指标
        for k, snap in cur_real.items():
            if snap.get("missing"):
                continue
            got, want_e = snap.get("engine"), snap.get("expect")
            if got != want_e:
                print(f"[FAIL] real/{k} 期望 {want_e}，实测 {got}")
                ok = False

        n_fix = len(cur["fixtures"])
        n_real = sum(1 for s in cur_real.values() if not s.get("missing"))
        if ok:
            extra = f"，跳过 {len(missing)} 个缺失样本" if missing else ""
            print(f"[OK] {n_fix} 个 fixture + {n_real} 个真实样本全部与基线一致{extra}")
            return 0
        return 1

    GOLDEN.write_text(
        json.dumps(cur, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    n_fix = len(cur["fixtures"])
    n_real = sum(1 for s in cur["real"].values() if not s.get("missing"))
    print(f"[OK] 已写入基线：{GOLDEN}（{n_fix} 个 fixture + {n_real} 个真实样本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
