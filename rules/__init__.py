#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎指纹规则引擎 —— 「规则表 + 解释器」。

## 为什么要有这一层

原先 9 个引擎的指纹全部硬编码在 `galgame_dispatch.scan()` 的函数体里：17 个 `hit()`
调用散落在 if/elif 分支中。加一个引擎就得改 Python 控制流，改权重得翻代码，
决策树文档与代码也容易走岔。外置成 `rules/engines.json` 之后，**权重、证据文案、
魔数、扩展名、探测路径全部是数据**，加引擎 = 改 JSON。

## 什么没有数据化（刻意的取舍）

有副作用的探测**不**进 JSON，而是以「具名探针（probe）」的形式由调用方注入：

  * `find_unity_version()` 要读二进制头部
  * `biggest_files()` 要 stat 目录
  * `garbro_probe()` 要起子进程
  * `demojibake()` 要试编码还原

把它们塞进 JSON 就得发明一门带 IO 的小语言，比现在难维护得多。规则文件只描述
**「什么条件加多少分、证据怎么写、顺带记哪些事实」**，探针只负责取数。

## 三条不变量（测试锁着）

1. **规则文件与解释器都不做内容级猜测**——判据一律是「文件存在 / 扩展名计数 /
   魔数命中 / 目录名」，与 `verified-findings.md` 里证伪过的启发式无关。
2. **`gate` 表达嵌套**：`gate` 指向的信号没触发，本条就不评估。这精确复刻了
   原先 `if A: hit(...); if B: hit(...)` 的语义（B 只在 A 成立时算分）。
3. **`mode: "first"` 表达 `elif`**：备选里只有第一个成立的那条计分。原先
   AdvHD / Yu-Ris / ExHIBIT / CatSystem2 都是「主判据 A，否则主判据 B」，
   写成两条独立信号会双计分——这是外置时最容易踩的坑。

词汇表见 `rules/engines.json` 的 `_help` 段。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

RULES_PATH = Path(__file__).resolve().parent / "engines.json"

Probe = Callable[..., Any]


# --------------------------------------------------------------------------
# 库存：一次遍历的结果，所有谓词都在它上面求值
# --------------------------------------------------------------------------
@dataclass
class Inventory:
    """游戏目录的一次遍历快照。只读。

    `all_files` 必须保持遍历顺序——`magic_any` 取「前 N 个候选」时依赖它，
    顺序变了就会去查不同的文件，结论可能跟着变。
    """
    game_dir: Path
    all_files: list[Path] = field(default_factory=list)
    top_dirs: list[str] = field(default_factory=list)
    truncated: bool = False

    def __post_init__(self) -> None:
        by_ext: dict[str, list[Path]] = {}
        counts: dict[str, int] = {}
        for p in self.all_files:
            ext = p.suffix.lower()
            by_ext.setdefault(ext, []).append(p)
            counts[ext] = counts.get(ext, 0) + 1
        self._by_ext = by_ext
        self._counts = counts

    @property
    def by_ext(self) -> dict[str, list[Path]]:
        return self._by_ext

    @property
    def counts(self) -> dict[str, int]:
        return self._counts

    def files_with_exts(self, exts: list[str]) -> list[Path]:
        """按原遍历顺序返回扩展名落在 `exts` 里的文件（多扩展名时顺序必须一致）。"""
        want = {e.lower() for e in exts}
        return [p for p in self.all_files if p.suffix.lower() in want]


def read_head(p: Path, n: int = 16) -> bytes:
    try:
        with p.open("rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


# --------------------------------------------------------------------------
# 规则集
# --------------------------------------------------------------------------
@dataclass
class RuleSet:
    threshold: int
    engines: list[dict]
    version: int = 1
    probes: tuple[str, ...] = ()


def load(path: Path | str | None = None) -> RuleSet:
    """读取规则文件。坏文件一律抛异常——规则表静默降级等于检测悄悄失效。"""
    p = Path(path) if path else RULES_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    engines = data.get("engines")
    if not isinstance(engines, list) or not engines:
        raise ValueError(f"{p} 里没有 `engines` 列表")
    return RuleSet(
        threshold=int(data.get("threshold", 60)),
        engines=engines,
        version=int(data.get("version", 1)),
        probes=tuple(data.get("probes") or ()),
    )


# --------------------------------------------------------------------------
# 模板渲染
# --------------------------------------------------------------------------
_PH = re.compile(r"\{([A-Za-z_][\w:.]*)\}")


def _render(tpl: str, env: dict) -> str:
    """把 `{d}` / `{count:.arc}` / `{game_dir}` 之类占位符替换掉。

    占位符只允许三种来源，写错就抛 KeyError（不要静默留 `{xxx}` 在证据里——
    那会让「证据对不上」变成肉眼才能发现的 bug）。
    """
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key.startswith("count:"):
            return str(env["inv"].counts.get(key[6:].lower(), 0))
        if key in env["bindings"]:
            val = env["bindings"][key]
            if isinstance(val, (list, tuple)):
                return "/".join(str(x) for x in val)
            return str(val)
        if key == "game_dir":
            return env["game_dir"]
        raise KeyError(f"未知占位符 {{{key}}}（模板：{tpl!r}）")

    return _PH.sub(sub, tpl)


# --------------------------------------------------------------------------
# 谓词求值
# --------------------------------------------------------------------------
def _norm_ext(ext: str) -> str:
    e = ext.lower()
    return e if e.startswith(".") else "." + e


def eval_pred(pred: Any, env: dict) -> bool:
    """求值一个谓词。副作用是往 `env["bindings"]` 里放绑定（files/which/known/n…）。"""
    if pred is True:
        return True
    if pred is False or pred is None:
        return False
    if isinstance(pred, list):                      # 列表 = all 的简写
        return all(eval_pred(p, env) for p in pred)
    if not isinstance(pred, dict) or len(pred) != 1:
        raise ValueError(f"谓词必须是 {{op: arg}} 单键对象：{pred!r}")

    op, arg = next(iter(pred.items()))
    inv: Inventory = env["inv"]

    if op == "all":
        return all(eval_pred(p, env) for p in arg)
    if op == "any":
        return any(eval_pred(p, env) for p in arg)
    if op == "not":
        return not eval_pred(arg, env)

    if op == "file_exists":
        return (inv.game_dir / _render(arg, env)).is_file()
    if op == "dir_exists":
        return (inv.game_dir / _render(arg, env)).is_dir()
    if op == "top_dir_name":
        return any(d.lower() == str(arg).lower() for d in inv.top_dirs)
    if op == "top_dir_suffix":
        return any(d.endswith(str(arg)) for d in inv.top_dirs)

    if op == "count_ext":
        for ext, minimum in arg.items():
            if inv.counts.get(_norm_ext(ext), 0) < int(minimum):
                return False
        return True

    if op == "count_any_ext":
        n = sum(inv.counts.get(_norm_ext(e), 0) for e in arg)
        env["bindings"]["n"] = n
        return n >= 1

    if op == "any_file":
        found = [name for name in arg if (inv.game_dir / name).exists()]
        env["bindings"]["files"] = found
        return bool(found)

    if op == "first_file":
        for name in arg:
            if (inv.game_dir / name).exists():
                env["bindings"]["which"] = name
                return True
        return False

    if op == "any_name":
        want = str(arg["name"]).lower()
        ext = _norm_ext(arg["ext"])
        return any(p.name.lower() == want for p in inv.by_ext.get(ext, []))

    if op == "known_names":
        ext = _norm_ext(arg["ext"])
        names = {str(n).lower() for n in arg["names"]}
        k = sum(1 for p in inv.by_ext.get(ext, []) if p.name.lower() in names)
        env["bindings"]["known"] = k
        return k > 0

    if op == "magic_any":
        exts = arg.get("exts") or [arg["ext"]]
        limit = int(arg.get("limit", 5))
        want = bytes.fromhex(str(arg["hex"]))
        for p in inv.files_with_exts(list(exts))[:limit]:
            if read_head(p, len(want)) == want:
                env["bindings"]["magicfile"] = p.name
                return True
        return False

    raise ValueError(f"未知谓词 op={op!r}（规则文件写错了？）")


# --------------------------------------------------------------------------
# 信号执行
# --------------------------------------------------------------------------
def _clone(env: dict, bindings: dict | None = None) -> dict:
    b = dict(env["bindings"])
    if bindings:
        b.update(bindings)
    return {
        "inv": env["inv"],
        "bindings": b,
        "game_dir": env["game_dir"],
        "probes": env["probes"],
    }


def _resolve(val: Any, env: dict) -> Any:
    """把规则文件里的一种「取值写法」变成真实值。

    支持五种写法（见 engines.json 的 `_help.事实取值`）：
    字符串（渲染占位符）、`{"path": [...]}`、`{"count": ext}`、
    `{"count_any": [...]}`、`{"pred": 谓词}`、`{"probe": 名, "args": [...]}`。
    事实与探针实参共用这一套，免得两处各写一份。
    """
    if isinstance(val, str):
        return _render(val, env)
    if not isinstance(val, dict):
        return val

    if "probe" in val:
        fn: Probe | None = env["probes"].get(val["probe"])
        if fn is None:
            raise KeyError(f"用了未注册的探针 {val['probe']!r}")
        raw = val.get("args")
        if raw is None:
            raw = [val["arg"]] if "arg" in val else []
        return fn(*[_resolve(a, env) for a in raw])
    if "path" in val:
        return str(Path(*[_render(x, env) for x in val["path"]]))
    if "count" in val:
        return env["inv"].counts.get(_norm_ext(str(val["count"])), 0)
    if "count_any" in val:
        return sum(env["inv"].counts.get(_norm_ext(str(e)), 0)
                   for e in val["count_any"])
    if "pred" in val:
        return eval_pred(val["pred"], _clone(env))
    raise ValueError(f"不认识的取值写法：{val!r}")


def _apply_facts(spec: dict | None, env: dict, facts: dict) -> None:
    """把信号的 `facts` 写进结果。`setdefault` 语义 = 先写者优先。

    先写者优先是为了精确复刻原先「只有第一个 `*_Data` 目录才记事实」的行为。
    """
    if not spec:
        return
    for key, val in spec.items():
        val = _resolve(val, env)
        if val is None:
            continue
        facts.setdefault(key, val)


def _match_all(for_each: dict, inv: Inventory) -> list[str]:
    """`for_each` 的取值来源。目前只支持两种顶层目录匹配。"""
    kind, arg = for_each.get("match"), str(for_each.get("arg", ""))
    if kind == "top_dir_suffix":
        return [d for d in inv.top_dirs if d.endswith(arg)]
    if kind == "top_dir_name":
        return [d for d in inv.top_dirs if d.lower() == arg.lower()]
    raise ValueError(f"未知 for_each.match={kind!r}")


def _run_signal(sig: dict, env: dict, fired: dict[str, list[dict]],
                hits: list[tuple[str, int, str]], facts: dict) -> bool:
    engine = sig["_engine"]

    # ---- mode:"first" —— 精确复刻 elif：只有第一个成立的备选计分 ----
    if "alternatives" in sig:
        for alt in sig["alternatives"]:
            e = _clone(env)
            if eval_pred(alt.get("when", True), e):
                hits.append((engine, int(sig["weight"]), _render(alt["detail"], e)))
                _apply_facts(alt.get("facts"), e, facts)
                if sig.get("id"):
                    fired.setdefault(sig["id"], []).append(e["bindings"])
                if alt.get("id"):
                    fired.setdefault(alt["id"], []).append(e["bindings"])
                return True
        return False

    # ---- for_each —— 每个匹配项各算一次（Unity 的 *_Data 循环） ----
    for_each = sig.get("for_each")
    if for_each:
        vals = _match_all(for_each, env["inv"])
        any_fired = False
        for v in vals:
            e = _clone(env, {for_each["var"]: v})
            if eval_pred(sig.get("when", True), e):
                hits.append((engine, int(sig["weight"]), _render(sig["detail"], e)))
                _apply_facts(sig.get("facts"), e, facts)
                if sig.get("id"):
                    fired.setdefault(sig["id"], []).append(e["bindings"])
                any_fired = True
        return any_fired

    # ---- 普通信号 ----
    e = _clone(env)
    if eval_pred(sig.get("when", True), e):
        if not sig.get("silent"):
            hits.append((engine, int(sig["weight"]), _render(sig["detail"], e)))
        _apply_facts(sig.get("facts"), e, facts)
        if sig.get("id"):
            fired.setdefault(sig["id"], []).append(e["bindings"])
        return True
    return False


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
@dataclass
class Result:
    hits: list[tuple[str, int, str]] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    engines_hit: set[str] = field(default_factory=set)
    # 命中信号 id 集合（去重）。**格式签名**的稳定来源：渲染后的 detail 文案带
    # 游戏专属计数（"发现 12 个 .xp3"），跨游戏不可比；信号 id 才是「哪些格式
    # 特征被认出」的可比口径。cases/ 案例库用它算指纹签名。
    fired_ids: set[str] = field(default_factory=set)


def evaluate(inv: Inventory, probes: dict[str, Probe] | None = None,
             rs: RuleSet | None = None) -> Result:
    """对一份库存跑完整张规则表，返回 (engine, weight, detail) 命中列表与事实。

    命中顺序 = 规则文件里的书写顺序。`galgame_dispatch` 依赖这个顺序来保证
    「同分引擎的排序」与历史一致，所以**不要按得分重排**。
    """
    rs = rs or load()
    res = Result()
    env = {
        "inv": inv,
        "bindings": {},
        "game_dir": str(inv.game_dir),
        "probes": probes or {},
    }
    fired: dict[str, list[dict]] = {}

    for engine_block in rs.engines:
        engine = engine_block["engine"]
        for sig in engine_block["signals"]:
            sig = {**sig, "_engine": engine}

            gate = sig.get("gate")
            if gate:
                parents = fired.get(gate)
                if not parents:
                    continue
                for pb in parents:
                    _run_signal(sig, _clone(env, pb), fired, res.hits, res.facts)
            else:
                _run_signal(sig, _clone(env), fired, res.hits, res.facts)

    res.engines_hit = {e for e, _, _ in res.hits}
    res.fired_ids = set(fired)
    return res


# --------------------------------------------------------------------------
# 校验（测试用）：把规则文件里所有谓词/探针名都走一遍，抓拼写错误
# --------------------------------------------------------------------------
_KNOWN_OPS = {
    "all", "any", "not", "file_exists", "dir_exists", "top_dir_name",
    "top_dir_suffix", "count_ext", "count_any_ext", "any_file", "first_file",
    "any_name", "known_names", "magic_any",
}


def validate(rs: RuleSet | None = None, probes: set[str] | None = None) -> list[str]:
    """静态检查规则文件，返回问题列表（空 = 没问题）。

    覆盖：谓词名、探针名、`gate` 指向的信号是否真的存在（且写在前面的位置），
    以及每条非 silent 信号是否都有 `detail`。

    `probes` 不给时用规则文件自己声明的 `probes` 列表——这样单跑
    `rules.validate()` 也能查出「用了没声明的探针」和「声明了没人用的探针」。
    """
    rs = rs or load()
    problems: list[str] = []
    declared = set(rs.probes)
    probes = declared if probes is None else set(probes)
    used: set[str] = set()

    def walk(pred: Any, where: str) -> None:
        if pred is None or isinstance(pred, bool):
            return
        if isinstance(pred, list):
            for i, p in enumerate(pred):
                walk(p, f"{where}[{i}]")
            return
        if not isinstance(pred, dict) or len(pred) != 1:
            problems.append(f"{where}: 谓词必须是单键对象，实际 {pred!r}")
            return
        op, arg = next(iter(pred.items()))
        if op not in _KNOWN_OPS:
            problems.append(f"{where}: 未知谓词 {op!r}")
            return
        if op in ("all", "any"):
            for i, p in enumerate(arg):
                walk(p, f"{where}.{op}[{i}]")
        elif op == "not":
            walk(arg, f"{where}.not")

    for block in rs.engines:
        engine = block.get("engine")
        if not engine:
            problems.append("有引擎块缺少 `engine` 名")
            continue
        seen_ids: set[str] = set()
        for si, sig in enumerate(block.get("signals", [])):
            where = f"{engine}.signals[{si}]"
            gate = sig.get("gate")
            if gate and gate not in seen_ids:
                problems.append(f"{where}: gate={gate!r} 指向未定义或后置的信号")
            if "alternatives" in sig:
                for ai, alt in enumerate(sig["alternatives"]):
                    walk(alt.get("when"), f"{where}.alt[{ai}].when")
                    if not alt.get("detail"):
                        problems.append(f"{where}.alt[{ai}]: 缺 detail")
                    for fk, fv in (alt.get("facts") or {}).items():
                        _check_fact(fk, fv, f"{where}.alt[{ai}].facts", probes,
                                    problems, used)
            else:
                walk(sig.get("when"), f"{where}.when")
                if not sig.get("silent") and not sig.get("detail"):
                    problems.append(f"{where}: 非 silent 信号缺 detail")
            for fk, fv in (sig.get("facts") or {}).items():
                _check_fact(fk, fv, f"{where}.facts", probes, problems, used)
            if sig.get("id"):
                seen_ids.add(sig["id"])
            for alt in sig.get("alternatives", []) or []:
                if alt.get("id"):
                    seen_ids.add(alt["id"])

    for name in sorted(declared - used):
        problems.append(f"声明了探针 {name!r} 但规则表里没用到")
    for name in sorted(used - declared):
        problems.append(f"规则表用了探针 {name!r} 但 `probes` 里没声明")
    return problems


def _check_fact(key: str, val: Any, where: str, probes: set[str],
                problems: list[str], used: set[str]) -> None:
    if isinstance(val, dict) and "probe" in val:
        name = val["probe"]
        used.add(name)
        if name not in probes:
            problems.append(f"{where}.{key}: 未注册的探针 {name!r}")
