#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工介入方案（半自动协作模式，2026-11-04）。

## 为什么需要这个模块

这个工具原先的目标是「一条命令全自动跑完」。但有些障碍的**自动绕过成本远高于人工**：
加密 KiriKiri 的 UI 自动化要模拟鼠标拖拽、依赖真实桌面与 100%/200% DPI、跑约 40 分钟，
一旦环境不匹配（远程桌面、多虚拟桌面、缩放异常）用户拿到的只有一句「失败」；
而人手把 xp3 拖进 KrkrExtract 窗口只要 3 分钟。

「能自动的自动掉，不划算的交给用户」比「为了全自动堆复杂度」可靠得多。
所以失败时不再只报 error code，而是给一份**可执行的人工方案**：
需要什么、点哪里、产物放哪、做完跑哪条命令。

## 契约（三处消费同一份数据，别各写一遍）

  · CLI      —— `render()` 打成终端区块（main() 打印）
  · GUI      —— 摘要里取 summary + 前几步（gui.summarize_text）
  · manifest —— `manual` 块，机器可读（`as_dict()`，自动化流程可以照着做）

纯数据 + 纯函数：不读磁盘、不碰 Tk、不 import orchestrator（避免循环依赖）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

#: 方案代码 —— manifest 与测试都按它断言，改字面量等于改契约。
CODE_KIRIKIRI_ENCRYPTED = "kirikiri-encrypted"
CODE_KIRIKIRI_GUI_FAILED = "kirikiri-gui-failed"
CODE_UNITY_NO_ASSETS = "unity-no-assets"
CODE_ENGINE_NO_CHAIN = "engine-no-chain"
CODE_DETECT_FAILED = "detect-failed"


@dataclass(frozen=True)
class ManualPlan:
    """一份人工介入方案。

    `steps` 是**给人照着做**的编号动作；`target` 是产物必须落到的目录；
    `then` 是做完之后可直接复制的命令 —— 三者缺一个，用户就会卡在半路。
    """

    code: str
    summary: str
    why: str
    needs: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    target: str | None = None
    then: str | None = None
    alternatives: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "summary": self.summary,
            "why": self.why,
            "needs": list(self.needs),
            "steps": list(self.steps),
            "target": self.target,
            "then": self.then,
            "alternatives": list(self.alternatives),
        }

    def render(self, width: int = 74) -> str:
        """终端区块。宽度只用来画分隔线，不做全角对齐（中英混排对不齐反而更乱）。"""
        line = "-" * width
        out = [f"需要人工介入 · {self.code}", line, self.summary]
        if self.why:
            out.append(f"原因：{self.why}")
        if self.needs:
            out.append("")
            out.append("需要准备：")
            out += [f"  · {n}" for n in self.needs]
        if self.steps:
            out.append("")
            out.append("按顺序做：")
            out += [f"  {i}) {s}" for i, s in enumerate(self.steps, 1)]
        if self.target:
            out.append("")
            out.append(f"产物放到：{self.target}")
        if self.then:
            out.append("")
            out.append("做完重跑这一条：")
            out.append(f"  {self.then}")
        if self.alternatives:
            out.append("")
            out.append("备选方案（不推荐，但不用你动手）：")
            out += [f"  · {a}" for a in self.alternatives]
        out.append(line)
        return "\n".join(out)


def _q(p: Path | str) -> str:
    """带空格的路径必须加引号，否则用户复制过去就失败。"""
    s = str(p)
    return f'"{s}"' if " " in s else s


def plan_for(error: str, *, engine: str | None, game_dir: Path, out_dir: Path,
             raw_dir: Path, png_dir: Path, prog: str = "orchestrator.exe",
             tools: Mapping[str, str] | None = None,
             stages: list[dict] | None = None) -> ManualPlan | None:
    """按失败码给一份人工方案；没有合适方案返回 None（不要硬凑）。"""
    tools = tools or {}
    resume = f"{prog} {_q(game_dir)} --out {_q(out_dir)} --reuse-raw {_q(raw_dir)}"

    if engine == "KiriKiri" and error in ("extract-failed", "preflight-failed"):
        detail = _stage_detail(stages, "extract")
        gui_failed = "GUI 链路失败" in detail or "没有产出 KrkrExtract_Output" in detail
        code = CODE_KIRIKIRI_GUI_FAILED if gui_failed else CODE_KIRIKIRI_ENCRYPTED
        krkr = tools.get("krkr") or r"<随包目录>\bin\krkr\KrkrExtract.Lite.exe"
        return ManualPlan(
            code=code,
            summary="这个游戏的 xp3 自动解不开：GARbro 列不出目录（大概率加密/受保护）。",
            why="GARbro 的 Console 版没有「指定游戏标题/密钥」的参数；"
                "KrkrExtract 的自动化要模拟鼠标拖拽，慢且挑环境。",
            needs=[
                f"KrkrExtract.Lite.exe（随包路径：{krkr}）",
            ],
            steps=[
                f"打开 {krkr}",
                "把游戏目录下的所有 .xp3 拖进 KrkrExtract 窗口（先拖 data.xp3），"
                "等界面状态回到 idle（有进度条就走完）",
                "解出来的东西在 KrkrExtract 目录下的 KrkrExtract_Output\\data 与 ...\\png",
                f"把 data\\ 里的全部内容拷到：{raw_dir}",
                f"如果 ...\\png 里有东西，一并拷到：{png_dir}",
            ],
            target=str(raw_dir),
            then=resume,
            alternatives=[
                f"{prog} {_q(game_dir)} --out {_q(out_dir)} --allow-gui --overwrite"
                f"（全自动，约 40 分钟，期间别动鼠标、别切虚拟桌面）",
            ],
        )

    if engine == "Unity" and error == "extract-failed":
        as_dir = tools.get("assetstudio") or r"<随包目录>\bin\assetstudio"
        return ManualPlan(
            code=CODE_UNITY_NO_ASSETS,
            summary="AssetStudio 的 JSON 枚举到 0 个资产，自动链路拿不到地面真相。",
            why="要么 <游戏名>_Data 目录里没有可导出的资源，要么 AssetStudio 版本不认这个 Unity 版本。",
            needs=[f"AssetStudio.GUI.exe（随包路径：{as_dir}）"],
            steps=[
                f"打开 {as_dir}\\AssetStudio.GUI.exe",
                "File → Load Folder，选游戏的 *\\<游戏名>_Data 目录",
                "等资源树加载完，全选 → Export → 选一个空目录导出",
                f"把导出的图片类拷到：{raw_dir / 'Image_Texture2D'}"
                f"（Sprite 另一个目录，音频到 {raw_dir / 'Audio'}）",
            ],
            target=str(raw_dir),
            then=resume,
            alternatives=[],
        )

    if error == "chain-not-implemented":
        return ManualPlan(
            code=CODE_ENGINE_NO_CHAIN,
            summary=f"引擎判成了 {engine or '未知'}，但本工具还没有这条自动链路。",
            why="自动链路只覆盖已实测过的那几个引擎；这个引擎要么小众，要么格式还没逆向。",
            needs=["对应引擎的专用解包工具（见 galgame-unpack-decision-tree.md 的引擎表）"],
            steps=[
                "用该引擎的专用工具（或 GARbro.GUI 逐个格式试）把资源解出来",
                f"把解出的全部文件拷到：{raw_dir}",
                "如果图片是 .tlg/.pna 等中间格式，直接放 raw/ 即可，后处理会自动转 PNG",
            ],
            target=str(raw_dir),
            then=resume,
        )

    if error == "detect-failed":
        return ManualPlan(
            code=CODE_DETECT_FAILED,
            summary="没判出这是什么引擎，自动链路无法选择。",
            why="指纹规则没命中（文件名/目录结构太特殊，或者根目录选错了）。",
            needs=[],
            steps=[
                f"确认传给工具的是**游戏根目录**（能看到 exe 与数据目录的那一层）：{game_dir}",
                "如果知道引擎，用 --engine 强制指定后重跑（支持的引擎见 README 表格）",
                "不知道引擎就把目录里的顶层文件名发给开发者，补一条指纹规则",
            ],
            then=f"{prog} {_q(game_dir)} --out {_q(out_dir)} --engine <引擎名>",
        )

    return None


def _stage_detail(stages: list[dict] | None, name: str) -> str:
    for s in stages or []:
        if s.get("stage") == name:
            return str(s.get("detail") or "")
    return ""


def dry_run_plan(engine: str | None, *, game_dir: Path, out_dir: Path,
                 raw_dir: Path, png_dir: Path, xp3_probe: tuple[bool, str] | None,
                 prog: str = "orchestrator.exe",
                 tools: Mapping[str, str] | None = None) -> ManualPlan | None:
    """`--dry-run` 的提前预判：**别让用户跑完 40 分钟才发现要人工**。

    `xp3_probe` = (能否列出, 最大 xp3 的名字)；None 表示没探（非 KiriKiri）。
    """
    if engine == "KiriKiri" and xp3_probe is not None and not xp3_probe[0]:
        plan = plan_for("extract-failed", engine=engine, game_dir=game_dir,
                        out_dir=out_dir, raw_dir=raw_dir, png_dir=png_dir,
                        prog=prog, tools=tools, stages=[])
        if plan is None:
            return None
        return ManualPlan(
            code=plan.code,
            summary=f"预判：{xp3_probe[1]} 用 GARbro 列不出目录，正式跑大概率要人工介入。",
            why=plan.why, needs=plan.needs, steps=plan.steps, target=plan.target,
            then=plan.then, alternatives=plan.alternatives,
        )
    return None


def render_dict(data: Mapping | None, width: int = 74) -> str:
    """从 manifest 的 `manual` 块（dict）渲染 —— CLI 拿到的就是 dict，别为它再建对象。"""
    if not data:
        return ""
    return ManualPlan(
        code=str(data.get("code") or "manual"),
        summary=str(data.get("summary") or ""),
        why=str(data.get("why") or ""),
        needs=tuple(data.get("needs") or ()),
        steps=tuple(data.get("steps") or ()),
        target=data.get("target"),
        then=data.get("then"),
        alternatives=tuple(data.get("alternatives") or ()),
    ).render(width)
