# -*- coding: utf-8 -*-
"""P0 数据安全：--overwrite 改名备份 + 失败自动回滚；以及 P1/P2 的文案收口。

2026-11-06 实跑事故：GUI 的 --overwrite 直接 `drop_tree(raw/)` + `drop_tree(png/)`，
KrkrExtract 链路随后失败，9818 + 2748 个上一轮人工产物被清空，既不备份也不回滚。
本文件锁住现在的三条红线：
  1. 旧产物只改名、一字节不删，reset stage 写明备份路径；
  2. 失败收尾自动回滚（本轮无新产物时），本轮有新产物时绝不覆盖、保留两堆完整数据；
  3. 失败文案引用真实报错、不重复推荐已用过的 --allow-gui，GUI 摘要能看到真实原因。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gui  # noqa: E402
import manual  # noqa: E402
import orchestrator as orch  # noqa: E402


def _ctx(tmp_path: Path, **kw) -> orch.Ctx:
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    return orch.Ctx(game_dir=tmp_path / "game", out_dir=out,
                    work_dir=out / "_work", manifest_path=out / "manifest.json",
                    **kw)


def _ok_stage(name: str, **data) -> orch.Stage:
    return orch.Stage(name, ok=True, seconds=0.01, detail="fake", data=data)


def _run(tmp_path, monkeypatch, *, extract_ok: bool, write_new: bool = False):
    """跑一轮最小化的 run()：extract 成功或失败都由替身决定。"""
    ctx = _ctx(tmp_path, engine="Ren'Py", overwrite=True)
    (ctx.raw_dir / "sub").mkdir(parents=True)
    (ctx.raw_dir / "sub" / "old.ogg").write_bytes(b"OLD-DATA")
    ctx.png_dir.mkdir(parents=True)
    (ctx.png_dir / "old.png").write_bytes(b"OLD-PNG")
    monkeypatch.setattr(orch.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 100 * 1024 ** 3})())

    def fake_extract(c):
        if write_new:
            c.raw_dir.mkdir(parents=True, exist_ok=True)
            (c.raw_dir / "new.ogg").write_bytes(b"NEW")
        if not extract_ok:
            return orch.Stage("extract", ok=False, detail="模拟解包失败")
        c.raw_dir.mkdir(parents=True, exist_ok=True)
        (c.raw_dir / "new.ogg").write_bytes(b"NEW")
        return _ok_stage("extract", archives=[{"archive": "x.rpa", "expected": 1, "got": 1}],
                         expected_total=1, actual_total=1)

    monkeypatch.setattr(orch, "stage_extract_renpy", fake_extract)
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _ok_stage("postprocess"))
    monkeypatch.setattr(orch, "stage_verify", lambda c: _ok_stage("verify", verified=True))
    monkeypatch.setattr(orch.faillog, "log_failure", lambda *a, **kw: None)
    rc, res = orch.run(ctx)
    return ctx, rc, res


# ---------------------------------------------------------------------------
# 1) 改名备份：不删除、可复盘
# ---------------------------------------------------------------------------

def test_overwrite_renames_old_products_into_backup(tmp_path, monkeypatch):
    """★核心★ 旧 raw/ png/ 是**改名**，不是删除：备份里的数据必须一字节不少。"""
    ctx, rc, man = _run(tmp_path, monkeypatch, extract_ok=True)
    assert rc == 0, man

    assert (ctx.raw_dir / "new.ogg").read_bytes() == b"NEW"
    assert not (ctx.raw_dir / "sub" / "old.ogg").exists(), "旧文件不能混进本轮交付"

    backup = Path(ctx.overwrite_backup)
    assert backup.is_dir()
    assert (backup / "raw" / "sub" / "old.ogg").read_bytes() == b"OLD-DATA"
    assert (backup / "png" / "old.png").read_bytes() == b"OLD-PNG"

    reset = [s for s in man["stages"] if s["stage"] == "reset"]
    assert reset and reset[0]["ok"] is True
    # Stage.as_dict() 把 data **平铺**进 stage dict，没有嵌套的 "data" 键
    assert reset[0]["method"] == "rename"
    assert reset[0]["backup"] == str(backup)
    assert reset[0]["moved"] == {"raw": 1, "png": 1}
    assert "备份" in reset[0]["detail"]


# ---------------------------------------------------------------------------
# 2) 失败自动回滚
# ---------------------------------------------------------------------------

def test_failed_extract_auto_rolls_back_old_products(tmp_path, monkeypatch):
    """★核心★ 现场就是这个形状：清空 → GUI 失败 → 数据没了。现在要自动还回来。"""
    ctx, rc, res = _run(tmp_path, monkeypatch, extract_ok=False)
    assert rc == 1
    assert res["error"] == "extract-failed"

    assert (ctx.raw_dir / "sub" / "old.ogg").read_bytes() == b"OLD-DATA"
    assert (ctx.png_dir / "old.png").read_bytes() == b"OLD-PNG"
    man = res["manifest"]
    rollback = [s for s in man["stages"] if s["stage"] == "rollback"]
    assert rollback and rollback[0]["ok"] is True
    assert rollback[0]["restored"] == ["raw", "png"]
    assert "自动回滚" in rollback[0]["detail"]


def test_rollback_never_overwrites_new_products(tmp_path, monkeypatch):
    """本轮已经解出半成品：绝不覆盖，备份完整保留，让用户在两堆数据间取舍。"""
    ctx, rc, res = _run(tmp_path, monkeypatch, extract_ok=False, write_new=True)
    assert rc == 1

    assert (ctx.raw_dir / "new.ogg").read_bytes() == b"NEW", "本轮新产物不能被旧数据盖掉"
    backup = Path(ctx.overwrite_backup)
    assert (backup / "raw" / "sub" / "old.ogg").read_bytes() == b"OLD-DATA"
    rollback = [s for s in res["manifest"]["stages"] if s["stage"] == "rollback"][0]
    assert rollback["kept"] == ["raw"]
    assert "未覆盖" in rollback["detail"]


def test_reuse_raw_does_not_create_backup(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, engine="Ren'Py", overwrite=True,
               reuse_raw=tmp_path / "old_raw")
    ctx.raw_dir.mkdir(parents=True, exist_ok=True)
    (ctx.raw_dir / "old.ogg").write_bytes(b"OLD")
    monkeypatch.setattr(orch, "stage_extract_renpy", lambda c: _ok_stage("extract"))
    monkeypatch.setattr(orch, "stage_postprocess", lambda c: _ok_stage("postprocess"))
    monkeypatch.setattr(orch, "stage_verify", lambda c: _ok_stage("verify", verified=True))
    monkeypatch.setattr(orch.faillog, "log_failure", lambda *a, **kw: None)

    orch.run(ctx)

    assert ctx.overwrite_backup is None, "复用模式不重新解包，不该动旧产物"
    assert (ctx.raw_dir / "old.ogg").read_bytes() == b"OLD"


# ---------------------------------------------------------------------------
# 3) 真实报错提取（manual / GUI 摘要要引用它，而不是复述错误码）
# ---------------------------------------------------------------------------

def test_gui_error_from_output_picks_readable_line():
    out = ("pids_by_exe_path: 27 个进程读不到镜像路径\n"
           "  File \"orchestrator.py\", line 131, in _run_sibling\n"
           "RuntimeError: 拖拽落点被遮挡：重试 6 轮仍未在 KrkrExtract 窗口内找到可见空白点。\n")
    err = orch._gui_error_from_output(out, 1)
    assert "拖拽落点被遮挡" in err
    assert "File " not in err


def test_gui_error_from_output_handles_empty_output():
    assert "rc=1" in orch._gui_error_from_output("", 1)


def test_stage_as_dict_flattens_gui_error():
    """★契约锁★ 生产形状的 stages 才是人工方案的输入，别再拿嵌套 data 造夹具。"""
    err = "RuntimeError: 拖拽落点被遮挡：重试 6 轮仍未找到可见空白点。"
    d = orch.Stage("extract", ok=False, detail="GUI 链路失败或没有产出 KrkrExtract_Output (rc=1)",
                   data={"gui_error": err}).as_dict()
    assert "data" not in d, "Stage.as_dict() 是平铺的，生产 manifest 没有 data 键"
    assert d["gui_error"] == err
    assert manual._gui_error_text([d], d["detail"]) == err, \
        "detail 不带「真实报错：」时也必须能取到顶层 gui_error"


def test_gui_error_text_flat_wins_over_detail():
    flat = {"stage": "extract", "gui_error": "顶层真实报错",
            "detail": "GUI 链路失败；真实报错：detail 里的旧文本"}
    assert manual._gui_error_text([flat], flat["detail"]) == "顶层真实报错"


def test_gui_error_text_keeps_legacy_compat():
    """外部自造的嵌套 dict 与老 manifest（只有 detail 后缀）仍要能兜住。"""
    nested = {"stage": "extract", "data": {"gui_error": "嵌套形状"}}
    assert manual._gui_error_text([nested]) == "嵌套形状"
    assert manual._gui_error_text([{"stage": "extract", "detail": "无字段"}],
                                  "GUI 链路失败；真实报错：老文本兜底") == "老文本兜底"
    assert manual._gui_error_text(None) == ""


# ---------------------------------------------------------------------------
# 4) 失败文案：GUI 链路失败 ≠ 加密；已用 --allow-gui 不再重复推荐
# ---------------------------------------------------------------------------

# 真实形状：`Stage.as_dict()` 把 data 平铺到顶层（规范字段后盖），生产 manifest
# 里 **没有** "data" 键。detail 也刻意不带「真实报错：」后缀 —— 否则死路径会被
# detail 兜底分支掩盖（2026-11-07 QA 复核发现的夹具失真）。
_GUI_STAGES = [
    {"stage": "extract", "ok": False, "skipped": False, "seconds": 60.54,
     "detail": "GUI 链路失败或没有产出 KrkrExtract_Output (rc=1)",
     "gui_error": "RuntimeError: 拖拽落点被遮挡：重试 6 轮仍未找到可见空白点。"},
]


def _plan(allow_gui: bool, **kw):
    return manual.plan_for(
        "extract-failed", engine="KiriKiri",
        game_dir=Path(r"D:\HY\G"), out_dir=Path(r"D:\HY\G\output"),
        raw_dir=Path(r"D:\HY\G\output\raw"), png_dir=Path(r"D:\HY\G\output\png"),
        stages=_GUI_STAGES, allow_gui=allow_gui, **kw)


def test_gui_failure_summary_no_longer_blames_garbro():
    plan = _plan(allow_gui=True)
    assert plan.code == manual.CODE_KIRIKIRI_GUI_FAILED
    assert "GARbro 列不出目录" not in plan.summary
    assert "GUI 自动化链路已经跑过但失败" in plan.summary
    assert "拖拽落点被遮挡" in plan.summary, "要直接引用真实报错"
    assert "安全软件" in plan.why and "远程桌面" in plan.why
    assert "独占" in plan.why


def test_gui_failure_steps_are_actionable():
    plan = _plan(allow_gui=True)
    text = " ".join(plan.steps) + " " + " ".join(plan.needs)
    assert "KRKR_DROP_ATTEMPTS" in text
    assert "KRKR_WINDOW_WAIT" in text
    assert "extract.log" in text and "krkr_auto_extract.log" in text
    assert "Full Unpack" in text
    assert plan.then and "--reuse-raw" in plan.then


def test_gui_failure_does_not_recommend_allow_gui_again():
    """★用户现场★ 已经勾了「用于加密的 krkr」，失败弹窗不能再让他加一次 --allow-gui。"""
    plan = _plan(allow_gui=True)
    assert plan.alternatives == ()
    assert all("--allow-gui" not in a for a in plan.alternatives)
    assert "备选方案" not in plan.render()


def test_gui_failure_keeps_alternative_when_gui_was_never_used():
    plan = _plan(allow_gui=False)
    assert any("--allow-gui" in a for a in plan.alternatives)


def test_gui_failure_mentions_backup_path():
    plan = _plan(allow_gui=True,
                 backup_dir=Path(r"D:\HY\G\output\_overwrite_backup_20261106_230000"))
    text = plan.render()
    assert "_overwrite_backup_" in text
    assert "未删除" in text


# ---------------------------------------------------------------------------
# 5) GUI 层：摘要显示真实原因；视图也算残留（防「raw 空就跳过二次确认」）
# ---------------------------------------------------------------------------

def test_summarize_shows_real_reason_besides_error_code():
    man = {
        "manifest_version": 1, "engine": "KiriKiri",
        "counts": {"final": {"total": 0}},
        "reconcile": {"method": "no-index-available", "diff": None},
        "verify": {"status": "skipped"},
        "error": "extract-failed",
        "manual": {"code": manual.CODE_KIRIKIRI_GUI_FAILED,
                   "summary": "GUI 自动化链路已经跑过但失败：拖拽落点环节没走通",
                   "steps": ["看日志"], "then": None},
    }
    text = gui.summarize_text(1, man)
    assert "失败原因：extract-failed" in text, "错误码要保留，历史契约锁着"
    assert "拖拽落点环节没走通" in text, "真实原因必须看得见"


def test_has_stale_products_counts_marked_view(tmp_path):
    """raw/png 已被清空但分类视图还在时，GUI 仍必须问一次。"""
    view = tmp_path / "分类"
    (view / "其他" / "raw" / "data").mkdir(parents=True)
    (view / ".galunpack-view").write_text("generated by organize.py\n", encoding="utf-8")
    (view / "其他" / "raw" / "data" / "a.ks").write_bytes(b"x")

    assert gui.has_stale_products(tmp_path) is True


def test_has_stale_products_ignores_unmarked_directory(tmp_path):
    """没有 .galunpack-view 标记 = 用户自己的目录，不能当残留去问覆盖。"""
    (tmp_path / "分类" / "其他").mkdir(parents=True)
    (tmp_path / "分类" / "其他" / "a.ks").write_bytes(b"x")
    assert gui.has_stale_products(tmp_path) is False


# ---------------------------------------------------------------------------
# 6) 2026-11-07 真机日志可读性：报错去重 / 未验收说人话 / 步骤对症
# ---------------------------------------------------------------------------

def test_gui_error_from_output_dedups_repeated_diagnostic_lines():
    """现场：同一句诊断行出现 3 次还被 GUI 摘要腰斩，用户完全看不懂。"""
    out = (
        "主窗口=[]；Button 文本=[]；全部子控件=[]；诊断异常=None\n"
        "ERROR: 没点上 'Full Unpack'：按钮枚举失败。\n"
        "主窗口=[]；Button 文本=[]；全部子控件=[]；诊断异常=None\n"
        "RuntimeError: 没点上 'Full Unpack'：按钮枚举失败。\n"
        "主窗口=[]；Button 文本=[]；全部子控件=[]；诊断异常=None\n"
        "该进程顶层窗口(hwnd,类名,标题)=[(8101, 'WindowsForms10.Window.8.app', "
        "'KrkrExtract(local 5.0.0.2)')]\n"
    )
    err = orch._gui_error_from_output(out, 1)
    assert err.count("主窗口=[]") == 1, "诊断行不许重复"
    assert "RuntimeError:" in err
    assert "该进程顶层窗口" in err


def test_summarize_skipped_verify_is_plain_language():
    man = {
        "manifest_version": 1, "engine": "KiriKiri",
        "counts": {"final": {"total": 0}},
        "reconcile": {"method": "no-index-available", "diff": None},
        "verify": {"status": "skipped"},
        "error": "extract-failed",
        "manual": {"summary": "GUI 自动化链路已经跑过但失败", "steps": [], "then": None},
    }
    text = gui.summarize_text(1, man)
    assert "验收：未执行" in text
    assert "None/None" not in text, "没验成不该显示成图片 None/None失败"


def test_manual_steps_target_full_unpack_instead_of_drop_point():
    stages = [{"stage": "extract", "ok": False,
               "detail": "GUI 链路失败或没有产出 KrkrExtract_Output (rc=1)",
               "gui_error": "RuntimeError: 没点上 'Full Unpack'：按钮枚举失败"}]
    plan = manual.plan_for(
        "extract-failed", engine="KiriKiri",
        game_dir=Path(r"D:\HY\G"), out_dir=Path(r"D:\HY\G\output"),
        raw_dir=Path(r"D:\HY\G\output\raw"), png_dir=Path(r"D:\HY\G\output\png"),
        stages=stages, allow_gui=True)
    text = " ".join(plan.steps)
    assert "Full Unpack 按钮没点上" in text
    assert "先勾上 Full Unpack" in text
    assert "KRKR_DROP_ATTEMPTS" not in text, "落点步骤与本次真因无关，别再让用户照着做"
