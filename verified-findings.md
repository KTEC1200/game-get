# 实测记录：工具行为与环境（证据留档）

> 记录日期 2026-10-12。这里只放**实测得到的事实**与**踩过的坑**，推断一律标注。
> AGENTS.md 只保留结论摘要；证据细节在本文件。

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
