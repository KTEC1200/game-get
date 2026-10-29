# 自动解包 galgame 的 AI 工作流 → Windows 软件：可行性与落地方案

> 事实来源：GitHub REST API（`license.spdx_id` / `archived` / `pushed_at`）+ 仓库 README 原文逐条核实，复核时点 2026-10-12。
> 凡未能核实的内容一律显式标注 **[未核实]**。**本文不构成法律意见。**

---

## 0. 前提与假设（对应需求中的「待补充」）

需求中 5 项信息缺失，按最通用情形假设如下。**每处假设都标明它影响哪些结论**。

| 待补充项 | 本文采用的假设 | 影响 |
|---|---|---|
| 目标引擎/格式 | 不限定单一引擎，覆盖面最大化，优先日系主流（KiriKiri/Z、RealLive、Siglus、BGI/Ethornell、Majiro、CatSystem2、NScripter、YU-RIS、Artemis、Ren'Py、RPG Maker、Unity） | 第 1 节通用；第 3 节偏向多格式通用解包器 |
| 解包目标内容 | 全部（文本+图片+音频），**文本优先** | S5/S6 都要做；若只要文本，S5 工作量可砍大半 |
| AI 承担环节 | 引擎识别兜底、参数求解、报错分诊、未知格式解析器生成、结构化、翻译与 QA | 第 2 节全部设计 |
| 技术栈 | Python 编排 + 外部解包器作独立 exe 调用 | 第 4 节以 PyInstaller 为主线 |
| 许可证要求 | **假设要商业/闭源分发**（最严格）。若纯个人非商业，第 5 节约束大幅放松 | 第 3 节把 GPL 与非开源组件全部标红 |

> **先说结论**：项目**技术可行**，但「AI 工作流」不是最大风险，**许可证与法律边界才是**。并且存在一个重合度极高的先例（GameStringer）证明整条链路可工程化——同时它也证明了**别把它当开源代码抄**（3.4、5.1）。

---

## 1. 技术链路拆解

| # | 环节 | 输入 | 输出 | 难度 | 主要失败模式 |
|---|---|---|---|---|---|
| S1 | 目标发现 | 游戏安装目录 | 候选文件清单 | 低 | 无扩展名归档、归档嵌在 exe 内 |
| S2 | 引擎/格式识别 | 头部字节+目录结构 | `(format_id, 置信度)` | **中～高** | 多义命中、私有变体、加密版本 |
| S3 | 参数求解 | `format_id`+元信息 | 可执行 argv | **中～高** | 需要密钥/plugin/游戏标题 |
| S4 | 执行解包 | argv | 原始资源树+日志 | 低 | 崩溃、部分成功、静默产出垃圾 |
| S5 | 资源解码 | 专有图片/音频 | PNG/OGG/WAV | 高（长尾） | TLG/PSB/G00 各一个编解码器 |
| S6 | 文本提取 | 脚本文件 | 原始文本流 | 高（长尾） | Shift-JIS/UTF-16、控制码、脚本加密 |
| S7 | 结构化 | 文本流 | `(id, speaker, text)` | 中～高 | 说话人切分、内嵌变量 |
| S8 | 翻译与后处理 | 结构化文本 | 译文+QA 分 | 中 | 术语不一致、长度膨胀、控制码破坏 |
| S9 | 回写/重打包 | 译文+原始归档 | 可运行的游戏 | **最高** | 索引/校验重建、重新加密 |
| S10 | 验证 | 打补丁后的游戏 | 通过/失败 | 中 | 需真正启动游戏 |
| S11 | 产物交付 | 中间产物 | 资源包+报告 | 低 | 命名/去重/格式统一 |

### S2 引擎/格式识别 —— 第一个真正的难点
- **成熟工具已内置大规模签名识别**，这是设计前提：
  - GARbro 签名表约 **1000 条**「文件/签名 → 引擎/厂商 → 游戏名」映射，公开可查：<https://morkt.github.io/GARbro/supported.html>。
  - arc_unpacker README 原文：*"It will guess the format and unpack it for you."*
- **所以签名识别不该由 LLM 从零做**，应复用现成签名表 + 魔数匹配。
- **arc_unpacker README 亲自点名的两个失败模式**（设计 AI 兜底时最值钱的一手依据）：
  1. **多义命中**：*"The file format might be detected by two or more decoders at once. In such cases you need to tell the program which one to use by supplying `--dec=...`."*
  2. **参数缺失**：*"XP3 archives need `--plugin` that tells what kind of decryption to use."*（示例 `--plugin=fsn` = Fate/Stay Night）

### S3 参数求解
- GARbro README 印证同一问题：*"Some archives are encrypted, so you will be asked for credentials or a supposed game title."*
- **「用哪个 decoder + 哪个 plugin/key」是需要外部知识才能填的参数空间** —— 正是 AI 检索+推理能补的位置。
- 已验证的加密变体实例：`xmoezzz/xp3-brute` 专治 KiriKiri 变体；`YeLikesss/KrkrExtractForCxdecV2` 专治 Wamsoft **CxdecV2(Hxv4)**。说明同一「.xp3」下还有多种加密，参数求解是真实需求而非假想。

### S5/S6 长尾
- **复用优先**：GARbro 把「解包」和「转通用格式」合在一起做（README：*"with all images and audio converted to common formats in the process"*）。
- 文本必须处理 Shift-JIS / UTF-16 / Big5、内嵌控制码、脚本加密。

### S9 回写/重打包 —— 最高难度，最容易被低估
- **一手证据**：arc_unpacker 作者**明确拒绝**实现打包。README 原文：
  > *"Packing / encoding support? **Not going to happen.** ... writing encoders is often much more difficult than writing decoders."*
- **含义**：**「解包工具生态」远成熟于「回写工具生态」**。绝大多数工具只能出不能进。
- **这是选型的第一决策点**：
  - 目标 = 「提取资源」→ 难度降一个数量级，工具随手可得。
  - 目标 = 「汉化后可运行的游戏」→ **必须在选型阶段就确认该引擎有没有回写方案**（KiriKiri 有：`xmoezzz/KrkrExtract` 明确支持 pack；文本层有 `VNTranslationTools/VNTextPatch` 支持 21 种引擎回填）。

---

## 2. AI 工作流设计

### 2.1 六条设计原则（先定约束）
1. **确定性优先，AI 兜底**。能用签名表/魔数判定的**绝不调 LLM**——省成本且保证可复现。
2. **LLM 只做分类、排序、规划、生成代码；绝不采信它给出的二进制偏移/长度。** LLM 会编造 offset。
3. **所有 LLM 输出必须 schema 校验 + 白名单校验**后再执行。
4. **每个节点都要有机器可判定的验收信号**，否则失败会静默传播。
5. **绝不把 LLM 输出拼成 shell 字符串**，一律 `subprocess.run(argv_list)` 防命令注入。
6. **有限重试 + 预算上限**（重试 ≤3、单游戏花费上限、总时长上限），防死循环烧钱。

### 2.2 编排 DAG
```
N1 扫描 → N2 签名识别 ─┬─(高置信)──────────────→ N3 参数求解 → N4 解包 → N5 产物校验
                       └─(多义/零命中)→ [A1] ─┘                              │
                                                                             ▼
N11 启动验证 ← N10 回写 ← N9 翻译 ← N8 结构化 ← N7 文本提取 ← N6 资源解码 ←──┘
```

### 2.3 AI 介入节点
| 节点 | 任务 | 输入 | 输出（强 schema） | 为什么适合 AI |
|---|---|---|---|---|
| **A1** | **多义/未知格式判别** | 前 4KB hexdump + `strings` + 目录清单 + **签名表 RAG Top-K** | `{format, decoder, confidence, reason}` | 签名表约 1000 条且高度相似，LLM+检索比手写规则更耐长尾 |
| **A2** | **参数/插件求解** | 游戏标题、厂商、文件名 | `{plugin: <枚举值>}` | **只能从合法 plugin 白名单里选**，不允许自由生成 |
| **A3** | **报错分诊重试** | stderr+exit code+已试策略 | `{next_action, params}` | 把非结构化报错映射到有限策略集 |
| **A4** | **未知归档解析器生成** | hexdump+大小 | Python 解析脚本 | 价值最高、风险最高，**必须沙箱**（2.6） |
| **A5** | **脚本文本抽取规则生成** | 脚本样本 | 正则/状态机+自测 | 用「可打印字符比例/含假名」自动验收 |
| **A6** | 翻译+术语表 | 结构化文本 | 译文 | 成熟用法 |
| **A7** | QA 评分 | 原文/译文对 | 0–100 | 确定性指标+LLM 语义评分 |

### 2.4 兜底阶梯（L0–L5）—— 本方案核心
| 级别 | 触发 | 动作 | 调 LLM |
|---|---|---|---|
| **L0** | 签名精确唯一命中 | 直接调用对应 decoder | **否**（主路径，成本≈0） |
| **L1** | 多义命中 | A1 排序候选→依序试，用验收判据择优 | 是 |
| **L2** | 零命中 | 通用手段(binwalk/7z/熵分析) → 仍失败则 A4 生成解析器 | 是 |
| **L3** | 命中但报错（加密/缺 key） | 查内置已知密钥库 → 失败标记「需人工」 | 是 |
| **L4** | 归档层彻底失败 | **绕开归档**：运行时文本钩子 / OCR 覆盖层 | 否 |
| **L5** | 全部失败 | 生成「逆向任务单」交人工，并**入库** | 是 |

**L4 的价值**：归档打不开时，成熟方案不是继续啃归档，而是**换维度**——运行时直接从内存/绘图调用抓文本，**完全跳过 S2–S6**。已核实实现见 3.2。注意其局限：KiriKiri 运行时方案（`KrkrzExtract` README 原文）*"Extracting all resources requires playing through the entire game… Resources unused during gameplay cannot be extracted."* ——**只提取，且只能拿到玩到的部分**。

### 2.5 验收 oracle（决定闭环成败）
- **归档层**：产出文件数>0；条目偏移**单调递增且不越界**；大小之和与归档总大小比例合理。
- **图片**：Pillow 能打开且尺寸合理（非 1×1、非 65535×65535）。
- **音频**：头魔数正确、可解出时长。
- **文本**：可打印字符+假名比例超阈值；重复行比例低；行数>0。
- **回写**：游戏能启动且存活 N 秒；截图无 tofu 方块。
- **反例**：全 0 字节 / 全乱码 / 偏移校验失败 → 判失败并回退。

### 2.6 A4 的安全边界（必须写进规格）
- 在**独立低权限子进程**运行生成的代码：无网络、只读挂载目标文件、CPU/内存/时间硬上限。
- 生成代码**只允许读文件并打印结构化结果**，禁止写/删/网络。
- 这是全系统唯一「执行 LLM 生成代码」处，也是唯一必需的沙箱点。

### 2.7 自愈闭环（把 AI 成本逐步降到 0）
每次成功/失败写入**案例库**：`(格式签名哈希, 目录特征) → (decoder, plugin/key, 备注)`
下次同类文件**直接命中 L0，完全跳过 LLM**。这是长期成本模型的关键。

### 2.8 明确「AI 不该做」
- ❌ 采信 LLM 输出的二进制偏移/长度。
- ❌ 让 LLM 决定是否覆盖/删除用户文件（回写前**强制自动备份**）。
- ❌ 无界重试。
- ❌ 用 LLM 重写签名匹配这类确定性逻辑（不可复现、更慢更贵更容易错）。

---

## 3. GitHub 可复用项目

### 3.1 通用解包器与回写工具

| 项目 | 用途/适用引擎 | 语言 | 许可证 | 维护状态 |
|---|---|---|---|---|
| **[morkt/GARbro](https://github.com/morkt/GARbro)** ★首选 | VN 资源浏览器。约 1000 签名：KiriKiri `.xp3`/`.tlg`、BGI/Ethornell、NScripter `.nsa`、Ren'Py `.rpa`、Majiro、YU-RIS、CatSystem2、Nitro+、Alice Soft、Shiina Rio、Artemis 等。**含 `Console/`（GARbro.Console）CLI** | C# | **MIT** | 3,327★，**未归档**，master 最后提交 2023-10-27，`pushed_at` 2024-07-08 → 低速维护 |
| **[vn-tools/arc_unpacker](https://github.com/vn-tools/arc_unpacker)** | CLI 提取图片/音频/音乐。**自动猜测格式**（XP3 `--dec=krkr/xp3 --plugin=...`） | C++ | **GPL-3.0** | 670★，**已归档 2022-04-25** |
| **[xmoezzz/KrkrExtract](https://github.com/xmoezzz/KrkrExtract)** | *"extract and pack krkr2 and krkrz's xp3 files"* —— **能解包也能打包** | C++ | ⚠️ README 声明 **GPLv3**，但 API `license=null`（**许可证冲突，未核实**） | 1,426★，**已归档**，README 自带 "Not Under Maintain"，`pushed_at` 2022-01-01 |
| **[xmoezzz/KrkrzExtract](https://github.com/xmoezzz/KrkrzExtract)** | *"The next generation of KrkrExtract"*。仅 krkrz | C | **GPL-3.0** | 267★，**未归档**，`pushed_at` 2026-08-25。README 警告 *"Beta version, unstable now (a decade)."* |
| **[xmoezzz/xp3-brute](https://github.com/xmoezzz/xp3-brute)** | *"unpack, pack, and modify Kirikiri (krkr) XP3 archives"*，**无需运行游戏**（Win32 模拟+符号执行+暴力） | Rust | ⚠️ **无明确许可证**（`license=null`） | 45★，创建 2026-08-20，`pushed_at` 2026-10-09，**新** |
| **[arcusmaximus/VNTranslationTools](https://github.com/arcusmaximus/VNTranslationTools)** ★文本回写首选 | **含 VNTextPatch**。*"extracting original text from, and patching translated text into, a variety of visual novel formats."* 支持 **21 种引擎**：Kirikiri `.ks/.scn`、RealLive、Majiro、CatSystem2、Artemis、Ren'Py `.rpy`、BGI/Ethornell、YU-RIS、AdvHD、KaGuYa、Silky's/AI6WIN、SystemNNN、Whale、Qlie 等 | C# | **MIT** | 424★，**已归档** 2023-02-20。**仅文本**，不导出图片/音频 |
| **[arcusmaximus/KirikiriTools](https://github.com/arcusmaximus/KirikiriTools)** | KiriKiri 引擎工具集 | C++ | **MIT** | 434★，**已归档** 2023-04-12 |
| **[Lattyware/unrpa](https://github.com/Lattyware/unrpa)** | Ren'Py RPA 解包 | Python | **GPL-3.0** | 766★，`pushed_at` 2022-06-27 |
| **[shizmob/rpatool](https://github.com/shizmob/rpatool)** | Ren'Py 封包 | Python | **WTFPL** | **已归档**，已迁至 codeberg |
| **[uuksu/RPGMakerDecrypter](https://github.com/uuksu/RPGMakerDecrypter)** | RPG Maker XP/VX/VX Ace 加密档、MV/MZ 加密文件 | C# | **MIT** | 333★，`pushed_at` 2024-12-30 |
| **[trigger-segfault/TriggersTools.CatSystem2](https://github.com/trigger-segfault/TriggersTools.CatSystem2)** | CatSystem2 引擎提取库 | C# | **MIT** | 78★，`pushed_at` 2019-03-28（久未更新） |
| **[UlyssesWu/FreeMote](https://github.com/UlyssesWu/FreeMote)** | E-mote/PSB（`.psb/.psz/.pimg/.scn/.mmo/.mtn/.dpak`）；TLG 经 `FreeMote.Tlg`；`PsbDecompile`/`PsBuild` 可回编译 | C# | ⚠️ **CC BY-NC-SA 4.0 — 禁止商业使用**（API `NOASSERTION`） | 521★，**活跃**，`pushed_at` 2026-10-06 |

### 3.2 运行时文本提取（对应 L4 兜底）
| 项目 | 用途 | 许可证 | 状态 |
|---|---|---|---|
| **[Artikash/Textractor](https://github.com/Artikash/Textractor)** | x86/x64 **文本钩子**（Windows 7+），自动 hook 大量引擎，支持 AGTH code。原理：host 注入 `texthook`，pipe 通信，在 `TextOut`/`GetGlyphOutline` 注入指令截获文本 | **GPL-3.0** | 2,705★，`archived:false` 但 master 最后提交 **2023-08-26** → **事实休眠**；且**已被官方指定由 LunaTranslator 接替** |
| **[bbepis/XUnity.AutoTranslator](https://github.com/bbepis/XUnity.AutoTranslator)** | **Unity 专用**运行时文本 hook（ReiPatcher/BepInEx），非解包 | **MIT** | 3,454★，`pushed_at` 2026-10-11，**活跃**。⚠️ GameStringer 的 Unity 路线就是自动装 BepInEx + 此工具 |
| **[HIllya51/LunaTranslator](https://github.com/HIllya51/LunaTranslator)** | HOOK 为主（自述*"几乎适配了所有常见和冷门的视觉小说"*）+ 内嵌翻译 + 内置 OCR + HOOK 模拟器（NS/PSP/PSV/PS2）+ 几乎所有翻译引擎（含 LLM） | **GPL-3.0** | **13.7k★**，1.2k forks，非常活跃 |

> **LunaTranslator 的价值在于架构同构**：它的「HOOK 为主 + OCR 兜底 + 内嵌翻译」三路策略与 2.4 的 L4 设计完全一致——说明这个兜底思路是被大规模实践验证过的。**但不要抄代码（GPL）**。

### 3.3 Unity / 其它引擎专用
| 项目 | 用途 | 许可证 | 状态 |
|---|---|---|---|
| **[K0lb3/UnityPy](https://github.com/K0lb3/UnityPy)** ★最易内嵌 | Python 解包并**可编辑** Unity 资源（`obj.patch()`/`env.file.save()`），基于 AssetStudio | **MIT** | 810 commits，**活跃**，`pushed_at` 2026-10-05 |
| **[AssetRipper/AssetRipper](https://github.com/AssetRipper/AssetRipper)** | Unity `3.5.0`–`6000.4.X`，导出为原生 Unity 工程。另有闭源付费 Premium | **GPL-3.0** | 8.6k★，**活跃** `pushed_at` 2026-10-09 |
| **[aelurum/AssetStudioMod](https://github.com/aelurum/AssetStudioMod)** | `Perfare/AssetStudio` 的活跃 fork（原版 Unity 3.4–2022.1，**已归档 2023-01-21**） | **MIT** | 2,118★，`pushed_at` 2025-10-15 |
| **[abunomaru/VNTools](https://github.com/abunomaru/VNTools)** | System-NNN 家族（PIL/SLASH 系） | **[未核实]** | **[未核实]** |

### 3.4 完整先例与知识库

**13) [rouges78/GameStringer](https://github.com/rouges78/GameStringer)** ★ 与你的项目重合度极高
- **用途**：桌面应用，**自动识别引擎 → 提取文本 → 本地/云端 AI 翻译 → 回写补丁**，自述 20+ 引擎、20+ AI 提供商、11 种 UI 语言。
- **覆盖**：Unity、Unreal（`.locres`/`_P.pak`）、Godot、RPG Maker(MV/MZ/VX/Ace/XP)、Ren'Py、GameMaker、Telltale、Wolf RPG、**KiriKiri**、TyranoScript、Electron、Bethesda、CRI、Visionaire、Danganronpa。
- **三路策略（直接可借鉴）**：文件级 patcher / 运行时注入（BepInEx+XUnity.AutoTranslator）/ 屏幕 OCR。
- **状态**：125★，**最后更新 1 小时前（非常活跃）**，1,221 commits，个人项目。
- **许可证**：⚠️ **自定义 "GameStringer Source Available License" v1.1（2026-01）—— 不是开源许可证。**
  - 禁止：商业使用、销售/再分发、**创建竞争性商业产品**、SaaS；商用需另行授权。
- **复用方式**：**只可作为架构与产品形态参照，不可复制代码**。
- **它验证了什么**：整条链路（含回写、OCR 兜底、难度评估、补丁分发）可工程化。且它**自愿公开了短板**：*"It already recognizes 20+ engines (12 with a dedicated parser), but real games are messy"* → **长尾引擎覆盖才是护城河，AI 编排只是手段**。
- **它踩过的坑（可直接抄经验）**：DLL 注入引发杀软误报（仓库有 `docs/ANTIVIRUS.md`）；字体缺字形显示 tofu 方块（需自动换 Noto 字体）；引擎更新后补丁失效（需更新追踪）；编码与控制码必须保证游戏内标签/变量不被破坏。

**14) [shushui0710/STool](https://github.com/shushui0710/STool)** ★ 唯一「自动识别引擎 → 自动分派」的现成编排器
- **用途原文**：*"多引擎 Galgame / 视觉小说一站式工具箱（Rust）— 解包/封包/汉化文本提取回填/存档编辑/MOD 管理"*。Tauri v2 GUI + `stool-cli.exe`（仅 Windows x64）。
- **关键命令（README 原文）**：
  - `stool-cli detect <游戏目录>` — *"判断这个游戏是用什么引擎做的（会给出判断依据和置信度）"*
  - `stool-cli extract <游戏目录> -o 输出目录` — *"自动识别引擎；-p 可手动指定引擎"*
  - `stool-cli batch <根目录> --op detect|extract --csv 报告.csv` — 批量扫描并生成引擎 CSV 报告
- **机制**：`engines/recognize.rs` **证据打分**——*"命中的特征越多，分数越高，超过 60 分判定为该引擎"*。分派：内置插件直接处理，外部转交 unrpyc / WolfDec / AssetRipper / GARbro / GDRE Tools（自官方 Release 下载并校验 SHA-256）。
- **支持引擎（自述）**：Ren'Py、RPG Maker MV/MZ/XP/VX/Ace、KiriKiri、Artemis、Godot、SACT/System40、NScripter/ONScripter、HTML/Electron、Wolf RPG、Unity（借 AssetRipper）。
- **许可证**：**MIT**。
- **状态**：⚠️ **创建 2026-09-08，`pushed_at` 2026-10-01，仅 1 star，6 open issues，无任何第三方验证**。README 自述 355 项测试通过（**自述，未独立核实**）。
- **复用建议**：**架构参照价值高于代码复用价值**。「证据打分 + 阈值判定 + 插件分派 + 外部工具兜底」这套设计**与 2.4 的 L0→L1→L2 阶梯几乎同构**，可直接作为你的编排骨架蓝本。但其能力和稳定性未经社区验证，**不要直接依赖**。

**15) [2439905184/Galgame-Engine-Collect](https://github.com/2439905184/Galgame-Engine-Collect) (galWiki)**
- **用途**：*"关于视觉小说的一切，争取打造全网最全的资料库"*，是**资料索引/百科，不是解包程序**。README 链接 `unpack.md`（解包工具表格）、`table.md`（引擎表格大全）、`tools.md`。
- **适用**：**A1/A2 的 RAG 语料首选** —— 引擎→格式→工具映射就是本项目的知识底座。
- **许可证**：`NOASSERTION`（**[未核实]** 具体条款）。**状态**：672★，`pushed_at` 2026-06-21。`unpack.md` 内容 **[未核实]**。

**16) [VelocityRa/awesome-game-file-format-reversing](https://github.com/VelocityRa/awesome-game-file-format-reversing)**
- **用途**：游戏文件格式逆向资源索引（含 Archive Extractors、Translation & Localization、Engines 分类）。
- **适用**：长尾格式的检索入口。**许可证：CC0-1.0**（可自由使用）。222★。

### 3.5 其它经核实候选
- **[hiroshil/asmodean-tools](https://github.com/hiroshil/asmodean-tools)**（51★，`license=null`）：镜像描述原文 *"These software may not be redistributed, modified or used in other software without the author's permission."* → **实际为「须经作者许可」，非开源**。asmodean 官方站 `asmodean.reverse.net` DNS 解析失败，**现状未核实**。
- **[Inori/FuckGalEngine](https://github.com/Inori/FuckGalEngine)**：*"My tools to crack galgame"*，C，**无许可证**，1,019★，`pushed_at` 2022-02-06。引擎覆盖 **未核实**。**无许可证 + "crack" 定位 → 商业项目中风险最高，建议完全避开。**
- **[Weiss-UltimateSavior/Tyranor-Next](https://github.com/Weiss-UltimateSavior/Tyranor-Next)**：**GPL-2.0**，616★，Android 多引擎聚合**启动器**（内置 KiriKiri/ONScripter/Tyrano/Artemis/Siglus/FVP 运行环境）。**能识别引擎但不能解包**。
- **[M1zukiri/Gal-Extractor](https://github.com/M1zukiri/Gal-Extractor)**：*"用于解包Galgame资源的应用"*，C#，**无许可证**，**0★**，2026-06-23。成熟度 **未核实**。
- **[capacitor1/ImageGlass-G00-Plugin](https://github.com/capacitor1/ImageGlass-G00-Plugin)**：RealLive G00 编解码插件，**MIT**。注意：**是看图器插件，不是解包器**。

### 3.6 关键结论：有没有「自动识别引擎」的现成项目？

**有两个，但都不是 AI 驱动，且都不成熟：**
1. **`shushui0710/STool`** —— 唯一有 `detect`（带置信度）+ `extract`（自动识别）+ `batch`（CSV 报告）的编排器，证据打分>60 分判定。**但仅 1★、创建 11 天、无第三方验证。**
2. **`rouges78/GameStringer`** —— 完整产品级先例，**但非开源、禁商用**。

**其它工具的定位差异（重要，别混淆）**：
- `arc_unpacker` 与 GARbro 是**逐文件嗅探**（*"guess the format"* / 按 Enter 尝试打开），**不会先判定「这是哪个引擎的游戏」再分派**。
- `Tyranor-Next` 能识别引擎，但目的是**运行**而非解包。

**未发现任何「让 LLM 直接解析游戏归档」的项目。** 但**发现了更重要的东西**：既有的解包器已经开始**主动把自己暴露给 AI Agent**（见 3.9），而通用 Agent 逆向工程已经是一个巨型赛道。**这直接决定了本项目的正确形态**（见 3.9 的结论）。

---

### 3.7 翻译与本地化工具链（S8 的相关资产）

| 项目 | 用途 | 许可证 | 状态 |
|---|---|---|---|
| **[GalTransl/GalTransl](https://github.com/GalTransl/GalTransl)** ★ | *"支持GPT/Claude/Deepseek/Sakura等大语言模型的Galgame自动化翻译解决方案"* —— 专为 VN 脚本设计的 LLM 批量翻译 | **GPL-3.0** | 2,322★，`pushed_at` 2026-10-11，**活跃** |
| **[NEKOparapa/AiNiee](https://github.com/NEKOparapa/AiNiee)**（上游）／ [SakuraLLM/AiNiee-chatgpt](https://github.com/SakuraLLM/AiNiee-chatgpt)（fork） | 面向 MTool/Translator++ 导出文件的 AI 批量翻译：术语表、替换字典、提示词工程、**语义检查（相似度低自动重译）**、文本清洗 | **[未核实]** | fork 页标 675 commits |
| **[dreamsavior/TranslatorPlusPlus](https://github.com/dreamsavior/TranslatorPlusPlus)** ⚠️ | 游戏本地化 CAT 框架。**解包+回注入**，引擎覆盖极广：RPG Maker 全系、Wolf RPG、Ren'Py、TyranoScript、Unity(Mono/IL2CPP)、Unreal、Godot、GameMaker、**KiriKiri/KAG**、Artemis、NScripter、YU-RIS、CatSystem2、Qlie、SystemNNN、LiveMaker、Ethornell、Light.vn。**自带 REST API + MCP 端点**（见 3.9） | ⚠️ **冲突**：README 与 API 均称 **GPL-3.0**，但**仓库只有 `docs/`+`images/`+`LICENSE`+`README.md`**（5 commits、**0★**、`language: null`），实际程序是**加了密码的便携包**（官网 https://dreamsavior.net/download/ ，解压密码 `Dreamsavior`）。**未找到应用源码仓库 → 不可写作「开源」** | `pushed_at` 2026-10-02；真正的分发/社区在官网/Patreon/Discord，**不要用该仓库星数判断项目健康度** |
| **MTool** | 拖拽式游戏翻译/修改工具（PC+Android），引擎覆盖广（RPG Maker 全系、Wolf RPG、TyranoBuilder、**KiriKiri 2/Z**、Ren'Py、VNMaker、SRPG Studio 等），宣称全离线 | ⚠️ **闭源**：官网 https://mtool.app/ 只有下载+订阅，**未找到任何公开源码仓库** → 视为专有软件 | 活跃维护 |
| **[WWWee80/MTool-Translator](https://github.com/WWWee80/MTool-Translator)** | MTool JSON 批量翻译（12+ 引擎） | ⚠️ **无许可证** | 51★，`pushed_at` 2026-09-10 |
| **Sugoi Toolkit** | 离线日→英翻译（CNN，用大量 VN 语料训练） | ⚠️ **[未核实]**：原作者仓库 `leminhyen2/Sugoi-Japanese-Translator` **返回 404**；现商业站 https://sugoitoolkit.com/ 为纯 JS 渲染，条款无法提取。已核实的 MIT 代码（`dreamsavior/sugoi-translator-server`、`sugoitrans-legacy`）均为 **2022 年第三方打包**，非模型本身；**模型的可再分发许可未核实** | 原仓库已死 |

### 3.8 AI 工作流框架（能否内嵌进桌面软件）

许可证取自 GitHub API `spdx_id`；**「可打包性」是工程判断，非抓取事实**。

| 框架 | 许可证 | 可离线 | 能否内嵌进发布的 Windows 程序（无需用户跑服务）|
|---|---|---|---|
| **[ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)** ★最合适 | **MIT** | 是 | **[判断] 是** —— 构建出 `libllama`/`ggml` **C/C++ 库**，库路径**不需要服务进程**，可被直接链接/加载。130,920★ |
| **[langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)** | **MIT** | 是 | **[判断] 是** —— 纯 Python 库，可被 PyInstaller/Nuitka 冻结。43,135★ |
| **[crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)** | **MIT** | 是 | **[判断] 是** —— Python 库。59,600★ |
| **[langchain-ai/langchain](https://github.com/langchain-ai/langchain)** | **MIT** | 是 | **[判断] 是** —— 库。147,685★ |
| **[microsoft/autogen](https://github.com/microsoft/autogen)** | ⚠️ **拆开看**：API 报 `CC-BY-4.0`（那是根 `LICENSE`，覆盖**文档**）；**代码**在 `LICENSE-CODE` = **MIT** | 是 | **[判断] 是**（用 MIT 代码许可）。本组中最不活跃：`pushed_at` 2026-04-15。61,370★ |
| **[ollama/ollama](https://github.com/ollama/ollama)** | **MIT** | 是 | **[判断] 部分** —— 可分发单文件二进制，但其常态是**监听 127.0.0.1:11434 的本地 HTTP 服务**。你的程序可把它作为子进程拉起，但用户技术上仍在跑本地服务；它**不是可链接的推理库**。182,852★ |
| **[vllm-project/vllm](https://github.com/vllm-project/vllm)** | **Apache-2.0** | 是 | **[判断] 否（消费级桌面）** —— 基于 PyTorch/CUDA 的 GPU 服务引擎，以 HTTP 服务运行，需重型 Python 栈。93,636★ |
| **[langgenius/dify](https://github.com/langgenius/dify)** | ⚠️ **NOASSERTION**（自定义 Apache-2.0 衍生；**条款细节未核实**） | 可自托管 | **[判断] 否** —— Web 平台而非可嵌入库，需 Postgres/Redis/向量库多容器栈。158,238★ |
| **[n8n-io/n8n](https://github.com/n8n-io/n8n)** | ❌ **Sustainable Use License v1.0**（非开源） | 可自托管 | **[判断] 否（商业产品禁用）** —— 且是 Node 服务而非库。207,088★ |
| **[FlowiseAI/Flowise](https://github.com/FlowiseAI/Flowise)** | ⚠️ **NOASSERTION** | — | ❌ **不要选用：项目已日落。** API `archived: true`；README 写明 *"Flowise has been archived."*；官方页 https://flowiseai.com/sunset 写明 **August 10, 2026 仓库归档**，issues/PR 将锁定，npm 与 Docker 镜像将标记废弃 |

> **框架选型结论**：要**内嵌进桌面软件**，只有「库」形态可用 → **llama.cpp（本地推理）+ LangGraph 或 crewAI（编排，MIT）** 是合规且可打包的组合。
> ❌ **避开**：n8n（许可禁止商业分发）、Flowise（已日落）、Dify/vLLM（服务栈形态，不适合消费级桌面内嵌）。
> ✅ **已核实修正**：`ggerganov/llama.cpp` 已迁移，**正确路径是 [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp)**（API 返回 repo id 612354784，与 `ggml-org` 一致）。

### 3.9 AI 驱动的逆向工程 —— 以及本项目的正确形态

**通用 Agent 逆向工程已是巨型赛道（均已核实）：**

| 项目 | 用途 | 许可证 | 状态 |
|---|---|---|---|
| **[morluto/rea](https://github.com/morluto/rea)** ⭐ | *"**Reverse engineer anything with agents, from app behavior down to native binaries.**"* 主题含 `ai-agents`、`ghidra`、`mcp`、`binary-analysis`、**`dsh-plugin`** | **MIT** | TypeScript，**136,846★ / 30,821 forks**，创建 2026-04-14，`pushed_at` 2026-10-12，`fork:false`（上游） |
| **[LaurieWired/GhidraMCP](https://github.com/LaurieWired/GhidraMCP)** | MCP Server for Ghidra，把反编译器暴露给 LLM Agent | **Apache-2.0** | 11,101★，`pushed_at` 2026-10-10 |
| **[cyberkaida/reverse-engineering-assistant](https://github.com/cyberkaida/reverse-engineering-assistant) (ReVa)** | Ghidra 内的模型无关 AI 助手。README：*"uses a tool driven approach with a focus on designing tools for effective LLM use"* | **Apache-2.0** | 869★，`pushed_at` 2026-10-07 |
| **[mrphrazer/reverser_ai](https://github.com/mrphrazer/reverser_ai)** | *"automated reverse engineering assistance through the use of **local LLMs on consumer hardware**"* | **GPL-2.0** | 1,155★ |

**两个决定性发现：**

1. **`dreamsavior`（Translator++ 作者）已经 fork 了 `rea`** —— <https://github.com/dreamsavior/rea>（`fork: true`，创建 2026-10-07）。**游戏本地化工具的作者已经在做 Agent 化逆向**，方向已被业内验证。
2. **Translator++ 主动暴露了 MCP 端点**（README 原文）：*"**Model Context Protocol (MCP): Connect your favorite AI agents (like Claude Desktop, Cursor, or local orchestrators) directly to the running application via `/mcp`**"*，另有 REST API（`GET /api/tools`、`POST /api/call`、`POST /api/exec`）与内置 JS CodeRunner。

> ### ⭐ 由此得出本项目的**正确形态**
>
> 现有实践给出的模式是：**「让 AI 通过 MCP/REST 驱动一个确定性的解包器」，而不是「让 LLM 自己去解析二进制」。**
>
> 这与 2.1 的原则 2（LLM 不做字节级解析）**完全一致，并且已经被工业界验证**：
> - Translator++ = 确定性解包 + **MCP 暴露** → Agent 调用
> - GameStringer = 确定性管线 + LLM 只负责**翻译与决策**
> - `rea`/GhidraMCP/ReVa = **把分析能力封装成工具**再交给 LLM（ReVa 原话：*"a tool driven approach with a focus on designing tools for effective LLM use"*）
>
> **落地建议**：把你自己的解包编排器也**暴露成 MCP Server + CLI**。这样：
> - 你的 AI 层可以用**任意** Agent 框架（LangGraph/crewAI）或现成客户端（Claude Desktop、Cursor）驱动；
> - 别人也能复用你的能力，形成生态；
> - 确定性逻辑与 AI 逻辑彻底解耦，可独立测试、独立替换。
>
> **⚠️ 但注意**：`rea` 在主题里带 **`dsh-plugin`** 标签（DSH 即本 harness）。若你打算与本平台集成，需自行确认其集成方式。

---

## 4. Windows 打包方案

### 4.1 架构选型
| 方案 | 适用 | 优点 | 代价 |
|---|---|---|---|
| **A. Python + PyInstaller(onedir) + 外部工具 exe** | 团队熟悉 Python（本文假设） | AI 生态最全，开发最快 | 体积大、杀软误报、PyInstaller 坑多（4.4） |
| **B. Tauri v2（Rust+Web）** | 追求小体积/原生 | **有两个成功先例**：GameStringer（Tauri v1→v2）、STool（Tauri v2）；包小启动快 | Rust 学习曲线；解析逻辑要重写 |
| **C. Electron** | 前端团队 | 生态成熟 | 体积最大（100MB+） |

**建议：A 起步，接口按 B 预留**（解析/解包做成独立可执行模块，未来可换 Rust）。这同时解决许可证隔离（4.3）。

### 4.2 构建产物
> 版本参考（官方文档核实）：**PyInstaller 6.22.3**（2026-09-12；要求 Python `>=3.8,<3.16`；**不是交叉编译器**——*"to make a Windows app you run PyInstaller on Windows"*）。
> ⚠️ **Nuitka 4.3 的免费版不是 Apache-2.0，而是 AGPL-3.0**（官方手册原文：*"Nuitka is licensed under the GNU Affero General Public License, Version 3"*，附 `LICENSE-RUNTIME.txt` 运行时例外）。**AGPL 对闭源商业产品是高危许可，选 Nuitka 前必须亲自核对发行包内的 `LICENSE.txt` / `LICENSE-RUNTIME.txt`。**（商业版 €250–1000/年）

- **用 `--onedir`，不要 `--onefile`。** 官方文档原文：onefile *"creates a temporary folder... named `_MEIxxxxxx`"*，每次启动都要解压（*"a little slower to start"*），且 *"running multiple copies is expensive in disk space because nothing is shared"*、*"The `_MEIxxxxxx` folder is not removed if the program crashes or is killed"*。
- ⚠️ **onefile + 管理员权限是禁止组合**：官方明确警告，临时目录中的共享库可能被低权限进程篡改而**导致提权**。若程序需要提权，**必须用 onedir**。
- 单文件安装需求交给**安装器**（Inno Setup / NSIS / WiX-MSIX）满足，而不是 PyInstaller。
- 推荐：**PyInstaller onedir → Inno Setup 单文件安装器**。

### 4.3 外部工具集成（顺带解决许可证）
把 GARbro.Console / arc_unpacker / KrkrExtract / VNTranslationTools 等**以独立 exe 放在 `resources/bin/`，用 `subprocess`+argv 数组调用**：
1. **许可证隔离**：独立进程调用通常被视为「聚合」而非「衍生作品」（见 5.2，**有 GPL 原文与 FSF FAQ 支撑，但仍非法律定论**）。
2. **语言异构**：C#/C++/Rust 工具不必重编译。
3. **可替换**：某工具失效时换单文件即可。
4. ⚠️ 正式分发仍须随包提供 GPL 组件的对应源码与许可证文本（**这一条「独立进程」并不能豁免**，见 5.2）。

> ⚠️ **本方案有一个官方记载的坑，必须提前处理**（PyInstaller 文档 *Common Issues and Pitfalls*）：
> 冻结后的程序会修改库搜索路径，且**这些修改会被它启动的子进程继承**——原文：*"changes made to the frozen application's run-time environment are also inherited by subprocesses launched by the frozen application"*。
> 后果：从冻结程序里 `subprocess.run()` 调用外部 exe（尤其 C/C++ 工具）**可能因 DLL 加载冲突而失败**，而源码运行时完全正常。
> **对策**：调用外部工具前还原环境——Windows 上用 `ctypes.windll.kernel32.SetDllDirectoryW(None)`，并清理 `PATH` 中与 `sys._MEIPASS` 相关的项。
> **这条直接把「冻结程序 + 外部 CLI 工具」列为阶段 1 必须先验证的高风险项。**

### 4.4 依赖处理与已知坑点（PyInstaller 路线）
| 坑点 | 表现 | 对策 |
|---|---|---|
| **hidden imports** | 官方原文点名触发条件：*"`__import__()`, `importlib.import_module()` or perhaps `exec()` or `eval()`"*；后果 *"There will be no warnings, only an ImportError at run-time."* | 用 `--debug=imports` 排查；改显式 import 注册表；或 `--hidden-import`/spec/hook。**注意：缺失模块只写进 `build/<name>/warn-<name>.txt`，不报错——务必检查该文件** |
| **`multiprocessing`** | 未调 `freeze_support()` 会在 Windows 上陷入 *"endless spawn loop"* | `if __name__ == "__main__": multiprocessing.freeze_support()` |
| **原生 DLL** | VC++ 运行库、OpenSSL、libtlg 缺失 | `--add-binary`、`--collect-binaries`、`--collect-all`；运行时 `os.add_dll_directory()` |
| **大模型文件** | ⚠️ **官方没有大文件专门指引或容量上限说明**（[未核实]）。机制性事实：onefile 会压缩嵌入并在每次启动解压 → **启动解压 + 磁盘占用翻倍 + 崩溃后残留**三重代价；可用 `--runtime-tmpdir` 指定解压位置 | **不内置**：首启按需下载+SHA256 校验；或调用本地 Ollama / 云 API。官方另一条硬建议：*"Before you attempt to bundle to one file, make sure your app works correctly when bundled to one folder"* |
| **ONNX Runtime / llama-cpp-python** | wheel 需匹配 Python 版本与 CPU 指令集(AVX) | 锁版本矩阵；提供 CPU 回退分支 |
| **非 ASCII / 长路径** | 中文用户名、深层目录失败；onedir 产物必须在支持符号链接的文件系统上生成/移动/打包 | 全程 `pathlib`；避免 ANSI API |
| **.NET Framework 依赖** | GARbro 需 4.6+；VNTranslationTools 系 C# | Win10 1809+ 通常自带；旧系统需检测提示 |
| **更新机制** | 用户长期用旧版 | Tauri Updater（带签名）/WinSparkle/Squirrel |

### 4.5 杀软与 SmartScreen（必然遇到，非可选项）
- **根因**：DLL 注入（BepInEx / texthook）本身就是启发式扫描重点怀疑对象；新版本 SmartScreen 信誉为零。
- **缓解**：① **买代码签名证书**（EV 对信誉提升最明显）；② 提供**便携版 zip** 备用渠道；③ 提供哈希/签名校验与误报申诉说明；④ 参照 GameStringer `docs/ANTIVIRUS.md` 的主动说明做法。
- **设计层面**：把「需注入的功能」做成**可选项**，默认走纯文件级解包，能显著缩小误报面。
- ⚠️ **来源说明**：本节结论来自**社区实践 + GameStringer 的公开文档**，**不是 PyInstaller 官方说明**——已核对 PyInstaller 的 *Common Issues and Pitfalls* 与 *When Things Go Wrong* 两页，**均无 antivirus / false positive 章节**。请勿把本节当作官方保证。

### 4.6 权限
游戏装在 `Program Files` 下时回写需管理员。建议默认不提权，仅在必要时 UAC manifest 提权；**回写前强制自动备份**（GameStringer 亦如此）。⚠️ 结合 4.2：**需要提权就必须用 onedir**。

### 4.7 打包/安装器工具的许可证（已核实）

| 工具 | 版本 | 许可证 | 对你的含义 |
|---|---|---|---|
| **PyInstaller** | 6.22.3 | **GPL-2.0+ 带例外** | ✅ **官方原文：*"You may use PyInstaller to bundle commercial applications out of your source code."*** 生成的 bundle 可**任意许可**发布，**无需**附带 PyInstaller 的许可证或致谢。仅**修改 PyInstaller 自身源码**才落入 GPL。**商用最省心** |
| **Nuitka（免费版）** | 4.3 | ⚠️ **AGPL-3.0** + 运行时例外 | ❌ 对闭源产品高危，**必须自行核对发行包内 `LICENSE.txt`/`LICENSE-RUNTIME.txt`** |
| **cx_Freeze** | 8.7.1 | （宽松，**[未核实]**具体） | ⚠️ Windows **不支持单人文件**（官方：*"On other systems, this is not supported by cx_Freeze"*，建议 `bdist_msi` 或 IExpress/7zip sfx）；MSVC 运行时**默认不拷贝**，需自负许可责任或要求用户装 VC++ Redist；会把自身许可证文件塞进产物且**要求随产物附带** |
| **py2exe** | 0.14.2.0 | **MIT + MPL-2.0** | ⚠️ 单人文件**已弃用**（*"Deprecate `bundle_files<3`"*，下一大版本移除）；仅 Windows；官方站 py2exe.org 仍是 2020 年旧 wiki |
| **Briefcase (BeeWare)** | 0.4.5 | （宽松，**[未核实]**具体） | 需 Python ≥3.11；**不产出单人 exe**，Windows 走 WiX→MSI 或 ZIP；**Tkinter 不可用**（用 Embeddable 包，缺标准库模块）；MSI 卸载有注册表残留陷阱；版本号必须是严格整数三元组 |
| **Inno Setup** | 7.1.0（2026-08-12） | **宽松式**：*"Permission is granted to anyone to use this software for any purpose, **including commercial applications**"* | ✅ **推荐**。官网仅 *"requested"* 商业用户购买许可（**非强制**） |
| **NSIS** | （版本号 [未核实]） | **zlib/libpng**（压缩模块除外）；LZMA 模块为 CPL-1.0 **但附特例**：明确允许静态/动态链接而不污染你的代码 | ✅ 可用 |
| **WiX Toolset** | 7.0.0（2026-04-06） | MS-RL（自文档镜像，**[未核实]** v7 仓库原文） | ⚠️ 官方明确 **v3/v4/v5 已退出社区支持** |
| **MSIX** | — | 平台规范 | 官方原文：*"All MSIX packages must be signed before installation."* 结构含 `AppxManifest.xml`/`AppxBlockMap.xml`（每 64KB 块哈希）/`AppxSignature.p7x`；容器化虚拟文件系统与注册表；*"guarantees a clean uninstall with no leftover files or registry entries"*；持续更新只下变化的 64KB 块 |

> **选型结论**：**PyInstaller（许可最友好）+ Inno Setup 或 NSIS** 是商业闭源产品的最稳组合。
> ❌ **避开 Nuitka 免费版**（AGPL），除非核对运行时例外后确认可用或购买商业授权。

---

## 5. 许可证与法律风险（**非法律意见**）

### 5.1 许可证总表（按商业闭源分发评估）
| 组件 | 许可证 | 商业/闭源分发含义 |
|---|---|---|
| GARbro | **MIT** | ✅ 宽松，保留版权声明。**优先选它** |
| awesome-game-file-format-reversing | **CC0-1.0** | ✅ 公共领域 |
| UnityPy | **MIT** | ✅ 宽松，且 Python 可直接内嵌 |
| AssetStudioMod | **MIT** | ✅ |
| RPGMakerDecrypter | **MIT** | ✅ |
| TriggersTools.CatSystem2 | **MIT** | ✅ |
| **VNTranslationTools (VNTextPatch)** | **MIT** | ✅ **回写能力的宽松许可来源，价值最高** |
| KirikiriTools | **MIT** | ✅ |
| **STool** | **MIT** | ✅ 但成熟度极低（1★） |
| rpatool | **WTFPL** | ✅ 极宽松 |
| **arc_unpacker** | **GPL-3.0** | ⚠️ 分发二进制须提供对应源码；衍生作品须 GPL |
| **Textractor** | **GPL-3.0** | ⚠️ 同上 |
| **LunaTranslator** | **GPL-3.0** | ⚠️ 同上；**不要抄代码** |
| **unrpa** | **GPL-3.0** | ⚠️ 同上 |
| **AssetRipper** | **GPL-3.0** | ⚠️ 同上 |
| **KrkrzExtract** | **GPL-3.0** | ⚠️ 同上 |
| **KrkrExtract** | ⚠️ **冲突**：README 称 GPLv3，但无 LICENSE 文件 | ❓ 商用前必须澄清 |
| **xp3-brute** | ⚠️ **无许可证** | ❌ 无许可＝默认保留全部权利，**不可用于分发** |
| **FuckGalEngine / Gal-Extractor / asmodean-tools** | ⚠️ **无许可证 / 须作者许可** | ❌ **不可商用** |
| **FreeMote** | ⚠️ **CC BY-NC-SA 4.0** | ❌ **禁止商业使用**（易被误认为开源） |
| **GameStringer** | ⚠️ **自定义 Source-Available v1.1** | ❌ 禁商用、禁再分发、禁做竞争性商业产品 |
| **n8n** | ⚠️ **Sustainable Use License v1.0** | ❌ **禁止随商业产品分发**。原文：*"only for your own internal business purposes or for non-commercial or personal use"* |
| **Dify** | ⚠️ **修改版 Apache-2.0** | ⚠️ 可商用，但**多租户需授权**；**不得移除前端 LOGO/版权** |
| Galgame-Engine-Collect | `NOASSERTION` **[未核实]** | ❓ |
| VNTools / YeLikesss/KrkrExtractForCxdecV2 | **[未核实]** | ❓ |
| Tyranor-Next | **GPL-2.0** | ⚠️ |
| **XUnity.AutoTranslator** | **MIT** | ✅ Unity 运行时 hook，宽松 |
| **langgraph / langchain / crewAI** | **MIT** | ✅ 可内嵌（Python 库） |
| **llama.cpp**（`ggml-org/llama.cpp`） | **MIT** | ✅ **本地推理最佳内嵌选择**（C/C++ 库，无需服务） |
| **autogen** | **代码 MIT**（`LICENSE-CODE`）/ 文档 CC-BY-4.0 | ✅ 用 MIT 代码许可即可 |
| **ollama** | **MIT** | ⚠️ 许可宽松，但形态是本地 HTTP 服务（127.0.0.1:11434） |
| **vllm** | **Apache-2.0** | ⚠️ 服务栈+GPU，不适合消费级桌面内嵌 |
| **rea / GhidraMCP / ReVa** | **MIT / Apache-2.0** | ✅ 可参考其「工具化 + MCP」架构 |
| **reverser_ai** | **GPL-2.0** | ⚠️ |
| **GalTransl** | **GPL-3.0** | ⚠️ 不要抄代码 |
| **Flowise** | `NOASSERTION` | ❌ **项目已日落（2026-08 归档），不要选用** |
| **Translator++** | ⚠️ **README 称 GPL-3.0，但未发布应用源码** | ❓ **不可视为开源** |
| **MTool** | ⚠️ **闭源**（未找到源码仓库） | ❌ 专有软件 |
| **Sugoi Toolkit** | **[未核实]**（原仓库 404，现站条款无法提取） | ❓ 模型可再分发许可未核实 |
| **MTool-Translator / AiNiee / AITranslator / GalTransl_DumpInjector** | **[未核实]** | ❓ |

> **两个最容易踩的坑**：
> 1. **n8n** —— 「AI 工作流」最顺手的选型，但许可证明确禁止随商业产品分发。若闭源商业发布，**改用 MIT 的框架（如 LangGraph）或自研轻量编排**。
> 2. **FreeMote** —— API 显示 `NOASSERTION`，很容易被当成开源；实为 **CC BY-NC-SA 4.0（禁商用）**。
>
> **AI 工作流框架**（许可证已核实，详见 3.8）：**可内嵌的合规组合 = llama.cpp（MIT，本地推理）+ LangGraph 或 crewAI（MIT，编排）**。
> ❌ 避开 **n8n**（Sustainable Use，禁止随商业产品分发）、**Flowise**（2026-08 已归档日落）、**Dify / vLLM**（服务栈形态，不适合消费级桌面内嵌）。
> ⚠️ 注意 **autogen** 的许可证是拆开的：代码 MIT（`LICENSE-CODE`），API 报的 CC-BY-4.0 只覆盖文档。

### 5.2 GPL 组件的正确用法（已取得 GPL-3.0 原文与 FSF FAQ）
**GPL-3.0 原文依据**（引自 SPDX 许可证全文，与 gnu.org 同源）：
- **§5 末段「聚合」条款**支持「独立分发不传染」：
  > *"A compilation of a covered work with other separate and independent works, which are not by their nature extensions of the covered work, and which are not combined with it such as to form a larger program, in or on a volume of a storage or distribution medium, is called an "aggregate"... **Inclusion of a covered work in an aggregate does not cause this License to apply to the other parts of the aggregate.**"*
- **§6 是你真正躲不掉的义务**（把 GPL 工具二进制随产品分发即属 conveying，必须提供 Corresponding Source）：可用 **§6(b)** 三年期书面要约，或 **§6(d)** 同址网络提供。
- **§10** 不得附加限制；**§5** 若你**修改**了该工具，修改版整体须以 GPL 授权（**这正是「能不改就不改」的原因**）。

**FSF FAQ 的解释倾向**（原文取自 FSF 官方中文镜像 `gnu.net.cn`，因 gnu.org 对本环境返回 403，**英文原文未逐字核对**；且该 FAQ 主体是 GPLv2 FAQ）：
> *"管道、套接字和命令行参数是通常在两个单独的程序之间使用的通信机制。因此，当它们用于通信时，模块通常是单独的程序。"* 但 *"如果通信的语义足够密切，交换复杂的内部数据结构，那么这也可能成为将两个部分视为组合成一个更大的程序的基础。"*
> 且 FAQ 自己承认：*"这是一个法律问题，最终将由法官决定。"*

**结论（工程可执行版）**：
| 做法 | 你的代码是否被传染 | 是否须提供该工具源码 |
|---|---|---|
| 独立 exe + 命令行/管道调用，**不交换复杂数据结构** | ❌ 通常不传染 | ✅ **仍然必须** |
| 独立 exe 但频繁交换复杂数据结构 | ⚠️ 有被认定为「单一组合作品」的风险 | ✅ 必须 |
| 链接进二进制 / 修改后分发 | ✅ **高度可能传染** | ✅ 必须 |

> ⚠️ **关键澄清（最容易被误解的一点）**：**「独立进程」只解决「你的代码是否被传染」，并不解决「你分发了 GPL 二进制」这件事本身。** 只要 GPL 工具随你的安装包分发，§6 的源码提供义务就成立。
> ⚠️ 以上为条文原文 + 许可方解释，**不是法律定论**，商业发布前**必须让律师复核**。

### 5.3 游戏内容本身的合法性（与工具许可证是两件事）

**已取得条文原文（一般信息，非法律意见）。**

**① 日本《著作権法》**（维基文库全文，最终改正 令和五年法律第三十三号；e-Gov 为 JS 渲染无法抓取，**非官方一手源**）
- **第30条第1項第2号**——「私的使用」抗辩的**剥夺条款**：明知而复制「技術的保護手段の回避により可能となり…た複製」时，**不适用私的使用例外**。原文关键句：*"…により可能となり、又はその結果に障害が生じないようになつた複製を、**その事実を知りながら**行う場合"*。
- **第30条の4**——标题即限定条件：*"著作物に表現された思想又は感情の享受を目的としない利用"*（不以享受思想感情为目的的利用），含「情報解析」事由。**它给数据分析留出空间，但不认可「为再发布素材」或「制作衍生作品」。**
- **第113条第7項**——提供**以规避 TPM 为功能**的指令/程序，即「视为侵权」：*"技術的保護手段の回避又は技術的利用制限手段の回避を行うことをその機能とする指令符号…を公衆に譲渡し…公衆の使用に供し…する行為は…侵害する行為とみなす"*。
- **第2条第1項第20号 / 第21号**——注意区分两个概念：**技術的保護手段**（防/抑止侵权）与**技術的利用制限手段**（限制「視聴」）。规避后者由**第113条第6項**直接视为侵权。

**② 美国 DMCA 17 U.S.C. §1201**（原文引自 U.S. Copyright Office）
- **§1201(a)(1)(A)**：*"No person shall circumvent a technological measure that effectively controls access to a work protected under this title."*
- **§1201(a)(2)**：禁止提供/贩卖**主要为规避访问控制而设计**、或**仅有有限商业意义用途**、或**以规避为目的营销**的技术/产品/服务。
- **§1201(f) 互操作性例外范围很窄**：仅限 *"sole purpose of identifying and analyzing those elements… necessary to achieve **interoperability**"* —— **不覆盖「为提取美术/音频素材」。**
- **§1201(c)(1)** 只说明 1201 不影响合理使用抗辩，**并不为规避行为本身提供抗辩**。

**③ 真实日语游戏 EULA 实例**（证明「禁止解析」是通行条款）
- [Abyss Walker「DEMON WORK WALK」EULA](https://store.steampowered.com/eula/4216070_eula_0)（日本法人、日本法準拠、东京地裁专属管辖）第2条禁止事項原文列举：*"1. リバースエンジニアリング、逆コンパイル、逆アセンブル"*、*"2. データ改ざん、メモリ操作、通信改変"*。
- [Artifex Mundi 日语版 EULA](https://store.steampowered.com/eula/855640_eula_0?eulaLang=japanese)：*"(d)…技術的保護手段を回避すること、(e)リバースエンジニアリング、逆コンパイル、逆アセンブル、二次的著作物の作成…"*，且**一旦尝试规避 TPM，EULA 立即失效**。
- ⚠️ **未取得**日本 galgame 品牌（ゆずソフト/minori/Key 等）自有 利用規約 原文。

**三类风险的等级差异（务必区分）**
| 行为 | 风险 | 依据 |
|---|---|---|
| 分发「以规避 TPM 为功能」的工具 | **高** | 日《著作権法》第113条第7項；DMCA §1201(a)(2) |
| 为个人使用提取自购游戏资源 | 灰色；**若涉及规避 TPM 则抗辩丧失** | 第30条第1項第2号 |
| **再分发提取出的资源或修改后的游戏数据** | **几乎必然侵权** | 第21/23/27条；汉化社区惯例 ≠ 法律许可 |

- **降低风险的产品设计**：
  - 软件**只提供工具能力**，不内置、不分发任何游戏资源或译文补丁。
  - 若做补丁分享（如 GameStringer 的 Patch Hub），需评估是否构成「帮助侵权」——**这是该模式最大的法律暴露面**。
  - EULA/免责声明中明确要求用户仅对自己合法持有的游戏使用。
- ⚠️ **以上为条文原文与一般性信息，不构成法律意见。商业发布前请咨询律师。**
- ⚠️ **重要限制**：日本法条文本取自**维基文库**（该页自带「不保证反映最新改正」免责声明），非 e-Gov 官方原文；**罰則（第119条/第120条の2）条文原文未抓取**。

---

## 6. 建议的落地路线（分阶段，降低返工）

**阶段 0（1–2 周）｜先验证最窄闭环**
- 选**一个**引擎（建议 KiriKiri：工具链最全且有可回写方案）。
- 用 GARbro.Console 解一个真实游戏 → 提取文本 → 人工确认质量。
- **此阶段不写任何 AI**，只验证「提取」这一半。

**阶段 1（2–4 周）｜确定性管线**
- 实现 S1–S6 确定性版本 + 2.5 验收 oracle + 案例库（SQLite/JSON）。
- 直接借鉴 STool 的「证据打分 + 阈值判定 + 插件分派」骨架覆盖 GARbro 签名表能命中的情况（L0 路径）。
- **此时应已有可用产品**（只对已知引擎有效）。

**阶段 2（3–6 周）｜接入 AI 兜底**
- 按 A1 → A2 → A3 顺序加，每加一个都用阶段 1 的 oracle 做回归。
- A4（生成解析器）最后做，且必须先有沙箱（2.6）。

**阶段 3｜回写 + 打包发布**
- 回写按引擎逐个攻（KiriKiri 优先：需澄清 `KrkrExtract` 的许可证冲突，或改用 MIT 的 `VNTranslationTools` 走文本层回填）。
- PyInstaller onedir + Inno Setup；买代码签名证书；写 ANTIVIRUS 说明。

**贯穿始终的两条纪律**
1. **每次失败都入库**（2.7），否则 AI 成本永远降不下来。
2. **先扩引擎覆盖，再优化 AI**。GameStringer 的经验表明长尾引擎覆盖才是护城河。

**阶段 1 就应确定的一件事：把编排器暴露成 CLI + MCP Server**（见 3.9 的架构结论）
- 理由：工业界已验证的模式是「AI 通过 MCP/REST 驱动确定性工具」（Translator++ 的 `/mcp`、ReVa 的 tool-driven 设计、`rea` 的 agent 化）。
- 收益：AI 层可用任意框架或现成客户端（Claude Desktop / Cursor）驱动；确定性逻辑与 AI 逻辑彻底解耦，可独立测试与替换；能力可被他人复用。
- 成本很低：在阶段 1 的 CLI 之上再包一层 MCP 即可，**不要等到阶段 2 才考虑**。

---

## 7. 未核实 / 存疑清单

1. `xmoezzz/KrkrExtract` **许可证冲突**：README 声明 GPLv3，但 API `license=null`，无 LICENSE 文件。以哪个为准未核实。
2. `xmoezzz/xp3-brute`、`Inori/FuckGalEngine`、`M1zukiri/Gal-Extractor`、`hiroshil/asmodean-tools` **无明确许可证** → 商用不可用。
3. `FreeMote` 为 **CC BY-NC-SA 4.0（禁商用）**，虽 API 显示 `NOASSERTION`。
4. `Galgame-Engine-Collect` 许可证为 `NOASSERTION`；其 `unpack.md`/`table.md` 内容未核实。
5. **STool 能力全为自述**（支持引擎表、355 项测试、60 分阈值），仅 1★、创建 11 天，无第三方验证。
6. `GARbro` 完整格式清单未核实（supported.html 在 50,000 字符处截断）；**Unity 支持**仅有间接证据（FreeMote 致谢引用 `ArcFormats/Unity/Bc7Decoder.cs`），未在格式表直接确认。
7. `arc_unpacker` 逐引擎覆盖未核实（README 仅举 XP3/BGI/Team Shanghai Alice 三例，`GAMELIST.htm` 未逐条读取；README 中 rawgit 链接域名已停服）。
8. `abunomaru/VNTools`、`YeLikesss/KrkrExtractForCxdecV2` 许可证未核实。
9. `asmodean` 官方站 `asmodean.reverse.net` **DNS 解析失败**，现状/清单未核实。
10. **AI 工作流框架许可证已核实**（见 3.8）。剩余未核实：Dify 与 Flowise 的**具体条款文本**（两者均为 `NOASSERTION` 自定义许可）；`NEKOparapa/AiNiee`、`GalTransl_DumpInjector`、`jxq1997216/AITranslator` 的许可证。
10b. **`HIllya51/LunaHook` 返回 404**（经两次核实），2024-11-15 被报告归档；其 C++ hook 代码是否已并入 LunaTranslator **未核实**。**不要引用该链接**；第三方 fork 见 `ZUIcat/LunaHook`。
10c. **Translator++「开源」存在冲突**：README 与 API 均称 GPL-3.0，但 `dreamsavior/TranslatorPlusPlus` 仓库**只有 docs/images/LICENSE/README**（5 commits、0★、`language: null`），实际程序是**带密码的便携包**，未找到应用源码仓库 → **不可写作「开源」**。注意该仓库**不是**其社区中心，不要用其星数判断项目健康度。
10d. **MTool 闭源**属「未找到源码」的推断，作者本人是否明确声明闭源 **未核实**。
10e. **Sugoi** 原作者仓库 `leminhyen2/Sugoi-Japanese-Translator` **返回 404**；现站 `sugoitoolkit.com` 为纯 JS 渲染，**许可与定价条款未核实**；已核实的 MIT 代码均为 2022 年第三方打包，**非模型本身**，模型的可再分发许可未核实。
10f. **VNR** 仅核实到 2018 年的源码存档（`Artikash/VNR-Core`，GPL-3.0，`pushed_at` 2018-12-10，30★）；官方站点是否仍在运营 **未核实**。
10g. **Flowise 归档日期存在轻微分歧**：API 为 `archived: true` / `pushed_at` 2026-08-13，官方 sunset 页写 **2026-08-10** 归档。以官方页 + API 标志为准。
11. **日本《著作権法》条文来源非官方一手**：取自**维基文库**（该页自带「不保证反映最新改正」免责声明），**e-Gov 法令検索为 JS 渲染无法抓取**；已核对最终改正为令和五年法律第三十三号。**罰則（第119条／第120条の2）条文原文未抓取**，仅由第30条/第113条的交叉引用确认其存在与适用范围。
12. **日本 galgame 品牌自有 利用規約 原文未取得**（检索未命中）。已用**两份真实的日语商业游戏 EULA**替代（Abyss Walker、Artifex Mundi），二者均含「禁止リバースエンジニアリング」与「禁止规避技术保护手段」条款。
12b. **FSF FAQ 引文为官方中文镜像文本**（`gnu.net.cn`；gnu.org HTML FAQ 对本环境返回 **403**），**英文原文未逐字核对**；且该 FAQ 主体是 **GPLv2 FAQ**，GPLv3 单列条目正文位于抓取截断之后未取得。
12c. **LGPL-3.0 下「仅以独立进程调用 LGPL 可执行文件」**：许可原文**无对应条款**，义务归属属解释问题（**[未核实]**）。已核实的是 §4/§5 义务以构成 Combined Work 为前提。
12d. **DMCA 2024 年最终豁免的具体类别**（是否含游戏保存/废弃游戏）**未核实**；仅确认该次 rulemaking 与 Final Rule 存在，第十次 rulemaking 在推进（续期豁免 2027-10 ~ 2030-10）。
16. ⚠️ **Nuitka 许可存在冲突（最需注意）**：当前 4.3 官方手册写明 **AGPL-3.0** + 运行时例外；但检索到的一份 nuitka.net 手册 PDF 片段写 **Apache-2.0**。疑为版本沿革（早期 Apache → 现 AGPL）。**用于闭源产品前必须直接核对发行包内 `LICENSE.txt` / `LICENSE-RUNTIME.txt`。**
17. **PyInstaller 杀软误报无官方记载**：已核对 *Common Issues and Pitfalls* 与 *When Things Go Wrong* 两页，**均无 antivirus/false positive 章节**（官方 wiki FAQ 因直连失败未读）。故「官方对 AV 误报的说明」**[未核实]**——4.5 的结论来自社区实践与 GameStringer 的公开记录，**非 PyInstaller 官方**。
18. **PyInstaller 打包大型 ML 模型**：官方**无专门指引或容量上限说明**（**[未核实]**）。可核实的只有机制性事实（onefile 压缩嵌入+每次启动解压+崩溃残留）。
19. **`arc_unpacker` 的 `LICENSE.md` 原文与版权行未取得**（根目录无 `LICENSE`；`LICENSE.md` 抓取两次失败）。GPL-3.0 仅由仓库侧栏确认。
20. **NSIS 当前版本号**、**WiX v7 仓库 LICENSE 原文**（MS-RL 取自 3.10.1 时代文档镜像）、**cx_Freeze / Briefcase 的许可证具体条款**、**MSIX 明确「不支持」场景清单**：均 **[未核实]**。
13. **未发现任何「让 LLM 直接解析游戏归档」的项目**（检索 `visual novel engine detect`、`galgame extract`、`galgame engine`、`galgame unpack archive decrypt tool AI LLM` 均无对应命中）。但**通用 Agent 逆向工程确实存在且规模巨大**（`rea` 136,846★、GhidraMCP 11,101★、ReVa、`reverser_ai`），且**已有解包器主动暴露 MCP 给 Agent 驱动**（Translator++）。**准确的结论是：空白点在于「游戏资源解包」这一具体领域，而非「AI 驱动逆向」这一范式本身。**
14. **本次会话 `pwsh` 执行环境不可用**（`0xC0000142`），所有结论基于文档与仓库页面核实，**未做本地实测**。
15. `platform_search(platform="github")` 对多个确实存在的查询返回 0 结果，**与 GitHub REST API 不一致、不可靠**；本报告仓库级事实以 GitHub REST API + README 原文为准，未把该工具的空结果当作「不存在」的证据。
