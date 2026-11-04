# 杀软误报与 SmartScreen 应对（软件化阶段 3 交付物）

> **状态（2026-11-04）**：用户决定**不做安装器，只发便携 zip**（理由见 §5：安装器在本机
> 被火绒 + 深信服 EDR 按进程信誉拦敏感写入，而它只换来卸载键与开始菜单快捷方式）。
> 本文档 §5 的安装器实测记录**保留为历史证据**，不再对应现行交付形态；
> 现行交付 = `packaging/Output/GalgameUnpacker-<版本>-portable.zip`，解压即用。

> **来源声明（必读）**：本节结论来自**社区实践 + 参考项目公开文档**（GameStringer `docs/ANTIVIRUS.md`
> 的做法、PyInstaller 社区常见讨论），**不是杀软厂商或 PyInstaller 官方的保证**。
> 蓝图（`galgame-ai-unpack-workflow-plan.md` §4.5）已核对 PyInstaller 的 *Common Issues and
> Pitfalls* 与 *When Things Go Wrong* 两页：**均无 antivirus / false positive 章节**。
> 所有「有效」的说法都是经验性结论，请以自测为准。

## 1. 为什么会被报（机制性原因）

| 原因 | 说明 |
|---|---|
| **PyInstaller 引导器是误报重灾区** | 打包器也是恶意软件最常用的载体之一 → 厂商对 `PyInstaller bootloader` 特征普遍给低初始信誉。**本工具的 exe 是 onedir + PyInstaller 6.x，天然在嫌疑名单里** |
| **新文件信誉为零** | SmartScreen 对没有累积下载量/签名的二进制直接弹「未知发布者」；代码签名证书也没签时必然遇到 |
| **注入类伴生工具** | KrkrExtract（GUI 注入链路用的**外部**工具）本身干的就是「DLL 注入 + 脱壳」这类启发式重点怀疑对象的事。注意：注入是 **KrkrExtract.exe 自己干的**，不是本工具的 exe 注入别人——本工具进程面相对干净，但**外部工具目录整体可能被报** |
| **UPX 等壳** | 加壳=误报放大器。**本项目明确不使用 UPX**（build_exe.py 未加任何压缩壳参数） |

## 2. 本项目已做的设计级缓解

1. **onedir 而非 onefile**（蓝图 §4.2）：onefile 每次启动解压到临时目录 `_MEIxxxxx` 的行为更像恶意软件、也更可疑；onedir 落盘即运行，无此特征。
2. **注入功能是可选开关**：加密 KiriKiri 的 GUI 自动化链路只在显式 `--allow-gui` 时启用；默认路径全部是纯文件级解包（读归档→落盘→验收）。
3. **不加壳**：无 UPX/Nuitka，二进制就是 PyInstaller 原始产物。
4. **外部工具不进安装包**：GARbro / KrkrExtract / ffprobe / AssetStudio 全部由用户自备（`toolbridge.py` 按 override → 环境变量 → `toolbridge.json` → 内置候选 → PATH 解析）。安装包里只有本工具自己的代码与数据，许可证上也更干净（蓝图 §5.2）。

## 3. 发布前自检清单（每次出新版都过一遍）

1. **本地全链验证过再发**：`python build_exe.py` → `python _spike_pkg/run_frozen_smoke.py --full` 退出码 0。
2. **产出并记录哈希**：安装包与 exe 的 SHA256 写进 release 说明（build_exe.py `--installer` 末尾会打印安装包 SHA256）。
3. **VirusTotal 自查**：上传安装包与 `orchestrator.exe`，记录被报引擎数。PyInstaller 产物常见 **2~10 个引擎误报**（多为吊牌型：Mal/Generic-Suspicious 一类）；如果某家报出具体木马名（如 Trojan:Win32/...），先怀疑构建环境被污染，不要直接发布。
4. **便携 zip 备用渠道**：把 `_spike_pkg/dist/orchestrator/` 整目录打 zip 提供下载，作为安装器被拦时的退路（社区实践：提供第二渠道能显著降低「装不上」的客诉）。

## 4. 遇到误报后的处置（按代价从低到高）

1. **先确认是误报**：VirusTotal 看报的是哪几家、报名是否具体。吊牌型（Generic/Heuristic）→ 走申诉；真报名 → 停。
2. **厂商申诉**：
   - Microsoft（Defender/SmartScreen）：安全门户误报提交表单（Microsoft Security Intelligence 的 *Report a software vulnerability / false positive* 渠道），通常数天到数周回复；
   - 其他主流厂商（Kaspersky / ESET / Avast 等）各有误报提交表单，搜「<厂商> false positive submission」；
   - 申诉材料：软件用途说明、官网/GitHub 页、签名（若有）、为什么二进制长这样（PyInstaller onedir）。
3. **代码签名证书**（成本最高、收益最大）：
   - OV 证书：几百年费级别，能消掉大部分「未知发布者」，但**刚签的 OV 同样要积累信誉**；
   - EV 证书：对 SmartScreen 信誉提升最明显（社区共识），个人开发者办理门槛高；
   - 本项目当前个人自用，**暂不办理**；若未来分发给他人，这是第一优先项。
4. **被动应对（发给个人用户的话术）**：提供 SHA256 供比对 → 让用户在 Defender 里添加排除目录 → 或走便携 zip 渠道。

## 5. 已知事实记录

- 2026-11-02 首次构建（PyInstaller 6.22.3 + Inno Setup 6.7.3 安装器）。安装包 25.3 MiB
  （onedir 77 MiB → lzma2/max），SHA256 见构建输出。
- **⭐ 2026-11-02 实测根因（修正早前误判）：本机装有火绒（HipsDaemon/HipsTray）+ 深信服
  EDR（Sangfor×4 进程），按「进程信誉」拦截未签名新程序的敏感面写入**。SAC=0、
  Defender RTP=关、AppLocker=停——排除其它嫌疑。表象：
  1) **用户真实桌面双击安装包**：第一步建 `%TEMP%\is-*.tmp` 就被拒（Error 5 拒绝访问）；
  2) 代理会话里跑同一安装包：建 temp 成功、184 文件复制成功，但开始菜单 .lnk
     （`IPersistFile::Save 0x80070005`）与 HKCU 卸载键（`RegCreateKeyEx code 5`）被拒 → rc=4 回滚；
  3) `reg.exe` / `powershell.exe` 同样的写**放行**；csc 现编的无名小 exe 同样的写**被拒**。
  → 结论：**终端防护按镜像放行白名单进程、拦未知进程**，不是安装器缺陷、不是 ACL 问题。
  （此前的「代理会话产物」判断错误——用户桌面双击同样被拒，证据闭环。）
- **对用户测试的影响与通道**：
  - **便携版 zip（首选通道）**：`python build_exe.py --portable` →
    `packaging/Output/GalgameUnpacker-<版本>-portable.zip`，解压即用，不碰安装器被拦的
    那些写入（SHA256 以构建输出为准）。
  - 安装版要装的话：把安装包加进**火绒信任区**（或让深信服管理员放行）后再双击。
  - **预警：ExHIBIT / CatSystem2 链路首用会现编 C#（csc 落 exe 到 `_internal/`）**——
    若 EDR 同样拦「未知 exe 写程序目录」，这两条链路会失败并如实报错；遇到就在
    火绒/EDR 里放行 `csc.exe` 与本程序目录。
- 参考先例：GameStringer（Tauri）维护了公开的 `docs/ANTIVIRUS.md` 主动说明页——若本项目未来公开分发，照此做一页并链接进 README。
