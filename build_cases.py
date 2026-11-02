#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cases/ 案例库构建器（galgame 解包工作流的软件化第 5 步）。

为什么需要案例库
----------------
蓝图 §2.7 的「自愈闭环」要求：拿到一个新游戏时，先用 (格式签名哈希, 目录特征)
查案例库，命中就跳过 LLM 推理（L0）、直接套用已验证的 (decoder, key, 备注)。
本仓库的规则表 `rules/engines.json` 解决「这是哪个引擎」，
案例库解决「这个引擎的这个变体上次是怎么解出来的、踩过什么坑」。

两类来源，两种可信度
--------------------
1. `manifest` —— 从 `_extracted/<样本>/manifest.json` 机械重建。
   counts / verify / reconcile / timing 全部逐字来自 manifest（地面真相），
   **不手填、不估算**。
2. `docs-reconstructed` —— 从 AGENTS.md 样本表 + verified-findings.md 提炼。
   这类样本的产物目录已不存在（或从未跑过 orchestrator），所以 counts 是
   **文档记载的摘要**，不是逐文件清单。provenance 必须写清这一点 ——
   把「文档摘要」当成「manifest 地面真相」是本仓库最忌讳的造假。

诚实纪律（写进测试 tests/test_cases.py）
----------------------------------------
- `provenance.source` 只能是 `manifest` 或 `docs-reconstructed`。
- docs 重建的案例 `provenance.manifest_path` 必须是 null。
- `failures[]` 每条必须有 `ref`（verified-findings 章节号），不许写无出处的「可能」。
- `bytes` 不知道就写 null，不许编。

用法
----
    python build_cases.py --from-manifests   # 从 _extracted/*/manifest.json 重建
    python build_cases.py --from-docs         # 从 _failures_raw.json + _docs_meta.json 提炼
    python build_cases.py --index             # 重建 cases/index.json
    python build_cases.py --validate          # 校验所有 case 的 schema + provenance 诚实
    python build_cases.py                     # 索引并校验已有案例（不重建）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
sys.path.insert(0, str(ROOT))

import galgame_dispatch as gd  # noqa: E402
import case_lib                # noqa: E402

SCHEMA_VERSION = "cases/1"
THRESHOLD = gd.THRESHOLD  # 60

FAILURES_RAW = CASES / "_failures_raw.json"
DOCS_META = CASES / "_docs_meta.json"

# ---------------------------------------------------------------------------
# 样本注册表
#
# key = _failures_raw.json 里的样本名（子代理提炼时用的键）。
# game_dir 一律用 AGENTS.md 样本表里的路径（实测存在性已在 2026-11-01 核过）。
# manifest = _extracted 下的 manifest.json（相对仓库根）；None = 纯文档样本。
# discriminator = 同签名时的区分标签（见下方「已知坑」）。
# ---------------------------------------------------------------------------
SAMPLES: dict[str, dict] = {
    "兼职人妻": {"game_dir": r"D:\HY\pork社\兼职人妻", "manifest": None,
                "discriminator": "xp3-plain"},
    "My Wife Wants to Be a Professional Cosplayer": {
        "game_dir": r"D:\HY\My Wife Wants to Be a Professional Cosplayer",
        "manifest": "_extracted/My Wife Wants to Be a Professional Cosplayer/manifest.json",
        "discriminator": None},
    "My Best Deal v4.7": {"game_dir": r"D:\HY\最佳的交易\My_Best_Deal_v4.7-pc",
                          "manifest": None, "discriminator": "rpa-python2"},
    "SPITE": {"game_dir": r"D:\HY\SPITE", "manifest": None, "discriminator": None},
    "Swipe Right for Sugar Mama Sensei": {
        "game_dir": r"D:\HY\Swipe Right for Sugar Mama Sensei",
        "manifest": None, "discriminator": "rpa-python3-4pack"},
    "常識改変学園-製品版-": {"game_dir": r"D:\HY\常識改変学園-製品版-",
                              "manifest": None, "discriminator": None},
    "ラブラブお痴験バイト性活": {
        "game_dir": r"D:\HY\tm\ラブラブお痴験バイト性活",
        "manifest": "_extracted/ラブラブお痴験バイト性活/manifest.json",
        "discriminator": None},
    "あまねぇ": {"game_dir": r"D:\HY\あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-",
                "manifest": None, "discriminator": None},
    "夕凪荘的S级的女朋友们": {
        "game_dir": r"D:\HY\夕凪荘的S级的女朋友们",
        "manifest": "_extracted/夕凪荘的S级的女朋友们/manifest.json",
        "discriminator": None},
    "甜蜜女友2+": {
        "game_dir": r"D:\HY\甜蜜女友\【PC电脑】甜蜜女友2+",
        "manifest": "_extracted/甜蜜女友2+/manifest.json",
        "discriminator": None},
    "高慢妻陥落！！": {"game_dir": r"D:\HY\pork社\高慢妻陥落！！",
                      "manifest": None, "discriminator": "xp3-encrypted"},
    "教师催眠1": {"game_dir": r"D:\HY\教师催眠1", "manifest": None,
                  "discriminator": "xp3-encrypted-krkrZ"},
}

# 已排除的 manifest 目录（同款试跑，非独立样本）
EXCLUDED_MANIFEST_DIRS = {"甜蜜女友2+_试跑"}


def _sha1(*parts: str) -> str:              # 兼容旧调用；实现在 case_lib
    return case_lib._sha1(*parts)


def _now() -> str:
    # 本地时区（Asia/Shanghai = UTC+8）
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _slug(name: str) -> str:                # 兼容旧调用；实现在 case_lib
    return case_lib.slug(name)


def _fingerprint(game_dir: Path) -> dict:
    """现场重扫游戏目录，拿真实指纹。目录不存在时返回 reconstructed=False。"""
    if not game_dir.exists():
        return {"signals": [], "score": 0, "threshold": THRESHOLD,
                "signature": None, "reconstructed": True,
                "note": f"游戏目录不存在：{game_dir}"}
    rep = gd.scan(game_dir)
    best = rep.best
    signals = sorted(rep.fired_ids)
    # 签名算法在 case_lib（与 orchestrator 查表共用同一份，改一处不会两边漂移）
    sig = case_lib.signature(best.engine if best else None, signals)
    return {
        "signals": signals,
        "score": best.score if best else 0,
        "threshold": THRESHOLD,
        "signature": sig,
        "engine": best.engine if best else None,
        "reconstructed": False,
    }


def _case_id(engine: str, signals: list[str], sample: str, discriminator: str | None) -> str:
    """case_id = sha1(engine + 信号集 + 样本 + discriminator)[:12]（实现在 case_lib）。

    纯指纹哈希在「兼职人妻 vs 高慢妻」这类同签名场景会撞车，
    所以把样本 slug 与 discriminator 一并入哈希，保证唯一且确定性。
    """
    return case_lib.case_id(engine, signals, sample, discriminator)


def _load_failures() -> dict:
    return json.loads(FAILURES_RAW.read_text(encoding="utf-8"))


def _load_docs_meta() -> dict:
    return json.loads(DOCS_META.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 从 manifest 重建
# ---------------------------------------------------------------------------
def build_from_manifest(sample: str, spec: dict, failures_data: dict) -> dict:
    manifest_path = ROOT / spec["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    game_dir = Path(spec["game_dir"])
    detect = next(st for st in manifest["stages"] if st.get("stage") == "detect")
    engine = detect["engine"]
    engine_label = manifest.get("engine")
    signals = sorted(detect["fired_ids"])
    fp = {"signals": signals, "score": detect["score"], "threshold": THRESHOLD,
          "signature": case_lib.signature(engine, signals), "engine": engine,
          "reconstructed": False}

    timing = {"detect": None, "extract": None, "postprocess": None,
              "verify": None, "manifest": None, "total": None}
    for st in manifest.get("stages", []):
        name = st.get("stage")
        secs = st.get("seconds")
        if name in timing and secs is not None:
            timing[name] = secs
    timing["total"] = manifest.get("total_seconds")

    counts = manifest.get("counts")
    verify = manifest.get("verify")
    reconcile = manifest.get("reconcile")

    # 从 counts.final.by_ext 推导 summary（图片/音频/视频）
    summary = _summarize(counts)

    failures = failures_data.get(sample, {}).get("failures", [])

    return {
        "schema": SCHEMA_VERSION,
        "case_id": _case_id(engine, signals, sample, spec.get("discriminator")),
        "engine": engine,
        "engine_label": engine_label,
        "sample": sample,
        "game_dir": str(game_dir),
        "discriminator": spec.get("discriminator"),
        "fingerprint": fp,
        "decision": failures_data.get(sample, {}).get("decision", {}),
        "timing": timing,
        "result": {
            "ok": manifest.get("ok"),
            "source": "manifest",
            "summary": summary,
            "media_minutes": (verify or {}).get("media_minutes"),
            "counts": counts,
            "verify": verify,
            "reconcile": reconcile,
        },
        "failures": failures,
        "provenance": {
            "source": "manifest",
            "manifest_path": spec["manifest"],
            "doc_refs": ["AGENTS.md 样本表"],
            "generated_at": _now(),
        },
    }


def _summarize(counts: dict | None) -> dict:
    """从 manifest counts 推导 {images, audio, video, total}。"""
    if not counts:
        return {"images": None, "audio": None, "video": None, "total": None}
    final = counts.get("final") or {}
    by_ext = final.get("by_ext") or {}
    img_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tlg", ".mos"}
    aud_exts = {".ogg", ".wav", ".mp3", ".flac", ".m4a", ".opus", ".aac", ".wma"}
    vid_exts = {".mpg", ".mpeg", ".avi", ".webm", ".mkv", ".wmv", ".mp4", ".mov"}
    images = sum(v for k, v in by_ext.items() if k.lower() in img_exts)
    audio = sum(v for k, v in by_ext.items() if k.lower() in aud_exts)
    video = sum(v for k, v in by_ext.items() if k.lower() in vid_exts)
    return {"images": images or None, "audio": audio or None,
            "video": video or None, "total": final.get("total")}


# ---------------------------------------------------------------------------
# 从文档提炼
# ---------------------------------------------------------------------------
def build_from_docs(sample: str, spec: dict, failures_data: dict, docs_meta: dict) -> dict:
    game_dir = Path(spec["game_dir"])
    fp = _fingerprint(game_dir)
    # engine 以现场重扫的规范名为准（案例库按指纹查，engine 必须与 fingerprint.engine 一致）；
    # _failures_raw 里的描述性标签（如「KiriKiri 加密」）另存 engine_label 供人读。
    engine = fp.get("engine") or failures_data.get(sample, {}).get("engine")
    engine_label = failures_data.get(sample, {}).get("engine")
    signals = fp["signals"]

    meta = docs_meta.get(sample, {})
    summary = {"images": meta.get("images"), "audio": meta.get("audio"),
               "video": meta.get("video"), "total": None}

    timing = {"detect": None, "extract": None, "postprocess": None,
              "verify": None, "manifest": None, "total": None}
    timing_note = meta.get("timing_note")
    if timing_note:
        timing["note"] = timing_note

    failures = failures_data.get(sample, {}).get("failures", [])

    return {
        "schema": SCHEMA_VERSION,
        "case_id": _case_id(engine, signals, sample, spec.get("discriminator")),
        "engine": engine,
        "engine_label": engine_label,
        "sample": sample,
        "game_dir": str(game_dir),
        "discriminator": spec.get("discriminator"),
        "fingerprint": fp,
        "decision": failures_data.get(sample, {}).get("decision", {}),
        "timing": timing,
        "result": {
            "ok": True,
            "source": "docs",
            "summary": summary,
            "media_minutes": meta.get("media_minutes"),
            "counts": None,
            "verify": None,
            "reconcile": None,
        },
        "failures": failures,
        "provenance": {
            "source": "docs-reconstructed",
            "manifest_path": None,
            "doc_refs": ["AGENTS.md 样本表", "verified-findings.md"],
            "generated_at": _now(),
        },
    }


# ---------------------------------------------------------------------------
# 写盘 / 索引 / 校验
# ---------------------------------------------------------------------------
def _case_filename(case: dict) -> str:
    eng = _slug(case["engine"])
    return f"{case['case_id']}-{eng}.json"


def write_case(case: dict) -> Path:
    CASES.mkdir(parents=True, exist_ok=True)
    path = CASES / _case_filename(case)
    content = json.dumps(case, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as out:
        out.write(content)
    return path


def build_all() -> list[dict]:
    failures_data = _load_failures()
    docs_meta = _load_docs_meta()
    cases = []
    existing = {case["sample"] for case in load_cases()}
    for sample, spec in SAMPLES.items():
        if sample in existing:
            continue
        if spec["manifest"] and not (ROOT / spec["manifest"]).is_file():
            print(f"[build] 跳过缺失 manifest: {spec['manifest']}")
            continue
        if spec["manifest"]:
            case = build_from_manifest(sample, spec, failures_data)
        else:
            case = build_from_docs(sample, spec, failures_data, docs_meta)
        cases.append(case)
    return cases


def write_all(cases: list[dict]) -> list[Path]:
    """Create cases without deleting or replacing existing files."""
    paths = [CASES / _case_filename(c) for c in cases]
    if len(set(paths)) != len(paths):
        raise FileExistsError("duplicate case destination")
    for path in paths:
        if path.exists():
            raise FileExistsError(path)
    return [write_case(c) for c in cases]


def load_cases() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(CASES.glob("*.json"))
            if path.name != "index.json" and not path.name.startswith("_")]


def build_index(cases: list[dict]) -> dict:
    """指纹签名 → case_id 列表。同签名对应多 case 时列出全部，靠 discriminator 区分。"""
    by_sig: dict[str, list[dict]] = {}
    for c in cases:
        sig = c["fingerprint"].get("signature")
        if not sig:
            continue
        by_sig.setdefault(sig, []).append({
            "case_id": c["case_id"],
            "engine": c["engine"],
            "engine_label": c.get("engine_label"),
            "sample": c["sample"],
            "discriminator": c.get("discriminator") or None,
            "provenance": c["provenance"]["source"],
        })
    return {
        "schema": "cases-index/1",
        "generated_at": _now(),
        "by_signature": by_sig,
        "cases": [{
            "case_id": c["case_id"],
            "engine": c["engine"],
            "sample": c["sample"],
            "signature": c["fingerprint"].get("signature"),
            "provenance": c["provenance"]["source"],
        } for c in cases],
    }


def validate_cases(cases: list[dict]) -> list[str]:
    """校验 schema + provenance 诚实。返回问题列表（空 = 全过）。"""
    problems = []
    seen_ids = set()
    for c in cases:
        cid = c.get("case_id", "")
        if cid in seen_ids:
            problems.append(f"重复 case_id: {cid}")
        seen_ids.add(cid)

        if c.get("schema") != SCHEMA_VERSION:
            problems.append(f"{cid}: schema 不是 {SCHEMA_VERSION}")

        for field in ("engine", "sample", "game_dir", "fingerprint",
                      "decision", "timing", "result", "failures", "provenance"):
            if field not in c:
                problems.append(f"{cid}: 缺字段 {field}")

        prov = c.get("provenance", {})
        src = prov.get("source")
        if src not in ("manifest", "docs-reconstructed"):
            problems.append(f"{cid}: provenance.source 非法: {src!r}")
        if src == "docs-reconstructed" and prov.get("manifest_path") is not None:
            problems.append(f"{cid}: docs 重建案例不许带 manifest_path")
        if src == "manifest" and not prov.get("manifest_path"):
            problems.append(f"{cid}: manifest 案例必须有 manifest_path")

        # 指纹签名一致性
        fp = c.get("fingerprint", {})
        sig = fp.get("signature")
        if src == "manifest" and not sig:
            problems.append(f"{cid}: manifest 案例必须有指纹签名")
        if fp.get("reconstructed") and src == "manifest":
            problems.append(f"{cid}: manifest 案例的指纹不该是 reconstructed")

        # failures 诚实
        for i, f in enumerate(c.get("failures", [])):
            if not f.get("ref"):
                problems.append(f"{cid}: failures[{i}] 缺 ref")
            for kf in ("stage", "symptom", "root_cause", "fix"):
                if not f.get(kf):
                    problems.append(f"{cid}: failures[{i}] 缺 {kf}")

        # docs 案例不许伪造 manifest 口径的 counts/verify/reconcile
        if src == "docs-reconstructed":
            res = c.get("result", {})
            for k in ("counts", "verify", "reconcile"):
                if res.get(k) is not None:
                    problems.append(f"{cid}: docs 重建案例的 result.{k} 必须是 null")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="cases/ 案例库构建器")
    ap.add_argument("--from-manifests", action="store_true", help="从 manifest 重建")
    ap.add_argument("--from-docs", action="store_true", help="从文档提炼")
    ap.add_argument("--index", action="store_true", help="重建索引")
    ap.add_argument("--validate", action="store_true", help="校验 schema + provenance")
    args = ap.parse_args(argv)

    do_build = args.from_manifests or args.from_docs
    do_index = args.index or do_build or not args.validate
    do_validate = args.validate or do_build or not args.index

    if do_build:
        cases = build_all()
        paths = write_all(cases)
        print(f"[build] 写入 {len(paths)} 个 case 到 {CASES}")
        for p in paths:
            print(f"  - {p.name}")

    if do_index:
        cases = load_cases()
        problems = validate_cases(cases)
        if problems:
            for problem in problems:
                print(problem)
            return 1
        index = build_index(cases)
        idx_path = CASES / "index.json"
        if idx_path.exists():
            previous = json.loads(idx_path.read_text(encoding="utf-8"))
            if previous.get("cases") == index["cases"] and previous.get("by_signature") == index["by_signature"]:
                index["generated_at"] = previous.get("generated_at")
        content = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
        if not idx_path.exists() or idx_path.read_text(encoding="utf-8") != content:
            idx_path.write_text(content, encoding="utf-8", newline="\n")
        print(f"[index] 写入 {idx_path}（{len(index['by_signature'])} 个签名）")

    if do_validate:
        cases = load_cases()
        problems = validate_cases(cases)
        if problems:
            print(f"[validate] 发现 {len(problems)} 个问题：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"[validate] {len(cases)} 个 case 全部通过 schema + provenance 校验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
