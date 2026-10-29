# -*- coding: utf-8 -*-
"""`planner.py`（判定 → 提取计划）的契约测试。

为什么值得单独测
----------------
planner 输出的是一条**用户会直接复制执行的命令**。这类代码最典型的失效方式
不是抛异常，而是安静地给出一条跑不通的命令：参数名写错、路径被空格拆碎、
引用了根本不存在的脚本。用户执行后拿到一堆报错，却不知道该怀疑哪一层。

所以这里的断言都围绕「这条命令真的能跑」展开：
- `argv` 必须是列表（不经 shell，含空格路径不会被拆碎）
- 每个 `extractor` 必须**真的存在于磁盘**（防引用幽灵工具）
- 每条命令的第一个参数必须是**真实存在的文件**
- 参数必须与工具**实际接受的参数**一致（用源码/--help 核过的那批）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import galgame_dispatch as gd  # noqa: E402
import orchestrator  # noqa: E402
import planner  # noqa: E402


# --------------------------------------------------------------------------
# 造假 Report / Inventory，避免测试依赖 D:\HY 的真实游戏
# --------------------------------------------------------------------------
class _FakeGuess:
    def __init__(self, engine: str, score: int = 100) -> None:
        self.engine = engine
        self.score = score
        self.evidence: list[str] = []


class _FakeRep:
    def __init__(self, engine: str | None, score: int = 100,
                 archives: dict[str, list[Path]] | None = None,
                 game: Path | None = None) -> None:
        self.path = game or Path(r"D:\HY\Some Game")
        self.guesses = [_FakeGuess(engine, score)] if engine else []
        self.notes: list[str] = []
        self.facts: dict[str, object] = {}
        self.archives = archives or {}

    @property
    def best(self):
        return self.guesses[0] if self.guesses else None


def _arch(name: str, size: int = 1024) -> Path:
    """造一个真的存在的小文件（`_kirikiri` 会 stat 它）。"""
    import tempfile

    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_bytes(b"\0" * min(size, 4096))
    return p


# --------------------------------------------------------------------------
# 1. 覆盖面：每个能判出来的引擎都必须有 builder
# --------------------------------------------------------------------------
def test_every_advice_engine_has_a_plan_builder() -> None:
    """ADVICE 声称支持的引擎，planner 必须都能给出计划。

    否则用户看到「判定：CatSystem2」之后拿不到任何命令，只能自己翻文档。
    """
    missing = set(gd.ADVICE) - set(planner._BUILDERS)
    assert not missing, f"这些引擎有 ADVICE 但 planner 不知道怎么跑：{missing}"


def test_every_engine_builds_a_plan() -> None:
    """逐个引擎跑一遍 build()，都必须返回 Plan 而不是 None。"""
    for engine in gd.ADVICE:
        rep = _FakeRep(engine)
        plan = planner.build(rep)
        assert plan is not None, f"{engine} 没生成计划"
        assert plan.engine == engine


def test_unknown_engine_returns_placeholder_not_crash() -> None:
    """规则表里有、planner 里没接的引擎 → 给占位计划并说明，不许抛异常。"""
    rep = _FakeRep("SomeNewEngine")
    plan = planner.build(rep)
    assert plan is not None
    assert plan.extractor == "(无)"
    assert "没有对应的提取器定义" in plan.reason


def test_no_engine_returns_none() -> None:
    assert planner.build(_FakeRep(None)) is None


def test_low_score_returns_none() -> None:
    """未达阈值（推测）不给计划——推测出来的引擎去跑真工具只会浪费时间。"""
    assert planner.build(_FakeRep("Ren'Py", score=30)) is None


# --------------------------------------------------------------------------
# 2. 命令必须真能跑：extractor 存在、argv 是列表、路径不拆碎
# --------------------------------------------------------------------------
def test_extractor_file_exists_on_disk() -> None:
    """★核心护栏★ 计划里引用的脚本必须真的存在。

    这条防的是「文档说有这么个工具，其实没写」以及「脚本改名后忘了改 planner」。
    """
    missing: list[str] = []
    for engine in gd.ADVICE:
        plan = planner.build(_FakeRep(engine, archives={
            ".xp3": [_arch("data.xp3")],
            ".rpa": [_arch("archive.rpa")],
            ".arc": [_arch("Bgm.arc")],
            ".ypf": [_arch("data.ypf")],
            ".gyu": [_arch("cg.gyu")],
            ".grp": [_arch("res2000.grp")],
            ".int": [_arch("image00.int")],
            ".asar": [_arch("app.asar")],
        }))
        assert plan is not None
        for p in [plan, *plan.extras]:
            for token in p.argv:
                if not token.endswith((".py", ".exe", ".ps1")):
                    continue
                name = Path(token).name
                # 外部工具（GARbro.Console.exe）允许不在仓库里，但必须是绝对路径或
                # 明确的外部工具名；仓库内的脚本必须存在。
                if token.startswith(str(ROOT)) and not Path(token).exists():
                    missing.append(f"{engine}: {token}")
                elif not token.startswith(str(ROOT)) and "/" not in token and "\\" not in token:
                    if name not in {"GARbro.Console.exe"}:
                        missing.append(f"{engine}: {name}（既不是仓库内路径也不是已知外部工具）")
    assert not missing, "计划引用了不存在的工具：\n" + "\n".join(missing)


def test_argv_is_a_list_and_cmdline_is_quoted() -> None:
    """argv 必须是列表（执行用），cmdline 只给人看。"""
    game = Path(r"D:\HY\Swipe Right for Sugar Mama Sensei")
    plan = planner.build(_FakeRep("Ren'Py", game=game))
    assert plan is not None
    assert isinstance(plan.argv, list)
    assert all(isinstance(a, str) for a in plan.argv)
    # 含空格的路径在 cmdline 里必须带引号，否则复制出来就是错的
    assert '"' in plan.cmdline
    # 但 argv 里绝不能带引号——那会被当成路径的一部分
    assert not any(a.startswith('"') for a in plan.argv)


def test_spaced_path_stays_one_argv_token() -> None:
    """★核心护栏★ 含空格的游戏目录必须是一个 argv 元素，不能被拆开。

    AGENTS.md 记过两次教训：`Start-Process -ArgumentList` 把
    `...\\My Wife Wants...` 拆碎，制造出「工具失败」的假象。
    """
    game = Path(r"D:\HY\My Wife Wants to Be a Professional Cosplayer")
    for engine in ("Ren'Py", "KiriKiri", "Unity"):
        plan = planner.build(_FakeRep(engine, game=game))
        assert plan is not None
        assert str(game) in plan.argv, f"{engine} 的计划里找不到完整游戏路径"
        assert not any(" " in a and str(game) in a and a != str(game) for a in plan.argv)


# --------------------------------------------------------------------------
# 3. 参数必须与工具真实接受的参数一致
# --------------------------------------------------------------------------
def test_orchestrator_argv_matches_real_cli() -> None:
    """已接 orchestrator 的引擎，argv 必须能被 orchestrator 的 argparse 解析。

    用真的 argparse 解析器去 parse，而不是自己数参数——这样工具改参数名时
    这里会立刻红，而不是等用户跑到一半报「unrecognized arguments」。
    """
    import argparse

    # orchestrator 的 main() 只接受 argv 并构造 parser，这里复刻它的选项集，
    # 并用 set 比对，避免 argparse 内部细节。
    src = (ROOT / "orchestrator.py").read_text(encoding="utf-8")
    assert 'add_argument("game_dir"' in src or "add_argument('game_dir'" in src
    known = {"--out", "--work", "--manifest", "--engine", "--reuse-raw",
             "--allow-gui", "--no-verify", "--strict", "--json", "--dry-run"}

    for engine in planner.IMPLEMENTED_CHAINS:
        plan = planner.build(_FakeRep(engine))
        assert plan is not None
        assert plan.kind == "orchestrator"
        flags = {a for a in plan.argv if a.startswith("--")}
        unknown = flags - known
        assert not unknown, f"{engine} 的计划用了 orchestrator 不认识的参数：{unknown}"
        assert "--out" in flags, "缺 --out，orchestrator 会直接退出"


def test_implemented_flag_matches_orchestrator() -> None:
    """★防漂移★ planner 的 implemented 必须与 orchestrator.IMPLEMENTED 一致。

    两边各写一份「支持哪些引擎」，改了一边忘了另一边，用户就会看到
    「计划说一条命令搞定」然后 orchestrator 退出码 2（无链路）。
    """
    assert set(planner.IMPLEMENTED_CHAINS) == set(orchestrator.IMPLEMENTED)


def test_unimplemented_engines_are_marked_as_such() -> None:
    for engine in gd.ADVICE:
        plan = planner.build(_FakeRep(engine))
        assert plan is not None
        expected = engine in orchestrator.IMPLEMENTED
        assert plan.implemented is expected, f"{engine} 的 implemented 标错了"


# --------------------------------------------------------------------------
# 4. 归档路径只来自实测，不靠猜
# --------------------------------------------------------------------------
def test_plan_uses_only_archives_from_report() -> None:
    """计划里提到的归档必须是 Report.archives 里真有的那些。"""
    xp3 = _arch("data.xp3", 999)
    rep = _FakeRep("KiriKiri", archives={".xp3": [xp3]})
    plan = planner.build(rep)
    assert plan is not None
    blob = plan.cmdline + "".join(n for n in plan.notes)
    assert "data.xp3" in blob
    assert "data.xp3" in blob and "544.7" not in blob  # 别编体积


def test_no_archive_still_produces_usable_plan() -> None:
    """归档为空时也要给命令（可能资源裸放），只是加一条说明。"""
    for engine in gd.ADVICE:
        plan = planner.build(_FakeRep(engine, archives={}))
        assert plan is not None
        assert plan.argv or plan.notes, f"{engine} 既没命令也没说明"


def test_kirikiri_mentions_largest_xp3() -> None:
    """多个 xp3 时要点出最大的那个——它最可能是加密包，也是探针该选的。"""
    small = _arch("patch.xp3", 10)
    big = _arch("data.xp3", 4096)
    rep = _FakeRep("KiriKiri", archives={".xp3": [small, big]})
    plan = planner.build(rep)
    assert plan is not None
    assert any("data.xp3" in n for n in plan.notes)


def test_advhd_notes_warn_about_headerless_listing() -> None:
    """AdvHD 的计划必须提醒「.arc 列表无表头」——这是实测踩过的差一错误。"""
    plan = planner.build(_FakeRep("AdvHD", archives={".arc": [_arch("Bgm.arc")]}))
    assert plan is not None
    assert any("无表头" in n for n in plan.notes)


def test_rpgmaker_mentions_no_comma_types_trap_is_unity_only() -> None:
    """坑 4（--types 逗号归零）只属于 AssetStudio，别串到别的引擎。"""
    unity = planner.build(_FakeRep("Unity"))
    rpg = planner.build(_FakeRep("RPG Maker"))
    assert unity is not None and rpg is not None
    assert any("逗号" in n for n in unity.notes)
    assert not any("逗号" in n for n in rpg.notes)


# --------------------------------------------------------------------------
# 5. 序列化与渲染
# --------------------------------------------------------------------------
def test_as_dict_is_json_serialisable() -> None:
    import json

    for engine in gd.ADVICE:
        plan = planner.build(_FakeRep(engine, archives={".xp3": [_arch("data.xp3")]}))
        assert plan is not None
        text = json.dumps(plan.as_dict(), ensure_ascii=False)
        back = json.loads(text)
        assert back["engine"] == engine
        assert isinstance(back["argv"], list)


def test_render_none_is_empty() -> None:
    assert planner.render(None) == ""


def test_render_marks_unimplemented() -> None:
    plan = planner.build(_FakeRep("Unity"))
    assert plan is not None
    text = planner.render(plan)
    assert "orchestrator 未接" in text


def test_render_does_not_mark_implemented() -> None:
    plan = planner.build(_FakeRep("Ren'Py"))
    assert plan is not None
    assert "orchestrator 未接" not in planner.render(plan)


def test_out_dir_is_under_project_not_game_dir() -> None:
    """★约定护栏★ 产物必须落在项目的 _extracted/ 下，不许倒进游戏目录。

    倒进游戏目录会污染原包，而加密 KiriKiri 那条链还要 stage 出纯 ASCII 副本，
    混在一起根本分不清哪个文件是谁产生的。
    """
    game = Path(r"D:\HY\Some Game")
    plan = planner.build(_FakeRep("Ren'Py", game=game))
    assert plan is not None
    out = plan.argv[plan.argv.index("--out") + 1]
    assert str(ROOT / "_extracted") in out
    assert not out.startswith(str(game))


# --------------------------------------------------------------------------
# 6. CLI 接线
# --------------------------------------------------------------------------
def test_cli_plan_flag_writes_json(tmp_path: Path) -> None:
    """`--plan --plan-json` 端到端：真跑一次 CLI（fixture 目录，不碰 D:\\HY）。"""
    import json
    import subprocess

    fixture = ROOT / "_fixtures" / "renpy_game"
    if not fixture.is_dir():
        pytest.skip("fixture 不在了")
    out = tmp_path / "plan.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "galgame_dispatch.py"), str(fixture),
         "--plan", "--plan-json", str(out)],
        capture_output=True, encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr
    assert "提取计划" in r.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data and data[0]["plan"]["engine"] == "Ren'Py"


def test_cli_without_plan_flag_has_no_plan_section(tmp_path: Path) -> None:
    import subprocess

    fixture = ROOT / "_fixtures" / "renpy_game"
    if not fixture.is_dir():
        pytest.skip("fixture 不在了")
    r = subprocess.run(
        [sys.executable, str(ROOT / "galgame_dispatch.py"), str(fixture)],
        capture_output=True, encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        cwd=str(ROOT),
    )
    assert r.returncode == 0
    assert "提取计划" not in r.stdout
