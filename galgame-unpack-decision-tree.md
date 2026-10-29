# Galgame 自动解包：决策规则表（从你自己的教程中提取）

> 来源：`tutorials/krkr引擎游戏解包.md`、`tutorials/unity引擎游戏解包.md`、`tutorials/其他常见引擎游戏的解包.md`
> 这是**你的经验**的显性化，不是我查来的。工具链接已用 GitHub API 核实的状态标注在【】里。
> 目标：成为自动分派器的规格。**先追求覆盖你的高频路径，不追求穷尽。**

---

## 1. 主决策树

```
入口：任何单机游戏 → 先用 GARbro 试（万能入口，成本最低）
│
├─ 命中 目录特征 [游戏名]_Data/  ────────────────→ Unity 分支
│
├─ 命中 扩展名 .xp3 ────────────────────────────→ KiriKiri 分支
│
├─ 命中 扩展名 .asar ───────────────────────────→ Tyrano/Electron 分支
│
├─ 命中 扩展名 .rpa ────────────────────────────→ Ren'Py 分支
│
├─ 命中 www/ 目录（内有 js/rpg_core.js 或 rmmz_core.js）→ RPG Maker MV/MZ 分支
│
├─ 命中 AdvHD.exe（封包 .arc）─────────────────→ AdvHD 分支
│
├─ 命中 pac/*.ypf + yscfg.dat ─────────────────→ Yu-Ris 分支
│
├─ 命中 ExHIBIT.JP / .gyu / .grp ──────────────→ ExHIBIT 分支
│
├─ 命中 KIF 封包（.int + __key__）────────────→ CatSystem2 分支
│
└─ 都不命中 → 按文件类型试 + 社区检索（见 §4）
```

**为什么 GARbro 是入口**：教程原文「一般的单机游戏都可以先用 GARbro 试试」。它覆盖广、成本低，是**唯一一个值得无条件先跑**的工具。

---

## 2. 分支细则

### 2.1 Unity 分支

**触发特征**：存在 `[游戏名称]_Data/` 文件夹。

| 步骤 | 动作 |
|---|---|
| 1 | 定位 `[游戏名称]_Data/StreamingAssets/aa/` → `.bundle` 文件在此 |
| 2 | AssetStudio：`File / Load folder` 导入 `[游戏名称]_Data`，可勾选 Enable Advanced Search |
| 3 | 按 Type 筛选（AudioClip / Texture2D / VideoClip / Sprite…），Export 选 All / Selected / Filtered |

**子分支（由报错驱动）**：

| 观测到的报错 | 判断 | 动作 |
|---|---|---|
| Shader 无法解析 / `EndOfStreamException` | **Unity 6000 改了 Shader 序列化格式**（移除旧字段） | 改用 **AssetStudioNext** |
| AssetStudio 无法正常解析文件 | 资源可能加密 | 走 IL2CPP 路线或换 AssetRipper |
| 有 `il2cpp_data/` 文件夹 | IL2CPP 打包 | `Il2CppDumper.exe "GameAssembly.dll" "global-metadata.dat" "输出目录"` |
| `ERROR: Metadata file supplied is not valid metadata file.` | **global-metadata.dat 被加密或混淆** | 到此需人工 |

**产出物**：`skeleton.atlas`（纹理图集）、`skeleton*.png`（贴图）、`skeleton.skel.bytes`（骨骼）
**备选**：AssetRipper（教程原文「AssetStudio 功能更强的代替品」）

---

### 2.2 KiriKiri 分支（你的主力分支）

**触发特征**：`.xp3` 文件。常见文件名与内容对应关系：

| 文件名 | 内容 |
|---|---|
| `data.xp3` | 游戏主数据 |
| `event.xp3` / `evimage.xp3` | 事件 CG |
| `fgimage.xp3` | 人物立绘 |
| `bgimage.xp3` | 背景图片 |
| `scenario.xp3` | 游戏脚本 |
| `voice.xp3` / `sound.xp3` | 语音 / 音效 |
| `bgm.xp3` | 背景音乐 |
| `system.xp3` | 系统界面 |
| `patch.xp3` | 游戏补丁 |
| `adult.xp3` | R18 内容 |

> ⭐ **这张表本身就是一条规则**：即使解包失败，也能从文件名反推该包该有什么，用来**校验产物是否完整**（见 §5 验收）。

**流程**：

```
① GARbro 静态提取（找体积较大的 .xp3，右键 Extract）
   │
   └─ 成功 → 完成
   │
   └─ 失败 → 判定「已加密」（见下方判据）→ ② 动态提取
        │
        ② 游戏能否正常运行？
            ├─ 否（只能用模拟器启动）→ 放弃动态，回 GARbro
            └─ 是 → ③ 是 Steam 版吗？
                 ├─ 是 → Steam 会阻止注入 → 先用 Steamless 脱壳
                 └─ 否 → 直接
                      │
                      ④ KrkrExtract 动态提取
                      （文件放游戏根目录，把主程序拖到 KrkrExtract.exe 启动，
                        再把 .xp3 拖进控制台；利用游戏自身的解密机制解开）
                      │
                      └─ 红字警告 `Unknown chunk in root chunk : 34767848, at address : 00000000`
                         → 封包头被修改 → ⑤ 改用 KrkrzExtract（用法相同）
```

> ⭐ **④ 已全自动，不要手工拖拽**：`python krkr_auto_extract.py <游戏目录> [--out DIR] [--keep-stage]`
> （2026-10-28 两个样本实测 2838/2838、5724/5724 零失败）。手工拖拽仅在排障时用。
> 工具做四件事：ASCII stage 硬链接 → `KrkrExtract.Lite.exe` CLI 注入 → **Explorer 真拖拽**逐包提取 → 完成判定后移产物。

**⭐ 加密 xp3 动态提取的两条硬结论（2026-10-28，踩过代价，务必先读）**：

1. **游戏路径必须纯 ASCII**。CJK 路径下注入后游戏进程活着但**两个窗口都不弹**，只弹 `#32770` 错误框
   「ANSI 文字列を UNICODE 文字列に変換できません」（GBK 代码页 + krkr2 的 ANSI→Wide 转换被 Core 钩子放大）。
   → 解法：建 ASCII stage 目录，`os.link` 硬链接 xp3（同卷零拷贝），并复制 `plugin/*.tpm`、`*.cf`。
   工具已内置。**看到「游戏没启动」先怀疑路径编码，别怀疑工具。**
2. **跨进程 WM_DROPFILES / OLE 拖拽全部不可行**。受控实验里接收方 wndproc 确实收到了消息，
   但 `DragQueryFileW` 返回 0（`GMEM_SHARE` 在现代 Windows 是 no-op，句柄进程私有）。
   → **唯一通路是 Explorer 发起的真拖拽**：`explorer /select` 打开父目录并选中文件 → UIA 取 item 矩形 →
   `SendInput` 拖动。工具已内置（配套 `_uia_item_rect.ps1`）。
   （本机 DPI 200%，坐标必须 `SetProcessDPIAware()` 且全程物理坐标。）

**⭐ 「工具静默 0 产出」先查 TOC 混淆，别急着判定格式不支持**：`movie.xp3` 曾被两个工具都吐 0 文件，
真相是 **Lock 混淆了 TOC 的 segm (offset,size) 字段**——两个字段被写成相同大数（`offset==size` 是强特征），
**数据本身完全没加密**。破解 = 用数据魔数自定位：MPEG-PS 包链 `00 00 01 BA` + 2048B 扇区扫出 `logo.mpg`，
其后紧跟 PS 结束码 `00 00 01 B9` + 明文 ASF 头 `30 26 B2 75…` 扫出 `pv_movie.wmv`（见 verified-findings §17.7）。

**⭐ 加密判据（三条任一命中即可判定）**：
1. GARbro 提示「无法识别的格式」
2. GARbro 提示「密码错误」
3. **提取出的音频无法播放** ← 这条最不容易想到，但很可靠

**较新 xp3 的备选**：KrkrDump、krkrzCxdec（`YeLikesss/KrkrExtractForCxdecV2`）

---

### 2.3 RPG Maker MV/MZ 分支（2026-10-26 `常識改変学園` 实测打通）

**触发特征**：根目录一堆 NW.js 运行时文件（`nw.dll`/`node.dll`/`icudtl.dat`/`locales/*.pak`/`package.json`）+ **`www/`** 目录；
`www/js/rpg_core.js` = MV，`www/js/rmmz_core.js` = MZ。常见变体：直接 `www/` 平铺（无壳）、`.rpgsave` 存档。

| 步骤 | 动作 |
|---|---|
| 1 | 读 `www/data/System.json`：`hasEncryptedImages`/`hasEncryptedAudio`=false → **媒体本来就是明文**（img/audio/movies 目录直接用，无需解包） |
| 2 | =true → 解密：**加密 = 假头 16B + 原[0:16] XOR key + 原[16:] 明文**；key 就是同文件里的 `"encryptionKey"`（32 hex） |
| 3 | 后缀还原：`.rpgmvp→png`、`.rpgmvo→ogg`、`.rpgmvm→m4a`（MZ 还有 `.png_/.ogg_` 风格） |
| 4 | 工具：**`_rpgmv_decrypt.py`**（自建，见 verified-findings §12.1；无需下载 RPGMakerDecrypter） |
| 5 | 视频：MV 原生支持 `www/movies/*.webm|.mp4`（明文，无加密后缀）；目录没有就是没有 |

> ⭐ **加密的地面真相在游戏自己的 `www/js/rpg_core.js` 里**（`Decrypter.decryptArrayBuffer`）——
> 别信网上流传的「MV 加密很复杂」，它只 XOR 了假头之后的前 16 字节。
> ⭐ 汉化组常在每个目录塞「免责声明请在使用前阅读我/」目录（txt+jpg），**按目录名前缀整体跳过**，否则污染图片对账。

### 2.4 AdvHD 分支（2026-10-26 `ラブラブお痴験バイト性活` 实测打通）

**触发特征**：根目录 `AdvHD.exe`（+ `AdvHDLang.dll`）。封包 `.arc` 若干 + 视频直接以 `.dat` 散放（OP.dat / ED_*.dat）。

| 步骤 | 动作 |
|---|---|
| 1 | **GARbro 直接支持 .arc**：`GARbro.Console.exe <arc>` 列表 / `-x` 提取（音频出 ogg、图片自动转 PNG） |
| 2 | `.dat` 是 ASF/WMV（头 GUID `30 26 b2 75 …`）→ **复制改 `.wmv` 后缀**即可，无需工具 |
| 3 | `.pna`（PNAP 多帧容器，GARbro 不认）→ `_pna_carve.py` 按 PNG 签名→IEND carve 逐帧 |
| 4 | `.mos` 魔数就是 PNG，按 PNG 验收即可 |

> ⚠️ `.arc` 的 GARbro **列表输出没有表头，每行一条**（xp3 有表头）——计数对账别套 `len(lines)-1`。
> ⚠️ 编排对账以「包头 u32 条目数」为地面真相（第 0-3 字节），逐包比对落盘数。

### 2.5 Yu-Ris 分支（2026-10-26 `あまねぇ` 实测打通，YPF 格式已完整逆向）

**触发特征**：`pac/*.ypf`（魔数 `YPF\0`）+ `yscfg.dat` + 存档 `.sd`（魔数 `YSSD`）+ `エンジン設定.exe`。
**GARbro 不支持 YPF**（其 YaneSDK 目录只有 ArcDAT/ArcHibiki，报 unknown format 属正常，不是假阴性）。

| 步骤 | 动作 |
|---|---|
| 1 | 工具：**`_ypf_extract.py`**（自研，格式逆向自 arc_unpacker `ypf_archive_decoder.cc`，含 YCG→PNG） |
| 2 | 备选：arc_unpacker（`vn-tools/arc_unpacker` 0.11 bin，识别为 `yuris/ypf`）——⚠️ **`--out` 必须写 `--out=DIR`**，空格形式会把 DIR 当成又一个输入文件（实测把 cwd 整个递归扫了一遍）；且对大包（3484 条）疑似卡死 30 分钟无产出 |
| 3 | 格式（版本 0x1EE 实测）：头 32B = `YPF\0`+version+count+table_size（**table_size 从文件头起算，含主头 32B**）；条目 = 4B+名长(^0xFF 查 4 张置换表之一)+名+type+zlib标志+orig+comp+offset+8B |
| 4 | 文件名 = **XOR 单字节 key**（本作 0xFF；key 靠 `name[-4]^'.'` 命中已知扩展名猜测）；数据可选 zlib；本作 cg/sound 包**未压缩**，本体就是明文 PNG / OGG |
| 5 | YCG 图片（`YCG\0`+w+h+depth32+method1+两段 zlib = BGRA 原始像素）本作未用到，但提取器已支持 |

> ⭐ 教训：**「源码即规格书」**——archive 本体分析卡壳时，直接读现成解码器的源码（api.github.com 拉
> `ypf_archive_decoder.cc`）比纯手撸 hexdump 快一个数量级；读完再自研实现，还能绕开工具自身的坑。

### 2.6 ExHIBIT / Retouch 分支（2026-10-26 `夕凪荘` 实测，图片/语音/视频全通，BGM 加密未解）

**触发特征**：`ExHIBIT.JP` + `RESIDENT.JP`（文本配置）、`res/` 下 `.gyu`（魔数 `GYU\x1a`）/`.grp`/`.rld`、
`*.TTE` 字体。MOONSTONE 系品牌多用此引擎。

| 步骤 | 动作 |
|---|---|
| 1 | 图片 `.gyu` → **`_gyu_tool.exe`**（自研 C#；Key 在头里，三种压缩模式；详见 verified-findings §15.1） |
| 2 | 音频 `.grp` → **`_grp_extract.py`**（TOC = 同目录 `AiFS` 魔数的 resNNNN-1.grp） |
| 3 | 视频 `.wmv`/`op.wmv` 明文直接收 |
| 4 | ⚠️ `res/s/m/*.ogg`（BGM）**头两页加密**——现成工具无解，破解路线见 verified-findings §15.3 |
| 5 | `.rld`(脚本)/`.dlt`(差分) 非目标；E-mote 类合成（.dlt）保留人工 |

> ⭐ 「源码即规格书」再次生效：GARbro-Mod 源码树里有 `ExHibit/ImageGYU.cs` + `ArcGRP.cs`
> （api.github.com 可拉），本机 GARbro 版本旧不认 ≠ 格式无支持——**先查上游源码树再判「无工具」**。

### 2.7 CatSystem2 分支（2026-10-27 `甜蜜女友2+` 实测，加密全链打通）

**触发特征**：`.int` 封包（魔数 `KIF\0`，头部带 `__key__.dat`）+ `cs2.exe`；常伴 `.hg3` 图片与 `key.dat`。

| 步骤 | 动作 |
|---|---|
| 1 | 工具：**`_cs2_int_extract.py`**（自研全链；索引+数据 Blowfish-ECB 小端打包，密钥 = MT(头 0x4C 种子).rand() 4 字节） |
| 2 | 文件名 = MT(main_key+i) 的 52 字母表轮换；**main_key 缺口用 k0 反推 + 约束爆破**（§16.2 方法论） |
| 3 | 图片 HG-3 家族 → **`_hg3_tool.exe`**（按魔数扫描——引擎会混淆扩展名；分节链从 0x14 起、LSB 位流） |
| 4 | 音频解密后即 OggS；视频 = MPEG-PS（魔数 `00 00 01 ba`）复制为 .mpg |

> ⚠️ GARbro 小端 Blowfish ≡ 标准大端解密 + **输入与输出都要 4 字节半块反转**（只反输出 = 静默错数据）。
> ⚠️ 本机 GARbro Console 无 ExHibit/CatSystem 新版支持 ≠ 上游源码没有——**先查 GARbro-Mod 源码树再下结论**。

### 2.8 其他引擎（按容器格式分派）

| 特征 | 引擎 | 工具 | 备选 |
|---|---|---|---|
| `.asar` | Tyrano / Electron | **AsarKit**（安装无依赖） | WinASAR |
| `.rpa` | Ren'Py | **RPA-Explorer**（还能改/建 rpa、预览编译后的 rpy） | rpaextract（较新） |

---

## 3. 报错字符串 → 动作 映射表（**本表价值最高**）

> 这些字符串是你教程里记录的**真实观测**。自动分派器的核心逻辑就是这张表。
> **注意：其中大部分根本不需要 LLM，字符串匹配即可。**

| 工具 | 观测字符串 | 含义 | 下一步动作 |
|---|---|---|---|
| GARbro | 无法识别的格式 | 封包加密或格式不支持 | → 动态提取 / 换工具 |
| GARbro | 密码错误 | **加密** | → 动态提取 |
| GARbro | （导出音频无法播放） | **加密** | → 动态提取 |
| KrkrExtract | `Unknown chunk in root chunk : 34767848, at address : 00000000` | 封包头被修改 | → **KrkrzExtract** |
| AssetStudio | `EndOfStreamException` | Unity 6000 Shader 序列化变更 | → **AssetStudioNext** |
| AssetStudio.CLI | `Nothing exported.`（**退出码却是 0**） | ⚠️ `--types` 用**逗号**分隔被静默忽略；或输出目录里文件已存在 | 检查类型参数写法；**永远不要用退出码判成功，要数产物** |
| AssetStudio.CLI | 进程崩溃、退出码 `-1073740940`（`0xC0000374`） | **堆损坏**：一次性全导体积太大（≈870 MB 触发） | → **按类型分批独立导出**（见 `unity_unpack.ps1`） |
| AssetStudio | 日志里每个资产都打印 `Exporting X`，但磁盘上几乎没有产物，**且无任何报错** | Unity 音频是 **FSB5(FMOD)** 容器（`m_Source: resources.resource`）时 CLI 的静默失败 | → 用 `_as_audio_collect2.py` **多轮正则分组累积**，最后 `^(A\|B\|C)$` 精确锚定清尾巴 |
| FFmpeg | `Not yet implemented in FFmpeg, patches welcome`（对 FSB5） | FFmpeg 认识 FSB 容器但不支持其编码 | → 不要指望 FFmpeg 解 FSB；走 AssetStudio 分组累积 |
| RPA | `_pickle.UnpicklingError: invalid load key, 'x'`（`'x'` 即 `0x78`） | **索引是 zlib 压缩的**，你把 zlib 流直接喂给了 pickle | → 定位索引偏移后先 `zlib.decompress` 再 `pickle.loads`（见 `rpa_tool.py`） |
| RPA | 表头第 32 字节不是空格（如 `.`），`split(b" ")` 切不开 | Ren'Py 把表头分隔空格**换成别的字符**（换成什么由游戏决定） | → 用正则 `^RPA-3\.0 ([0-9a-f]{16}) ([0-9a-f]{8})` 抓「偏移+key」，**别 split 空格** |
| RPA | 索引偏移「看起来大得离谱」、疑似需要解混淆 | 常见误判：**字符串形状可疑 ≠ 值可疑** | → 先用**文件大小**验证：偏移 < 文件大小、且距文件尾合理（≈索引体积）即说明值没错，别去解混淆 |
| Il2CppDumper | `ERROR: Metadata file supplied is not valid metadata file.` | metadata 被加密/混淆 | → 人工（当前无解） |
| FFmpeg | `Invalid argument` | `mylist.txt` 中日文/中文文件名编码问题 | → 将 mylist.txt 另存为 **UTF-8** |
| arc_unpacker | `--out DIR`（空格形式）后多出一个「unknown input file: error opening .../DIR」，且开始递归扫描 cwd | **0.11 的 `--out` 不吃空格形式，DIR 被当成输入路径** | → 一律写 `--out=DIR`（等号形式） |

> 第 4 行那个 `34767848` 是**决定性证据**——它把一个"玄学问题"变成了可编程的 if 判断。这类具体错误串越多，自动化覆盖率越高。

---

## 4. 未知情况的降级路径（「杀手锏」）

教程原文的兜底策略，**恰好是 AI 最该介入的地方**：

1. **若游戏发售日期在 2010 年以后**，检索游戏信息：
   - 维基百科（zh）
   - 2dfan（`galge.fun`）
   - 萌娘百科
   - 目标：拿到 **发售日期 / 日文名 / 罗马音 / 厂商**
2. **查「乜都讲 D」博客**（`blog.ztjal.info`）——用**日文名**搜
   - 该博客的格式是：`/[发售时间][公司] 名称` 换行 `工具1：插件，工具2`
   - 例：`[210730][はむはむソフト] Lowな妹にサキュバスが…` → `crass：RealLive`
   - 例：`[210730][ういんどみるOasis] 悠久のカンパネラ` → `7z，IrsysPack_CipherKey`
   - 例：`[210730][BISHOP] しりこん☆まじっく` → `asmodean：exbsa`
3. **⭐「上一作」策略**：如果是新出的游戏，**查该厂商的上一个游戏**，重复解包流程找出工具，再用到新游戏上。
   → 这本质是 **厂商 → 工具 的历史映射**，完全可以用你的案例库数据化。
4. 最后：等他人分享，或去贴吧碰运气。

---

## 5. 后处理（解包 ≠ 拿到可用文件）

**这是你目标里最容易被低估的一环**：解包成功不代表产出物能直接播放/查看。

| 产出格式 | 来源 | 转换工具 | 备注 |
|---|---|---|---|
| `.tlg` | KiriKiri CG | **tlg2png** | `for %i in ("D:\game\cg\*.tlg") do tlg2png "%i" "D:\cgout\%~ni.png"` |
| `.pimg` / `.psb` | KiriKiri 立绘（E-mote） | **FreeMote** `PsbDecompile.exe` → 再 **krkrFgiEditor** 合成 | `for /r "D:\Game\cg" %f in (*.pimg *.psb) do PsbDecompile.exe "%f"`，每个变成含 `.png`+`.json` 的文件夹 |
| 散碎 `.ogg` | 语音 | **FFmpeg** concat | 见下 |
| `.atlas` / `.png` / `.skel.bytes` | Unity | 通常可直接用 | |

**立绘合成（krkrFgiEditor）**：创建图层组 → 每个组加对应图层 → 设置合成规则。
例：身体组(图1,2) + 表情组(图3,4) → 自动生成 `1+3`、`1+4`、`2+3`、`2+4` 全部组合。
→ ⚠️ **这一步是"组合爆炸"的语义操作，很难纯规则化，也不适合 AI 猜**，建议保留人工。

> **仅在游戏真有 E-mote / `.pimg` / `.psb` 时才需要上面两步。**
> 实测 `兼职人妻` 全包**无 `.pimg/.psb/.mtn/.emo`**，`fgimage/` 是 261 张**已合成好的整张 PNG**（`fg_友美_黒下着_微笑み.png`）
> → **FreeMote + krkrFgiEditor 整条分支不需要**。先查扩展名再决定要不要找这两个工具。
> 同作的语音同理：`sound/` 是 1563 个平铺 `.ogg` 但名字是**语义名**（`挿入.ogg`、`喘ぎ.ogg`）而非序号，
> **没有「按序号 concat」的自然合并方式**；真要按场景合并必须解析 `scenario/*.ks`，靠文件名规则做不到。

**语音合并（FFmpeg）**：
```cmd
(for %i in (*.ogg) do @echo file '%i') > mylist.txt
ffmpeg -f concat -safe 0 -i mylist.txt -vn -c:a libvorbis -q:a 8 output.ogg
```
> mp3 版：`-c:a libmp3lame -q:a 2 output.mp3`
> ⚠️ 报 `Invalid argument` → 检查 mylist.txt 里日文/中文文件名是否正常显示 → 另存为 **UTF-8** 重试。

---

## 6. 验收判据（给自动化的"成功"定义）

结合你的目标（视频/音频/图片），**「解包没报错」不算成功**：

1. **产物非空**：文件数 > 0，无 0 字节文件
2. **产物可开**：图片能被看图器/Pillow 打开；音频能解出时长；视频能被播放器识别
3. **⭐ 产物与包名相符**：用 §2.2 的文件名对照表反查——
   解了 `bgimage.xp3` 就应该只有背景图；混进了语音就说明解错了包
4. **数量合理性**：CG 数、立绘数不应为 1 或 0（常见静默失败）

---

## 7. 工具清单与核实状态

| 工具 | 链接 | 核实状态 |
|---|---|---|
| **GARbro-Mod** ⭐你的主力 | github.com/nanami5270/GARbro-Mod | **MIT**，145★，**`pushed_at` 2026-10-12（当天仍在更新）**，`fork of morkt/GARbro`。**比上游 morkt/GARbro（master 停在 2023-10）活跃得多** |
| KrkrExtract | github.com/xmoezzz/KrkrExtract | 已归档；README 称 GPLv3 但仓库无 LICENSE（**冲突**） |
| KrkrzExtract | github.com/xmoezzz/KrkrzExtract | GPL-3.0，`pushed_at` 2026-08-25，未归档 |
| krkrzCxdec | github.com/YeLikesss/KrkrExtractForCxdecV2 | **[未核实]** |
| KrkrDump | github.com/crskycode/KrkrDump | **[未核实]** |
| Steamless | github.com/atom0s/Steamless | **[未核实]** |
| AssetStudio | github.com/Perfare/AssetStudio | MIT，**已归档 2023-01-21** |
| AssetStudioNext | github.com/Razviar/assetstudio | **[未核实]** |
| AssetRipper | github.com/AssetRipper/AssetRipper | GPL-3.0，活跃 |
| Il2CppDumper | github.com/Perfare/Il2CppDumper | **[未核实]** |
| **tlg2png** | github.com/vn-tools/tlg2png | C++，57★，**已归档**（`pushed_at` 2016-01-07），**无许可证** |
| FreeMote | github.com/UlyssesWu/FreeMote | **CC BY-NC-SA 4.0（禁商用）**，活跃 |
| **krkrFgiEditor** | github.com/CjangCjengh/krkrFgiEditor | C#，65★，未归档但 `pushed_at` 2022-09-14（停滞），**无许可证** |
| **RPA-Explorer** | github.com/UniverseDevel/RPA-Explorer | **GPL-3.0**，107★，`pushed_at` 2025-05-10 |
| rpaextract | github.com/Kaskadee/rpaextract | **[未核实]** |
| WinASAR | github.com/flydoos/WinASAR | **[未核实]** |
| AsarKit | 52pojie 论坛贴（非 GitHub） | **[未核实]**，非公开源码分发 |
| FFmpeg | ffmpeg.org | 广泛使用，未在本次核实 |

> **许可证提示**：个人自用不分发 → 上述限制（GPL / CC BY-NC-SA / 无许可证）**均不触发**。
> ⚠️ 一旦你**分发**这个软件（哪怕免费、哪怕只放 GitHub），限制立即生效，届时需重新评估。
