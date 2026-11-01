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

## 外部工具（不随包分发，需自备）

解包器按 `环境变量 TOOLBRIDGE_<KEY>` → `orchestrator.exe` 旁的 `toolbridge.json` →
内置候选路径 → PATH 的顺序找工具。全部缺席时：能静态判引擎，但提取会失败并如实报出。

| key | 用途 | 默认候选 |
|---|---|---|
| `garbro` | KiriKiri/AdvHD 等静态提取 | `D:\K\galgame\GARbro\GARbro.Console.exe` |
| `assetstudio` | Unity 导出 | `D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe` |
| `tlg2png` | KiriKiri 图片转码 | `D:\K\galgame\tlg2png\tlg2png.exe` |
| `ffprobe` | 音视频验收 | `D:\ffmpeg\bin\ffprobe.exe` |

`toolbridge.json` 示例（放在 exe 旁即可）：

```json
{ "garbro": "C:\\tools\\GARbro.Console.exe", "ffprobe": "C:\\ffmpeg\\bin\\ffprobe.exe" }
```

GARbro/AssetStudio 需要 .NET Framework 4.6+（Win10 1809+ 一般自带；安装器会提示）。
加密 KiriKiri 的 GUI 自动化另需 KrkrExtract 三件套（`TOOLBRIDGE_KRKRLITE` 指向
`KrkrExtract.Lite.exe` 所在目录）。

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
