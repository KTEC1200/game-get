# VN/Galgame 解包工具 — 一手来源核实报告

核对时点：2026-10-12（UTC 前后）。方法：直接读 GitHub REST API（`api.github.com/repos/...`、`/search/repositories`）与仓库 README 原文；`license` 字段取自 GitHub API 的 `license.spdx_id`，README 原文另附引号引文。凡未取到一手证据者，一律标注 **未核实/UNCERTAIN**。

---

## 解包工具

### 1. morkt/GARbro
- **仓库**：`morkt/GARbro` — https://github.com/morkt/GARbro
- **用途（原文）**："Visual Novels resource browser"（README 首行）
- **语言**：C#
- **支持的引擎/封包**（据官方格式表 https://morkt.github.io/GARbro/supported.html ，字段为"签名/品牌引擎"）：BGI/Ethornell `*.arc`（`BURIKO ARC20`）、KiriKiri `*.xp3`（`XP3`）+ `*.tlg`；NScripter `*.nsa`/`*.sar`；Ren'Py `*.rpa`（`RPA-3.0`）；Majiro `*.arc`（`MajiroArcV1.000`/`V2`/`V3`）；YU-RIS `*.ypf`/`*.ycg`；CatSystem2 `*.int`/`*.hg3`/`*.hg2`；Nitro+ `*.npa`；Alice Soft `*.ald`/`*.afa`/`*.alk`；Will `*.arc`/`*.wip`/`*.msk`/`*.mos`；Liar-soft `*.xfl`/`*.lwg`；Shiina Rio `*.war`（`WARC 1.x`）；Lucifen `*.lpk`；AZ System `*.arc`（`ARC\x1a`/`ARC`）；Silky's `*.mfg`/`*.mfm`/`*.mfs`；Marble `*.mbl`；以及大量厂商私有格式（Active Soft、DRS、SYSTEM-ε、Kogado、NeXAS、RAGE、Flying Shine、Studio e.go!、FFA System/G-SYS 等）。该页还标注了各格式是否支持 **Create（封包回写）**。Unity 支持：FreeMote README 的致谢中引用了该仓库代码路径 `morkt/GARbro/blob/master/ArcFormats/Unity/Bc7Decoder.cs`，可证存在 Unity 模块目录；但 supported.html 抓取在 50k 字符处被截断，Unity 是否完整列入 **未核实**。
- **来源**：https://github.com/morkt/GARbro ; https://morkt.github.io/GARbro/supported.html ; https://github.com/UlyssesWu/FreeMote （致谢段）
- **许可证**：GitHub API `license.spdx_id = "MIT"`；README 原文："Written by morkt under MIT License"。仓库 About 区显示 "MIT license"。
- **最后活动**：**未归档**（API `archived: false`）。master 最新提交 `b09ee45` "added more PC-98 formats."，2023-10-27（仓库页显示"3 years ago"）。API `pushed_at = 2024-07-08T19:36:58Z`（可能含其他分支）。3,327 stars，276 个 open issues（长期未清理，实际处于低速维护状态）。无 Releases 页内容。
- **可提取**：文本（作为原始文件）/ 图片（导出时转常见格式）/ 音频（转常见格式）/ 脚本（原始文件）；部分格式支持回写封包。另有 `Console/`（GARbro.Console）命令行项目。

### 2. vn-tools/arc_unpacker
- **仓库**：`vn-tools/arc_unpacker` — https://github.com/vn-tools/arc_unpacker
- **用途（原文）**："arc_unpacker is a command line tool for extracting images, sounds, music and miscellaneous resources from visual novels (and some other Japanese games)."
- **语言**：C++
- **支持的引擎/封包**：按文件内容自动猜测格式；README 明确举例 KiriKiri `XP3`（需 `--dec=krkr/xp3 --plugin=...`，示例 `--plugin=fsn` 为 Fate/Stay Night 解密）、Team Shanghai Alice `th08.dat`（`--dec=team-shanghai-alice/pbgz`）、BGI `bse`（提交记录 `dec/bgi/bse: initial support`）。逐游戏清单在 `GAMELIST.htm`/`GAMELIST.js`（本次未逐条读取 → 具体覆盖范围 **未核实**）。
- **来源**：https://github.com/vn-tools/arc_unpacker （README、仓库页）
- **许可证**：GitHub API `license.spdx_id = "GPL-3.0"`；仓库 About 区 "GPL-3.0 license"，文件为 `LICENSE.md`。
- **最后活动**：**已归档**（仓库页横幅："This repository was archived by the owner on Apr 25, 2022. It is now read-only."；API `archived: true`）。最新提交 `456834e` 2021-09-06（xiongnemo，docs 更新）；API `pushed_at = 2022-02-18T19:09:09Z`。670 stars，87 open issues。**只读，不再维护**。
- **可提取**：图片 / 音频（含 `.wavloop`）/ 音乐 / 杂项资源。**不提取文本或脚本**；README 明确拒绝封包功能："Packing / encoding support? Not going to happen."

### 3. xeonlive/KrkrExtract —— **该仓库不存在**
- https://github.com/xeonlive/KrkrExtract 返回 **HTTP 404**（本次实测）。GitHub 仓库搜索 `KrkrExtract` 共 7 个结果，**没有 xeonlive 名下仓库**；是否历史上存在过 **未核实**。
- **正确的同名仓库是 `xmoezzz/KrkrExtract`** — https://github.com/xmoezzz/KrkrExtract
  - **用途（README 原文）**："A tool can extract and pack krkr2 and krkrz's xp3 files (32Bit & 64Bit)"
  - **语言**：C++
  - **支持**：KiriKiri krkr2 / krkrz 的 `.xp3`（含运行时 Universal Dump / Universal Patch，可覆盖顶层脚本）
  - **许可证（重点：README 与 GitHub 判定不一致）**：GitHub API `license: null`（未检出 LICENSE 文件）；但 README 原文写明："All source code files are licensed under **GNU General Public License v3 (GPLv3)**."（并附 GPLv3 徽标链接）。引用时须说明二者冲突。
  - **最后活动**：**已归档**（API `archived: true`）。README 自带 "⚠️ Not Under Maintain" 小节。API `pushed_at = 2022-01-01T05:45:29Z`；1,426 stars，79 open issues。
  - **来源**：https://github.com/xmoezzz/KrkrExtract
- **后继/替代（同作者 xmoezzz）**：
  - `xmoezzz/KrkrzExtract` — https://github.com/xmoezzz/KrkrzExtract — "The next generation of KrkrExtract"；C；**GPL-3.0**（API `spdx_id = "GPL-3.0"`）；**未归档**，`pushed_at = 2026-08-25T11:34:07Z`，267 stars，9 open issues。README 原文警告："Beta version, unstable now (a decade)."、"KrkrzExtract only supports krkrz engine."；局限："Extracting all resources requires playing through the entire game… Resources unused during gameplay cannot be extracted."
  - `xmoezzz/xp3-brute` — https://github.com/xmoezzz/xp3-brute — "A nostalgic way to unpack, pack, and modify Kirikiri (krkr) XP3 archives."；**Rust**；`license: null`（无 LICENSE 文件，**无明确开源许可证**）；**未归档**，创建 2026-08-20，`pushed_at = 2026-10-09T05:54:13Z`，45 stars。KrkrzExtract README 描述其为"cross-platform tool that can extract XP3 archives without running the game… leverages reverse-engineering, Win32 emulation, symbolic execution, and brute-force"。
- **可提取**：图片 / 音频 / 脚本（xp3 内全部文件）；krkrz 运行时方式只能拿到游戏实际读取过的资源。

### 4. UlyssesWu/FreeMote
- **仓库**：`UlyssesWu/FreeMote` — https://github.com/UlyssesWu/FreeMote
- **用途（原文）**："Managed EMT/PSB tool libs."；"FreeMote is a set of tool/libs for `M2 Packaged Struct Binary` file format."
- **语言**：C#（.NET Framework 4.8 / VS2022）
- **支持的引擎/格式**：E-mote（EMT）的 PSB 系列——`.psb|.psz|.mdf|.pimg|.scn|.mmo|.emtbytes|.mtn|.dpak|.psb.m`。README 明确排除同名但不同的格式（`.psb` PlayStation Binary / PhotoShop Big、`.mdf` Alcohol 120% / MSSQL、`.mtn` Live2D Motion）。TLG 图像经 `FreeMote.Tlg` 插件；音频为实验性（`NuGet.Config` 提交记录 "[audio] add AT3 support #170"，2026-07-20）；FastLz 压缩经 `FreeMote.FastLz`。
- **来源**：https://github.com/UlyssesWu/FreeMote （README）；提交记录 https://github.com/UlyssesWu/FreeMote/commit/e3d06bfdc0f8394483f21d6928d9c404d7e96fa9
- **许可证**：GitHub API `license.spdx_id = "NOASSERTION"`（`name: "Other"`）。README 原文："FreeMote is licensed under a [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-nc-sa/4.0/) (CC BY-NC-SA 4.0)." 且 "Some outputs of FreeMote (mmo/psd etc.) … are always licensed under CC BY-NC-SA 4.0"；另要求随发布附带 `FreeMote/FreeMote.LICENSE.txt`。**注意：CC BY-NC-SA 4.0 非 OSI 认可的开源许可证，且禁止商业使用。**
- **最后活动**：**未归档**，`pushed_at = 2026-10-06T15:01:27Z`，最新提交 `d87be1f` "update build.yml" 2026-10-06；521 stars，2 open issues。活跃维护（2026 年 2 月/7 月/9 月/10 月均有提交）。
- **可提取**：图片（含 TLG）/ 音频（实验性）/ 脚本（`PsbDecompile` 反编译 PSB → json + 资源；`PsBuild` 可回编译）；`EmtConvert` 转换、`FreeMote.Tools.Viewer` 渲染。**不是通用 VN 解包器**，仅 E-mote/PSB。

### 5. VNTextPatch —— 正确 owner 是 **arcusmaximus**，不是 AtomCrafty
- **`AtomCrafty/VNTextPatch` 不存在**：https://github.com/AtomCrafty/VNTextPatch 返回 **HTTP 404**（本次实测）。遍历 `AtomCrafty` 的公开仓库列表，与 VN 相关的只有 `UniversalInjectorFramework`（C++，110 stars，`pushed_at 2026-01-28`，无 license 字段）、`QuickLootIE`（GPL-3.0）、`CstPatcher`（C#，无 license）、`catsystem-py`（MIT，fork）、`TriggersTools.CatSystem2`（MIT，fork）——**没有 VNTextPatch**。
- **正确仓库**：`arcusmaximus/VNTranslationTools` — https://github.com/arcusmaximus/VNTranslationTools （内含 **VNTextPatch** 与 **VNTextProxy**）
- **用途（原文）**："A tool for extracting original text from, and patching translated text into, a variety of visual novel formats."
- **语言**：C#
- **支持的引擎/格式**（README 表格原文逐一列出）：AdvHD `.ws2`；ArcGameEngine `.bin`；Artemis `.asb/.ast/.txt`；Buriko General Interpreter/Ethornell（无扩展名）；CatSystem2 `.cst`；Cyberworks C,system `.a0`；KaGuYa `message.dat`；Kirikiri `.ks/.scn/.txt`；Majiro `.mjo`；Musica `.sc`；Mware `.nut`；Propeller/Stuff Script Engine `.msc`；RealLive `.txt`；Ren'Py `.rpy`；ShSystem `.hst`；Silky's/AI6WIN `.mes/.map`；Qlie `.s`；Softpal `script.src`；SystemNNN `.nnn/.spt`；TmrHiroAdvSystem `.srp`；Whale `.txt`；YU-RIS `.ybn`。
- **来源**：https://github.com/arcusmaximus/VNTranslationTools （README）
- **许可证**：GitHub API `license.spdx_id = "MIT"`。
- **最后活动**：**已归档**（API `archived: true`）；`pushed_at = 2023-02-20T17:50:50Z`；424 stars，25 open issues。
- **可提取**：**仅文本**（导出为 `.xlsx` 或 `.json`，可从 Excel/JSON/Google Docs 回填）。脚本解析按引擎实现（如 `KirikiriScript.cs`，README 提示部分游戏需自行改源码）。不导出图片/音频。附带 `VNTextProxy`（代理 `d2d1.dll`）解决 SJIS 隧道、字体、比例字体排版问题。
- **活跃分支/移植（均有据可查）**：
  - `rafael-vasconcellos/VNTextPatch-net8` — https://github.com/rafael-vasconcellos/VNTextPatch-net8 — **MIT**，C#，**未归档**，`pushed_at = 2026-10-12T00:35:02Z`，11 stars（.NET 8 移植，本次搜索中 star 最高者）
  - `lunaswd/VNTextPatch-GUI` — https://github.com/lunaswd/VNTextPatch-GUI — MIT，`pushed_at 2024-10-14`
  - `rafael-vasconcellos/VNTextPatch-web` — https://github.com/rafael-vasconcellos/VNTextPatch-web — MIT，TypeScript，`pushed_at 2026-01-31`

### 6. Unity：Perfare/AssetStudio 与 AssetRipper/AssetRipper
#### 6a. Perfare/AssetStudio
- **仓库**：`Perfare/AssetStudio` — https://github.com/Perfare/AssetStudio
- **用途（原文）**："AssetStudio is a tool for exploring, extracting and exporting assets and assetbundles."
- **语言**：C#
- **支持**：Unity **3.4 – 2022.1**；资源类型 Texture2D（→png/tga/jpeg/bmp）、Sprite、AudioClip（mp3/ogg/wav/m4a/fsb，可 FSB→WAV(PCM)）、Font（ttf/otf）、Mesh（obj）、TextAsset、Shader、MovieTexture、VideoClip、MonoBehaviour（json）、Animator（→FBX）。
- **许可证**：GitHub API `license.spdx_id = "MIT"`；About 区 "MIT license"。
- **最后活动**：**已归档**（仓库页横幅 "archived by the owner on **Jan 21, 2023**"；API `archived: true`）。最新提交 `d158e86` "support 2022.1" 2022-06-16；API `pushed_at = 2022-12-08T15:37:37Z`。15,588 stars，182 open issues。
- **可提取**：图片 / 音频 / 文本(TextAsset) / 脚本(Shader、MonoBehaviour→json) / 模型与动画。
- **活跃 fork（实际被继续使用）**：`aelurum/AssetStudioMod` — https://github.com/aelurum/AssetStudioMod — "modified version of Perfare's AssetStudio"；**MIT**；C#；**未归档**，`pushed_at = 2025-10-15T19:38:12Z`，2,118 stars（`fork: true`，parent = Perfare/AssetStudio）。

#### 6b. AssetRipper/AssetRipper
- **仓库**：`AssetRipper/AssetRipper` — https://github.com/AssetRipper/AssetRipper
- **用途（原文）**："AssetRipper is a powerful tool for analyzing Unity game files." / About: "GUI application to analyze game files"；官网 https://assetripper.com/
- **语言**：C#
- **支持**：Unity `3.5.0` 到 `6000.4.X`（README 原文："AssetRipper supports Unity versions from `3.5.0` to `6000.4.X`. However, support quality may vary slightly for different Unity versions."）。导出为原生 Unity 工程格式。
- **许可证**：GitHub API `license.spdx_id = "GPL-3.0"`；README 原文："AssetRipper is licensed under the [GNU General Public License v3.0]"；About 区 "GPL-3.0 license"。注意另有**闭源付费 Premium 版**（$10/月，README "Premium Edition" 段）。
- **最后活动**：**未归档**；最新提交 `beeb50e` "Update NAudio.Core to 3.1.0" 2026-10-09；`pushed_at = 2026-10-09`；8.6k stars，108 tags。**活跃维护**。
- **可提取**：图片 / 音频 / 文本 / 脚本（含反编译相关工具链）/ 模型；整包导出为 Unity 工程。

### 7. K0lb3/UnityPy
- **仓库**：`K0lb3/UnityPy` — https://github.com/K0lb3/UnityPy
- **用途（原文）**："UnityPy is python module that makes it possible to extract/unpack and edit Unity assets"；"A Unity asset extractor for Python based on [AssetStudio](https://github.com/Perfare/AssetStudio)."
- **语言**：Python（README：Python 3.8+）
- **支持**：Unity 序列化文件 / AssetBundle / WebFile / APK（`UnityPy.load` 自动判别）；对象类型 Texture2D、Sprite（自动合并 alpha 图）、TextAsset、AudioClip、Mesh 等，并支持通过 typetree 修改后回存。
- **许可证**：GitHub API `license.spdx_id = "MIT"`；README 徽标 "MIT"，LICENSE 文件于 2026-08-01 更新版权年。
- **最后活动**：**未归档**；最新提交 `417d595` "chore(CompressionHelper): use divmod for decompress_lzma" 2026-10-05；`pushed_at = 2026-10-05`；810 commits；0 tags（版本经 PyPI 发布）；**活跃维护**（README 自述 "still in active development, breaking changes can happen"）。
- **可提取**：图片 / 音频 / 文本(TextAsset) / 脚本 / 模型；**并支持编辑**（`obj.patch()`、`env.file.save()`）。

### 8. asmodean（"as-tools"）—— **没有官方 GitHub 仓库**
- GitHub 搜索 `asmodean` 无作者本人账号下的仓库。存在的只是**镜像/再分发**：
  - `hiroshil/asmodean-tools` — https://github.com/hiroshil/asmodean-tools — 51 stars，`pushed_at = 2023-10-03T18:42:49Z`（一次性导入），主语言 Batchfile，**`license: null`**。仓库描述原文："These software may not be redistributed, modified or used in other software without the author's permission. Author: asmodean. Forked from galgametools/asmodean/asmodean tools"。→ **实际许可为"须经作者许可"，不是开源。**
  - `000ylop/galgametools` — https://github.com/000ylop/galgametools — 180 stars，`pushed_at = 2020-08-12T03:22:07Z`，**`license: null`**，README 仅 14 字节（原文 `# galgametools`），无文档。topic: `extract`/`extractor`/`galgame`。
  - 相关的再实现：`trigger-segfault/GrisaiaExtractor`（MIT，C#，`pushed_at 2019-01-20`，描述明言 "All ripping written by asmodean"）。
- **官方分发站点** `https://asmodean.reverse.net/`：本次抓取失败（`getaddrinfo ENOTFOUND`）→ **该站当前是否在线、工具清单与版本日期均未核实/UNCERTAIN**。

### 9. 中文 galgame 解包工具箱（经核实后才列出）
- **`shushui0710/STool`** — https://github.com/shushui0710/STool
  - **用途（原文）**："多引擎 Galgame / 视觉小说一站式工具箱（Rust）— 解包/封包/汉化文本提取回填/存档编辑/MOD 管理"；README："一个为 Ren'Py、RPG Maker、吉里吉里等主流视觉小说 / RPG 游戏引擎设计的『游戏工具箱』"
  - **语言**：Rust（Tauri v2 GUI `stool-tauri.exe` + `stool-cli.exe`，仅 Windows x64）
  - **支持的引擎**（README 表格逐项声明）：Ren'Py、RPG Maker MV/MZ、RPG Maker XP/VX/Ace、KiriKiri（吉里吉里）、Artemis Engine（`.pfs` pf6/pf8）、Godot、SACT/System40、NScripter/ONScripter、HTML/Electron、Wolf RPG Editor、Unity（Mono/IL2CPP，解包借 AssetRipper）；识别不出的走 GARbro 兜底。外部依赖：unrpyc、WolfDec、AssetRipper、GARbro、GDRE Tools（README 声明可自动从其官方 Release 下载并校验 SHA-256）。
  - **许可证**：GitHub API `license.spdx_id = "MIT"`。
  - **最后活动**：**未归档**；创建 `2026-09-08`，`pushed_at = 2026-10-01T16:41:11Z`，**1 star**，6 open issues。→ **极新、无第三方验证**；README 自述 `cargo test --tests` 355 项全通过，属**自述、未独立核实**。
- **`Inori/FuckGalEngine`** — https://github.com/Inori/FuckGalEngine
  - **用途（原文）**："My tools to crack galgame"；作者 Inori（中文圈 galgame 工具作者）。**语言**：C；**`license: null`（无许可证）**；**未归档**，`pushed_at = 2022-02-06T01:52:40Z`；1,019 stars，156 forks。具体引擎覆盖 **未核实**（README 抓取被限流失败）。
- **`2439905184/Galgame-Engine-Collect`** — https://github.com/2439905184/Galgame-Engine-Collect
  - **用途（README 原文）**："# galWiki … 工具：galgame 游玩/开发/二次开发中使用的各种工具，包括引擎，模拟器，编译器 等"。这是**资料索引/百科，不是解包程序**；README 明确列出 `[解包工具表格](unpack.md)`、`[引擎表格大全](table.md)`、`[相关开发/编译工具](tools.md)`。**许可证**：API `spdx_id = "NOASSERTION"`（`name: "Other"`）。`pushed_at = 2026-06-21T07:30:15Z`，672 stars。`unpack.md` 内容 **未核实**（未读取）。
- **`Weiss-UltimateSavior/Tyranor-Next`** — https://github.com/Weiss-UltimateSavior/Tyranor-Next — **GPL-2.0**，`pushed_at = 2026-10-12T09:21:14Z`，616 stars。用途原文："多引擎视觉小说（Galgame）聚合启动器，面向 Android 平台。内置 Kirikiri / ONScripter / Tyrano / Artemis / Siglus / FVP 六套引擎运行环境，并支持 Ren'Py、RPG Maker RGSS 外置 APK 引擎模块…可识别和启动多类游戏"。**能识别引擎但不能解包**（是启动器）。
- **`M1zukiri/Gal-Extractor`** — https://github.com/M1zukiri/Gal-Extractor — "用于解包Galgame资源的应用。"；C#；**`license: null`**；创建与最后推送均为 2026-06-23；**0 stars**。成熟度 **未核实**。
- 另在 platform_search 中出现但**未抓取、未核实**：`GanFan/bruns-localizer`（Bruns 引擎汉化拆包）、`TesterNaN/KFCEngine_Tools`（KFC 自研引擎 DAT 解包）、`shapeshifterXD/vn-galgame-asset-extractor-tool`（MIT，0 stars，创建 2026-06-23）、`Code-play/GalQuiz`。→ 均为 **未核实/UNCERTAIN**。

### 10. 其他经核实的高相关工具（补充候选）
- **`trigger-segfault/TriggersTools.CatSystem2`** — https://github.com/trigger-segfault/TriggersTools.CatSystem2 — "A library for extracting from and working with the CatSystem 2 visual novel game engine."；C#；**MIT**；**未归档**，`pushed_at = 2019-03-28T17:38:24Z`（8 年未更新）；78 stars。可提取：CatSystem2 `.cst`/`.int`/`.hg2`/`.hg3` 等封包内资源与脚本。
- **`arcusmaximus/KirikiriTools`** — https://github.com/arcusmaximus/KirikiriTools — "Tools for the Kirikiri visual novel engine"；C++；**MIT**；**已归档**（API `archived: true`），`pushed_at = 2023-04-12T22:02:42Z`；434 stars。
- **`Lattyware/unrpa`** — https://github.com/Lattyware/unrpa — "A program to extract files from the RPA archive format."（Ren'Py）；Python；**GPL-3.0**；**未归档**，`pushed_at = 2022-06-27T12:05:29Z`；766 stars。
- **`shizmob/rpatool`** — https://github.com/shizmob/rpatool — "A tool to work with Ren'Py archives."；Python；**WTFPL**；**已归档**（`archived: true`），`pushed_at = 2022-08-23T18:28:07Z`；描述注明已迁移至 https://codeberg.org/shiz/rpatool 。
- **`uuksu/RPGMakerDecrypter`** — https://github.com/uuksu/RPGMakerDecrypter — "Tool for decrypting and extracting RPG Maker XP, VX and VX Ace encrypted archives and MV and MZ encrypted files."；C#；**MIT**；**未归档**，`pushed_at = 2024-12-30T14:49:30Z`；333 stars。
- **`capacitor1/ImageGlass-G00-Plugin`** — https://github.com/capacitor1/ImageGlass-G00-Plugin — "RealLive G00 codec plugin for ImageGlass"；C#；**MIT**；创建/推送 2026-10-01；0 stars。是**看图器插件，不是解包器**，仅作 RealLive `.g00` 图像解码佐证。

---

## 是否存在"自动识别引擎 → 自动调用对应解包器"的项目？

**存在一个，但是极新且未经验证：`shushui0710/STool`。**
证据（README 原文，https://github.com/shushui0710/STool ）：
- `stool-cli detect <游戏目录>` —— 注释原文"判断这个游戏是用什么引擎做的（会给出判断依据和置信度）"
- `stool-cli extract <游戏目录> -o 输出目录` —— 注释原文"把游戏资源解包出来（**自动识别引擎**；-p 可手动指定引擎）"
- `stool-cli batch <根目录> [--depth N] [--op detect|extract|...] [--csv 报告.csv]` —— "批量检测：给一个根目录，自动扫描下面所有游戏、**识别引擎**并生成 CSV 报告"
- 实现机制（README 程序结构段原文）：`engines/recognize.rs 证据打分识别`；"识别采用『证据打分』机制：游戏目录里命中的特征越多，分数越高，**超过 60 分判定为该引擎**；任何一个插件出错都不影响其他插件工作"
- 分派方式：内置引擎插件直接处理；外部引擎转交外部工具（unrpyc / WolfDec / AssetRipper / GARbro / GDRE Tools）。
**限制**：仅 Windows x64；创建于 2026-09-08，**1 star**，6 open issues，**未找到任何第三方评测或依赖它的项目**；其逐引擎解码正确性仅由作者自述。

**其他相关但不等价的机制**：
- **按"文件"而非按"游戏目录"自动嗅探**：`arc_unpacker` README 原文"It will guess the format and unpack it for you."；`GARbro` 的"按 Enter 尝试作为封包打开"也是逐文件识别。二者都**不会先判定"这是哪个引擎的游戏"再分派**。
- **能识别引擎但目的是"运行"而非"解包"**：`Weiss-UltimateSavior/Tyranor-Next`（Android 多引擎启动器，GPL-2.0）。
- **未发现任何 AI/LLM 驱动的自动解包器**：GitHub 仓库搜索 `visual novel engine detect` 仅 2 个完全无关结果；`galgame extract`（16 个结果）与 `galgame engine`（141 个结果）的头部命中均为**引擎本体、启动器、资料索引或单体工具**，没有"识别+分派"的编排器。→ **除 STool 外，未找到第二个此类项目；AI 驱动者未发现。**

---

## 未核实/存在冲突的信息

1. **`xeonlive/KrkrExtract` 不存在**（HTTP 404）；是否曾存在过 **未核实**。同名工具的正确仓库是 `xmoezzz/KrkrExtract`。
2. **`AtomCrafty/VNTextPatch` 不存在**（HTTP 404）。VNTextPatch 的正确归属是 `arcusmaximus/VNTranslationTools`（已归档，MIT）。任务书中的 owner 归属有误。
3. **`xmoezzz/KrkrExtract` 许可证冲突**：README 原文声明 "All source code files are licensed under GNU General Public License v3 (GPLv3)"，但 GitHub API `license` 为 `null`（未检出 LICENSE 文件）。**以哪个为准未核实。**
4. **`asmodean` 无官方 GitHub 仓库**；官方站点 `asmodean.reverse.net` DNS 解析失败（`getaddrinfo ENOTFOUND`），**站点现状、工具清单与日期均未核实**。其镜像仓库描述称须经作者许可方可再分发 → 非开源。
5. **`UlyssesWu/FreeMote` 不是 OSI 开源许可证**：`license.spdx_id = "NOASSERTION"`，实际为 **CC BY-NC-SA 4.0（禁止商业使用）**。若报告需要"开源许可证"结论，此处应特别标注。
6. **GARbro 的完整格式清单未核实**：`supported.html` 抓取在 50,000 字符处截断；其中 **Unity 支持**仅有间接证据（FreeMote 致谢引用了 `ArcFormats/Unity/Bc7Decoder.cs` 路径），未在 supported.html 中直接确认。
7. **arc_unpacker 的逐引擎覆盖未核实**：README 只举了 XP3/BGI/Team Shanghai Alice 三例；`GAMELIST.htm` 未逐条读取（其 README 中的 rawgit 链接为已停服域名，实际可达性未核实）。
8. **`Inori/FuckGalEngine` 支持的引擎清单未核实**（README 抓取因 Firecrawl 免费额度限流 429 失败）；其描述、语言、星数、日期、无许可证已由 API 核实。
9. **`2439905184/Galgame-Engine-Collect` 的 `unpack.md`（解包工具表格）内容未核实**；仅确认该文件被 README 链接。
10. **`shushui0710/STool` 的能力为自述**：README 自报支持引擎表、355 项测试通过、60 分阈值识别机制，均**未见独立验证**；仓库仅 1 star、创建 11 天。
11. **`M1zukiri/Gal-Extractor`、`shapeshifterXD/vn-galgame-asset-extractor-tool`、`GanFan/bruns-localizer`、`TesterNaN/KFCEngine_Tools`、`Code-play/GalQuiz`** 未抓取正文 → 用途、引擎覆盖、许可证细节 **未核实**。
12. **`xmoezzz/xp3-brute` 无许可证**（API `license: null`，未检出 LICENSE 文件）——如报告需要许可证结论，应标注"无明确许可证"。
13. **工具可用性说明**：`platform_search(platform="github")` 对多个实际存在的查询（如 "GARbro console CLI batch"、"nsa extractor nscripter"、"majiro arc extractor"、"auto detect visual novel engine extractor"）返回 0 结果，与 GitHub REST API 结果不一致。**本报告中所有仓库级事实以 GitHub REST API 与仓库 README 原文为准**，未采用 platform_search 的空结果作为"不存在"的证据。
