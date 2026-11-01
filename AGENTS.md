# Galgame 自动解包工具 — 项目上下文

个人自用/学习项目：自动解包 galgame，产出**视频、音频、图片**三类资源。
**不做**：打包回写、文本提取、翻译、对外分发。

> **⭐ 终局目标（2026-10-27 用户明确）**：把这套工作流最终做成**一套可复用的 Windows 软件**
> （打包分发的那种，不是散装脚本）。当前所有解包攻坚都在为它攒三样东西：
> ① 决策树/规则表（分派逻辑）② 已验证的自研工具（引擎分支实现）③ verified-findings（实测证据）。
> 写新工具时向这个方向靠：依赖要轻（C# csc 优先）、规则要数据驱动、各分支接口要统一。
> 完整方案（Windows 打包、许可证/法律）见 `galgame-ai-unpack-workflow-plan.md`。

> **⭐ 项目主目录：`D:\K\deepseek`**（2026-10-29 用户确认，以此为准；`D:\K\zcode\game` 是同期副本，**已不再使用**）。
> 本项目**所有新产出**（解包产物、清单、报告、新脚本、文档更新）一律放在 `D:\K\deepseek` 里。
> 外部工具（GARbro / AssetStudio 等）在 `D:\K\galgame\`，位置见下方「环境」。
>
> **📦 版本控制（2026-10-29 建立）**：`D:\K\deepseek` 已是本地 git 仓库（基线提交 `55135af`）。
> **远程仓库：`git@github.com:KTEC1200/game-git.git`** —— 用户 2026-10-29 指定，
> **但约定「等软件第一版成型了才上传」**，在那之前**不要 push**、不要加 remote。
> 期间照常在本地提交，保持历史干净。`.gitignore` 已排除 `_extracted/` 等大产物。

## 文件索引（按需读，别全读）

| 文件 | 何时读 |
|---|---|
| `galgame-unpack-decision-tree.md` | **写任何分派/判定逻辑前必读**：决策树、报错串→动作、后处理、验收判据 |
| `verified-findings.md` | 需要实测证据、工具行为、坑的细节时 |
| `tutorials/` | 需要规则原始出处时（krkr / unity / 其他引擎三篇） |
| `galgame-ai-unpack-workflow-plan.md` | 需要完整方案、Windows 打包、许可证/法律时 |
| `vn-unpacker-verification.md` | 需要第三方工具核实状态时 |

## 工作区布局（2026-10-29 实测：根目录 **63 个文件 + 4 个子目录**，含 C# 解码器与黑盒工具）

**知识产物（长期保留）**
- `AGENTS.md` / `verified-findings.md` / `galgame-unpack-decision-tree.md` —— 结论、证据、规则
- `galgame_dispatch.py` —— dry-run 分派器（主产物）
- `_fixtures/` —— 回归样例（`make_fixtures.py` 可重建）
- `tutorials/` —— 用户的原始教程（**用户提供的资料，勿删**）

**可复用脚本**
- **编排器：`orchestrator.py`**（2026-10-29，软件化第 3 步，**主入口**）—— 一条命令跑完
  `detect → extract → postprocess → verify → manifest`：
  `python orchestrator.py <游戏目录> --out <输出目录> [--allow-gui] [--reuse-raw DIR] [--no-verify] [--dry-run]`。
  已接 **Ren'Py / KiriKiri / RPG Maker / Yu-Ris / AdvHD / ExHIBIT / CatSystem2 / Unity 八条链路**（其余引擎判得出就退出码 2，不假装成功）。
  退出码：`0` 全通过 / `1` 阶段失败或对账有差 / `2` 引擎判出但无链路 / `3` 未命中。
  输出 `raw/`（原始）+ `png/`（tlg/pna 转出的成品）+ `manifest.json`（counts 分 raw/final/converted 三段）
  + `_work/*.log`。**对账一律以索引为地面真相，diff≠0 即失败**；`--reuse-raw` 跳解包但不跳对账。
  实测：`Swipe Right` 2156 条目 0 差、`兼职人妻` 2562 条目 0 差 + 507 tlg→png（图片 902/902）、
  `常識改変学園` 1585 条目 0 差（图片 719/719、音频 866/866、视频 0/0）、
  `あまねぇ` 8201 条目 0 差（图片 3484/3484、音频 4522/4522、527.7 分钟）、
  `ラブラブお痴験バイト性活` 9032 条目 0 差 + 48 个 `.pna`→2640 帧
  （图片 4306/4306、音频 7031/7031、视频 9/9，媒体 857.4 分钟，全链 578.8s 退出码 0）、
  `夕凪荘的S级的女朋友们` 11476 条目 0 差（`.gyu` 2184 + `.grp` 9185 + 散装 107；
  图片 2184/2184、音频 9291/9291、视频 1/1，媒体 1072.0 分钟，全链 930.3s 退出码 0；
  **22 个加密 BGM 显式排除并报出**）。
  **待转格式按扩展名分派**：`.tlg`→`tlg2png`、`.pna`→`_pna_carve.carve()`；两者都列在
  `manifest.CONVERTIBLE`（**唯一出处**，orchestrator 直接引用，别在两边各写一份，否则
  「交付了多少」两边数字对不上）。一个 `.pna` 出多帧，所以 postprocess 另记 `frames_out`。
  **接新引擎的四条硬规矩**：① 地面真相只写一份（RPG Maker 的 `_rpgmv_decrypt.iter_candidates()`、
  Yu-Ris 的 `_ypf_extract.read_index()`、ExHIBIT 的 `_grp_extract.expected_counts()`，orchestrator 直接调，别抄第二份）；
  ② `EXTRACTORS` 存**函数名**不存函数对象（存对象会在 import 时焊死引用，monkeypatch 失效）；
  ③ `IMPLEMENTED`（orchestrator）与 `IMPLEMENTED_CHAINS`（planner）必须同步，测试有防漂移护栏；
  ④ **有意排除的输入必须显式报出**（ExHIBIT 的 22 个加密 BGM 不纳入交付，但要进 `st.data["unsupported"]`、
  写进 detail、并经 `source.unsupported` 落进 manifest）——`.mos` 那次教训：无声的漏验最危险。
- **外部工具桥：`toolbridge.py`**（2026-10-29，软件化第 2 步；**2026-10-30 起含 C# 现编**）——
  统一「找工具 + 调用 + 数产物 + **退出码不信任**」，已覆盖
  GARbro / tlg2png / ffprobe / AssetStudio / KrkrExtract / **csc** / **gyu** / **hg3** 八个。
  `python toolbridge.py check` 自检（含自带 C# 工具）、`python toolbridge.py csharp` 看编译状态；
  库用法 `tb.run("garbro", ["-x", xp3], cwd=out, product_dir=out)`。
  工具路径按 override → `TOOLBRIDGE_<KEY>` 环境变量 → `toolbridge.json` → 内置候选 → PATH 解析，
  **不再硬编码**。成败一律看产物数，`returncode` 只进诊断字段。坑 4（AssetStudio 逗号/竖线）已做成参数级护栏。
  **`ffprobe_ex()` 是验收口径的补强（2026-10-31）**：`ffprobe()` 原来把所有失败原因折叠成一个 `None`，`stage_verify` 只能报一句「ffprobe 无结果」——看日志的人分不清「文件真坏」和「子进程没起来/超时」。
   `ffprobe_ex(path, timeout=120, retries=1) -> tuple[info|None, reason]` 失败时重试一次，并把原因串出来
   （`超时（>120s）` / `rc=N：<stderr 末行>` / `没有任何音视频流` / `JSON 解析失败` / 非白名单）；`ffprobe()` 退化成取 `[0]` 的薄包装，老调用方行为不变。
   `stage_verify` 把原因写进 `fail_examples`，格式 `[av] <路径> :: ffprobe 无结果——<原因>`。
- **自带 C# 工具源码随包、首启现编**（阶段 2 第 2 条，2026-10-30）：`_gyu_tool` / `_hg3_tool`
  **只带 `.cs`**（exe 不入库）；`ensure_csharp("gyu")` / `run_csharp("gyu", argv, product_dir=…)`
  先确保 exe 在——仓库里已有且不比源码旧就直接复用，否则 `csc /nologo /target:exe /platform:X /out:…`
  现编一次，产物缓存在源码旁（**源码 mtime 变新才重编**）。编译失败抛 `CSharpBuildError`，
  消息带 **csc 路径 + 源码名 + stderr 原文**——不许静默退化成「工具不存在」（那会把用户引到错方向）。
  `run_csharp` 与 `run()` 共用同一套「数产物」判定（自带工具都是「扫一棵树 → 另存一棵树」，
  rc=0 而 0 产物完全可能）。`check_all()` 的特例：exe 不在但**源码在且 csc 在**记为可用
  （`buildable=True`），否则「源码随包」的干净检出会被误报成缺工具。
  编译平台：载 32 位游戏 DLL 的黑盒 oracle 必须 `x86`（否则 `BadImageFormatException`），
  纯独立转换器 `anycpu` 即可。
- **manifest 契约：`manifest.py`**（2026-10-29，软件化第 4 步）—— **契约的唯一实现**，
  供 `orchestrator.py`、`krkr_auto_extract.py` 与三个单格式解包器共用（各写一遍必然漂移，
  而 manifest 是交付清单，漂移就等于工具之间对「交付了多少」说法不一致）。
  counts 分 `raw`/`final`/`converted` 三段：`raw` 含待转格式（.tlg）、`final` 是**交付口径**
  （图片报成品数，如高慢妻 1301 而非 raw 的 436）、`converted` 解释两者差额。
  `reconcile(expected, actual)`：`expected=None` 时返回 `diff=None` + `method="no-index-available"`
  —— **不许把「没验」伪装成「验过了」**。`final` 一律**实际扫盘不做减法**（转换失败/同名覆盖时会算错）。
  标签统一 `as_posix()`（跨机器可比）。`python manifest.py <输出目录>` 打摘要。
  `source.unsupported`（可选）：**有意排除、没进交付**的输入（ExHIBIT 的 22 个加密 BGM），
  空列表不写——下游读的是 `source`，不能把「我知道漏了什么」藏在 stages 里。
  - `counts(raw_dir, png_dir)` —— **raw/ + png/ 两目录形态**（orchestrator、krkr_auto_extract）。
  - `counts_flat(out_dir)` —— **落盘即成品形态**（`rpa_extract_organized.py` / `_rpgmv_decrypt.py` /
    `_ypf_extract.py`：转换做在落盘之前，磁盘上从不存在中间格式，故 raw == final、converted 为空；
    **不许伪造带 `.ycg`/`.rpgmvp` 的 raw 段，那是编数据**，转换明细进 `postprocess`）。
- **案例库查表：`case_lib.py`**（2026-11-01，orchestrator 阶段 1.5）—— `cases/` 的**签名与查表唯一出处**：
  `signature(engine, signals)`（= sha1("engine|逗号连接的排序信号 id")[:12]）、`case_id(...)`、
  `load_index()` / `load_case()` / `lookup(engine, signals)`。命令行 `python case_lib.py <engine> <sig1,sig2>` 手工查。
  查表**只报告不决策**：案例的 `expected_total` **不参与对账**（编排器自己的归档索引才是地面真相）。
- Ren'Py：**`rpa_tool.py`**（`info`/`list`/`extract`）、**`rpa_extract_organized.py`**（一步分类解包，`--manifest PATH` 可选）、`_organize_rpa.py`（先解再分，留档）
- Unity：**`_unity_extract.py`**（AssetStudio JSON 枚举 + Convert 导出，orchestrator 第 8 条链路）、**`unity_unpack.ps1`**（手工版）、`_as_audio_collect2.py`（FSB5 分组累积）、`_as_catalog.py`、`_as_summary.py`、`_scan_unity_video.py`
- KiriKiri：`_tlg2png_all.ps1`、**`_krkr_tlg_convert.py`**（tlg2png 批量转换 Python 版，避开 CJK 路径坑）
- **KiriKiri 加密动态提取：`krkr_auto_extract.py`**（ASCII stage 硬链接 → Lite.exe CLI 注入 →
  Explorer 拖拽逐包提取 → 完成判定 → 移产物；`<游戏目录> [--out DIR] [--keep-stage]`；
  配套 `_uia_item_rect.ps1`；方法论见 verified-findings §17）
- 通用验收：**`_verify_media.py`**（图片 Pillow / 音视频 ffprobe，带扩展名白名单）、`_verify_images.py`、`_verify_audio.py`、`_manifest.py`、`_scan_video.py`、`_locate.py`
- 选样盘点：**`_scan_hy_inventory.py`**（扫 `D:\HY` 两级体积 + 引擎特征签名，输出 UTF-8 JSON，只读）
- Electron/asar：**`asar_tool.py`**（info/list/extract）、**`_spite_decrypt.py`**（ChaCha20 资源解密 + 多轮路径反哺）、
  **`_spite_bruteforce_paths.py`**（缺失路径组合枚举）、**`_spite_extract_pool.py`**（minified 混淆池提取/解码）
- 弯路留档（别再照抄）：`_reclassify.py`（原地改归档，见坑 5）、`_as_audio_collect.py`（旧版慢）、
  `_check_rpa_verify.py`（内含硬编码路径 `D:\K\deepseek\_rpa_media.csv`，该中间产物早已删除，路径已失效——本脚本仅作教训留档，勿再运行）
- RPG Maker：**`_rpgmv_decrypt.py`**（MV/MZ 解密：假头 16B + 仅前 16B XOR key，key 取自 System.json；见 verified-findings §12）
- AdvHD：**`_advhd_run.py`**（逐 .arc 先列后提 + 对账 + .dat→wmv）、**`_pna_carve.py`**（PNAP 等多帧容器按 PNG 签名→IEND 逐帧 carve，通用）；见 verified-findings §13
- Yu-Ris：**`_ypf_extract.py`**（YPF 提取：名字 XOR key、名长置换表、可选 zlib、YCG→PNG；格式逆向自 arc_unpacker 源码）；见 verified-findings §14
- ExHIBIT：**`_gyu_tool.cs/_exe`**（.gyu 批量解码，C# + csc 编译）、**`_grp_extract.py`**（.grp/AiFS TOC 切分）；见 verified-findings §15
- CatSystem2：**`_cs2_int_extract.py`**（.int 全链：MT 名字混淆 + 小端 Blowfish + key 爆破法）、**`_hg3_tool.cs/_exe`**（HG-3 家族批量转 PNG，按魔数扫描）、`_cs2_key_brute.cs`（main_key 约束爆破器）；见 verified-findings §16

**`_as_probe/`（AssetStudio 全资产枚举）已删除**。
它曾用于记录 Unity 样本中**未被导出的资产类型**（TextAsset 214 含 Spine、MonoBehaviour 490、Shader 70…）
以及「本作无 VideoClip」的一手证据——这些结论**已转写进 `verified-findings.md` §8.6/§8.7**，无需保留原始 JSON。
需要时重跑 `AssetStudio.CLI --export_type JSON` 即可重建。

**已清理（过程产物，勿再找）**
Unity 侧：`_as_aud_*` / `_as_stage` / `_t_*` / `_as_audio` / `_fsb_probe` / `_tmp_extract` / `_as_probe`、
对照实验日志（`_t_*.log`）、已废弃的证伪脚本（`_probe_magic.py` / `_probe_xp3.py` / `_validate_index.py`）。
Ren'Py 侧：`_rpa_stage` / `_rpa_patch_stage` / `_rpa_arch.txt` / `_rpa_patch.txt` / `_rpa_media*.csv` / `_vframe*.png`。
各条结论与数据**均已转写进本文档与 `verified-findings.md`**，无需原始中间产物。

## 状态

- ✅ **`galgame_dispatch.py`** — dry-run 分派器，纯规则、只读、仅标准库。引擎指纹在
  `rules/engines.json`（规则表 + 解释器），提取计划由 `planner.py` 生成。
  `python galgame_dispatch.py "<目录>" [--depth N] [--garbro <GARbro.Console.exe>] [--json out.json] [--plan] [--plan-json out.json]`
  - `--plan` 附「建议 extractor + 可直接复制的命令」；`--plan-json` 给批处理。
  - planner 只写「怎么跑」不写「跑不跑得通」（`implemented` 只表示 orchestrator 有没有接这条链，
    能不能解一律实跑定——坑 2）；参数只从 `Report.archives` 的实测归档拼，不猜包名、不猜哪个加密；
    `argv` 是列表（含空格路径不会被拆碎），`cmdline` 只给人复制、不参与执行。
  - 产物一律落 `<仓库>/_extracted/<游戏名>/`，**不写进游戏目录**（会污染原包，且加密 KiriKiri 链
    要 stage 纯 ASCII 副本，混在一起分不清谁产生的）。
- 引擎判定已实测正确 **9/9**（1 Unity + 8 KiriKiri）；回归样例 `_fixtures/`（用 `make_fixtures.py` 重建）**6/6 通过**（2026-10-14 复跑确认）。
  2026-10-30 起引擎规则扩到 **9 个**（Unity / KiriKiri / Ren'Py / Tyrano-Electron / RPG Maker /
  AdvHD / Yu-Ris / ExHIBIT / CatSystem2），12 个真实样本里 11 个在场全部判对（`My Best Deal` 已从磁盘消失）；
  `tests/golden_detect.json` 逐字锁定 engine/score/evidence/facts 四个维度，**测试 318 passed / 5 skipped**。
- 用户的 `D:\HY\pork社` 7 个游戏经 **GUI 实测全部可静态提取**。
- ✅ **三条产出线（视频 / 图片 / 音频）全部有实测验证过的样本** —— 见下表。

### 十二个已跑通的完整样本

| 样本 | 分支 | 产物 | 验收 |
|---|---|---|---|
| `D:\HY\pork社\兼职人妻` | **KiriKiri** | 图片 902 PNG / 音频 1577 OGG | Pillow 902/902、ffprobe 1577/1577（217.7 分钟） |
| `D:\HY\My Wife Wants to Be a Professional Cosplayer` | **Unity**（Naninovel 2022.3.62f2 / Mono） | 图片 777 PNG / 音频 1168 WAV | Pillow 777/777、ffprobe 1168/1168 |
| `D:\HY\最佳的交易\My_Best_Deal_v4.7-pc` | **Ren'Py**（RPA-3.0 / Python 2.7） | **视频 288**（mpeg4+v9，71.2 分钟）/ 图片 7804 / 音频 47 | Pillow 7804/7804、ffprobe 288 全通过 |
| `D:\HY\SPITE` | **Electron 自研引擎**（asar + ChaCha20 加密，2026-10-25） | 图片 128 / 音频 68（49.4 分钟）/ 视频 45（h264 循环动画）+ Spine 8 skel/8 atlas | Pillow 128/128、ffprobe 113/113、**失败 0**；资源覆盖 257/365 槽 |
| `D:\HY\Swipe Right for Sugar Mama Sensei` | **Ren'Py**（RPA-3.0 / Python 3，四包分工，2026-10-26） | 音频 1541 OGG（187.6 分钟）/ 图片 326（png 256 + bmp 70）/ 脚本 114 rpyc | Pillow 326/326、ffprobe 1539/1539；5 个 0 长度条目全部与索引对上 |
| `D:\HY\常識改変学園-製品版-` | **RPG Maker MV**（NW.js 壳 + www/，2026-10-26） | 图片 719 PNG（717 解密 + 2 明文）/ 音频 866 OGG（651 分钟） | Pillow 719/719、ffprobe 866/866；**无视频（验证过）**，见 verified-findings §12 |
| `D:\HY\tm\ラブラブお痴験バイト性活` | **AdvHD**（.arc ×18 + ASF .dat，2026-10-26） | 音频 7031 OGG（841 分钟）/ 图片 989 PNG + 677 mos(PNG) + 2640 PNA 帧 / **视频 9 WMV** | ffprobe 7031+9 全过；Pillow 989+677+2640 全过；18 包对账 0 差，见 verified-findings §13 |
| `D:\HY\あまねぇ -幼馴染お姉ちゃんとのえちえちあまやかされ同棲生活-` | **Yu-Ris**（pac/*.ypf，YPF 格式完整逆向，2026-10-26） | 图片 3484 PNG / 音频 4522 OGG（527.7 分钟） | Pillow 3484/3484、ffprobe 4522/4522；**无视频（pac 只有 3 包）**；自研 `_ypf_extract.py` 2 分钟提完，见 verified-findings §14 |
| `D:\HY\夕凪荘的S级的女朋友们` | **ExHIBIT/Retouch**（.gyu + .grp 逆向，2026-10-26） | 图片 2184 PNG / 音频 9291（ogg 9185 + wav 106）/ 视频 1 WMV | Pillow 2184/2184；grp 对账 9185/9185；**BGM 22 个加密未解**（侦察留档 §15.3） |
| `D:\HY\甜蜜女友\【PC电脑】甜蜜女友2+` | **CatSystem2**（KIF/.int 加密全链逆向，2026-10-27） | 图片 4499 PNG / 音频 23259 OGG（2275.7 分钟）/ 视频 10 MPG（22.6 分钟） | 提取 53500/53500 零失败；ffprobe/Pillow 全过；main_key=0x212C5F31 爆破获得；**2026-10-28 补完 107 个 24bpp HG-3 变体 → 4502/4502 零失败**（根因=row 硬编码 w*4，见 §16.5） |
| `D:\HY\pork社\高慢妻陥落！！` | **KiriKiri 加密**（KrkrExtract 动态注入，2026-10-28） | 图片 1301（tlg 865→png + png 436）/ 音频 1396（148.8 分钟） | **2838/2838 零失败**；ffprobe/Pillow 全过；无视频（条目级验证）；**全自动管线打通**（`krkr_auto_extract.py`），见 verified-findings §17 |
| `D:\HY\教师催眠1` | **KiriKiri 加密 ×10 包**（krkrZ 引擎，2026-10-28） | 图片 2009 / 音频 3600（556.8 分钟）/ **视频 2**（logo.mpg 5s + pv_movie.wmv 124s，1280x720） | **5724/5724 零失败**（含逐包补齐的版权声明 txt）；ffprobe/Pillow 全过；movie.xp3 的 Lock 混淆 TOC 手工破解（§17.7）；10 包全自动 + 断点续传实测 |

**四条产出线全部打通**：KiriKiri 与 Unity 两个样本**没有视频**（都是**验证过**的「没有」，判据见坑 3），
`My Best Deal` 验证了 Ren'Py 视频链路，`SPITE` 验证了 **Electron/asar + 资源加密**这条最难的新链路
（自研引擎、HKDF+ChaCha20 按路径派生密钥，详见 `verified-findings.md` §10）。
`兼职人妻` 还**不适用** E-mote 立绘与语音 concat 两条后处理分支（全包无 `.pimg/.psb`，语音是语义名而非序号）。
详细证据见 `verified-findings.md` §7（KiriKiri）、§8（Unity）、§9（Ren'Py）。

## ⚠️ 动手前先看（五个坑，每个都花过代价）

1. **`GARbro.Console.exe` ≠ `GARbro.GUI.exe`** — Console 会**假阴性**：GUI 能提取的游戏它报 `unknown format`。
   → **Console 报「读不出」不可信**，只能把「可识别」当正面证据；拿不准用 GUI 复核。
2. **别试图静态预测「能否解包」** — 已试过两种判据（搜 UTF-16LE 扩展名、解析 XP3 索引长度）**全部失败，且两个方向都出过错**。
   → **直接调用工具，不要预测。**（证据见 `verified-findings.md` §1–2）
3. **纯魔数扫描判「有没有视频」会大量假阳性** — `FLV`/`MPEG-PS`/`JPEG`/`ftyp`/`mdat` 在 `.ogg`/`.tlg`/`.resS` 压缩数据内部大量巧合命中。
   → 判据：**命中偏移 == 条目/资源起始偏移** 才算真文件。KiriKiri 用 `_locate.py` 与 GARbro 条目表交叉定位；
   Unity 直接看 AssetStudio 枚举出的 `VideoClip` 数量（0 就是真没有）。
   （此坑曾让 §3 得出「这批游戏有视频」的错误结论，已于 §7.1 修正）
4. **⭐ `AssetStudio.CLI` 的 `--types`：逗号会「静默归零」，exit code 0 毫无意义**
   - `--types A,B,C` → **0 个文件**（逗号被静默忽略，**退出码仍是 0**）
   - `--types 'A|B|C'` → 过滤器**整体失效**，退化成「导出全部」
   - **正确做法：只用单类型 `--types A`，或者干脆不写 `--types`。**
   - **退出码 0 绝不可当成功判据**，必须数产物文件。（证据见 `verified-findings.md` §8.1–8.3）
5. **⭐ 按资源分类归档必须「扩展名优先」，绝不能只按目录判**
   - 实测：`images/animations/` 下**同时**有 `.avi`(166)/`.webm`(115)/`.jpg`(283)，
     只按目录判会把 **282 个 jpg 错分进 `Video_WebM`**；视频还散落在 `images/mm/`、`images/notes/`、`tl/…`。
   - **正解**：先按**扩展名**认媒体本体，再退回按目录分；`tl/` 视为本地化补丁树整体保留。
   - **分类逻辑一旦发现错了，就「修逻辑 + 从源归档重跑」**，不要写迁移脚本原地修数据
     （原归档没动过，重跑只需 31 秒；原地迁移要处理「已移动/未移动」混合状态，越修越乱——实测踩过）。

## 下一步

> **⭐ 2026-10-28 用户定调的新方向**：主线做 **Ren'Py（含 .rpa 文件的）与 KrkrZ 引擎**，**Unity 作为进阶**；
> 终局目标不变——把工作流做成一套可复用的 Windows 软件（方案蓝图 `galgame-ai-unpack-workflow-plan.md`）。

1. ~~跑通一个游戏的完整提取~~ ✅ **已完成十二个**（见上表）。
2. **已暂停任务（2026-10-28 用户指示，四项均已完成，断点详单见「⭐⭐ 交接摘要 → 已暂停的未完成任务」）**：
   ① ~~KrkrExtract 补 Lite.exe~~ ✅（已下载核实）→ ② ~~pork 社 `高慢妻陥落！！` 动态提取~~ ✅ →
   ③ ~~教师催眠1 动态提取~~ ✅ → ④ ~~软件制作规划~~ ✅。教程流程（留作背景）：三件套放游戏根目录 → 游戏 exe 拖到
   `KrkrExtract.Lite.exe` 启动注入 → xp3 拖入控制台 → 输出 `KrkrExtract_Output`；
   报 `Unknown chunk in root chunk` 时换 KrkrzExtract；更新的 xp3 可试 KrkrDump/krkrzCxdec。
   **自动化版本见 `krkr_auto_extract.py`（推荐，无需手工拖拽）。**
3. **搁置（需用户辅助/交互，等指示）**：夕凪荘 BGM 22 个加密 ogg 的内存 dump（游戏开场界面需交互点击推进；
   静态逆向进展已回写 §15.3——解密器挂 this+0x70 的 vtable[0]，构造点 0x1029E1F0 置 0 系外部安装，
   dump 工具 `_bgm_dump2.py` 已备好）、GUI 弹窗行为确认。
4. **划走（2026-10-28 用户决定）**：夏への方舟 ×3、NekoSDK。
5. 最后才考虑接 AI 兜底（A1/A2/A3）——目前规则覆盖率已够高。
6. 选样参考：`_scan_hy_inventory.py` 的盘点结果（2026-10-25）+ `_extracted/_batch_dispatch.json`（2026-10-26 批量判定）。

### ⭐ 当前任务队列（2026-10-26 商定；2026-10-27 更新：前 3 项已完成，用户改为「GARbro 能解的不做，只做难/没见过的」→ 转入下方「全库扫描候选清单」，本队列仅存档）

按序执行，每个都走完整流程：判定 → 提取 → `_verify_media.py` 验收 → 计数对账到 0 → 结论回写本文档与
`verified-findings.md`。产出一律放 `D:\K\deepseek\_extracted\<游戏名>\`，解包前看磁盘余量（2026-10-29 实测 D 盘可用 73.4 GiB）。

1. ~~**常識改変学園-製品版-**（1.16 GB）—— RPG Maker MV/MZ 新分支~~ ✅ **已完成**（2026-10-26，见样本表；
   加密=假头16B+前16B XOR，key 在 System.json，自建 `_rpgmv_decrypt.py` 解决，无需 RPGMakerDecrypter；RPG Maker 分支已写入决策树 §2.3）。
2. ~~**tm／ラブラブお痴験バイト性活**（3.0 GB，本体在 `tm\ラブラブお痴験バイト性活\`）—— AdvHD 引擎新分支~~
   ✅ **已完成**（2026-10-26，见样本表；GARbro 原生支持 .arc 一个工具通吃，.dat=ASF/WMV 改后缀即得，
   .pna=PNAP 多帧容器用 `_pna_carve.py` carve；AdvHD 判据已写进决策树 §2.4。封包是 .arc 不是 .pac——原文笔误）。
3. ~~**あまねぇ -幼馴染…-**（2.14 GB）—— 未知 `pac/` 格式~~ ✅ **已完成**（2026-10-26，见样本表）。
   YPF = **Yu-Ris 引擎**封包（不是 Yaneura，yscfg/YSSD 前缀有迷惑性）；GARbro 不支持；
   格式完整逆向后自研 `_ypf_extract.py`（名字 XOR key + 名长置换表 + 可选 zlib + YCG），
   3484 PNG + 4522 OGG 全过验收；arc_unpacker 可作备选但有大坑（见决策树 §3 坑表）。
   Yu-Ris 判据已写进决策树 §2.5。
4. ~~Boku_Kano / 我与老师的私人课程2 / Toshiue Kanojo~~ **已划走**（全是 pf8/.pfs 家族，GARbro 可读，见候选清单划走区）。
5. ~~**温泉蒸汽人妻**~~ 已划走（KiriKiri Console 可读，按用户 2026-10-26 标准「GARbro 能解的不做」）。
6. ~~**MagicalMILFs / スキだらけ！**~~ 已划走（Ren'Py 散装，媒体裸放只验收）。
7. ~~（可选）**EnderLilies**~~ 出圈外（UE，非 galgame）。
8. ~~挂起等用户~~ → 并入候选清单「加密 KiriKiri 动态提取」项（现已 **8 部**：pork社×4 + 教师催眠×2 +
   aniyome + Doinaka Kyoudai）。

### ⭐ 全库扫描候选清单（2026-10-26 应用户要求扫 D:\HY 全部 49 目录）

盘点 JSON：`_extracted/_hy_inventory_20261026.json`。已跑通 7 样本之外，未知引擎全部做了魔数+GARbro 探针，
**按含金量（新分支 × 覆盖游戏数）排序**；「探针」= GARbro.Console 裸调 listing。

**~~划走~~（2026-10-26 用户判定：GARbro 能解包的不做）**：
- pf8/.pfs 家族 ×8：meikuraS、Maid for Loving You、SlowLife【PC+Ty】、yugamase、bokukano2、Toshiue_Kanojo、
  bonusfd1(Boku_Kano)、**アマカノ3**（后补探针：iarsys+emotedriver+`70 66 38`）——GARbro 全可读（含队列第 4 项三作）
- KAGUYA「LINK」.arc ×3：Mama×Holic、アネトモ、姉ちゃんのススメ——GARbro 可读（vrm.arc 内是 VRM 3D 模型，标准 glTF）
- Seifuku PAC ×2：Seifuku Kanojo 1+2——GARbro 可读（Movie.pac 内是 ZSTD 流）
- riruka .arc ×1——GARbro 可读（movie.arc=裸 ASF）
- role player（KiriKiri .xp3 Console 可读 ✅）、有閑夫人倶楽部（AdvHD ✅）、催眠性指導/Mizuki（Ren'Py）、
  MagicalMILFs/スキだらけ/爱的课堂（媒体裸放只验收）

**保留——难/没见过（按经验价值排序）**：

1. **ExHIBIT 引擎**（夕凪荘的S级的女朋友们 + 夏への方舟 ×3，共 4 部 13.1G）——~~真·未知格式~~
   ✅ **夕凪荘已攻坚（2026-10-26）**：.gyu 图片 2184/2184 全解（`_gyu_tool.exe`，含 7 变体/MT 去混淆/
   双 LZ/调色板/alpha）、.grp 语音 9185/9185（`_grp_extract.py`，AiFS TOC）、op.wmv 视频——
   **唯 BGM 22 个加密未破**（侦察全档见 verified-findings §15.3，密钥疑在 cluu/GUID/DPMODE）。
   **夏への方舟 ×3 待做**（同引擎，res2001.grp 是明文 OGG 拼流，BGM 大概率白捡；.gyu 同解码器）。
2. **CatSystem2 `__key__` 加密**（甜蜜女友 ss/ss+/1/1+/2/2+ 6 部，取一作即可覆盖分支）
   ✅ **甜蜜女友2+ 已攻坚（2026-10-27）**：加密全链逆向（小端 Blowfish + MT 名字混淆），
   main_key=0x212C5F31 用「k0 反推+约束爆破」拿下，**53500/53500 零失败**，图片 4392 PNG、
   音频 22806 OGG、视频 10 MPG（见 verified-findings §16）。**同系列其余 5 部可直接复用工具**
   （main_key 若不同按 §16.2 方法重爆，秒级）。
3. ~~**加密 KiriKiri 动态提取**（8 部：pork社×4 + 教师催眠1/2 + aniyome + Doinaka Kyoudai）~~
   ✅ **分支已打通（2026-10-28）**：`krkr_auto_extract.py` 全自动（注入+拖拽+完成判定，
   教师催眠1 全 10 包即用它跑完）；剩余 7 部可直接复用该工具，逐部跑一遍即可。
   （环境注意：游戏路径必须 ASCII stage——工具已内置；verified-findings §17）
4. **NekoSDK**（俺を欲しがる二人の母，WAFFLE）——本体是 **4.9G RAR（iso+mds）未解压**；
   翻译补丁脚本带 `NEKOSDK_ADVSCRIPT` 头 → 引擎指纹明确，NekoSDK（ねこぱんだ）资源格式现场分析。

**出圈外（非目标）**：nier（49G NieR:Automata）、nikke2（NIKKE 私服客户端）、Miside（Unity+BepInEx）、
EnderLilies/EnderMagnolia（UE，umodel 可选）。
**搭车项**：E-mote 立绘后处理（`.pimg/.psb`→FreeMote+krkrFgiEditor）是决策树里从未触发过的分支——
pf8/加密 KiriKiri 家族提取后若见到这两个扩展名，顺手把这条线走通。

**建议打法（2026-10-27 更新，前两项已完成）**：~~ExHIBIT 夕凪荘~~✅ → ~~CatSystem2 甜蜜女友2+~~✅ →
**夏への方舟 ×3**（ExHIBIT 工具直接复用）→ **NekoSDK**（先解 RAR 再判定）→ **加密 KiriKiri ×8**
（需补 Krkr 工具 + 用户 GUI 确认，放最后）。

### ⭐⭐ 交接摘要（2026-10-28 会话中状态）——新会话从这里接手

**终局目标提醒**：最终交付物是**一套可复用的 Windows 软件**（详见文首「终局目标」）。
后续每个新引擎分支的工具实现，都按「将来要进软件包」的标准写：
依赖轻（C# csc 自包含优先，Python 仅在无 C# 必要时用）、参数统一（`<输入> <输出>` 风格）、
判定规则可数据驱动（方便并进 `galgame_dispatch.py`）。方案蓝图在 `galgame-ai-unpack-workflow-plan.md`。

**主线方向（2026-10-28 用户定调）**：**Ren'Py（.rpa）与 KrkrZ 引擎为主，Unity 进阶**。

**已完成（累计 12 个完整样本，全部走完 判定→提取→验收→对账→回写）**：KiriKiri 兼职人妻 /
Unity My Wife / Ren'Py×2（My Best Deal、Swipe Right）/ Electron SPITE / RPG Maker MV 常識改変学園 /
AdvHD ラブラブ / Yu-Ris あまねぇ / ExHIBIT 夕凪荘 / CatSystem2 甜蜜女友2+ /
**KiriKiri加密 高慢妻陥落！！（2838/2838）+ 教师催眠1（5724/5724，含 movie.xp3 Lock 破解）**。
其中甜蜜女友2+ 已于 2026-10-28 **补完 107 个 24bpp HG-3 变体**（4502/4502 零失败；
根因=`_hg3_tool.cs` 的 `DecodeFile` 硬编码 `row = w*4`，24bpp 时 flip 越界；ApplyDelta 的 4 等分位
转置对 24bpp 同构无需改——GARbro 原版语义即如此，方法论见 verified-findings §16.5）。

**已暂停的未完成任务（2026-10-28 用户指示暂停，断点如下，可直接续做）**：

1. ~~**KrkrExtract 补工具**~~ ✅ **已完成（2026-10-28）**：Lite.exe 534,016 B 已下载并核实
   （本地 dll 就是 5.0.0.2 配套构建，运行时标题实锤），三件套齐。
2. ~~**pork 社最小加密 Krkr 动态提取（高慢妻陥落！！）**~~ ✅ **已完成（2026-10-28）**：
   2838/2838 零失败，全自动管线沉淀为 `krkr_auto_extract.py`；两条硬结论（ASCII 路径必需、
   Explorer 拖拽是唯一自动化通路）见 verified-findings §17。
3. ~~**教师催眠1 动态提取**~~ ✅ **已完成（2026-10-28）**：5724/5724 零失败（10 包全自动，
   中途断点续传实测；movie.xp3 Lock 混淆 TOC 手工破解出 logo.mpg + pv_movie.wmv，见 §17.7）。
4. ~~**软件制作规划**~~ ✅ **已完成（2026-10-28）**：输出 `software-plan.md`
   （manifest 契约 / toolbridge / orchestrator 四阶段路线，蓝图的落地版）。

**搁置（需用户辅助交互，等指示再动）**：
- 夕凪荘 BGM 22 个加密 ogg：静态逆向已推进（解密器挂 loader 对象 this+0x70 的 vtable[0]，
  虚调用壳 0x1029ECA0，构造 0x1029E1F0 只置 0 → 解密器系**外部安装**，安装点未追到）；
  内存 dump 方案工具已备好（`_bgm_dump2.py`：启动游戏+自动点击+按 serial 匹配扫描），
  但游戏停在需交互的开场界面，自动点击未推进——**需用户配合玩到标题画面/播放 BGM 时跑 dump**。
- GUI 弹窗行为确认（加密 KiriKiri 纯 CLI 自动化可行性）。

**划走（2026-10-28 用户决定）**：夏への方舟 ×3（ExHIBIT 工具本已现成）、NekoSDK（4.9G RAR）。

**环境变化**：磁盘余量 ~50G（2026-10-27）；外部工具新增 `D:\K\galgame\arc_unpacker\`（0.11，注意
`--out=DIR` 必须等号形式）与 csc.exe 黑盒 oracle / C# 解码器工作流（`csc -platform:x86` 载 32 位游戏 DLL）。
本会话新增可复用技能：**capstone PE 反汇编流水线**（`_bgm_re*.py`：vtable 搜索 → ctor 调用点 → 虚调用链；
比黑盒 oracle 快且不需要游戏跑起来）。**PrintWindow 窗口截屏**（`_bgm_shot.py`，查游戏当前画面）。
2026-10-28 深夜会话新增环境事实：**① 本机 DPI 200%**（物理 2880x1800，无感知进程看到 1440x900 虚拟坐标）
——UI 自动化脚本必须 `SetProcessDPIAware()` 且全程物理坐标，跨进程坐标（UIA/PowerShell）要自检口径；
**② 网络**：系统代理 `127.0.0.1:7897` 时断时续（挂着也可能全断），直连 `raw.githubusercontent.com`
通常可用、`github.com` 直连不通但走代理偶尔可通、`api.github.com`/`codeload` 基本不通——下载 GitHub
release 资产多试几条路由；**③ KrkrzExtract.exe**（176KB, v1.0.0.0）已由用户放入 `D:\K\galgame\krkr\krkrz\`。

**新会话开局**：读本文件 → 「已暂停的未完成任务」四项已全部完成（2026-10-28）；
软件化进度见 `software-plan.md` §5（2026-10-30 状态，**§5 六项全部完成**）：
`toolbridge.py` ✅ → `orchestrator.py` ✅ → `manifest.py` ✅ 契约唯一实现
（含 `counts()` 两目录形态与 `counts_flat()` 落盘即成品形态）→ 4 个解包器全部接上 `--manifest` ✅
→ `rules/engines.json` 指纹外置 ✅（规则表 + 解释器，`rules/__init__.py`）→ `planner.py` ✅
（`dispatch --plan` 输出「建议 extractor + 参数」）。
**测试 432 passed / 8 skipped**；`python tests/make_golden.py --check` 零漂移。
**软件化四阶段（software-plan §3）里阶段 1 已完成**；**阶段 2 进行中**：
- ✅ orchestrator 已接 **8 条链路**（Ren'Py / KiriKiri / RPG Maker / Yu-Ris / AdvHD / ExHIBIT /
  CatSystem2 / **Unity**）；前七条都用真实样本跑过退出码 0、对账 0 差，CatSystem2 验到 4 包
  （bgm/config/fes/image00 = 1351/1351 零失败，含最大单包 image00 的 1163 条），Unity 已全量跑通（图片 777/777、音频 1168/1168、视频 0/0，媒体 123.2 分钟，全链 153.0s 退出码 0）。
- ✅ **csc 黑盒工作流产品化进 toolbridge**（阶段 2 第 2 条）：8 个工具、C# 源码随包现编、
  `check_all()` / `check_csharp()` 自检，19 项新测试 + 3 轮变异验证（真 csc 编 hello-world 并运行）。
- 下一步：① ~~CatSystem2 **全量 51 包 / 53500 条**~~ ✅ **已跑通并拿到绿色 manifest**（2026-11-01：extract 53500/0 差、postprocess 4499 PNG、
  verify 图片 4499/4499、音频 23259/23259、视频 10/10、失败 0，媒体 2291.0 分钟，全链 2261.6s 退出码 0）
  ② ~~接 **Unity**~~ ✅ **已实现并全量跑通第 8 条链路（`_unity_extract.py`）**：JSON 枚举作地面真相、Convert 分批导出、FSB5 多轮累积。实测图片 777/777、音频 1168/1168、视频 0/0，媒体 123.2 分钟，全链 153.0s 退出码 0（Texture2D 有 5 个引用型资产缺口，已显式报出并对账通过）
  ③ 接剩下 1 个引擎（**Tyrano-Electron**；目前只有 `_fixtures/tyrano_game`，没有真实样本）—— 排在 cases/ 之后
     **2026-11-01 用户决定：Tyrano 暂不做**（无真实样本，收益低），软件化优先。
  ④ ~~`cases/` 案例库~~ ✅ **已完成（2026-11-01）**：12 个 case + `index.json` + `build_cases.py` +
  `tests/test_cases.py`；并已**接入 orchestrator**（阶段 1.5 `case-lookup` + `case_lib.py` +
  `manifest.source.case_match`），见下方专节。
- **阶段 3 第 1 条（PyInstaller 冻结冒烟）已完成（2026-11-01）**，结论见 `verified-findings.md` §19、
  路线更新见 `software-plan.md` §3 阶段 3。一句话：**冻结可行，但必须先改三处**——
  ① 7 处 `[sys.executable, "<脚本>.py"]` 兄弟脚本调用改 **in-process**（冻结后必坏，已实测）；
  ② 数据文件（`rules/engines.json` / `cases/` / `*.cs` / `toolbridge.json`）必须显式 `--add-data`（漏了就启动即崩）；
  ③ 子进程环境清理（`_MEIPASS` 被塞进 PATH，会继承给 ffprobe/GARbro/csc）。
  实测可用：原生/.NET 外部 exe 正常、CJK 路径正常、Pillow/numpy/pycryptodome 均进包、onedir 66.3 MiB / 冷启动 0.67s。

## cases/ 案例库（已完成 2026-11-01）

**目的**（蓝图 §2.7 自愈闭环）：拿到新游戏先算 (格式签名哈希, 目录特征)，命中案例库就直接套用
已验证的 (decoder, plugin/key, 备注)，跳过 LLM 推理（L0）。这是终局软件「决策树 + 已验证工具 +
实测证据」三件套里的第三件。

**设计**（2026-11-01 用户批准）：每个样本一个 JSON（`cases/<case_id>-<engine>.json`），字段
`case_id`（= sha1(engine + 命中信号 id 集合 + 样本 slug + discriminator)[:12]）、`engine`（**规范名**，
与 `fingerprint.engine` 一致）、`engine_label`（人读的描述名，如「KiriKiri 加密」）、`sample`、
`game_dir`、`discriminator`、`fingerprint`（signals/score/threshold/signature/reconstructed）、
`decision`（extractor/archive_exts/archive_count/expected_total/notes）、`timing`（各阶段秒）、
`result`（counts/verify/reconcile/ok/source/summary）、`failures[]`（stage/symptom/root_cause/fix/ref）、
`provenance`（source/manifest_path/doc_refs/generated_at）。
`cases/index.json`：指纹签名 → case_id 列表（同签名对应多 case，靠 `discriminator` 区分）。
`build_cases.py`：`--from-manifests`（从 `_extracted/*/manifest.json` 机械重建）/ `--from-docs`
（从文档提炼）/ `--index`（重建索引）/ `--validate`（校验 schema + provenance 诚实）。
**诚实纪律**：docs 重建案例 `provenance.source = "docs-reconstructed"`、`manifest_path = null`、
`result.counts/verify/reconcile = null`（不许伪造 manifest 口径的数字）；`failures[]` 只写有出处的。

**已完成**（2026-11-01）：
- ✅ `rules/__init__.py` + `galgame_dispatch.py` 加 `fired_ids`（命中信号 id 集合）——指纹签名的
  稳定来源；不改 facts，golden 零漂移。
- ✅ `cases/_failures_raw.json`（43 条 failure，12 样本齐全，ref 全部核验）。
- ✅ `engines.json` 缺 id 的信号补语义 id（Unity 6、KiriKiri 1、Ren'Py 3、Tyrano 2、RPG Maker 2、
  AdvHD 3、Yu-Ris 3、ExHIBIT 3、CatSystem2 2，共 25 个）——Ren'Py 的 fired_ids 不再是空集。
- ✅ `cases/_docs_meta.json`（8 个纯文档样本的图片/音频/视频/媒体分钟数，文档口径）。
- ✅ `build_cases.py`（构建器，含 `write_all` 清陈旧文件 + `validate_cases` 诚实校验）。
- ✅ 生成 **12 个 case + `index.json`（9 个签名）**，`--validate` 全过。
- ✅ `tests/test_cases.py`（21 个测试，锁纯函数 + 构建产物 + 诚实纪律）。
- ✅ **接入 orchestrator（2026-11-01，用户批准「报告命中」口径）**：新增 `case_lib.py`（签名/查表**唯一出处**，
  `build_cases.py` 与 `orchestrator.py` 都调它，别各写一份）、`stage_case_lookup`（**阶段 1.5**，
  在 detect 之后、`IMPLEMENTED` 链路检查**之前**——未接链路的引擎如 Tyrano-Electron 也能看到历史案例）、
  `manifest.source.case_match`（仅命中时写）、`--dry-run` 的 payload 增 `case_lookup`。
  **三种结局都 `ok=True`**：命中 N 个 / 无匹配 / 案例库缺失或损坏——区别只在 detail，
  「看过案例库，没有」和「根本没有案例库」不能混成同一种空。
  ✅ `tests/test_case_lookup.py`（41 个测试，含「签名/ case_id 可由每个 case 文件重算」锁定算法）。
- ✅ 测试 **493 passed / 9 skipped**；`python tests/make_golden.py --check` 零漂移。

**12 个 case 的来源分布**：5 个 `manifest`（My Wife / ラブラブ / 夕凪荘 / 甜蜜女友2+ ×2，其中
甜蜜女友2+_试跑 是同款非独立样本已排除）+ 7 个 `docs-reconstructed`（兼职人妻 / My Best Deal /
SPITE / Swipe Right / 常識改変学園 / あまねぇ / 高慢妻陥落！！ / 教师催眠1——实际 8 个纯文档，
My Best Deal 目录已删、指纹 reconstructed）。

**已知坑**：
- 兼职人妻（GARbro 可解）与高慢妻陥落！！（必须动态注入）**指纹完全相同**（都只有
  `xp3`/`xp3_known_names` 信号，规则无「加密 xp3」信号）→ 案例库必须靠 `discriminator`
  字段区分（`xp3-plain` / `xp3-encrypted` / `xp3-encrypted-krkrZ`），不能只靠签名。
- `engine` 字段曾误用 `_failures_raw.json` 的描述性标签（如「KiriKiri 加密」）导致与
  `fingerprint.engine` 不一致、按指纹查会错位——已改为以 `gd.scan` 的规范名为准，描述性标签
  另存 `engine_label`。
- `write_all` 必须清陈旧 case 文件：case_id 随 engine 规范化会变，不清的话旧文件残留、
  案例库越攒越脏（实测踩过：SPITE 早期被映射成 Tyrano/Electron 的残留文件）。

## 引擎分支要点（实测）

### KiriKiri
`GARbro.Console.exe -x <data.xp3>` 直接解（`兼职人妻` 2562 条 / **8 秒**）。
后处理按需：`.tlg`→`tlg2png`；`.pimg/.psb`→FreeMote + krkrFgiEditor（**仅在游戏有 E-mote 立绘时**才需要）。
**加密 xp3（Console/GARbro 读不出）→ 动态提取已全自动**：`krkr_auto_extract.py <游戏目录>`
（Lite.exe CLI 注入 + Explorer 拖拽法 + 完成判定；两大硬结论：游戏路径必须纯 ASCII、
跨进程 WM_DROPFILES 不可行唯一通路是 Explorer 真拖拽——详见 verified-findings §17）。

### Ren'Py（RPA）
- **不要用 `split(b" ")` 解表头**，用正则 `^RPA-3\.0 ([0-9a-f]{16}) ([0-9a-f]{8})` 抓「索引偏移 + XOR key」。
- **索引是 zlib 压缩的 pickle**：定位到偏移后若首字节 `0x78` 先 `zlib.decompress` 再 `pickle.loads`。
- 每个 `offset`/`length` **都要 `^ key`**（两作都是 `0x42424242`）才是真实值。
- 主工具：**`rpa_tool.py`**（`info`/`list`/`extract`）+ **`rpa_extract_organized.py`**（一步分类解包）。
  - **通用性已双样本验证**（2026-10-26 `Swipe Right` 四包 2156/2156 条目 0 失败）。
- **包分工不止 `archive+patch` 一种**：`Swipe Right` 用 `archive`(脚本) / `gui_resource` / `img_resource` / `sfx_resource`
  四包、无 patch。key 相同（0x42424242）不代表是同一作——别拿 key 当指纹。
- **patch 是「新增」还是「覆盖」→ 用两份索引求交集**判断，别猜。
- **0 字节文件要先查索引**：验收发现 0 字节产物时，先对索引里该条目的 length——
  源包声明 0 长度（占位文件，如 `se008.ogg`、`__init__.py`）属正常，不是解包 bug。别把源本身的空文件当失败。
- 视频常见 `mpeg4/.avi`（体积大、无音轨）与 `vp9/.webm`（含 Opus）；**数视频要按文件扩展名，不要用 ffprobe 的 stream 数**（内嵌封面会被算成视频流）。

### Unity（AssetStudio）
- **orchestrator 链路（2026-11-01 接入，第 8 条）**：`_unity_extract.py` 用 AssetStudio JSON 枚举
  作地面真相（唯一出处）、Convert 分批导出（按 Texture2D/Sprite/AudioClip 三类）、FSB5 容器音频
  多轮累积（`_as_audio_collect2.py`，单次只出 ~30%）。侦察实测：Texture2D JSON 460 / Convert 455
  （差 5 个引用型资产）、Sprite 322/322 完美、AudioClip JSON 1168 / 单次 Convert 377（32%，需多轮）。
  全量已跑通：raw 1945 文件（png 777 + wav 1168），图片 777/777、音频 1168/1168、视频 0/0，失败 0。Texture2D JSON 枚举 460 vs Convert 455 的 5 个缺口是引用型资产，AssetStudio 固有行为，已用 texture2d_gap 调整 expected_total 并在 detail 显式报出。
- 主流程脚本：**`unity_unpack.ps1`**（分批导出 + 引擎判定，已内置坑 4 的注释）
- 版本/后端判定：正则读 `globalgamemanagers` 拿版本；存在 `il2cpp_data/` 或 `GameAssembly.dll` 即 IL2CPP。
  Unity 6000 系改用 AssetStudioNext；IL2CPP 需先 Il2CppDumper。
- **不要一次性全导**（870 MB 规模会 `0xC0000374` 堆损坏）→ **按类型分批独立导出**。
- 音频若是 **FSB5(FMOD) 容器**（JSON 里 `m_Source: resources.resource`），CLI 单次只出极少数且静默失败
  → 用 **`_as_audio_collect2.py`** 多轮正则分组累积，**最后用 `^(A|B|C)$` 精确锚定清尾巴**（实测能到 100%）。
- 已排除的两条路（**别再试**）：`fsb5` pip 库（需原生 `libvorbis`+`libogg` 且有查表依赖）；
  FFmpeg（识别 FSB 容器但报 `Not yet implemented`）。

### RPG Maker MV/MZ（`常識改変学園` 实测，2026-10-26）
- 判定：NW.js 壳（`nw.dll`/`icudtl.dat`/`locales/*.pak`）+ `www/`；`js/rpg_core.js`=MV、`rmmz_core.js`=MZ。
- 加密=**假头 16B（`RPGMV`/`RPGMZ`）+ 原[0:16] XOR key + 其余明文**；key=`www/data/System.json` 的
  `encryptionKey`（32 hex，默认值=MD5("")）。**只有前 16 字节被加密**，其余照抄。
- 工具：**`_rpgmv_decrypt.py`**（自动找 www、跳过「免责声明」垃圾目录、明文直出文件照收）。
- 无需 RPGMakerDecrypter；加密的地面真相就在游戏自带 `www/js/rpg_core.js` 的 `Decrypter.decryptArrayBuffer`。

### AdvHD（`ラブラブお痴験バイト性活` 实测，2026-10-26）
- 判定：`AdvHD.exe` + `AdvHDLang.dll`。封包 `.arc`（索引含 UTF-16LE 名），**GARbro 原生支持**，
  音频出 ogg、图片自动转 PNG；逐包对账以包头 u32 条目数为地面真相。
- **GARbro 列表输出对 `.arc` 和 `.xp3` 都无表头**（每行一条，首行即第一个条目）——计数一律 `len(非空行)`，
  别套 `len(lines)-1`，否则每包差 1（2026-10-29 实测纠正：`兼职人妻` 实为 2562 条、`温泉蒸汽人妻` 3425 条，
  旧文档记的 2561/3424 就是这个口径错误的产物）。用 `toolbridge.garbro_list()` 拿条目数可避坑。。
- `.dat`（OP/ED）= ASF/WMV（头 GUID `30 26 b2 75…`）→ 复制改 `.wmv` 即可。
- `.pna` = PNAP 多帧容器 → `_pna_carve.py` carve（orchestrator 已接进 postprocess；
  `.pna` 与 `.tlg` 同列 `manifest.CONVERTIBLE`——**唯一出处**，48 个 `.pna` → 2640 帧，
  一个容器出多帧所以 postprocess 另记 `frames_out`，不能拿「输入文件数」当产出数）。
- `.mos` 内容就是 PNG（2026-10-30 实测 677/677 全部以 `89 50 4E 47 0D 0A 1A 0A` 开头），
  **必须列进 orchestrator 的 `IMG_EXT`**：否则它落进 `verify` 的 `nonmedia` 分支**被静默放过**、
  verify 照样报「失败 0」，交付清单凭空少验 677 张图（这是全链跑完才发现的口径漏洞）。
  该作图片口径 = 989 png + 677 mos + 2640 PNA 帧 = **4306**（前两项 Pillow 逐个过）；
  2026-10-30 全链复跑已确认 **4306/4306 零失败**——没列进 `IMG_EXT` 时是 3629/3629，
  677 张图凭空消失而失败数仍是 0（口径漏洞是无声的）。
  两个附带事实：`.mos` 的真实扩展名是**大写 `.MOS`**，且全在 `raw/<arc名>/` 子目录里
  （`raw/` 顶层只有 9 个 `.wmv` + 18 个子目录），清点必须 `rglob`。

### Yu-Ris（`あまねぇ` 实测，2026-10-26）
- 判定：`pac/*.ypf`（魔数 `YPF\0`）+ `yscfg.dat` + 存档 `.sd`（`YSSD`）+ `エンジン設定.exe`。
  **「YS」= Yu-Ris System，不是 Yaneura**。GARbro 不支持 YPF（真不支持，非假阴性）。
- 工具：**`_ypf_extract.py`**（自研；名字 XOR 单字节 key 靠 `name[-4]^'.'` 猜、名长 ^0xFF 查 4 张置换表、
  数据可选 zlib、YCG=两段 zlib 拼 BGRA）。
- arc_unpacker 0.11 备选坑：**`--out` 必须等号形式**（空格形式 DIR 变输入、递归扫 cwd）；
  大包（3484 条）疑似卡死 30 分钟无产出，小包（195 条）9 秒正常。
- 「源码即规格书」：卡壳时拉现成解码器源码（api.github.com）对照，比纯手撸 hexdump 快一个量级。

### CatSystem2（`甜蜜女友2+` 实测，2026-10-27；24bpp 补完 2026-10-28）
- 判定：`.int`（魔数 `KIF\0`）+ `__key__.dat` 种子 + cs2.exe。**索引与数据全部 Blowfish-ECB
  （GARbro 小端打包 ≡ 标准解密+输入/输出 4 字节半块反转）**，密钥来自包头 0x4C 种子驱动 MT。
- 文件名 = MT(main_key+i) 的 52 字母表轮换；main_key 无口令时用「k0 只有 256 种 → 逐条目反推
  k0 → 双约束并行爆破」拿下（本作 0x212C5F31，方法论见 verified-findings §16.2）。
- 图片 HG-3 家族（.hg3/.nm3/.gf3 及**任意扩展名**——引擎会二次混淆扩展名，必须按魔数扫描）；
  分节链从 0x14 起、ctl 位流 LSB-first。工具 `_hg3_tool.exe`（C#）。
- **24bpp 变体（107 个，2026-10-28 已解）**：ApplyDelta 的 4 等分位转置对 24bpp **同样适用**
  （GARbro 原版语义，RLE 输出均分 4 份重组后恰好 w*h*3）；**陷阱在自己写的 flip/落盘段**——
  row 必须按 `w * (bpp/8)` 算，硬编码 `w*4` 会越界崩。cptype/imgmode 节**全文件都有**（非 24bpp 特有），
  与失败无关，别被它带偏。教训：**移植解码器时先拉原版源码对拍语义，再改自己的代码**。
- 音频 OggS 明文（解密后），视频是 MPEG-PS（`00 00 01 ba`）。
- **orchestrator 链路（2026-10-30 接入，第 7 条）**：`stage_extract_cs2` 逐包（`raw/<包名>/`）
  + 总计两层对账；`_cs2_postprocess` ① 按**魔数**归一扩展名 ② HG-3 家族 → `png/`。
  - **扩展名不可信（二次轮换）**：实测 pcm_AA 的 3907 个 `OggS` 里只有 148 个恰好叫 `.ogg`
    （≈1/26，「按文件轮换、转到 0 才露真名」），其余散在几十个随机扩展名上；同一 base name 会成对
    出现（`.KCC` 是 OggS、`.HLx` 是 `LPD\0`）。**不按魔数归一，乱扩展名的媒体会落进
    `stage_verify` 的 `nonmedia` 被静默放过**（`.mos` 那次的翻版）。LPD 是 float32 数据文件
    （ffprobe 读不了），不是媒体、也不算缺失。
  - **交付口径 vs 对账口径要分开**：HG-3 转出的 PNG 才是交付物，raw 里那份中间产物记进
    `ctx.consumed` 并从 `final` 排除（`manifest.iter_final_files(..., exclude=)` / `counts(..., exclude=)`）
    ——**按路径排除**，因为扩展名被混淆；且 `raw` 仍然数着它，否则 53500 条对账就没了依据。
  - **同 stem 撞车**：`_hg3_tool` 落盘是 `Path.ChangeExtension('.png')`，`a.hg3` 与 `a.nm3` 互相覆盖
    → 期望张数要**去重后**算（历史解 4502、交付 4499），拿文件数当 `min_products` 会误判「产物不足」。
  - **内存**：最大的包 2.3 GB，`_cs2_int_extract.py` 已改成 **mmap + 32 MiB 分块解密**；
    进程被杀时不会再有「日志一行都没有」的情况（进度行 `flush=True`）。
  - **尾部 `fsize % 8` 字节在归档里本来就是明文**（2026-10-31 用 Ogg 页 CRC 判明）：打包器只加密
    整 8 字节块，落盘尾部的零头是原文，所以 `decipher_fast(bf, blob, fsize // 8 * 8)` + 尾部原样照抄是
    **正确**实现——别改成「解填充块再截断」。判据是**最后一个 Ogg 页的 CRC**（页里存的 CRC 是编码器按
    真实明文算的）：对 `pcm_DD/dd_02_ch08_019.OGG`（size 89899、`%8=3`）盘上变体算出 `0xfe9a5de8` 与
    页里存的一致，「全解后截断」变体算出 `0xc45b0d83` 不一致。**全量 23259 个 `.ogg` 最后一页 CRC 全部
    通过**（其中 20384 个 = 87.6% 大小不是 8 的整数倍）。→ 「最后一页 CRC」是 CS2 音频最廉价的地面真相
    校验，比 ffprobe 更硬（FFmpeg 会「尽力解码」，CRC 一字节都不能错）。
  - **护栏算错比不设护栏更坏**：HG-3 期望张数原来按**大小写敏感**去重算出 4501，而 `_hg3_tool` 落盘走
    NTFS、`X.png` 与 `x.png` 是同一文件（后写覆盖先写），实际 4499 —— 一次**完全正确**的解包被自己的
    护栏判成「产物不足」。判据必须按**平台语义**来。另：产物判定要看 **png/ 目录总量 == 期望**，
    不是「本轮增量 ≥ 期望」（`--reuse-raw` 复跑时增量天然是 0，按增量判会二次误报）。
  - **别用眼睛核对单行大字典**：orchestrator 把 75 键的 `by_ext` 挤在一行，我肉眼以为 `final` 里还有
    `.hg3`；逐键 diff 后真相是 `ONLY IN RAW: ['.hg3']`、`ONLY IN FINAL: ['.png']`。大字典一律逐键 diff。
  - **偶发 ffprobe 失败**：全量 verify 只在 `raw/pcm_DD/dd_02_ch08_019.OGG` 上失败一次，但该文件直接探
    rc=0、连探 5 次全过、最后一页 CRC 也对 → 是偶发。`ffprobe_ex()` 的重试正好覆盖。

### ExHIBIT / Retouch（`夕凪荘` 实测，2026-10-26）
- 判定：`ExHIBIT.JP`/`RESIDENT.JP` + `.gyu`（魔数 `GYU\x1a`）/ `.grp` / `.rld` + `moonstone.TTE`。
  MOONSTONE 系品牌。主逻辑在 resident.dll（引擎名 Retouch）。
- 图片 `.gyu`：**密钥在文件头**（Key≠0xFFFFFFFF 时 MT 交换 10 对字节去混淆），压缩分
  原样/GyuLZ(0x800)/LZSS 三种，8bpp 调色板 + 可选 alpha 平面，图自下而上。
  工具 `_gyu_tool.cs`（系统自带 csc 编译，零依赖）。**Gyu-LZ 位流与字节流共享游标**——移植大坑。
- 音频 `.grp`：TOC 就是同名小的 `AiFS` 魔数文件（res2000.grp），按 TOC 切 ogg，工具 `_grp_extract.py`。
- **BGM（res/s/m/*.ogg）加密未解**：只有头两页（3853B）被加密、页 2 起明文。已排除置换类/
  两套 MT 键流/RC4/ROR 函数 2^31 爆破；密钥材料大概率在配置键 `cluu`（settings.dat）/`GUID`/
  `DPMODE=0xC300`，解密器在 resident.dll 虚调用链后（见 verified-findings §15.3 侦察全档）。
- **orchestrator 链路（2026-10-30 接入，第 6 条）**：三条来源合一，期望总数 **11476** =
  `.gyu` 2184 + `.grp` 9185 + 散装 `.wav/.wmv` 107。
  ① `.gyu` → `tb.run_csharp("gyu", [游戏目录, raw/img], product_dir=…, min_products=2184)`（递归扫树、保持相对路径）；
  ② `.grp` → `_grp_extract.py <res> <raw/audio> --manifest …`，期望取 `grp.expected_counts(res)`（唯一出处）；
  ③ 散装媒体 → `raw/loose/<游戏相对路径>`。
  `res2000.grp` 是纯 TOC（`@0xC` 块数），`res2001/2002.grp` 头就是 `OggS`（裸 OGG 流）；
  `grp_arcs()` **必须把 AiFS 文件自己排除掉**，否则 TOC 会被当成「列不出的数据包」。
  **22 个加密 BGM 不纳入交付但必须显式报出**（`st.data["unsupported"]` → `source.unsupported`）；
  判据是**魔数不是路径**（`_exhibit_ogg_is_encrypted()` = `_head(p) != b"OggS"`，换一作路径会变、魔数不会）。
  实测 raw == final == 11476 文件 5139.6 MB（ogg 9185 / png 2184 / wav 106 / wmv 1），
  全链 930.3s 退出码 0（extract 93.66s、verify 828.57s）。
- **DLL 黑盒 oracle**：32 位编译 + `LoadLibraryEx(LOAD_WITH_ALTERED_SEARCH_PATH)`（必须 CharSet.Unicode，
  否则 CJK 路径 126）+ `GetDelegateForFunctionPointer` 调未导出内部函数——resident.dll 可在裸进程稳定调用。

### Electron / asar（SPITE 实测，2026-10-25）
- 判定：`app.asar` + Electron 壳。**别急着上 AsarKit/WinASAR**——自研 **`asar_tool.py`**（info/list/extract）
  直接解析索引更快更可控（asar 格式：16 字节头 + JSON 索引 + 连续数据区 + `.unpacked` 旁路）。
- **asar 里通常只有引擎代码**（dist/ + node_modules），媒体多半在外的 `data/` 目录、且可能**加密**。
- SPITE 的加密方案（逆向自 `dist-electron/services/media-crypto.cjs`，源码未混淆）：
  文件名 = sha256(原始路径).hex[:16]；密钥 = HKDF-SHA256(48 字节硬编码 IKM, salt, info="spite-media-chacha20:"+路径, 44B)；
  密文体 = 原始文件 ⊕ ChaCha20 流（RFC 8439，计数器 0 起，无认证标签）。**密钥依赖原始路径** → 必须先恢复路径映射。
- 路径恢复三板斧（`_spite_decrypt.py` + `_spite_bruteforce_paths.py` + `_spite_extract_pool.py`）：
  ① asar 文本里挖字面量引用（**引号无关**正则，Ink 剧本里路径是裸写的）；② 解密出的 `.atlas` 反哺贴图页路径；
  ③ minified 混淆池（`function X(){const t=[...]}` + `arr[i-K]`）→ 用已知锚点对（如 `/\.[a-z0-9]+$/i[f(3497)]` 必为 `"test"`）
  联立解出偏移 K，全池解码后再枚举「目录 × 名字 × 扩展名」。
- 覆盖率预期：257/365（70%）。**没有路径就永远解不开**（密钥依赖路径），剩余 108 个判定为未引用遗留资产——
  这是此类方案的天然上限，不是 bug。被引用的资产（含全部 45 个视频）100% 恢复。
- 另一个教训：minified JS 文本里**引号不配对**（正则字面量/单引号/模板串混用），朴素正则提取会错位；
  要拿池就用「反向行走 + 平衡扫描 + 自写 tokenizer」（见 `_spite_extract_pool.py`）。

## 归档与验收纪律（跨样本沉淀，十二个样本都验证过）

1. **先拿「地面真相」再动手** —— 归档的条目表/索引（GARbro `-l`、AssetStudio JSON 枚举、RPA 索引）是唯一权威。
   **不要预测工具行为**（坑 2）；**不要用未经校验的工具输出当真相**（工作约定）。
2. **计数必须对账到 0** —— 解包后逐扩展名与实际落盘数比对。三个样本都是靠这一步才发现真问题：
   `兼职人妻` 的 `.tlg` 506 vs 507（我统计时 `Select-Object -Skip 1` 吃掉首行）、
   Unity 的 `Video_WebM` 396 vs 应有的 115（282 个 jpg 被错分）、Ren'Py 的 118 个 webm 分布对不上（漏了别处的文件）。
   **"差不多" 等于没验。**
3. **验收看产物，不看退出码** —— 决策树 §6 四项判据：非空且无 0 字节 / 逐个可开（Pillow `verify()`、ffprobe）/ 与语义相符 / 数量合理。
   **工具退出码 0 毫无意义**（坑 4 就是 `exit=0` 却 0 文件）。
4. **数媒体要按扩展名，不要按容器内的流数** —— ffprobe 会把 mp3/图片的**内嵌封面**报成 `codec_type=video`，
   导致视频数虚高（本作 318 个"视频流"里 30 个是封面，真实文件是 288）。
5. **判定 patch 是「新增」还是「覆盖」→ 用索引求交集**，不要靠猜、也不要靠文件名相似度。
6. **解包前先看磁盘余量** —— 大样本解包后体积≈原包（RPA 是裸存），别把盘写满。
7. **中途临时产物最终要清掉，但结论必须先转写进文档** —— 否则下次会去找不存在的中间目录；
   另一方面，「修逻辑 + 从源归档重跑」永远优于写迁移脚本原地修数据（坑 5）。

## 工作约定

- **⭐ 跑多 GB 级样本前先看可用内存**（本机 13.8 GiB）。2026-10-30 实测：可用只剩 1.9 GiB 时，
  `_cs2_int_extract.py` 把 2.1 GB 的包整包 `read()` 进内存 → 进程被压死、**连 stdout 都丢了**
  （表现为 `rc=1` + 日志空白，看起来像代码 bug，其实是内存）。两条规矩：
  ① 大文件一律 **mmap / 流式**，不要 `read()` 整包；需要整段变换时**分块**（见 `_CHUNK`）；
  ② 别在别的重负载旁边开大任务，跑之前 `shutil.disk_usage` / 内存自检，跑完立刻收工。

- **事实先核实再断言**；未核实的明确标注「未核实」，不推测。链接/版本/许可证尤其。
- 仓库事实查 `api.github.com/repos/<owner>/<repo>`（`platform_search` 对本场景不可靠）。
- **用户的教程与实操结论优先于我的检索与推断。**
- **不要把未经校验的工具输出当作「地面真相」** —— 这是我犯过的最大错误（见坑 1）。
- **两次栽在同一个动作上：只看日志尾部就下结论。** 关键信息（`Found N files`、`Detected Unity version`、
  真实报错）**只在日志开头**。→ **先看开头，再看结尾，并数产物文件**。
- **PowerShell 调外部程序一律用调用符 `&`**（自动给含空格路径加引号），
  **不要用 `Start-Process -ArgumentList`** 传含空格的路径——它会把 `...\My Wife Wants...` 拆碎，
  制造出「工具失败」的假象（我自己就因此误判过一次，见 §8.2）。
- **⭐ 本环境的 Bash 工具会吃掉反斜杠转义**（`\\`、`\xNN` 都会被处理，heredoc 和 `-c` 内联代码都会中招）。
  → 含正则/转义的代码**一律先用 Write 写成 .py 文件再执行**，绝不内联。（2026-10-25 SPITE 期间实测踩坑）
- **⭐ 试跑/验证的产物一律落 `<本仓库>/_extracted/<游戏名>/`，不许散到盘根**（2026-10-30 用户提出）。
  我曾把 orchestrator 的 `--out` 手填成 `D:\_orch_advhd`、`D:\_orch_yuris`、`D:\_orch_rpgmv(2)`、
  `D:\_orch_kenmin`、`D:\_orch_swipe`，六份合计 **8.4 GiB 躺在 D 盘根目录**，用户先发现我才知道。
  当时的动机是对的（不用 Git-Bash `/tmp`——它会映射到随机 `dsh-win-bash-*` 目录、路径不可复现；
  也不把 GB 级产物塞进 git 仓库），**但落点选错了**：`_extracted/` 已进 `.gitignore`，
  `planner.py` 生成的提取计划里写死的就是这个路径，直接用它即可，不需要另找地方。
- **跑长任务（>几分钟）用 `python -u`，且别只盯 stdout**：stdout 被块缓冲，跑十分钟日志文件可能还是 0 字节；
  `orchestrator.py` 会实时写 `<输出目录>/_work/<阶段>.log`，看进度看那里。
- **⭐ 前台 shell 有 5 分钟硬上限**（2026-10-30 实测：`timeoutMs: 1500000` 仍在 **300000 ms** 被砍，
  报 `[timed out after 300000ms; the persistent shell was stopped]`、exit 124）→ **超过 5 分钟的活
  不能拿前台命令硬跑**（AdvHD 的 verify 阶段约 514s，正好卡死）。两条实测结论：
  ① 自己 `subprocess.Popen(..., creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP)` 起的
  「独立」进程**也逃不掉**——它仍在会话的进程树里被一起清掉，实测跑到 `verify [2000/11624]` 就消失，
  留下「raw/ 有、png/ 和 manifest.json 没有」的半截产物；
  ② **正解是用工具自带的 `run_in_background: true`**（harness 自己管的后台 job），拿 job id 后用
  `job_output` 收；长任务期间**不要反复轮询**同一条命令（用户 2026-10-30 明确要求「一次性搞了」）。

## 环境

- **shell**：`workspace-write` 下 pwsh 启动失败（`0xC0000142`，DSH win32 pwsh 沙盒缺陷）。用户已切到**完全权限**，pwsh 可直接运行。
  → **不要设置 `sandbox_permissions`**（approval 已禁用，带该参数会被自动拒绝）。根因见 `verified-findings.md` §6。
- **命令里别写 CJK 字面量**（GBK 控制台会乱码）→ 让 PowerShell/Python 自行从文件系统解析路径。
- `web_fetch`/`read_page` 会限流（Firecrawl 429）→ 改用 `api.github.com`。

### 外部工具位置（2026-10-29 逐一核实存在；均在 `D:\K\deepseek` 之外，勿搬）

| 工具 | 路径 |
|---|---|
| GARbro-Mod | `D:\K\galgame\GARbro\GARbro.Console.exe`、`GARbro.GUI.exe` |
| AssetStudio.CLI | `D:\K\galgame\unity\AssetStudio\AssetStudio.CLI.exe`（`unity_unpack.ps1 -Exe` 默认值、`_as_audio_collect2.py` 已指向此路径） |
| tlg2png | `D:\K\galgame\tlg2png\tlg2png.exe`（`_tlg2png_all.ps1 -Tool` 默认值） |
| KrkrExtract | `D:\K\galgame\krkr\krkr\`（**三件套已齐**：`KrkrExtract.Lite.exe` 534,016 B（2026-10-28 自 release 5.0.0.2 下载，SHA256 EB5D609B…CE89）+ `KrkrExtract.Core.dll` 11,237,376 B + `KrkrExtract.UI.Lite.dll` 129,024 B，版本配套已核实；CLI 注入用法与自动化见 verified-findings §17） |
| KrkrzExtract | `D:\K\galgame\krkr\krkrz\`（**主程序已就位**：`KrkrzExtract.exe` 176,128 B（v1.0.0.0，2026-10-28 用户放入）+ `KrkrzExtract.dll` 1,827,328 B。用于 KrkrExtract 报 `Unknown chunk in root chunk` 时兜底） |
| RPA-Explorer | `D:\K\galgame\rpa\RPA Explorer.exe` |
| AsarKit | `D:\K\galgame\asar\AsarKit.exe` |
| ffmpeg / ffprobe | `D:\ffmpeg\bin\`（`_verify_media.py`、`_verify_audio.py` 硬编码此路径） |
| 其他（FModel / umodel / quickbms / SpineViewer） | `D:\K\galgame\UE\` |
