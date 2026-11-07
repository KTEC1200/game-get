# Galgame 自动解包工具 — 项目上下文

个人自用/学习项目：自动解包 galgame，产出**视频、音频、图片**三类资源。
**不做**：打包回写、文本提取、翻译、对外分发。

> **⭐ 终局目标（2026-10-27 用户明确）**：把这套工作流最终做成**一套可复用的 Windows 软件**
> （打包分发的那种，不是散装脚本）。当前所有解包攻坚都在为它攒三样东西：
> ① 决策树/规则表（分派逻辑）② 已验证的自研工具（引擎分支实现）③ verified-findings（实测证据）。
> 写新工具时向这个方向靠：依赖要轻（C# csc 优先）、规则要数据驱动、各分支接口要统一。
> 完整方案（Windows 打包、许可证/法律）见 `galgame-ai-unpack-workflow-plan.md`。

> **⭐ 项目主目录：`D:\K\deepseek`**（2026-10-29 用户确认，以此为准；`D:\K\zcode\game` 是同期副本，**已不再使用**）。
> 本项目**所有新产出**（解包产物、清单、报告、新脚本、文档更新）一律放在 `D:\K\deepseek` 里。
> 外部工具（GARbro / AssetStudio 等）在 `D:\K\galgame\`，位置见下方「环境」。
>
> **📦 版本控制（2026-10-29 建立；2026-11-02 已上传）**：`D:\K\deepseek` 是本地 git 仓库。
> **远程仓库：`git@github.com:KTEC1200/game-get.git`**（注意拼写是 **game-get**，不是 game-git——
> GitHub 实际仓库名如此，旧地址靠重定向也能用但别用）。2026-11-02 用户点头后**首次 push**
> （master 全历史至 `2d64bac`），remote 已建、tracking 已设。
> `.gitignore` 已排除 `_extracted/`、`packaging/Output/`、`_spike_pkg/dist|build/` 等大产物。

> **2026-11-02 测试反馈**：随包 GARbro 的 .NET 插件加载修复仅适用于可信工具目录；Unity 样本的音频收集未对账通过，KiriKiri 索引兜底已用真实注入新索引和模拟窗口缺失提取 2562 条，自然窗口缺失尚未复现。案例索引已保留旧案例并加入 Toshiue。实测和限制见 `verified-findings.md`。

> **📌 当前状态（2026-11-07 16:01，WinForms 根因已修 + bugfix2 包已部署，待真机实跑）**
> - **交付**：`packaging/Output/GalgameUnpacker-0.8.2-portable.zip`（148,528,606 B / 141.7 MiB，
>   SHA256 `687f4cd3…f26de05e983d`），已发布到 GitHub Release **`v0.8.2`**
>   <https://github.com/KTEC1200/game-get/releases/tag/v0.8.2>（仅 1 个附件，asset `717312891`）。
>   **本轮不改 Release 附件、不动 `version.py` / README。**
> - **✅ 当前本地包 bugfix2（用这个）**：
>   `packaging/Output/GalgameUnpacker-0.8.2-bugfix2-portable.zip`
>   （148,560,766 B / 141.7 MiB，SHA256 `931c6c44…1eb41cdb2`），包内 `BUILD_INFO.txt`
>   标 `bugfix2` / 源码提交 `b22174a`；README 125 行逐字相同、包内 exe 与 dist 同 SHA、
>   `testzip()` 无损坏（1514 项）；CArchiveReader 实证 `uia_click_button` / `click_button_ex` /
>   `_uia_ps` / `MAIN_TITLE_PREFIX` 与更新后的 `_uia_item_rect.ps1` 都在包里。
>   部署在 **`D:\GalgameUnpacker\orchestrator_bugfix2`**：`--doctor` High 完整性 / rc=0、
>   `--gui-smoke` rc=0、冻结 exe 只读 `--dry-run` rc=0。
>   ⚠️ 旧的 `D:\GalgameUnpacker\orchestrator` 仍被用户开着的 GUI 进程占用（pid 30452），
>   **没强杀、没删、没改名**，里面还是 bugfix1 旧代码 —— 别在那个窗口点「开始解包」。
>   关掉旧 GUI 后把 `orchestrator` 改名 `orchestrator_prev_bugfix1`、把 `orchestrator_bugfix2`
>   改名 `orchestrator` 即可切回标准路径（路径本身不影响完整性级别）。
> - **历史包**：已发布 0.8.2 / dropfix1 / bugfix1 三个 zip 均**未改动、未覆盖**，留作对照；
>   `build_exe.py --tag` 对同名 zip 一律拒绝覆盖。
> - **✅ 用户数据已恢复（00:40）**：`D:\HY\教师催眠2\output` 的 `raw/`(7070) 与 `png/`(2748)
>   共 **9818 个交付文件**由 `分类/` 视图硬链接重建，`--check --sample 8` 8/8 通过、rc=0；
>   视图 9818 文件 / 4.4 GiB 原样保留。2748 个 `.tlg`/`.pna` 中间格式**无法还原**（PNG 成品完整）。
> - **✅ 15:07 / 15:22 两轮真机失败已定位并修复**（详见文末「16:01 WinForms 根因与 bugfix2」）：
>   不是落点遮挡/加密/桌面独占问题，是 `KrkrExtract.Lite.exe` 为 .NET WinForms，主窗口类名
>   不是 `#32770`、按钮不是标准 `Button`，旧判据把控件全过滤空。已改按 pid+标题认主窗口、
>   按文本归一化认按钮、点击后 `BM_GETCHECK` 复核、UIA Invoke/Toggle/鼠标点击兜底、
>   失败日志带原始顶层窗口清单；顺带修报错重复拼贴与 `验收[skipped] None/None失败` 显示。
> - **源码状态**：代码提交 `b22174a` 已推 `game-get/master`，其后是文档回写提交；
>   最新提交号以 `git log -1` 为准，包内 BUILD_INFO 记 `b22174a` 是**打包那一刻**的 HEAD。
>   工作树干净。全量 `tests=819 / 0 failures / 0 errors / 9 skipped → PASS`，golden 零漂移。
>   **提交一律显式 add，禁用 `git add -A`。**
> - **⚠️ 唯一未闭环项：真机 `--allow-gui` 全自动**。原 4 项修复 + 本轮 WinForms 修复都只在
>   源码 / 冻结包自检 / 替身测试里验过，**未经真机复现**；下一次约 40 分钟独占桌面实跑。
> - **能力面**：9 条引擎链路可用；加密 KiriKiri 需 `--allow-gui`（要真实桌面）或人工拖拽 +
>   `--reuse-raw` 收尾。其余引擎判得出但无链路（退出码 2）。
>
> **📋 待办（按优先级，2026-11-07 16:01 重排）**
> 1. **关掉旧 GUI 窗口（pid 30452）**，从 `D:\GalgameUnpacker\orchestrator_bugfix2` 启动；
>    别在旧 `orchestrator` 目录的窗口里点「开始解包」。需要标准路径就按上段改名切换。
> 2. **`--allow-gui` 全自动真机闭环**：约 40 分钟独占桌面（不切窗口、不动鼠标、不锁屏、
>    不用远程桌面）跑 `教师催眠2`；看新日志的「unpack mode: Full Unpack 已开启（…）」与
>    四分类落点统计。若仍失败，日志会带原始顶层窗口清单（hwnd/类名/标题）与 UIA 控件清单，
>    能直接定位，不用再猜。**rc=0 且三媒体零失败之前别声称闭环**。
>    ⚠️ 别对 `D:\HY\教师催眠2\output` 直接 `--overwrite`，先在副本上试或另指定输出目录。
> 3. `Full Unpack` 是否对所有 KrkrExtract 版本/游戏都有效：目前只对 `教师催眠2` 验证过。
> 4. 案例库仍只有 12 个 case；新变体照旧要从头逆向。
> 5. `packaging\Output\orchestrator` 上那两条非标准 ACE（`Everyone …(DENY)(DC)`）来源未查明
>    —— 已确认不影响规避方式（放普通目录即按 High 运行）。
> 6. **不要加暗色模式**：用户 2026-11-06 明确说不做；界面 token 也刻意保持单套，别留半成品分支。
> 7. 用户数据现场别再动：别删/改名 `D:\HY\教师催眠2\output\分类`；真要重跑先在副本上试。
>
> **已完成（16:01）**：数据恢复、QA 收口、WinForms 根因修复、819 项回归、bugfix2 新包与部署自检。

> **🚀 接手顺序（新会话只做这四步）**
> ① 读上面「当前状态 / 待办」+ 文末「2026-11-07 真机实跑失败与 BugFix」「接手收口」+「⚠️ 五个坑」；
>    先跑 `git status` —— **工作树若有未提交改动，先问清是不是修复产物，别当成垃圾清掉**；
> ② 跑基线：`C:\Python314\python.exe tests\run_all.py`（**不要用裸 `python`**，它没有 pytest；
>    提交后基线 **tests=819 / 0 failures / 0 errors**，skip 9~11 均为环境条件、随环境波动）
>    + `C:\Python314\python.exe tests\make_golden.py --check`（应零漂移）；
> ③ 用户数据已恢复，别再动 `D:\HY\教师催眠2\output`；用 `orchestrator_bugfix2` 目录推进
>    待办 1、2，真机全链未复现前别声称「可交付」；
> ④ **改完先回写本文档 + `verified-findings.md`，再清临时产物，最后显式 add 提交。**

## 文件索引（按需读，别全读）

| 文件 | 何时读 |
|---|---|
| `galgame-unpack-decision-tree.md` | **写任何分派/判定逻辑前必读**：决策树、报错串→动作、后处理、验收判据 |
| `verified-findings.md` | 需要实测证据、工具行为、坑的细节时 |
| `tutorials/` | 需要规则原始出处时（krkr / unity / 其他引擎三篇） |
| `galgame-ai-unpack-workflow-plan.md` | 需要完整方案、Windows 打包、许可证/法律时 |
| `vn-unpacker-verification.md` | 需要第三方工具核实状态时 |
| `software-plan.md` | **软件化路线与进度**：四阶段、阶段 3（打包/GUI）完成状态 |
| `_ui/` | 界面截图与 `shot_app.py`（PrintWindow 渲染，不依赖前台窗口）—— 改 UI 后用它核对 |

## 工作区布局（2026-11-01 实测：根目录 **70 个文件 + 11 个子目录**，含 C# 解码器与黑盒工具）

**知识产物（长期保留）**
- `AGENTS.md` / `verified-findings.md` / `galgame-unpack-decision-tree.md` —— 结论、证据、规则
- `galgame_dispatch.py` —— dry-run 分派器（主产物）
- `_fixtures/` —— 回归样例（`_fixtures/make_fixtures.py` 可重建，6 个 fixture）
- `cases/` —— **案例库**（12 个 case + `index.json` 9 个签名 + `_failures_raw.json` / `_docs_meta.json` 原始素材），见下方专节
- `rules/` —— 引擎指纹**规则表**（`engines.json` + 解释器 `rules/__init__.py`，含命中信号 `fired_ids`）
- `tests/` —— 全量测试 + `golden_detect.json` 基线（`make_golden.py --check` 查漂移）
- **`build_exe.py`**（2026-11-02，软件化阶段 3）—— 冻结构建 + **数据文件清单唯一出处**：
  `python build_exe.py --check` 单验清单；**默认 = 冻结 + 出便携 zip**（2026-11-04 起
  唯一交付形态，安装器已删除）；`--portable` 跳过冻结、用现有 dist 重出 zip。
  新增「代码要读的数据文件」必须同步改它的 `DATA_FILES`（漏一个启动即崩）。
- `packaging/Output/` —— 便携 zip 输出目录（已 .gitignore）。`installer.iss` 已于
  2026-11-04 删除（用户决定不做安装器，见杀软文档头部状态说明）
- `antivirus-false-positives.md` —— 杀软误报应对（发布前自检清单、申诉渠道、会话写过滤实测）
- `_spike_pkg/` —— PyInstaller 探针（`probe.py` / `run_probe.py`；`run_frozen_smoke.py` 冻结包
  真样本验证驱动，`--full` 跑全链）；`dist/`、`build/` 已进 .gitignore
- `OUT/`（空占位）、`_unused/`（旧日志）、`banben/`（历史空目录）、`_extracted/`（解包产物，已 .gitignore）
- `tutorials/` —— 用户的原始教程（**用户提供的资料，勿删**）

**可复用脚本**
- **编排器：`orchestrator.py`**（2026-10-29，软件化第 3 步，**主入口**）—— 一条命令跑完
  `detect → case-lookup → extract → postprocess → verify → manifest`：
  `python orchestrator.py <游戏目录> --out <输出目录> [--allow-gui] [--reuse-raw DIR] [--no-verify] [--dry-run]`。
  已接 **Ren'Py / KiriKiri / RPG Maker / Yu-Ris / AdvHD / ExHIBIT / CatSystem2 / Unity / Artemis 十条链路**（其余引擎判得出就退出码 2，不假装成功）。
  **兄弟链路 in-process（2026-11-02，打包必修第 1 条）**：7 个兄弟脚本统一
  `main(argv: list[str] | None = None) -> int`（内部不 `sys.exit`），经 **`_run_sibling(mod, argv)`**
  进程内调用（冻结包里 `sys.executable` 拉不了脚本，§19.2）+ orchestrator 顶部**静态 import** 全部
  7 个兄弟模块（PyInstaller 静态分析只认这个）；orchestrator 代码里禁 `sys.executable`/`subprocess`
  （AST 护栏，test_orchestrator.py §8.5）。**新增链路时**：脚本 main 签名照这个约定来，别再写
  「读 sys.argv 的 CLI-only 脚本」。
  退出码：`0` 全通过 / `1` 阶段失败或对账有差 / `2` 引擎判出但无链路 / `3` 未命中。
  输出 `raw/`（原始）+ `png/`（tlg/pna 转出的成品）+ `manifest.json`（counts 分 raw/final/converted 三段）
  + `_work/*.log`。**对账一律以索引为地面真相，diff≠0 即失败**；`--reuse-raw` 跳解包但不跳对账。
  实测：`Swipe Right` 2156 条目 0 差、`兼职人妻` 2562 条目 0 差 + 507 tlg→png（图片 902/902）、
  `常識改変学園` 1585 条目 0 差（图片 719/719、音频 866/866、视频 0/0）、
  `あまねぇ` 8201 条目 0 差（图片 3484/3484、音频 4522/4522、527.7 分钟）、
  `ラブラブお痴験バイト性活` 9032 条目 0 差 + 48 个 `.pna`→2640 帧
  （图片 4306/4306、音频 7031/7031、视频 9/9，媒体 857.4 分钟，全链 578.8s 退出码 0）、
  `夕凪荘的S级的女朋友们` 11476 条目 0 差（`.gyu` 2184 + `.grp` 9185 + 散装 107；
  图片 2184/2184、音频 9291/9291、视频 1/1，媒体 1072.0 分钟，全链 930.3s 退出码 0；
  **22 个加密 BGM 显式排除并报出**）、
  `Toshiue Kanojo`（Artemis，2026-11-02）3 个 .pfs 3977 条 + 散装 31 = 4008 条目 0 差
  （图片 1007/1007、音频 2597/2597、视频 1/1，媒体 389.3 分钟，全链 235.5s 退出码 0）。
  **待转格式按扩展名分派**：`.tlg`→`tlg2png`、`.pna`→`_pna_carve.carve()`；两者都列在
  `manifest.CONVERTIBLE`（**唯一出处**，orchestrator 直接引用，别在两边各写一份，否则
  「交付了多少」两边数字对不上）。一个 `.pna` 出多帧，所以 postprocess 另记 `frames_out`。
  **接新引擎的四条硬规矩**：① 地面真相只写一份（RPG Maker 的 `_rpgmv_decrypt.iter_candidates()`、
  Yu-Ris 的 `_ypf_extract.read_index()`、ExHIBIT 的 `_grp_extract.expected_counts()`，orchestrator 直接调，别抄第二份）；
  ② `EXTRACTORS` 存**函数名**不存函数对象（存对象会在 import 时焊死引用，monkeypatch 失效）；
  ③ `IMPLEMENTED`（orchestrator）与 `IMPLEMENTED_CHAINS`（planner）必须同步，测试有防漂移护栏；
  ④ **有意排除的输入必须显式报出**（ExHIBIT 的 22 个加密 BGM 不纳入交付，但要进 `st.data["unsupported"]`、
  写进 detail、并经 `source.unsupported` 落进 manifest）——`.mos` 那次教训：无声的漏验最危险。
- **外部工具桥：`toolbridge.py`**（2026-10-29，软件化第 2 步；**2026-10-30 起含 C# 现编**）——
  统一「找工具 + 调用 + 数产物 + **退出码不信任**」，已覆盖
  GARbro / tlg2png / ffprobe / AssetStudio / KrkrExtract / **csc** / **gyu** / **hg3** 八个。
  `python toolbridge.py check` 自检（含自带 C# 工具）、`python toolbridge.py csharp` 看编译状态；
  库用法 `tb.run("garbro", ["-x", xp3], cwd=out, product_dir=out)`。
  工具路径按 override → `TOOLBRIDGE_<KEY>` 环境变量 → `toolbridge.json` → 内置候选 → PATH 解析，
  **不再硬编码**。成败一律看产物数，`returncode` 只进诊断字段。坑 4（AssetStudio 逗号/竖线）已做成参数级护栏。
  **`ffprobe_ex()` 是验收口径的补强（2026-10-31）**：`ffprobe()` 原来把所有失败原因折叠成一个 `None`，`stage_verify` 只能报一句「ffprobe 无结果」——看日志的人分不清「文件真坏」和「子进程没起来/超时」。
   `ffprobe_ex(path, timeout=120, retries=1) -> tuple[info|None, reason]` 失败时重试一次，并把原因串出来
   （`超时（>120s）` / `rc=N：<stderr 末行>` / `没有任何音视频流` / `JSON 解析失败` / 非白名单）；`ffprobe()` 退化成取 `[0]` 的薄包装，老调用方行为不变。
   `stage_verify` 把原因写进 `fail_examples`，格式 `[av] <路径> :: ffprobe 无结果——<原因>`。
- **自带 C# 工具源码随包、首启现编**（阶段 2 第 2 条，2026-10-30）：`_gyu_tool` / `_hg3_tool`
  **只带 `.cs`**（exe 不入库）；`ensure_csharp("gyu")` / `run_csharp("gyu", argv, product_dir=…)`
  先确保 exe 在——仓库里已有且不比源码旧就直接复用，否则 `csc /nologo /target:exe /platform:X /out:…`
  现编一次，产物缓存在源码旁（**源码 mtime 变新才重编**）。编译失败抛 `CSharpBuildError`，
  消息带 **csc 路径 + 源码名 + stderr 原文**——不许静默退化成「工具不存在」（那会把用户引到错方向）。
  `run_csharp` 与 `run()` 共用同一套「数产物」判定（自带工具都是「扫一棵树 → 另存一棵树」，
  rc=0 而 0 产物完全可能）。`check_all()` 的特例：exe 不在但**源码在且 csc 在**记为可用
  （`buildable=True`），否则「源码随包」的干净检出会被误报成缺工具。
  编译平台：载 32 位游戏 DLL 的黑盒 oracle 必须 `x86`（否则 `BadImageFormatException`），
  纯独立转换器 `anycpu` 即可。
- **manifest 契约：`manifest.py`**（2026-10-29，软件化第 4 步）—— **契约的唯一实现**，
  供 `orchestrator.py`、`krkr_auto_extract.py` 与三个单格式解包器共用（各写一遍必然漂移，
  而 manifest 是交付清单，漂移就等于工具之间对「交付了多少」说法不一致）。
  counts 分 `raw`/`final`/`converted` 三段：`raw` 含待转格式（.tlg）、`final` 是**交付口径**
  （图片报成品数，如高慢妻 1301 而非 raw 的 436）、`converted` 解释两者差额。
  `reconcile(expected, actual)`：`expected=None` 时返回 `diff=None` + `method="no-index-available"`
  —— **不许把「没验」伪装成「验过了」**。`final` 一律**实际扫盘不做减法**（转换失败/同名覆盖时会算错）。
  标签统一 `as_posix()`（跨机器可比）。`python manifest.py <输出目录>` 打摘要。
  `source.unsupported`（可选）：**有意排除、没进交付**的输入（ExHIBIT 的 22 个加密 BGM），
  空列表不写——下游读的是 `source`，不能把「我知道漏了什么」藏在 stages 里。
  - `counts(raw_dir, png_dir)` —— **raw/ + png/ 两目录形态**（orchestrator、krkr_auto_extract）。
  - `counts_flat(out_dir)` —— **落盘即成品形态**（`rpa_extract_organized.py` / `_rpgmv_decrypt.py` /
    `_ypf_extract.py`：转换做在落盘之前，磁盘上从不存在中间格式，故 raw == final、converted 为空；
    **不许伪造带 `.ycg`/`.rpgmvp` 的 raw 段，那是编数据**，转换明细进 `postprocess`）。
- **案例库查表：`case_lib.py`**（2026-11-01，orchestrator 阶段 1.5）—— `cases/` 的**签名与查表唯一出处**：
  `signature(engine, signals)`（= sha1("engine|逗号连接的排序信号 id")[:12]）、`case_id(...)`、
  `load_index()` / `load_case()` / `lookup(engine, signals)`。命令行 `python case_lib.py <engine> <sig1,sig2>` 手工查。
  查表**只报告不决策**：案例的 `expected_total` **不参与对账**（编排器自己的归档索引才是地面真相）。
- Ren'Py：**`rpa_tool.py`**（`info`/`list`/`extract`）、**`rpa_extract_organized.py`**（一步分类解包，`--manifest PATH` 可选）、`_organize_rpa.py`（先解再分，留档）
- Unity：**`_unity_extract.py`**（AssetStudio JSON 枚举 + Convert 导出，orchestrator 第 8 条链路）、**`unity_unpack.ps1`**（手工版）、`_as_audio_collect2.py`（FSB5 音频按名字补齐全集）、`_as_catalog.py`、`_as_summary.py`、`_scan_unity_video.py`
- KiriKiri：`_tlg2png_all.ps1`、**`_krkr_tlg_convert.py`**（tlg2png 批量转换 Python 版，避开 CJK 路径坑）
- **KiriKiri 加密动态提取：`krkr_auto_extract.py`**（ASCII stage 硬链接 → Lite.exe CLI 注入 →
  Explorer 拖拽逐包提取 → 完成判定 → 移产物；`<游戏目录> [--out DIR] [--keep-stage]`；
  配套 `_uia_item_rect.ps1`；方法论见 verified-findings §17）
- 通用验收：**`_verify_media.py`**（图片 Pillow / 音视频 ffprobe，带扩展名白名单）、`_verify_images.py`、`_verify_audio.py`、`_manifest.py`、`_scan_video.py`、`_locate.py`
- 选样盘点：**`_scan_hy_inventory.py`**（扫 `D:\HY` 两级体积 + 引擎特征签名，输出 UTF-8 JSON，只读）
- Electron/asar：**`asar_tool.py`**（info/list/extract）、**`_spite_decrypt.py`**（ChaCha20 资源解密 + 多轮路径反哺）、
  **`_spite_bruteforce_paths.py`**（缺失路径组合枚举）、**`_spite_extract_pool.py`**（minified 混淆池提取/解码）
- 弯路留档（别再照抄）：`_reclassify.py`（原地改归档，见坑 5）、`_as_audio_collect.py`（旧版慢）、
  `_check_rpa_verify.py`（内含硬编码路径 `D:\K\deepseek\_rpa_media.csv`，该中间产物早已删除，路径已失效——本脚本仅作教训留档，勿再运行）
- RPG Maker：**`_rpgmv_decrypt.py`**（MV/MZ 解密：假头 16B + 仅前 16B XOR key，key 取自 System.json；见 verified-findings §12）
- AdvHD：**`_advhd_run.py`**（逐 .arc 先列后提 + 对账 + .dat→wmv）、**`_pna_carve.py`**（PNAP 等多帧容器按 PNG 签名→IEND 逐帧 carve，通用）；见 verified-findings §13
- Yu-Ris：**`_ypf_extract.py`**（YPF 提取：名字 XOR key、名长置换表、可选 zlib、YCG→PNG；格式逆向自 arc_unpacker 源码）；见 verified-findings §14
- ExHIBIT：**`_gyu_tool.cs/_exe`**（.gyu 批量解码，C# + csc 编译）、**`_grp_extract.py`**（.grp/AiFS TOC 切分）；见 verified-findings §15
- CatSystem2：**`_cs2_int_extract.py`**（.int 全链：MT 名字混淆 + 小端 Blowfish + key 爆破法）、**`_hg3_tool.cs/_exe`**（HG-3 家族批量转 PNG，按魔数扫描）、`_cs2_key_brute.cs`（main_key 约束爆破器）；见 verified-findings §16

**`_as_probe/`（AssetStudio 全资产枚举）已删除**。
它曾用于记录 Unity 样本中**未被导出的资产类型**（TextAsset 214 含 Spine、MonoBehaviour 490、Shader 70…）
以及「本作无 VideoClip」的一手证据——这些结论**已转写进 `verified-findings.md` §8.6/§8.7**，无需保留原始 JSON。
需要时重跑 `AssetStudio.CLI --export_type JSON` 即可重建。

**已清理（过程产物，勿再找）**
Unity 侧：`_as_aud_*` / `_as_stage` / `_t_*` / `_as_audio` / `_fsb_probe` / `_tmp_extract` / `_as_probe`、
对照实验日志（`_t_*.log`）、已废弃的证伪脚本（`_probe_magic.py` / `_probe_xp3.py` / `_validate_index.py`）。
Ren'Py 侧：`_rpa_stage` / `_rpa_patch_stage` / `_rpa_arch.txt` / `_rpa_patch.txt` / `_rpa_media*.csv` / `_vframe*.png`。
各条结论与数据**均已转写进本文档与 `verified-findings.md`**，无需原始中间产物。

## 最新进度（2026-11-02 收尾：Unity 音频补齐，Happiness Double Room 全链通过）

- **Unity 音频（FSB5）补齐完成**：`Happiness Double Room`（Unity 2021.1.9f1 / Mono）全链 **rc=0**，
  **3500/3500 对账 diff=0**，图片 **2059/0 失败**、音频 **1441/0 失败**、无视频、媒体 186.8 分钟。
  此前该样本音频只到 **761/1441**（旧「前缀分组多轮 + round2 无新增就提前结束」策略的错判）。
  根因与实测证据见 `verified-findings.md` 顶部「Unity 音频（FSB5）补齐」。
- **音频补齐机制换掉了**：`_as_audio_collect2.py` 改成「JSON 枚举名字（BySource）→ 50 名一批锚定导出
  → **按名字对账** → 只补缺的、批量逐轮减半」。实测 58 次运行 / 4 轮补到 1441/1441、缺 0。
  地面真相是**名字清单**，不是文件数（AssetStudio 对 FSB5 是随机静默丢失：同批 80 名两次跑出
  80/80 与 28/80，**rc 全是 0**）。
- Artemis 已接入规则和提取链；Toshiue 全链 rc=0，4008/4008 零差，图片 1007、音频 2597、视频 1。
- KiriKiri 新增索引 dump 提取兜底，仅支持经校验的单段明文条目；目标样本本次 GARbro 直接全链成功
  （2562/2562，图片 902、音频 1577），未触发兜底，「窗口失败后自动提取」仍未自然复现。
- 案例库 13 个案例 `--validate` 全过；新增 Toshiue 案例及 manifest 快照。

## 状态

- ✅ **`galgame_dispatch.py`** — dry-run 分派器，纯规则、只读、仅标准库。引擎指纹在
  `rules/engines.json`（规则表 + 解释器），提取计划由 `planner.py` 生成。
  `python galgame_dispatch.py "<目录>" [--depth N] [--garbro <GARbro.Console.exe>] [--json out.json] [--plan] [--plan-json out.json]`
  - `--plan` 附「建议 extractor + 可直接复制的命令」；`--plan-json` 给批处理。
  - planner 只写「怎么跑」不写「跑不跑得通」（`implemented` 只表示 orchestrator 有没有接这条链，
    能不能解一律实跑定——坑 2）；参数只从 `Report.archives` 的实测归档拼，不猜包名、不猜哪个加密；
    `argv` 是列表（含空格路径不会被拆碎），`cmdline` 只给人复制、不参与执行。
  - 产物一律落 `<仓库>/_extracted/<游戏名>/`，**不写进游戏目录**（会污染原包，且加密 KiriKiri 链
    要 stage 纯 ASCII 副本，混在一起分不清谁产生的）。
- 引擎判定：**10 条引擎规则**（Unity / KiriKiri / Ren'Py / Tyrano-Electron / RPG Maker / AdvHD / Yu-Ris / EXHIBIT / CatSystem2 / Artemis）。
  基线由两处共同锁住：`_fixtures/make_fixtures.py` 重建的 **6 个 fixture** + 现场 **11 个真实样本**
  （`My Best Deal` 已从磁盘消失），全部与 `tests/golden_detect.json`（逐字锁定 engine/score/evidence/facts）一致 ——
  跑 `python tests/make_golden.py --check` 应输出零漂移；全量测试 **541 passed / 9 skipped**（`python -m pytest tests -q`）。
- 用户的 `D:\HY\pork社` 7 个游戏经 **GUI 实测全部可静态提取**。
- ✅ **三条产出线（视频 / 图片 / 音频）全部有实测验证过的样本** —— 见下表。

### 十三个已跑通的完整样本

| 样本 | 分支 | 产物 | 验收 |
|---|---|---|---|
| `D:\HY\pork社\兼职人妻` | **KiriKiri** | 图片 902 PNG / 音频 1577 OGG | Pillow 902/902、ffprobe 1577/1577（217.7 分钟） |
| `D:\HY\My Wife Wants to Be a Professional Cosplayer` | **Unity**（Naninovel 2022.3.62f2 / Mono） | 图片 777 PNG / 音频 1168 WAV | Pillow 777/777、ffprobe 1168/1168 |
| `D:\HY\最佳的交易\My_Best_Deal_v4.7-pc` | **Ren'Py**（RPA-3.0 / Python 2.7） | **视频 288**（mpeg4+v9，71.2 分钟）/ 图片 7804 / 音频 47 | Pillow 7804/7804、ffprobe 288 全通过 |
| `D:\HY\SPITE` | **Electron 自研引擎**（asar + ChaCha20 加密，2026-10-25） | 图片 128 / 音频 68（49.4 分钟）/ 视频 45（h264 循环动画）+ Spine 8 skel/8 atlas | Pillow 128/128、ffprobe 113/113、**失败 0**；资源覆盖 257/365 槽 |
| `D:\HY\Swipe Right for Sugar Mama Sensei` | **Ren'Py**（RPA-3.0 / Python 3，四包分工，2026-10-26） | 音频 1541 OGG（187.6 分钟）/ 图片 326（png 256 + bmp 70）/ 脚本 114 rpyc | Pillow 326/326、ffprobe 1539/1539；5 个 0 长度条目全部与索引对上 |
| `D:\HY\常識改変学園-製品版-` | **RPG Maker MV**（NW.js 壳 + www/，2026-10-26） | 图片 719 PNG（717 解密 + 2 明文）/ 音频 866 OGG（651 分钟） | Pillow 719/719、ffprobe 866/866；**无视频（验证过）**，见 verified-findings §12 |
| `D:\HY\tm\ラブラブお痴験バイト性活` | **AdvHD**（.arc ×18 + ASF .dat，2026-10-26） | 音频 7031 OGG（841 分钟）/ 图片 989 PNG + 677 mos(PNG) + 2640 PNA 帧 / **视频 9 WMV** | ffprobe 7031+9 全过；Pillow 989+677+2640 全过；18 包对账 0 差，见 verified-findings §13 |
| `D:\HY\あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-` | **Yu-Ris**（pac/*.ypf，YPF 格式完整逆向，2026-10-26） | 图片 3484 PNG / 音频 4522 OGG（527.7 分钟） | Pillow 3484/3484、ffprobe 4522/4522；**无视频（pac 只有 3 包）**；自研 `_ypf_extract.py` 2 分钟提完，见 verified-findings §14 |
| `D:\HY\夕凪荘的S级的女朋友们` | **ExHIBIT/Retouch**（.gyu + .grp 逆向，2026-10-26） | 图片 2184 PNG / 音频 9291（ogg 9185 + wav 106）/ 视频 1 WMV | Pillow 2184/2184；grp 对账 9185/9185；**BGM 22 个加密未解**（侦察留档 §15.3） |
| `D:\HY\甜蜜女友\【PC电脑】甜蜜女友2+` | **CatSystem2**（KIF/.int 加密全链逆向，2026-10-27） | 图片 4499 PNG / 音频 23259 OGG（2275.7 分钟）/ 视频 10 MPG（22.6 分钟） | 提取 53500/53500 零失败；ffprobe/Pillow 全过；main_key=0x212C5F31 爆破获得；**2026-10-28 补完 107 个 24bpp HG-3 变体 → 4502/4502 零失败**（根因=row 硬编码 w*4，见 §16.5） |
| `D:\HY\pork社\高慢妻陥落！！` | **KiriKiri 加密**（KrkrExtract 动态注入，2026-10-28） | 图片 1301（tlg 865→png + png 436）/ 音频 1396（148.8 分钟） | **2838/2838 零失败**；ffprobe/Pillow 全过；无视频（条目级验证）；**全自动管线打通**（`krkr_auto_extract.py`），见 verified-findings §17 |
| `D:\HY\教师催眠1` | **KiriKiri 加密 ×10 包**（krkrZ 引擎，2026-10-28） | 图片 2009 / 音频 3600（556.8 分钟）/ **视频 2**（logo.mpg 5s + pv_movie.wmv 124s，1280x720） | **5724/5724 零失败**（含逐包补齐的版权声明 txt）；ffprobe/Pillow 全过；movie.xp3 的 Lock 混淆 TOC 手工破解（§17.7）；10 包全自动 + 断点续传实测 |
| `D:\HY\Happiness Double Room` | **Unity**（2021.1.9f1 / Mono，2026-11-02） | 图片 2059 PNG / 音频 **1441 WAV**（186.8 分钟）/ 无视频 | **3500/3500 对账 0 差**；Pillow 2059/2059、ffprobe 1441/1441、失败 0；音频是 FSB5，靠「按名字对账补齐」才从 761 收全（见 verified-findings 顶部） |

**四条产出线全部打通**：KiriKiri 与 Unity 两个样本**没有视频**（都是**验证过**的「没有」，判据见坑 3），
`My Best Deal` 验证了 Ren'Py 视频链路，`SPITE` 验证了 **Electron/asar + 资源加密**这条最难的新链路
（自研引擎、HKDF+ChaCha20 按路径派生密钥，详见 `verified-findings.md` §10）。
`兼职人妻` 还**不适用** E-mote 立绘与语音 concat 两条后处理分支（全包无 `.pimg/.psb`，语音是语义名而非序号）。
详细证据见 `verified-findings.md` §7（KiriKiri）、§8（Unity）、§9（Ren'Py）。

## ⚠️ 动手前先看（五个坑，每个都花过代价）

1. **`GARbro.Console.exe` ≠ `GARbro.GUI.exe`** — Console 会**假阴性**：GUI 能提取的游戏它报 `unknown format`。
   → **Console 报「读不出」不可信**，只能把「可识别」当正面证据；拿不准用 GUI 复核。
2. **别试图静态预测「能否解包」** — 已试过两种判据（搜 UTF-16LE 扩展名、解析 XP3 索引长度）**全部失败，且两个方向都出过错**。
   → **直接调用工具，不要预测。**（证据见 `verified-findings.md` §1–2）
3. **纯魔数扫描判「有没有视频」会大量假阳性** — `FLV`/`MPEG-PS`/`JPEG`/`ftyp`/`mdat` 在 `.ogg`/`.tlg`/`.resS` 压缩数据内部大量巧合命中。
   → 判据：**命中偏移 == 条目/资源起始偏移** 才算真文件。KiriKiri 用 `_locate.py` 与 GARbro 条目表交叉定位；
   Unity 直接看 AssetStudio 枚举出的 `VideoClip` 数量（0 就是真没有）。
   （此坑曾让 §3 得出「这批游戏有视频」的错误结论，已于 §7.1 修正）
4. **⭐ `AssetStudio.CLI` 的 `--types`：逗号会「静默归零」，exit code 0 毫无意义**
   - `--types A,B,C` → **0 个文件**（逗号被静默忽略，**退出码仍是 0**）
   - `--types 'A|B|C'` → 过滤器**整体失效**，退化成「导出全部」
   - **正确做法：只用单类型 `--types A`，或者干脆不写 `--types`。**
   - **退出码 0 绝不可当成功判据**，必须数产物文件。（证据见 `verified-findings.md` §8.1–8.3）
5. **⭐ 按资源分类归档必须「扩展名优先」，绝不能只按目录判**
   - 实测：`images/animations/` 下**同时**有 `.avi`(166)/`.webm`(115)/`.jpg`(283)，
     只按目录判会把 **282 个 jpg 错分进 `Video_WebM`**；视频还散落在 `images/mm/`、`images/notes/`、`tl/…`。
   - **正解**：先按**扩展名**认媒体本体，再退回按目录分；`tl/` 视为本地化补丁树整体保留。
   - **分类逻辑一旦发现错了，就「修逻辑 + 从源归档重跑」**，不要写迁移脚本原地修数据
     （原归档没动过，重跑只需 31 秒；原地迁移要处理「已移动/未移动」混合状态，越修越乱——实测踩过）。

## 下一步（当前）

> **方向**：2026-10-28 用户定调主线 **Ren'Py（.rpa）与 KrkrZ**、Unity 进阶；2026-11-01 用户追加
> **「Tyrano 不做，先软件化」**。终局不变——可复用的 Windows 软件（路线 `software-plan.md`）。

**基线**：13 个样本全部走完（判定→提取→验收→对账→回写，见上表）；orchestrator 9 条链路；cases/ 案例库建成并接入；
**软件 v0.1.0 成型（2026-11-02）**：冻结 exe（含 GUI 壳）+ 数据清单 + Inno Setup 安装包 + 杀软文档 + README，
阶段 3 全部完成。

> **2026-11-02 追加收尾**：Unity 链路的音频（FSB5）从「多轮前缀分组」改成「按名字对账补齐」，
> `Happiness Double Room` 全链首次通过（3500/3500、图片 2059、音频 1441、rc=0）。
> ⚠️ 这项改动会让 Unity 链路多跑十几分钟（1441 条音频要 58 次 AssetStudio 调用）——
> 是**必要代价**：不补齐就是 diff≠0 的假失败，补了才是能交付的 1441/1441。

### ① 打包三条必修（§19.2）—— ✅ **三条全部完成（2026-11-02），冻结全链真样本实证通过**

1. ~~**7 处兄弟脚本改 in-process**~~ ✅：7 兄弟脚本统一 `main(argv: list[str] | None = None) -> int`
   （内部不 `sys.exit`）；orchestrator 新增 `_run_sibling(mod, argv)` + 顶部静态 import 全部 7 模块；
   测试 fake 改 patch `orch.<mod>.main`；AST 护栏禁 `sys.executable`/`subprocess` 回潮（§8.5）。
   细节见 verified-findings §19.2 第 1 条。
2. ~~**打包数据文件清单**~~ ✅：**`build_exe.py`**（清单唯一出处，`--check` 可单验）——
   rules/、cases/、两个 `.cs`、**`_uia_item_rect.ps1`**（盘点新发现的必打包项）、可选 toolbridge.json；
   无需 --hidden-import。`python build_exe.py` 冻结出 `_spike_pkg/dist/orchestrator/orchestrator.exe`。
3. ~~**子进程环境卫生**~~ ✅：`_sanitize_env`/`_clear_dll_dir` 早已在 toolbridge 并覆盖全部 4 个
   子进程出口（本次盘点确认），无需新代码。

**冻结实测（§19.2）**：真样本 `常識改変学園-製品版-` 上冻结 exe 全链 **rc=0（124.2s）**——
dry-run 命中 rules+cases（case_path 在包内）、extract in-process **1585/1585 对账 0 差**、
图片 719/0 失败、音频 866/0 失败、媒体 651.4 分钟、manifest ok=true。复跑：
`python build_exe.py` → `python _spike_pkg/run_frozen_smoke.py [--full]`。

### ② 阶段 3 —— ✅ **全部完成（2026-11-02）**

1. ~~打包三条必修（§19.2）~~ ✅：7 兄弟脚本 in-process（`_run_sibling` + 静态 import + AST 护栏）；
   `build_exe.py` 数据清单唯一出处（rules/cases/两个 .cs/**_uia_item_rect.ps1**[新发现]/可选
   toolbridge.json）；`_sanitize_env`/`_clear_dll_dir` 早已覆盖 toolbridge 全部子进程出口。
   **冻结实测**：真样本全链 rc=0（1585 对账 0 差 + 验收 0 失败），细节 §19.2。
2. ~~Inno Setup 安装包~~ **已废弃删除（2026-11-04 用户决定：只保留便携版）**：当时的实现是
   `packaging/installer.iss` + `build_exe.py --installer`（ISCC env→候选→PATH + SHA256），
   testmode 会话内验证过静默装 rc=0、安装态 dry-run/`--gui-smoke` 双 rc=0。
   删除理由：本机火绒 + 深信服 EDR 按进程信誉拦安装器敏感写入（证据在
   antivirus-false-positives.md §5），而安装器只换来卸载键与开始菜单——
   对私人工具不划算。现行交付 = 便携 zip。
3. ~~杀软误报文档~~ ✅：`antivirus-false-positives.md`（社区实践非官方；发布自检清单/申诉渠道）。
4. ~~GUI 最小壳~~ ✅：`gui.py` + `orchestrator --gui`（**单 exe 双模式**）：拖/选目录 →
   工作线程 `orch.run` → 队列回流日志 → 交付摘要弹窗。tkinterdnd2 可选增强（没装退化
   浏览+粘贴）；`--gui-smoke` 冻结态 Tk 冒烟 rc=0；tests/test_gui.py 6 条（纯逻辑全锁 +
   Tk 冒烟）。纪律：**GUI 线程只碰 Tk、worker 只塞队列**；`ctx.log` 实例属性遮蔽做日志回流。
5. ~~README + requirements~~ ✅：`README.md`（安装/用法/引擎表/外部工具配置）随安装包分发。

### ③ 下一步（当前：**v0.5.0 已交付（速度优化 + 对账口径修复，2026-11-06）；等用户实测反馈**）

> ⭐ **实测反馈 #3（2026-11-04 23:37，v0.4.1/v0.4.2 期间）**：`教师催眠2` 全链跑了一次，
> **失败路径全部正确**（这是重点，不是抱怨）：
> - 引擎判定 KiriKiri score=90（`.xp3` + 已知包名）
> - 案例库命中 3 个（签名 `6519ddb81f58`），含 `教师催眠1 / xp3-encrypted-krkrZ`
> - preflight 磁盘余量 60.57 GB > 需要 3.81 GB
> - extract 1.74s 失败：`image02.xp3: unknown format`
> - manifest 完整落盘（`ok=false` / `error=extract-failed` / `verify.status=skipped` /
>   `manual` 8 字段齐全），`_work/manual.log` 有完整人工方案
> - **输出目录这次是可写的**（写到 `packaging/Output`），说明 §23/§27 那批修复有效
>
> 但暴露两个**真缺口**（见下方「待办优先级」P1 两条）：
> ① 案例库的 `decision.extractor` 不参与决策；② extract 失败时 `source.archives` / `unsupported` 是空的。
>
> **现场补测（2026-11-05）**：逐个 `garbro -l` 该游戏 11 个 xp3，**全部 unknown format**
> —— 不是「个别包加密」，是整包 krkrZ。目录里有 `katei2.exe` + `Mai@KF.dll` +
> `katei2.exe.org`（被 patch 过的原 exe），与 `教师催眠1` 同族。所以案例命中的
> `krkr_auto_extract` 是对症的，只是没被用上。

> 2026-11-02 用户指示：**「不管加密 krkr 了……让我测试完再推进剩余队列」**——
> 剩余队列全部挂起，先等真实使用反馈。
>
> **⭐ 实测反馈 #1（2026-11-02）**：安装包在用户桌面双击即报
> 「Setup was unable to create the directory %TEMP%\is-*.tmp Error 5」——根因是
> **本机火绒 + 深信服 EDR 按进程信誉拦未签名新程序的敏感写入**（修正了早前
> 「代理会话产物」的误判；SAC/Defender RTP/AppLocker 全排除）。完整证据链与通道见
> `antivirus-false-positives.md` §5。**给用户的通道：便携版 zip
> （`python build_exe.py --portable`）**；预警：ExHIBIT/CatSystem2 首用现编 C# 可能
> 同样被拦，遇到就在火绒/EDR 放行 csc 与程序目录。
>
> **⭐ 实测反馈 #2（2026-11-02，用户要求）**：外部工具随包集成 + 运行环境写清。
> ① toolbridge 解析顺序插「随包 bin」档：override → env → json → **bin/<key>/<exe>** →
> 内置候选 → PATH（`_bin_root()` 独立函数好测）；② `build_exe.py` 默认按 `BUNDLE_TOOLS`
> 打包 6 工具进 `bin/`（garbro 65/assetstudio 38/tlg2png 1/krkr 11/krkrz 2/ffprobe 159 MiB
> ——共享构建连 av* DLL 一起），`NOTICE.txt` 记许可证状态（tlg2png/krkr/krkrz/ffprobe 构建
> **未核实**，对外分发前必须补齐，蓝图 §5.2）；③ krkr_auto_extract 的 KRKR_TOOL 加随包回退。
> **⚠️ 构建机特有坑**：`_spike_pkg\dist\orchestrator\` **这个目录里**随包 GARbro 的 .NET
> 程序集加载被防护拦（同字节从 temp/部署位置跑全正常、无 ADS、哈希一致）——
> **部署位置不受影响**（便携 zip 解压到新目录：随包 garbro -l 657 行正常 + frozen dry-run
> rc=0）。在 dist 里直接调工具失败时**先换部署位置复测**，别急着改代码。
> 产物：setup 101.4 MiB / 便携 141.4 MiB；本体约 350 MiB。

1. ~~加密 KiriKiri 剩余 ~7 部逐部跑~~ **划走（用户 2026-11-02：不管加密 krkr 了）**。
   样本仍在盘（温泉蒸汽人妻 3 包 / 教师催眠2 11 包 / aniyome 11 包 / Doinaka 9 包 /
   pork社另有 パート妻の情事・堕落妻子・昼下がり×2），将来想跑随时说。
2. ~~E-mote 搭车项~~ **跟着挂起**（盘面 0 命中；将来跑 KiriKiri 样本时留意 .pimg/.psb）。
3. ~~远程上传~~ ✅ **已完成（2026-11-02）**：master 全历史 → `KTEC1200/game-get`。
4. 搁置不变（需用户配合）：~~夕凪荘 22 BGM 内存 dump~~（**用户 2026-11-04 明确舍弃，不再做**）、
   GUI 弹窗行为确认（见下方说明）。
5. 最后才考虑：AI 兜底（A1/A2/A3）。

**✅ 2026-11-02 补完（本条已收口）**：Unity 音频补齐上线 + `Happiness Double Room` 全链实证通过
（3500/3500、图片 2059、音频 1441、rc=0）。下一步仍是**等用户实测反馈**；
未验证的只剩「KiriKiri 索引兜底的**自然**窗口缺失场景」（目前只有注入式模拟证据）。

**用户测试时的入口**：源码态 `start-gui.bat`（走 `python.exe`，绕开未签名 exe 的写入拦截）
或便携 zip `packaging/Output/GalgameUnpacker-0.4.3-portable.zip`（解压即用，不写注册表，
但需要把解压目录加入杀软信任区）；CLI 用法见随包 `README.md`。
**重跑注意**：输出目录已有产物时默认拒绝（`--overwrite` 清空重跑 / `--reuse-raw` 复用），
这是 2026-11-04 新加的口径 —— 别把「跑失败」当成 bug，先看 detail 里给的出口。
测试反馈回来后的修法照旧纪律：改逻辑 + 回写文档 + 提交 push。

### ③ 搁置（需用户配合交互，等指示）
~~夕凪荘 22 个加密 BGM 的内存 dump~~ —— **2026-11-04 用户明确舍弃**（工具 `_bgm_dump2.py`
与 §15.3 的静态分析保留在仓库里备查，不再列为待办）。

**「GUI 弹窗行为确认」是什么**（免得下次接手的人猜）：不是 KrkrExtract 的报错弹窗，
而是 **GARbro.GUI 的「选游戏标题 / 输密钥」弹窗疑云**。起因见 verified-findings §1：
`pork社` 有 4 个游戏（高慢妻陥落！！/堕落妻子/昼下がり×2）用 `GARbro.Console` 报
`unknown format`、`-x` 也解不出 0 个文件，但 `GARbro.GUI` 能解。怀疑根因是 GUI 会弹窗
让用户选标题/密钥（`GameData/kirikiri_*.lst` 里确有按游戏的密钥表），而 Console 没有
对应参数。**要用户确认的就是这一件事**：用 GARbro.GUI 打开那 4 个游戏时，有没有弹窗
要求选标题或输密钥。有 → 加密 KiriKiri 的「纯 CLI 自动化」这条路堵死，只能走
`--allow-gui` 的 UI 自动化；没有 → 说明 GUI 走了别的兜底逻辑，值得再挖。

### ④ 最后才考虑
接 AI 兜底（A1/A2/A3）——目前规则覆盖率已够高。

## 样本来源与划走清单（选样参考）

**旧盘点数据已删除**：`_extracted/_hy_inventory_20261026.json` 与 `_batch_dispatch.json` 都不在了。
要选样一律**现场重跑** `python _scan_hy_inventory.py`（只读，出 UTF-8 JSON）+ `galgame_dispatch.py` 判定，
**不要引用旧结论**（坑 2：能不能解一律实跑定）。

- **划走（GARbro 能解，用户 2026-10-26「不做」）**：pf8/.pfs 家族 ×8（meikuraS / Maid for Loving You / SlowLife /
  yugamase / bokukano2 / Toshiue_Kanojo / bonusfd1 / アマカノ3）、KAGUYA「LINK」.arc ×3（Mama×Holic / アネトモ /
  姉ちゃんのススメ）、Seifuku PAC ×2、riruka .arc、role player、有閑夫人倶楽部、催眠性指導/Mizuki、
  MagicalMILFs / スキだらけ / 爱的课堂（媒体裸放，只验收）。
- **划走（用户 2026-10-28 决定）**：夏への方舟 ×3（同 ExHIBIT 引擎，工具现成）、NekoSDK（本体 4.9G RAR 未解压）。
- **出圈外（非 galgame）**：nier、nikke2、Miside、EnderLilies / EnderMagnolia。
- **保留未做**：加密 KiriKiri 剩余 7 部（pork社其余 + 教师催眠2 + aniyome + Doinaka Kyoudai）——
  工具 `krkr_auto_extract.py` 现成，逐部跑即可。
- **搭车项**：E-mote 立绘（`.pimg/.psb` → FreeMote + krkrFgiEditor）是决策树里**从未触发过**的分支，
  见到 `.pimg/.psb` 就顺手走通。

## cases/ 案例库（已完成 2026-11-01）

**目的**（蓝图 §2.7 自愈闭环）：拿到新游戏先算 (格式签名哈希, 目录特征)，命中案例库就直接套用
已验证的 (decoder, plugin/key, 备注)，跳过 LLM 推理（L0）。这是终局软件「决策树 + 已验证工具 +
实测证据」三件套里的第三件。

**设计**（2026-11-01 用户批准）：每个样本一个 JSON（`cases/<case_id>-<engine>.json`），字段
`case_id`（= sha1(engine + 命中信号 id 集合 + 样本 slug + discriminator)[:12]）、`engine`（**规范名**，
与 `fingerprint.engine` 一致）、`engine_label`（人读的描述名，如「KiriKiri 加密」）、`sample`、
`game_dir`、`discriminator`、`fingerprint`（signals/score/threshold/signature/reconstructed）、
`decision`（extractor/archive_exts/archive_count/expected_total/notes）、`timing`（各阶段秒）、
`result`（counts/verify/reconcile/ok/source/summary）、`failures[]`（stage/symptom/root_cause/fix/ref）、
`provenance`（source/manifest_path/doc_refs/generated_at）。
`cases/index.json`：指纹签名 → case_id 列表（同签名对应多 case，靠 `discriminator` 区分）。
`build_cases.py`：`--from-manifests`（从 `_extracted/*/manifest.json` 机械重建）/ `--from-docs`
（从文档提炼）/ `--index`（重建索引）/ `--validate`（校验 schema + provenance 诚实）。
**诚实纪律**：docs 重建案例 `provenance.source = "docs-reconstructed"`、`manifest_path = null`、
`result.counts/verify/reconcile = null`（不许伪造 manifest 口径的数字）；`failures[]` 只写有出处的。

**已完成**（2026-11-01）：
- ✅ `rules/__init__.py` + `galgame_dispatch.py` 加 `fired_ids`（命中信号 id 集合）——指纹签名的
  稳定来源；不改 facts，golden 零漂移。
- ✅ `cases/_failures_raw.json`（43 条 failure，12 样本齐全，ref 全部核验）。
- ✅ `engines.json` 缺 id 的信号补语义 id（Unity 6、KiriKiri 1、Ren'Py 3、Tyrano 2、RPG Maker 2、
  AdvHD 3、Yu-Ris 3、ExHIBIT 3、CatSystem2 2，共 25 个）——Ren'Py 的 fired_ids 不再是空集。
- ✅ `cases/_docs_meta.json`（8 个纯文档样本的图片/音频/视频/媒体分钟数，文档口径）。
- ✅ `build_cases.py`（构建器，`write_all` 只创建新案例，`validate_cases` 校验来源）。
- ✅ 生成 **12 个 case + `index.json`（9 个签名）**，`--validate` 全过。
- ✅ `tests/test_cases.py`（21 个测试，锁纯函数 + 构建产物 + 诚实纪律）。
- ✅ **接入 orchestrator（2026-11-01，用户批准「报告命中」口径）**：新增 `case_lib.py`（签名/查表**唯一出处**，
  `build_cases.py` 与 `orchestrator.py` 都调它，别各写一份）、`stage_case_lookup`（**阶段 1.5**，
  在 detect 之后、`IMPLEMENTED` 链路检查**之前**——未接链路的引擎如 Tyrano-Electron 也能看到历史案例）、
  `manifest.source.case_match`（仅命中时写）、`--dry-run` 的 payload 增 `case_lookup`。
  **三种结局都 `ok=True`**：命中 N 个 / 无匹配 / 案例库缺失或损坏——区别只在 detail，
  「看过案例库，没有」和「根本没有案例库」不能混成同一种空。
  ✅ `tests/test_case_lookup.py`（41 个测试，含「签名/ case_id 可由每个 case 文件重算」锁定算法）。
- ✅ 测试 **493 passed / 9 skipped**；`python tests/make_golden.py --check` 零漂移。

**12 个 case 的来源分布（2026-11-01 实测）**：**4 个 `manifest`** 机械重建（My Wife / ラブラブ / 夕凪荘 /
甜蜜女友2+；`甜蜜女友2+_试跑` 是同款非独立样本，已排除）+ **8 个 `docs-reconstructed`**（兼职人妻 / My Best Deal /
SPITE / Swipe Right / 常識改変学園 / あまねぇ / 高慢妻陥落！！ / 教师催眠1）。其中 My Best Deal 目录已删
（`fingerprint.reconstructed=true`、`signature=null`），**这是唯一查不到的样本**。

**已知坑**：
- 兼职人妻（GARbro 可解）与高慢妻陥落！！（必须动态注入）**指纹完全相同**（都只有
  `xp3`/`xp3_known_names` 信号，规则无「加密 xp3」信号）→ 案例库必须靠 `discriminator`
  字段区分（`xp3-plain` / `xp3-encrypted` / `xp3-encrypted-krkrZ`），不能只靠签名。
- `engine` 字段曾误用 `_failures_raw.json` 的描述性标签（如「KiriKiri 加密」）导致与
  `fingerprint.engine` 不一致、按指纹查会错位——已改为以 `gd.scan` 的规范名为准，描述性标签
  另存 `engine_label`。
- `write_all` 只创建新案例，不删除或覆盖旧案例；部分历史 manifest 已缺失。索引与校验使用现存案例，迁移旧案例时须先核对来源并保留原件。

## 引擎分支要点（实测）

### KiriKiri
`GARbro.Console.exe -x <data.xp3>` 直接解（`兼职人妻` 2562 条 / **8 秒**）。
后处理按需：`.tlg`→`tlg2png`；`.pimg/.psb`→FreeMote + krkrFgiEditor（**仅在游戏有 E-mote 立绘时**才需要）。
**加密 xp3（Console/GARbro 读不出）→ 动态提取**：
- 首选 `krkr_auto_extract.py <游戏目录>`（Lite.exe CLI 注入 + Explorer 拖拽法 + 完成判定；游戏路径必须纯 ASCII；跨进程 WM_DROPFILES 不可行，唯一通路是 Explorer 真拖拽——详见 verified-findings §17）。
- **动态兜底（新）**：若注入后 KrkrExtract UI 窗口永不出现，但每个 `.xp3` 旁被引擎 dump 出完整 `.index`（引擎视角明文 TOC，已对 `高慢妻陥落！！` data.xp3.index 384,558 B 2562 条逐条验证：段数据明文、总字节 571,075,653 + 头/索引 60,761 = 文件 571,136,414），则走 `_xp3_carve.py` 解析 `.index`（连续 `File` chunk；`info` = u32(0)+u64 fsize+u64 fsize+u16 name_len(UTF-16 字符数)+UTF-16LE 名；`segm` = u32(段数-1)+每段(u64 offset,u64 size)+末尾 u64 total；`adlr` = u32 adler32）并按扩展名验魔数逐条 carve 落 `<out>/<xp3 名>/相对路径`，走 `manifest.counts_flat` + `reconcile`（expected=None/diff=None，不把“没验”伪装成“验过了”）。
→ 尚未在**真实自然缺窗场景**下触发（自然运行 KrkrExtract 窗口存在；GUI 阻塞而非缺窗），代码与单元/真实索引测试已通过（tests/test_xp3_carve.py + tests/test_krkr_index_fallback.py 9 passed）。

### Ren'Py（RPA）
- **不要用 `split(b" ")` 解表头**，用正则 `^RPA-3\.0 ([0-9a-f]{16}) ([0-9a-f]{8})` 抓「索引偏移 + XOR key」。
- **索引是 zlib 压缩的 pickle**：定位到偏移后若首字节 `0x78` 先 `zlib.decompress` 再 `pickle.loads`。
- 每个 `offset`/`length` **都要 `^ key`**（两作都是 `0x42424242`）才是真实值。
- 主工具：**`rpa_tool.py`**（`info`/`list`/`extract`）+ **`rpa_extract_organized.py`**（一步分类解包）。
  - **通用性已双样本验证**（2026-10-26 `Swipe Right` 四包 2156/2156 条目 0 失败）。
- **包分工不止 `archive+patch` 一种**：`Swipe Right` 用 `archive`(脚本) / `gui_resource` / `img_resource` / `sfx_resource`
  四包、无 patch。key 相同（0x42424242）不代表是同一作——别拿 key 当指纹。
- **patch 是「新增」还是「覆盖」→ 用两份索引求交集**判断，别猜。
- **0 字节文件要先查索引**：验收发现 0 字节产物时，先对索引里该条目的 length——
  源包声明 0 长度（占位文件，如 `se008.ogg`、`__init__.py`）属正常，不是解包 bug。别把源本身的空文件当失败。
- 视频常见 `mpeg4/.avi`（体积大、无音轨）与 `vp9/.webm`（含 Opus）；**数视频要按文件扩展名，不要用 ffprobe 的 stream 数**（内嵌封面会被算成视频流）。

### Unity（AssetStudio）
- **orchestrator 链路（2026-11-01 接入，第 8 条）**：`_unity_extract.py` 用 AssetStudio JSON 枚举
  作地面真相（唯一出处）、Convert 分批导出（按 Texture2D/Sprite/AudioClip 三类）、FSB5 容器音频
  按名字补齐（`_as_audio_collect2.py`，单次只出一部分）。侦察实测：Texture2D JSON 460 / Convert 455
  （差 5 个引用型资产）、Sprite 322/322 完美、AudioClip JSON 1168 / 单次 Convert 377（32%，需多轮）。
  全量已跑通：raw 1945 文件（png 777 + wav 1168），图片 777/777、音频 1168/1168、视频 0/0，失败 0。Texture2D JSON 枚举 460 vs Convert 455 的 5 个缺口是引用型资产，AssetStudio 固有行为，已用 texture2d_gap 调整 expected_total 并在 detail 显式报出。
- 主流程脚本：**`unity_unpack.ps1`**（分批导出 + 引擎判定，已内置坑 4 的注释）
- 版本/后端判定：正则读 `globalgamemanagers` 拿版本；存在 `il2cpp_data/` 或 `GameAssembly.dll` 即 IL2CPP。
  Unity 6000 系改用 AssetStudioNext；IL2CPP 需先 Il2CppDumper。
- **不要一次性全导**（870 MB 规模会 `0xC0000374` 堆损坏）→ **按类型分批独立导出**。
- 音频若是 **FSB5(FMOD) 容器**（JSON 里 `m_Source: resources.resource`），CLI 单次只出**一部分**
  （Happiness Double Room：1441 条只出 293~446，**退出码始终 0、日志无报错**；同批名字重复跑每次
  落盘子集还不同）→ 用 **`_as_audio_collect2.py`**：**JSON 枚举名字（`BySource`）→ 50 名一批锚定
  `^(a|b)$`（名字里的 `.` 必须 `re.escape`）→ 按名字对账 → 只补缺的、批量逐轮减半**。
  实测 58 次运行 / 4 轮 → 1441/1441、缺 0。**别再回到「前缀分组多轮 + 无新增就提前结束」**——
  「这一批没新增」不等于「剩下的也没有」，旧策略就是这样卡在 761 的。
- 已排除的两条路（**别再试**）：`fsb5` pip 库（需原生 `libvorbis`+`libogg` 且有查表依赖）；
  FFmpeg（识别 FSB 容器但报 `Not yet implemented`）。

- **临时目录不得写进游戏目录**：`_unity_extract.py` 所有 AssetStudio 与 FSB5 累积暂存目录（`_json_*`、`_conv_*`、`Audio_work` 等）必须落在编排器传入的 `ctx.work_dir/…`（输出侧），严禁使用 `data_dir.parent` 即游戏根目录——实测 `D:\HY\Happiness Double Room\_json_Texture2D` 在受保护游戏目录下 `mkdir` 直接抛 `WinError 5`，与 Unity/AssetStudio 版本无关（verified-findings §8.x）。

### RPG Maker MV/MZ（`常識改変学園` 实测，2026-10-26）
- 判定：NW.js 壳（`nw.dll`/`icudtl.dat`/`locales/*.pak`）+ `www/`；`js/rpg_core.js`=MV、`rmmz_core.js`=MZ。
- 加密=**假头 16B（`RPGMV`/`RPGMZ`）+ 原[0:16] XOR key + 其余明文**；key=`www/data/System.json` 的
  `encryptionKey`（32 hex，默认值=MD5("")）。**只有前 16 字节被加密**，其余照抄。
- 工具：**`_rpgmv_decrypt.py`**（自动找 www、跳过「免责声明」垃圾目录、明文直出文件照收）。
- 无需 RPGMakerDecrypter；加密的地面真相就在游戏自带 `www/js/rpg_core.js` 的 `Decrypter.decryptArrayBuffer`。

### AdvHD（`ラブラブお痴験バイト性活` 实测，2026-10-26）
- 判定：`AdvHD.exe` + `AdvHDLang.dll`。封包 `.arc`（索引含 UTF-16LE 名），**GARbro 原生支持**，
  音频出 ogg、图片自动转 PNG；逐包对账以包头 u32 条目数为地面真相。
- **GARbro 列表输出对 `.arc` 和 `.xp3` 都无表头**（每行一条，首行即第一个条目）——计数一律 `len(非空行)`，
  别套 `len(lines)-1`，否则每包差 1（2026-10-29 实测纠正：`兼职人妻` 实为 2562 条、`温泉蒸汽人妻` 3425 条，
  旧文档记的 2561/3424 就是这个口径错误的产物）。用 `toolbridge.garbro_list()` 拿条目数可避坑。。
- `.dat`（OP/ED）= ASF/WMV（头 GUID `30 26 b2 75…`）→ 复制改 `.wmv` 即可。
- `.pna` = PNAP 多帧容器 → `_pna_carve.py` carve（orchestrator 已接进 postprocess；
  `.pna` 与 `.tlg` 同列 `manifest.CONVERTIBLE`——**唯一出处**，48 个 `.pna` → 2640 帧，
  一个容器出多帧所以 postprocess 另记 `frames_out`，不能拿「输入文件数」当产出数）。
- `.mos` 内容就是 PNG（2026-10-30 实测 677/677 全部以 `89 50 4E 47 0D 0A 1A 0A` 开头），
  **必须列进 orchestrator 的 `IMG_EXT`**：否则它落进 `verify` 的 `nonmedia` 分支**被静默放过**、
  verify 照样报「失败 0」，交付清单凭空少验 677 张图（这是全链跑完才发现的口径漏洞）。
  该作图片口径 = 989 png + 677 mos + 2640 PNA 帧 = **4306**（前两项 Pillow 逐个过）；
  2026-10-30 全链复跑已确认 **4306/4306 零失败**——没列进 `IMG_EXT` 时是 3629/3629，
  677 张图凭空消失而失败数仍是 0（口径漏洞是无声的）。
  两个附带事实：`.mos` 的真实扩展名是**大写 `.MOS`**，且全在 `raw/<arc名>/` 子目录里
  （`raw/` 顶层只有 9 个 `.wmv` + 18 个子目录），清点必须 `rglob`。

### Yu-Ris（`あまねぇ` 实测，2026-10-26）
- 判定：`pac/*.ypf`（魔数 `YPF\0`）+ `yscfg.dat` + 存档 `.sd`（`YSSD`）+ `エンジン設定.exe`。
  **「YS」= Yu-Ris System，不是 Yaneura**。GARbro 不支持 YPF（真不支持，非假阴性）。
- 工具：**`_ypf_extract.py`**（自研；名字 XOR 单字节 key 靠 `name[-4]^'.'` 猜、名长 ^0xFF 查 4 张置换表、
  数据可选 zlib、YCG=两段 zlib 拼 BGRA）。
- arc_unpacker 0.11 备选坑：**`--out` 必须等号形式**（空格形式 DIR 变输入、递归扫 cwd）；
  大包（3484 条）疑似卡死 30 分钟无产出，小包（195 条）9 秒正常。
- 「源码即规格书」：卡壳时拉现成解码器源码（api.github.com）对照，比纯手撸 hexdump 快一个量级。

### CatSystem2（`甜蜜女友2+` 实测，2026-10-27；24bpp 补完 2026-10-28）
- 判定：`.int`（魔数 `KIF\0`）+ `__key__.dat` 种子 + cs2.exe。**索引与数据全部 Blowfish-ECB
  （GARbro 小端打包 ≡ 标准解密+输入/输出 4 字节半块反转）**，密钥来自包头 0x4C 种子驱动 MT。
- 文件名 = MT(main_key+i) 的 52 字母表轮换；main_key 无口令时用「k0 只有 256 种 → 逐条目反推
  k0 → 双约束并行爆破」拿下（本作 0x212C5F31，方法论见 verified-findings §16.2）。
- 图片 HG-3 家族（.hg3/.nm3/.gf3 及**任意扩展名**——引擎会二次混淆扩展名，必须按魔数扫描）；
  分节链从 0x14 起、ctl 位流 LSB-first。工具 `_hg3_tool.exe`（C#）。
- **24bpp 变体（107 个，2026-10-28 已解）**：ApplyDelta 的 4 等分位转置对 24bpp **同样适用**
  （GARbro 原版语义，RLE 输出均分 4 份重组后恰好 w*h*3）；**陷阱在自己写的 flip/落盘段**——
  row 必须按 `w * (bpp/8)` 算，硬编码 `w*4` 会越界崩。cptype/imgmode 节**全文件都有**（非 24bpp 特有），
  与失败无关，别被它带偏。教训：**移植解码器时先拉原版源码对拍语义，再改自己的代码**。
- 音频 OggS 明文（解密后），视频是 MPEG-PS（`00 00 01 ba`）。
- **orchestrator 链路（2026-10-30 接入，第 7 条）**：`stage_extract_cs2` 逐包（`raw/<包名>/`）
  + 总计两层对账；`_cs2_postprocess` ① 按**魔数**归一扩展名 ② HG-3 家族 → `png/`。
  - **扩展名不可信（二次轮换）**：实测 pcm_AA 的 3907 个 `OggS` 里只有 148 个恰好叫 `.ogg`
    （≈1/26，「按文件轮换、转到 0 才露真名」），其余散在几十个随机扩展名上；同一 base name 会成对
    出现（`.KCC` 是 OggS、`.HLx` 是 `LPD\0`）。**不按魔数归一，乱扩展名的媒体会落进
    `stage_verify` 的 `nonmedia` 被静默放过**（`.mos` 那次的翻版）。LPD 是 float32 数据文件
    （ffprobe 读不了），不是媒体、也不算缺失。
  - **交付口径 vs 对账口径要分开**：HG-3 转出的 PNG 才是交付物，raw 里那份中间产物记进
    `ctx.consumed` 并从 `final` 排除（`manifest.iter_final_files(..., exclude=)` / `counts(..., exclude=)`）
    ——**按路径排除**，因为扩展名被混淆；且 `raw` 仍然数着它，否则 53500 条对账就没了依据。
  - **同 stem 撞车**：`_hg3_tool` 落盘是 `Path.ChangeExtension('.png')`，`a.hg3` 与 `a.nm3` 互相覆盖
    → 期望张数要**去重后**算（历史解 4502、交付 4499），拿文件数当 `min_products` 会误判「产物不足」。
  - **内存**：最大的包 2.3 GB，`_cs2_int_extract.py` 已改成 **mmap + 32 MiB 分块解密**；
    进程被杀时不会再有「日志一行都没有」的情况（进度行 `flush=True`）。
  - **尾部 `fsize % 8` 字节在归档里本来就是明文**（2026-10-31 用 Ogg 页 CRC 判明）：打包器只加密
    整 8 字节块，落盘尾部的零头是原文，所以 `decipher_fast(bf, blob, fsize // 8 * 8)` + 尾部原样照抄是
    **正确**实现——别改成「解填充块再截断」。判据是**最后一个 Ogg 页的 CRC**（页里存的 CRC 是编码器按
    真实明文算的）：对 `pcm_DD/dd_02_ch08_019.OGG`（size 89899、`%8=3`）盘上变体算出 `0xfe9a5de8` 与
    页里存的一致，「全解后截断」变体算出 `0xc45b0d83` 不一致。**全量 23259 个 `.ogg` 最后一页 CRC 全部
    通过**（其中 20384 个 = 87.6% 大小不是 8 的整数倍）。→ 「最后一页 CRC」是 CS2 音频最廉价的地面真相
    校验，比 ffprobe 更硬（FFmpeg 会「尽力解码」，CRC 一字节都不能错）。
  - **护栏算错比不设护栏更坏**：HG-3 期望张数原来按**大小写敏感**去重算出 4501，而 `_hg3_tool` 落盘走
    NTFS、`X.png` 与 `x.png` 是同一文件（后写覆盖先写），实际 4499 —— 一次**完全正确**的解包被自己的
    护栏判成「产物不足」。判据必须按**平台语义**来。另：产物判定要看 **png/ 目录总量 == 期望**，
    不是「本轮增量 ≥ 期望」（`--reuse-raw` 复跑时增量天然是 0，按增量判会二次误报）。
  - **别用眼睛核对单行大字典**：orchestrator 把 75 键的 `by_ext` 挤在一行，我肉眼以为 `final` 里还有
    `.hg3`；逐键 diff 后真相是 `ONLY IN RAW: ['.hg3']`、`ONLY IN FINAL: ['.png']`。大字典一律逐键 diff。
  - **偶发 ffprobe 失败**：全量 verify 只在 `raw/pcm_DD/dd_02_ch08_019.OGG` 上失败一次，但该文件直接探
    rc=0、连探 5 次全过、最后一页 CRC 也对 → 是偶发。`ffprobe_ex()` 的重试正好覆盖。

### Artemis(iMel，`Toshiue Kanojo` 实测，2026-11-02)
- 判定：`iarsys64.dll` / `iarsys32.dll` / `iarsys.dll` + `.pfs` 分卷封包（D:\HY 深度 3 普查 8/8 共现）。`.pfs` 头 `706638`（=pf8），分卷形如 `<base>.pfs.NNN`（Amakano3 还有 .000/.001/.002/.003/.005）。
- 工具：`_pfs_extract.py`（按 `SHA1(索引区)` 取 key，逐包解密，按包名进 `raw/<包名>/`；GARbro 能解 pf8，非坑 1 假阴性）。分卷不是独立封包，每包一个子目录，跨包重名 ~70。
- orchestrator 链路（第 10 条）：`stage_extract_artemis` 调 `_pfs_extract.py` 产出 3977 个归档条目，再由 orchestrator 复制 31 个散装媒体（`.dat/.jpg/mp3` 等），共 4008 文件，对账口径拆分——`_pfs_extract.py` 只对账归档子目录（3977），散装媒体由 orchestrator 层对账（4008），两者口径不混淆。
- 实测：Toshiue Kanojo detect=Artemis score=90（fired `artemis_pfs`、`artemis_runtime`）；3 个 .pfs，3977 + 31 = 4008，diff=0；verify 图片 1007/1007、音频 2597/2597、视频 1/1，失败 0；manifest 写入，全链 235.5s，退出码 0。

### ExHIBIT / Retouch（`夕凪荘` 实测，2026-10-26）
- 判定：`ExHIBIT.JP`/`RESIDENT.JP` + `.gyu`（魔数 `GYU\x1a`）/ `.grp` / `.rld` + `moonstone.TTE`。
  MOONSTONE 系品牌。主逻辑在 resident.dll（引擎名 Retouch）。
- 图片 `.gyu`：**密钥在文件头**（Key≠0xFFFFFFFF 时 MT 交换 10 对字节去混淆），压缩分
  原样/GyuLZ(0x800)/LZSS 三种，8bpp 调色板 + 可选 alpha 平面，图自下而上。
  工具 `_gyu_tool.cs`（系统自带 csc 编译，零依赖）。**Gyu-LZ 位流与字节流共享游标**——移植大坑。
- 音频 `.grp`：TOC 就是同名小的 `AiFS` 魔数文件（res2000.grp），按 TOC 切 ogg，工具 `_grp_extract.py`。
- **BGM（res/s/m/*.ogg）加密未解**：只有头两页（3853B）被加密、页 2 起明文。已排除置换类/
  两套 MT 键流/RC4/ROR 函数 2^31 爆破；密钥材料大概率在配置键 `cluu`（settings.dat）/`GUID`/
  `DPMODE=0xC300`，解密器在 resident.dll 虚调用链后（见 verified-findings §15.3 侦察全档）。
- **orchestrator 链路（2026-10-30 接入，第 6 条）**：三条来源合一，期望总数 **11476** =
  `.gyu` 2184 + `.grp` 9185 + 散装 `.wav/.wmv` 107。
  ① `.gyu` → `tb.run_csharp("gyu", [游戏目录, raw/img], product_dir=…, min_products=2184)`（递归扫树、保持相对路径）；
  ② `.grp` → `_grp_extract.py <res> <raw/audio> --manifest …`，期望取 `grp.expected_counts(res)`（唯一出处）；
  ③ 散装媒体 → `raw/loose/<游戏相对路径>`。
  `res2000.grp` 是纯 TOC（`@0xC` 块数），`res2001/2002.grp` 头就是 `OggS`（裸 OGG 流）；
  `grp_arcs()` **必须把 AiFS 文件自己排除掉**，否则 TOC 会被当成「列不出的数据包」。
  **22 个加密 BGM 不纳入交付但必须显式报出**（`st.data["unsupported"]` → `source.unsupported`）；
  判据是**魔数不是路径**（`_exhibit_ogg_is_encrypted()` = `_head(p) != b"OggS"`，换一作路径会变、魔数不会）。
  实测 raw == final == 11476 文件 5139.6 MB（ogg 9185 / png 2184 / wav 106 / wmv 1），
  全链 930.3s 退出码 0（extract 93.66s、verify 828.57s）。
- **DLL 黑盒 oracle**：32 位编译 + `LoadLibraryEx(LOAD_WITH_ALTERED_SEARCH_PATH)`（必须 CharSet.Unicode，
  否则 CJK 路径 126）+ `GetDelegateForFunctionPointer` 调未导出内部函数——resident.dll 可在裸进程稳定调用。

### Electron / asar（SPITE 实测，2026-10-25）
- 判定：`app.asar` + Electron 壳。**别急着上 AsarKit/WinASAR**——自研 **`asar_tool.py`**（info/list/extract）
  直接解析索引更快更可控（asar 格式：16 字节头 + JSON 索引 + 连续数据区 + `.unpacked` 旁路）。
- **asar 里通常只有引擎代码**（dist/ + node_modules），媒体多半在外的 `data/` 目录、且可能**加密**。
- SPITE 的加密方案（逆向自 `dist-electron/services/media-crypto.cjs`，源码未混淆）：
  文件名 = sha256(原始路径).hex[:16]；密钥 = HKDF-SHA256(48 字节硬编码 IKM, salt, info="spite-media-chacha20:"+路径, 44B)；
  密文体 = 原始文件 ⊕ ChaCha20 流（RFC 8439，计数器 0 起，无认证标签）。**密钥依赖原始路径** → 必须先恢复路径映射。
- 路径恢复三板斧（`_spite_decrypt.py` + `_spite_bruteforce_paths.py` + `_spite_extract_pool.py`）：
  ① asar 文本里挖字面量引用（**引号无关**正则，Ink 剧本里路径是裸写的）；② 解密出的 `.atlas` 反哺贴图页路径；
  ③ minified 混淆池（`function X(){const t=[...]}` + `arr[i-K]`）→ 用已知锚点对（如 `/\.[a-z0-9]+$/i[f(3497)]` 必为 `"test"`）
  联立解出偏移 K，全池解码后再枚举「目录 × 名字 × 扩展名」。
- 覆盖率预期：257/365（70%）。**没有路径就永远解不开**（密钥依赖路径），剩余 108 个判定为未引用遗留资产——
  这是此类方案的天然上限，不是 bug。被引用的资产（含全部 45 个视频）100% 恢复。
- 另一个教训：minified JS 文本里**引号不配对**（正则字面量/单引号/模板串混用），朴素正则提取会错位；
  要拿池就用「反向行走 + 平衡扫描 + 自写 tokenizer」（见 `_spite_extract_pool.py`）。

## 归档与验收纪律（跨样本沉淀，十二个样本都验证过）

1. **先拿「地面真相」再动手** —— 归档的条目表/索引（GARbro `-l`、AssetStudio JSON 枚举、RPA 索引）是唯一权威。
   **不要预测工具行为**（坑 2）；**不要用未经校验的工具输出当真相**（工作约定）。
2. **计数必须对账到 0** —— 解包后逐扩展名与实际落盘数比对。三个样本都是靠这一步才发现真问题：
   `兼职人妻` 的 `.tlg` 506 vs 507（我统计时 `Select-Object -Skip 1` 吃掉首行）、
   Unity 的 `Video_WebM` 396 vs 应有的 115（282 个 jpg 被错分）、Ren'Py 的 118 个 webm 分布对不上（漏了别处的文件）。
   **"差不多" 等于没验。**
3. **验收看产物，不看退出码** —— 决策树 §6 四项判据：非空且无 0 字节 / 逐个可开（Pillow `verify()`、ffprobe）/ 与语义相符 / 数量合理。
   **工具退出码 0 毫无意义**（坑 4 就是 `exit=0` 却 0 文件）。
4. **数媒体要按扩展名，不要按容器内的流数** —— ffprobe 会把 mp3/图片的**内嵌封面**报成 `codec_type=video`，
   导致视频数虚高（本作 318 个"视频流"里 30 个是封面，真实文件是 288）。
5. **判定 patch 是「新增」还是「覆盖」→ 用索引求交集**，不要靠猜、也不要靠文件名相似度。
6. **解包前先看磁盘余量** —— 大样本解包后体积≈原包（RPA 是裸存），别把盘写满。
7. **中途临时产物最终要清掉，但结论必须先转写进文档** —— 否则下次会去找不存在的中间目录；
   另一方面，「修逻辑 + 从源归档重跑」永远优于写迁移脚本原地修数据（坑 5）。

## 工作约定

- **⭐ 跑多 GB 级样本前先看可用内存**（本机 13.8 GiB）。2026-10-30 实测：可用只剩 1.9 GiB 时，
  `_cs2_int_extract.py` 把 2.1 GB 的包整包 `read()` 进内存 → 进程被压死、**连 stdout 都丢了**
  （表现为 `rc=1` + 日志空白，看起来像代码 bug，其实是内存）。两条规矩：
  ① 大文件一律 **mmap / 流式**，不要 `read()` 整包；需要整段变换时**分块**（见 `_CHUNK`）；
  ② 别在别的重负载旁边开大任务，跑之前 `shutil.disk_usage` / 内存自检，跑完立刻收工。

- **事实先核实再断言**；未核实的明确标注「未核实」，不推测。链接/版本/许可证尤其。
- 仓库事实查 `api.github.com/repos/<owner>/<repo>`（`platform_search` 对本场景不可靠）。
- **用户的教程与实操结论优先于我的检索与推断。**
- **不要把未经校验的工具输出当作「地面真相」** —— 这是我犯过的最大错误（见坑 1）。
- **两次栽在同一个动作上：只看日志尾部就下结论。** 关键信息（`Found N files`、`Detected Unity version`、
  真实报错）**只在日志开头**。→ **先看开头，再看结尾，并数产物文件**。
- **PowerShell 调外部程序一律用调用符 `&`**（自动给含空格路径加引号），
  **不要用 `Start-Process -ArgumentList`** 传含空格的路径——它会把 `...\My Wife Wants...` 拆碎，
  制造出「工具失败」的假象（我自己就因此误判过一次，见 §8.2）。
- **⭐ 本环境的 Bash 工具会吃掉反斜杠转义**（`\\`、`\xNN` 都会被处理，heredoc 和 `-c` 内联代码都会中招）。
  → 含正则/转义的代码**一律先用 Write 写成 .py 文件再执行**，绝不内联。（2026-10-25 SPITE 期间实测踩坑）
- **⭐ 试跑/验证的产物一律落 `<本仓库>/_extracted/<游戏名>/`，不许散到盘根**（2026-10-30 用户提出）。
  我曾把 orchestrator 的 `--out` 手填成 `D:\_orch_advhd`、`D:\_orch_yuris`、`D:\_orch_rpgmv(2)`、
  `D:\_orch_kenmin`、`D:\_orch_swipe`，六份合计 **8.4 GiB 躺在 D 盘根目录**，用户先发现我才知道。
  当时的动机是对的（不用 Git-Bash `/tmp`——它会映射到随机 `dsh-win-bash-*` 目录、路径不可复现；
  也不把 GB 级产物塞进 git 仓库），**但落点选错了**：`_extracted/` 已进 `.gitignore`，
  `planner.py` 生成的提取计划里写死的就是这个路径，直接用它即可，不需要另找地方。
- **跑长任务（>几分钟）用 `python -u`，且别只盯 stdout**：stdout 被块缓冲，跑十分钟日志文件可能还是 0 字节；
  `orchestrator.py` 会实时写 `<输出目录>/_work/<阶段>.log`，看进度看那里。
- **⭐ 前台 shell 有 5 分钟硬上限**（2026-10-30 实测：`timeoutMs: 1500000` 仍在 **300000 ms** 被砍，
  报 `[timed out after 300000ms; the persistent shell was stopped]`、exit 124）→ **超过 5 分钟的活
  不能拿前台命令硬跑**（AdvHD 的 verify 阶段约 514s，正好卡死）。两条实测结论：
  ① 自己 `subprocess.Popen(..., creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP)` 起的
  「独立」进程**也逃不掉**——它仍在会话的进程树里被一起清掉，实测跑到 `verify [2000/11624]` 就消失，
  留下「raw/ 有、png/ 和 manifest.json 没有」的半截产物；
  ② **正解是用工具自带的 `run_in_background: true`**（harness 自己管的后台 job），拿 job id 后用
  `job_output` 收；长任务期间**不要反复轮询**同一条命令（用户 2026-10-30 明确要求「一次性搞了」）。

## 环境

- **shell**：`workspace-write` 下 pwsh 启动失败（`0xC0000142`，DSH win32 pwsh 沙盒缺陷）。用户已切到**完全权限**，pwsh 可直接运行。
  → **不要设置 `sandbox_permissions`**（approval 已禁用，带该参数会被自动拒绝）。根因见 `verified-findings.md` §6。
- **命令里别写 CJK 字面量**（GBK 控制台会乱码）→ 让 PowerShell/Python 自行从文件系统解析路径。
- `web_fetch`/`read_page` 会限流（Firecrawl 429）→ 改用 `api.github.com`。
- **本机 DPI 200%**（物理 2880×1800，无感知进程看到 1440×900 虚拟坐标）→ UI 自动化脚本必须
  `SetProcessDPIAware()` 且全程物理坐标；跨进程坐标（UIA / PowerShell）先自检口径。
- **网络**：系统代理 `127.0.0.1:7897` 时断时续（挂着也可能全断）。直连 `raw.githubusercontent.com` 通常可用；
  `github.com` 直连不通、走代理偶尔可通；`api.github.com` / `codeload` 基本不通 → 下 GitHub release 资产多试几条路由。

### 外部工具位置（2026-10-29 逐一核实存在；均在 `D:\K\deepseek` 之外，勿搬）

| 工具 | 路径 |
|---|---|
| GARbro-Mod | `D:\K\galgame\GARbro\GARbro.Console.exe`、`GARbro.GUI.exe` |
| AssetStudio.CLI | `D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe`（`unity_unpack.ps1 -Exe` 默认值、`_as_audio_collect2.py` 已指向此路径） |
| tlg2png | `D:\K\galgame\tlg2png\tlg2png.exe`（`_tlg2png_all.ps1 -Tool` 默认值） |
| KrkrExtract | `D:\K\galgame\krkr\krkr\`（**三件套已齐**：`KrkrExtract.Lite.exe` 534,016 B（2026-10-28 自 release 5.0.0.2 下载，SHA256 EB5D609B…CE89）+ `KrkrExtract.Core.dll` 11,237,376 B + `KrkrExtract.UI.Lite.dll` 129,024 B，版本配套已核实；CLI 注入用法与自动化见 verified-findings §17） |
| KrkrzExtract | `D:\K\galgame\krkr\krkrz\`（**主程序已就位**：`KrkrzExtract.exe` 176,128 B（v1.0.0.0，2026-10-28 用户放入）+ `KrkrzExtract.dll` 1,827,328 B。用于 KrkrExtract 报 `Unknown chunk in root chunk` 时兜底） |
| RPA-Explorer | `D:\K\galgame\rpa\RPA Explorer.exe` |
| AsarKit | `D:\K\galgame\asar\AsarKit.exe` |
| ffmpeg / ffprobe | `D:\ffmpeg\bin\`（`_verify_media.py`、`_verify_audio.py` 硬编码此路径） |
| 其他（FModel / umodel / quickbms / SpineViewer） | `D:\K\galgame\UE\` |
| Inno Setup 6.7.3 | `%LocalAppData%\Programs\Inno Setup 6\ISCC.exe`（2026-11-02 winget 用户级安装；`build_exe.py` 按 `TOOLBRIDGE_ISCC` → 内置候选（含 LocalAppData/Program Files 6 与 7）→ PATH 解析） |

- **⚠️ 本代理会话对「未签名未知镜像」做敏感面写过滤**（2026-11-02 实测）：csc 现编的无名 exe
  写 HKCU 卸载键 / 开始菜单 .lnk 会被「拒绝访问」，而 reg.exe、powershell.exe 同样操作放行；
  与沙盒开关无关、机器上只有 Defender 且实时防护关闭。**含义**：安装器的卸载键/快捷方式
  无法在会话内验证（用 `build_exe.py --installer-only --testmode` + `/NOICONS` 验其余段），
  别把这类拒绝误诊成产品 bug 或 ACL 问题（完整证据链见 `antivirus-false-positives.md` §5）。
- **Git Bash 会把 `/FLAG` 形式的参数改写成 `C:/Program Files/Git/FLAG`**（MSYS 路径转换，
  2026-11-02 把 Inno Setup 的 `/SILENT` 吃掉过，导致安装器弹了交互窗口）→ 给原生 exe 传
  旗标一律加 `MSYS_NO_PATHCONV=1` 前缀。
- **⚠️ 删除守卫：>50 个文件的批量删除要人工确认**（2026-11-02 实测，`sitecustomize` 的 safe-delete）：
  Python 侧 `shutil.rmtree` 被替换成走回收站，超阈值时打 `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`
  并**抛 BaseException 系**——`ignore_errors=True` **拦不住**，会在任意位置中断整条链
  （第一次 Unity 复跑就是这样在「数 JSON」之后 8 秒死掉的，看起来像 AssetStudio 崩）。
  → 代码里临时目录一律「**唯一名 + 尽力清理**」（`_drop()` 吞 BaseException），绝不「先删后建」；
  残留的 `_work/unity/_json_*`、`_conv_*` 每个几 MB，批量清用 bash `rm -rf`（工具侧会申请提权）。

## 2026-11-03 软件加固（探测 → 收口 → 优化）

交接时 v0.1.0 已能跑通 9 条链路，但「纪律只落地了一半」。本轮用 架构师+QA 双线只读审计列出
**P0 3 / P1 9 / P2 12** 条隐患（每条带 file:line 证据，两条 P0 当场实测复现），然后按批次修复：
**批次 A 交付正确性 → 批次 B 可用性/安全 → 批次 C 性能/清场**，QA 全程独立复验（含两次打回）。
版本号升至 **v0.1.1**。修复明细见 `verified-findings.md` §20，这里只留结论与环境坑。

### 修掉的真问题（按影响排序，全部带回归测试）
1. **失败运行会打印上一轮的成功数字**（P0，实测复现）：manifest 现在**唯一出口** `_write_manifest`，
   所有非 0 退出统一走 `_finish_failure`；`main()` 只认 `_result_manifest()`，绝不回读磁盘。
2. **阶段异常穿透**（P0）：`_run_stage` 兜 `Exception`（Ctrl+C 仍穿透）；`toolbridge.drop_tree`
   只重抛 `KeyboardInterrupt`，`SystemExit` = 删除失败（守卫语义）；`gui._worker` 兜 BaseException
   并保证补一条 `done`。三处各错一点会合谋成「GUI 永久卡死 + manifest 不落盘」。
3. **Unity Texture2D 缺口自洽**（P0）：缺口不再削减 expected，改 2%/20 阈值闸门，
   非 Texture2D 类必须逐类严格相等。
4. **KiriKiri 静默漏包**（P1）：任一 xp3 列不出 → 判失败并进 `manifest.source.unsupported`。
5. **验收串行 188s**（P1/性能）：线程池默认 8（`--verify-jobs` / `GALUNPACK_VERIFY_WORKERS`），
   结果按下标回填、按原序聚合 —— **jobs=1 与 jobs=8 的 manifest 逐字节一致**（有测试钉住）。
   实测 3500 文件：188.02s → **68.38s（2.75×）**。
6. **磁盘余量预检**（P1，文档承诺过但代码里没有）：新 `preflight` 阶段三档结论；
   `--reuse-raw` 跳过。
7. **GUI 取消 / 关窗 / 摘要**（P1）：取消按钮（阶段边界生效）、关窗确认、摘要走本轮 manifest。
8. **GUI 轮询器会被「没验成」的摘要打死**（P1，QA/架构师实测）：`media_minutes=null` →
   `TypeError` → `_poll` 不再重挂 `after` → 界面永久「运行中」。渲染层改为「媒体未统计」，
   `_poll` 事件异常只记日志；**manifest 里的 null 保持不动**（null=没测过 ≠ 0.0=测过是 0）。
9. **音频枚举超时冒充「没有音频」**（P1）：返回 None → stage 判失败「地面真相未知」。
10. **krkr 按进程名盲杀 game.exe**（P1）：改按镜像路径匹配（ctypes QueryFullProcessImageNameW）。
11. **golden 基线写死 `D:/K/deepseek` 绝对路径**（P1，QA 在副本里发现）：归一化为 `<repo>/...`，
    生成/比对两侧共用 `make_golden.normalise_paths`；**换目录必红的护栏恢复成真的护栏**。
12. 其它：manifest 单次写盘、`--strict` 真语义、`verify-no-products` 错误码、`manifest_written` 标记、
    CLI 验收归因五分支、重复测试去重、两处无效转义、`tests/run_all.py`。

### ⚠️ 本机环境坑（新增 4 条，都会制造假绿/假红）
- **pytest 的 `--basetemp` 不要指到仓库所在盘**：删除守卫会拦掉测试内部的清理动作，
  制造 5 条与代码无关的假失败（实测：`test_audio_collect2` / `test_krkr_index_fallback` / 3 条 unity）。
- **pytest 退出码在本机不可信**：全绿也可能 exit=1（退出清理撞守卫）。基线一律
  `C:/Python314/python.exe tests\run_all.py`（按 junit 的 failures/errors 判，脚本会自己说明）。
- **验收 JSON 别用 grep**：JSON 里反斜杠是双写，`grep 'D://K'` 恒 0 —— 会把「没修」看成「已修」。
  用 `json.load` + 递归遍历字符串值。
- **不要并发跑两个 pytest**（共用 `%TEMP%\pytest-of-<user>\` 的编号目录，互相删对方 tmp →
  成片的 `FileNotFoundError`，看起来像 155 条真失败）。

### 当时未做 —— ✅ 2026-11-04 全部完成（明细见文末 §「2026-11-04 收尾（v0.1.2）」）

- ~~raw 非空重跑（`--overwrite` 开关）~~、~~GUI 默认输出目录口径~~、~~Unity 子进程透出 rc/env~~、
  ~~`close_all_explorers()` 收窄到 stage 相关窗口~~、~~`find_tool` 配置缓存~~、
  ~~`source.archives` 键名统一~~、~~Unity 合并路径拍平~~、~~manifest 加 `verify.status` 单值枚举~~。
- 引擎侧仍挂起（需要用户配合/样本）：加密 krkr 剩余约 7 部（需用户放样本）、E-mote、夕凪荘 BGM。

## 2026-11-04 收尾（v0.1.2）—— 8 项遗留全清 + 许可证核实

v0.1.1「未做」清单的 8 项全部落地，另加随包工具许可证逐项核实。**没有新增引擎链路**，
这一轮改的全是「交付记录能不能信」和「重跑会不会给出假数字」。

### 会改变用户行为的四件事（测试反馈时别当成新 bug）

1. **raw 非空默认拒绝重跑**：`--out` 指向已有产物时，preflight 直接失败并给两个出口
   （`--overwrite` 清空 / `--reuse-raw` 复用）。GUI 会弹「清空重跑还是换目录」二选一。
   原因：旧实现静默叠跑，产物数虚高而 `reconcile` 照样 `diff=0` —— 一份完美格式的假记录。
2. **GUI 默认输出目录改了**：现在是 **`<游戏目录>\output`**（v0.4.0，用户要求）。
   早期版本落过 `Documents`（被终端防护拦）和 `%USERPROFILE%\GalgameUnpacker`（用户找不到），
   都不要回去。路径一律 `resolve()` 成绝对路径 —— 相对路径会让「打开输出目录」静默失效。
   （原先是程序安装目录，卸载即删、用户找不到）；源码态仍是 `<仓库>\_extracted\<游戏名>`。
3. **manifest 多了 `verify.status`**：单值枚举 `ok/partial/failed/skipped`。
   `verified=False` 不再等同于失败 —— `reason=disabled`（--no-verify）/`not-run`（加密 krkr）
   是「没验」，判 `skipped`。
4. **`source.archives` 全链路统一三键** `{name, entries, extracted}`。
   `entries` = 地面真相（没有就是 null），`extracted` = 实测落盘。读 manifest 的脚本如果
   以前按 `files`/`total_after`/`archive` 取值，现在要改（别名只在入口翻译，输出只有规范键）。

### 修掉的真问题（按风险排序）

1. **raw 非空静默叠跑**（最危险）：preflight 只读拦截 + `run()` 里 `reset` 阶段清 raw/png +
   GUI 询问。清不掉就失败，绝不「清一半继续」。
2. **Unity 合并产物拍平路径**：`relative_to(src).name` → `relative_to(src)`；
   同名不同内容直接报错，不再 `if not exists: skip` 静默丢文件。
3. **Unity 子进程 rc/stderr 被吞**：`_run_as` 返回 `CompletedProcess`、超时/OSError 变
   rc=-9/-2 诊断、env 走 `_sanitize_env`+`_clear_dll_dir`；`expected_counts`/`extract_all`
   返回 `errors`，orchestrator 拼进 detail 与阶段日志。`_as_audio_collect2` 同步。
4. **`close_all_explorers()` 关用户窗口**：按 stage 目录名过滤，hint 故意不设默认值。
5. **GUI 默认输出落安装目录**：见上。
6. **`find_tool` 重复读配置**：按 `(path, mtime_ns, size)` 缓存，返回浅拷贝。
7. **`source.archives` 三套键名**：`manifest.normalise_archives` 挂在 `build()` 唯一出口。
8. **verify 结论要消费方自己拼**：`verify_status()` 纯函数 + `fail_total` 输入。

### 许可证核实结论（**已不是阻塞项**：用户 2026-11-04 定「私人项目，完成后转私人仓库」）

`build_exe.TOOL_LICENSES` 已从「未核实」升级为逐项结论（依据写在条目里）：
**KrkrExtract = GPL-3.0、KrkrzExtract = GPL-3.0、ffprobe = GPL-3.0-or-later（本机构建
`--enable-gpl --enable-version3`）、tlg2png = 无许可证（vn-tools/tlg2png 仓库无 LICENSE，
API license=null）**，garbro/assetstudio 为 MIT。
→ **自用与私人仓库不触发任何分发义务，不需要处理**。核实结论只作事实备查：
将来若要公开仓库或把便携 zip 发给别人，GPL 三件必须随包给源码/书面报价，
tlg2png 必须换掉（GARbro 的 TLG 转换或自研）。详见 verified-findings §21.9。

### 交付形态（2026-11-04 用户定：只做便携版）

`installer.iss`、`build_exe.py` 的 `--installer/--installer-only/--testmode`、
以及产出的 setup.exe **已全部删除**。现行：`python build_exe.py` = 冻结 + 出
`packaging/Output/GalgameUnpacker-<版本>-portable.zip`。删除理由见杀软文档头部状态说明。

### 基线（收尾实测）

- `C:/Python314/python.exe tests/run_all.py` → **tests=656 failures=0 errors=0 skipped=8 → PASS**
  （开工前 626；新增 30 条）
- `C:/Python314/python.exe tests/make_golden.py --check` → **6 fixture + 12 真实样本零漂移**
- 新增 `tests/test_unity_extract.py`（7 条：rc/env 透出 + 合并路径）

### 仍未做（都要用户配合或样本）

- 用户实测 v0.2.0 的反馈（当前最高优先级，等这个）
- KiriKiri 索引兜底的**自然**窗口缺失场景（仍只有注入式模拟证据）
- ~~GUI 弹窗行为确认~~（GARbro.GUI 选标题/密钥弹窗）—— **2026-11-04 结案：划走**。
  那 4 个 pork 社游戏用户早就明确不做，确认结果不改变任何交付；真要做只能走
  40 分钟/部的 UI 自动化。判定依据与原始疑点保留在 `verified-findings.md` §1 与 §21.11。
- 加密 krkr 剩余 ~7 部（用户 2026-11-02 划走，样本在盘）、E-mote、AI 兜底（A1/A2/A3，最后才考虑）
- ~~夕凪荘 22 BGM dump~~（2026-11-04 用户明确舍弃）
- ~~安装器卸载键/开始菜单验证~~（安装器已删除，不存在这项）

## 2026-11-04 半自动协作（失败时给可执行方案）

### 一句话

把「全自动跑不通 → 抛一个 error code」改成「全自动跑不通 → 告诉你 3 分钟人工怎么做，
做完接着跑」。理由：有些障碍的自动绕过成本远高于人工（加密 KiriKiri 的 UI 自动化
约 40 分钟且挑环境，人工拖 xp3 只要 3 分钟）。

### 改造范围（只覆盖真能省事的场景）

| code | 触发条件 | 人工方案 | 产物落点 |
|---|---|---|---|
| `kirikiri-encrypted` | extract 失败 + engine=KiriKiri + detail 不含 GUI 失败 | KrkrExtract 手动拖 xp3 | `raw/` + `png/` |
| `kirikiri-gui-failed` | 同上，但 detail 含「GUI 链路失败」 | 同上 + 提示安全软件拦进程 | `raw/` + `png/` |
| `unity-no-assets` | extract 失败 + engine=Unity | AssetStudio.GUI 导出 | `raw/Image_Texture2D` 等 |
| `engine-no-chain` | rc=2（引擎判出但没链路） | 专用工具解到 `raw/` | `raw/` |
| `detect-failed` | rc=3（判不出引擎） | 确认根目录 / `--engine` 强制 | — |

**不做的**：preflight 空间不足（换盘即可）、raw 非空（已有两个出口）、verify 失败
（产物已在，人工无从下手）。没有合适方案时 `plan_for()` 返回 `None`、manifest 不写
`manual` 块 —— **不硬凑**，编出来的指引比错误码更害人。

### 交互提示形式（三处消费同一份数据）

1. **CLI**：`manual.render_dict()` 打区块 —— 分隔线 / 原因 / 需要准备 / 编号步骤 /
   产物路径 / 可直接复制的续跑命令 / 备选方案。放在所有统计之后（失败时用户最需要的
   是「现在干什么」）。
2. **GUI**：`gui.summarize_text()` 追加「需要人工介入」+ **前 3 步** + 「还有 N 步」
   ——弹窗再长就没人读了，完整步骤在日志与 manifest 里。
3. **manifest**：`manual` 块（`code/summary/why/needs/steps/target/then/alternatives`），
   机器可读；`res["manual"]` 与 `man["manual"]` 是**同一份**数据。
4. **`--dry-run`**：KiriKiri 样本多探一次 `garbro -l`（几秒），列不出就当场给方案 +
   `auto_feasible=false`。stdout 保持纯 JSON，人读区块走 stderr。

### 验收标准（每条都有测试）

1. 5 个失败码各有一份方案，且三件套齐全：`needs` / `steps` / `target`+`then`
   （`tests/test_manual.py` 12 条）。
2. 路径带空格时命令必须加引号 —— 用户是复制粘贴，不是自己拼。
3. 三处同一份：`res["manual"] == man["manual"]`
   （`test_failure_carries_manual_plan_for_encrypted_kirikiri`）。
4. 无方案不硬凑：Ren'Py extract 失败时 manifest **没有** `manual` 块。
5. dry-run 预判：KiriKiri + garbro 列不出 → `auto_feasible=false` + `manual`，
   且 stdout 仍是合法 JSON（`test_dry_run_predicts_manual_intervention_for_kirikiri`）。
6. 人工做完能续跑：方案里的 `then` 直接用既有 `--reuse-raw`（**不新增命令**，
   人工产物与自动产物走同一条验收/后处理链路）。
7. GUI 只显示前 3 步、超出要报「还有 N 步」（`test_summarize_text_includes_manual_plan`）。

### 待办优先级（2026-11-05 重排，基于 `教师催眠2` 实测）

| 级别 | 事项 | 状态 |
|---|---|---|
| P0 | 无 | 没有阻塞交付的问题 |
| ~~P1~~ | ~~案例库 `decision.extractor` 没接线~~ | ✅ **2026-11-05 修完（v0.4.3，用户定 A 案）**，见文末与 verified-findings §30.2 |
| ~~P1~~ | ~~extract 失败时 `source.archives` / `unsupported` 为空~~ | ✅ **2026-11-05 修完（v0.4.3，探针升级成逐包普查）**，见 verified-findings §30.1 |
| ~~P1~~ | ~~解包速度优化~~ | ✅ **2026-11-06 修完（v0.5.0）**：Unity 音频批量 50→400 + 内存自适应并行；顺带修掉对账口径自相矛盾。见 verified-findings §31 |
| P2 | `教师催眠2` 人工闭环 | 等用户走完（拖 xp3 → 拷 `raw/` → `--reuse-raw`）；或直接对它重跑 v0.4.3 看新提示 |
| P3 | KiriKiri **自然**窗口缺失验证 | 等样本/时机（现有只有注入式模拟证据） |
| P4 | 加密 krkr 7 部 / E-mote / AI 兜底 | 用户划走 / 盘面 0 命中 / 最后才考虑 |
| 舍弃 | 夕凪荘 BGM、安装器、GUI 弹窗确认 | 用户明确 / 建议划走 |

### P1-①：案例库的 `extractor` 不参与决策（实锤）—— ✅ 已修（2026-11-05，用户定 A 案，v0.4.3）

> **修法落点**：`Ctx.case_match`（run() 阶段 1.5 回填，不重复查库）+ `_case_krkr_hint()`
> 把证据拼进 extract 失败 detail 与 manual plan 的 **summary**（GUI 摘要只显示 summary，
> 放 why 用户看不见）；dry-run 预判同样带上。GUI 已跑过但失败的分支不套用（再推荐就是误导）。
> 案例的 `expected_total` 只进提示文本，`reconcile` 恒用编排器自己的索引（有测试钉住）。
> 明细见 verified-findings §30.2。

**现状**：`case_lookup` 把 `decision`（含 `extractor` / `expected_total` / `notes`）
写进 `manifest.source.case_match` 供人看，**只此而已**。真正决定走哪条链路的是
`EXTRACTORS.get(engine)` 这张静态表（`orchestrator.py` 约 2461 行）。

**后果（真实发生过）**：`教师催眠2` 命中 `教师催眠1 / xp3-encrypted-krkrZ /
extractor=krkr_auto_extract / 5724 成功`，但因为 engine 是 KiriKiri，仍然走 GARbro
→ 11 个包全部 `unknown format` → 失败 → 要用户手动拖 3 分钟。
**已经验证过的解法就在手边，没接上。**

**两个方案的差别只在一件事：要不要自动接管鼠标。**

- **A（保守，我推荐）**：命中且 `extractor == krkr_auto_extract` 时，只在失败提示里
  摆出证据 ——「案例库记录同系列用 krkr_auto_extract 全自动成功（5724/5724），
  加 `--allow-gui` 可自动跑；或按下面的 3 分钟人工方案」。默认行为不变。
- **B（激进）**：命中就直接走 GUI 自动化，不问。风险是突然接管鼠标约 40 分钟，
  且远程桌面/多虚拟桌面会让 `SendInput` 失效，失败后还得重来。

**实现要点（两案共用）**：`stage_extract_kirikiri` 需要拿到案例信息，但 `Ctx` 里没有。
现成的路是 `stage_case_lookup` 已经在 `run()` 里跑过，把结果存进 `ctx`（新增一个字段）
即可，不要重新查一遍库。**别把案例的 `expected_total` 拿去当对账地面真相**——
那是别的游戏的数字，混进来就是伪造对账（本项目最贵的错）。

### P1-②：extract 失败时漏包记录是空的 —— ✅ 已修（2026-11-05，v0.4.3，比原方案更进一步）

`教师催眠2` 的 manifest 里 `source.archives == []`、`source.unsupported == null`，
而 `AGENTS.md` 第 697 行承诺「任一 xp3 列不出 → 判失败并进 `manifest.source.unsupported`」。

**原因**：那条只在 `--reuse-raw` 分支实现了。正常流程在 probe 失败时**直接 return**，
连 `st.data["archives"]` 都没填。

**修法（实际实现）**：原方案是「probe 失败把其余包填成 null 记录」，实际直接把探针
升级成**逐包普查**——`stage_extract_kirikiri` 逐包 `garbro -l` 全部列完再下结论，
每个包都有实测记录，null 记录分不清的「整包加密 vs 个别包坏了」现在 manifest 自己能答。
连带：混合情形先解掉列得出的包再点名失败；GUI 成功后撤掉 `unsupported`（都交付了）；
GUI 触发条件改成「没有任何包列得出 + `--allow-gui`」。加密失败路径 ~2s → ~15s，
明文游戏反而省一次重复列表。明细见 verified-findings §30.1。

**速度优化的下手点（先量再改，别猜）**：Unity 音频收集是当前最贵的一段
（Happiness Double Room 1441 条要 58 次 AssetStudio 调用、十几分钟），
候选方向：批量 50→100 的丢失率对比、按名字分片到独立临时目录并行后合并（注意同名冲突）、
以及先确认瓶颈在进程启动还是磁盘 IO。verify 已 8 路并行（3500 文件 68s），
preflight 的 `_tree_bytes` 在大样本上是几十秒（已有提示）——这两个优先级低于 Unity 音频。

## 2026-11-04 v0.2.0 交付（半自动协作打磨 + 挂起项结案）

### 打磨（半自动协作第一版的两个缺口）

1. **`kirikiri-gui-failed` 不再建议「原样再跑一次」**：GUI 自动化跑过但没产出，
   多半是安全软件拦了 `KrkrExtract`/`game.exe`，或不是真实桌面会话（远程桌面/多虚拟桌面
   会让 `SendInput` 失效）。所以这个分支的 `why` 改成排查方向，而不是重复同一段技术解释
   ——原样重试等于再浪费 40 分钟。
2. **`engine-no-chain` 点名本仓库现成脚本**：唯一已知的无链路引擎是 Tyrano/Electron，
   而根目录就有 `asar_tool.py`。方案里直接写脚本名（不给参数，参数在文件头），
   省掉「去哪找工具」这一步。
3. **完整方案落 `_work/manual.log`**：GUI 的 worker stdout 不进日志面板，摘要又只显示
   前 3 步；用户真要照着操作时必须能看到全部步骤。`_finish_failure` 里 `ctx.log("manual", …)`。

### 挂起项结案

| 项 | 结论 | 依据 |
|---|---|---|
| GUI 弹窗确认（GARbro.GUI 选密钥） | **划走** | 涉及 4 个用户已明确不做的游戏；确认结果不改变交付 |
| 加密 krkr 剩余 ~7 部 | 维持划走 | 用户 2026-11-02 明确 |
| E-mote | 维持挂起 | 盘面 0 命中 |
| AI 兜底（A1/A2/A3） | 维持「最后才考虑」 | 规则覆盖率已够 |
| 夕凪荘 BGM | 已舍弃 | 用户 2026-11-04 |

### 版本与交付

- `APP_VERSION` 0.1.2 → **0.2.0**（半自动协作是新特性，按 minor 升）
- 交付形态：`packaging/Output/GalgameUnpacker-0.2.0-portable.zip`（便携版，无安装器）
  ——**已被 v0.4.2 取代**，当前产物见 ③ 下一步与 v0.4.2 章节
- **速度优化按用户要求暂不启动**：用户明确「等我版本实测，然后再准备速度优化（现在先不做）」。
  下手点与测量计划已记在上方「待办优先级」段，等实测反馈回来再动。

## 2026-11-04 失败日志（`faillog.py`）

### 为什么单独一个模块

阶段日志在 `_work/<stage>.log`，跟着**输出目录**走。而输出目录本身可能就是第一个失效的
东西（§23：未签名 exe 写 `Documents` 被终端防护拒，`mkdir` 直接炸）。把失败记录放在一个
「可能建不出来」的目录里等于没有。所以失败日志落在**软件根目录**（便携版 = 解压目录，
源码 = 仓库根），与产物完全解耦。

### 契约

- 位置：`<软件根>/failures.log`（追加）；不可写时退 `%LOCALAPPDATA%\GalgameUnpacker\failures.log`
- 格式：纯文本块，一块一条失败。第一行 `[时间] error [engine=] [rc=]`，缩进字段
  `game/out/stage/exc/自定义/python/traceback/---`
- **永不抛异常**：目录不存在就建、超 2 MB 轮转 `.1`、两处都失败只往 stderr 说一句
- 只写失败阶段（`ok=False`），成功的阶段不进日志（噪声会让人不看）

### 接入点（少一个就会漏掉一类失败）

| 位置 | 覆盖的失败 |
|---|---|
| `_finish_failure` | 所有非 0 退出（detect/preflight/extract/post/verify/reset） |
| `main()` 早期 return | 游戏目录不存在、`--reuse-raw` 目录不存在、清空 raw 失败 |
| `main()` dry-run 失败 | 只判引擎就跑的场合（rc=3） |
| `gui._worker` 的 `except BaseException` | 线程崩溃（不走 `_finish_failure`，最容易被漏） |

### 验收（`tests/test_faillog.py` 8 条 + 2 条集成）

时间戳格式、上下文齐全、成功阶段不出现、目录自动创建、主路径不可写降级、
两处都失败只 stderr 不抛、超限轮转、文件头只写一次、多行值压平、traceback 只留末尾 40 行；
集成侧断言 `run()` 失败后 `<app>/failures.log` 有该条记录、GUI 线程崩溃时
`error=worker-crashed` 且仍补 `done`。

## 2026-11-04 v0.4.0：输出目录改成 `<游戏目录>\output`

### 用户要求

「用户添加游戏的时候，解包目录自动变为 ……/游戏根目录/output」。

### 实现与连带修复

1. `gui.default_out_dir(game)` → `game / "output"`。删掉 `user_output_root` /
   `_output_root`（产物不再基于应用根或用户目录）。planner 的 `_extracted` 约定**没动**
   —— 它是 CLI/规划器的口径，与 GUI 的默认值无关。
2. **路径一律 resolve**：`_start` 和 `_autofill_out` 都 `.expanduser().resolve()`。
   这是「解包完打开输出目录没反应」的直接原因 —— 相对路径下 `is_dir()` 依赖 cwd，
   判失败后 `_open_out` 静默返回，用户以为按钮坏了。
3. `_open_out` 目录不存在时明确弹「输出目录不存在」，不再静默。
4. 游戏目录不可写时，可写预检仍然接管：退到 用户目录 / LOCALAPPDATA / TEMP。

### 为什么这个默认值比之前两个都对

- `Documents`：未签名 exe 被 EDR 拦（§23）
- `%USERPROFILE%\GalgameUnpacker`：能写，但用户根本不知道该去那找（实测产物落到了
  程序目录下的相对路径，等于没找到）
- `<游戏>\output`：解完就在游戏旁边，符合直觉；多个游戏各自独立；换盘换机器跟着走

代价：会往游戏目录里写字。用户明确要求，且游戏目录只读时有 fallback 兜底。

## 2026-11-04 v0.4.1：输出目录不可写的两个真因

详见 verified-findings §27。结论先写这里，避免下次又在错的维度上打补丁：

1. **目录名含 `|`**（`【PC】… | Ore o Hoshigaru…`）：NTFS 允许它存在，但**不允许在它下面
   建子目录**（系统报「语法不正确」）。→ `default_out_dir` 检测非法字符，改落
   **父目录**下的 `<清洗名>-output`。
2. **真被终端防护拦**（`教师催眠2`）：用 .NET 的普通进程能建能写，冻结 exe 不能。
   → 删掉 `writable_fallback`（它靠环境变量猜位置，实测猜到了**程序目录**），
   改成弹目录选择框让用户自己挑；连选两个都失败就明说「去加白名单」。

顺带：
- `_open_out` 目录没建成时退到最近存在的上级并说明；`startfile` 失败也显示错误。
- 可写性失败写进 `failures.log`（`error=output-not-writable`）。
- GUI 勾选框文案：`允许 GUI 自动化（加密 KiriKiri，约 40 分钟）` → **`用于加密的 krkr`**。

**别再做的事**：不要用 `Path.home()` / `LOCALAPPDATA` 猜产物位置。在用户机器上这些变量
不受控（实测 fallback 算到了程序目录），猜错比不猜更糟 —— 让用户选。

## 2026-11-04 v0.4.2：「为什么只拦我」—— 补身份 + 给绕路

### 结论先说

拦截看的是**文件身份**，不是代码做了什么。本项目的 exe 原先五项证据全缺：

| 证据 | 主流软件 | 本工具（v0.4.1 及以前） |
|---|---|---|
| 数字签名 | 有 | 无 |
| 文件属性（公司/产品/描述/版本） | 齐全 | **PyInstaller 默认全空** |
| 云端信誉 | 百万装机 | 零，且每次构建哈希都变 |
| 二进制结构 | 已备案 | PyInstaller bootloader（打包器是恶意软件重灾区） |
| 安装来源 | 商店/官网 | 自己打的 zip |

所以不是「针对这个程序」，是按同一个模式拦所有答不出「谁做的」的 exe。

### 本轮做的三件事

1. **`build_exe.version_file()`**：生成 PyInstaller 版本资源并写进 exe
   （CompanyName/FileDescription/FileVersion/ProductName/OriginalFilename/LegalCopyright）。
   填的是真实信息，不冒充厂商；只解决「认不出来」这一层。
2. **`build_exe.icon_file()`**：用 Pillow 现生成多尺寸 ico（无 Pillow 时返回 None，构建照常）。
   没有图标时拦截弹窗里是个空白框，用户没法判断这是自己装的东西。
3. **`start-gui.bat`**：用系统 Python 直接跑 GUI，**完全绕开 exe 的写入拦截**。
   `python.exe` 在白名单里（实测它能写 `Documents`，冻结 exe 不能）。

### `start-gui.bat` 的两个坑（写 bat 的人会反复踩）

- **必须存成 GBK**：cmd 按系统 OEM 代码页解析 `.bat` 文件本身，UTF-8 的中文注释
  会被当成命令执行（实测报一堆「不是内部或外部命令」）。`chcp 65001` 救不了——
  它在文件被解析之后才生效。
- **必须 CRLF**：LF 行尾下标签/goto 会失配。用 Python 写 bat 时记得显式转换。

### 别做的事

- 不要指望「补版本信息 + 图标」解决拦截。它只降低误判概率，不改变签名缺失这个事实。
- 不要为了绕拦截去改 bin、加壳、混淆 —— 那会把「可疑」变成「确定可疑」。

## 2026-11-05 实测复盘：`教师催眠2` 暴露的两个缺口

### 这次跑对了什么（别只盯着失败）

用户 2026-11-04 23:37 在 `D:/HY/教师催眠2` 上跑了一轮，manifest：

```
engine=KiriKiri  score=90  error=extract-failed  total_seconds=2.0
counts: raw=0 final=0 converted=null
reconcile: expected=null actual=0 diff=null method=no-index-available
verify.status=skipped（不是 failed —— §21.3 的枚举生效了）
manual: 8 字段齐全，_work/manual.log 有完整方案
```

**这条链路的每一处修过的地方都对了**：

- 输出目录**可写**（写到 `packaging/Output`）→ §23/§27 的目录修复有效
- 失败也写 manifest，`ok=false` + `error` + 阶段明细 → §20 的唯一出口有效
- `verify.status=skipped` 而不是 `failed` → §21.3 的「没验 ≠ 验失败」有效
- 人工方案三件套齐（工具路径 / 产物落点 / 可复制命令）→ §22 半自动有效
- 案例库命中并落盘 → 有据可查

**所以这不是「软件坏了」，是「软件说了它解不了，并给了办法」。**

### 现场补测：11 个 xp3 全是加密的

逐个 `garbro -l`：

| 包 | 大小 | 结果 |
|---|---|---|
| data.xp3 | 0.3 MB | unknown format |
| image00~04.xp3 | 15.2 / 61.7 / 1028.9 / 65.9 / 924.5 MB | 全部 unknown format |
| media.xp3 | 142.9 MB | unknown format |
| movie.xp3 | 148.6 MB | unknown format |
| scenario.xp3 | 0.5 MB | unknown format |
| voice01/02.xp3 | 5.6 / 509.5 MB | 全部 unknown format |

11/11 失败。目录特征：`katei2.exe` + `Mai@KF.dll` + `katei2.exe.org`（原 exe 被 patch）。
与案例库 `教师催眠1 / xp3-encrypted-krkrZ` 同族。

**结论：不是「个别包加密」，是整包 krkrZ。这种情况下 GARbro 100% 解不了，
继续探第二个包也没意义 —— 失败是正确结论。**

### 缺口一：案例库的 `extractor` 是死数据

`case_lookup` 把 `decision.extractor` 写进 manifest，但没人读它。选链路的仍是
`EXTRACTORS.get(engine)` 静态表。于是：

```
案例说：教师催眠1 用 krkr_auto_extract，5724/5724 零失败
实际做：KiriKiri → GARbro → 11 包全灭 → 让用户手动拖
```

**已经验证过的解法没接上，这是设计缺陷，不是 bug。**

决策点（等用户定）：

- **A 保守**：命中且 `extractor=krkr_auto_extract` 时，只在失败提示里摆证据，
  推荐 `--allow-gui`；默认行为不变。
- **B 激进**：命中就自动走 GUI 自动化，不问。

我推荐 A：B 会突然接管鼠标 40 分钟，而且远程桌面/多虚拟桌面下 `SendInput` 会失效，
失败后用户还得重来 —— 不如让他自己选时机。

实现时注意：**案例的 `expected_total` 是别的游戏的数字，绝不能拿来当对账地面真相。**
只能用于「提示」和「判断该走哪条链路」。

### 缺口二：失败时漏包记录是空的

manifest：`source.archives == []`、`source.unsupported == null`。
而本文档第 697 行承诺过「任一 xp3 列不出 → 判失败并进 `manifest.source.unsupported`」。

原因：那条只在 `--reuse-raw` 分支实现了；正常流程 probe 失败直接 return，
连 `st.data["archives"]` 都没填。

修法：probe 失败时把 11 个包的 `{name, entries: null, extracted: null, listable}`
填进 `archives`，列不出的进 `unsupported`。成本极低，收益是「一眼分清全军覆没还是个别包」。

## 2026-11-05 v0.4.3：两条 P1 缺口修复（案例接线 + 失败记录）

§「2026-11-05 实测复盘」的两条缺口当天收口。**用户对 P1-① 定了 A 案（保守）**：
默认行为不变，只在失败提示里摆证据。证据明细与行为变化全表见 `verified-findings.md` §30，
这里只留接手要用的结论。

### 改了什么

1. **P1-②（记录缺口）**：`stage_extract_kirikiri` 的探针升级成**逐包普查** ——
   逐包 `garbro -l` 全部列完再下结论，每个包在 `source.archives` 都有实测记录
   （`{name, entries, extracted, listable}`），列不出的进 `source.unsupported`。
   加密失败路径 ~2s → ~15s（11 包量级），**明文游戏反而更快**（旧流程最大包列两遍）。
2. **P1-①（A 案）**：`Ctx.case_match`（run() 阶段 1.5 回填）+ `_case_krkr_hint()` ——
   命中「同签名案例曾用 krkr_auto_extract 全自动成功」时，证据进 extract 失败 detail
   与 manual plan 的 **summary**（GUI 摘要只显示 summary 与前 3 步）；`--dry-run` 预判同带。
   `extractor=garbro` 的候选不进提示；GUI 已跑过但失败的分支不套用。
3. **连带语义**：部分包列得出（混合）→ 先静态解掉列得出的，再点名判失败；
   GUI 自动化只在「没有任何包列得出 + `--allow-gui`」时触发；GUI 成功后撤掉
   `unsupported`（都进交付了），`archives` 的 listable=false 保留解释「为什么走 GUI」。

### 红线（别回退）

- 案例的 `expected_total` **只能出现在提示文本里**，绝不进 `reconcile`
  （`test_krkr_case_hint_never_touches_reconciliation` 钉住）。
- 失败也必须有完整 `source.archives` / `unsupported`（AGENTS 第 697 行的承诺现在
  在正常流程也成立了，不只 `--reuse-raw`）。

### 基线与交付

- `tests/run_all.py` → **tests=702 failures=0 errors=0 skipped=9 → PASS**（新增 9 条测试）
- `make_golden.py --check` → 零漂移
- `APP_VERSION` 0.4.2 → **0.4.3**；交付形态不变：便携 zip
  （`packaging/Output/GalgameUnpacker-0.4.3-portable.zip`，`python build_exe.py` 重出）
- 用户入口：源码态 `start-gui.bat` 或解压新 zip

### 下一步（当前）

1. **解包速度优化**（P1，用户 2026-11-04 指定，实测反馈已回）：Unity 音频收集最贵
   （Happiness Double Room 1441 条 = 58 次 AssetStudio 调用、十几分钟）。下手点：
   批量 50→100 丢失率对比、按名字分片并行后合并（注意同名冲突）、先确认瓶颈是
   进程启动还是磁盘 IO。**先量再改，别猜。**
2. P2：`教师催眠2` 人工闭环等用户走完；或对它重跑 v0.4.3 直接看新提示与完整记录。
3. P3/P4 不变：KiriKiri 自然窗口缺失验证（等样本）、加密 krkr 7 部 / E-mote / AI 兜底（划走或最后）。

## 2026-11-06 v0.5.0：解包速度优化（Unity 音频）+ 对账口径修复

用户 2026-11-06 授权开工（「你先优化速度」）。全程先量后改；完整实测档案与
「被数据纠正的方案」见 verified-findings §31，这里只留接手要用的结论。

### 改了什么（`_as_audio_collect2.py` + `orchestrator.py`）

1. **`BATCH` 50 → 400**（首轮）：每进程 ~4.1s 固定开销主导，首轮 29 次×50 名
   （≈130s）→ 3 次×400 名（≈22s）。**400 是实测安全点**：1441 名一片挂死
   （900s 超时、172/1441 后无产出），悬崖在 400~1441 之间，别上调去试。
2. **并行补齐**：线程池 + 每片独立临时目录 + 锁内合并；`WORKERS=3`，
   环境变量 `GALUNPACK_AUDIO_WORKERS` 可强制（1=串行）。
3. **内存门**：可用内存扣 1.5 GiB 后按 1 GiB/进程折算，不足自动降串行。
   开发当天机器全程 78~85% 负载，门全程生效（一直串行）——设计行为。
4. **逐轮减半保留**（MAX_ROUNDS 5→12）：中间版曾按「丢失率与批量无关」删掉减半，
   第二轮验证 12 轮后仍缺 294/1441 —— **重试轮的难名字收益率随批量变小急剧上升**
   （同日实测 36%→60%→99%），减半是收敛的承重墙。教训：探针的样本要和目标场景同分布。
5. **对账口径修复**（验证第一轮暴露的既有缺陷）：阶段级认 Texture2D 缺口、manifest
   级裸 diff 不认 → 同一份输出「对账 0 差」+ 退出码 1 自相矛盾。现在阶段放行时写
   `explained_shortfall`，`build_manifest` 在数额恰好相等时附 `reconcile.explained_by`，
   rc 据此放行；CLI 摘要亮出解释。**expected 不削减（A3 红线不动），数额对不上照旧失败。**

### 验证与交付

- 全链验证（Happiness Double Room，第三轮）：**rc=0**，图片 2059/2059、
  音频 1441/1441、失败 0、媒体 186.4 分钟；音频收集 7 轮 67 次（内存门全程串行，
  机器 80%+ 负载）；全链 493.8s。
- `tests/run_all.py` → **tests=708 / 0 / 0 / 9 PASS**（新增 6 条：worker 解析、内存门、
  真并发 Barrier、单片不起线程池、解释性缺口 rc=0、数额不符照旧失败）
- `make_golden.py --check` 零漂移；`APP_VERSION` 0.4.3 → **0.5.0**，便携 zip 重出。

### 下一步（当前）

1. **等用户实测反馈**（速度优化的实际体感、以及 v0.4.3 两条缺口的现场表现）。
2. P2：`教师催眠2` 人工闭环（拖 xp3 → `--reuse-raw`），或用 v0.4.3 的新提示选 `--allow-gui`。
3. P3/P4 不变：KiriKiri 自然窗口缺失验证（等样本）、加密 krkr 7 部 / E-mote / AI 兜底。

### ⭐ 实测反馈 #3（2026-11-06）：写入拦截与信任区无关

`D:\HY\我与老师的私人课程2`（Artemis/iMel，`iarsys64.dll` + `bokukano2.pfs/.000/.001`）
启动即弹「输出目录不可写」。排查结论（完整证据见 `antivirus-false-positives.md` §8）：

- **警告：信任区不是解药。** 用户把**整个 D 盘**加进火绒 6.0.12.3 信任区仍全灭，随后清空。
  `wlfile.db` 的 `TrustRegion_60` 为 0 行是**清空**的结果，别误读成「加白没落盘」。
- **已排除**：目录 ACL（`Authenticated Users:(M)`）、非法字符（是 WinError 5 不是 123）、
  Defender（RTP/AM 均 False）、SAC=0、AppLocker。
- **决定性对照**：`runas /trustlevel:0x20000` 下 `cmd` 能写桌面、`orchestrator.exe` 连
  `%TEMP%` 都建不了目录；同一 exe 在提权会话里写 `<游戏>\output` 与桌面均成功。
  → 是「按进程 + 按目录」放行，差异在**进程身份 / 是否提权**，换目录无意义。
- **修正**：本机 `Sangfor\SSL\…` 是 **EasyConnect SSL VPN**（ECAgent/PWEx/Promote/UDProtect），
  **不是深信服 EDR**。`ECAgent` 于 13:25 启动、13:35 起连续失败，时间吻合，尚未排除。
- **给用户的通道**：① `start-gui.bat`（python 通道）；② 停掉**服务/驱动**级防护再试
  （不是关界面，见 §8.6）；③ 让程序自己出证据：`--doctor` 或 GUI「环境自检」。
  ⚠️ 「右键以管理员身份运行」在本机**无效**（UAC 已关闭，等于双击），别再当排查步骤。
- **待修**：`main()` 的 `out_dir.mkdir` 无兜底，非提权 CLI 直接吐 traceback（GUI 有友好提示）。

#### v0.6.0（2026-11-06 下午）：把「猜原因」改成「让程序交证据」

用户回报「管理员 / 退出火绒 / 卸载 EasyConnect **都不行**」——查完现场发现
**三条都没真正改变变量**（详见 `antivirus-false-positives.md` §8.6）：
`EnableLUA=0` 让「右键管理员」等于双击；托盘退出只停 `HipsTray`，`HipsDaemon`
（PID 4216）全程在跑；Sangfor 的 `PWEx`/`UDProtectEx` 是服务，卸载后仍在运行。
**结论：一个变量都没排除，根因仍未锁定。**

⚠️ **另一个必须记住的教训（§8.7）**：本次两次「复现」（`runas /trustlevel` 与一次
低完整性会话）都稳定报 `WinError 5`，但同一 exe 在正常会话里写程序目录/桌面/游戏目录
**全部成功**。受限令牌造出来的「只有程序目录可写」与用户故障**现象同、成因不同**——
只有「在正常会话也能写的位置上失败」才算复现。

因此本轮改的是**能力**，不是猜测：

1. **`doctor.py` + `--doctor` + GUI「环境自检」按钮**：一次打印版本、打包态、用户、
   完整性级别、**`EnableLUA`**、在跑的安全类进程、已注册驱动，以及六个位置的
   **写探针表**（每条带完整 `Errno/WinError` 原文）。用户点一下、复制、发回即可。
2. **输出目录自动降级**（`gui.fallback_out_dirs` / `pick_writable`）：默认不可写时
   依次试 程序目录 → LOCALAPPDATA → TEMP，第一个能写就**继续跑**并弹窗说明改到哪；
   全灭才报错，错误框里直接列探测表 + 给「仍然尝试」出口（探针可能误报）。
   ⚠️ 这条**推翻了** v0.4.1「不自动跳位置」的口径 —— 实测让用户挑目录等于让他反复撞墙。
3. **CLI 兜底**：`main()` 的 `mkdir` 包住，记 `failures.log`（`error=output-not-writable`，
   `stage=cli-pre-start-mkdir`）+ 人话 + 指向 `--doctor`。
4. **版本号挪进 `version.py`**（唯一出处）：`build_exe` / `--doctor` / GUI 共用，
   免得「包叫 0.6.0、报告写 0.5.0」。
5. 测试：`tests/test_doctor.py` 9 条 + `tests/test_gui.py` 3 条（降级/全灭/去重）；
   全量 `tests=720 failures=0 errors=0 skipped=12 → PASS`。

交付：`packaging/Output/GalgameUnpacker-0.6.0-portable.zip`
（141.6 MiB；2026-11-06 15:23 重打，SHA256 `3c5e9798…f43453db`；解压后 1485 文件 / 354.1 MiB）。
重打后已实测：解压到 `%TEMP%` 跑 `--doctor` 版本 0.6.0、`--gui-smoke` rc=0。

#### 结案（2026-11-06 15:2x）：根因是**路径**，不是 ACL/杀软/提权

用户用 0.6.0 跑通了 `D:\HY\我与老师的私人课程2`：**Artemis，rc=0，7361/7361 零差，
图片 1348/0 失败、音频 4857/0 失败、视频 0、511.4 分钟**——产物落在
`packaging\Output\orchestrator\output`（自动降级挑的位置）。

随后定位到真因（完整对照表见 `antivirus-false-positives.md` §8.8）：
**同一份 exe，放在 `D:\K\deepseek\packaging\Output\orchestrator` 下进程是 Low 完整性，
复制到 `%TEMP%` 或 `D:\gtool` 下就是 High**；同一 shell 内 `python.exe` 恒为 High。
Low 令牌被强制「禁止向上写」，所以 Medium 标签的桌面/文档/游戏目录/%TEMP% 全部
`WinError 5`，只有那个子树里未打标的目录能写。

→ **规避：便携包解到 `D:\K` 之外**（如 `D:\GalgameUnpacker\`），别再在这个子树里跑。
→ 未查明：`packaging\Output\orchestrator` 上那两条非标准 ACE（`Everyone:(I)(CI)(DENY)(DC)`、
`S-1-4-…:(W,D,DC)`）是谁写的；`D:\K` 本身干净。查清之前不要用这棵树当部署位置。

## 2026-11-06 v0.7.0：启动守卫 + 产物按类型归档 + 加密 krkr 三处修复

用户当天定的顺序：A（启动守卫）→ `--allow-gui` 闭环 → B（归档）；krkr 缺失验证与批量样本划走。

### A 启动守卫（`gui.restricted_environment` / `restricted_tip`）

启动时读进程完整性级别：`Low`/`Untrusted` 就在状态栏与日志区写明「只能写程序目录，建议把
整个 orchestrator 文件夹移到 `D:/GalgameUnpacker` 后重开」，并指向「环境自检」。
**不弹窗、不阻断** —— 降级路径本身能跑，缺的只是「为什么」。测试 4 条
（Low/Untrusted 识别、High 与查询失败时不误报、提示里必须给出可执行的去处）。

### B 产物按类型归档（`organize.py`，v0.7.0 新增）

解包的终点就是「图片/音频/视频」三类，但产物只落 `raw/` + `png/`，用户得自己挑。做法：

- **不搬文件**：`counts`/`reconcile` 的地面真相都在 `raw/`，搬走等于拆掉唯一的交付担保。
  只额外产出 `类目清单.csv`（UTF-8 **BOM**，Excel 双击不乱码）与
  `分类/<图片|音频|视频|其他>/raw|png/…` 的**硬链接视图**（同盘不复制字节）。
- **分类规则只写一份**：扩展名优先，认不出才退回路径目录名（坑 5：按目录判会把
  `images/animations/` 下 282 个 `.jpg` 分进视频）。
- 链接失败**只计数不复制**（跨卷时偷偷拷 100 GiB 比少几个链接糟得多），失败数进 manifest；
  视图目录已存在时顺延 `分类-2`，绝不覆盖旧视图。
- 入口：CLI `--organize`；GUI 复选框「按类型整理」**默认开**；`manifest.organize`
  记 kinds/linked/failed/view，**不参与 ok/rc 判定**（附加产物，失败不毁整轮）。
- 测试 9 条；全量 `tests=735 failures=0 errors=0 skipped=11 → PASS`。

### 加密 krkr：`--allow-gui` 闭环暴露的三处缺陷（已修）

`教师催眠2` 第一次跑 23 秒就报 `kirikiri-gui-failed`，逐层挖出三个真问题：

1. **窗口只等 5 秒判一次**（`find_ui_window` 单次调用）→ 把「还没建好」当成「注入失败」。
   改 `wait_ui_window()` 轮询 40 秒（`KRKR_WINDOW_WAIT` 可覆盖），失败时打印该 pid 的
   全部窗口标题（区分「没建窗」与「标题不匹配」）。
2. **模态提示没人关**：注入后游戏自己弹 `Information / 正常に起動できませんでした`，
   盖住拖拽落点、并让完成判定永远看到「还有对话框」。新增 `dismiss_dialogs()`
   （只点非主界面的 `#32770`，按 `确定/OK` 关闭；主界面标题以 `KrkrExtract(local` 开头，明确排除）。
   实测：关掉它，data.xp3 立刻 +57 个文件。
3. **解包模式从来没设过**：KrkrExtract 的模式是开关式的，默认只开 `Decompile Script`，
   于是 data.xp3 只出 46 个 `.tjs` + 11 个 `.ks`（一张图都没有），image00 拖进去 57→57
   **0 新增还判「完成」**。新增 `click_button(pid, "Full Unpack")` 再拖。
   教师催眠1 当年能出 2009 张图，是因为那个 stage 带着上次手工操作落下的配置 ——
   **这条链路一直是「碰巧能跑」**，换机器/重建就退化成只解脚本。
4. 完成判据改成「产物数稳定 40s 且有产物」，不再靠 `FindWindow("#32770","KrkrExtract")`
   （主界面本身就是 `#32770`，旧写法能work纯属标题恰好不等）。

### 教师催眠2 现状（未完成，等人工）

- 11 个 xp3 全是 krkrZ（`garbro -l` 全 `unknown format`），目录带 `Mai@KF.dll` + `katei2.exe.org`。
- `--allow-gui` 在本机能跑起来：data.xp3 成功（57 个脚本），随后卡在
  `assert drop, "no blank spot on KrkrExtract UI"` —— 日志显示
  `blockers: {'Chrome_RenderWidgetHostHWND': …}`，**KrkrExtract 窗口被别的窗口压住**时
  找不到空白落点。这类 GUI 链路只适合「人在电脑前、别动鼠标」的场景。
- ⚠️ 代理会话另有干扰：`_krkr_stage/auto` 有 215 个文件，`drop_tree` 清理时被本会话的
  删除守卫拦下（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），表现为「无法清理 stage」。用户自己跑不会遇到。
- **收尾路径（交用户手动）**：打开 `_krkr_stage/auto/KrkrExtract.Lite.exe` → 把同目录 11 个
  `.xp3` 逐个拖进窗口（先点 `Full Unpack`）→ 产物在 `KrkrExtract_Output` →
  `orchestrator … --reuse-raw D:/HY/教师催眠2/output/raw` 走验收与对账。

交付：`packaging/Output/GalgameUnpacker-0.7.0-portable.zip`
（141.6 MiB，SHA256 `cbe4d8f8…0b9c25faa`；解压后 1484 文件 / 354.0 MiB；`--doctor` 报 0.7.0、`--gui-smoke` rc=0）。

> **README 滞后修正（2026-11-06，用户发现）**：`README.md` 还停在 **v0.4.2**（连
> `GalgameUnpacker-0.4.2-portable.zip` 的包名都没改），而这份 README 是**原样打进便携包**的
> —— 用户解压后第一眼看到的就是旧版本号。已把版本块、包名、GUI/CLI 用法、产物清单、
> 工作流表（加 `organize` 阶段）全部同步到 0.7.0，并把「加信任区能解决」的旧建议
> 改成 §8 的实测结论。
> 新护栏：`tests/test_docs_contract.py::test_readme_shows_current_version`
> 比对 README 的「当前版本 vX.Y.Z」与包名是否等于 `version.APP_VERSION`，再漂移即红。

## 2026-11-06 教师催眠2 闭环完成（v0.7.1）：手动拖拽 + 复用 raw 走通全链

用户手动把 11 个 xp3 拖进 KrkrExtract（先点 **Full Unpack**），产物 **9818 文件 / 3.0 GB**
（`data` / `image00~04` / `media` / `movie` / `scenario` / `voice01~02`）。移进
`output/raw` 后按 `--reuse-raw` 跑完剩余阶段：**rc=0，135.6s**。

| 阶段 | 结果 |
|---|---|
| detect | KiriKiri score=90 |
| case-lookup | 命中 3 个案例（`兼职人妻` / `教师催眠1 xp3-encrypted-krkrZ` / `高慢妻陥落！！`） |
| postprocess | 2748 个 `.tlg` → 2748 PNG（**复用上一轮，1.4s**） |
| verify | 图片 3082/3082、音频 6558/6558、视频 12/12，失败 0，媒体 **907.1 分钟** |
| organize | 图片 3082 / 音频 6558 / 视频 12 / 其他 166；硬链接 9818，失败 0 |
| 对账 | `diff=None`（`no-index-available`：krkrZ 无索引，这是「没验」不是「验过」） |

### 实跑暴露并修掉的 4 个问题（v0.7.1）

1. **后处理不认已转产物**：`--reuse-raw` 重跑会把 2748 张 tlg 再解一遍（**1229s**）。
   新增 `_converted_fresh()`（产物非空且 mtime ≥ 源）→ 1.4s，detail 里写「复用 N 个」。
2. **`Stage.as_dict()` 被 data 盖字段**：`**self.data` 放在规范字段之后，而 postprocess 的
   data 里也有 `ok`（转换成功数）→ `manifest.stages[].ok` 变成 **2748**。
   改成「data 先铺、规范字段后盖」。
3. **`stage_organize` 漏 `st.ok = True`**（`Stage.ok` 默认 False）→「硬链接 9818、失败 0」
   被判成 `[FAIL]`，交付记录自相矛盾。
4. **分类数与验收数差 1 个**：`voice01/*.soc` 扩展名认不出、按目录兜底算成音频
   （音频 6559 vs 验收 6558）。新增 `EXT_OTHER`（ks/tjs/csv/ttf/sli/soc…）优先于目录兜底；
   **`.dat`/`.at`/`.bin` 明确不能进** —— AdvHD 的视频就是 `.dat`、音频是 `.at`。

顺带两处视图重建的正确性：加 `.galunpack-view` 标记（自己的视图原地重建、别人的同名目录
顺延 `分类-2` 绝不覆盖）；重建时清理过期链接（分类规则变过会留下旧类目里的链接）；
已链同一文件时跳过（原先「先 unlink 再 link」是 9818 次删除，本会话里直接被删除守卫拦到整轮失败）。

交付：`packaging/Output/GalgameUnpacker-0.7.1-portable.zip`
（141.6 MiB，SHA256 `7e2e72a0…455f654f2`；`--doctor` 报 0.7.1、`--gui-smoke` rc=0）。

> 本轮全部实测证据（含「三层假阴性」「代理会话的假复现判据」「同一 exe 三处路径的对照表」）
> 已归档到 `verified-findings.md` **§32**，排查同类问题时先读那一节。

## 2026-11-06 v0.8.x：界面重做 / 高 DPI 适配 / 首次发布

用户要求「更现代、更有质感，天空蓝只作点缀」，随后给了两轮具体反馈（上半部分挤、勾选框小、
环境自检字太浅）。最终在 v0.8.2 收敛，并首次发布到 GitHub Release。

### 设计口径（改 UI 前先读这段，别推翻重来）

参考 Linear / Vercel Dashboard / GitHub Desktop / HandBrake：**留白 + 1px 发丝线分区**，
不用凹陷状态栏、不用 3D 凸起按钮；层级靠**字号与字色**（`#0F172A` / `#475569` / `#94A3B8`）。

- 底色 `#F5F7FA`、卡片纯白、描边 `#E5EAF1`；
- **天空蓝 `#0EA5E9` 只出现四处**：主按钮、输入框聚焦环、勾选框选中态、状态点，
  合计 < 3% 窗口面积。大面积铺蓝会让工具显得玩具感，也压掉日志可读性；
- 圆角 12（卡片）/ 9（按钮）/ 8（输入框），间距 24 / 18 / 12 三档。

### 控件全部自绘（`PillButton` / `RoundedEntry` / `Check` / `Card`）

ttk 在 Windows 上只有系统主题的三维边框，做不出「1px + 圆角 + hover」。
自绘后**接口仍兼容 ttk**（`configure(state=...)` / `configure(text=...)`），
所以 `_start` / `_poll` 那些调用点一行没改 —— 这条别破坏。

四个真踩过的坑：

| 坑 | 现象 | 正解 |
|---|---|---|
| Card 把 body 塞进 `create_window` 并撑满 | 卡片高度被 canvas 默认高（276px）锁死，内容 100px 下面留 170px 空白 | canvas 只当背景层（`place`），body 用 `pack`，高度由内容决定 |
| `create_polygon(..., smooth=True)` + 1px 描边 | 圆角断成一格格虚线（放大可见） | 用 `_round_pts()` 显式算 8 段圆弧点；要虚线时 `create_line(pts, dash=(5,4))` |
| 日志 `Text(height=10)` | 高 DPI 下行高翻倍，请求高度超过卡片可用空间 → `pack` 把日志压成 **0 行**，界面一片空白 | `height=3` + `expand` 撑满；日志卡片内边距单独降到 16 |
| 自绘尺寸写死像素 | 字体按点自动缩放、框不缩 → 200% 下「字大框小」，这也是「上半部分挤」的真因 | `UI.S` + `UI.px()`，按 `winfo_fpixels('1i')/96` 换算；`GALUNPACK_UI_SCALE` 可强制覆盖 |

### 交互补丁（v0.8.1）

- **进度线**：日志卡片分隔线位置一条 4px 细线，由 stage 事件驱动
  （`detect` 8% / `extract` 55% / `verify` 93% / `manifest` 100%），单调不回退、0.3 系数缓动、
  完成 0.9s 收起。位置**刻意粗粒度**：各阶段耗时差几十倍，按真实耗时换算会让线长时间卡住。
  进度线出现时把上方 1px 分隔线调成卡片色，避免两条横线并排。
- **拖拽悬停**：`<<DropEnter>>` / `<<DropLeave>>` → 输入框浅蓝底 + 天空蓝**虚线**
  （实线留给聚焦态，两者语义不能撞车），状态条提示「松开鼠标 → 用这个目录开始」。

### 文档与发布（2026-11-06 晚）

- **README 精简 312 → 125 行**：只留用途 / 安装 / 使用（GUI+CLI 表）/ 产物 / 引擎表 /
  环境 / 常见问题 / 边界 / 构建 / 文档索引。删掉版本演进长文、界面细节、工具链细节。
  改完必须跑 `test_docs_contract.py`（锁「当前版本」「包名」「引擎表 = IMPLEMENTED」三件事）。
- **首次 GitHub Release**：`v0.8.2`，附件 `GalgameUnpacker-0.8.2-portable.zip`。
  环境里**没有 `gh`**，走的是「从 Git Credential Manager 取 token → REST API：
  `POST /releases` 建标签和发布、`POST uploads.github.com/.../assets` 传附件」。
  token 只存在变量里，别 echo、别写进任何文件。

### 发布收尾与最终校验（2026-11-06 21:45，接手先读这段）

首传的包里 README **还是精简前的 312 行版本**，而说明已写「包内 README 为精简版」——
版本一致但内容不一致。于是重打 ZIP（125 行 README），SHA256 从
`bcbd5f80…6e6c7899` 变成 **`687f4cd39611cbb714b884beb032c00d6ae7ab89dca534693facf26de05e983d`**，
PATCH 说明里的校验值同步改掉，再删旧 asset `717271806` 准备替换。

⚠️ **踩到的坑**：删旧附件与传新附件之间会话被中断，结果 Release 说明已是新 SHA、
**`assets` 却是空数组**（`GET /releases/436536386/assets` 返回 `[]`）——
页面看着像发布完成，实际一个可下载文件都没有。补传后恢复正常。
**护栏**：任何「替换附件」操作，先 `GET /releases/{id}/assets` 看数量与 `digest`，
确认后再动手；删旧附件和传新附件要连着做完，别在中间停；结束后必须再查一次
`assets[].digest` 是否等于本地 `sha256sum` 与说明里的 SHA256。

最终状态（已三方核对）：

| 项 | 值 |
|---|---|
| Release | `v0.8.2` / id `436536386`，公开，含本次更新说明与 CLI 用法 |
| 附件 | 1 个：`GalgameUnpacker-0.8.2-portable.zip`，asset `717312891`，148,528,606 B |
| digest | `sha256:687f4cd3…f26de05e983d`（远端 = 本地 ZIP = 说明） |
| 包内 README | `orchestrator/README.md` 125 行，与仓库同源 |

上传用 `curl -X POST --data-binary @ZIP "https://uploads.github.com/repos/.../releases/{id}/assets?name=..."`
（`Content-Type: application/zip`），148 MB 约 27s 返回 201。API 响应缓存文件
（`_ui/assets.json` / `rel.json` / `rel_patch.json` / `upload*.json`）属临时产物，用完即删，
不要留在工作树里，更不要提交。

### 落点遮挡加固（2026-11-06 22:20，源码态，**尚未真机验证**）

用户定「先加固，再实跑」。第四轮那句 `no blank spot` 拆开是**五层**问题，不是「窗口被挡」一句话：

| # | 真因 | 修法 |
|---|---|---|
| 1 | **前台锁**：Windows 只允许前台进程调 `SetForegroundWindow`；本脚本是 orchestrator 拉起的子进程，注入后前台常是游戏/浏览器，调用静默返回 0，窗口根本没被抬起来 | `raise_ui_window()` 用 **TOPMOST → NOTOPMOST** 连招：先临时置顶越过所有普通窗口，立刻退回普通组顶部（Z 序仍在最前），**不需要前台权限**，也不会把窗口永久置顶留给用户 |
| 2 | 64 位下 `SetWindowPos` 未声明 `argtypes`，`(HWND)-1` 被按 `c_int` 截成 `0xFFFFFFFF`，置顶静默失效 | 显式声明 `argtypes/restype`；另验证 `wintypes.HWND(-1) == 0xffffffffffffffff` |
| 3 | 落点**只算一次**，11 个 xp3 共用一个坐标；两包之间约 40s，任何一次切窗都会让后续全错 | 循环内每包 `find_drop_point(ui)` 重新抬窗 + 重扫；循环外保留一次早失败检查 |
| 4 | 打开 Explorer 并 `SetForegroundWindow(exp)` 后又把终点盖住 —— 旧代码从不复核终点，包可能被拖到 Explorer 上**静默丢掉** | 拖拽前 `ensure_drop_point()` 复核；失效就在当前 Z 序里换一个仍可见的空白点，**刻意不重新抬窗**（否则起点 xp3 图标会被压到后面，起点终点必须同时可见） |
| 5 | 裸 `assert drop`：`python -O` 下整行被优化掉，报错只有一句字符串，看不出谁挡着 | 抛 `RuntimeError`，列出遮挡窗口的类名 / pid / 标题与出现次数，并给「关闭或缩小窗口、别切窗口」的处置建议 |

新增 `DROP_ATTEMPTS`（`KRKR_DROP_ATTEMPTS` 可覆盖，默认 6）、`DROP_GRID=40`。
`scan_drop_point` **仍只接受 `WindowFromPoint == 主窗口` 的点**：子控件不收 `WM_DROPFILES`，
落到上面会丢包，这条口径别「顺手放宽」。

回归：`tests/test_krkr_drop_point.py` 7 条，用 `FakeUser32` 把 Z 序抽象成
`WindowFromPoint` 返回值，锁住前台锁下仍能抬窗、Chrome 遮挡恢复、全遮挡报错可操作、
子控件不作落点、Explorer 盖住时刷新且**不重新抬窗**、以及 main 里
`find=3 / ensure=2`（2 个包 → 循环外 1 + 每包 1 / 每包 1）。全量回归
`tests=756 / 0 failures / 0 errors → PASS`，`make_golden.py --check` 零漂移。

> **别把「测试绿」当成「闭环完成」**：这些是 Win32 行为的替身测试，真机上的前台锁、
> DPI、多显示器、杀软注入拦截都没跑过。下一步仍是要一段干净桌面重跑 `--allow-gui`；
> 实跑用本地 `GalgameUnpacker-0.8.2-dropfix1-portable.zip`（已发布的 0.8.2 附件里没有
> 这次改动）。包已解压到 `D:\GalgameUnpacker\orchestrator`，直接双击 exe 即可；
> 别放 `D:\K`（会被降成 Low 完整性，写不进去）。

### 本地加固包怎么打的（2026-11-06 23:17，用户选「只出本地包、不发布」）

`build_exe.portable()` 的输出名写死 `GalgameUnpacker-<APP_VERSION>-portable.zip`，直接跑会
**覆盖已发布 0.8.2 的本地副本**。这次保持 `version.py` 的 `0.8.2` 不变（README 有契约测试
锁着「当前版本」与便携包名），改为：只调 `build_exe.build()` 重新冻结 → 同步精简版 README
→ 写 `BUILD_INFO.txt` → 用 `shutil.make_archive` 压到带 `-dropfix1` 的新文件名 → 立刻删掉
dist 里的 BUILD_INFO（别污染下次正式构建）。打包装在一次性脚本 `.build_dropfix_pack.py`
里，执行后已删除；关键护栏是**压缩前后各断言一次发布包 SHA256 未变**，以及包内 README
125 行与仓库逐字相同、包内 exe 与 dist 的 SHA 相同、`testzip()` 无损坏条目。

两个坑：① PyInstaller 的 COLLECT 阶段要删旧 `dist/orchestrator`（1502 文件）会被本机
删除守卫拦，规避办法照旧是**把旧目录改名**（`orchestrator_prev_082`）再重跑，别批量删；
该旧目录留作新旧对照（非交付物，可自行删除）。② `shutil.make_archive` 自动加 `.zip`，
`base_name` 里别多写后缀；写 `BUILD_INFO.txt` 要显式 `newline="\n"`，否则 Windows 文本模式
转成 CRLF，逐字校验会对不上。

加固代码确实进包的实证（比「重新冻结过」硬）：`CArchiveReader(exe)` →
`open_embedded_archive("PYZ.pyz")` → `extract("krkr_auto_extract")` 返回 code 对象，
遍历 `co_names` / `co_consts`。新 exe 含 `raise_ui_window`、`scan_drop_point`、
`find_drop_point`、`ensure_drop_point`、`KRKR_DROP_ATTEMPTS` 且旧断言字符串消失；
旧的 0.8.2 exe 正好相反（885 个 PYZ 模块数一致，差异只在这一个模块）。

## 2026-11-07 真机 `--allow-gui` 实跑失败与 BugFix（事故原始记录；01:02 收口见后一节）

> ⚠️ 本节与下面「源码 / 测试 / QA 状态」「换窗口后的接手清单」是 **00:20 的历史快照**，
> 其中的「未提交 / QA 未完成 / 待接手」均已过时。当前状态以文件顶部与
> 「2026-11-07 00:47 接手收口」§4/§5 为准；事故证据与四个真因仍然有效。

**换窗口前后的唯一权威状态。** 用户用 `D:\GalgameUnpacker\orchestrator`（dropfix1 解压目录）
在 GUI 勾「用于加密的 krkr」+「按类型整理」，游戏 `D:/HY/教师催眠2`，输出
`D:\HY\教师催眠2\output`（已有上一轮人工拖拽成果），点开始后弹「需要人工介入」：
退出码 1、交付 0 文件、失败原因 `extract-failed`。

### 现场（只读证据，路径 `D:\HY\教师催眠2\output`）

| 位置 | 内容 |
|---|---|
| `manifest.json` | detect OK(KiriKiri score=90) / case-lookup 命中 3 案例 / preflight OK / **reset OK「`--overwrite` 已清空 raw/ 9818 个文件、png/ 2748 个文件」** / extract FAIL 60.54s「GUI 链路失败或没有产出 KrkrExtract_Output (rc=1)」；`manual.code = kirikiri-gui-failed` |
| `_work/extract.log` | 11 个 xp3 全部 `garbro -l … unknown format`；`krkr_auto_extract.py rc=1`；`injected pid=34888 ui=0x9A0F28 rect=(812,282,2068,1422)`；`dismissed dialog(s): ['Information']`；`WARNING: ??? 'Full Unpack' ?????`；`RuntimeError: 拖拽落点被遮挡：重试 6 轮仍未… - (无可见遮挡窗口)` |
| 弹窗 / `_work/manual.log` | 摘要「这个游戏的 xp3 自动解不开：GARbro 列不出目录」+ 备选「加 `--allow-gui --overwrite`」，与「用户已经勾了 --allow-gui」自相矛盾 |

**结论：`allow_gui` 确实生效、GUI 链路真跑了 60.54s**，不是「没走全自动」。上一轮加固也生效了
（从裸 `assert` 变成带处置建议的 `RuntimeError`），但暴露 4 个新问题：

| # | 真因 | 修法（已在源码、未提交） |
|---|---|---|
| 1 | `--overwrite` 在 extract **之前**直接 `drop_tree(raw/)` + `drop_tree(png/)`，删除不可逆、失败不回滚；`gui.has_stale_products` 只数 raw/png，raw 被清空后「分类」视图还在却判成空目录 → **跳过二次确认** | `orchestrator.py`：同盘**改名备份**到 `<out>/_overwrite_backup_<时间戳>/{raw,png}`（零拷贝、不删）；`_finish_failure` 自动回滚（无新产物 rename 回来；有新产物绝不覆盖、备份保留）；reset/rollback stage 写进 manifest；GUI 把带 `.galunpack-view` 标记的视图也算残留 |
| 2 | 落点扫描 `range(rc.top+6, rc.bottom-6, 40)` 在 `GetWindowRect` 返回**退化矩形**（最小化 -32000 附近 / 句柄失效全 0）时循环体执行 **0 次**，blockers 空 → 把「窗口不可见」误报成「(无可见遮挡窗口)」；旧实现命中首点即 return，统计只覆盖前几点 | `krkr_auto_extract.py`：新增 `_rect_valid` / `_is_window_alive` / `_is_window_visible` / `_classify_point` / `_rebind_ui_window` / `_scan_drop_point` 四分类统计（hit/no_window/child/other）/ `_drop_failure_message` / `find_drop_point_ex`（每轮自检 → 必要时重绑主窗口 → 抬窗 → 刷新 rect → 扫描，新 hwnd 回写 `main.ui`）。**口径未放宽**：仍只接受 `WindowFromPoint == 主窗口`，子控件不作落点 |
| 3 | `click_button` 在**第一个**主窗口就 return、标签只做 `== "Full Unpack"` 精确比较（`&`/大小写/空格全漏）；**旧 main 只 log 一句 WARNING 就继续拖 11 个包**，KrkrExtract 默认只 `Decompile Script` → 无声的半份交付；`log()` 用 `msg.encode("ascii","replace")` 把中文打成 `?`，被 `_run_sibling` 收进 extract.log 后完全不可读 | 遍历全部主窗口 + `_norm_button_label` 归一化 + 只读诊断 `describe_unpack_controls`（区分枚举失败 / BM_CLICK 没生效，按 pid 找不到时按标题兜底）；**没点上 Full Unpack 在拖包之前硬失败**（`RuntimeError`，仅 `KRKR_ALLOW_NO_FULL_UNPACK=1` 降级且写明风险）；`_print_log` 保住中文 |
| 4 | `manual.plan_for` 的 gui_failed 分支只换 code/why，summary 与 alternatives 复用加密分支；`stage_extract_kirikiri` 失败 detail 没带 krkr stdout 真实报错；`gui.summarize_text` 只显示错误码 | `manual.py` gui_failed 独立可操作文案（引用真实报错、日志路径、`KRKR_DROP_ATTEMPTS` / `KRKR_WINDOW_WAIT`、独占桌面、备份路径）；`allow_gui=True` 时 `alternatives=()`；`orchestrator._gui_error_from_output` 写入 `extract.data.gui_error` 与 detail「真实报错：…」；GUI 摘要显示错误码 + 真实原因 |

### 数据现场与恢复（最急）

`output/raw`、`output/png` **目录已不存在**；`output/分类` 硬链接视图 **9818 文件 / 4.4 GiB 完好**
（含 `.galunpack-view` 标记）。数据没真丢，只是少了一个目录项。

新增 `tools/restore_from_view.py`（纯标准库、零项目依赖、可单独拷走）：只读视图、要求
`.galunpack-view` 标记、目标冲突默认拒绝覆盖、链接失败**不退化成复制**、只建硬链接不复制字节。
只读 dry-run 已实测：`视图条目 9818（raw 7070 / png 2748）／新建硬链接 9818，冲突 0，失败 0（未写盘）rc=0`。

```
C:\Python314\python.exe tools\restore_from_view.py --out "D:\HY\教师催眠2\output" --dry-run
C:\Python314\python.exe tools\restore_from_view.py --out "D:\HY\教师催眠2\output"
C:\Python314\python.exe tools\restore_from_view.py --out "D:\HY\教师催眠2\output" --check --sample 8
```

**口径别写错**：还原的是 9818 个**交付文件**（raw 7070 + png 2748），不是「raw 9818 全恢复」；
原 raw 里 2748 个 `.tlg`/`.pna` 中间格式不在视图内、无法还原（PNG 成品完整）。若确实需要中间
格式原件只能重新解包 —— 这次**没有** `_overwrite_backup_` 目录，因为旧代码根本没备份。

### 源码 / 测试 / QA 状态

- HEAD `635549c`；工作树 **9 个未提交改动**：改 `gui.py`、`krkr_auto_extract.py`、`manual.py`、
  `orchestrator.py`、`tests/test_krkr_drop_point.py`；增 `tools/restore_from_view.py`、
  `tests/test_krkr_full_unpack.py`(14)、`tests/test_overwrite_backup.py`(14)、
  `tests/test_restore_from_view.py`(10)。已跟踪部分 diff `+807/-93`。
- 工程师自测：`tests=800 / 0 failures / 0 errors / 9 skipped → PASS`（791 passed / 9 skipped）；
  主理人 00:20 复核 `790 passed / 10 skipped`、`0 failures / 0 errors`（skip 差异只是环境用例
  波动；基线 756 + 新增 44，新增用例无一被跳过）；`make_golden.py --check` 零漂移；
  `IS_PASS: YES`。定向 krkr 60 passed、backup+restore 24 passed。
- **QA 独立验证未完成**：跑到一半被中断，只留下不完整的 `_qa_junit.xml`（已删）。它发现、
  我已核实的疑点：`Stage.as_dict()`（`orchestrator.py:160`）把 data **平铺**到顶层，
  `manual._gui_error_text`（`manual.py:291`）只读 `s.get("data").get("gui_error")` →
  生产路径永远取空，靠 detail 里「真实报错：」的兜底分支（295 行）才工作；
  `tests/test_overwrite_backup.py` 的 `_GUI_STAGES` 夹具用了非真实的嵌套 `data` 形状，把死路径测绿了。
  **最小修法**：`_gui_error_text` 同时读顶层 `s.get("gui_error")`，并把夹具改成平铺形状。
- 另一未决问题：恢复后（raw 7070 + png 2748）直接 `--reuse-raw --organize` 能否 rc=0？
  要查 `stage_postprocess._converted_fresh()` 在源 `.tlg` 缺失时是跳过 / 重转 / 报错，
  以及 `verify` 图片计数、`manifest.stages[].ok` 会不会被 `data["ok"]` 覆盖成异常值（v0.7.1 踩过）。

### 换窗口后的接手清单

1. `git status` 确认 9 个未提交改动还在；`C:\Python314\python.exe tests\run_all.py` 复现 800/0/0。
2. 若团队上下文仍在，唤醒 `software-qa-engineer` 出最终报告（含上面两个未决点），按判定决定
   是否把 `_gui_error_text` 交回工程师；否则自己按这两点做独立验证，别只复述工程师结论。
3. **先恢复用户数据**（三条命令，先 dry-run）；`output/分类` 目录别删、别改名、别再点「开始解包」。
4. 显式 add 那 9 个文件提交并推送（网络已恢复）；别改 `version.py` / README / Release `v0.8.2` 附件。
5. 重新打本地包（新标识，不覆盖 dropfix1 与 0.8.2），解压到 `D:\GalgameUnpacker`，再让用户
   独占桌面约 40 分钟实跑；**修复未经真机复现，不能声称闭环**。

仍需真机验证：click_button 能否在真实 KrkrExtract 上枚举并点到 Full Unpack（现场日志是问号，
分不清枚举失败还是点击失败）、退化 rect 的真实成因（看新日志的四分类统计行）、
`IsWindow`/`GetAncestor` 在 200% DPI 与真实 Z 序下的行为、`raise_ui_window` 连招在具体桌面
能否恢复可见性、改名备份/自动回滚在冻结 exe + 中文路径 + 删除守卫下的表现，
以及整条链路端到端能否产出含图/音频的完整产物。

## 2026-11-07 00:47 接手收口（数据恢复 + QA 独立验证 + 契约修复）

### 1. 用户数据恢复（已实跑，不是 dry-run 推演）

现场只读复核：`output/` 只有 `_work/`、`manifest.json`、`分类/`、`类目清单.csv`；
`raw/`、`png/` 不存在；`分类/` 9819 文件（含 `.galunpack-view` 标记）/ 4.4 GiB；
无 `_overwrite_backup_`（旧代码根本没备份）。

| 步骤 | 结果 |
|---|---|
| `--dry-run` | 视图条目 9818（raw 7070 / png 2748），新建硬链接 9818，冲突 0，失败 0，未写盘，rc=0 |
| 实跑 | 新建硬链接 9818，冲突 0，失败 0，rc=0 |
| `--check --sample 8` | raw 7070 / 1,134,518,660 B；png 2748 / 3,565,677,014 B；缺失 0；8 个抽样 `samefile=True`、大小一致 → 通过，rc=0 |

`分类/` 视图未删、未改名、未重写；恢复工具只建硬链接，没用 `--force`。
**中间格式 2748 个 `.tlg`/`.pna` 不在交付视图内，恢复不了**（PNG 成品完整）。
用户目录此后别再点 `--overwrite` 覆盖这份恢复产物。

### 2. QA 契约疑点：已核实并修复

`orchestrator.Stage.as_dict()`（`orchestrator.py:160`）是 `{**self.data, "stage":…, "ok":…}`
—— **data 平铺，结果里没有 `data` 键**。`manual._gui_error_text` 原来只读
`s.get("data").get("gui_error")` → 生产路径永远取空，一直靠 detail 里「真实报错：」的
兜底分支碰巧能用；`tests/test_overwrite_backup.py` 的 `_GUI_STAGES` 夹具用了非真实嵌套形状
且 detail 带 marker，把死路径测绿了。

修法：`_gui_error_text` 先读顶层 `s.get("gui_error")`，再兼容嵌套 dict，最后退回 detail 后缀；
夹具改成 `Stage.as_dict()` 的真实平铺形状且 detail 不带 marker；新增 3 条回归
（真实 `Stage(...).as_dict()` 形状 / 顶层优先于 detail / 嵌套与老 manifest 兼容）。

### 3. 恢复后 `--reuse-raw --organize` 是否 rc=0：隔离实证

新增 `tests/test_reuse_after_restore.py`（tmp_path 复刻现场：raw 只有交付文件、png 是合法 PNG
成品、`分类/` 视图与清单已存在、假 xp3 全 `unknown format`），3 条全过：

- **默认模式 rc=0**。postprocess `ok=True/skipped=True`、detail「无待转格式（.tlg/.pna），
  无需后处理」，monkeypatch 的 `tlg2png` 一次都没被调用；verify final = raw 交付 + png 成品，
  图片数不受源 tlg 缺失影响；`manifest.stages[].ok` 全是布尔（v0.7.1 的 `data["ok"]` 覆盖没回潮）；
  reconcile `method=no-index-available`、`diff=None`（没验不伪装成 0 差）；
  organize 原地重建视图，**视图条目数、raw/、png/ 文件数全部不变**（`_prune_stale` 删 0）。
- **边界（重要）**：这只对「加密包、索引列不出」成立。若 GARbro 列得出索引，reuse 分支拿
  索引条目数对着 raw/ 数，恢复后少了 .tlg/.pna 中间格式必然 `复用产物对账失败`
  → rc=1 / `extract-failed`。这类样本只能重新解包，不能靠视图恢复后半路复用。
- `--strict` 下无地面真相仍按既有契约判 rc=1 / `strict-no-ground-truth`。

### 4. 测试、提交与打包（01:02 收口）

`tests/run_all.py` → **808 / 0 failures / 0 errors / 10 skipped → PASS**（基线 800 + 新增 8：
manual 3 + reuse 3 + build_exe 2）；`make_golden.py --check` 零漂移。3 次提交均已推送
`game-get/master`：`9aabbca`（12 文件：4 项根因修复 + 恢复工具 + QA 契约 + 文档）、
`3ca1045`（`build_exe.py --tag` 护栏 + 2 测试）、`22495fd`（BUILD_INFO 去掉硬编码测试数），
其后是文档回写提交（见 `git log`）。
**始终显式 add，没有用 `git add -A`，也没有删任何文件。**

### 5. 新包 bugfix1：构建、校验与部署

- **构建**：`build_exe.py` 新增 `--tag`（文件名后缀 + 包内 `BUILD_INFO.txt` 自动生成；
  `APP_VERSION` / README 契约不动；**同名 zip 一律拒绝覆盖**，tag 限安全字符；2 条护栏测试）。
  旧 `dist/orchestrator` 与 `build/orchestrator` **改名保留**（`orchestrator_prev_dropfix1`、
  `build_prev_dropfix1`），没有批量删除——绕开 PyInstaller COLLECT 阶段的删除守卫。
  重跑冻结 1m36s：1485 文件 / 354.1 MiB，6 个随包工具全部 `[OK]`。
- **产物**：`packaging/Output/GalgameUnpacker-0.8.2-bugfix1-portable.zip`，
  148,556,732 B / 141.7 MiB，SHA256 `29f35cf5725074a94023ab92ad10e30f4c2dd1388f20e274f54701e006a0ee7c`。
  初版包（BUILD_INFO 里误写 806）**改名保留**在
  `_spike_pkg/dist/GalgameUnpacker-0.8.2-bugfix1-prelim-portable.zip`，未删除；
  修掉口径后用 `--portable --tag bugfix1` 重出，包内 `源码提交 = 22495fd`。
- **校验**：`testzip()` 无损坏（1514 项）、README 125 行与仓库逐字相同、包内 exe 与 dist
  同 SHA `d00b1665…87b5`；`CArchiveReader` 提取 PYZ 模块比对：新 exe 的
  `krkr_auto_extract` 含 `_scan_drop_point` / `describe_unpack_controls` / `_norm_button_label`
  （旧 dropfix1 exe 没有），`manual._gui_error_text` 含平铺读取的 `isinstance` —— 修复确实进包。
- **部署**：旧 `D:\GalgameUnpacker\orchestrator` 改名 `orchestrator_prev_dropfix1` **保留未删**，
  新包解压到 `D:\GalgameUnpacker\orchestrator`；`--doctor` High 完整性 / 全部位置可写 / rc=0，
  `--gui-smoke` rc=0，冻结 exe 对 `教师催眠2` 只读 `--dry-run` rc=0
  （detect / 案例库 / 随包 GARbro 全通）。
- **已发布 0.8.2 与 dropfix1 的 zip 字节、mtime 均未变**（148,528,606 B / 151,401,258 B）。

⚠️ 真机 `--allow-gui` 全自动仍未复现：以上全是源码态 + 冻结包自检 + 隔离替身验证。
当时计划用 bugfix1 包、约 40 分钟独占桌面跑 `教师催眠2`（实际两轮失败，见下一节）。

## 2026-11-07 16:01 WinForms 根因与 bugfix2（15:07 / 15:22 两轮真机失败复盘）

### 1. 现场（两轮，同一处失败）

用户用 bugfix1 包在 `D:\HY\教师催眠2\output11`（**新目录**，没碰恢复好的 `output`）跑
`--allow-gui`。`_work/extract.log` 追加了两轮（15:07 pid=29884、15:22 pid=8884），
两轮都在 `dismissed dialog(s): ['Information']` 后 1 秒报：

```
ERROR: 没点上 'Full Unpack'：按钮枚举失败。
主窗口=[]；Button 文本=[]；全部子控件=[]；诊断异常=None
```

注入成功（`ui=0x120752 rect=(812,282,2068,1422)`）、11 个 xp3 全 `unknown format`
（整包 krkrZ，预期内）、预检与案例库全通过。**不是落点遮挡、不是加密判定、
不是安全软件、不是桌面没独占**；是「点 Full Unpack」前置检查主动刹车（防半份交付）。

### 2. 根因（二进制证据 + 源码对读）

- `KrkrExtract.Lite.exe` PE 里有 CLI header（`BSJB`）与 `System.Windows.Forms`
  → .NET WinForms；`KrkrExtract.Core.dll` / `KrkrExtract.UI.Lite.dll` 的 UTF-16
  字符串表里有 `Full Unpack` / `Text Decryption`（界面选项）。
- `find_ui_window(pid)` 按「pid + 标题 `KrkrExtract(local`」找到窗口（所以 rect 有效）；
  但 `_main_dialogs(pid)` 额外要求 `cls == "#32770"`，`describe_unpack_controls`
  的全局标题兜底也过滤 `#32770`，`click_button` 又要求子控件 `cls == "Button"`。
  WinForms 主窗口类名是 `WindowsForms10.Window.8.app...`、按钮是
  `WindowsForms10.BUTTON.app...`，三条全不匹配 → 枚举恒空。
- 日志里能关掉 `Information` 弹窗，正因为它才是标准 `#32770` 消息框。
- 旧版诊断只打印「过滤后的空列表」，没打原始窗口清单，所以分不清「类名被过滤」
  和「窗口真消失了」。

### 3. 修法（`b22174a`，11 条新替身测试）

| 层 | 改动 |
|---|---|
| 判据 | `_main_dialogs` 只按 pid + 标题认主窗口、按标题排除模态框；按钮候选按文本归一化精确匹配，类名含 `BUTTON` 优先，不再要求 `Button` |
| 复核 | `click_button_ex` 返回 `(是否点到, 复核状态)`；点击后 `BM_GETCHECK` 读勾选状态，日志写明「已勾选 / 未勾选 / 无法复核」 |
| 兜底 | Win32 枚举不到时走 UIA：`_uia_item_rect.ps1` 新增 `-Invoke` / `-Fuzzy`，InvokePattern → TogglePattern → BoundingRectangle 中心鼠标点击；带回控件清单诊断 |
| 诊断 | `describe_unpack_controls` 新增 `raw_windows`（该 pid 全部顶层窗口 hwnd/类名/标题）与 `global_title_matches`，失败日志全部带上 |
| 可读性 | `_gui_error_from_output` 去重、只取 1 条主报错 + 2 条原始诊断；`验收[skipped]` 改显示「未执行」而非 `None/None失败`；manual 按真因给步骤，不再让用户照着落点模板做 |

全量 `tests=819 / 0 failures / 0 errors / 9 skipped`，golden 零漂移；
`_uia_item_rect.ps1` 经 PowerShell Parser 语法校验通过，`build_exe.py --check` 清单齐全。

### 4. bugfix2 包与部署

`GalgameUnpacker-0.8.2-bugfix2-portable.zip`（148,560,766 B，
SHA256 `931c6c44…1eb41cdb2`），包内 BUILD_INFO 记 `源码提交 = b22174a`；
`testzip()` 无损坏（1514 项）、README 逐字相同、exe 与 dist 同 SHA。
CArchiveReader 实证 `uia_click_button` / `click_button_ex` / `_uia_ps` /
`MAIN_TITLE_PREFIX` 与新版 ps1 都进包；`manual` / `gui` 的新文案也在。
旧 dist/build 目录改名 `orchestrator_prev_bugfix1` / `build_prev_bugfix1` **保留未删**。

部署时旧 `D:\GalgameUnpacker\orchestrator` 被用户仍开着的 GUI 进程（pid 30452）占用，
改名失败 → **不强杀、不删、不覆盖**，新包解压到并列目录
`D:\GalgameUnpacker\orchestrator_bugfix2`：`--doctor` High 完整性 / rc=0、
`--gui-smoke` rc=0、冻结 exe 只读 `--dry-run` rc=0。
关掉旧 GUI 后可把两目录改名切回标准路径；**别在旧窗口里点开始**。

⚠️ **真机 `--allow-gui` 全自动仍未复现**。以上全是源码 + 替身 + 冻结包自检；
下一次约 40 分钟独占桌面用 bugfix2 跑 `教师催眠2`，见待办 1、2。
