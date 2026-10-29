# Galgame 自动解包软件 —— 可执行分阶段方案（software-plan）

> 2026-10-28 沉淀。上游蓝图：`galgame-ai-unpack-workflow-plan.md`（许可证矩阵 / PyInstaller 坑 /
> 法律边界均已调研，本文不重复，只引用）。本文回答的是：**以仓库现有资产为起点，每阶段做什么、
> 交付什么、验收什么**。终局目标：一套可复用、可分发的 Windows 软件（个人自用/学习）。

## 0. 现状盘点（2026-10-28，12 个已跑通样本）

**已有能力（全部实测零失败）**：

| 引擎/格式 | 工具 | 语言/依赖 | 接口（已统一度） |
|---|---|---|---|
| 分派（10 引擎指纹） | `galgame_dispatch.py`（dry-run、纯规则、只读） | Python 标准库 | `<目录> [--json out]` ✅ |
| KiriKiri(静态) | GARbro.Console + `_tlg2png_all.ps1`/`_krkr_tlg_convert.py` | 外部 exe + Python | 部分 |
| **KiriKiri(加密)** | **`krkr_auto_extract.py`**（注入+Explorer 拖拽全自动） | Python 标准库 | `<游戏目录> [--out]` ✅ |
| Ren'Py | `rpa_tool.py` / `rpa_extract_organized.py` | Python 标准库 | `info/list/extract` ✅ |
| Unity | `unity_unpack.ps1` + `_as_audio_collect2.py` | PowerShell + AssetStudio CLI | 部分 |
| RPG Maker MV/MZ | `_rpgmv_decrypt.py` | Python 标准库 | 内置约定 |
| AdvHD | GARbro + `_pna_carve.py` | Python 标准库 | 部分 |
| Yu-Ris | `_ypf_extract.py` | Python 标准库 | 内置约定 |
| ExHIBIT | `_gyu_tool.cs/_exe` + `_grp_extract.py` | C#(csc) + Python | 部分 |
| CatSystem2 | `_cs2_int_extract.py` + `_hg3_tool.exe` | Python(py cryptodome) + C# | 内置约定 |
| Electron/asar | `asar_tool.py` + `_spite_decrypt.py` 系 | Python 标准库 | 内置约定 |
| 验收 | `_verify_media.py`（Pillow + ffprobe 白名单） | Python | `<目录> [--csv]` ✅ |
| 盘点 | `_scan_hy_inventory.py` | Python 标准库 | 只读 ✅ |

**关键缺口（对照终局）**：工具间是「约定」而非「契约」；无统一 manifest；无编排器；
Python/C#/PowerShell/外部 exe 混杂但无调用规范；GARbro/AssetStudio 等外部工具依赖硬编码路径。

## 1. 产品形态与架构（沿用蓝图 §4.1 的决策）

- **打包**：Python + PyInstaller `--onedir` → Inno Setup 单安装包（蓝图 §4.2-4.4 的坑已列全）。
- **架构**：编排器（CLI 优先）+ 引擎插件（每个引擎一个 extractor 模块）+ 外部工具桥（`resources/bin/`
  独立 exe，subprocess + argv 数组调用，启动前 `SetDllDirectoryW(None)`——蓝图 §4.3 高风险项）。
- **AI 层**：确定性管线先行；编排器暴露 **CLI + MCP**（蓝图 §6 阶段 1 就做，不等阶段 2）。
- **范围**（不变）：视频/音频/图片三类产出；**不做**回写/文本提取/翻译/分发。

## 2. 统一契约（阶段 1 的第一件事，一切模块向它靠）

```
工具调用约定（所有 extractor 统一）:
  <extractor> <input_path> <output_dir> [--work DIR] [--manifest out.json]

输出目录约定:
  <output_dir>/
    raw/          原始提取物（含 .tlg 等待转格式）
    png/          图片成品（tlg→png 等转换后）
    manifest.json 交付清单

manifest.json 契约（对账与验收的唯一地面真相）:
{
  "engine": "kirikiri-encrypted",
  "source": {"archives": [{"name": "data.xp3", "size": 6922, "entries": 2838}]},
  "counts":  {"by_ext": {".ogg": 1394, ".tlg": 865}, "total": 2838},
  "video":   {"present": false, "evidence": "index-entry-scan"},   // 坑3判据
  "postprocess": [{"tool": "tlg2png", "in": 865, "ok": 865, "fail": 0}],
  "verify":  {"image_ok": 1301, "image_fail": 0, "audio_ok": 1396, "audio_fail": 0,
              "audio_minutes": 148.8, "csv": "verify.csv"}
}
```

**判定规则数据驱动**：`galgame_dispatch.py` 的指纹表移进 `rules/engines.json`
（签名/文件特征/判定次序），dispatch 与软件共用同一份（蓝图「规则要数据驱动」的落实）。

## 3. 分阶段路线（替换蓝图 §6 的占位内容，全部对准现有资产）

### 阶段 1：契约化 + 编排器（当前 → M1，预计 2-3 个工作日粒度）
1. **manifest 契约落地**：给 4 个已统一接口的工具补 `--manifest`
   （`rpa_extract_organized.py`、`krkr_auto_extract.py`、`_rpgmv_decrypt.py`、`_ypf_extract.py`）。
2. **`galgame_dispatch.py` 升级**：指纹表外置 `rules/engines.json`；输出增加「建议 extractor + 参数」。
3. **`orchestrator.py`**：`detect → extract → postprocess → verify → manifest` 串成一条命令；
   每步产物与日志落 `--work` 目录；对账不为 0 即停（纪律 2）。
4. **外部工具桥** `toolbridge.py`：统一「找工具（注册表化路径）+ 调用 + 数产物 + 退出码不信任」；
   先覆盖 GARbro / tlg2png / ffprobe / AssetStudio / KrkrExtract 五个。
5. **验收**：拿 `高慢妻陥落！！`（加密 krkr）与 `My Best Deal`（Ren'Py）双样本回归，manifest 对账 0 差。

### 阶段 2：引擎插件收编（M1 → M2）
1. 把剩余 extractor 逐个改造成契约插件（每个 ≤ 半天）：`_cs2_int_extract`（去 pycryptodome 硬依赖或
   随包带二进制）、`_ypf_extract`、`_pna_carve`、`asar_tool` 系、`_gyu_tool`（C# 源码随包 + csc
   运行时编译回退）、`_hg3_tool.exe`。
2. **csc 黑盒工作流产品化**：`_gyu_tool` 模式（源码随包、首启 csc 编译、失败给明确提示）写进
   toolbridge，ExHIBIT/HG-3 两处复用。
3. **验收**：12 样本全量回归（每个引擎至少一个样本走 orchestrator 全链，manifest 入案例库）。
4. **案例库**：`cases/`（JSON per 样本：指纹、判定、耗时、失败与修复）——蓝图 2.7 自愈闭环的地基。

### 阶段 3：Windows 软件壳（M2 → M3）
1. PyInstaller onedir 冒烟：**先验证「冻结 + subprocess 调外部 exe」**（蓝图 §4.3 官方坑，阶段 1
   未验证完的高风险项在此收口）。
2. `SetDllDirectoryW(None)` + PATH 清理写进 toolbridge。
3. Inno Setup 打包；杀软误报应对文档（蓝图 §4.5，社区实践非官方结论）。
4. GUI 最小化：先 CLI + 简单托盘/表单（拖一个目录进去 → 出 manifest 报告），不抢在管线稳之前。

### 阶段 4：AI 兜底（M3 后，按蓝图 §2.4 阶梯）
- A1（规则检索增强）→ A2（错误日志归因）→ A3（参数求解）逐个上，每个都用案例库做回归；
- A4（生成解析器）最后，且必须先有蓝图 §2.6 沙箱。
- 触发面已收敛：现在规则覆盖率 12 引擎 + 加密 krkr 全自动，AI 只接「真正没见过的」。

## 4. 风险与依赖（引用蓝图编号，防散失）

| 风险 | 处置 | 出处 |
|---|---|---|
| KrkrExtract GPL v3 vs API license=null | 只做「独立进程聚合」使用；分发时附其源码链接与许可文本 | 蓝图 §5.2 / §7.1 |
| FreeMote 禁商用（CC BY-NC-SA） | E-mote 分支暂不纳入软件默认能力 | 蓝图 §7.3 |
| GARbro 需 .NET 4.6+ | 安装器检测提示 | 蓝图 §4.4 |
| PyInstaller 冻结环境继承给子进程 | 阶段 1 §3.5 + 阶段 3 §3.1 双重验证 | 蓝图 §4.3 |
| 大样本磁盘占用（解包≈原包） | orchestrator 启动前查盘（纪律 6 已实测） | AGENTS.md 纪律 6 |
| CJK 路径（引擎层） | krkr 系 stage 必须 ASCII——已沉淀进 krkr_auto_extract.py | verified-findings §17.2 |
| 跨进程 WM_DROPFILES 不可行 | 加密 krkr 自动化已解决（Explorer 拖拽法） | verified-findings §17.3 |

## 5. 立即可做的下一步（按序）

1. `rules/engines.json` 抽取（把 `galgame_dispatch.py` 的指纹表原样外置，行为不变的纯重构）。
2. `toolbridge.py` + GARbro/tlg2png/ffprobe 三工具接入。
3. `orchestrator.py` 最小闭环（detect→extract→verify），用两个已交付样本做回归。
4. manifest 契约在 `krkr_auto_extract.py` 试点（数据现成：§17.5 的全部数字）。
