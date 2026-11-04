# 实测记录：工具行为与环境（证据留档）

> 记录日期 2026-10-12。这里只放**实测得到的事实**与**踩过的坑**，推断一律标注。
> AGENTS.md 只保留结论摘要；证据细节在本文件。

## 2026-11-02 Unity 音频（FSB5）补齐——Happiness Double Room 全链首次通过

**现象（量化）**：`Happiness Double Room`（Unity 2021.1.9f1 / Mono）JSON 枚举 **1441 个 AudioClip**，
单次 Convert 只落盘 **293～446 个**（同一命令不同次运行数字不同），四次运行退出码**全部 0**、
逐条 `Exporting AudioClip: X` 日志齐全、无任何报错。此前一轮多轮累积停在 **761**。

**排除的三个假设**：
| 假设 | 做法 | 结果 |
|---|---|---|
| 同名覆盖 | 逐条枚举 1441 条的 `m_Name` | **1441 个名字全唯一**，0 重复 → 不是覆盖 |
| 批量阈值导致崩溃 | 同一批 80 个名字连跑两次 | 一次 **80/80**、一次 **28/80**，`rc=0` 两次 → 随机丢失，不是规模阈值 |
| 单名也导不出 | `--names "^1000\.0$"` 等三个单名 | 各 **1/1** 成功 → 单名稳定 |

**结论**：AssetStudio 对 FSB5 源的 AudioClip 是**随机性静默丢失**，同一批名字重复跑每次落盘子集不同
（偶发批量极大时还有 access violation 段错误）。**退出码与日志都不能当成功判据，只能按名字数产物。**

**新策略（`_as_audio_collect2.py` 重写）**：① JSON 枚举拿到全部名字（`--group_assets BySource`，
ByType 会让同名 JSON 互相覆盖）② 50 名一批、锚定正则 `^(a|b)$`（名字里的 `.` 必须 `re.escape`）③ 落盘后
**逐个名字核对**，只把缺的收进下一轮，批量逐轮减半 ④ 补不齐就报 `missing`，不静默放过。
实测：**58 次运行 / 4 轮 / 1441 个全部补齐 / 缺 0**（batch 50→25→12→6），约 12 分钟。

**旧策略为什么停在 761**：round1 的 `^[0-9]` 一次只捞到 149 个数字名；round2 恰好**一个都没新增**，
于是「连续无新增，提前结束」直接 break——**「这一批没新增」不等于「剩下的也没有」**，该提前结束判据是错的。

**全链结果**：`3500/3500 对账 diff=0`，图片 **2059/0 失败**、音频 **1441/0 失败**、无视频，媒体 186.8 分钟，
全链 **902.1s、退出码 0**（同配置两次全链均 rc=0，另一次 789.0s；此前音频 761 时该链路对账必失败）。

**顺带修掉的三处口径/工程问题**：
- `source.archives` 三个 `null`：Unity 阶段用了 `name/entries` 键，而 `build_manifest` 只认
  `archive/expected/got` → 交付记录里三个存档名全是 null。已统一键名并加回归测试。
- 产物搬迁原为「复制到 raw/ + 删临时目录」，本样本要**多占 2 GB**；改成**一次改名**（同盘）。
  注意：目标目录已存在时（断点续跑）必须走合并，否则本轮新产物会随临时目录一起被清掉。
- 本机删除守卫（`sitecustomize` 的 safe-delete）：**>50 个文件的批量删除要人工确认**，抛的是
  `BaseException` 系，`shutil.rmtree(ignore_errors=True)` **拦不住**（第一次复跑就是这样在「数 JSON」
  之后 8 秒整条链中断）。→ 临时目录改「唯一名 + 尽力清理（吞 BaseException）」，删不掉就留着；
  `_work/unity/` 下会残留若干 `_json_*`/`_conv_*` 目录（每个几 MB），可手工清。

## 2026-11-02 打包 GARbro 插件加载

- 同一パート妻 data.xp3：外部 GARbro 列出 2562 项，旧打包版返回 `unknown format`；两份 127 个文件的 SHA-256 均一致。旧打包版 `-l` 仅输出标题，外部版列出 656 种格式。
- 打包目录中 ArcFormats.dll 通过 .NET `Assembly.LoadFrom` 加载时报 `0x80131515`；该文件没有 Zone.Identifier 数据流，具体触发来源判定的系统因素未确定。为随包 GARbro 配置 `loadFromRemoteSources enabled="true"` 后，实际重新打包副本可列出原始封包 2562 项、退出码 0。此设置放宽 GARbro 进程的程序集加载限制，随包目录必须可信。
- .NET 对 assemblyBinding 的原有默认命名空间写法敏感；使用 minidom 保留配置原写法，不能使用 ElementTree 默认的 ns0 前缀重写。

## 2026-11-02 三项反馈修复进度

- 动态兜底补充实测：对パート妻真实注入生成新 data.xp3.index，测试进程将窗口查找结果强制设为不存在，兜底逐条校验并提取 2562 文件，退出码 0。自然运行时窗口实际存在，未自然复现窗口缺失；首次正常窗口流程因 Explorer 窗口未找到而中断。测试暂存与产物保留在 _extracted/krkr_dynamic_test_stage 和 _extracted/krkr_dynamic_test_output。

- Unity 临时目录原落在游戏目录，报 WinError 5；现改到输出侧，自动测试覆盖。Happiness Double Room 已越过原权限错误。一次试跑约 12 分钟后中止；另一轮保留的日志显示音频收集器自行结束，1441 个枚举 AudioClip 最终只落盘 761 个 WAV。旧第二轮 150 个模式只覆盖 VA/VB/VC，但样本大部分音频名以数字开头；原按内容哈希去重也可能丢失不同名称的同内容文件。未完成对账与媒体验收，不能宣称全链成功。
- Artemis 的三个 Toshiue pf8 归档真实索引数为 3282、624、71，均有独立索引。原实现从偏移 11 而非 7 读取索引；修正后实际全链运行退出码 0：归档 3977 条加散装媒体 31 个，对账 4008/4008；图片 1007/1007、音频 2597/2597、视频 1/1，失败 0，耗时 235.5 秒。
- 高慢妻的 data.xp3.index 含 2838 项，先前逐段检查 Adler32 为 2838/2838；本次新解析器对真实封包成功提取 2838 条并逐条校验 Adler32，但尚未验证 GUI 失败后自动获得索引及输出交付。另一游戏索引含不支持的条目标志，解析器明确拒绝，不能推广到所有 XP3。用户反馈的パート妻样本本次运行时 GARbro 直接成功：2562/2562 对账零差、507 个 TLG 全转出，图片 902/902、音频 1577/1577，退出码 0；因此本次没有触发索引兜底，差异已复现：旧打包副本的 .NET 插件加载失败；详见上方「打包 GARbro 插件加载」。
- 自动测试 511 passed、12 skipped；golden 检查 6 fixture、12 个真实样本无漂移。这不是三个目标游戏的全链验收。

---

## 1. GARbro：Console ≠ GUI（代价最大的一个坑）

**事实**
- 用户用 **`GARbro.GUI.exe`** 实测 `D:\HY\pork社` 全部 7 个游戏：**均无静态加密，均可直接提取解包**。
- 但 **`GARbro.Console.exe`** 对其中 4 个报 `unknown format`——**列表与 `-x` 解包都失败（输出 0 个文件）**：
  `高慢妻陥落！！`、`堕落妻子`、`昼下がり、欲求不満の人妻たちは…`、`昼下がりの団地妻たち`。
- Console 能读出的仅 3 个（`パート妻の情事` 2562 条、`兼职人妻` 2562 条、`温泉蒸汽人妻` 3425 条）。
  （2026-10-29 用 `toolbridge.garbro_list()` 复测纠正：旧记 2561/2561/3424 是 `len(lines)-1` 口径错误的产物——
  GARbro 列表输出**对 xp3 也无表头**。见 §7 与决策树 §2.4。）
  其中 `兼职人妻` = `パート妻の情事`，是**同一个游戏**（544.7 MB 完全相同）。

**已排除的原因**
| 假设 | 验证方式 | 结果 |
|---|---|---|
| Console 版本旧、格式支持少 | 比对版本/日期/依赖 | ❌ 同为 **x86**、**同日构建 2026-07-20**、**共用 `ArcFormats.dll` 1.2.48.2200** |
| 工作目录不对（找不到 GameData） | 从 GARbro 目录内运行 | ❌ 同样失败 |
| Console 缺数据文件 | 检查 `GameData/`；`-l` | ❌ `Formats.dat`(1.9MB) 正常，`-l` 列出 **657** 种格式（含 `XP3 KiriKiri引擎压缩文件`） |
| 只是列不出、其实能解 | 实跑 `-x` 到空目录 | ❌ 一样失败，输出 0 文件 |

**原因：[未核实]** 怀疑 GUI 会交互式选择「游戏标题/密钥」（`GameData/` 下确有 `kirikiri_bracon.lst`、`kirikiri_keikan.lst` 等按游戏的密钥表），而 Console **没有**任何指定标题/密钥的选项。
→ **待用户确认：GUI 打开那 4 个游戏时是否有选标题/输密钥的弹窗。**

**可复用规则**
> Console 报「读不出」**不可信**；只能把「可识别」当作**正面证据**。拿不准就用 GUI 复核。

**Console 用法**
```
GARbro.Console.exe <archive>          # 无选项 = 列出条目（只读、快）
GARbro.Console.exe -x <archive>       # 解包（输出到当前目录）
GARbro.Console.exe -l                 # 列出它认识的格式（657 种）
```

---

## 2. 「静态预测能否解包」——两种判据均证伪，勿再重试

| 判据 | 预期 | 实测结果 |
|---|---|---|
| 全文件搜 UTF-16LE 扩展名标记 | 标记多→明文→能解 | ❌ **两个方向都错**：`高慢妻陥落！！` 1159 标记却读不出；`温泉蒸汽人妻` 0 标记却读出 3424 条 |
| 解析 XP3 索引长度（`index_offset` → flags&0x80 → uint64） | 长度 0→索引被剥→不能解 | ❌ **不判别**：6 个全是「索引长度=0」，却 3 个能读、3 个不能 |

**根因**：第一种测的是「文件里有没有 UTF-16LE 日文文本」，与「索引能否解析」无关；第二种我连字段都解析错了。

> **教训：不要预测工具行为，直接调用工具。** 一个「地面真相」来源本身也必须先被验证——我曾把未验证的 Console 输出当权威，得出了完全错误的结论。

相关脚本：`_probe_xp3.py`、`_probe_magic.py`、`_validate_index.py`（均已废弃；**2026-10-13 已删除**，结论与证伪理由完整保留在本节，不需要再跑它们）。

---

## 3. 归档内容为明文（即使用工具读不出）

```
高慢妻陥落！！/data.xp3   692 MB   OggS×20922  PNG×436  JPEG×345  TLG×865  MP4×1
game/data.xp3            1672 MB   OggS×94917  PNG×513  JPEG×764  TLG×1069 MP4×1
arc/bgm.xp3                86 MB   JPEG×4399  OggS×1349  RIFF/WAV×3
```

**两个结论**
1. ~~**这批游戏确实有视频**（发现 `MP4`/`ftyp` 魔数）。~~ ← **已证伪，见 §7。纯魔数扫描会大量假阳性，必须交叉定位。**
2. **carve（按魔数扫描提取）技术上可行**，且不需要游戏能运行。但因 GUI 已能正常解包，**现降级为备用方案**。

---

## 4. Unity 判定（首个真实游戏）

`D:\HY\My Wife Wants to Be a Professional Cosplayer`
- 引擎 **Unity 2022.3.62f2**、脚本后端 **Mono**、发行商 GentlemanGame（读自 `app.info`）
- 版本号读法：从 `globalgamemanagers` / `level0` 前 4KB 正则 `\d+\.\d+\.\d+[a-z]\d+` 提取（无需解析 PE）
- **无 `StreamingAssets/`、无 `.bundle`** → 资源在 `resources.assets` + `resources.assets.resS`（**1372 MB**）+ `resources.resource`
- 因 2022.3 ≠ Unity 6000 → **用 AssetStudio 原版即可**，无需 AssetStudioNext；Mono → 无需 Il2CppDumper

---

## 5. 乱码文件名还原（已实测正确）

`D:\HY\pork社\昼下がりの団地妻たち ～熟れた匂いとムレた肌～` 中有 3 个 Shift-JIS 名被按 GBK 解读的文件：

| 乱码 | 还原 |
|---|---|
| `僼傽僀儖攋懝僠僃僢僋僣乕儖.exe` | `ファイル破損チェックツール.exe` |
| `僼傽僀儖攋懝僠僃僢僋僣乕儖.ini` | `ファイル破損チェックツール.ini` |
| `拫壓偑傝偺抍抧嵢払.cf` | `昼下がりの団地妻達.cf` |

**还原法**：把名字按 **GBK 编码回字节**，再按 **Shift-JIS 解码**；若结果含假名则认定是乱码。
→ 这类名字会让 **FFmpeg concat 报 `Invalid argument`**，正是教程里那条「另存为 UTF-8」的坑。

---

## 6. 环境

### shell（pwsh）
- **现象**：`workspace-write` 模式下所有 pwsh 命令立即失败，退出码 `3221225794`（`0xC0000142` `STATUS_DLL_INIT_FAILED`），连 `echo probe` 都失败。文件读写工具正常。
- **已排除**：不是 PowerShell 损坏——`C:\Program Files\PowerShell\7\pwsh.exe` 存在，安装完整（827 个 DLL，含 `coreclr.dll`/`clrjit.dll`），.NET 运行时 6/8/9/10 齐全。
- **根因**：DSH 的 Windows pwsh 沙盒组件 `@deepseek-ai/dsh-pwsh-sandbox`（`disabled: process.platform !== 'win32'` → 在 win32 **启用**）在 `workspace-write` 下无法启动 PowerShell 7。系统提示称该模式本应运行于 FullLanguage，故属**非预期行为（疑似 DSH 缺陷）**。
- **解**：逐条 `sandbox_permissions: danger-full-access` 可成功（已实测，返回 `pwsh 7.6.4`）；或整会话切「完全权限」（= `cordis.yml` 的 `danger-full-access: {sandbox, approval: never}`）。
- **当前状态**：用户已切到**完全权限** → pwsh 可直接运行，**不要设置 `sandbox_permissions`**（approval 已禁用，带该参数会被自动拒绝）。

### 命令行 CJK
把中文/日文写进 pwsh 命令传给 Python 会被**乱码**（GBK 控制台）。→ 让 PowerShell/Python **自行从文件系统解析路径**（如 `Where-Object { $_.Name -like "pork*" }`），不要把 CJK 字面量写进命令。

### 抓取
`web_fetch` / `read_page` 依赖的 Firecrawl 会限流（429）→ 失败时改用 `api.github.com/repos/<owner>/<repo>`（紧凑 JSON）。

---

## 7. 首次完整跑通解包 → 后处理 → 验收（`兼职人妻`，2026-10-12）

样本：`D:\HY\pork社\兼职人妻\data.xp3`（544.7 MB）。KiriKiri，仅一个主包，**GARbro.Console 可识别 2562 条，`-x` 8 秒解完**。
（2026-10-29 复测纠正：旧记 2561 条是 `len(lines)-1` 口径错误——GARbro 列表输出对 xp3 同样**无表头**，
条目数 = 非空行数。同一份包的另一目录 `パート妻の情事` 实测 size 与首 1MB SHA 完全一致，确系同一游戏。）

### 7.1 ⭐ 纯魔数扫描会大量假阳性，**必须交叉定位到条目起始**

对原包按魔数全扫，再拿每个命中的**绝对偏移**去比对 GARbro 条目表（`偏移 → 包内路径`）：

| 魔数 | 命中 | 判定 | 证据 |
|---|---|---|---|
| `ftyp`(MP4) | 0 | — | 无 MP4 |
| `FLV\x01` | 1 | **假阳性** | 偏移落在 `image/cg35_6.tlg` **内部**第 118683 字节 |
| `\x00\x00\x01\xba`(MPEG-PS) | 18 | **假阳性** | 落在 `bgm/ending2.ogg` 内部第 1389334 字节 |
| `\xff\xd8\xff`(JPEG) | 540 | **假阳性** | 落在 `bgm/ending1.ogg` / `ending2.ogg` 内部 |
| `OggS` | 72126 | 真 | 命中偏移 = `bgm/ending1.ogg` **条目起始 0** |
| `PNG` | 395 | 真 | 命中偏移 = `fgimage/fg_dummy.png` **条目起始 0** |

> **判据**：魔数命中偏移 **== 条目起始偏移** 才算真文件；落在条目内部的是压缩数据里的巧合字节。
> **这修正了 §3 的旧结论**：「pork 社这批游戏有视频」是错的——那次 `MP4`/`ftyp` 命中同样是没做交叉定位的假阳性。
> `兼职人妻` 的 `video/` 下只有 `～このファイルは削除してかまいません～.txt`（36 字节，「此文件可删除」）＝ KiriKiri 占位文件。**本作确实没有视频。**

### 7.2 `.tlg` → PNG 实测

- 全部 **507/507 成功，0 失败**，耗时 **73.8 s**（≈145 ms/个，瓶颈是进程启动开销，非解码）。
- 产物：326.8 MB PNG。原 `.tlg` 合计 183.3 MB。
- `tlg2png` 对带 alpha 的图会打印 `Tag found: mode = addalpha`；退出码 0。
- 尺寸分布印证游戏年代：**800×600（4:3）486 张**、立绘 527/528×600、另有 6 张 800×1200。

### 7.3 验收实测（决策树 §6 四项判据**首次全部跑通**）

| 判据 | 实测 | 方法 |
|---|---|---|
| 非空 / 无 0 字节 | 2562 文件，**0 字节文件 0 个** | `Get-ChildItem` 过滤 `Length -eq 0` |
| 图片可开 | **902/902** | Pillow `im.verify()` + 重开读 size/format |
| 音频可开 | **1577/1577** | `ffprobe -show_format -show_streams` 读 codec/sr/duration；vorbis，总时长 **217.7 分钟** |
| 数量合理 | CG 422 / 背景 83 / 立绘 261 / BGM 14 / 语音音效 1563 | 均 ≫1，无静默失败 |
| 与包名相符 | 各子目录内容与语义一致，无串包 | — |

> **⚠️ 2026-10-29 纠正：图片数是 902，不是 903。** 旧记录写「903/903」是错的。
> 三重独立验证：① 索引 2562 条按扩展名 `Counter({'ogg':1577,'tlg':507,'png':395,...})`，
> 图片来源 = 395 png + 507 tlg = **902**（无重名、无大小写变体）；② 历史解包目录
> `D:\HY\pork社\兼职人妻\已解包\` 实测 png 902（根目录 395 + `png/` 507），`manifest.csv` 分类
> `image/PNG 902`，游离 PNG 0 个；③ 本文 §7.1 表格自己写的就是 `PNG | 395` + `tlg 507` = 902，
> 与旧 §7.3 的 903 自相矛盾。**教训：同一节的表格之间也要交叉对账，别只对外部数字对账。**

### 7.4 本例**不适用**的两条后处理分支（省得下次白找工具）

- **E-mote 立绘分支不适用**：全包**无 `.pimg` / `.psb` / `.mtn` / `.emo`**。`fgimage/` 是 **261 张已合成好的整张 PNG**（`fg_友美_黒下着_微笑み.png`）→ **FreeMote + krkrFgiEditor 那一步不需要**。
- **语音 concat 分支不适用**：`sound/` 是 **1563 个平铺 `.ogg`**，但文件名是**语义名**（`挿入.ogg`、`喘ぎ.ogg`、`電車内.ogg`），**不是数字序号** → 没有「按序号拼接」的自然合并方式。真要按场景合并必须解析 `scenario/*.ks` 的语音标签，**不能靠文件名规则完成**。

### 7.5 统计口径的坑（我这次又踩了一次）

用 `& $gb $xp3 2>&1 | Select-Object -Skip 1` 统计条目时，**首行 `.tlg` 被吃掉**，导致 `bgimage` 数成 82（实为 83）、`.tlg` 总数数成 506（实为 507）。
→ **计数差异必须对账到 0**，不要用「差不多」放过。本例的原始目录构成（507 = image 422 + bgimage 83 + fgimage 2）与索引完全一致。

### 7.6 Python 输出的 CJK 乱码

`python _scan_video.py` 打印路径时中文变 `??`（GBK 控制台）。**解**：在 pwsh 里先设 `$env:PYTHONIOENCODING='utf-8'`；`galgame_dispatch.py` 内部已用 `SetConsoleOutputCP(65001)` 自行处理，无需外部设置。

### 7.7 本次新增/使用的脚本（工作区 `D:\K\deepseek\`）

| 脚本 | 用途 |
|---|---|
| `_scan_video.py` | 按魔数扫描归档，统计各类容器命中数与前若干偏移 |
| `_locate.py` | **把魔数命中偏移与 GARbro 条目表交叉定位**（证伪假阳性的关键工具） |
| `_tlg2png_all.ps1` | 批量 `.tlg`→PNG + 逐个校验 PNG 魔数，带失败清单 |
| `_verify_audio.py` | 逐文件 ffprobe 解码校验（codec/采样率/时长） |
| `_verify_images.py` | 逐文件 Pillow `verify()` 校验（尺寸/格式分布） |
| `_manifest.py` | 产出 `manifest.csv`（relpath / category / bytes） |

---

## 8. Unity 分支首次实操（`My Wife Wants to Be a Professional Cosplayer`，2026-10-13）

样本：`D:\HY\My Wife Wants to Be a Professional Cosplayer`。
**Unity 2022.3.62f2 / Mono 后端**（→ 原版 AssetStudio 即可，**无需** AssetStudioNext / Il2CppDumper）。
无 `StreamingAssets/`、无 `il2cpp_data/`；资源在 `resources.assets`(97.9 MB) + `resources.assets.resS`(1372 MB) + `resources.resource`(146.7 MB)。
引擎是 **Naninovel**（`Managed/Elringus.Naninovel.Runtime.dll`）。

### 8.1 ⭐⭐ AssetStudio.CLI 的 `--types` 参数：逗号会「静默归零」

这是本次最大的时间陷阱。同一份输入，只改类型参数的写法：

| 写法 | 产物 | 说明 |
|---|---|---|
| `--types AudioClip` | 正常 | 单类型有效 |
| `--types AudioClip,Texture2D,Sprite` | **0 个文件** | **逗号被静默忽略，退出码仍是 0**，日志末尾只有 `Nothing exported` |
| `--types 'AudioClip\|Texture2D\|Sprite'` | 1898 个 | 过滤器**整体失效** → 退化成「导出全部」（连没请求的 MonoBehaviour/TextAsset/Material 都出来了） |
| 不用 `--types` | 全部 | **最省事**：不过滤，一次拿全，再按子目录挑 |

> **结论：不要用逗号分隔 `--types`；要么只给单类型，要么干脆不写。**
> 更关键的是——**exit code 0 完全不能当作成功判据**。

### 8.2 ⭐ 我自己造成的假故障：`Start-Process -ArgumentList` 不自动加引号

我一度用 `Start-Process -FilePath ... -ArgumentList @($data,$out,...)` 调用 CLI，
结果 `D:\...\My Wife Wants to Be a Professional Cosplayer_Data` 被**按空格拆碎**
（stderr 报 `Unrecognized command or argument 'Wants'` 等），CLI 只打印了 help。
而我当时**只看日志最后几行**（`Nothing exported`），就把它当成了「AssetStudio 导不出音频」的证据。

> **两个教训**：
> 1. **PowerShell 里调外部程序一律用调用符 `&`**（自动引号），不要用 `Start-Process -ArgumentList` 传含空格路径。
> 2. **又一次「只看尾部日志就下结论」**——与 §1 的坑同源。**必须看完整日志开头**（`Found N files`、`Detected Unity version` 这类行只在开头）。

### 8.3 一次性全导会在收尾崩溃

`--export_type Convert` 不带 `--types` 全量导出（约 870 MB）时进程崩溃：
退出码 **`-1073740940` = `0xC0000374`（STATUS_HEAP_CORRUPTION，堆损坏）**。
崩溃时 `Sprite` 只出 225/322、`Texture2D` 452/460，**而且不出现在日志里**。
→ **改按类型分批独立导出**（每批一个目录、一份日志、各自校验），三批全部干净完成。

### 8.4 本作实测产物（已逐个校验）

| 类别 | 数量 | 体积 | 验收 |
|---|---|---|---|
| PNG 图片 | **777**（Texture2D 455 + Sprite 322） | 348.1 MB | Pillow `verify()` **777/777** |
| 音频 | **1168** WAV | 1231.0 MB | ffprobe **1168/1168** 可解码，`pcm_s16le`，总时长 **121.7 分钟** |
| 视频 | **0** | — | 见 §8.6 |

分辨率以 **1920×1080（133 张）** 与 2048×1152（32）为主。

### 8.5 ⭐ FSB5 音频：CLI 静默导不出，靠「分组多轮」捞全

**现象**：`resources.assets` 里有 **1183 个 AudioClip**，CLI 单次导出只落地 **8 个**。
日志里**每一个都打印** `[Info] [i/1183] Exporting AudioClip: X`，**没有任何 Warning/Error**，
末尾却是 `Finished exporting 38 assets. 1145 assets skipped (not extractable or files already exist)`。

**真因**：AudioClip 的 `"m_Source": "resources.resource"` + `m_Offset`/`m_Size`，
读出来是 **`FSB5`（FMOD Sample Bank 5）**容器（`46 53 42 35`），不是裸 Vorbis。
AssetStudio 用同目录的 `fmod.dll` 解 FSB5，但成功率很低且**静默失败**。

**已排除的两条替代路线**（别再试）：
- `pip install fsb5`（HearthSim/python-fsb5）能解析 FSB5 头（VORBIS/48kHz/2ch），
  但 `rebuild_sample()` 需要原生 **`libvorbis`+`libogg`**，且依赖一张**预存的 vorbis setup header 查表**
  （`vorbis_header_lookup[crc32]`，查不到直接 `ValueError`）→ 脆弱，弃用。
- **FFmpeg 也不行**：能识别 FSB 容器，但对本作的编码报 `Not yet implemented in FFmpeg, patches welcome`。

**✅ 可用解法：按名字正则分组，多轮反复跑，按内容哈希累积。**
依据是实测发现**失败取决于单次运行内的处理顺序/规模**——换分组就能多捞一批。实测曲线：

| 阶段 | 累计 |
|---|---|
| 单模式分批（`^VA1`、`^VA2`…） | 689 |
| 第 1 轮：合并 alternation `^(VA0\|VA1\|…\|VA9)` 等 69 个模式 | 993 |
| 第 2 轮：两两组合 `^(VA10\|VA11)` 等 150 个 | 1132 |
| 第 3 轮：单个两位前缀 300 个 | 1163 |
| 收尾：**精确锚定** `^(click01\|VA1011\|VA1022\|VA1065\|VC4)$` | **1168 = 100%** |

> **关键技巧**：最后一击是 **`^(A|B|C)$` 精确锚定**——把「逃掉的那几个」用完全匹配的正则单独成组，
> 一次全出。**先分组跑大面，再用精确锚定清尾巴。**

### 8.6 本作**没有视频**（用 AssetStudio 枚举 + 交叉定位双重确认）

- AssetStudio 枚举了**全部资产类型**：`VideoClip` **数量为 0**。
- 对 1372 MB 的 `resources.assets.resS` 做魔数扫描，`ftyp`/`mdat`/`moov`/`OggS` 等都有命中，**但周围全是乱码**：
  ```
  ftyp ctx: b'\xb1\x81Xw[af\x19ftyp\xa7j\xa0r\xa8\x91\xa6\x9c\x08\xf4\xdb\xa4'
  mdat ctx: b"\xe1\xe1\xe1\xe1\xa8\xa8\xa7\xa9mdatD0'V-\x1a\x12>\x1c\x10\x0b'"
  ```
  （1372 MB 里只有 **1 个**巧合 `OggS`）→ **全是压缩数据内部的巧合字节**，与 §7.1 的判据一致。
- 游戏的「动态 CG」由 **Spine 骨骼动画**实现：每个 CG 是 **`CGxx.atlas` + `CGxx.skel`（TextAsset）**，
  图集页恰好是**同名的 Texture2D 资产**（实测 `CG01.atlas` 引用 `CG01.png, CG01_2.png`，
  与 `CG03`=3 页 / `CG07`=7 页 完全对应）。共 18 个 CG 动画 + 12 个剧情动画。

> ⚠️ 注意 `Texture2D` 与 `Sprite` 高度重叠：Sprite 是 Texture2D 的裁剪区（322 个 Sprite 里有 318 个的名字
> 都能在 Texture2D 里找到同名项）。两套各有用途，但体积会翻倍，交付时要说明。

### 8.7 资产画像（AssetStudio JSON 枚举，共 2883 条）

- **音频 1168**：语音 675（角色 A=`VA`）+ 260（角色 C=`VC`）+ 131（角色 B=`VB`）、BGM 19、成人音效 25、系统音效 1、其余音效 57
- **图片**：Texture2D 460 / Sprite 322 / TextAsset 214（含 Spine）/ MonoBehaviour 490 / Material 94 / Shader 70 / Mesh 42 / Animator 14 / AnimationClip 9

### 8.8 本次新增脚本

| 脚本 | 用途 |
|---|---|
| **`unity_unpack.ps1`** | Unity 解包主流程（分批导出 + 引擎判定 + 验收提示），已内置 §8.1–8.3 三个坑的注释 |
| **`_as_audio_collect2.py`** | FSB5 音频多轮分组累积导出（§8.5 的解法） |
| `_as_audio_collect.py` | 上一版（单模式分批，慢但可用，留档） |
| `_as_catalog.py` | 按命名规律给音频/图片分类画像 |
| `_as_summary.py` | 汇总 AssetStudio JSON 枚举结果（按类型统计） |
| `_scan_unity_video.py` | 用 mmap 在 Unity 大数据文件里找视频魔数（带上下文，便于判假阳性） |

### 8.9 ⭐ 临时目录绝不能写进游戏目录

**现象**：`orchestrator` 对 `Happiness Double Room` 跑 Unity 链路时，`_unity_extract.py` 用 `data_dir.parent / f"_json_{t}"` 把临时目录建在游戏根目录 `D:HYHappiness Double Room_json_Texture2D`，受保护/只读游戏目录下 `mkdir` 直接抛 `PermissionError: [WinError 5] 拒绝访问`，与 Unity/AssetStudio 版本无关。

**修法**：`tmp_root=ctx.work_dir/"unity"`，`_json_*/_conv_*/Audio_work` 等 AssetStudio 暂存目录全部落在输出侧（`ctx.work_dir`/`out_dir` 下），**严禁 `data_dir.parent`**。新测试 `test_orchestrator.py::test_unity_scratch_never_writes_into_game_dir` 已放宽：保留“临时目录绝不能在游戏目录”，仅对 `_json_*/_conv_*` 要求在 `out_dir` 或 `work_dir` 下。

> **结论**：临时产物一律落输出侧；游戏根目录只读不写（避免污染原包，也避免权限拦截）。

---


## 9. Ren'Py 分支首次实操（`My Best Deal v4.7`，2026-10-14）

样本：`D:\HY\最佳的交易\My_Best_Deal_v4.7-pc`。**Ren'Py / Python 2.7**（`lib/python2.7/`）。
`game\archive.rpa` **5863.4 MB / 8248 条目**；`game\patch.rpa` 23.4 MB / 101 条目。
**这是本项目第一个真有视频的样本**（见 §9.3）。

### 9.1 ⭐ RPA-3.0 索引有两层「包装」，只看表头解不开

表头（`\n` 前）看起来是「空格分隔的明文」，实际被**异或混淆**过：

```
RPA-3.0 000000016e743562 42424242.Made with Ren'Py.RENPY RPC2
                                     ^^ 第 32 字节是 '.' 而不是空格
```

**两个坑叠在一起**，第一版脚本直接报 `_pickle.UnpicklingError: invalid load key, 'x'`：

| 层 | 事实 | 不处理的后果 |
|---|---|---|
| ① 空格被替换 | Ren'Py 把分隔空格换成**什么字符由游戏决定**（本作 `.`） | `split(b" ")` 切不动 |
| ② **索引 zlib 压缩** | 索引偏移处是 **`78 9C`** 开头的 zlib 流，不是裸 pickle | `pickle` 读到 `0x78` → `invalid load key, 'x'` |

**正解**（`rpa_tool.py` 已实现）：
1. 读第一行，用**正则** `^RPA-3\.0 ([0-9a-f]{16}) ([0-9a-f]{8})` 抓偏移与 key（**不要 `split(b" ")`**）；
2. 定位偏移后，若首字节 `0x78` → 先 `zlib.decompress`；
3. 再 `pickle.loads` 得 `{name: [(offset, length, prefix)]}`；
4. 每个 `offset`/`length` **都要 `^ key`**（本作 `0x42424242`）。

> **走过的弯路**：我一度以为「空格被换成 `.`」意味着**偏移数字也被异或过**，去试「把十六进制文本按 `0x2E` 解混淆」。
> **这是错的**——用文件大小即可证伪：`0x16E743562` = 6,148,076,898 < 文件大小 6,148,267,088，
> 且距文件尾 190,190 字节（正是 zlib 指数的大小）。
> **教训：字符串看起来坏 ≠ 值坏；先用「文件大小」这类物理约束验证，再动手解混淆。**

### 9.2 patch 是「新增」还是「覆盖」——用索引对账，别猜

`patch.rpa` 在 `game\` 与 `v4.7 Patch\` 下**两份完全相同**（同 24,525,836 字节 / 同索引偏移 `0x1763355` / 同 101 条目）。
两份索引求交集：**0 个重名** → 该补丁是**纯新增**，**无需合并覆盖**。

### 9.3 首个含视频样本：288 个视频 / 71.2 分钟

| 分类 | 编码 | 分辨率 | 数量 | 体积 |
|---|---|---|---|---|
| `Video_AVI` | **mpeg4** | 1920×1080 | 170 | 1645.6 MB |
| `Video_WebM` | **vp9**（116）+ vp8（2），含 **Opus** 音轨 | 1920×1080 | 118 | 411.3 MB |

主体是 H 场景动画（`images/animations/a1.avi`…），另有片头 `images/video/after_disclamer_video.avi`。
**已抽帧视觉确认**（`ffmpeg -ss 1 -frames:v 1`），画面正常。

> ⚠️ **ffprobe 的「视频流数」≠「视频文件数」**：本作有 24 个 mp3/图片内嵌封面，
> ffprobe 会把封面报成 `codec_type=video`（`codec_name=png`），于是「318 个视频流」里约 30 个是封面。
> **要按文件扩展名数视频，不要按 ffprobe 的 stream 数。**

### 9.4 ⭐⭐ 分类归档必须「扩展名优先」，**绝不能只按目录判**

第一版 `_organize_rpa.py` 只按目录分类 → 把 **282 个 jpg 错分进 `Video_WebM`**（该类瞬间 396 个）。
因为 `images/animations/` 下**同时存在** `.avi`(166) / `.webm`(115) / `.jpg`(283)。
同类陷阱：视频还散落在 `images/mm/`、`images/notes/`、`tl/chinese/images/animations/`。

**正解**：先按**扩展名**认媒体本体，再退回按目录分；`tl/` 视为本地化补丁树整体保留。

**还有一个更贵的错**：随后写的 `_reclassify.py`（原地重分类）把「已归档目录名」误当包内路径，
又把 282 个文件分成了 `Image_a1.jpg/`、`Image_a10.jpg/` 这类**单文件目录**，且**已移动的文件无法可靠还原原位**。
→ 最后**删掉重来**：从原始归档重新解包只花 **31 秒**。

> **规则：分类逻辑一旦发现错了，最省时的做法是「修逻辑 + 从源归档重跑」，而不是写迁移脚本原地修数据。**
> 源归档没动过，重跑是确定性的；原地迁移要处理「已移动/未移动」混合状态，越修越乱。

### 9.5 实测性能

- 5863.4 MB / 8248 条目 **解包 31 秒，187 MB/s**（纯 Python `seek`+分块读，无解压）。
- RPA 内文件是**裸存**（`offset`/`length` 直取），速度只受磁盘限制。
- 计数对账**逐扩展名完全一致**：
  `jpg 6891 · png 913 · avi 170 · webm 118 · rpyc 101 · mp3 47 · otf 3 · rpyb 2 · rpym 1 · rpymc 1 · txt 1` = **8248**

### 9.6 验收脚本的局限：别把非媒体文件送 ffprobe

`_verify_media.py` 第一版把「不在图片白名单里的都用 ffprobe 试」，
于是 `.rpyc`/`.otf`/`.txt` 全部报 `Invalid data found when processing input` → **108 项假失败**。
**修正**：加 `AV_EXT` 白名单，只有真媒体才送 ffprobe，其余归 `nonmedia/*` 单独计数。
→ 修正后：图片 **7804/7804**、视频 **288**、音频 **47**，失败 **0**。

### 9.7 本次新增脚本

| 脚本 | 用途 |
|---|---|
| **`rpa_tool.py`** | RPA-2.0/3.0 解析：`info` / `list` / `extract`（支持 `--only`） |
| **`rpa_extract_organized.py`** | 一步「解包 + 按类型分类」写盘，避免先全解再搬运的两次 I/O |
| `_organize_rpa.py` | 先解到暂存再分类（分类逻辑同上，留作参考） |
| `_reclassify.py` | 原地重分类（**已证明是弯路**，仅留档警示，见 §9.4） |
| `_verify_media.py` | 统一媒体验收（Pillow / ffprobe，带扩展名白名单） |
| `_check_rpa_verify.py` | 核对验收 CSV，区分「真媒体失败」与「非媒体误判」 |

---

## 10. Electron/asar 自研引擎首次实操（`SPITE`，2026-10-25）

样本：`D:\HY\SPITE`（1.08 GB）。分派器判定 Tyrano/Electron（90 分，判定正确但引擎**不是 TyranoScript**，
是**自研 Electron 引擎**：pixi-vn + Ink + Spine + React，带 steamworks.js）。**AsarKit 没用上**。

### 10.1 结构：asar 只有引擎，媒体在外部且加密

- `resources/app.asar` 51.7 MB = 纯应用代码（dist/ + node_modules，**媒体 0 个**，只有字体/svg）。
- `data/` 164 个哈希名 `.dat`（736 MB）+ `resources/app.asar.unpacked/`（steamworks 原生库）。
- `.dat` 头部全为高熵随机字节、无任何魔数 → **资源全部加密**（162 个独立文件 + 1 个 SPAK 打包文件）。

### 10.2 ⭐ 加密方案（逆向自 asar 内 `dist-electron/services/media-crypto.cjs`，源码未混淆）

| 要素 | 值 |
|---|---|
| 文件名 | `sha256(原始媒体路径).hex[:16]`（路径 = URL 去掉开头 `/`，如 `audio/music/x.ogg`） |
| 密钥派生 | `HKDF-SHA256(ikm=48B 硬编码常量, salt="spite-media-salt", info="spite-media-chacha20:"+路径, L=44)` → key32 + nonce12 |
| 加密本体 | 原始文件 ⊕ **ChaCha20** 流（noble/ciphers，**RFC 8439、计数器 0 起**，无 Poly1305 标签） |
| 密码学结论 | **密钥依赖原始路径** → 不知道路径就永远解不开；路径恢复是唯一难点 |

SPAK 打包（`media-pack.cjs`）：`_dafab9efd603f53.dat`，12 字节头（`SPAK`+ver+count）+ count×28B 条目
（16B ascii hash + u32 offset + u32 length），数据区 12+count*28 起，条目同样加密。本作 202 条目 / 51 MB。

### 10.3 ⭐ 路径恢复（多轮反哺，257/365 = 70%）

| 轮次 | 手段 | 新增 |
|---|---|---|
| 1 | asar 文本**引号无关**正则挖字面量（Ink 剧本里路径裸写、无引号） | 222 |
| 2 | 解出的 `.atlas` 反哺贴图页相对路径 | +6 |
| 3 | main chunk 混淆池解码后按池内字符串枚举 `audio/sfx/`、`scenes/`、`characters/zmm/` 等 | +16 |
| 4 | 角色名前缀/`audio/ui_sfx/` 目录补漏 | +9 |
| 5 | 新解 atlas 再反哺 + 服装变体（`{c}_tachie.png` 等） | +4 |

**混淆池解码**（`_spite_extract_pool.py`）：main chunk 有 `function Iu(){const t=["..."]}` 大池（6165 条）
+ 解码器 `arr[i-K]`，**K=293 由双锚点联立解出**（`/\.[a-z0-9]+$/i[f(3497)]` 必为 `"test"`、
`typeof E==R(4844)` 必为 `"string"`，二者交集唯一）。池内 `/audio/`、角色 icon、hscene 缩略图等路径全部还原。

**剩余 108 个 hash（独立 36 + 包内 85...最终 108）在 asar 全文本（含解码池）中零引用**
→ 判定为**未引用遗留资产**（dev 时期生成、无运行时路径），此类方案天然无法恢复——不是工具缺陷。
**凡被引用的资产 100% 恢复**（含全部 45 个 hscene 视频）。

### 10.4 实测产物与验收（`_extracted/SPITE/`）

| 类别 | 数量 | 验收 |
|---|---|---|
| 图片 | 128（webp 74 + png 53 + jpg 1，最大 4096×2232） | Pillow **128/128** |
| 音频 | 68（vorbis 66 + **flac 2**） | ffprobe **68/68**，总时长 **49.4 分钟** |
| 视频 | 45（h264 3584×2048 等，**循环短动画**，合计 1.4 分钟） | ffprobe **45/45** |
| Spine 源 | 8 skel + 8 atlas（非媒体目标，留档） | — |
| **失败** | **0** | — |

### 10.5 本次新增脚本（工作区 `D:\K\deepseek\`）

| 脚本 | 用途 |
|---|---|
| **`asar_tool.py`** | asar 解析：info / list / extract（支持 `--only`、unpacked 旁路） |
| **`_spite_decrypt.py`** | HKDF+ChaCha20 批量解密 + SPAK 解析 + 多轮 atlas 反哺（计数器起点自动判） |
| **`_spite_bruteforce_paths.py`** | 缺失路径组合枚举（token+ext、目录×名字×ext、角色前缀、数字编号） |
| **`_spite_extract_pool.py`** | minified 混淆池提取（反向行走 + 平衡扫描 + 自写 tokenizer，单双引号/模板串通吃） |
| `_scan_hy_inventory.py` | 游戏库盘点（两级体积 + 引擎签名，选样用） |

### 10.6 环境坑（新增）

- **本环境的 Bash 工具会吃反斜杠转义**（`\\`→`\`、`\xNN` 被处理；heredoc 与 `-c` 内联均中招）。
  含正则/转义的代码**必须 Write 成 .py 文件再执行**。本次因此浪费了数轮"诡异的正则失败"。
- minified JS 文本**引号不配对**（正则字面量/单双引号/模板串混用）→ 朴素 `"..."` 配对提取会整体错位，
  且错位随扫描起点漂移。要可靠拿池必须用状态机级解析（见 `_spite_extract_pool.py`）。

---

## 11. Ren'Py 第二样本（`Swipe Right for Sugar Mama Sensei`，2026-10-26）

样本：`D:\HY\Swipe Right for Sugar Mama Sensei`（0.67 GB）。Ren'Py / **Python 3**（`lib/py3-windows-x86_64`）。
**包分工与 My Best Deal 不同**：无 patch，四个包按内容分工——
`archive.rpa`（5.8 MB / 275 条目，脚本与 python-packages）、`gui_resource.rpa`（63.9 MB / 122）、
`img_resource.rpa`（293.3 MB / 218）、`sfx_resource.rpa`（243.0 MB / 1541）。
四包同为 **RPA-3.0 / key `0x42424242`**（与 My Best Deal 相同 → **key 相同≠同一作，别拿 key 当指纹**）。

### 11.1 实测结果

- `rpa_tool.py extract` 四包 **2156/2156 条目全部落盘，0 失败**（纯 Python 秒级，无需 GUI）。
  → **rpa_tool.py 通用性双样本验证通过**（Python 2.7 与 Python 3 两代 Ren'Py）。
- 扩展名对账（与索引一致）：`ogg 1541 · png 256 · rpyc 114 · py 89 · bmp 70 · pyc 68 · ttf 11 · otf 3 · txt 2 · typed 1 · pem 1` = 2156。
- 验收（`_verify_media.py`）：图片 **326/326**（主分辨率 1920×1440）、音频 **1539/1539** vorbis、
  总时长 **187.6 分钟**；脚本/字体等 130 项为非媒体。**本作无视频**（无任何视频扩展名条目）。

### 11.2 ⭐ 0 字节文件要「对索引」而不是直接判失败

ffprobe 报 `End of file` 的 2 个文件：`sfx_resource/audio/{ha,nm}/se008.ogg`。
查 RPA 索引：**源包就声明这 2 条 length=0**（同名占位音效，游戏自带的空文件）。
另 archive.rpa 有 3 个 0 长度条目（`__init__.py` / `py.typed`，Python 包标记，正常）。

> **验收纪律 4 的延伸**：0 字节产物有两种成因——解包 bug（索引非 0 却解出 0）或源包本身 0 长度。
> 用「索引 length 与落盘 size 逐条对账」区分；后者如实记录即可，不是失败。

### 11.3 批量判定副产物（`_extracted/_batch_dispatch.json`）

2026-10-26 对 <3GB 待解池跑了一轮 dispatch + GARbro 实调（该批量提取任务随后被用户取消，仅保留判定结果）：
- **Console 可读**：`温泉蒸汽人妻`（data.xp3 3424 + patch 30 + patch2 37）。
- **Console 全读不出**（假阴性名单新增 2 个）：pork社 4 个已知 + **`教师催眠1`（6 个 xp3）+ `教师催眠2`（6 个 xp3）**——
  都是多包结构（image01-04/voice02/movie/media），GUI 状态待复核，与「待用户确认」事项合并。
- Ren'Py 其余：`スキだらけ！`/`MagicalMILFs` 散装无 .rpa（媒体直接在 game/ 下，无需解包，验收即可）。

## 12. RPG Maker MV 首个样本（`常識改変学園-製品版-`，2026-10-26）

样本：`D:\HY\常識改変学園-製品版-`（1.16 GB）。**NW.js 壳**（`nw.dll`/`node.dll`/`locales/*.pak`/
`icudtl.dat`）包着标准 **`www/` 结构**——判定 RPG Maker MV 靠 `www/js/rpg_core.js`（MZ 是 `rmmz_core.js`）。

### 12.1 ⭐ 加密真身：假头 + 仅前 16 字节 XOR，key 就在 System.json

实测读游戏自带的 `www/js/rpg_core.js` `Decrypter.decryptArrayBuffer`（MV/MZ 同源），加密 =：

```
加密文件 = 假头 16B（"RPGMV" + 00 00 00 00 + 03 01 + 00 00 00 00 00，即 SIGNATURE+VER+REMAIN）
         + 原[0:16] XOR key        ← 只有这 16 字节被动过
         + 原[16:]                  ← 纯明文
```

- key = `www/data/System.json` 的 `"encryptionKey"`（32 hex）。本作是 `d41d8cd98f00b204e9800998ecf8427e`
  ——**即 MD5("")**，打包器没设自定义 key 时的默认值。
- 后缀映射：`.rpgmvp→png`、`.rpgmvo→ogg`、`.rpgmvm→m4a`（MZ 命名风格 `.png_/.ogg_` 同理）。
- **假头 ≠ 校验障碍而是判据**：文件前 5 字节是 `RPGMV`/`RPGMZ` 才算加密体；明文直出的文件
  （如 `img/system/Window.png`，`Decrypter._ignoreList` 特意不加密）按普通媒体收。
- **结论：不用下载 RPGMakerDecrypter**（MIT，C#）。十行 Python 即可（`_rpgmv_decrypt.py`），
  且能逐字节校验魔数；下载/运行外部工具反而多一层不可校验性。

### 12.2 实测产物与验收（`_extracted/常識改変学園-製品版-/`）

- 解密 **1583/1583**（717 `.rpgmvp`→png + 866 `.rpgmvo`→ogg），**0 失败、0 魔数异常**；
  另明文收 2 张（`img/system/Loading.png`、`Window.png`）→ **图片 719、音频 866**。
- 验收：Pillow **719/719**（主分辨率 1200×816×385 张）；ffprobe **866/866** vorbis，总时长 **≈651 分钟**。
- **本作无视频**（验证过的没有）：`www/movies/` 只有免责声明目录，全量扩展名普查无任何视频文件。
- **对账**：源 `rpgmvp 717 + rpgmvo 866 + 明文 2` = 产物 `png 719 + ogg 866`，差 0。

### 12.3 分发垃圾目录：「免责声明请在使用前阅读我」

汉化组在每个目录（www 下共 13 处）塞了同名 `免责声明请在使用前阅读我/`（txt+jpg）。
这些是**分发者垃圾，不是游戏资源**：`_rpgmv_decrypt.py` 按目录名前缀整体跳过（87 个文件），
否则 15 张免责 jpg 会混进图片产物、污染对账。

### 12.4 验收时又见「内嵌封面被算成视频」

866 个 ogg 里 19 个被 ffprobe 报为 `video:mjpeg`——全部是 `audio/bgm/P*.ogg`（BGM 带专辑封面）。
**纪律 4（按扩展名不按流数）第三次命中**：847 audio + 19 "video" = 866，逐个核对全部是 ogg 音频。
`_verify_media.py` 取流时 video 优先于 audio，见内嵌封面会误标 kind，计数时要用扩展名兜底。

## 13. AdvHD 引擎首个样本（`tm／ラブラブお痴験バイト性活`，2026-10-26）

样本：`D:\HY\tm\ラブラブお痴験バイト性活`（3.0 GB）。判定零成本：根目录 `AdvHD.exe` + `AdvHDLang.dll`。
封包是 **`.arc`**（不是 .pac——AGENTS.md 队列原文写 .pac 是笔误），18 个包；
另有 9 个 `*.dat`（OP/ED×8）与汉化补丁容器 `LoveLove.cpk`（魔数 `CialloPAK`，653KB，无媒体，不处理）。

### 13.1 ⭐ GARbro 原生支持 AdvHD .arc，一个工具通吃

- `GARbro.Console.exe <arc>` 直接列出条目；`-x` 提取到 cwd。音频原样出 ogg（`OggS` 实测），
  **图片自动转成 PNG**（引擎自有格式不落盘）。18 包逐包「列条目数 vs 落盘数」对账全部一致。
- **`.arc` 的列表输出没有表头，每行就是一条**（`  size [OFFSET] name`）。
  我在 KiriKiri 养成了 `len(lines)-1` 的习惯，到这里**每包差 1、全军见红**——差点误判成提取缺漏。
  **2026-10-29 复测纠正**：当时以为「xp3 有表头、.arc 没有」，其实**两者都没有表头**
  （xp3 首行也是第一个条目，如 `     1974 [00000028] bgimage/black.tlg`），
  所以 KiriKiri 侧的历史数字（`兼职人妻` 2561、`温泉蒸汽人妻` 3424）同样差 1，已一并纠正为 2562/3425。
  统一口径：**条目数 = 非空行数，任何格式都不减 1**（`toolbridge.garbro_list()` 已按此实现）。
  实际落盘数与包头里的条目数完全吻合（Chip6: 855=0x357、Se: 272=0x110、Voice: 6737=0x1A51）。
  → **计数对账必须跟"魔数条目数"对，不能跟自己的解析习惯对。**
- `.dat` = **ASF/WMV**（头 GUID `30 26 b2 75 8e 66 cf 11 a6 d9 00 aa 00 62 ce 6c`），
  复制改 `.wmv` 后缀即可，ffprobe 全过（wmv3，9 个共 16.3 分钟）。

### 13.2 产物里的三类「非 PNG 扩展名」与处置

| 扩展名 | 魔数 | 数量 | 处置 |
|---|---|---|---|
| `.mos` | `89 50 4E 47`（就是 PNG） | 677（全在 Chip6/7 精灵图） | 按 PNG 验收：Pillow **677/677** 通过 |
| `.pna` | `50 4E 41 50`（PNAP 专有多帧容器） | 48（Chip4 立绘 16 + SysGraphic UI 32） | **`_pna_carve.py` 逐帧 carve**（PNG 签名→IEND 自定界），得 **2640 帧 PNG，Pillow 2640/2640** |
| `.fx/.csh/.psh/.vsh/.hlsl/.h` | DX11 shader | 63 | 非媒体，记录不处理 |

> `.pna` 头结构：`PNAP` + w + h + 帧数(u32，如 0x21=33) + 索引区，PNG 数据从索引后开始；
> 不用逐字段解析——**PNG 自定界，签名→IEND 直接切**就是稳妥解（2640/2640 零失败实证）。

### 13.3 实测产物与验收（`_extracted/ラブラブお痴験バイト性活/`）

- **音频 7031 ogg**（Voice 6737 + Se 272 + Bgm 15 + SysVoice 7），ffprobe **7031/7031** vorbis，**841.1 分钟**。
- **图片 989 png**（Chip0-3/5 背景 + Chip6/7 与 Graphic 等）+ **677 mos**（PNG 内容）+
  **PNA_frames/ 2640 帧**（48 个 pna carve 所得）→ 三者 Pillow 全过（989+677+2640）。
- **视频 9 wmv**（OP + ED×8），ffprobe 9/9。
- 非媒体留档：`.ws2` 脚本 201 / `.lua` 15 / shader 63 / `Pan.dat`（PAN3 动画数据）1。
- 对账：18 包 索引数=落盘数 0 差；.dat 9/9；无 0 字节文件。

### 13.4 本次新增脚本

- `_advhd_run.py` —— AdvHD 编排：逐 .arc 先列后提 + 对账 + .dat→wmv 复制。
- `_pna_carve.py` —— PNAP 多帧容器逐帧 carve（通用：任何"容器内嵌标准 PNG"的格式都能切）。

## 14. Yu-Ris 引擎首个样本（`あまねぇ -幼馴染…-`，2026-10-26）——YPF 格式完整逆向

样本：`D:\HY\あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-`（2.14 GB）。
任务队列里最含金量的一个：**GARbro 不认**（其 YaneSDK 目录只有 ArcDAT/ArcHibiki，YPF 报
unknown format 是真不支持、不是假阴性）、无现成趁手工具，按「魔数→指纹→检索」走完全程。

### 14.1 引擎指纹与检索路径

- 魔数：`pac/*.ypf`（`YPF\0`+版本+条目数+表大小）、存档 `.sd`（`YSSD`）、`yscfg.dat`、
  `エンジン設定.exe`——「YS」前缀。
- 一度误判为 Yaneura SDK（yscfg/YSSD 前缀迷惑），**检索后确认 YPF = Yu-Ris 引擎封包**
  （`YS` = Yu-Ris System）。现成工具：crskycode/YPF_Tool（C#，主打封包不主打解）与
  vn-tools/arc_unpacker（0.11 有 `yuris/ypf` 解码器）。

### 14.2 ⭐ arc_unpacker 0.11 的两个实测坑（详见决策树 §3 坑表）

1. **`--out DIR`（空格形式）不吃**：DIR 被当成又一个输入文件；写成 `--out .` 时 cwd 被整个
   递归扫一遍（表现为大量 `yst*.ybn: unknown input file` 幻影任务）。**必须 `--out=DIR`**。
2. **大包疑似卡死**：cg.ypf（3484 条）跑了 30+ 分钟（CPU 在烧）零落盘，杀掉。
   data.ypf（195 条）9 秒完成——小包可用，大包别等。

### 14.3 ⭐ YPF 格式（版本 0x1EE，逆向自 arc_unpacker 源码 + hexdump 交叉验证）

```
头 32B: "YPF\0" + u32 version + u32 file_count + u32 table_size + 0x00*16
        ⚠️ table_size 从文件头起算（含主头 32B），表区实际 = table_size - 32
表@0x20, 每条目: u8 name_len(值^0xFF 后查 4 张置换表之一得实际名长)
                 + name(原始字节，XOR 单字节 key)
                 + u8 type + u8 compressed(1=zlib) + u32 size_orig + u32 size_comp
                 + u32 offset + extra(版本>=0x1D9 为 8B；0xDE 为 12B；否则 4B)
名 key: name[-4] ^ '.' 应命中已知扩展名的 '.'（bmp/png/ogg/wav/txt/ybn）；本作 key=0xFF
数据: offset 处 size_comp 字节，compressed 则 zlib inflate；YCG 图片另见 _ypf_extract.py 注释
```

- 排查过程的核心锚点：**entry[0].offset == table_size**（表后紧跟数据区）、
  **entry[i].offset + size_comp == entry[i+1].offset**（数据连续打包）——这两条把手算布局钉死。
- 实现细节：解析**按 file_count 精确读 N 条**，不要"读到表尾"（表尾后 32B 已是数据区）。

### 14.4 实测产物与验收（`_extracted/あまねぇ -幼馴染…-/`）

- **cg.ypf → 3484 张真 PNG**（1.5 GB；本作未用 zlib、未用 YCG，明文直出）；
  **sound.ypf → 4522 个真 OGG**（501 MB）；**data.ypf → 195 个 .ybn 脚本**（YSCM，非媒体）。
- 对账：三包 索引数=落盘数（3484/4522/195）**0 差**；自研提取器与 arc_unpacker 在 data.ypf 上的
  **195 个文件名清单完全一致**（交叉验证通过）。
- 验收：Pillow **3484/3484**（1285×850×1320 立绘 + 1117×1500×1320 CG + 720p×425 等）；
  ffprobe **4522/4522** vorbis，**527.7 分钟**。**本作无视频**（pac/ 只有 cg/data/sound 三包）。
- 自研提取 3484+4522 条目 **全程 2 分钟**（arc_unpacker 卡死同任务 30 分钟+）。

### 14.5 本次新增脚本与工具

- **`_ypf_extract.py`** —— Yu-Ris YPF 提取器（自研，含 YCG→PNG、四种置换表、key 猜测）。
- `D:\K\galgame\arc_unpacker\arc_unpacker.exe` —— arc_unpacker 0.11 bin（留作大包备选/交叉验证，
  注意 §14.2 两个坑）。

## 15. ExHIBIT 引擎首个样本（`夕凪荘的S级的女朋友们`，2026-10-26）—— .gyu/.grp 完整逆向 + BGM 加密侦察

样本：`D:\HY\夕凪荘的S级的女朋友们`（5.5 GB）。MOONSTONE Cherry 品牌用 **ExHIBIT 引擎**（内部名
**Retouch**，见 resident.dll 的 `RetouchSystem`/`FCRetouchKey` 符号）：根目录 `ExHIBIT.JP`/`RESIDENT.JP`
（引擎配置脚本）、`ExHIBIT.ini`（含 `DPMODE=0xC300` 与游戏 GUID）、`Yunagiso.exe`+`acmp.exe`+
`resident.dll`（3.7MB 主逻辑）+`sc00.dll`（脚本）+`moonstone.TTE` 字体。

### 15.1 ⭐ .gyu 图片格式（7 变体全解，2154+30 张零失败）

规格书 = GARbro-Mod `ArcFormats/ExHibit/ImageGYU.cs`（api.github.com 拉源码）。本机 GARbro（7 月构建）
无 ExHibit 支持、上游 release 停在 2019 → **自研 C# 解码器 `_gyu_tool.cs`**（用系统自带
`C:\Windows\Microsoft.NET\Framework(64)\v4.0.30319\csc.exe` 编译，零外部依赖）。

```
头 0x24: 'GYU\x1a' + u16 Flags + u16 CompressionMode + u32 Key + i32 BPP
        + u32 W + u32 H + i32 DataSize + i32 AlphaSize + i32 PaletteSize
之后: [调色板(PaletteSize)] [Data(DataSize)] [Alpha(AlphaSize)]
Key ≠ 0xFFFFFFFF → Deobfuscate: MT(key) 取 10 对随机下标交换字节（密钥就在文件头，不用猜）
CompressionMode: 0x0100=原样 / 0x0800=Gyu自定义LZ / 其他(0x0400)=LZSS
  Gyu-LZ: 跳过 packed 前 4 字节，首字节直出，之后 MSB 位流:
          bit=1→字面量；bit=0→bit=1→16位{offset=-(0x2000-(v>>3)), len=(v&7)?v&7+2:读1字节(0=EOF)}
                     bit=0→短形式{len=2+2bit, offset=-256+byte}
  LZSS:   环形 0x1000 / fill 0 / 起始 0xFEE / flag 位 LSB 先行 / (hi&0xF0)<<4|lo, len=3+(hi&0xF)
  Alpha:  AlphaSize==(w+3&~3)*h → 原样；否则 LZSS。Flags≠3 时 alpha<0x10 → *0x10，否则 0xFF
  8bpp 用调色板（4 字节 BGRx 项）；最终图自下而上存储 → PNG 前上下翻转
本作变体: Flags∈{0,1,3} × Mode∈{0x0100,0x0400,0x0800} × BPP∈{8,24}，F=全图 / P000=差分（各自独立成图）
```

**关键 bug（移植踩坑）**：Gyu-LZ 的**字节读取与位读取共享同一游标**（原实现 `mem`/`mem` 同源）——
自移植时拆成两个游标后从第一个 token 就错位。表现为「首个回引距离荒谬」。**教训：位流+字节流混读
的格式，移植时必须共用一个游标对象。**

### 15.2 .grp 音频库（AiFS TOC，9185/9185）

规格书 = GARbro-Mod `ArcGRP.cs`。`res2001/2002.grp` = 裸 OGG 流集合，**TOC 就是 res2000.grp**（魔数
`AiFS`）：TOC @0xC = 块数，每块 {i32 num（0x01000000 为转义标志）, u32 start_index, u32 ?, u32 count}
+ count×(u32 offset, u32 size)，size≠0 的对 → 从 res 文件 offset 切出，命名 `{start_index+i:D5}.ogg`。
本作：res2001=6755 条语音 + res2002=2430 条，**9185/9185 零失败**（TOC 解析一次通过）。

### 15.3 ⚠️ res/s/m/*.ogg BGM 加密——已侦察未破解（22 个，41MB）

结构实测：**文件 = [0,3853) 加密块 + 页 2..402 明文 OGG 页**（serial 一致、seq 从 2 起、granule 递增；
尾部零冗余）。即**只加密了 vorbis 的 ident+comment/setup 两页**，且 `OggS`/`\x01vorbis` 字节值在加密区
内不存在 → 排除置换类，是值变换（流密码/XOR/旋转）。

已排除：GARbro 版 MT 键流（含 2^25 种子爆破）、引擎版 MT 键流（无 tempering，69069 链单步进位变体，
多候选种子）、RC4（常见键）、ROR/ROL-by-MT 表（对该函数 0x101f3ED0 做 2^31 全种子爆破——见下）、
文件头 4 字节作种子。**绕不开的原因：真正的解密器在虚调用链后面**（loader 读前 4 字节 cmp "OggS"
@resident.dll 0x1029E43E，≠ → 0x1029ECA0 → `[esi+0x70]` 虚调用），未再深挖。

侦察战利品（留档给未来会话）：
- 引擎内有**两套 MT19937**：GARbro 同款（带 tempering，用于 .gyu Deobfuscate）+ 无 tempering 版
  （srand=69069 链、Rand 返回裸状态字，对象布局 `[+4]=mti`、状态数组 `+8` 起 624 字）。
- **ROR/ROL-by-table 密码族**（0x101F3ED0/孪生）：`table[i]=MT.RandRange(8)`（即 rand()%8），
  `data[i] = ror(data[i], table[i&0xff])`——cdecl `(seed, data, len)`，自包含可黑盒调用。
  该函数**不能**解 BGM（'O' 的旋转像集不含 enc[0]=0x98），疑似存档用。
- 配置键 `cluu`（settings.dat 首行 `cluu=$J1q4F#V2Y4…` 混淆值，引擎读入时校验哈希 `0x29ACD315`）
  与 `GUID`（ExHIBIT.ini）——密钥材料大概率在这两者 + `DPMODE=0xC300` 里。
- **黑盒 oracle 技术**（本次最大可复用经验）：32 位进程 `LoadLibraryEx(LOAD_WITH_ALTERED_SEARCH_PATH)`
  加载游戏 DLL（Unicode 编组！否则 CJK 路径 126 错误），`Marshal.GetDelegateForFunctionPointer`
  直接调用未导出的内部 cdecl 函数——本次稳定跑了 2^31+ 次调用零崩溃。

#### 15.3.1 静态逆向进展（2026-10-28，capstone 反汇编；仍未破，但链路已摸清）

用 capstone PE 流水线（`_bgm_re*.py`，可复用）把虚调用链追到了构造层：

- **loader 函数全貌**（0x1029E320 起，vtable 槽 2）：打开文件 → 读 4 字节 `cmp [ebp-0x44], 0x5367674f`
  （"OggS"）→ 相等走正常加载 0x1029E630；**不等 → `call 0x1029ECA0`**。
- **0x1029ECA0 虚调用壳**：`mov ecx,[ecx+0x70]; test ecx,ecx; je ret; mov eax,[ecx]; push 1; call [eax]`
  —— 解密器对象挂在 loader 的 **this+0x70**，其 vtable[0] 就是解密入口（`push 1` 疑为「解密整个头块」标志）。
- **loader 类构造函数**（0x1029E1F0，vtable 0x102F2718）：`mov [esi], vtable` 后
  **`mov [esi+0x70], 0`** —— 构造时解密器为空，**由外部在构造后安装**（工厂 0x102559DA/0x10255C55
  处 `call 0x1029E1F0` 后未见紧接着的 +0x70 写入；全 .text 仅 3 处 `mov [reg+0x70]` 均非本类）。
  → 安装点在更上层的装配代码里，尚未追到（下次可从 0x10255C55 的调用者向上追）。
- **工程结论**：解密器是**多态对象**（可能按文件名/类型选择不同实现），静态追完成本高；
  **内存 dump 是更优路径**——工具已备好（`_bgm_dump2.py`：启动游戏 + 窗口点击 + 按 OGG serial
  匹配扫描进程内存，serial 指纹表 `_bgm_serials.json` 22 个全对齐，m17/m18 头长 3834 其余 3853）。
  实测两轮：游戏停在需交互的开场界面（截屏确认），标题 BGM 未起，内存中无匹配；
  **PostMessage 点击未能推进界面**（DirectInput 类游戏可能不理会消息点击，需真前台 SendInput 或用户手动）。
  → 本任务转为**搁置等用户配合**：用户把游戏开到标题画面/播放任一 BGM 时，跑 `_bgm_dump2.py` 即可抓到
  解密后的头块（anchor 自校验已内置），XOR 密文即得密钥流，再反推逐文件派生规律。

### 15.4 实测产物与验收（`_extracted/夕凪荘的S级的女朋友们/`）

- **图片 2184 PNG**（res/g 2154 + userdata 缩略图 30），Pillow 全过（主尺寸 1920×1080）。
- **音频 9291**：grp 语音 9185 ogg（841 分钟级）+ res/s SE 106 wav；**视频 1**：op.wmv（138MB，ASF）。
- 对账：gyu 2184/2184、grp 9185/9185、wav 106/106、wmv 1/1——**除 BGM 22 个外全部对账 0 差**。
- 未解析留档：`.dlt` ×20（引擎差分合成数据，非媒体）、`.rld` ×195（脚本）、res2000.grp（纯 TOC）。

### 15.5 本次新增脚本/工具

- **`_gyu_tool.cs` → `_gyu_tool.exe`** —— .gyu 批量解码器（C#，csc 编译，Parallel + GDI+ 出 PNG）。
- **`_grp_extract.py`** —— ExHIBIT .grp 音频库提取（AiFS TOC）。
- `_blackbox_test.cs` / `_full_brute.cs` —— DLL 黑盒 oracle 调用/爆破模板（可复用技术）。

## 16. CatSystem2 加密完整逆向（`甜蜜女友2+`，2026-10-27）——真·加密分支全链打通

样本：`D:\HY\甜蜜女友\【PC电脑】甜蜜女友2+`（9.9 GB，アザラシソフト/アマカノ2+）。51 个 `.int`
（魔数 `KIF\0`），全部 `__key__.dat` 种子；伴生 `key.dat`（64B 高熵）、`cs2.exe`（22KB 启动器 + 6MB
overlay，**无** GARbro 所期望的 DATA/V_CODE2 资源）、`cs2_Crack.exe`。

### 16.1 加密链（规格书 = GARbro-Mod `ArcFormats/CatSystem/ArcINT.cs` + `Blowfish.cs`）

```
索引: 头 0x48/条目 {name[0x40], u32 off_raw, u32 size_raw}
      off_raw + i 后整 8 字节块 Blowfish-ECB 解密（GARbro 小端打包）
      密钥 = 4 字节 = MT(包头 0x4C 处种子).rand() 的小端
数据: 条目本体同 Blowfish 解密（长度向下取整到 8）
文件名: MT(main_key + i).rand() 的四字节和 k0 → 52 字母表("zyx..cbaZYX..CBA")轮换
      j = idx(ch) - (k0+n)%52; out = alphabet[0x33 - ((j<0)?j+52:j)]
main_key: 正常取自 exe 的 V_CODE2 资源（EncodePassPhrase=类CRC32链）——本作没有，靠爆破
```

### 16.2 ⭐ main_key 爆破方法论（无口令时的通用打法）

名字移位量只依赖 `k0 = byteSum(MT(main_key+i).rand())`，而 k0 只有 256 种——**先逐条目穷举 k0**，
从「解出名为可读+带合法小写扩展名」反推每个条目的 k0（mot.int 的 entry3/5 反推出 k0=2 →
`mcFade.kcs` 实锤），再用「entry_i 的 k0 已知」做约束 C# 并行爆破 main_key 全空间：
双约束(2/256)² + 全名复核，**数秒命中** `0x212C5F31`（伪命中 `0x40C60698` 被 pcm 包 .ogg 率甄别）。
验证：`bg01_smr_a.hg3`、`AA_01_YU01_002.ogg`、`mcFade.kcs` 等语义名全对。

### 16.3 实测产物与验收（`_extracted/甜蜜女友2+/`）

- **53500/53500 条目零失败**（51 包，pycryptodome + numpy 快速版全量 ~4 分钟）。
  注意 GARbro 小端 Blowfish ≡ 标准大端解密 + **输入/输出都按 4 字节半块反转**（只反输出会得到静默错数据）。
- 内容魔数普查：OggS 23259 / HG-3 4502 / LPD 19052（图层）/ KCS 84 / PSZ 669 / MPEG-PS 10。
  **文件名被引擎二次混淆**（扩展名随机字母 .qiy/.phx…）——按魔数统一改 .ogg（22231 个）后验收。
- **图片 4499 PNG**（`_hg3_tool.exe` **4502/4502 零失败**——107 个 24bpp 变体已于 2026-10-28 补完，
  见 §16.5；4499 是唯一名数，源侧有 3 组去扩展名重名：`ezrzqz01_000000t`/`j_wjnu17n_0h`/`niaizi02_l`
  同名不同扩展各两份，PNG 覆盖属预期）；**音频 23259 ogg（2275.7 分钟）** + **视频 10 mpg**（6 个 180MB
  正片 + 4 动画，13 流 22.6 分钟）。全量 ffprobe/Pillow **零失败**（明细 `_extracted/_cs2_verify.csv`）。
- 决策树经验：本作 HG-3 方言 = **0x14 起就是分节链**（stdinfo 第一节，HeaderSize 字段是节的
  size 而非节起始偏移）；ctl 位流 = **LSB-first**；img0000 的四 i32 @ 节起点+0x18、数据 @+0x28。

### 16.4 本次新增脚本/工具

- **`_cs2_int_extract.py`** —— CatSystem2 .int 全链提取（π(Machin)生成 Blowfish 常数、
  MT/名字/Blowfish 全自研；pycryptodome 加速）。
- **`_cs2_key_brute.cs`** —— main_key 约束爆破器（C# 并行，可复用）。
- **`_hg3_tool.cs/_exe`** —— HG-3 家族（.hg3/.nm3/.gf3/任意扩展名按魔数）批量转 PNG。
- `_hg3_decode.py` —— HG-3 Python 版（含慢速参考实现，用于对拍验证）。

### 16.5 ⭐ 24bpp HG-3 变体补完（2026-10-28，4502/4502 收官）

- **初判全错**：107 个失败文件曾被疑为「独立压缩平面方案」「cptype 判别缺失」——实测**两者都无关**。
  cptype/imgmode 节 4502 个文件**全有**（`cptype` 载荷统一 `04 00 00 00 00 00 00 00`，32bpp 正常文件也一样），
  只是干扰项。RLE 位流模拟显示 107 个文件的解码**全部正常**：输出恰好 `w*h*3`、像素流精确耗尽。
- **真正根因**：`_hg3_tool.cs` 的 `DecodeFile` 在 flip 阶段硬编码 `int row = w * 4`——
  24bpp 时 px 只有 `w*h*3` 字节，`Array.Copy` 越界抛异常。ApplyDelta 的 4 等分位转置**无需任何修改**
  （GARbro 原版对 24/32bpp 同一段代码，只是 psize/Stride 不同；见 `ArcFormats/CatSystem/ImageHG3.cs`）。
- **修复**：`row = w * (bpp/8)` + 按 bpp 选 `Format24bppRgb`。重跑 **4502/4502 零失败**，
  Pillow 4499/4499 全过；24bpp 产物含 2560×1440 天空 CG（`ot32_BvA_j.png`）视觉无伪影。
- **方法论沉淀（两条）**：
  1. **对拍基准先行**：先写独立 Python 复刻 32bpp 全链、与已交付 PNG 逐字节比对（bytes-equal），
     确认流水线语义后再动 24bpp——一次就定位到自己代码段 vs 算法段的问题。
     顺带发现 `_hg3_decode.py` 的 numpy 版 delta（全缓冲长链 cumsum）与 C# 语义**不等**
     （正确语义 = 行 0 水平像素链 + 垂直逐行；32bpp 对拍 bytes-equal 验证）。
  2. **平滑度指标会被「竖条纹伪结构」欺骗**：错误的像素交错假设 dh/dv 也能得很低分
     （垂直累加把常量拉成条纹），**不能只看分数，必须人眼看图或逐字节对拍**。
  3. **minified 侦察脚本要控制复杂度**：首版对同一文件重复做全量 RLE 模拟（107×4 次）跑到小时级，
     重写为「头部解析每文件一次 + 模拟只跑子集」后秒级出结果。

### 16.6 ⭐ 全量 51 包 / 53500 条（2026-10-31）——尾部明文、护栏大小写、CRC 地面真相

> 本节的每一项都来自**真跑**（`_extracted/甜蜜女友2+/`，53500 条目、9.87 GB），
> 不是推论。前五条是「这次全量跑跑出来的新事实」，第六条是「顺带补上的验收口径」。

**① 尾部 `fsize % 8` 字节在归档里本来就是明文（用 Ogg 页 CRC 判明，不是猜的）**

`_extract_one` 里是 `decipher_fast(bf, blob, fsize // 8 * 8)`——长度**向下取整到 8 的倍数**，
尾部零头留的是密文态。我曾怀疑这是「解填充块再截断」写漏了，用**最后一个 Ogg 页的 CRC**
（页里存的 CRC 是编码器按真实明文算的）做判据，**否证了该怀疑**：

| 变体 | 末 3 字节 | 最后一个 Ogg 页 CRC | 页里存的 CRC |
|---|---|---|---|
| 盘上（只解 `fsize//8*8`） | `81 6b 13` | `0xfe9a5de8` | ✅ 一致 |
| 全解 `ceil(fsize/8)*8` 再截断 | `2a c5 81` | `0xc45b0d83` | ❌ 不一致 |

（前 5 字节 `c9 02 e0 bb 34` 两边一致，说明对齐部分的解密是对的，只有尾部分歧。）
→ **打包器只加密整 8 字节块，落盘尾部的零头就是原文**。「只解整块、尾部照抄」是**正确**实现，
不是缺陷。全量扩大验证：**23259 个 `.ogg` 最后一个页 CRC 全部通过**，其中
**20384 个（87.6%）大小不是 8 的整数倍**——尾部现象大量存在，且全部与原样解密自洽。

> 副产品：**「最后一页 CRC」是 CS2 音频最廉价的地面真相校验**——比 ffprobe 更硬
> （FFmpeg 会「尽力解码」蒙混过关，CRC 一字节都不能错）。判据脚本 `_tmp_cs2_crc.py`。

**② 护栏算错比不设护栏更坏（大小写）**

HG-3 期望张数原来按**大小写敏感**去重算出 **4501**，而 `_hg3_tool` 落盘走 `Path.ChangeExtension('.png')`、
NTFS 上 `X.png` 与 `x.png` 是同一文件（后写覆盖先写），实际 **4499**。
结果：一次**完全正确**的解包被自己的护栏判成「产物不足」，整条链 rc=1。
三组只差大小写的撞车：`image01/ezrzQz01_000000T.GF3`+`.hg3`、`J_WJNu17n_0h.hg3`+`j_wjnU17N_0H.ml3`、
`Niaizi02_l.hg3`+`nIAIZI02_L.PO3`。
→ **去重键必须按平台语义**（Windows 不区分大小写）。另：产物判定要看 **png/ 目录总量 == 期望**，
不是「本轮增量 ≥ 期望」——`--reuse-raw` 复跑时增量天然是 0，按增量判会二次误报。

**③ 交付口径 vs 对账口径必须分开**

HG-3 转出的 PNG 才是交付物，raw 里那份中间产物记进 `ctx.consumed`、从 `final` 按**路径**排除
（`manifest.iter_final_files(..., exclude=)` / `counts(..., exclude=)`），但 `raw` 仍然数着它——
否则 53500 条对账就没有依据。**按路径排除而非按扩展名**，因为扩展名被引擎混淆。
实测：raw 53500 − 4502 hg3 + 4499 png = final 53497，逐键 diff 无歧义。

**④ 扩展名二次混淆（全量实测）**

提取阶段记录的是归一**之前**的扩展名，正好把混淆拍了个正着：`.ogg` 只有 **417** 个，
而 OggS 总数 10915（3.8% ≈ 1/26），其余散在 `.woo`468/`.tll`452/`.umm`438/`.nff`438/`.phh`436/
`.dvv`445/`.kcc`412/`.ldd`411/`.imy`407/`.mee`397… 几十个值上；HG-3 家族同样散在
`.hg3`50/`.nm3`52/`.gf3`60/`.dc3`50/`.zy3`40/`.az3`35… 归一后合流成 **1148 个 `.hg3`**。
归一数 11596 = (10915 − 417) + (1148 − 50)，与预期分毫不差。
→ **不按魔数归一，乱扩展名的媒体会落进 `stage_verify` 的 `nonmedia` 被静默放过**
（`.mos` 那次的翻版：verify 照样报「失败 0」，交付清单凭空少验几千个文件）。

**⑤ 全量跑实测（`--reuse-raw` 复跑）**

```
extract   52.39s   51 个 .int，53500 个文件，对账 0 差（逐包 51/51）
postprocess 224.54s 扩展名按魔数归一 0 个；HG-3 4502 个 → png/ 4499 张（同 stem 撞车 3）
verify   6145.93s  图片 4499/4499、音频 23258/23259、视频 10/10，媒体 2290.8 分钟
raw 53500 个文件 9874.6 MB；final 53497 = 53500 − 4502 hg3 + 4499 png；converted {}
by_ext 关键项：.ogg 23259 / .mpg 10 / .png 4499（raw 侧另有 .hg3 4502）
```
- 唯一失败：`raw/pcm_DD/dd_02_ch08_019.OGG :: ffprobe 无结果`。**该文件本身是好的**——
  直接探 rc=0、连探 5 次全过、最后一页 CRC 也对 → **偶发**（子进程没起来/超时）。
- 历史基准里「音频 2275.7 分钟 + 视频 22.6 分钟 = 2298.3 分钟」，现在合计 **2290.8 分钟**；
  但**文件计数逐项相同**（23259 / 10 / 4499），差异来自两个工具量的字段不同
  （`parse_ffprobe_json` 优先 `format.duration`，历史那个数由 `_verify_media.py` 量的），**不是数据丢失**。
- `manifest.json` 因 verify 失败未落盘（编排器是先验完再写 manifest）。

**⑥ 验收口径补强：`ffprobe_ex()`**

`toolbridge.ffprobe()` 原来把所有失败原因折叠成一个 `None`（`rc != 0` / JSON 解析失败 /
`parse_ffprobe_json` 返 None 一律 None），`stage_verify` 只能报一句「ffprobe 无结果」——
**看日志的人分不清「文件真坏」和「子进程没起来/超时」**。
`ffprobe_ex(path, timeout=120, retries=1) -> tuple[info|None, reason]`：失败时重试一次并把原因串出来
（`超时（>120s）` / `rc=N：<stderr 末行>` / `没有任何音视频流（只有封面，或流列表为空）` / `JSON 解析失败：…` /
非白名单 → `扩展名 X 不在 ffprobe 白名单`；重试仍失败追加 `（重试 1 次仍失败）`）；
`ffprobe()` 退化成取 `[0]` 的薄包装（老调用方行为不变）。`stage_verify` 把原因写进 `fail_examples`：
`[av] <路径> :: ffprobe 无结果——<原因>`。

---

## 17. KiriKiri 加密 xp3 动态提取全链打通（2026-10-28）——KrkrExtract 自动化 + 两条硬结论

样本①：`D:\HY\pork社\高慢妻陥落！！`（data.xp3 692MB，Console 读不出）；样本②：`D:\HY\教师催眠1`
（xksaimin.exe + 10 个 xp3 共 1.9GB）。工具：KrkrExtract 5.0.0.2（2021-12-15，仓库已归档）。

### 17.1 工具补齐与版本核实

- Lite.exe 从 release 5.0.0.2 下载：**534,016 B**，SHA256 `EB5D609B1DCD6AB9C163C3640C06FF1CD80875592221E4D1208BEB318C69CE89`。
  本地 `KrkrExtract.Core.dll`(11,237,376 B) + `KrkrExtract.UI.Lite.dll`(129,024 B) 与该 release **配套**
  （运行时窗口标题 `KrkrExtract(local 5.0.0.2) - built on Dec 15 2021 22:32:03`，来自 Core 导出
  `GetKrkrExtractVersion`——版本字节级对上，不必再找 dll）。
- **Lite.exe 支持 CLI 注入**（源码 `Program.cs`：`args.Length == 2` 时把 args[1] 当游戏 exe，
  `LoaderHelper.CreateProcessWithDll` 挂起启动 + 手动映射注入 Core.dll，然后 `Environment.Exit(0)`）。
  → `KrkrExtract.Lite.exe <游戏exe绝对路径>` 即完成注入，**无需拖拽**。
- Core.dll 必须与游戏 exe **同目录**（注入传裸文件名，按游戏进程的加载路径解析）。
- 源码仓库（xmoezzz/KrkrExtract master）**不完整**：`KrkrExtractCore::Initialize` 无实现体（部分闭源），
  源码考古有边界；但 UI/拖拽/输出目录逻辑可读。

### 17.2 ⭐ 硬结论一：游戏路径必须纯 ASCII（CJK 路径 = 注入后必挂）

- CJK 路径（`D:\HY\pork社\高慢妻陥落！！\高慢妻！！.eXe`）下注入：游戏进程活着但**不弹游戏窗口也不弹
  工具窗口**，只弹一个 `#32770` 错误框（标题=游戏名）：『ANSI 文字列を UNICODE 文字列に変換できません…』
  （krkr2 引擎的 ANSI→Wide 转换失败，被 Core 的钩子放大；本机 GBK 代码页）。首判「游戏没启动」是误诊。
- **解法：ASCII stage 目录**。xp3 用 `os.link` 硬链接（同卷零拷贝）、主程序复制为 `game.exe`、
  其余文件（**plugin/*.tpm、*.cf 必带**——教师催眠1 缺 plugin 会启动失败）全部复制。
- 对照实验证实：同游戏同注入，ASCII 路径 → 游戏窗口 + KrkrExtract 窗口全部正常。

### 17.3 ⭐ 硬结论二：跨进程 WM_DROPFILES 不可行，OLE 拖拽也不行，唯一通路 = Explorer 发起真拖拽

两进程受控实验（接收方 DragAcceptFiles 窗口 + 发送方 GlobalAlloc(GMEM_MOVEABLE|GMEM_SHARE)）：
接收方 wndproc **收到** WM_DROPFILES 但 `DragQueryFileW` 返回 0（GMEM_SHARE 在现代 Windows 是
no-op，GlobalAlloc 句柄进程私有）。KrkrExtract 的 UI 源码只挂 WM_DROPFILES（`OnDropFiles` →
`OnStartDumper`），无按钮无命令行（`IDC_CMD` 编辑框在 master 源码里是死代码）；gRPC 服务只在
Remote 模式启动（实测无监听端口）。逐项证伪的替代通路：

| 尝试 | 结果 |
|---|---|
| 合成 WM_DROPFILES（SendMessageTimeout + 自建 HDROP） | 消息到达（弹 'XP3Extract' 框=Index!=1），DragQueryFileW 读不到内存 |
| SHDoDragDrop（OLE 拖拽）+ SendInput | 拖拽成立，但 OLE drop **不**投递 WM_DROPFILES 给 DragAcceptFiles-only 窗口（受控实验证实） |
| Core 命令通道 `df`/`di`（控制台/虚拟控制台） | 控制台只输出不读入；命令只能来自未开源的 IPC（ALPC+SessionKey 握手，成本过高） |
| **Explorer 发起的真实拖拽**（explorer /select + UIA 取 item 矩形 + SendInput 按下-移动-松开） | ✅ **唯一成功**。Explorer 的 drop 逻辑对 WS_EX_ACCEPTFILES 窗口走 legacy 通道，由 shell 完成跨进程 HDROP |

### 17.4 自动化要点（全部踩实，已沉淀进 `krkr_auto_extract.py`）

- **DPI 200%**：Python 必须 `SetProcessDPIAware()`（否则 1440x900 虚拟坐标 vs 物理 2880x1800 全错位）；
  PowerShell 的 UIA 脚本同样要先 `SetProcessDPIAware`，并自报 `GetSystemMetrics` 让调用方按比例换算
  （SetProcessDPIAware 在 PS 里可能太迟失效，不能假设生效）。
- **UIA 取 item 矩形**：`AutomationElement.FromHandle(游戏窗口句柄)` + Name 精确匹配；**Explorer 导航会
  重建顶层 HWND**（旧句柄 MoveWindow 是打在死窗口上）→ 轮询 UIA 到出 RECT 为止、以 UIA 实测坐标为准。
- **拖拽前验证 WindowFromPoint**：起点须命中 `SysListView32`（桌面）/`DirectUIHWND`（Explorer 内容区），
  落点须命中 KrkrExtract 对话框本身（找空白点）。
- **遮拦三类**：① 挂起引擎的 DWM **Ghost 窗口**（游戏窗口 hung=True 时 DWM 全屏替身，吃掉所有点击——
  krkr2 窗口加载期常见）；② 其他虚拟桌面上的窗口（EnumWindows 跨桌面可见但点不到；
  **最小化+还原**能把窗口拉回当前桌面）；③ 自己的测试窗口。桌面图标法因桌面全被盖住而放弃。
- **任务完成判定**：产物数连续 40s 稳定（UI 标题在任务中会变成 `[任务名] x/y`，也是信号）；
  错误弹窗标题为 `KrkrExtract`（区别于 'XP3Extract'=拖放格式错）。
- 每包一次拖放（源码 `Index != 1` 即报错，不支持多文件一次拖）。

### 17.5 样本①结果（`高慢妻陥落！！`，2026-10-28）

- **2838/2838 条目零失败**，692.2MB。明细：ogg 1394 + wav 1 + mp3 1（**音频 1396，148.8 分钟**）、
  tlg 865（→png 865/865，`_krkr_tlg_convert.py` + tlg2png）+ png 436（**图片 1301，Pillow 全过**）、
  ks 108 + tjs 26（脚本）、dll 3 + txt 2 + asd 2。
- **无视频**：索引条目与产物双重验证（扩展名清单里没有任何视频格式，判据同坑 3 的「条目级验证」）。
- 对账锚点：Core 注入后打开 data.xp3 时自动 dump `data.xp3.index`（**解密后的 TOC**，
  384,558 B，含 2838 个 File 条目）——条目数与产物精确一致。
- 产物：`_extracted/高慢妻陥落！！/KrkrExtract_Output/data/...`。

### 17.6 样本②结果（`教师催眠1`，2026-10-28）——krkrZ 引擎、10 包、断点续传实测

- `xksaimin.exe`（krkrZ：TVPMainWindow/TVPTimerWindow 窗口类）+ **10 个 xp3 共 1.9GB**，
  全部用 `krkr_auto_extract.py` 跑完：**5724/5724 零失败**。
  audio 3600（ogg 3213 + wav 387，**556.8 分钟**）/ image 2009（png 2007 + jpg 2）/ **video 2** /
  脚本 ks 50 + tjs 46 + csv 8 / soc 1 / txt 8（见下）。
- **本作直接出 PNG（无 .tlg）**，无转换步。
- **中途踩坑三连（都已修进工具）**：① stage 缺 `plugin/*.tpm` → 引擎起不来（stage 现复制除 xp3
  外全部文件）；② 上次失败残留的游戏进程叠了一个旧 UI 窗口遮住新窗口 → reuse-stage 也要**杀干净
  全部 game.exe 再重新注入**；③ 用户开着的 Chrome 盖住 Explorer item → 拖拽前
  `WindowFromPoint` 校验 + 前置窗口重试（工具加了 `--only`/`--reuse-stage` 断点续传）。
- **用户清理了 stage 目录**：原始 xp3 安然无恙（stage 里只是硬链接）——硬链接策略再次兜底。

### 17.7 ⭐ movie.xp3 的「Lock」TOC 混淆破解（两个工具都提不出的包）

症状：movie.xp3（155MB）拖给 KrkrExtract 与 KrkrzExtract 都 **0 文件**（拖放被接受、任务静默结束）。

- 包头与其它 9 个包完全一致（标准 XP3）；**索引被 Core 自动 dump**（1058 B，仅 3 条目）。
- 手工 hexdump 索引解码出真相：**3 条目 = 1 个 157B 的整蛊声明 txt（"Warning: Extracting this
  archive may infringe on author's rights."，日文名超长）+ `logo.mpg` + `pv_movie.wmv`**。
- **Lock 的手段是「TOC 的 segm 偏移/大小字段混淆」**：真实视频条目的 (offset,size) 两个字段
  被写成相同的大数（logo: 0x650004；pv: 0x8e39bbd=其真实大小），工具按此切分自然 0 产出。
  声明 txt 条目的 segm 反而是明文（offset 88, size 157）。
- **破解 = 用数据本身定位**：MPEG-PS 包链扫描（`00 00 01 BA` 起始码、2048B 扇区）——
  包链 951..6,618,039 连续（=logo.mpg，明文 MPEG-PS 6,619,136B，mpeg1video 1280x720 + mp2，4.98s），
  其后紧跟 `00 00 01 B9`（PS 结束码）+ **明文 ASF 头** `30 26 B2 75 8E 66 CF 11...`
  （=pv_movie.wmv，149,056,477B，wmv3 1280x720 + wmav2，124.2s）。**数据全部未加密**，
  只有 TOC 偏移被混淆——按魔数/包链定位即可直接切出。
- 两个视频 ffprobe 全过；声明 txt 按同样思路从每个包的 offset 88 提取（8 个包各带一份）。
- **对账 5724/5724**：每包索引条目数（58+102+43+401+126+1348+397+3+40+57+3149）与盘上文件数
  分毫不差；7 个包差的 1 条目就是各自包内的声明 txt（KrkrExtract 跳过不落盘，手工补齐）。
- 经验：**「工具静默 0 产出」先查 TOC 是否被混淆（offset==size 是强特征），再用数据魔数
  （包链/文件头）自行定位**——数据层往往没加密。

### 17.8 本次新增脚本

- **`krkr_auto_extract.py`** —— 一键自动化：ASCII stage（硬链接 xp3 + 全量复制其余文件）→ CLI 注入 →
  Explorer 拖拽逐包提取 → 完成判定 → 移动产物。参数 `<游戏目录> [--out DIR] [--keep-stage]
  [--only a.xp3,b.xp3] [--reuse-stage]`。
- `_uia_item_rect.ps1` —— UIA 取元素物理矩形（DPI 自检 + 换算）。
- `_krkr_tlg_convert.py` —— tlg2png 批量转换 + PNG 魔数校验（Python 版，替代 ps1 以避开 CJK 路径）。

## 18. `cases/` 案例库（2026-11-01）——指纹签名 → 已验证解法，跳过 LLM

蓝图 §2.7 的「自愈闭环」要求：新游戏进来先算 (格式签名哈希, 目录特征) 查案例库，命中就直接套用
已验证的 (decoder, plugin/key, 备注)，跳过 LLM 推理（L0）。这是终局软件「决策树 + 已验证工具 +
实测证据」三件套里的第三件。

### 18.1 指纹签名机制

**`fired_ids` 是签名的稳定来源**：`rules/__init__.py` 的 `Result` 加 `fired_ids: set[str]`，
`evaluate()` 末尾 `res.fired_ids = set(fired)`；`galgame_dispatch.py` 的 `Report` 加同名字段，
`scan()` 里 `rep.fired_ids = set(res.fired_ids)`。**不改 `facts`**，所以 `golden_detect.json`
（锁 engine/score/evidence/facts）零漂移。

签名 = `sha1(engine + 命中信号 id 集合)[:12]`。信号 id 必须给全——2026-11-01 前 Ren'Py 的 3 个信号
都没 id，指纹退化成空集（Swipe Right 实测 fired=[]），签名根本算不出来。给 9 个引擎共补了
**25 个语义 id**（Unity 6、KiriKiri 1、Ren'Py 3、Tyrano 2、RPG Maker 2、AdvHD 3、Yu-Ris 3、
ExHIBIT 3、CatSystem2 2）。

### 18.2 case schema 与两类来源

每个样本一个 JSON（`cases/<case_id>-<engine>.json`），核心字段：
`case_id`（= sha1(engine + 信号集 + 样本 slug + discriminator)[:12]）、`engine`（**规范名**，
与 `fingerprint.engine` 一致）、`engine_label`（人读的描述名）、`discriminator`、
`fingerprint`、`decision`（extractor/archive_exts/archive_count/expected_total）、`timing`、
`result`（counts/verify/reconcile/ok/source/summary）、`failures[]`（stage/symptom/root_cause/fix/ref）、
`provenance`（source/manifest_path/doc_refs）。

**两类来源，两种可信度**：
- `manifest` —— 从 `_extracted/*/manifest.json` 机械重建，counts/verify/reconcile/timing 逐字取，
  不手填不估算。这是**地面真相**。
- `docs-reconstructed` —— 从 AGENTS.md 样本表 + verified-findings.md 提炼。产物目录已不存在
  （或从未跑过 orchestrator），所以 counts 是**文档记载的摘要**。**诚实纪律**：`manifest_path`
  必须 null、`result.counts/verify/reconcile` 必须 null（不许伪造 manifest 口径的数字）、
  `failures[]` 每条必须有 `ref`。

### 18.3 三个真实坑（都花过代价）

1. **同签名不同解法**：兼职人妻（GARbro 直接解）与高慢妻陥落！！（必须 KrkrExtract 动态注入）
   **指纹完全相同**（都只有 `xp3`/`xp3_known_names`，规则无「加密 xp3」信号）。案例库必须靠
   `discriminator` 字段区分（`xp3-plain`/`xp3-encrypted`/`xp3-encrypted-krkrZ`），不能只靠签名。
   → 规则表的判别力上限就在这里，案例库的 discriminator 是第二道判别。

2. **`engine` 字段误用描述性标签**：早期用 `_failures_raw.json` 里的「KiriKiri 加密」当 engine，
   与 `fingerprint.engine`（规范名「KiriKiri」）不一致，按指纹查会错位。已改为以 `gd.scan` 的
   规范名为准，描述性标签另存 `engine_label`。

3. **`write_all` 不清陈旧文件**：case_id 随 engine 规范化会变，不清的话旧文件残留（实测踩过：
   SPITE 早期被映射成 Tyrano/Electron 的残留 case 文件）。build 时先删非保留 json 再写。

### 18.4 构建器与测试

`build_cases.py`（`--from-manifests` / `--from-docs` / `--index` / `--validate`）+ `tests/test_cases.py`
（21 个测试，锁纯函数 + 构建产物 + 诚实纪律）。测试 **453 passed / 8 skipped**，
`python tests/make_golden.py --check` 零漂移。

### 18.5 接入 orchestrator（2026-11-01）——查表只报告，不接管决策

**做法**：`case_lib.py` 成为「签名 + 查表」的**唯一出处**（`build_cases.py` 与 `orchestrator.py` 都调它；
两处各写一份签名算法必然漂移，而签名就是查表的钥匙，漂移等于查不到）。
orchestrator 新增**阶段 1.5 `case-lookup`**，位于 `detect` 之后、`IMPLEMENTED` 链路检查**之前**——
这样**未接链路的引擎也能看到历史案例**（SPITE 判成 Tyrano/Electron，退出码 2，但案例里记着
`_spite_decrypt` 的 ChaCha20 路径与 4 条坑）。命中写进 `manifest.source.case_match`
（与 `source.unsupported` 同理：读 manifest 的人读 `source`，不会去翻 `stages[*].data`）。

**四条设计纪律**：

1. **查表只报告，不接管决策**：案例的 `expected_total` **不参与对账**。对账的地面真相永远是编排器
   自己从归档索引算出来的数（`_rpa` 索引 / `_grp` TOC / `_cs2` 头…）。案例里的数字是「上次解出多少」，
   不是「这次应该解出多少」——拿它当判据，案例写错就会把一次正确解包判成失败（§16.6 护栏算错
   比不设护栏更坏的翻版）。退出码、对账口径、manifest 顶层 schema 一律不动。
2. **三种结局一律 `ok=True`**：命中 N 个 / 无匹配 / 案例库缺失或损坏。区别只在 `detail` 与 `data`。
   把「看过案例库，没有」和「根本没有案例库」混成同一种空，等于**无声漏验**（`.mos` 教训的翻版）。
3. **`--engine` 强制模式也要能查**：detect 没跑 → `fired_ids` 缺失 → 阶段自己补一次**只读** `gd.scan`
   拿指纹；扫描失败也只是 `skipped`，绝不抛异常、绝不让解包失败。
4. **同签名靠 `discriminator` 区分**：KiriKiri 三样本共享 `6519ddb81f58`，`lookup()` 必须**全部列出**
   （按签名分组、不取第一个），人读的 `detail` 带 discriminator 标签，否则「命中」等于给了个错答案。

**测试**：`tests/test_case_lookup.py` 41 个（40 passed / 1 skipped）。两条最值钱的断言：
① **每个 case 文件都能反算回自己的 `signature` 与 `case_id`**——算法一改，所有既有 case 立刻对不上，
   测试当场红（比断言某个魔法常量可靠，常量会跟着实现一起改）；
② 真实目录上跑阶段：`兼职人妻` 命中 3 个 KiriKiri 变体、SPITE 命中 `4955589831f2-Tyrano-Electron`。
全量 **493 passed / 9 skipped**，golden 零漂移。


### 18.3 Artemis 链路真机证据（`Toshiue Kanojo`，2026-11-02）

- 判定：`iarsys64.dll` / `iarsys32.dll` / `iarsys.dll` + `.pfs` 分卷封包（D:\HY 深度 3 普查 8/8 共遇）；`.pfs` 头 `706638` (=pf8)，分卷形如 `<base>.pfs.NNN`（Amakano3 还有 `.000/.001/.002/.003/.005`）。
- 工具：`_pfs_extract.py`，按 `SHA1(索引区)` 取 key，逐包解密，按包名落 `raw/<包名>/`。GARbro 能解 pf8，不属坑 1 假阴性。分卷不是独立封包，每包一个子目录，跨包重名约 70。
- orchestrator 链路（第 10 条）：`stage_extract_artemis` 调 `_pfs_extract.py` 产出归档条目 3977，再由 orchestrator 复制散装媒体 31 个（`.dat/.jpg/mp3`），共 4008 文件。对账口径拆分——`_pfs_extract.py` 只对账归档子目录 3977，散装媒体由 orchestrator 层对账 4008，两者口径不混淆。
- 实测：`Toshiue Kanojo` detect=Artemis score=90（fired `artemis_pfs`、`artemis_runtime`）；3 个 `.pfs`，3977 + 31 = 4008，diff=0；verify 图片 1007/1007、音频 2597/2597、视频 1/1，失败 0；manifest 写入，全链 235.5s，退出码 0。case-lookup 命中 `d51d21d26882`（manifest 来源，expected_total=4008）。

---
---

## 19. Windows 打包可行性（PyInstaller 冻结实测，2026-11-01）

**探针**：`_spike_pkg/probe.py` + `_spike_pkg/run_probe.py`（可重跑；`dist/`、`build/` 用完即删）。
环境：**Python 3.14.6 + PyInstaller 6.22.3，onedir**，产物 **66.3 MiB / 182 个文件，冷启动 0.67s**。

### 19.1 结论表

| 问题 | 实测结果 |
|---|---|
| 冻结后调**原生 exe**（ffprobe） | ✅ 正常，`ffprobe_ex` 返回 reason='ok' |
| 冻结后调 **.NET exe**（GARbro） | ✅ 正常，`garbro_list` 2562 条 / 1.42s |
| **CJK 路径**（`D:\HY\pork社\兼职人妻`） | ✅ 正常，scan 判出 KiriKiri(90) 并命中 3 个案例 |
| Pillow / numpy / pycryptodome 在包内 | ✅ 全部可 import（12.3.0 / 2.5.3 / 4.0.0） |
| 业务代码 in-process 跑 | ✅ 冻结包里 `_rpgmv_decrypt.iter_candidates()` 返回 **1585 条**（与文档口径一致） |
| **数据文件自动打包** | ❌ **不会**——`rules/engines.json` 缺失直接 `FileNotFoundError` 崩 |
| **`sys.executable` 拉兄弟脚本** | ❌ **必坏**——`[sys.executable, "orchestrator.py"]` 变成「冻结点自己跑自己」，rc=2 `unknown mode: orchestrator.py` |
| 子进程环境 | ⚠️ **`_MEIPASS` 被塞进 PATH**（`...\_internal\pywin32_system32` 排第一），会继承给所有子进程 |
| 动态 `importlib.import_module` | ⚠️ PyInstaller 静态分析**看不到**，14 个兄弟模块只有被静态 import 的 `_rpgmv_decrypt` 进了包 |

### 19.2 三个必修（按优先级）

1. ✅ **兄弟脚本调用改 in-process —— 已完成（2026-11-02）**。`orchestrator.py` 原有 **7 处**
   `subprocess.run([sys.executable, "<脚本>.py", ...])`（Ren'Py / krkr GUI / RPG Maker / Yu-Ris /
   ExHIBIT .grp / CatSystem2 / Unity FSB5 多轮累积）。冻结后这条通路从根上不存在。
   **实做**：① 7 个兄弟脚本统一 `main(argv: list[str] | None = None) -> int`（内部不 `sys.exit`；
   手动解析 `sys.argv` 的 `_rpgmv_decrypt` / `_ypf_extract` / `_cs2_int_extract` / `_as_audio_collect2`
   改成 `argv = sys.argv[1:] if argv is None else list(argv)`，argparse 的传 `parse_args(argv)`；
   krkr 补了 `return 0`）；② orchestrator 新增 **`_run_sibling(mod, argv) -> (rc, 输出全文)`**——
   `redirect_stdout/stderr` 收输出（与子进程时代 `capture_output` 的日志形态一致）、`SystemExit`
   按其 code 折算 rc（兜底 usage 路径）、其他异常降级 rc=1 + traceback 进输出（对应当年 stderr）、
   **KeyboardInterrupt 不拦**；③ orchestrator 顶部**静态 import** `rpa_extract_organized` /
   `krkr_auto_extract` / `_as_audio_collect2`（另 4 个本来就有）——PyInstaller 静态分析只认这个。
   **护栏测试 3 条**（test_orchestrator.py §8.5）：AST 检查 orchestrator 代码里不许再出现
   `sys.executable` / `subprocess.*`（用 AST 不用文本匹配——docstring 里的说明字样不算违例）、
   7 模块 `main` 签名锁定（argv=None + -> int）、`_run_sibling` 契约（收输出/降级/折算）。
   测试 fake 从 patch `orch.subprocess.run` 改为 patch `orch.<mod>.main`（in-process 下 argv
   直接就是 `[<参数>...]`，没有前导 python/脚本名）。全量 **496 passed / 9 skipped**（493+3），
   golden 零漂移；5 个脚本 CLI 无参退出码逐个冒烟与改前一致；rpgmaker 链路测试**真跑 in-process**
   `_rpgmv_decrypt.main()`（fixture www 实解密）通过。
   这一改同时解决「子进程环境被污染」与「错误信息跨进程丢失」两个老问题。
   替代方案（随包带私有 `python.exe`）不选：多一份运行时、还要管 stdlib 路径，换不来好处。
   已知取舍：`_as_audio_collect2` 子进程时代的 `timeout=3600` 进程内给不了——超时防护由
   外层对账兜底（少音频必然对不上）。
2. ✅ **数据文件必须显式打包 —— 已完成（2026-11-02）**。清单落在 **`build_exe.py`**（唯一出处，
   `python build_exe.py --check` 可单独校验）：`rules/`、`cases/`、`_gyu_tool.cs`、`_hg3_tool.cs`、
   **`_uia_item_rect.ps1`**（krkr GUI 链路的伴侣脚本，本次盘点新发现——krkr_auto_extract 按
   `__file__` 调它，漏打 GUI 链路就崩）、`toolbridge.json`（可选，存在才打）。
   各数据文件的定位全是 `Path(__file__).parent` 相对（rules/__init__ 45 行、case_lib 27 行、
   toolbridge 65 行、krkr_auto_extract 134 行），add-data 用 `;.` 镜像仓库根布局即可命中。
   **不需要 --hidden-import**：orchestrator 对 7 条链路全部顶部静态 import（必修第 1 条后），
   PyInstaller 静态分析跟得全；asar_tool/_advhd_run/_spite_* 等 orchestrator 够不着的独立脚本
   **故意不进包**（§19.1「14/14 可 import」是探针口径，不是产品口径）。
   **冻结实测**：`build_exe.py` 产物 66.3 MiB / 183 文件；真样本 `常識改変学園-製品版-` 上
   dry-run rc=0（detect 命中 RPG Maker + case-lookup 命中案例，`case_path` 就在包内
   `_internal\cases\`）；**全链 rc=0（124.2s）：extract in-process 1585/1585 对账 0 差、
   图片 719/0 失败、音频 866/0 失败、媒体 651.4 分钟、manifest ok=true**——与文档口径逐项一致。
   驱动脚本 `_spike_pkg/run_frozen_smoke.py`（`--full` 跑全链；CJK 样本路径由脚本从文件系统解析，
   不进命令行）。教训（§19.3）：--add-data 的相对路径相对 **spec 目录**解析——脚本一律传绝对路径。
3. ✅ **PATH / DLL 环境卫生 —— 实质已在 toolbridge 里（盘点 2026-11-02），冻结态已实证**。
   `_sanitize_env()`（剥 PATH 里一切含 `_MEI` 的段 + 删 PYTHONHOME/PYTHONPATH）与
   `_clear_dll_dir()`（`SetDllDirectoryW(None)`）覆盖 toolbridge 全部 4 个子进程出口：
   `build_csharp`（csc，env 清洗）、`_run_exe`（通用外部 exe：ffprobe/tlg2png/gyu/hg3，
   清洗 + 清 DLL 目录双做）、`garbro_list`（env 清洗）、`assetstudio_export`（双做）。
   冻结全链 866 个 ogg 的 ffprobe 全过 = 卫生处理在冻结态有效（§19.1 曾实测污染确实存在：
   `_MEIPASS` 排 PATH 第一位）。

### 19.3 复现

```bash
python -m PyInstaller --noconfirm --clean --onedir --name probe \
  --distpath _spike_pkg/dist --workpath _spike_pkg/build --specpath _spike_pkg \
  --add-data "D:/K/deepseek/rules;rules" --add-data "D:/K/deepseek/cases;cases" \
  --add-data "D:/K/deepseek/_gyu_tool.cs;." --add-data "D:/K/deepseek/_hg3_tool.cs;." \
  --hidden-import orchestrator --hidden-import _pna_carve ... probe.py
python -u _spike_pkg/run_probe.py
```

**教训**：`--add-data` 的相对路径**相对 spec 目录**解析（不是 cwd），必须用绝对路径或先 cd 到 spec 目录——
否则报 `Unable to find ...\_spike_pkg\rules`。

### 19.4 安装器（Inno Setup 6.7.3，2026-11-02）—— **已废弃删除（2026-11-04）**

> 本节保留为历史实测记录：用户 2026-11-04 决定只发便携版，`installer.iss` 与
> `--installer*` 参数已删除。下面的数据不必再复现，但「安装器在本机被 EDR 拦」的
> 证据链（§20 / antivirus-false-positives.md §5）仍是删除决策的依据。

- **构建**：`build_exe.py --installer` → `packaging/Output/GalgameUnpacker-0.1.0-setup.exe`
  **22.8 MiB**（onedir 66.3 MiB → lzma2/max solid），SHA256 打进输出。ISCC 解析顺序与
  toolbridge 同构：`TOOLBRIDGE_ISCC` → 内置候选（`%LocalAppData%\Programs` 与 Program Files
  的 Inno Setup 6/7，winget 用户级装在 LocalAppData）→ PATH。
- **设计**（蓝图 §4.2/4.4/4.6）：`PrivilegesRequired=lowest`（不提权、装
  `{localappdata}\Programs`）；.NET Framework 4.6+ 注册表检测（`Release >= 393295`）**只提示
  不拦**——纯 Python 链路没有 .NET 也能跑，GARbro/csc 链路需要；无 PATH 修改、无自启；
  `{cm:OpenExplore}` 不是内置消息（编译期才报）——自定义文案一律写字面量。
- **会话内验证（testmode）**：`--installer-only --testmode` 出 `Uninstallable=no` 构建配
  `/NOICONS` → `/SILENT` 安装 rc=0、184 文件全落位（orchestrator.exe + `_internal\rules\`
  + `_internal\cases\`）、**安装出来的 exe 对真样本 dry-run rc=0**。
- **为什么需要 testmode**：本代理会话对「未签名未知镜像」过滤敏感面写入——正式构建在
  会话里跑 `/SILENT` 时 184 文件复制全成功，但开始菜单 .lnk（`IPersistFile::Save
  0x80070005`）与 HKCU 卸载键（`RegCreateKeyEx code 5`）被拒 → 回滚 rc=4。证据链与
  排查过程见 `antivirus-false-positives.md` §5；**卸载键/快捷方式两步要真实桌面会话验证**。
- **Git Bash 旗标改写坑**：`/SILENT` 会被 MSYS 路径转换改成 `C:/Program Files/Git/SILENT`
  → 安装器变交互模式（弹窗）。给原生 exe 传旗标一律 `MSYS_NO_PATHCONV=1`。

## 20. 软件加固实测（2026-11-03）——假绿/假红的根因与修复证据

本轮目标是把「纪律只落地一半」的部分收口。架构师 + QA 双线只读审计出 **P0 3 / P1 9 / P2 12**，
修复按 A（交付正确性）/ B（可用性安全）/ C（性能清场）三批落地，QA 独立复验两次打回重做。
版本 0.1.0 → 0.1.1。这里只记**实测证据**，行为清单见 AGENTS.md。

### 20.1 P0-1「失败运行打印上一轮成功数字」的复现
把 `Happiness Double Room/png` 改名制造验收失败，盘上留有上一轮成功 manifest：
- 修前：退出码 1，屏幕却报「3500 个文件 / 0 失败」（读的是旧文件）；
- 修后：失败运行落盘 `ok:false, error:"verify-failed", counts.final.total=1`（本轮实测值），
  CLI 打印「失败原因： verify-failed」，**绝不回读磁盘**（`_result_manifest` 取不到就明说）。
回归：`test_run_failure_overwrites_stale_manifest_on_disk`（预置 final=3500 的旧文件，断言落盘是 1）。

### 20.2 验收吞吐（3500 文件 / 1441 音频，`_work_probe/bench_stage_verify.py`）
| jobs | 耗时 | 相对 |
|---|---|---|
| 1 | 188.02s | 1.00× |
| 4 | 85.38s | 2.20× |
| 8 | **68.38s** | **2.75×** |
三档 counts/detail 逐字一致；`test_parallel_verify_matches_serial_byte_for_byte` 钉住「并行不改变
结论与顺序」——这条是并行化唯一正确性屏障，删它=放弃并行正确性。

### 20.3 Unity Texture2D 的两个口径（都是实测）
- `My Wife Wants to Be a Professional Cosplayer`：Texture2D JSON 枚举 460 / Convert 455（差 5）。
- `Happiness Double Room`：**1045 枚举 / 1044 导出（差 1，0.1%）**。
旧写法 `expected = 总数 − 缺口` 让缺口任意大；新写法：缺口不削减 expected、
非 Texture2D 类严格相等、总短缺必须恰等于 Texture2D 缺口、比例 >2% 或 >20 个才放行。

### 20.4 golden 基线的「绝对路径」病（QA 在副本里发现）
`tests/golden_detect.json` 曾存 `D://K//deepseek//_fixtures//unity_game//MyGame_Data`，
`test_fixture_matches_golden` 逐字比对 → **仓库挪个位置必红**（QA 在 `_work_qa/pin/` 副本实测 1 failed）。
修复：`make_golden.normalise_paths` 把仓库内绝对路径换成 `<repo>/<相对 posix 路径>`（仓库外的
`D:/HY/...` 原样保留，那些是本机事实），生成/比对两侧共用同一函数。
验收方式（**不能用 grep**，JSON 里是双反斜杠、正则匹配不上——恒 0 假绿）：
把 `tests/ rules/ cases/ _fixtures/ *.py pytest.ini` 拷到别的路径，跑 `pytest tests/test_dispatch.py -q` → 34 passed。

### 20.5 本机删除守卫与 pytest 的三重坑（都会假绿/假红，花了半天才定位）
1. `--basetemp` 指到仓库所在盘 → 守卫拦测试内部清理 → 5 条无关用例假失败
   （`SHFileOperationW 0x2`；守卫对 OS TEMP 直接放行，对仓库盘 fail-closed）。
2. pytest 退出清理临时目录撞守卫 → **测试全绿但 exit=1**（sitecustomize 在 rmtree 里
   `raise SystemExit(1)`，`ignore_errors=True` 拦不住 BaseException）。
   → 基线判定一律 `python tests/run_all.py`（junitxml 的 failures/errors 才是真相）。
3. `%TEMP%\pytest-of-<user>\` 会**无限积累**：本轮实测已堆到 **35 GB**（含 preflight 测试的
   1 GiB 稀疏文件 × 多轮）——守卫频繁触发、磁盘告急的根源都在这，已清空一次；
   `pytest.ini` 的 `tmp_path_retention_policy = none` 让每轮结束即删，不再积累。
4. 两个 pytest 进程并发（共用编号目录）→ 成片 `FileNotFoundError`，像 155 条真失败。

### 20.6 GUI 轮询器被「没验成」的摘要打死（QA+架构师实测，批次引入的回归）
`verify.media_minutes` 在没验成的结局里是 **null**；`f"{ver.get('media_minutes', 0):.1f}"`
对 None 抛 TypeError → `_poll` 的 `after()` 在异常路径上永远执行不到 → 摘要不弹、
队列没人消费、再点开始也看不到结果，**只能重启程序**。触发面：空产物、verify 边界取消
（批次 B 新加的取消按钮恰好命中）。修法：文案抽成模块级 `summarize_text()` 纯函数并显式
区分「未统计」，`_poll` 事件异常只记日志；**manifest 侧 null 保持不动**（null=没测过 ≠ 0.0=测过是 0）。
护栏用 `App.__new__` 造壳（不建真 Tk），修前红（TypeError + after 0 次）修后绿——
**本机 `tk_root` fixture 约 11/12 的运行会撞「无可用显示」skip，依赖真 Tk 的护栏等于没写**。

### 20.7 工程纪律沉淀（这轮反复出现的病，三条）
1. **「测试加了」≠「测试有用」**：本会话出现 3 次「绿着但没验到东西」（盲杀进程的 fixture、
   永久 skip 的 case lookup、依赖显示的 GUI 测试）。要求：新增护栏必须附**修前红/修后绿**两次输出。
2. **自报数字必须独立复核**：工程师报「golden 已修」用的是 grep（假绿）；QA 抓回来重做。
   同一session里「写的人自己也信了」的验收命令，风险最高。
3. **成员会犯「凭名字推断、没跟到定义」的错**（QA 自己错了两次）：定案前要求给出
   可复现命令，而不是结论。

## 21. v0.1.2 收尾（2026-11-04）——重跑口径、契约归一、子进程诊断

v0.1.1 遗留 8 项（「未做，明确留给下一轮」）+ 许可证核实，本轮全部处理完。
基线：开工前 626 tests / 0 failures / 0 errors / 9 skipped、golden 零漂移；
收尾后见 §21.10。

### 21.1 raw 非空静默叠跑（最危险的一条）

**问题**：`--out` 指向已有产物的目录时，旧实现直接往里写。后果不是报错，而是
「上一轮 3500 + 本轮 3500 = 7000」，而 `reconcile` 拿本轮 expected 去比落盘总数照样
`diff=0` —— 一份**看起来完美**的交付记录。对账纪律只能抓住「索引 vs 落盘」，
抓不住「落盘里有不属于本轮的东西」。

**修法**（三处，缺一不可）：
1. `stage_preflight` 开头做**只读**检查：raw 非空且既没 `--reuse-raw` 也没 `--overwrite`
   → 当场 `ok=False`，detail 同时给出两个出口（覆盖 / 复用）。放在体积统计**之前**：
   否则用户白等几十秒的 `_tree_bytes` 才被告知跑不了。
2. `run()` 在 preflight 之后、extract 之前清场（`reset` 阶段）：`raw/` 与 `png/` **一起**清。
   只清 raw 会让上一轮的转换成品混进本轮 final 口径。清不掉（守卫/受保护目录）→ 直接
   失败 `reset-failed`，绝不「清一半继续跑」。
3. GUI 侧：`has_stale_products()` 检测到残留 → `askyesno` 二选一（清空重跑 / 取消换目录），
   选「是」才把 `overwrite=True` 交给 `Ctx`。GUI 不该让用户去背命令行开关。

**证据**：`test_preflight_fails_on_stale_raw_without_overwrite`（且断言预检**不删**文件）、
`test_run_stops_before_extract_when_stale_raw`（extract 调用次数 = 0）、
`test_run_overwrite_clears_raw_and_png_then_extracts`、`test_preflight_does_not_block_reuse_raw`。

### 21.2 `source.archives` 四条链路三套键名

**问题**：orchestrator 内部用 `archive/expected/got`，写 manifest 前转成 `name/entries/extracted`；
krkr 直接写 `name/files/total_after`；cs2/unity/pfs 写 `name/entries`。读 manifest 的下游
必须按链路分支兼容 —— 「同一份契约」名存实亡。

**修法**：`manifest.normalise_archives()` 做**唯一**归一化，挂在 `manifest.build()` 这个
唯一出口上（新链路天然守规矩，不用每个作者记一遍）。规范三键 `{name, entries, extracted}`
总是存在，附加键（`listable`/`note`/`total_after`）原样保留。

**语义必须分清**（这是当初混用的根源）：
- `entries` = **地面真相**（索引/枚举声明的条目数），没有就是 `None`
- `extracted` = **实际落盘数**

所以 krkr 的 `files`（加密包实测新增）映射到 `extracted`，`entries` 留 `None` ——
加密包没有索引，把实测数写进 entries 等于伪造对账。cs2 反过来：有索引没实测，
`entries=2 / extracted=None`。

**连带改动**：`krkr_auto_extract` 产出改为直接写规范键；`_unity_extract.extract_all`
的 archives 从 `{name, entries: n}` 改为 `{name, entries: None, extracted: n}`（原来把实测
数写成 entries，语义是错的）；`test_cs2_int_extract` / `test_krkr_manifest` 断言同步。

### 21.3 `manifest.verify.status` 单值结论

**问题**：verify 块有 8 个散字段，消费方要自己拼「验没验成」。拼错的方式有很多：
把 `verified=False` 当失败（冤枉 `--no-verify` 的正常运行）、只看 `verified` 忽略
`image_fail>0`（有坏图却报 ok）。

**修法**：`manifest.verify_status()` 纯函数，四态 `ok/partial/failed/skipped`：
- `skipped`：没有 `verified` 字段，或 `reason in (disabled, not-run)`
- `failed`：验了但没走完（`cancelled` / `no-products`）
- `partial`：走完了但有失败（`fail_total > 0`）
- `ok`：走完了且 0 失败

判定输入优先 `fail_total`（stage_verify 自己算的总失败数，含「零字节超护栏」这一条
只有阶段知道的信息），老 manifest 退回三类媒体失败计数。`normalise_verify()` 在 build 时
补齐 4 个判定字段（`image_fail/audio_fail/video_fail/zero_byte`）并写入 status。

**关键细节**：`reason` 是「没验」与「验失败」的唯一区分依据。三种「没验」各有来源：
`--no-verify` 由 `stage_verify` 写 `disabled`；加密 krkr 的工具自己写 `not-run`；
**前面阶段就失败（verify 压根没跑）**由 `build_manifest` 检测「stages 里没有 verify」补
`not-run` —— 端到端冒烟实测过这条：extract 失败的 manifest 原本被判成 `failed`，
补上之后才是 `skipped`。CLI 摘要打印 `[ok]/[partial]` 前缀，GUI 摘要打印 `验收[status]`。

### 21.4 Unity 子进程的 rc/stderr 被吞（假绿的温床）

**问题**：`_unity_extract._run_as()` 直接丢掉 `CompletedProcess`。于是「AssetStudio 起不来
（缺 DLL / 被安全软件拦 / 路径错）」和「这个游戏确实没这类资产」在日志里**长得一模一样**
——都是 `0`。而 AssetStudio 的 rc 本来就不可信（坑 4：exit=0 也能一个不导），所以 rc
不能当成功判据；但 rc≠0 时的 stderr 是唯一能解释「为什么一个都没有」的证据。

**修法**：
1. `_run_as` 返回 `CompletedProcess`，捕获 `TimeoutExpired`（rc=-9）与 `OSError`（rc=-2），
   把异常变成可读诊断而不是裸栈。
2. 子进程环境走 `toolbridge._sanitize_env()` + `_clear_dll_dir()`（蓝图 §4.3：冻结包
   `_MEI` 目录混进 PATH，.NET 会优先加载包内同名 DLL）。这条此前只覆盖 toolbridge 的
   出口，`_unity_extract` / `_as_audio_collect2` 这两个自己 `subprocess.run` 的地方漏了。
3. `expected_counts` / `extract_all` 返回 `errors` 列表（`"<type>: rc=N，<stderr 尾 400 字>"`）；
   orchestrator 把 errors 拼进 `st.detail`（枚举 0 个时）和阶段日志（stderr 在冻结包不进 GUI）。
4. `_as_audio_collect2.enumerate_names` / `_export` 同样补 rc 告警与 env 清洗。

**证据**：`test_run_as_passes_sanitized_env`（注入 `PYTHONHOME`，断言被洗掉）、
`test_run_as_turns_missing_exe_into_diagnostic`（rc=-2）、
`test_expected_counts_reports_rc_and_stderr`（rc=3 仍照数，但 errors 有 stderr）、
`test_extract_all_reports_convert_rc`。

### 21.5 Unity 合并产物时把路径拍平（静默丢文件）

`extract_all` 的断点续跑分支用 `relative_to(src).name` 把产物拍平到 `dst/` 根下，
并且 `if not tgt.exists(): copy`。AssetStudio 一旦按子目录输出（`BySource`/多级分组），
不同目录下的同名文件就互相顶掉，而且**完全无声** —— 计数看起来正常，少的那几个
永远不会出现在任何报告里。

**修法**：保留相对路径 `dst / f.relative_to(src)`；同路径同内容（size + sha1）= 重复导出，
跳过；同路径不同内容 = 真冲突，抛 `ValueError` 拒绝静默覆盖，提示清空 raw 加 `--overwrite`。

**证据**：`test_merge_keeps_relative_paths`（`sub/a.png` 必须落在子目录里）、
`test_merge_refuses_conflicting_same_name`、`test_merge_skips_identical_duplicate`。

### 21.6 `find_tool` 每次调用都读配置

Unity 链路一次跑 58 轮 AssetStudio（1441 条音频），每轮 `find_tool` → `_load_config`
都要 stat + 读 + 解析两个 JSON。纯重复 I/O。

**修法**：进程内缓存，key = `(路径, mtime_ns, size)` 三元组 —— 用户中途改配置（哪怕同一秒）
下一次调用就失效重建，比「启动读一次」安全。返回浅拷贝，调用方改不脏缓存。
`_config_paths()` / `_config_stamp()` 独立成函数便于测试定位。

**证据**：`test_load_config_is_cached_across_calls` 用「改内容 + 把 mtime 还原」证明第二次
**真的没读盘**（若读盘会拿到新值）——这比数调用次数更硬，不依赖 monkeypatch 计数。

### 21.7 `close_all_explorers()` 会关掉用户自己的窗口

旧实现枚举**所有** `CabinetWClass` 然后关掉。用户当时可能正在拷文件 —— 这不是「副作用」，
是数据损失。而它存在的目的只是清掉自动化自己 `explorer /select` 开出来的窗口。

**修法**：`all_cabinets(hint)` 按窗口标题过滤；`close_all_explorers(hint)` 的 hint
**故意不设默认值**（签名即护栏，想改回全关必须改签名，`test_close_all_explorers_requires_hint`
会拦住）。调用处传 `os.path.basename(stage)`。`find_explorer_by_title_hint` 复用同一枚举。

### 21.8 GUI 默认输出落进程序安装目录

冻结态 `APP_ROOT` = `{localappdata}\Programs\GalgameUnpacker`，`default_out_dir` 又把产物
写在 `<APP_ROOT>/_extracted/` 下。两个后果：卸载程序把它一起删掉；用户在那个隐藏目录里
根本找不到自己的图/音频/视频。

**修法**：源码态保持 `<仓库>/_extracted/<游戏名>`（开发者纪律不变）；便携版改为
`%USERPROFILE%\GalgameUnpacker\_extracted\<游戏名>`（**不进 Documents**，原因见 §23）。
README 与 GUI 首行日志同步写明。

### 21.9 随包工具许可证（对外分发前的硬阻塞，已核实完）

| 工具 | 结论 | 依据 |
|---|---|---|
| garbro | MIT | morkt/GARbro |
| assetstudio | MIT（上游）；本 CLI fork 未核实 | Perfare/AssetStudio |
| **tlg2png** | **无许可证（保留所有权利）** | GitHub API `license=null`；vn-tools/tlg2png 仓库无 LICENSE 文件，已归档 |
| **krkr** (KrkrExtract.Lite) | **GPL-3.0** | xmoezzz/KrkrExtract README 明示 GPLv3；exe 版本信息 Copyright © 2020 对应 lite 分支 |
| **krkrz** (KrkrzExtract) | **GPL-3.0** | xmoezzz/KrkrzExtract `license=GPL-3.0`；exe 版本信息 X'moe (C) 2018 v1.0.0.0 对应 release |
| **ffprobe** | **GPL-3.0-or-later** | 本机构建 `ffprobe -version` 的 configuration 含 `--enable-gpl --enable-version3`（BtbN 风格） |

**结论**：三个 GPL-3.0 组件 + 一个无许可证组件。**用户 2026-11-04 明确：私人项目、
完成后转私人仓库、不对外分发 → 不处理许可证义务，本项不再是阻塞**。核实结论保留作
事实备查：将来若要公开仓库或把便携 zip 发给别人，GPL 组件必须随包提供对应源码或
书面报价 + GPL-3.0 全文与版权声明，tlg2png 必须换掉（GARbro 的 TLG 转换或自研），
否则属于未经授权分发。「独立进程调用 = 聚合而非衍生」不豁免各工具自身的许可证义务。
已写入 `build_exe.TOOL_LICENSES`（含依据）与生成的 `bin/NOTICE.txt`。

### 21.10 收尾基线

`C:/Python314/python.exe tests/run_all.py` → **junit: tests=656 failures=0 errors=0
skipped=8 → PASS**（开工前 626，新增 30 条：Unity 7 / overwrite 5 / manifest 7 /
配置缓存 3 / 窗口 2 / GUI 5 / verify-not-run 1）。
`C:/Python314/python.exe tests/make_golden.py --check` → **6 个 fixture + 12 个真实样本
全部与基线一致**（detect 链路未动，零漂移）。

变更文件：
`manifest.py`（+2 纯函数）、`orchestrator.py`（preflight/run/reset/verify.status/--overwrite）、
`gui.py`（输出目录 + 残留询问）、`toolbridge.py`（配置缓存）、
`_unity_extract.py`（rc/env/合并路径）、`_as_audio_collect2.py`（rc/env）、
`krkr_auto_extract.py`（窗口收窄 + archives 键名）、`build_exe.py`（版本 0.1.2 + 许可证）、
`README.md`；新增 `tests/test_unity_extract.py`。

### 21.11 交付形态收敛（2026-11-04 用户决策，收尾后追加）

用户明确的四条，已落到代码/文档：

1. **不做安装器，只发便携版**。删除 `packaging/installer.iss`、
   `build_exe` 的 `--installer` / `--installer-only` / `--testmode`（含 `find_iscc` /
   `ISCC_CANDIDATES`）、以及已产出的 setup.exe。`python build_exe.py` 现在默认
   = 冻结 + 出 `GalgameUnpacker-<版本>-portable.zip`；`--portable` = 跳过冻结重出 zip。
   理由：本机火绒 + 深信服 EDR 拦安装器敏感写入（§20 / antivirus §5），而安装器只换来
   卸载键与开始菜单——对私人工具不划算。杀软文档与 §19.4 保留为历史证据并加了状态标注。
2. **许可证不再作为阻塞**。私人项目、完成后转私人仓库 → 自用不触发分发义务。
   §21.9 的核实结论保留（事实备查），但不再是待办。
3. **夕凪荘 22 BGM dump 舍弃**。用户明确不做；`_bgm_dump2.py` 与 §15.3 的静态分析
   留在仓库备查，不进待办清单。
4. **澄清「GUI 弹窗行为确认」**：指 §1 里 GARbro.GUI 的「选游戏标题 / 输密钥」弹窗疑云
   ——`pork社` 那 4 个游戏 Console 读不出、GUI 能解，怀疑是 GUI 有交互弹窗。
   与 KrkrExtract 运行时的错误弹窗（`#32770`，§17 已处理）是两件事。
   待用户用 GARbro.GUI 开一次那 4 个游戏确认有无弹窗。

顺带清理：`_spike_pkg/dist/orchestrator.build1`（357M）、`orchestrator.prev-0.1.1`（357M）、
`packaging/Output/orchestrator`（357M）三个可重建的旧构建产物已删除。

## 22. 半自动协作（2026-11-04）—— 失败时给可执行的人工方案

### 22.1 为什么改

原来的失败形态是「error code + 一句 detail」。对加密 KiriKiri，detail 写的是
「加 --allow-gui 重跑」——那等于**逼用户选最贵的路**：UI 自动化约 40 分钟、
依赖真实桌面 / DPI / 虚拟桌面，还在别的窗口里点鼠标。而同一件事人工做只要 3 分钟
（打开 KrkrExtract、拖 xp3、等 idle、拷产物）。

「能自动的自动掉，不划算的交给用户」比「为全自动堆复杂度」可靠。所以失败时输出
一份 `ManualPlan`：需要什么、点哪里、产物放哪、做完跑哪条命令。

### 22.2 实现（`manual.py`，纯数据 + 纯函数）

- `ManualPlan(code, summary, why, needs, steps, target, then, alternatives)`
- `plan_for(error, engine, game_dir, out_dir, raw_dir, png_dir, prog, tools, stages)`
  —— 按失败码映射；没有合适方案返回 `None`（不硬凑）
- `render()` / `render_dict()` —— CLI 区块；`as_dict()` —— manifest 块
- `dry_run_plan(...)` —— `--dry-run` 的提前预判（KiriKiri 探一次 `garbro -l`）

接入点只有两个：`_finish_failure()`（所有非 0 退出都走它）与 `main()` 的 dry-run 分支。
`_manual_tools()` 解析随包工具路径，**解析失败不连累失败路径**（给建议的过程本身不许炸）。

### 22.3 实测输出（fixture `krkr_game`，真实 GARbro）

```
[dry-run] 探针：garbro -l bgimage.xp3（几秒）

需要人工介入 · kirikiri-encrypted
--------------------------------------------------------------------------
预判：bgimage.xp3 用 GARbro 列不出目录，正式跑大概率要人工介入。
原因：GARbro 的 Console 版没有「指定游戏标题/密钥」的参数；KrkrExtract 的自动化要模拟鼠标拖拽，慢且挑环境。

需要准备：
  · KrkrExtract.Lite.exe（随包路径：D:/K/galgame/krkr/krkr/KrkrExtract.Lite.exe）

按顺序做：
  1) 打开 D:/K/galgame/krkr/krkr/KrkrExtract.Lite.exe
  2) 把游戏目录下的所有 .xp3 拖进 KrkrExtract 窗口（先拖 data.xp3），等界面状态回到 idle（有进度条就走完）
  3) 解出来的东西在 KrkrExtract 目录下的 KrkrExtract_Output\data 与 ...\png
  4) 把 data\ 里的全部内容拷到：D:/K/deepseek/_work_demo/out/raw
  5) 如果 ...\png 里有东西，一并拷到：D:/K/deepseek/_work_demo/out/png

产物放到：D:/K/deepseek/_work_demo/out/raw

做完重跑这一条：
  python orchestrator.py D:/K/deepseek/_fixtures/krkr_game --out D:/K/deepseek/_work_demo/out --reuse-raw D:/K/deepseek/_work_demo/out/raw

备选方案（不推荐，但不用你动手）：
  · python orchestrator.py ... --allow-gui --overwrite（全自动，约 40 分钟，期间别动鼠标、别切虚拟桌面）
--------------------------------------------------------------------------
```

JSON 侧同时给 `"auto_feasible": false` 与 `manual` 块（8 字段），stdout 保持纯 JSON。

### 22.4 覆盖边界（明确不做的）

磁盘空间不足、raw 非空、verify 失败 —— 这三类失败**没有「人工能帮上忙」的余量**
（换盘/选一个出口/产物已经在了），给指引只会增加噪声。`plan_for` 对它们返回 `None`，
manifest 不写 `manual` 块。这条边界由 `test_unknown_failure_returns_none` 与
`test_failure_without_a_usable_hint_does_not_invent_manual_block` 钉住。

### 22.5 验收

- 新增 `tests/test_manual.py` 12 条 + orchestrator 3 条 + GUI 1 条
- 全量：**672 tests / 0 failures / 0 errors / 9 skipped → PASS**
- 人工产物走**同一条链路**：`then` 里的 `--reuse-raw` 是既有命令，不新增分支 ——
  人工解出来的文件照样进 postprocess/verify/manifest，不会变成「人工的就不验了」

### 22.6 v0.2.0 打磨（同日，交付前）

三处补强，都不改契约（`manual` 块字段不变）：

1. **`kirikiri-gui-failed` 的 `why` 换成排查方向**：GUI 跑过但没产出，多是安全软件拦进程
   或非真实桌面会话（远程桌面/多虚拟桌面让 `SendInput` 失效）。原样重试是 40 分钟的浪费，
   所以这个分支不再复用「KrkrExtract 慢且挑环境」那段泛泛解释。
2. **`engine-no-chain` 点名 `asar_tool.py`**：Tyrano/Electron 是唯一已知的无链路引擎，
   仓库根就有现成脚本；方案里直接给脚本名（不给参数，避免编错）。
3. **方案落 `_work/manual.log`**：GUI 的 worker stdout 不进日志面板、摘要只显示前 3 步，
   用户照着操作时必须能翻到完整步骤。`_finish_failure` 里多一句 `ctx.log("manual", …)`，
   测试断言日志包含「需要人工介入」与第一步原文。

测试：`test_manual.py` 12 → **14 条**（+GUI 失败排查方向、+Tyrano 点名 asar_tool），
`test_failure_carries_manual_plan_for_encrypted_kirikiri` 增加 manual.log 断言。

### 22.6 v0.2.0 打磨（同日，交付前）

三处补强，都不改契约（`manual` 块字段不变）：

1. **`kirikiri-gui-failed` 的 `why` 换成排查方向**：GUI 跑过但没产出，多是安全软件拦进程
   或非真实桌面会话（远程桌面/多虚拟桌面让 `SendInput` 失效）。原样重试是 40 分钟的浪费，
   所以这个分支不再复用「KrkrExtract 慢且挑环境」那段泛泛解释。
2. **`engine-no-chain` 点名 `asar_tool.py`**：Tyrano/Electron 是唯一已知的无链路引擎，
   仓库根就有现成脚本；方案里直接给脚本名（不给参数，避免编错）。
3. **方案落 `_work/manual.log`**：GUI 的 worker stdout 不进日志面板、摘要只显示前 3 步，
   用户照着操作时必须能翻到完整步骤。`_finish_failure` 里多一句 `ctx.log("manual", …)`，
   测试断言日志包含「需要人工介入」与第一步原文。

测试：`test_manual.py` 12 → **14 条**（+GUI 失败排查方向、+Tyrano 点名 asar_tool），
`test_failure_carries_manual_plan_for_encrypted_kirikiri` 增加 manual.log 断言。

## 23. v0.2.0 实测第一个 P0：默认输出目录被终端防护拦（2026-11-04）

### 23.1 现象

用户双击便携版 → 选游戏 → 点「开始」，GUI 立刻弹「运行异常（看日志）」，
摘要显示 `本轮失败：worker-aborted（本轮未产出 manifest）`。日志窗口里的 traceback：

```
gui.py:469 in _worker → orchestrator.py:2380 in run → orchestrator.py:264 in stage_detect
→ gui.py:463 in sink → orchestrator.py:201 in log → pathlib mkdir ×3
PermissionError: [WinError 5] 拒绝访问。: 'C:\Users\27025\Documents\GalgameUnpack...'
```

### 23.2 根因（两层，缺一不成灾）

1. **路径选错**：v0.2.0 把便携版默认输出改成了 `%USERPROFILE%\Documents\GalgameUnpacker`。
   火绒 + 深信服 EDR 按进程信誉拦**未签名 exe** 在「文档」这类受保护目录里创建文件夹。
   实测对比：同一路径下，shell 与 `python.exe` 都能 mkdir + 写文件，
   **只有冻结的 orchestrator.exe 被拒** —— 拦的是 exe 不是路径
   （与 §20 / antivirus §5 的安装器被拦同源）。
2. **失败放大**：`Ctx.log()` 第一步就 `work_dir.mkdir(parents=True)`，而 GUI 的 `_worker`
   不像 `main()` 那样预建目录。于是「日志写不了」直接抛穿到 worker，被 `except BaseException`
   兜成 `worker-aborted` —— 用户看到的是一句「运行异常（看日志）」，
   而日志恰好就是写不进去的那个东西。**诊断通道本身变成了单点故障。**

### 23.3 修法（三处）

1. `gui.user_output_root()` → `Path.home() / "GalgameUnpacker"`（用户目录根下，非敏感区、
   不受 OneDrive 重定向影响）。
2. `gui.ensure_writable(path)`：点「开始」时先 mkdir + 写探针文件，失败弹
   「输出目录不可写」并提示换到 D 盘 —— 当场可修，不留到运行中。
3. `Ctx.log()` 降级：`OSError` 时往 stderr 打**一次**警告，后续日志丢弃，绝不抛。
   日志是诊断不是正确性；这条对所有「输出目录不可写」的场景都成立，
   不只是这次的具体路径。

### 23.4 证据

- 复现对比：shell 与 `python.exe` 写 `Documents\GalgameUnpacker` 均成功；
  冻结 exe 在同一步 `mkdir` 抛 WinError 5。
- 回归：`test_user_output_root_is_under_home_not_documents`（断言路径不含 `Documents`）、
  `test_ensure_writable_returns_reason_on_permission_error`、
  `test_ctx_log_degrades_when_work_dir_is_unusable`（且断言只提示一次）。

### 23.5 教训

**「默认值」必须按最恶劣的运行环境选，不是按最舒服的。** 开发机上 Documents 可写、
OneDrive 没开、杀软没装 —— 三个条件全中才会以为它安全。同一个 bug 在源码态永远复现不了，
因为拦的是 exe 的信誉。

## 24. 失败日志（2026-11-04）—— 记在软件旁边，而不是产物旁边

### 24.1 需求与判断

用户要求：每次失败自动写日志到**软件根目录**，含时间/错误/上下文，写入失败不影响主流程。

关键判断：**不能复用 `_work/<stage>.log`**。那套日志跟着输出目录走，而输出目录本身
可能就是第一个失效的东西（§23 实测：未签名 exe 写 `Documents` 被终端防护拒，`mkdir`
当场抛）。把失败记录放在一个「可能建不出来」的目录里，等于下雨天才发现伞在屋里。

### 24.2 实现（`faillog.py`，纯函数 + 单文件追加）

- 位置：`<软件根>/failures.log`；不可写退 `%LOCALAPPDATA%\GalgameUnpacker\failures.log`
- 格式：纯文本块，一块一条。第一行 `[YYYY-MM-DD HH:MM:SS +ZZZZ] error engine= rc=`，
  缩进字段 `game / out / stage / exc / 自定义 / python+platform / traceback / ---`
- **永不抛**：目录不存在就建；超过 2 MB 轮转 `failures.log.1`；两处都失败 → stderr 一行，
  返回 `None`
- 只输出 `ok=False` 的阶段；成功与跳过的阶段不写（噪声会让人不看日志）
- traceback 只留末尾 40 行（根因在末尾，前面是噪声）

### 24.3 接入点

`_finish_failure`（所有非 0 退出）+ `main()` 的三处早期 return（游戏目录不存在 /
`--reuse-raw` 不存在 / 清空 raw 失败）+ dry-run 判定失败 + `gui._worker` 的
`except BaseException`（线程崩溃不走 `_finish_failure`，最容易被漏）。

### 24.4 验证

`tests/test_faillog.py` 8 条：时间戳格式、上下文齐全、成功阶段不出现、目录自动创建、
主路径不可写降级备用、两处都失败只 stderr、超限轮转、文件头只写一次、多行值压平、
traceback 尾部保留；集成 2 条：`run()` 失败后 `<app>/failures.log` 有该条、
GUI 线程崩溃记 `worker-crashed` 且仍补 `done`。

### 24.5 边界

`failures.log` 是**时间线**，不替代 `manifest.json`：后者是机器可读的交付记录
（`error`/`stages`/`manual`），前者是给人翻的排障线索。两者同一时刻各写一份，
来源一致（都从 `stages` 取），不重复构造第二套事实。

## 25. 「浏览哪个位置都写不进去」（2026-11-04）—— 探针误报 + 进程级拦截

### 25.1 现象

v0.2.1 加了可写性预检之后，用户反馈：**浏览到任何目录都提示不可写**，
换个盘也一样。而之前只有 `Documents` 失败。

### 25.2 两个原因叠在一起，症状一样

1. **探针本身长得可疑**（我的锅）：预检写的是 `.galunpack-write-test`
   —— 点开头 + 无扩展名，正好是终端防护判定「可疑文件创建」的典型形状。
   于是**每个目录**都被判不可写，用户换到天边也没用。
2. **进程级拦截可能真的存在**：如果连正常文件都写不了，那不是路径问题，
   是 EDR 按进程信誉拦这个未签名 exe（与 §23 同源）。

两者必须分开处理：前者改探针，后者只能加白名单。

### 25.3 修法

1. 探针改成 `write-probe.txt`（正常名字 + 正常扩展名），写在目标目录里，写完删掉。
2. `writable_fallback(game_dir)`：默认位置不可写时依次试
   用户目录 → `%LOCALAPPDATA%` → `%TEMP%`，返回第一个能写的 + 每处失败原因。
   GUI 弹「原位置不可写，改用 X 继续吗」——一键可用，不让用户继续瞎选目录。
3. 三处全失败 → 弹窗直接说「这不是目录选错了，是安全软件在拦」，
   并指向 `antivirus-false-positives.md` §6（火绒信任区 / EDR 加白的具体步骤）。

### 25.4 教训

**诊断工具自己也会被拦。** 「写个临时文件试试能不能写」这个动作本身就是被监控的行为；
探针必须长得像正常业务（正常文件名、正常扩展名、写在真实业务目录里），
否则你测的是「探针会不会被拦」，不是「业务能不能写」。

同样的道理适用于日志：`failures.log` 用 `.log` 扩展名而不是 `.tmp`/无扩展名。

## 26. 首个端到端成功 + 输出目录定位（2026-11-04）

### 26.1 成功实证

用户实测 `我与老师的私人课程2`（Artemis）：

```
引擎: Artemis    退出码: 0
交付（final）: 7361 个文件
对账: 索引 7361 vs 落盘 7361（diff=0）
验收[ok]: 图片 1348/0失败 · 音频 4857/0失败 · 视频 0/0失败 · 511.4 分钟
另有 1156 个非媒体文件未验收（.lua/.hsl/.glsl/.tbl/.asb/.ipt/.iet/.otf 等）
```

这是 v0.2 之后第一次完整的真实交付：对账 0 差、三类媒体 0 失败。
1156 个非媒体是脚本/着色器/字体，不是媒体，按设计不计失败但必须报出。

### 26.2 两个 bug（同一个根因）

1. **产物落到了程序目录下的相对路径**（截图里 `Output\orchestrator\GalgameUnpacker\_extracted\…`）——
   说明 `out` 是相对路径。
2. **点「打开输出目录」没反应**：`_open_out` 里 `self._last_out.is_dir()` 对相对路径
   依赖当前工作目录，判 False 就静默 `return` —— 用户以为按钮坏了。

根因都是「路径没 resolve」。修：`_start` / `_autofill_out` 统一
`.expanduser().resolve()`；`_open_out` 目录不存在时明确弹窗，不再静默。

### 26.3 用户要求的新默认值

「解包目录自动变为 `<游戏目录>/output`」。已改 `gui.default_out_dir`，并删掉
`user_output_root` / `_output_root`（产物不再基于应用根或用户目录）。
planner 的 `<repo>/_extracted` 约定未动 —— 只影响 GUI 默认值，CLI 仍要求显式 `--out`。

三代默认值的教训：`Documents`（被拦）→ 用户目录（找不到）→ 游戏旁边（符合直觉）。
**默认值要选「用户会主动去看的地方」，不是「程序觉得安全的地方」。**

### 26.4 验证

- 新增/改测试：`test_default_out_dir_is_under_the_game`、
  `test_default_out_dir_shares_name_with_game_but_is_a_subdir`、
  `test_open_out_warns_when_directory_is_gone`
- 基线：**687 tests / 0 failures / 0 errors / 10 skipped**
