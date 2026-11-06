# Galgame Unpacker

个人自用/学习项目：**自动解包 galgame，产出视频、音频、图片三类资源**。
不做：打包回写、文本提取、翻译、对外分发。仅用于个人已购游戏的资源提取与学习。

当前版本 **v0.8.0**（Windows 10/11 x64，Python 3.14 + PyInstaller onedir，便携 zip）。
v0.8.0 **界面重做**：卡片式布局 + 天空蓝仅作点缀（主按钮 / 输入框聚焦环 / 勾选框 / 状态点
四处，占比 < 3%）、自绘圆角控件（按钮 / 输入框 / 勾选框）、日志区空状态提示、
状态灯随结果变色。功能与 CLI 一字未改。
v0.7.1 修实跑 9818 个文件暴露的四个问题：后处理重跑白转 2748 张图（改按 mtime 复用，
1229s → 1.4s）、阶段 `ok` 被 data 里的同名计数盖成数字、归档成功却显示 `[FAIL]`、
分类统计与验收统计差一个文件（`.soc`/`.sli` 这类明确非媒体不再按目录猜）。
v0.7.0 三件事：**启动环境守卫**（被系统降权运行时直接说明原因与去处）、
**产物按类型归档**（`类目清单.csv` + `分类/图片|音频|视频|其他` 硬链接视图，不占空间）、
加密 krkr 的 `--allow-gui` 链路修掉三处缺陷（窗口等待、模态弹窗、解包模式未开启）。
v0.6.0 加 **环境自检**（`--doctor` / GUI 按钮：完整性级别、UAC、安全类进程、六处写探针表），
输出目录不可写时**自动降级**到可写位置并继续跑。
v0.5.0 Unity 音频收集提速（批量 400 + 并行 + 内存门）。
v0.4.3 修案例库接线与失败记录两条 P1；v0.4.2 给 exe 补**文件身份**（公司/产品/描述/版本/图标）；
v0.4.1 修两类「输出目录建不出来」；v0.4.0 改默认输出为 `<游戏目录>\output`；
v0.3.1 修可写性探针误报；v0.3.0 加失败日志。

## 安装

**只提供便携版**（2026-11-04 决定不做安装器：本机的火绒会拦安装器对 %TEMP%／开始菜单
的敏感写入，而安装器只换来「卸载键 + 开始菜单快捷方式」，对私人工具没价值）。

- 解压 `packaging/Output/GalgameUnpacker-0.8.0-portable.zip` 到任意可写目录，
  双击 `orchestrator\orchestrator.exe`（不带参数即进 GUI）
- 或直接拷 `_spike_pkg/dist/orchestrator/` 整个目录（等价）
- 不写注册表、不需要管理员权限、卸载 = 删目录
- ⚠️ **别解压到带特殊权限/受管控的目录里**（例如仓库的 `packaging\Output\` 下）：
  实测那样运行会被系统降到 Low 完整性，桌面、文档、`<游戏目录>` 全部写不进去，
  只能缩在「程序目录\output」。**放到 `D:\GalgameUnpacker\` 这类普通目录即可**，
  程序启动时也会自己检测并提示。

杀软/SmartScreen 可能拦截未签名的新程序——说明与处置见 `antivirus-false-positives.md`。

## 界面

一屏三块，自上而下：**品牌栏 → 输入卡片 → 日志卡片**。

- **配色**：底色 `#F5F7FA`、卡片纯白、描边 `#E5EAF1`。天空蓝 `#0EA5E9` **只出现四处**——
  主按钮「开始解包」、输入框聚焦环、勾选框选中态、状态指示灯——合计不到窗口面积 3%。
  大面积铺蓝会让工具类软件显得「玩具感」，也会压掉日志本身的可读性。
- **层级靠字号与字色**（`#0F172A` / `#475569` / `#94A3B8`），不靠加粗和边框；
  分区靠 24/18/12 三档留白 + 1px 发丝线，不用凹陷状态栏、不用 3D 凸起按钮。
- **控件是自绘的**：按钮、输入框、勾选框都用 Canvas 画圆角（卡片 12px、按钮 9px、输入框 8px）。
  ttk 在 Windows 上只有系统主题的三维边框，做不出「1px 发丝线 + 圆角 + hover 变色」；
  自绘后按钮接口仍兼容 ttk（`configure(state=...)`），所以调用方一行没改。
- **状态灯**：就绪灰 / 运行中天空蓝 / 完成绿 / 失败红 / 受限或取消琥珀，颜色跟着状态文字走。
- 日志区内容不满一屏时自动收起滚动条；空状态给两行提示，而不是一片白。

## 使用

**GUI（推荐）**：`orchestrator.exe --gui` —— 拖（或浏览）一个游戏目录 → 开始解包 →
跑完弹交付摘要（交付数/对账/验收），manifest 报告在输出目录 `manifest.json`。
运行中可点「取消」（在当前阶段跑完的边界生效，已完成的产物保留）；运行中关窗会先确认。
**默认输出目录**：`<游戏目录>\output`（2026-11-04 起）。解完就在游戏旁边，
不用去 C 盘或程序目录翻；换盘换机器也跟着走。
输出目录已有上一轮产物时会先问「清空重跑还是换目录」。

- **「按类型整理」默认开**：跑完额外产出 `类目清单.csv` 与
  `分类/<图片|音频|视频|其他>/…`（同盘硬链接，不复制、不占空间；`raw/` 原样保留）。
- **「环境自检」按钮**：只读诊断，一次列出完整性级别、UAC 状态、在跑的安全类软件，
  以及对 程序目录/游戏目录/LOCALAPPDATA/TEMP/桌面/用户目录 六个位置的写探针结果
  （每条带完整错误码）。出问题时点一下、复制、发回来就能定位是哪一层在拦。
- **启动守卫**：若程序被系统降权运行（只能写自己目录），状态栏会直接说明并建议把程序
  整体换到普通目录，不用等报错才发现。
- **游戏目录名含 Windows 非法字符**（`|` `?` `*` 等，常见于从压缩包带来的目录）时，
  没法在里面建子目录（系统直接报「语法不正确」）。这时默认改成
  `<父目录>\<清洗过的名字>-output`。
- **默认位置写不进去**时，会依次自动试 程序目录 → LOCALAPPDATA → 临时目录，
  第一个能写的就直接开工（弹窗告诉你改到了哪，日志第一行也写）。**三个都不可写才报错**
  —— 那说明拦截发生在进程级，换目录没有意义，请点「环境自检」把报告发回。
  ⚠️ 别再指望「把目录加进火绒信任区」能解决这类问题：实测整盘加白仍然失败
  （见 `antivirus-false-positives.md` §8）。

**CLI**：

```
orchestrator.exe <游戏目录> --out <输出目录> [--overwrite] [--allow-gui] [--reuse-raw DIR]
                  [--no-verify] [--verify-jobs N] [--strict] [--organize] [--dry-run]
orchestrator.exe --doctor [游戏目录]      # 环境自检（只读，写探针不落残留）
orchestrator.exe --gui                    # 图形界面（不带参数也进这里）
```

- 退出码：`0` 全链通过（对账 0 差、验收 0 失败）／`1` 阶段失败或对账有差／
  `2` 引擎判出但无链路／`3` 引擎没判出
- **失败也会写 `manifest.json`**（`ok: false` + `error` + 失败阶段明细）：不再出现「上一轮的绿灯被当成本轮结果」
- **`--overwrite`**：输出目录已有上一轮产物时清空 `raw/` 与 `png/` 再跑。
  不加这个开关时遇到残留会**直接失败**——新旧产物混在一起的计数照样自洽，但数字是假的
- `--reuse-raw DIR`：复用已有 raw 产物，只重跑后处理与验收
- `--verify-jobs N`：验收并发度（默认 8，`1` = 完全串行；也可用环境变量 `GALUNPACK_VERIFY_WORKERS`）
- `--strict`：额外要求「有索引地面真相」且「验收真的跑过」，否则判失败
- `--organize`：跑完按媒体类型产出 `类目清单.csv` + `分类/` 硬链接视图
  （只加视图与清单，不搬 `raw/`、不影响对账；GUI 里默认开）
- `--doctor`：环境自检，打印完整性级别、UAC、安全类进程与六个位置的写探针表；退出码
  `0` = 所探位置全可写、`1` = 有不可写（给脚本用）
- `--dry-run` 只做引擎判定 + 案例库命中报告，不动文件；KiriKiri 样本会多做一次
  `garbro -l` 探针，提前告诉你「正式跑要不要人工」（几秒）
- 产物：`raw/`（原始）+ `png/`（转码成品）+ `manifest.json`（raw/final/converted 三段计数
  + `verify.status` 单值结论：`ok`/`partial`/`failed`/`skipped`）
  + `_work/*.log`（各阶段日志，失败复盘看这里）
  + `类目清单.csv` 与 `分类/`（`--organize` / GUI 勾选时；硬链接视图，不占额外空间）

## 工作流程（一条命令跑完八个阶段）

```
识别引擎 → 查案例库 → 磁盘预检 → 解包 → 后处理 → 验收 → 交付记录
```

| 阶段 | 做什么 | 完成判据 |
|---|---|---|
| `detect` | 扫目录，规则表打分（`rules/engines.json`，阈值 60） | 有引擎分数 ≥ 60 |
| `case-lookup` | 目录结构算签名，去 `cases/index.json` 找已验证解法 | 只读报告，不影响成败 |
| `preflight` | 按源体积估产物、查目标盘余量、查 `raw/` 是否已有残留 | 余量够，且残留已显式覆盖/复用 |
| `extract` | 按引擎分派，产物落 `raw/`，同时算「应该有多少」并逐包对账 | 落盘数 == 地面真相 |
| `postprocess` | `.tlg` / `.pna` 转 PNG，产物落 `png/` | 转换数与输入相等 |
| `verify` | 图片用 Pillow、音视频用 ffprobe（8 路并行） | 失败计数与零字节都在阈值内 |
| `organize` | 按扩展名（目录兜底）分成 图片/音频/视频/其他，写清单 + 硬链接视图 | 附加产物：不参与成败判定 |
| `manifest` | 写 `manifest.json`：三段计数 + 对账 + `verify.status` | **失败也写**，写明哪一步、为什么 |

**怎么判定引擎**（三层，从便宜到贵）：

1. **规则表打分** —— 扩展名、目录名、文件名、exe 名、封包魔数，每条信号有权重。
   例：`.rpa` 70 分 + `renpy/` 目录 20 分 → Ren'Py。
2. **案例库** —— 目录结构算签名，匹配「同一款/同一种打包方式之前是怎么解的」，
   连当时踩到的坑与参数一起带回来。
3. **人工兜底** —— 分数不到 60 或没有链路时，用 `--engine` 强制指定，或走人工方案。

> 软件不认识游戏名，只认文件特征。`--dry-run` 两秒内给出「判成什么引擎、
> 命中哪个案例、要不要人工」，不写一个文件。

## 半自动协作（解不动时会告诉你该做什么）

工具优先全自动。但有些障碍「自动绕」比「人工做」贵得多——典型是加密 KiriKiri：
UI 自动化约 40 分钟、依赖真实桌面/DPI/虚拟桌面，而人手把 xp3 拖进 KrkrExtract 只要 3 分钟。
所以**失败时不只报错**，会给一份可执行的人工方案：要什么工具、几步、产物放哪、做完跑哪条命令。

| 输出位置 | 形式 |
|---|---|
| CLI | 结束时打印「需要人工介入」区块，含编号步骤与可直接复制的命令 |
| GUI | 失败摘要带方案摘要 + 前 3 步（完整步骤看日志） |
| `manifest.json` | `manual` 块：`code` / `summary` / `why` / `needs` / `steps` / `target` / `then` / `alternatives`（机器可读） |
| `--dry-run` | KiriKiri 提前探 `garbro -l`，列不出就当场说明要人工，不让你白等 |

覆盖的失败场景：

| code | 场景 | 人工方案 |
|---|---|---|
| `kirikiri-encrypted` | xp3 列不出（加密或 Console 假阴性） | 手动用 KrkrExtract 拖 xp3 → 产物拷进 `raw/` → `--reuse-raw` 续跑 |
| `kirikiri-gui-failed` | `--allow-gui` 跑过但失败 | 同上（附「可能是安全软件拦了」的提示） |
| `unity-no-assets` | AssetStudio 枚举 0 个资产 | AssetStudio.GUI 手动导出到 `raw/Image_Texture2D` 等目录 |
| `engine-no-chain` | 引擎判出但没链路 | 用该引擎的专用工具解到 `raw/`，再 `--reuse-raw` |
| `detect-failed` | 判不出引擎 | 确认游戏根目录，或 `--engine` 强制指定 |

**不做半自动的**（没有「人工能帮上忙」的余量）：磁盘空间不足（换盘即可）、
输出目录已有产物（已有两个出口）、验收失败（产物已在，人工改不了）。
没有合适方案时**不硬凑** —— 编出来的指引比一个错误码更害人。

## 失败日志（`failures.log`）

每次失败都会往**软件根目录**的 `failures.log` 追加一条记录（便携版 = 解压目录，
源码 = 仓库根）。位置刻意不放在输出目录里——输出目录本身可能就是建不出来的那个
（实测：未签名 exe 写「文档」被终端防护拒，`_work/` 日志跟着一起写不进去）。

每条包含：时间、错误码、引擎、游戏目录、输出目录、失败阶段与原因、退出码、Python 版本：

```
[2026-11-04 22:41:58 +0800] extract-failed  engine=KiriKiri  rc=1
  game  : D:\HY\高慢妻陥落！！
  out   : D:\out\高慢妻
  stage : extract  GARbro 列不出目录（可能是加密 xp3）
  python: 3.14.6  win32
  ---
```

写不进去时（只读目录、权限不足）自动退到 `%LOCALAPPDATA%\GalgameUnpacker\failures.log`；
两处都不行就往 stderr 说一句然后放弃——**绝不因为记日志失败而中断解包**。
单个文件超过 2 MB 轮转成 `failures.log.1`（只留一份历史）。

机器可读的完整结果仍在输出目录的 `manifest.json`（`error` / `stages` / `manual`）；
`failures.log` 是给人和事后排查看的时间线，不替代 manifest。

## 运行环境

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10 1809+ / Windows 11，x64（触到的最老依赖是 .NET Framework 4.6） |
| 管理员权限 | **不需要**（便携版解压即用，不写注册表） |
| .NET Framework | **4.6+**（Win10 1809+ 自带）——GARbro / AssetStudio / 自带 C# 工具的 csc 现编需要；纯 Python 链路（Ren'Py / RPG Maker / Yu-Ris / ExHIBIT 等）没有它也能跑 |
| 内存 | 建议 ≥ 8 GiB（大封包解包按 mmap/分块处理，但产物落盘需要余量） |
| 磁盘 | 程序本体约 350 MiB（含随包工具，大头是 ffprobe 的共享 DLL 与 GARbro）；**解包产物另算，可能数 GiB**（RPA 是裸存储，体积≈原包），跑之前看目标盘余量 |
| 网络 | **不需要**（全部本地运行，无联网组件） |
| 显示器 | 加密 KiriKiri 的 GUI 自动化链路（`--allow-gui`）需要真实桌面 + 200% DPI 缩放已适配 |

**终端防护提示**：本程序与随包工具均未签名。火绒/企业 EDR 等按进程信誉拦截的软件可能
拦新程序的敏感写入——遇到「拒绝访问」类报错，**先跑 `--doctor`（或 GUI「环境自检」）**，
报告里的「完整性级别 / UAC / 写探针表」能直接看出是哪一层在拦。

⚠️ 实测结论（2026-11-06）：**「把目录加进火绒信任区」不一定有效** —— 整盘 D: 加白后仍然
全部不可写；真正的分水岭是「程序所在目录」（放在带特殊权限的目录里会被降权到 Low 完整性）
与「有没有开启 UAC 降权」。详见 `antivirus-false-positives.md` §8。

**如果换位置也不行**：**源码态**可用仓库根的 `start-gui.bat`，它调用系统 Python 直接跑
（不进 exe），等于借用 `python.exe` 已有的信任，可完全绕开这条限制。双击即开图形界面；
带参数则用控制台版运行（`start-gui.bat --gui-smoke` 自检）。
便携包**不含**这个脚本（包里只有 exe）。
原理与更多办法见 `antivirus-false-positives.md` §7–8。

## 支持的引擎（9 条链路）

| 引擎 | 判定特征 | 提取方式 |
|---|---|---|
| Ren'Py | `.rpa` | 自研 RPA 解包（索引对账） |
| KiriKiri | `.xp3` | GARbro 静态提取；**加密 xp3** 走 `--allow-gui` 动态注入（约 40 分钟） |
| RPG Maker MV/MZ | NW.js 壳 + `www/` | 自研解密（假头 16B + XOR） |
| Yu-Ris | `pac/*.ypf` | 自研 YPF 逆向（名字 XOR + 置换表 + zlib/YCG） |
| AdvHD | `AdvHD.exe` + `.arc` | GARbro + 自研 PNA 多帧 carve |
| ExHIBIT/Retouch | `.gyu`/`.grp` | 自研 C# 解码器（源码随包现编）+ TOC 切分 |
| CatSystem2 | KIF `.int` | 自研 Blowfish/MT 全链（含密钥爆破） |
| Unity | `<游戏>_Data` | AssetStudio JSON 枚举 + Convert 分批导出 |
| Artemis (iMel) | `iarsys*.dll` + `.pfs` | 自研 pf8 分卷解包（按索引 SHA1 取 key）+ 散装媒体归集 |

Tyrano/Electron 等其余引擎：判得出来但无链路（退出码 2，不假装成功）。

## 边界与局限（别把这些当成 bug）

1. **同名文件 ≠ 同一种加密**。都是 `data.xp3`，不同公司的加密方式可能完全不同。
   软件能判出「这是 KiriKiri」，判不出「这家用了哪种加密」——后者只能靠实测样本，
   再记进案例库。
2. **案例库是离散的，不是通用的**。目前 12 个 case，覆盖已经踩过的具体游戏；
   没踩过的新变体照样要从头逆向。
3. **决策树文档与代码不完全一致**。`galgame-unpack-decision-tree.md` 写的是人工流程
   「先用 GARbro 试一遍（万能入口）」，代码走的是「先判引擎再选工具」——
   因为全量跑 GARbro 慢，而且它对部分包会假阴性。想「先试 GARbro」目前得手工做。
4. **只做资源提取**。不做打包回写、文本提取、翻译；加密 KiriKiri 的纯 CLI 自动化
   也还做不到（见上面「半自动协作」）。

## 外部工具（已随包集成，无需自备）

解包所需的外部工具已打进 `bin/` 子目录（`NOTICE.txt` 列了每个工具的来源与许可证状态），
程序自动使用，**开箱即用**。工具按以下顺序解析（想换版本时只需走前两档覆盖）：

```
环境变量 TOOLBRIDGE_<KEY>  →  exe 旁 toolbridge.json 的 paths.<key>
  →  随包 bin/<KEY>/  →  内置候选路径  →  PATH
```

| key | 用途 | 随包位置 |
|---|---|---|
| `garbro` | KiriKiri/AdvHD 等静态提取 | `bin\garbro\GARbro.Console.exe` |
| `assetstudio` | Unity 导出 | `bin\assetstudio\AssetStudio.CLI.exe` |
| `tlg2png` | KiriKiri 图片转码 | `bin\tlg2png\tlg2png.exe` |
| `ffprobe` | 音视频验收 | `bin\ffprobe\ffprobe.exe`（连同 avcodec 等 DLL，共享构建） |
| `krkr` | 加密 KiriKiri 的 GUI 自动化（约 40 分钟/部，默认不用） | `bin\krkr\KrkrExtract.Lite.exe`（三件套同目录） |
| `krkrz` | KrkrExtract 报 Unknown chunk 时的手动兜底 | `bin\krkrz\KrkrzExtract.exe` |
| `csc` | 自带 C# 工具（gyu/hg3）现场编译 | Windows 系统组件，不随包（.NET Framework 自带） |

覆盖示例（`toolbridge.json` 放在 exe 旁）：

```json
{ "garbro": "C:\\tools\\GARbro.Console.exe", "ffprobe": "C:\\ffmpeg\\bin\\ffprobe.exe" }
```

> 许可证说明：本工具是**私人自用项目，不对外分发**，因此不处理许可证分发义务。
> `bin\NOTICE.txt` 仍记录各工具的上游与许可证状态（garbro/assetstudio 为 MIT，
> KrkrExtract/KrkrzExtract/ffprobe 为 GPL-3.0，tlg2png 上游无许可证）——
> 这份记录是事实备查，不构成分发许可；将来若要公开仓库或分发二进制，必须重新评估。

## 从源码构建

```
python build_exe.py --check   # 校验数据文件清单
python build_exe.py           # 冻结 + 出便携 zip（唯一交付形态）
python tests/run_all.py       # 全量测试（按 junit 结果退出，见下）
```

> 测试的退出码为什么不直接用 pytest：带「批量删除守卫」的环境里，pytest 退出清理
> 自己的临时目录会被守卫打断——测试全绿但 exit=1。`tests/run_all.py` 用 junitxml
> 判定真实结果，并打印 `tests/failures/errors/skipped` 一行汇总。
> 注意用**装了 pytest 的那个解释器**跑它（本机是 `C:\Python314\python.exe tests\run_all.py`），
> 脚本内部用 `sys.executable` 转发。

需要 Python 3.14 + PyInstaller + Inno Setup（外部工具见上表）。
依赖：见 `requirements.txt`（无重依赖：Pillow / pycryptodome / numpy / tkinterdnd2 可选）。

## 项目文档

- `AGENTS.md` —— 交接文档：状态、下一步、已踩过的坑（**新会话从这里读起**）
- `verified-findings.md` —— 实测证据库（每个引擎分支的格式逆向与工具行为）
- `galgame-unpack-decision-tree.md` —— 分派决策树（报错串 → 动作）
- `software-plan.md` —— 软件化路线与进度
- `galgame-ai-unpack-workflow-plan.md` —— 完整方案蓝图（打包/许可证/法律）
