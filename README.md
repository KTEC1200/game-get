# Galgame Unpacker

个人自用/学习项目：**自动解包 galgame，产出视频、音频、图片三类资源**。
不做：打包回写、文本提取、翻译、对外分发。仅用于个人已购游戏的资源提取与学习。

当前版本 **v0.1.2**（Windows 10/11 x64，Python 3.14 + PyInstaller onedir + Inno Setup）。
v0.1.2 修重跑口径与交付记录：**raw 非空默认拒绝重跑**（要覆盖加 `--overwrite`）、
`manifest.verify.status` 单值结论、`source.archives` 全链路统一键名、GUI 默认输出改到「文档」。

## 安装

**只提供便携版**（2026-11-04 决定不做安装器：本机的火绒 + 深信服 EDR 会拦安装器的
敏感写入，而安装器只换来「卸载键 + 开始菜单快捷方式」，对私人工具没价值）。

- 解压 `packaging/Output/GalgameUnpacker-0.1.2-portable.zip` 到任意可写目录，
  双击 `orchestrator\orchestrator.exe`（不带参数即进 GUI）
- 或直接拷 `_spike_pkg/dist/orchestrator/` 整个目录（等价）
- 不写注册表、不需要管理员权限、卸载 = 删目录

杀软/SmartScreen 可能拦截未签名的新程序——说明与处置见 `antivirus-false-positives.md`。

## 使用

**GUI（推荐）**：`orchestrator.exe --gui` —— 拖（或浏览）一个游戏目录 → 开始解包 →
跑完弹交付摘要（交付数/对账/验收），manifest 报告在输出目录 `manifest.json`。
运行中可点「取消」（在当前阶段跑完的边界生效，已完成的产物保留）；运行中关窗会先确认。
**默认输出目录**：便携版 `%USERPROFILE%\Documents\GalgameUnpacker\_extracted\<游戏名>`，
源码运行 `<仓库>\_extracted\<游戏名>`。输出目录已有上一轮产物时会先问「清空重跑还是换目录」。

**CLI**：

```
orchestrator.exe <游戏目录> --out <输出目录> [--overwrite] [--allow-gui] [--reuse-raw DIR]
                  [--no-verify] [--verify-jobs N] [--strict] [--dry-run]
```

- 退出码：`0` 全链通过（对账 0 差、验收 0 失败）／`1` 阶段失败或对账有差／
  `2` 引擎判出但无链路／`3` 引擎没判出
- **失败也会写 `manifest.json`**（`ok: false` + `error` + 失败阶段明细）：不再出现「上一轮的绿灯被当成本轮结果」
- **`--overwrite`**：输出目录已有上一轮产物时清空 `raw/` 与 `png/` 再跑。
  不加这个开关时遇到残留会**直接失败**——新旧产物混在一起的计数照样自洽，但数字是假的
- `--reuse-raw DIR`：复用已有 raw 产物，只重跑后处理与验收
- `--verify-jobs N`：验收并发度（默认 8，`1` = 完全串行；也可用环境变量 `GALUNPACK_VERIFY_WORKERS`）
- `--strict`：额外要求「有索引地面真相」且「验收真的跑过」，否则判失败
- `--dry-run` 只做引擎判定 + 案例库命中报告，不动文件
- 产物：`raw/`（原始）+ `png/`（转码成品）+ `manifest.json`（raw/final/converted 三段计数
  + `verify.status` 单值结论：`ok`/`partial`/`failed`/`skipped`）
  + `_work/*.log`（各阶段日志，失败复盘看这里）

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
拦新程序的敏感写入——遇到「拒绝访问」类报错，把解压目录整套放行；
详见 `antivirus-false-positives.md`。

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
