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

**⭐ counts 语义（2026-10-29 定案，修掉原计划的缺陷 #5）**：上面样例没区分「原始提取物」与「成品」，
实测 `高慢妻陥落！！` 时两者差很远（raw 2838 里含 865 个 .tlg，转完才有 1301 张图），
对账口径含糊就会两边都算不清。**定案 = counts 分三块，raw 与 final 各自独立对账**：

```jsonc
{
  "counts": {
    "raw":       {"by_ext": {".ogg": 1394, ".tlg": 865, ".png": 436}, "total": 2838},  // 提取器直接落盘的
    "final":     {"by_ext": {".ogg": 1394, ".png": 1301},              "total": 2695},  // 后处理完成后的交付物
    "converted": {".tlg": 865}                                                          // 被后处理消费掉的中间格式
  }
}
```

三条硬规矩：
1. **`raw` 是提取器的唯一自证**——必须等于封包条目数（`source.archives[].entries` 求和），差 1 都不许过。
2. **`final` 是交付口径**——报「图片多少张」时用 `final`（本例 1301 = png 436 + tlg 865 转出的），不是 raw 的 436。
3. **`converted` 解释 `raw.total != final.total`**——没有它，差额永远说不清是丢了还是转了。

**判定规则数据驱动**：`galgame_dispatch.py` 的指纹表移进 `rules/engines.json`
（签名/文件特征/判定次序），dispatch 与软件共用同一份（蓝图「规则要数据驱动」的落实）。

## 3. 分阶段路线（替换蓝图 §6 的占位内容，全部对准现有资产）

### 阶段 1：契约化 + 编排器（当前 → M1，预计 2-3 个工作日粒度）
1. ~~**manifest 契约落地**：给 4 个已统一接口的工具补 `--manifest`~~
   ✅ **全部 4 个已接（2026-10-30）**（`rpa_extract_organized.py`、`krkr_auto_extract.py`、
   `_rpgmv_decrypt.py`、`_ypf_extract.py`）。一律 `--manifest PATH`，不给就不写（不改变旧行为）。
   - ✅ **`krkr_auto_extract.py`（2026-10-29）**：走 `manifest.counts()`（raw/png 两目录形态），
     加密 xp3 无地面真相 → `reconcile.expected=None, diff=None, method="no-index-available"`
     （**明说没对账，不许用 diff=0 蒙混**）；`verify.verified=False` + note 指向 orchestrator/_verify_media。
   - ✅ **其余 3 个（2026-10-30）**：走新增的 **`manifest.counts_flat()`**（落盘即成品形态）。
     这三个工具的格式转换都做在**落盘之前**——`_rpgmv_decrypt.py` 的 `.rpgmvp` 落盘就叫 `.png`、
     `_ypf_extract.py` 的 `.ycg` 直接落 `.png`、RPA 条目本来就是裸存。
     磁盘上从不存在中间格式，所以 `raw == final`、`converted == {}`；
     硬造一个带 `.ycg`/`.rpgmvp` 的 raw 段就是**编数据**。转换明细（解密几个、YCG→PNG 几个、
     分类各多少）写进 `postprocess`，那才是它该待的地方。
   - 地面真相各自取：RPA = 索引**按名字去重**条目数（多段算一个文件）、YPF = 表内条目数、
     RPGMV = 工具自己数的 `decrypt + plain-copy`（每个候选文件必落且只落在这两类之一）；
     `--dry`（不落盘）时 `expected=None`，同样不许假装对过账。
   - 三份 manifest 都记 `source.out_root`（产物写到哪）——交付清单缺输出目录就没法交付。
   - 实测（2026-10-30，真实样本）：`gui_resource.rpa` 122/122 diff 0、`data.ypf` 195/195 diff 0、
     `常識改変学園` 7 个加密媒体 7/7 diff 0 且 `magic_fail_count=0`。
   - 测试：`tests/test_flat_manifest.py` 14 项（含「扁平工具不许套 CONVERTIBLE 悄悄抹掉 `.tlg`」
     和「必须记 out_root」两条护栏）。
2. **`galgame_dispatch.py` 升级**：~~指纹表外置 `rules/engines.json`~~ ✅ 已完成（2026-10-30，见 §5 第 5 项）；~~输出增加「建议 extractor + 参数」~~ ✅ 已完成（2026-10-30，`planner.py` + `--plan`/`--plan-json`，见 §5 第 6 项）。
3. ~~**`orchestrator.py`**~~ ✅ **已完成（2026-10-29）**：`detect → extract → postprocess → verify →
   manifest` 串成一条命令；每步产物与日志落 `--work`；对账不为 0 即停（纪律 2）。
   - 已接 **Ren'Py 与 KiriKiri 两条链路**（其余引擎判得出 → 退出码 2，明确「没链路」而不是假装成功）。
   - 退出码契约：`0` 全通过 / `1` 阶段失败或对账有差 / `2` 引擎判出但无链路 / `3` 未命中。
   - **实测**：`Swipe Right`（Ren'Py，4 包 2156 条目，退出码 0，图片 326/326、音频 1539/1539）；
     `兼职人妻`（KiriKiri 静态，2562 条目对账 0 差，507 个 tlg→png，图片 **902/902**、音频 1577/1577）。
   - 关键设计：地面真相一律取索引（Ren'Py 用 RPA 索引去重条目数、KiriKiri 用 GARbro 列表行数）；
     `--reuse-raw` **仍做对账**（跳步不等于跳验）；0 字节文件单列并用 1% 比例护栏兜底。
   - 测试 **143 项全绿**（`tests/test_orchestrator.py` 42 项契约 + `tests/test_orchestrator_smoke.py`
     真实样本冒烟；变异验证：改回「信退出码」→ rc 测试变红、去掉 0 字节护栏 → 2 项变红）。
   - 顺带修掉一个真缺陷：`_final_files()` 的标签在 Windows 嵌套路径下混用 `/` 与 `\`，
     已统一 `as_posix()`（manifest 要跨机器比对）。
4. ~~**外部工具桥** `toolbridge.py`~~ ✅ **已完成（2026-10-29）**：覆盖 GARbro / tlg2png / ffprobe /
   AssetStudio / KrkrExtract 五个。`python toolbridge.py check` 自检，`run(key, argv, product_dir=…)`
   统一调用；**成败一律由产物判定，退出码只作诊断**；路径按
   override → `TOOLBRIDGE_<KEY>` 环境变量 → `toolbridge.json` → 内置候选 → PATH 解析；
   子进程环境洗掉 `_MEI*`/`PYTHONHOME`/`PYTHONPATH` 并 `SetDllDirectoryW(None)`。
   坑 4（AssetStudio 逗号/竖线）已在 `assetstudio_export()` 里做成**参数级护栏**（直接抛 ValueError）。
   测试 101 项全绿（含「exit=0 但 0 产物必须判失败」的变异验证：故意改回信退出码 → 4 个测试变红）。
5. **验收**：拿 `高慢妻陥落！！`（加密 krkr）与 `Swipe Right`（Ren'Py）双样本回归，manifest 对账 0 差。
   > 原定第二样本 `My Best Deal` 已于磁盘消失（缺陷 #3），改用 `Swipe Right for Sugar Mama Sensei`
   > （四包 2156 条目，已双样本验证过通用性）。

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

> **2026-10-29 更新**：原第 1 项（`rules/engines.json` 抽取）**不是纯重构**，已后置——
> 指纹散在 `scan()` 的 17 个 `hit()` 调用里，还依赖 5 个有副作用的探测函数
> （`find_unity_version()` 解析二进制、`biggest_files()`、`count_subdir_games()`、`demojibake()`、
> `garbro_probe()` 调 subprocess）。外置 = 把 `scan()` 重写成「规则表 + 解释器」，
> 属**有回归风险的重构**，不该排在新增工作前面。调整后的顺序：

1. ~~`toolbridge.py` + 五工具接入~~ ✅ **已完成（2026-10-29）**，101 项测试全绿。
2. ~~`orchestrator.py` 最小闭环~~ ✅ **已完成（2026-10-29）**，见 §3 阶段 1 第 6 条。
3. ~~manifest 契约在 `krkr_auto_extract.py` 试点~~ ✅ **已完成（2026-10-29）**：
   先把契约抽成独立模块 **`manifest.py`**（唯一实现，供 orchestrator 与 krkr_auto_extract 共用
   ——两处各写一遍必然漂移，而 manifest 是交付清单，漂移就等于两个工具对「交付了多少」说法不一致），
   再让 `krkr_auto_extract.py` 走 `write_manifest()` 产出三段式 manifest。
   顺带修掉三个真实缺陷：
   - **`toolbridge.tlg2png()` 幂等盲点**：`--reuse-raw` 复跑时 png/ 已有上次成品，
     「产物增量 ≥ 1」判据看到增量 0 → 把 507 张图全判成失败。修法 = 调工具前先验
     `dst` 是否已是合法 PNG，是则跳过并 ok=True。「本次没新增」≠「失败」，可能只是**已经干过了**。
   - **`--reuse-raw` 跳过对账**：复跑时 extract 直接 return，没填 `expected_total`，
     manifest 变成 `期望 None vs 落盘 2562 (diff=None)`。修法 = 跳过解包但仍用索引算地面真相并对账
     （加密 xp3 列不出条目时 expected 才保持 None，并标 `no-index-available`）。
   - **`krkr_auto_extract.STAGE_ROOT` 指向已废弃的 zcode 路径** → 改为脚本同目录 `_krkr_stage`。
   测试 176 passed / 3 skipped（新增 `tests/test_manifest.py` 19 项、`tests/test_krkr_manifest.py` 7 项、
   toolbridge 幂等护栏 2 项、reuse 对账护栏 3 项）。
4. ~~**其余 3 个工具补 `--manifest`**~~ ✅ **已完成（2026-10-30）**：
   `rpa_extract_organized.py` / `_rpgmv_decrypt.py` / `_ypf_extract.py` 全部接上，
   新增 `manifest.counts_flat()`（「落盘即成品」形态：raw == final、converted 为空）。
   三个真实样本实测 diff 0：`gui_resource.rpa` 122/122、`data.ypf` 195/195、
   `常識改変学園` 7 个加密媒体 7/7。测试 190 passed / 3 skipped
   （新增 `tests/test_flat_manifest.py` 14 项）。
5. ~~`rules/engines.json` 抽取~~ ✅ **已完成（2026-10-30）**：
   落地为 `rules/__init__.py`（解释器）+ `rules/engines.json`（9 个引擎的权重/证据文案/魔数/扩展名）。
   **不是「把表搬出去」，而是「规则表 + 解释器」**——原 `scan()` 的 17 个 `hit()` 调用散在
   if/elif 分支里，重写成数据后由 `evaluate()` 统一求值。
   三条不变量（测试锁着）：`gate` 表达嵌套（父信号没触发子信号不计分）、
   `alternatives` 表达 `elif`（只让第一个成立的计分，否则 MZ+MV 双计分）、
   `for_each` 逐项计分（多个 `*_Data` 目录各算一次）。
   有副作用的探测（读二进制/起子进程/stat）**不进 JSON**，改为具名探针注入，
   规则文件里用 `probes` 声明——`rules.validate()` 静态查「用了没声明 / 声明了没用」。
   **零漂移验证**：`python tests/make_golden.py --check` → 6 fixture + 11 真实样本全部一致；
   测试 255 passed / 3 skipped（新增 `tests/test_rules.py` 53 项，含 6 项 `validate()` 变异验证）。
   顺带修掉 `garbro_probe()` 的**差一错误**（`len(lines)-1` → `len(lines)`；
   GARbro 列表无表头，实测 2562 条，与 `toolbridge.garbro_list()` 口径统一，加了护栏测试）。
6. ~~`galgame_dispatch.py` 输出增加「建议 extractor + 参数」~~ ✅ **已完成（2026-10-30）**：
   落地为 **`planner.py`**（判定 → 提取计划），由 `dispatch --plan` / `--plan-json FILE` 驱动。
   职责分离的理由：dispatch 管**判定**（要稳定到能进 golden 逐字比对），planner 管**分派**
   （随工具与参数频繁变动）——混在一起，改个参数名就得重刷 golden。
   三条硬规矩（测试锁着）：① 只写「怎么跑」不写「跑不跑得通」（`implemented` 只表示 orchestrator
   有没有接这条链，能不能解一律实跑定——坑 2）；② 参数只从实测事实拼（归档取自 `Report.archives`，
   绝不猜包名、猜哪个加密）；③ **`argv` 是列表不是字符串**（`Swipe Right for Sugar Mama Sensei`
   这种含空格路径用 shell 字符串拼必然出错），`cmdline` 只给人复制、不参与执行。
   `Report.archives` **故意不放进 facts**——facts 是判定证据快照（golden 逐字比对），archives 是拼
   命令行的原料，混在一起每次新增一条计划就冲掉 golden。
   9 个 builder 全覆盖 `ADVICE` 的 9 个引擎；已接 orchestrator 的引擎（Ren'Py / KiriKiri）给
   「一条命令走完全链」+ 单工具兜底 `extras`，其余 7 个标「orchestrator 未接，需单独跑」。
   产物一律落 `<仓库>/_extracted/<游戏名>/`（**不写进游戏目录**：会污染原包，且加密 KiriKiri 链
   要 stage 纯 ASCII 副本，混在一起分不清谁产生的）。
   **测试 278 passed / 3 skipped**（新增 `tests/test_planner.py` 23 项，含 3 轮变异验证）；
   `make_golden.py --check` 零漂移。顺带修掉 `_gyu_tool.exe` 写成裸文件名（靠 PATH 查找，PATH 里没有）。
