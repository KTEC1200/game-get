# Galgame Unpacker

个人自用/学习项目：**自动解包 galgame，产出视频、音频、图片三类资源**。
不做：打包回写、文本提取、翻译、对外分发。仅用于个人已购游戏的资源提取与学习。

当前版本 **v0.1.0**（Windows 10/11 x64，Python 3.14 + PyInstaller onedir + Inno Setup）。

## 安装

- 安装版：`packaging/Output/GalgameUnpacker-0.1.0-setup.exe`（**免管理员**，装到
  `%LocalAppData%\Programs\GalgameUnpacker`，卸载即净）
- 便携版：把冻结目录整个拷走即可（`_spike_pkg/dist/orchestrator/`）

杀软/SmartScreen 可能拦截未签名的新程序——说明与处置见 `antivirus-false-positives.md`。

## 使用

**GUI（推荐）**：`orchestrator.exe --gui` —— 拖（或浏览）一个游戏目录 → 开始解包 →
跑完弹交付摘要（交付数/对账/验收），manifest 报告在输出目录 `manifest.json`。

**CLI**：

```
orchestrator.exe <游戏目录> --out <输出目录> [--allow-gui] [--reuse-raw DIR] [--no-verify] [--dry-run]
```

- 退出码：`0` 全链通过（对账 0 差、验收 0 失败）／`1` 阶段失败或对账有差／
  `2` 引擎判出但无链路／`3` 引擎没判出
- `--dry-run` 只做引擎判定 + 案例库命中报告，不动文件
- 产物：`raw/`（原始）+ `png/`（转码成品）+ `manifest.json`（raw/final/converted 三段计数）
  + `_work/*.log`（各阶段日志，失败复盘看这里）

## 运行环境

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10 1809+ / Windows 11，x64（触到的最老依赖是 .NET Framework 4.6） |
| 管理员权限 | **不需要**（安装版装到 `%LocalAppData%\Programs`，便携版解压即用） |
| .NET Framework | **4.6+**（Win10 1809+ 自带）——GARbro / AssetStudio / 自带 C# 工具的 csc 现编需要；纯 Python 链路（Ren'Py / RPG Maker / Yu-Ris / ExHIBIT 等）没有它也能跑 |
| 内存 | 建议 ≥ 8 GiB（大封包解包按 mmap/分块处理，但产物落盘需要余量） |
| 磁盘 | 程序本体约 350 MiB（含随包工具，大头是 ffprobe 的共享 DLL 与 GARbro）；**解包产物另算，可能数 GiB**（RPA 是裸存储，体积≈原包），跑之前看目标盘余量 |
| 网络 | **不需要**（全部本地运行，无联网组件） |
| 显示器 | 加密 KiriKiri 的 GUI 自动化链路（`--allow-gui`）需要真实桌面 + 200% DPI 缩放已适配 |

**终端防护提示**：本程序与随包工具均未签名。火绒/企业 EDR 等按进程信誉拦截的软件可能
拦安装器的敏感写入——遇到「拒绝访问」类报错改用便携版，或在防护软件里放行；
详见 `antivirus-false-positives.md`。

## 支持的引擎（8 条链路）

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

> 许可证说明：工具以独立进程调用、本体不修改（聚合而非衍生）；`bin\NOTICE.txt`
> 记录了各工具的许可证状态——**对外分发前**必须补齐许可证全文并履行 GPL 组件的
> 源码义务（蓝图 §5.2）。

## 从源码构建

```
python build_exe.py --check      # 校验数据文件清单
python build_exe.py --installer  # 冻结 + Inno Setup 单文件安装包
python -m pytest tests -q        # 全量测试
```

需要 Python 3.14 + PyInstaller + Inno Setup（外部工具见上表）。
依赖：见 `requirements.txt`（无重依赖：Pillow / pycryptodome / numpy / tkinterdnd2 可选）。

## 项目文档

- `AGENTS.md` —— 交接文档：状态、下一步、已踩过的坑（**新会话从这里读起**）
- `verified-findings.md` —— 实测证据库（每个引擎分支的格式逆向与工具行为）
- `galgame-unpack-decision-tree.md` —— 分派决策树（报错串 → 动作）
- `software-plan.md` —— 软件化路线与进度
- `galgame-ai-unpack-workflow-plan.md` —— 完整方案蓝图（打包/许可证/法律）
