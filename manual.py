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
             stages: list[dict] | None = None,
             case_hint: str | None = None,
             allow_gui: bool = False,
             backup_dir: Path | str | None = None) -> ManualPlan | None:
    """按失败码给一份人工方案；没有合适方案返回 None（不要硬凑）。

    `case_hint`：案例库证据提示（P1-① A 案，2026-11-05 用户定）——
    同签名案例曾用 krkr_auto_extract 全自动成功时，把「加 --allow-gui 可自动跑」
    摆进 summary。放 summary 而不是 why：GUI 摘要只显示 summary 与前 3 步，
    放别处 GUI 用户看不见。GUI 自动化**已经跑过但失败**的分支不套用
    （那条的结论是「这条链路在你机器上没走通」，再推荐它就是误导）。

    `allow_gui`：本轮是否已经用了 `--allow-gui`。是，则 GUI 链路失败时**不再**
    把「加 --allow-gui 全自动」当备选重复推荐（2026-11-06 实跑：用户明明勾了
    「用于加密的 krkr」，失败弹窗却还让他再加一次这个参数）。
    `backup_dir`：`--overwrite` 把上一轮产物改名备份到的目录，写进方案让用户找得回。
    """
    tools = tools or {}
    resume = f"{prog} {_q(game_dir)} --out {_q(out_dir)} --reuse-raw {_q(raw_dir)}"

    if engine == "KiriKiri" and error in ("extract-failed", "preflight-failed"):
        detail = _stage_detail(stages, "extract")
        gui_failed = "GUI 链路失败" in detail or "没有产出 KrkrExtract_Output" in detail
        code = CODE_KIRIKIRI_GUI_FAILED if gui_failed else CODE_KIRIKIRI_ENCRYPTED
        krkr = tools.get("krkr") or r"<随包目录>\bin\krkr\KrkrExtract.Lite.exe"
        backup_note = (f"上一轮产物已改名备份（未删除）：{backup_dir}，"
                       f"失败时会自动回滚回 {out_dir}\\raw 与 {out_dir}\\png"
                       if backup_dir else "")

        if gui_failed:
            # 2026-11-06 实跑：`kirikiri-gui-failed` 分支原来照抄加密分支的 summary
            # 「GARbro 列不出目录（大概率加密/受保护）」，而真实根因是 KrkrExtract
            # 拖拽落点扫不到 / Full Unpack 没点上 —— 用户按着错误的方向排查了 40 分钟。
            gui_error = _gui_error_text(stages, detail)
            summary = ("GUI 自动化链路已经跑过但失败：KrkrExtract 的拖拽/落点环节没走通"
                       "（与引擎加密判定无关，别再往 GARbro 的方向排查）。")
            if gui_error:
                summary += f" 真实报错：{gui_error[:160]}"
            why = ("上一步的 GUI 自动化跑过了但没产出。常见原因：安全软件拦了 KrkrExtract 或 "
                   "game.exe；或者不是真实桌面会话（远程桌面/多虚拟桌面会让模拟鼠标失效）；"
                   "本轮还可能是主窗口被遮挡/最小化/句柄重建导致拖拽落点找不到，"
                   "或 'Full Unpack' 没点上（默认只解脚本）。"
                   "这条链路必须**独占真实桌面**：关掉浏览器与其他置顶窗口，运行期间"
                   "不要切换窗口、不要动鼠标、不要锁屏。")
            if gui_error:
                why += (f" 真实报错（摘自 _work/extract.log 与 krkr_auto_extract.log）："
                        f"{gui_error}")
            needs = [
                f"KrkrExtract.Lite.exe（随包路径：{krkr}）",
                "真实桌面会话（非远程桌面/多虚拟桌面），运行期间独占鼠标与前台",
                f"完整日志：{Path(out_dir) / '_work' / 'extract.log'} 与 "
                "<随包目录>/_krkr_stage/krkr_auto_extract.log（UTF-8，中文可读）",
            ]
            if backup_note:
                needs.insert(0, backup_note)
            steps = [
                "打开 _work/extract.log 与 krkr_auto_extract.log，定位最后一条 "
                "RuntimeError / ERROR（落点被遮挡 / 全是子控件 / 窗口不可见 / Full Unpack 没点上）",
                "关掉浏览器、远程桌面、其他置顶窗口；确认是真实桌面且屏幕未锁定，"
                "运行期间不切窗口、不动鼠标",
                "若仍报落点问题，可调大 KRKR_DROP_ATTEMPTS（默认 6）与 "
                "KRKR_WINDOW_WAIT（默认 40 秒）后重试；日志会写明是谁挡着、是不是子控件",
                f"或直接改走人工：打开 {krkr}，先勾上 Full Unpack",
                "把游戏目录下的所有 .xp3 拖进 KrkrExtract 窗口（先拖 data.xp3），"
                "等界面状态回到 idle（有进度条就走完）",
                "解出来的东西在 KrkrExtract 目录下的 KrkrExtract_Output\\data 与 ...\\png",
                f"把 data\\ 里的全部内容拷到：{raw_dir}",
                f"如果 ...\\png 里有东西，一并拷到：{png_dir}",
            ]
            if backup_note:
                steps.insert(0, f"先确认产物安全：{backup_note}")
            # 用户已经用过 --allow-gui 时，再把它当备选就是让他原样重跑 40 分钟。
            alternatives: tuple[str, ...] = ()
            if not allow_gui:
                alternatives = (
                    f"{prog} {_q(game_dir)} --out {_q(out_dir)} --allow-gui --overwrite"
                    f"（全自动，约 40 分钟，期间别动鼠标、别切虚拟桌面）",
                )
            return ManualPlan(
                code=code, summary=summary, why=why,
                needs=tuple(needs), steps=tuple(steps), target=str(raw_dir),
                then=resume, alternatives=alternatives,
            )

        # 没试过 GUI 链路：结论才是「列不出目录，需要人工或加 --allow-gui」。
        why = ("GARbro 的 Console 版没有「指定游戏标题/密钥」的参数；"
               "KrkrExtract 的自动化要模拟鼠标拖拽，慢且挑环境。")
        summary = "这个游戏的 xp3 自动解不开：GARbro 列不出目录（大概率加密/受保护）。"
        if case_hint and not gui_failed:
            summary = f"{summary} {case_hint}"
        needs = [f"KrkrExtract.Lite.exe（随包路径：{krkr}）"]
        if backup_note:
            needs.insert(0, backup_note)
        return ManualPlan(
            code=code,
            summary=summary,
            why=why,
            needs=tuple(needs),
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
        needs = ["对应引擎的专用解包工具（见 galgame-unpack-decision-tree.md 的引擎表）"]
        # 唯一已知的「判得出但没链路」是 Tyrano/Electron，仓库里就有现成脚本 ——
        # 与其让用户去猜，不如直接把脚本名给出来（不含参数，参数在脚本头部）。
        if (engine or "").startswith("Tyrano"):
            needs.append("本仓库根目录的 asar_tool.py 能解 Electron 的 .asar（用法见文件头）")
        return ManualPlan(
            code=CODE_ENGINE_NO_CHAIN,
            summary=f"引擎判成了 {engine or '未知'}，但本工具还没有这条自动链路。",
            why="自动链路只覆盖已实测过的那几个引擎；这个引擎要么小众，要么格式还没逆向。",
            needs=needs,
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


def _gui_error_text(stages: list[dict] | None, detail: str = "") -> str:
    """取 krkr 链路的**真实报错**，让人工方案引用它而不是复述错误码。

    `orchestrator.stage_extract_kirikiri` 把 krkr stdout 里的关键行存进
    `extract.data.gui_error`；但 `Stage.as_dict()` 会把 data **平铺到顶层**
    （规范字段后盖），所以真实 manifest 里字段是 `stages[].gui_error`，
    根本没有 `data` 这个键。2026-11-07 QA 复核：只查嵌套 data 是死路径，
    生产上一直靠 detail 里「真实报错：」的兜底分支才碰巧能用；夹具用了
    非真实的嵌套形状，把这条死路径测绿了。现在两种形状都读（嵌套只作
    外部自造 dict 的兼容），老 manifest 两处都没有时再退回 detail 后缀。
    """
    for s in stages or []:
        if s.get("stage") == "extract":
            data = s.get("data")
            nested = data.get("gui_error") if isinstance(data, dict) else None
            value = s.get("gui_error") or nested
            if value:
                return str(value)
    marker = "真实报错："
    if marker in (detail or ""):
        return str(detail).split(marker, 1)[1].strip()
    return ""


def dry_run_plan(engine: str | None, *, game_dir: Path, out_dir: Path,
                 raw_dir: Path, png_dir: Path, xp3_probe: tuple[bool, str] | None,
                 prog: str = "orchestrator.exe",
                 tools: Mapping[str, str] | None = None,
                 case_hint: str | None = None,
                 allow_gui: bool = False,
                 backup_dir: Path | str | None = None) -> ManualPlan | None:
    """`--dry-run` 的提前预判：**别让用户跑完 40 分钟才发现要人工**。

    `xp3_probe` = (能否列出, 最大 xp3 的名字)；None 表示没探（非 KiriKiri）。
    """
    if engine == "KiriKiri" and xp3_probe is not None and not xp3_probe[0]:
        plan = plan_for("extract-failed", engine=engine, game_dir=game_dir,
                        out_dir=out_dir, raw_dir=raw_dir, png_dir=png_dir,
                        prog=prog, tools=tools, stages=[], case_hint=case_hint,
                        allow_gui=allow_gui, backup_dir=backup_dir)
        if plan is None:
            return None
        summary = f"预判：{xp3_probe[1]} 用 GARbro 列不出目录，正式跑大概率要人工介入。"
        if case_hint:
            summary = f"{summary} {case_hint}"
        return ManualPlan(
            code=plan.code,
            summary=summary,
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
