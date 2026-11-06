# Galgame Unpacker

个人自用/学习项目：**自动解包 galgame，产出图片、音频、视频三类资源**。
不做打包回写、文本提取、翻译、对外分发。仅用于个人已购游戏的资源提取与学习。

当前版本 **v0.8.2**（Windows 10/11 x64，Python 3.14 + PyInstaller onedir，便携 zip）。
近期三条主线：v0.8 界面重做 + 跟随系统缩放；v0.7 产物按类型归档 / 环境自检；v0.6 输出目录自动降级。

## 安装

**只提供便携版**（不做安装器：只换来「卸载键 + 快捷方式」，却会撞安全软件对写入的拦截）。

- 解压 `GalgameUnpacker-0.8.2-portable.zip` 到任意**普通目录**，双击
  `orchestrator\orchestrator.exe`（不带参数即进 GUI）
- 不写注册表、不需要管理员权限、卸载 = 删目录

⚠️ **别解压到带特殊权限／受管控的目录**（例如仓库、某些同步盘）：实测那样运行会被系统
降到 Low 完整性，桌面、文档、游戏目录全部写不进去。放 `D:\GalgameUnpacker` 这类目录即可；
放错了程序会在状态栏提示，`--doctor` 也能给出逐层证据。

## 使用

**GUI（推荐）**：拖（或浏览）游戏目录 → 开始解包 → 跑完弹交付摘要。
默认输出 `<游戏目录>\output`；已有上一轮产物时会先问「清空重跑还是换目录」。
运行中可取消（在当前阶段边界生效，已完成产物保留）；「按类型整理」默认开。

**CLI**：

```
orchestrator.exe <游戏目录> --out <输出目录> [--overwrite] [--organize]
                  [--allow-gui] [--reuse-raw DIR] [--no-verify] [--verify-jobs N]
                  [--strict] [--dry-run]
orchestrator.exe --doctor [游戏目录]     # 环境自检（只读）
orchestrator.exe --gui                   # 图形界面
```

| 开关 | 作用 |
|---|---|
| `--organize` | 额外产出 `类目清单.csv` + `分类/` 硬链接视图（不搬 `raw/`、不影响对账） |
| `--allow-gui` | 加密 KiriKiri 动态注入解包（需要真实桌面，约 40 分钟） |
| `--reuse-raw DIR` | 复用已有 raw，只重跑后处理与验收；**已转好的图按 mtime 跳过** |
| `--overwrite` | 输出目录有残留时先清空（不加则直接失败，避免新旧混算） |
| `--strict` | 额外要求「有索引地面真相」且「验收真的跑过」 |
| `--dry-run` | 只判引擎 + 查案例库，不动文件 |

退出码：`0` 全链通过／`1` 阶段失败或对账有差／`2` 引擎判出但无链路／`3` 引擎没判出。

**产物**：`raw/`（原始）+ `png/`（`.tlg`/`.pna` 转码成品）+ `manifest.json`（三段计数、
对账、验收结论）+ `_work/*.log`（各阶段日志）+ 可选 `类目清单.csv` 与 `分类/`。
`manifest.json` **失败也写**，写明哪一步、为什么。

## 界面

- 一屏三块：品牌栏 → 输入卡片 → 日志卡片；用留白与 1px 发丝线分区。
- 天空蓝 `#0EA5E9` **只作点缀**：主按钮、输入框聚焦环、勾选框、状态点，合计不到窗口 3%。
- 自绘圆角控件，尺寸跟随系统缩放；检测不准时用 `GALUNPACK_UI_SCALE=1.5` 强制指定。
- 运行时日志卡片上有 4px 进度线（按阶段推进、完成收起）；拖文件到窗口时输入框转虚线高亮；
  状态灯随结果变色（就绪灰 / 运行中蓝 / 完成绿 / 失败红）。

## 支持的引擎（9 条链路）

| 引擎 | 判定特征 | 提取方式 |
|---|---|---|
| Ren'Py | `.rpa` | 自研 RPA 解包（索引对账） |
| KiriKiri | `.xp3` | GARbro 静态提取；**加密 xp3** 走 `--allow-gui` 动态注入 |
| RPG Maker MV/MZ | NW.js 壳 + `www/` | 自研解密（假头 16B + XOR） |
| Yu-Ris | `pac/*.ypf` | 自研 YPF 逆向（名字 XOR + 置换表 + zlib/YCG） |
| AdvHD | `AdvHD.exe` + `.arc` | GARbro + 自研 PNA 多帧 carve |
| ExHIBIT/Retouch | `.gyu`/`.grp` | 自研 C# 解码器（随包现编）+ TOC 切分 |
| CatSystem2 | KIF `.int` | 自研 Blowfish/MT 全链（含密钥爆破） |
| Unity | `<游戏>_Data` | AssetStudio JSON 枚举 + Convert 分批导出 |
| Artemis (iMel) | `iarsys*.dll` + `.pfs` | 自研 pf8 分卷解包 + 散装媒体归集 |

Tyrano/Electron 等其余引擎：判得出来但无链路（退出码 2，不假装成功）。

解不动的包不会硬猜：会给出「下一步该做什么」（手工丢进 KrkrExtract / 补案例库），
并按 skippable 规则跳过它继续解其余包。

## 运行环境

| 项 | 要求 |
|---|---|
| 系统 | Windows 10 1809+ / 11，x64 |
| 权限 | 不需要管理员 |
| .NET Framework | 4.6+（GARbro / AssetStudio / 自带 C# 工具的 csc 现编需要；纯 Python 链路没有也能跑） |
| 内存 / 磁盘 | 建议 ≥ 8 GiB；程序本体约 350 MiB，**产物另算**（可能数 GiB） |
| 网络 | 不需要（全本地） |

## 常见问题

**报「拒绝访问」**：先跑 `--doctor`（或 GUI「环境自检」），报告里的完整性级别 / UAC /
六处写探针能直接看出是哪一层在拦。**「加火绒信任区」不一定有效**——实测整盘加白仍然失败，
分水岭是「程序放在哪个目录」。换位置也不行时，源码态可用 `start-gui.bat`
（借 `python.exe` 的信任绕开未签名 exe 的拦截）。详见 `antivirus-false-positives.md` §7–8。

**加密 KiriKiri 解出来只有脚本、没有图**：KrkrExtract 的模式是开关式的，默认只开
`Decompile Script`，要先点 **Full Unpack**。

**失败复盘**：`_work/*.log` 是各阶段完整日志；程序级失败还会追加一条到 `failures.log`
（时间、错误码、引擎、阶段、退出码）。

## 边界与局限（别把这些当成 bug）

1. **同名文件 ≠ 同一种加密**：都是 `data.xp3`，不同公司的加密可能完全不同。软件能判出
   「这是 KiriKiri」，判不出「这家用了哪种加密」——后者只能靠实测样本，再记进案例库。
2. **案例库是离散的**：覆盖已经踩过的具体游戏，没踩过的新变体照样要从头逆向。
3. **只做资源提取**：不做打包回写、文本提取、翻译；加密 KiriKiri 的全自动仍依赖桌面环境。
4. **「没验」不等于「验过」**：加密包没有索引可数时 `diff=None`（`no-index-available`），
   `--strict` 下这种算失败。

## 从源码构建

```
python build_exe.py
```

产物在 `_spike_pkg/dist/orchestrator/`，便携 zip 在 `packaging/Output/`。
回归测试：`python tests/run_all.py`（含 README 与代码的契约测试）。

## 文档

- `AGENTS.md` — 交接文档：当前状态、决策、踩过的坑（接手先读）
- `verified-findings.md` — 实测证据簿：每个结论的出处与复现方式
- `antivirus-false-positives.md` — 被安全软件拦截的原理与处置
- `cases/` 案例库；`rules/engines.json` 引擎判定规则
