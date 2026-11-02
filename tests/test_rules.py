#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则引擎（rules/）的单元测试。

## 这些测试在守什么

指纹外置是一次**纯重构**：行为必须一模一样。golden 基线（tests/golden_detect.json）
守住了「9 个引擎在 17 个真实/构造样本上的判定结果」，但基线只覆盖**当前规则表实际写到的
路径**。解释器本身还有大量分支（`gate` / `alternatives` / `for_each` / 14 个谓词 /
6 种取值写法 / 模板渲染），任何一条写错都可能悄悄改变语义，而基线不一定踩得到。

所以这里分三层：
  ① **词汇表契约**——每个谓词、每种取值写法各测正反例，锁住语义；
  ② **结构不变量**——`gate` 真的表达嵌套、`alternatives` 真的只让第一个计分、
     `for_each` 真的逐项计分（这三条是外置时最容易写错的地方，写错就双计分/漏计分）；
  ③ **规则文件自检**——`validate()` 必须返回空，且它能抓出人为埋的错。

第 ③ 层的变异验证在 `test_validate_catches_*` 里：真往规则表里塞错误，
断言 `validate()` 点名它。没有这几条，`validate()` 只是个永远返回空列表的摆设。
"""

from __future__ import annotations

import json

import pytest

import rules


# --------------------------------------------------------------------------
# 构造库存的小工具
# --------------------------------------------------------------------------
def _inv(tmp_path, files=(), dirs=()):
    """按「文件相对路径 / 目录相对路径」造一棵树，返回 Inventory。"""
    for d in dirs:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    paths = []
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(b"\x00" * 4)
        paths.append(p)
    return rules.Inventory(
        game_dir=tmp_path,
        all_files=paths,
        top_dirs=sorted(d for d in dirs if "/" not in d and "\\" not in d),
    )


def _env(inv, probes=None):
    return {
        "inv": inv,
        "bindings": {},
        "game_dir": str(inv.game_dir),
        "probes": probes or {},
    }


def _one_engine(signals, name="X"):
    return rules.RuleSet(threshold=60, engines=[{"engine": name, "signals": signals}])


# --------------------------------------------------------------------------
# ① 谓词语义
# --------------------------------------------------------------------------
def test_pred_true_false_none(tmp_path):
    inv = _inv(tmp_path)
    e = _env(inv)
    assert rules.eval_pred(True, e) is True
    assert rules.eval_pred(False, e) is False
    assert rules.eval_pred(None, e) is False


def test_pred_list_is_all_shorthand(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3"])
    e = _env(inv)
    assert rules.eval_pred([{"file_exists": "a.xp3"}, {"file_exists": "a.xp3"}], e)
    assert not rules.eval_pred([{"file_exists": "a.xp3"}, {"file_exists": "b.xp3"}], e)


def test_pred_file_exists_and_dir_exists(tmp_path):
    inv = _inv(tmp_path, files=["a.txt"], dirs=["sub"])
    e = _env(inv)
    assert rules.eval_pred({"file_exists": "a.txt"}, e)
    assert not rules.eval_pred({"file_exists": "sub"}, e)      # 目录不是文件
    assert rules.eval_pred({"dir_exists": "sub"}, e)
    assert not rules.eval_pred({"dir_exists": "a.txt"}, e)     # 文件不是目录


def test_pred_top_dir_name_is_case_insensitive(tmp_path):
    inv = _inv(tmp_path, dirs=["RenPy"])
    e = _env(inv)
    assert rules.eval_pred({"top_dir_name": "renpy"}, e)
    assert not rules.eval_pred({"top_dir_name": "tyrano"}, e)


def test_pred_top_dir_suffix(tmp_path):
    inv = _inv(tmp_path, dirs=["Game_Data"])
    e = _env(inv)
    assert rules.eval_pred({"top_dir_suffix": "_Data"}, e)
    assert not rules.eval_pred({"top_dir_suffix": "_data"}, e)   # 后缀区分大小写


def test_pred_count_ext_needs_every_minimum(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3", "b.xp3", "c.rpa"])
    e = _env(inv)
    assert rules.eval_pred({"count_ext": {".xp3": 2}}, e)
    assert not rules.eval_pred({"count_ext": {".xp3": 3}}, e)
    # 多扩展名时**全部**满足才算成立
    assert rules.eval_pred({"count_ext": {".xp3": 2, ".rpa": 1}}, e)
    assert not rules.eval_pred({"count_ext": {".xp3": 2, ".rpa": 2}}, e)


def test_pred_count_ext_accepts_bare_ext(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3"])
    e = _env(inv)
    assert rules.eval_pred({"count_ext": {"xp3": 1}}, e)         # 不带点也认


def test_pred_count_any_ext_binds_n(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3", "b.xp3", "c.rpa"])
    e = _env(inv)
    assert rules.eval_pred({"count_any_ext": [".xp3", ".rpa"]}, e)
    assert e["bindings"]["n"] == 3                               # 求和，不是去重
    assert not rules.eval_pred({"count_any_ext": [".asar"]}, e)
    assert e["bindings"]["n"] == 0


def test_pred_any_file_binds_found_list(tmp_path):
    inv = _inv(tmp_path, files=["nw.dll", "icudtl.dat"])
    e = _env(inv)
    assert rules.eval_pred({"any_file": ["nw.dll", "node.dll", "icudtl.dat"]}, e)
    assert e["bindings"]["files"] == ["nw.dll", "icudtl.dat"]     # 只留存在的
    assert not rules.eval_pred({"any_file": ["node.dll"]}, e)


def test_pred_first_file_binds_which(tmp_path):
    inv = _inv(tmp_path, files=["boot.dfn"])
    e = _env(inv)
    assert rules.eval_pred({"first_file": ["cs2.exe", "boot.dfn"]}, e)
    assert e["bindings"]["which"] == "boot.dfn"                   # 按列表顺序取第一个存在的


def test_pred_any_name_requires_matching_ext(tmp_path):
    inv = _inv(tmp_path, files=["app.asar", "other.asar"])
    e = _env(inv)
    assert rules.eval_pred({"any_name": {"name": "app.asar", "ext": ".asar"}}, e)
    assert not rules.eval_pred({"any_name": {"name": "app.asar", "ext": ".rpa"}}, e)


def test_pred_known_names_counts_hits(tmp_path):
    inv = _inv(tmp_path, files=["data.xp3", "bgimage.xp3", "weird.xp3"])
    e = _env(inv)
    assert rules.eval_pred({"known_names": {"ext": ".xp3", "names": ["data.xp3", "bgimage.xp3"]}}, e)
    assert e["bindings"]["known"] == 2


def test_pred_magic_any_matches_head(tmp_path):
    inv = _inv(tmp_path)
    (tmp_path / "a.ypf").write_bytes(b"YPF\x00" + b"\x00" * 8)
    (tmp_path / "b.ypf").write_bytes(b"NOPE" + b"\x00" * 8)
    inv = rules.Inventory(game_dir=tmp_path,
                          all_files=[tmp_path / "a.ypf", tmp_path / "b.ypf"],
                          top_dirs=[])
    e = _env(inv)
    assert rules.eval_pred({"magic_any": {"ext": ".ypf", "hex": "59504600"}}, e)
    assert e["bindings"]["magicfile"] == "a.ypf"


def test_pred_magic_any_respects_limit(tmp_path):
    """`limit` 只查前 N 个候选——顺序来自 all_files 的遍历顺序。"""
    (tmp_path / "good.ypf").write_bytes(b"YPF\x00" + b"\x00" * 8)
    (tmp_path / "bad.ypf").write_bytes(b"NOPE" + b"\x00" * 8)
    # 把坏的放前面，limit=1 时查不到
    inv = rules.Inventory(game_dir=tmp_path,
                          all_files=[tmp_path / "bad.ypf", tmp_path / "good.ypf"],
                          top_dirs=[])
    e = _env(inv)
    assert not rules.eval_pred({"magic_any": {"ext": ".ypf", "hex": "59504600", "limit": 1}}, e)
    assert rules.eval_pred({"magic_any": {"ext": ".ypf", "hex": "59504600", "limit": 2}}, e)


def test_pred_magic_any_accepts_exts_list(tmp_path):
    (tmp_path / "a.int").write_bytes(b"KIF\x00" + b"\x00" * 8)
    inv = rules.Inventory(game_dir=tmp_path, all_files=[tmp_path / "a.int"], top_dirs=[])
    e = _env(inv)
    assert rules.eval_pred(
        {"magic_any": {"exts": [".int", ".dfn"], "hex": "4b494600"}}, e)


def test_pred_all_any_not(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3"])
    e = _env(inv)
    assert rules.eval_pred({"all": [{"file_exists": "a.xp3"}, {"file_exists": "a.xp3"}]}, e)
    assert rules.eval_pred({"any": [{"file_exists": "nope"}, {"file_exists": "a.xp3"}]}, e)
    assert rules.eval_pred({"not": {"file_exists": "nope"}}, e)
    assert not rules.eval_pred({"not": {"file_exists": "a.xp3"}}, e)


def test_pred_unknown_op_raises(tmp_path):
    inv = _inv(tmp_path)
    with pytest.raises(ValueError, match="未知谓词"):
        rules.eval_pred({"no_such_op": "x"}, _env(inv))


def test_pred_multi_key_dict_raises(tmp_path):
    inv = _inv(tmp_path)
    with pytest.raises(ValueError, match="单键"):
        rules.eval_pred({"file_exists": "a", "dir_exists": "b"}, _env(inv))


# --------------------------------------------------------------------------
# ② 模板渲染
# --------------------------------------------------------------------------
def test_render_bindings_and_count(tmp_path):
    inv = _inv(tmp_path, files=["a.arc", "b.arc"])
    e = _env(inv)
    e["bindings"].update({"n": 7, "files": ["a.dll", "b.dll"], "which": "cs2.exe"})
    assert rules._render("发现 {n} 个", e) == "发现 7 个"
    assert rules._render("运行时（{files}）", e) == "运行时（a.dll/b.dll）"   # list 用 / 连接
    assert rules._render("`{which}` 存在", e) == "`cs2.exe` 存在"
    assert rules._render("共 {count:.arc} 个", e) == "共 2 个"
    assert rules._render("{game_dir}", e) == str(inv.game_dir)


def test_render_unknown_placeholder_raises(tmp_path):
    """未知占位符必须炸——静默留 `{xxx}` 在证据里会变成肉眼才能发现的 bug。"""
    e = _env(_inv(tmp_path))
    with pytest.raises(KeyError, match="未知占位符"):
        rules._render("{no_such_binding}", e)


# --------------------------------------------------------------------------
# ③ 结构不变量（外置时最容易写错的三条）
# --------------------------------------------------------------------------
def test_gate_means_nesting_not_independent(tmp_path):
    """★不变量 2★ 父信号没触发，子信号一分都不加。

    这是 `if A: hit(70); hit(20)` 与 `hit(70); hit(20)` 的区别。
    写错的话，只带 .arc 但没有 AdvHD.exe 的目录会被误判成 AdvHD。
    """
    inv = _inv(tmp_path, files=["a.arc"])          # 只有 .arc，没有主程序
    rs = _one_engine([
        {"id": "main", "weight": 70, "when": {"file_exists": "AdvHD.exe"}, "detail": "主程序"},
        {"gate": "main", "weight": 20, "when": {"count_any_ext": [".arc"]}, "detail": "封包"},
    ])
    res = rules.evaluate(inv, rs=rs)
    assert res.hits == []                           # 父没触发 ⇒ 子不评估 ⇒ 0 分


def test_gate_fires_child_when_parent_fires(tmp_path):
    inv = _inv(tmp_path, files=["AdvHD.exe", "a.arc"])
    rs = _one_engine([
        {"id": "main", "weight": 70, "when": {"file_exists": "AdvHD.exe"}, "detail": "主程序"},
        {"gate": "main", "weight": 20, "when": {"count_any_ext": [".arc"]}, "detail": "封包"},
    ])
    res = rules.evaluate(inv, rs=rs)
    assert [(e, w) for e, w, _ in res.hits] == [("X", 70), ("X", 20)]


def test_alternatives_only_first_counts(tmp_path):
    """★不变量 3★ `alternatives` = elif：只有第一个成立的备选计分。

    写错成两条独立信号就会双计分（MZ 和 MV 的 js 文件同时存在时加 50 分）。
    """
    inv = _inv(tmp_path, files=["www/js/rmmz_core.js", "www/js/rpg_core.js"])
    rs = _one_engine([{
        "weight": 25,
        "alternatives": [
            {"when": {"file_exists": "www/js/rmmz_core.js"}, "detail": "MZ",
             "facts": {"variant": "MZ"}},
            {"when": {"file_exists": "www/js/rpg_core.js"}, "detail": "MV",
             "facts": {"variant": "MV"}},
        ],
    }])
    res = rules.evaluate(inv, rs=rs)
    assert [(e, w, d) for e, w, d in res.hits] == [("X", 25, "MZ")]   # 只 25，不是 50
    assert res.facts["variant"] == "MZ"


def test_alternatives_falls_through_to_second(tmp_path):
    inv = _inv(tmp_path, files=["www/js/rpg_core.js"])              # 只有 MV 的
    rs = _one_engine([{
        "weight": 25,
        "alternatives": [
            {"when": {"file_exists": "www/js/rmmz_core.js"}, "detail": "MZ"},
            {"when": {"file_exists": "www/js/rpg_core.js"}, "detail": "MV"},
        ],
    }])
    res = rules.evaluate(inv, rs=rs)
    assert [(w, d) for _, w, d in res.hits] == [(25, "MV")]


def test_alternatives_none_match_scores_nothing(tmp_path):
    inv = _inv(tmp_path, files=["readme.txt"])
    rs = _one_engine([{
        "weight": 25,
        "alternatives": [{"when": {"file_exists": "a.js"}, "detail": "A"}],
    }])
    assert rules.evaluate(inv, rs=rs).hits == []


def test_for_each_scores_per_matched_dir(tmp_path):
    """`for_each` 对每个匹配的顶层目录各算一次分（Unity 有多个 *_Data 时）。"""
    inv = _inv(tmp_path, dirs=["A_Data", "B_Data", "other"])
    rs = _one_engine([{
        "for_each": {"match": "top_dir_suffix", "arg": "_Data", "var": "d"},
        "weight": 60,
        "detail": "存在 `{d}/`",
    }])
    res = rules.evaluate(inv, rs=rs)
    assert sorted(d for _, _, d in res.hits) == ["存在 `A_Data/`", "存在 `B_Data/`"]
    assert sum(w for _, w, _ in res.hits) == 120


def test_for_each_none_matches(tmp_path):
    inv = _inv(tmp_path, dirs=["other"])
    rs = _one_engine([{
        "for_each": {"match": "top_dir_suffix", "arg": "_Data", "var": "d"},
        "weight": 60, "detail": "x",
    }])
    assert rules.evaluate(inv, rs=rs).hits == []


def test_facts_first_writer_wins(tmp_path):
    """事实是 `setdefault`——只有第一个命中的目录能写（原先只有第一个 *_Data 记版本）。"""
    inv = _inv(tmp_path, dirs=["A_Data", "B_Data"])
    rs = _one_engine([{
        "for_each": {"match": "top_dir_suffix", "arg": "_Data", "var": "d"},
        "weight": 60, "detail": "{d}",
        "facts": {"data_dir": "{d}"},
    }])
    res = rules.evaluate(inv, rs=rs)
    assert res.facts["data_dir"] == "A_Data"


def test_hit_order_follows_rule_file_order(tmp_path):
    """命中顺序 = 书写顺序，不按得分重排——`galgame_dispatch` 靠它保证同分排序。"""
    inv = _inv(tmp_path, files=["a.xp3", "a.rpa"])
    rs = rules.RuleSet(threshold=60, engines=[
        {"engine": "Low", "signals": [{"weight": 10, "detail": "low"}]},
        {"engine": "High", "signals": [{"weight": 90, "detail": "high"}]},
    ])
    res = rules.evaluate(inv, rs=rs)
    assert [e for e, _, _ in res.hits] == ["Low", "High"]


def test_silent_signal_scores_without_evidence(tmp_path):
    """silent 只是「不产生证据行」，分数照加。

    注意 `engines_hit` 由 hits 反推，所以 silent 命中的引擎不会出现在里面——
    这是有意的：`galgame_dispatch` 用 hits 建 Guess，silent 信号本身不该单独成条。
    """
    inv = _inv(tmp_path, files=["a.xp3"])
    rs = _one_engine([{"weight": 50, "when": {"file_exists": "a.xp3"},
                       "detail": "不该出现", "silent": True}])
    res = rules.evaluate(inv, rs=rs)
    assert res.hits == []
    assert res.engines_hit == set()


def test_silent_signal_contributes_score(tmp_path):
    """silent 只是「不产生证据行」，分数照加（`engines_hit` 也就不含它）。"""
    inv = _inv(tmp_path, files=["a.xp3"])
    rs = _one_engine([
        {"id": "a", "weight": 40, "when": {"file_exists": "a.xp3"}, "detail": "有证据"},
        {"weight": 20, "when": {"file_exists": "a.xp3"}, "silent": True},
    ])
    res = rules.evaluate(inv, rs=rs)
    assert sum(w for _, w, _ in res.hits) == 40     # silent 那条不在 hits 里


# --------------------------------------------------------------------------
# ④ 取值写法（facts）
# --------------------------------------------------------------------------
def test_fact_string_renders_placeholder(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3"])
    rs = _one_engine([{"weight": 10, "when": {"file_exists": "a.xp3"},
                       "detail": "d", "facts": {"f": "x={game_dir}"}}])
    res = rules.evaluate(inv, rs=rs)
    assert res.facts["f"] == f"x={inv.game_dir}"


def test_fact_path_joins_segments(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3"])
    rs = _one_engine([{"weight": 10, "when": {"file_exists": "a.xp3"}, "detail": "d",
                       "facts": {"p": {"path": ["{game_dir}", "sub"]}}}])
    res = rules.evaluate(inv, rs=rs)
    from pathlib import Path
    assert Path(res.facts["p"]) == inv.game_dir / "sub"


def test_fact_count_and_count_any(tmp_path):
    inv = _inv(tmp_path, files=["a.xp3", "b.xp3", "c.rpa"])
    rs = _one_engine([{"weight": 10, "when": True, "detail": "d",
                       "facts": {"xp3": {"count": ".xp3"},
                                 "all": {"count_any": [".xp3", ".rpa"]}}}])
    res = rules.evaluate(inv, rs=rs)
    assert res.facts["xp3"] == 2
    assert res.facts["all"] == 3


def test_fact_pred_boolean(tmp_path):
    inv = _inv(tmp_path, files=["GameAssembly.dll"])
    rs = _one_engine([{"weight": 10, "when": True, "detail": "d",
                       "facts": {"il2cpp": {"pred": {"file_exists": "GameAssembly.dll"}}}}])
    assert rules.evaluate(inv, rs=rs).facts["il2cpp"] is True


def test_fact_probe_called_with_rendered_args(tmp_path):
    inv = _inv(tmp_path, dirs=["G_Data"])
    seen = {}

    def fake_probe(path):
        seen["path"] = path
        return "2022.3.62f2"

    rs = _one_engine([{
        "weight": 60, "when": True, "detail": "d",
        "facts": {"ver": {"probe": "fake_probe",
                          "args": [{"path": ["{game_dir}", "G_Data"]}]}},
    }])
    res = rules.evaluate(inv, rs=rs, probes={"fake_probe": fake_probe})
    assert res.facts["ver"] == "2022.3.62f2"
    assert seen["path"] == str(inv.game_dir / "G_Data")


def test_fact_probe_missing_raises(tmp_path):
    inv = _inv(tmp_path)
    rs = _one_engine([{"weight": 10, "when": True, "detail": "d",
                       "facts": {"x": {"probe": "nope"}}}])
    with pytest.raises(KeyError, match="未注册的探针"):
        rules.evaluate(inv, rs=rs)


def test_fact_none_is_skipped(tmp_path):
    """探针返回 None（没查到版本号）时**不写这个事实**，而不是写个 None 进去。"""
    inv = _inv(tmp_path)
    rs = _one_engine([{"weight": 10, "when": True, "detail": "d",
                       "facts": {"ver": {"probe": "p"}, "other": "kept"}}])
    res = rules.evaluate(inv, rs=rs, probes={"p": lambda: None})
    assert "ver" not in res.facts
    assert res.facts["other"] == "kept"


def test_fact_unknown_form_raises(tmp_path):
    inv = _inv(tmp_path)
    rs = _one_engine([{"weight": 10, "when": True, "detail": "d",
                       "facts": {"x": {"no_such_form": 1}}}])
    with pytest.raises(ValueError, match="不认识的取值写法"):
        rules.evaluate(inv, rs=rs)


# --------------------------------------------------------------------------
# ⑤ 规则文件本身
# --------------------------------------------------------------------------
def test_rules_file_loads():
    rs = rules.load()
    assert rs.version == 1
    assert rs.threshold == 60
    assert len(rs.engines) == 10


def test_rules_file_declares_its_probes():
    rs = rules.load()
    assert set(rs.probes) == {"find_unity_version", "unity_big_files"}


def test_validate_returns_no_problems():
    assert rules.validate() == []


def test_engine_names_are_unique():
    names = [b["engine"] for b in rules.load().engines]
    assert len(names) == len(set(names)), f"引擎名重复：{names}"


def test_engine_order_is_stable():
    """引擎块顺序影响同分排序，锁住它防止无意重排。"""
    assert [b["engine"] for b in rules.load().engines] == [
        "Unity", "KiriKiri", "Ren'Py", "Tyrano/Electron", "RPG Maker",
        "AdvHD", "Yu-Ris", "ExHIBIT", "CatSystem2", "Artemis",
    ]


def test_every_engine_has_at_least_one_signal():
    for b in rules.load().engines:
        assert b.get("signals"), f"{b['engine']} 没有任何信号"


# ---- 变异验证：真埋错误，validate() 必须点名 ----------------------------
def _with_signal(tmp_path, mutate):
    """复制一份真规则表，对第 0 个引擎的第 0 条信号做修改，写到临时文件再 load。"""
    data = json.loads(rules.RULES_PATH.read_text(encoding="utf-8"))
    mutate(data["engines"][0]["signals"][0])
    p = tmp_path / "engines.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return rules.load(p)


def test_validate_catches_unknown_op(tmp_path):
    rs = _with_signal(tmp_path, lambda s: s.update(when={"no_such_op": "x"}))
    problems = rules.validate(rs, probes={"find_unity_version", "unity_big_files"})
    assert any("未知谓词" in p for p in problems), problems


def test_validate_catches_missing_detail(tmp_path):
    rs = _with_signal(tmp_path, lambda s: s.pop("detail", None))
    problems = rules.validate(rs, probes={"find_unity_version", "unity_big_files"})
    assert any("缺 detail" in p for p in problems), problems


def test_validate_catches_undeclared_probe(tmp_path):
    rs = _with_signal(
        tmp_path, lambda s: s["facts"].update({"bogus": {"probe": "not_a_probe"}}))
    problems = rules.validate(rs, probes={"find_unity_version", "unity_big_files"})
    assert any("not_a_probe" in p for p in problems), problems


def test_validate_catches_declared_but_unused_probe(tmp_path):
    """声明了探针但规则表里没用 → 也报（防止 `probes` 列表变成垃圾场）。"""
    rs = _with_signal(tmp_path, lambda s: None)
    rs.probes = tuple(rs.probes) + ("never_used",)
    problems = rules.validate(rs)
    assert any("never_used" in p and "没用到" in p for p in problems), problems


def test_validate_catches_gate_pointing_forward(tmp_path):
    """`gate` 指向写在后面的信号 → 报（那时父信号还没评估，永远不触发）。"""
    data = json.loads(rules.RULES_PATH.read_text(encoding="utf-8"))
    sigs = data["engines"][0]["signals"]
    sigs[0]["gate"] = sigs[-1].get("id") or "later"
    p = tmp_path / "engines.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    problems = rules.validate(rules.load(p),
                              probes={"find_unity_version", "unity_big_files"})
    assert any("gate" in x for x in problems), problems


def test_validate_catches_alternatives_missing_detail(tmp_path):
    data = json.loads(rules.RULES_PATH.read_text(encoding="utf-8"))
    # RPG Maker 的 alternatives 在 signals[1]
    alt = data["engines"][4]["signals"][1]["alternatives"][0]
    alt.pop("detail", None)
    p = tmp_path / "engines.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    problems = rules.validate(rules.load(p),
                              probes={"find_unity_version", "unity_big_files"})
    assert any("alt[0]" in x and "缺 detail" in x for x in problems), problems


# --------------------------------------------------------------------------
# ⑥ 与 galgame_dispatch 的等价性（规则表 vs golden 基线已覆盖，这里只锁接口）
# --------------------------------------------------------------------------
def test_dispatch_scan_accepts_rules_path(tmp_path):
    """`scan(rules_path=...)` 能换一套规则表跑——这是「规则数据驱动」的可验证证据。"""
    import galgame_dispatch as gd

    game = tmp_path / "game"
    game.mkdir()
    (game / "a.xp3").write_bytes(b"XP3\r\n \n\x1a\x8bg\x01" + b"\x00" * 8)

    # 真规则表 → KiriKiri
    assert gd.scan(game).best.engine == "KiriKiri"

    # 换成只认 .rpa 的规则表 → 同一个目录判不出 KiriKiri
    fake = tmp_path / "engines.json"
    fake.write_text(json.dumps({
        "version": 1, "threshold": 60,
        "engines": [{"engine": "FakeOnly", "signals": [
            {"weight": 99, "when": {"count_any_ext": [".rpa"]}, "detail": "rpa"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    rep = gd.scan(game, rules_path=str(fake))
    assert rep.guesses == []


def test_dispatch_threshold_comes_from_rules_file(tmp_path):
    """阈值也来自规则表——改 JSON 就能改判定线，不用改 Python。"""
    import galgame_dispatch as gd

    game = tmp_path / "game"
    game.mkdir()
    (game / "a.rpa").write_bytes(b"RPA-3.0 " + b"\x00" * 8)

    fake = tmp_path / "engines.json"
    fake.write_text(json.dumps({
        "version": 1, "threshold": 50,
        "engines": [{"engine": "Low", "signals": [
            {"weight": 55, "when": {"count_any_ext": [".rpa"]}, "detail": "rpa"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    rep = gd.scan(game, rules_path=str(fake))
    assert rep.best.engine == "Low"
    assert rep.best.score == 55
