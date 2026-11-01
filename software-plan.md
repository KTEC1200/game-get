# Galgame 自动解包软件 —— 可执行分阶段方案（software-plan）

> 2026-10-28 沉淀。上游蓝图：`galgame-ai-unpack-workflow-plan.md`（许可证矩阵 / PyInstaller 坑 /
> 法律边界均已调研，本文不重复，只引用）。本文回答的是：**以仓库现有资产为起点，每阶段做什么、
> 交付什么、验收什么**。终局目标：一套可复用、可分发的 Windows 软件（个人自用/学习）。

## 0. 现状盘点（2026-10-28，12 个已跑通样本）

**已有能力（全部实测零失败）**：

| 引擎/格式 | 工具 | 语言/依赖 | 接口（已统一度） |
|---|---|---|---|
| 分派（10 引擎指纹） | `galgame_dispatch.py`（dry-run、纯规则、只读） | Python 标准库 | `<目录> [--json out]` ✅ |
| KiriKiri(静态) | GARbro.Console + `_tlg2png_all.ps1`/`_krkr_tlg_convert.py` | 外部 exe + Python | 部分 |
| **KiriKiri(加密)** | **`krkr_auto_extract.py`**（注入+Explorer 拖拽全自动） | Python 标准库 | `<游戏目录> [--out]` ✅ |
| Ren'Py | `rpa_tool.py` / `rpa_extract_organized.py` | Python 标准库 | `info/list/extract` ✅ |
| Unity | `unity_unpack.ps1` + `_as_audio_collect2.py` | PowerShell + AssetStudio CLI | 部分 |
| RPG Maker MV/MZ | `_rpgmv_decrypt.py` | Python 标准库 | 内置约定 |
| AdvHD | GARbro + `_pna_carve.py` | Python 标准库 | 部分 |
| Yu-Ris | `_ypf_extract.py` | Python 标准库 | 内置约定 |
| ExHIBIT | `_gyu_tool.cs/_exe` + `_grp_extract.py` | C#(csc) + Python | 部分 |
| CatSystem2 | `_cs2_int_extract.py` + `_hg3_tool.exe` | Python(py cryptodome) + C# | 内置约定 |
| Electron/asar | `asar_tool.py` + `_spite_decrypt.py` 系 | Python 标准库 | 内置约定 |
| 验收 | `_verify_media.py`（Pillow + ffprobe 白名单） | Python | `<目录> [--csv]` ✅ |
| 盘点 | `_scan_hy_inventory.py` | Python 标准库 | 只读 ✅ |

**关键缺口（对照终局）**：工具间是「约定」而非「契约」；无统一 manifest；无编排器；
Python/C#/PowerShell/外部 exe 混杂但无调用规范；GARbro/AssetStudio 等外部工具依赖硬编码路径。

## 1. 产品形态与架构（沿用蓝图 §4.1 的决策）

- **打包**：Python + PyInstaller `--onedir` → Inno Setup 单安装包（蓝图 §4.2-4.4 的坑已列全）。
- **架构**：编排器（CLI 优先）+ 引擎插件（每个引擎一个 extractor 模块）+ 外部工具桥（`resources/bin/`
  独立 exe，subprocess + argv 数组调用，启动前 `SetDllDirectoryW(None)`——蓝图 §4.3 高风险项）。
- **AI 层**：确定性管线先行；编排器暴露 **CLI + MCP**（蓝图 §6 阶段 1 就做，不等阶段 2）。
- **范围**（不变）：视频/音频/图片三类产出；**不做**回写/文本提取/翻译/分发。

## 2. 统一契约（阶段 1 的第一件事，一切模块向它靠）

```
工具调用约定（所有 extractor 统一）:
  <extractor> <input_path> <output_dir> [--work DIR] [--manifest out.json]

输出目录约定:
  <output_dir>/
    raw/          原始提取物（含 .tlg 等待转格式）
    png/          图片成品（tlg→png 等转换后）
    manifest.json 交付清单

manifest.json 契约（对账与验收的唯一地面真相）:
{
  "engine": "kirikiri-encrypted",
  "source": {"archives": [{"name": "data.xp3", "size": 6922, "entries": 2838}]},
  "counts":  {"by_ext": {".ogg": 1394, ".tlg": 865}, "total": 2838},
  "video":   {"present": false, "evidence": "index-entry-scan"},   // 坑3判据
  "postprocess": [{"tool": "tlg2png", "in": 865, "ok": 865, "fail": 0}],
  "verify":  {"image_ok": 1301, "image_fail": 0, "audio_ok": 1396, "audio_fail": 0,
              "audio_minutes": 148.8, "csv": "verify.csv"}
}
```

**⭐ counts 语义（2026-10-29 定案，修掉原计划的缺陷 #5）**：上面样例没区分「原始提取物」与「成品」，
实测 `高慢妻陥落！！` 时两者差很远（raw 2838 里含 865 个 .tlg，转完才有 1301 张图），
对账口径含糊就会两边都算不清。**定案 = counts 分三块，raw 与 final 各自独立对账**：

```jsonc
{
  "counts": {
    "raw":       {"by_ext": {".ogg": 1394, ".tlg": 865, ".png": 436}, "total": 2838},  // 提取器直接落盘的
    "final":     {"by_ext": {".ogg": 1394, ".png": 1301},              "total": 2695},  // 后处理完成后的交付物
    "converted": {".tlg": 865}                                                          // 被后处理消费掉的中间格式
  }
}
```

三条硬规矩：
1. **`raw` 是提取器的唯一自证**——必须等于封包条目数（`source.archives[].entries` 求和），差 1 都不许过。
2. **`final` 是交付口径**——报「图片多少张」时用 `final`（本例 1301 = png 436 + tlg 865 转出的），不是 raw 的 436。
3. **`converted` 解释 `raw.total != final.total`**——没有它，差额永远说不清是丢了还是转了。

**判定规则数据驱动**：`galgame_dispatch.py` 的指纹表移进 `rules/engines.json`
（签名/文件特征/判定次序），dispatch 与软件共用同一份（蓝图「规则要数据驱动」的落实）。

## 3. 分阶段路线（替换蓝图 §6 的占位内容，全部对准现有资产）

### 阶段 1：契约化 + 编排器（当前 → M1，预计 2-3 个工作日粒度）
1. ~~**manifest 契约落地**：给 4 个已统一接口的工具补 `--manifest`~~
   ✅ **全部 4 个已接（2026-10-30）**（`rpa_extract_organized.py`、`krkr_auto_extract.py`、
   `_rpgmv_decrypt.py`、`_ypf_extract.py`）。一律 `--manifest PATH`，不给就不写（不改变旧行为）。
   - ✅ **`krkr_auto_extract.py`（2026-10-29）**：走 `manifest.counts()`（raw/png 两目录形态），
     加密 xp3 无地面真相 → `reconcile.expected=None, diff=None, method="no-index-available"`
     （**明说没对账，不许用 diff=0 蒙混**）；`verify.verified=False` + note 指向 orchestrator/_verify_media。
   - ✅ **其余 3 个（2026-10-30）**：走新增的 **`manifest.counts_flat()`**（落盘即成品形态）。
     这三个工具的格式转换都做在**落盘之前**——`_rpgmv_decrypt.py` 的 `.rpgmvp` 落盘就叫 `.png`、
     `_ypf_extract.py` 的 `.ycg` 直接落 `.png`、RPA 条目本来就是裸存。
     磁盘上从不存在中间格式，所以 `raw == final`、`converted == {}`；
     硬造一个带 `.ycg`/`.rpgmvp` 的 raw 段就是**编数据**。转换明细（解密几个、YCG→PNG 几个、
     分类各多少）写进 `postprocess`，那才是它该待的地方。
   - 地面真相各自取：RPA = 索引**按名字去重**条目数（多段算一个文件）、YPF = 表内条目数、
     RPGMV = 工具自己数的 `decrypt + plain-copy`（每个候选文件必落且只落在这两类之一）；
     `--dry`（不落盘）时 `expected=None`，同样不许假装对过账。
   - 三份 manifest 都记 `source.out_root`（产物写到哪）——交付清单缺输出目录就没法交付。
   - 实测（2026-10-30，真实样本）：`gui_resource.rpa` 122/122 diff 0、`data.ypf` 195/195 diff 0、
     `常識改変学園` 7 个加密媒体 7/7 diff 0 且 `magic_fail_count=0`。
   - 测试：`tests/test_flat_manifest.py` 14 项（含「扁平工具不许套 CONVERTIBLE 悄悄抹掉 `.tlg`」
     和「必须记 out_root」两条护栏）。
2. **`galgame_dispatch.py` 升级**：~~指纹表外置 `rules/engines.json`~~ ✅ 已完成（2026-10-30，见 §5 第 5 项）；~~输出增加「建议 extractor + 参数」~~ ✅ 已完成（2026-10-30，`planner.py` + `--plan`/`--plan-json`，见 §5 第 6 项）。
3. ~~**`orchestrator.py`**~~ ✅ **已完成（2026-10-29）**：`detect → extract → postprocess → verify →
   manifest` 串成一条命令；每步产物与日志落 `--work`；对账不为 0 即停（纪律 2）。
   - 已接 **Ren'Py 与 KiriKiri 两条链路**（其余引擎判得出 → 退出码 2，明确「没链路」而不是假装成功）。
   - 退出码契约：`0` 全通过 / `1` 阶段失败或对账有差 / `2` 引擎判出但无链路 / `3` 未命中。
   - **实测**：`Swipe Right`（Ren'Py，4 包 2156 条目，退出码 0，图片 326/326、音频 1539/1539）；
     `兼职人妻`（KiriKiri 静态，2562 条目对账 0 差，507 个 tlg→png，图片 **902/902**、音频 1577/1577）。
   - 关键设计：地面真相一律取索引（Ren'Py 用 RPA 索引去重条目数、KiriKiri 用 GARbro 列表行数）；
     `--reuse-raw` **仍做对账**（跳步不等于跳验）；0 字节文件单列并用 1% 比例护栏兜底。
   - 测试 **143 项全绿**（`tests/test_orchestrator.py` 42 项契约 + `tests/test_orchestrator_smoke.py`
     真实样本冒烟；变异验证：改回「信退出码」→ rc 测试变红、去掉 0 字节护栏 → 2 项变红）。
   - 顺带修掉一个真缺陷：`_final_files()` 的标签在 Windows 嵌套路径下混用 `/` 与 `\`，
     已统一 `as_posix()`（manifest 要跨机器比对）。
4. ~~**外部工具桥** `toolbridge.py`~~ ✅ **已完成（2026-10-29）**：覆盖 GARbro / tlg2png / ffprobe /
   AssetStudio / KrkrExtract 五个。`python toolbridge.py check` 自检，`run(key, argv, product_dir=…)`
   统一调用；**成败一律由产物判定，退出码只作诊断**；路径按
   override → `TOOLBRIDGE_<KEY>` 环境变量 → `toolbridge.json` → 内置候选 → PATH 解析；
   子进程环境洗掉 `_MEI*`/`PYTHONHOME`/`PYTHONPATH` 并 `SetDllDirectoryW(None)`。
   坑 4（AssetStudio 逗号/竖线）已在 `assetstudio_export()` 里做成**参数级护栏**（直接抛 ValueError）。
   测试 101 项全绿（含「exit=0 但 0 产物必须判失败」的变异验证：故意改回信退出码 → 4 个测试变红）。
5. **验收**：拿 `高慢妻陥落！！`（加密 krkr）与 `Swipe Right`（Ren'Py）双样本回归，manifest 对账 0 差。
   > 原定第二样本 `My Best Deal` 已于磁盘消失（缺陷 #3），改用 `Swipe Right for Sugar Mama Sensei`
   > （四包 2156 条目，已双样本验证过通用性）。

### 阶段 2：引擎插件收编（M1 → M2）

> **进度（2026-10-30）**：orchestrator 已从 2 条链路扩到 **6 条**（Ren'Py / KiriKiri /
> **RPG Maker** / **Yu-Ris** / **AdvHD** / **ExHIBIT**），`IMPLEMENTED` 与 `EXTRACTORS` 双表对齐，
> 测试 **425 passed / 7 skipped**。AdvHD 顺带把 postprocess 从「只会 .tlg」改成按扩展名分派
> （`.pna` → `_pna_carve.carve()`，一个容器出多帧），`manifest.CONVERTIBLE` 成为待转格式的唯一出处。
> 六条链都用真实样本跑过退出码 0、对账 0 差（详见下方第 3 条）。
> **第 2 条（csc 工作流进 toolbridge）也已完成**——`_gyu_tool`/`_hg3_tool` 源码随包、
> `ensure_csharp()`/`run_csharp()` 现编复用，详见下方第 2 条。

1. 把剩余 extractor 逐个改造成契约插件（每个 ≤ 半天）：`_cs2_int_extract`（去 pycryptodome 硬依赖或
   随包带二进制）、`_ypf_extract`、`_pna_carve`、`asar_tool` 系、`_gyu_tool`、`_hg3_tool`
   （后两者的「C# 源码随包 + csc 运行时编译」已由第 2 条完成）。
2. ~~**csc 黑盒工作流产品化**~~ ✅ **已完成（2026-10-30）**：`_gyu_tool` / `_hg3_tool` **只带 `.cs`**，
   toolbridge 新增 `csc`（系统自带 Framework 编译器）/ `gyu` / `hg3` 三个注册项，
   以及 `build_csharp()` / `ensure_csharp()` / `run_csharp()`：
   - 编译产物**缓存在源码旁**，`exe mtime >= 源码 mtime` 就复用，源码变新或 `force=True` 才重编；
   - 失败抛 `CSharpBuildError`，消息带 **csc 路径 + 源码名 + 退出码 + stderr 原文**；
   - `run_csharp()` 复用 `run()` 的**产物判定**（`_run_exe()` 抽出执行体，判定口径只写一份）；
   - `check_all()` 认「源码在 + csc 在」为可用（`buildable=True`），
     新增 `python toolbridge.py csharp` 看编译状态（源码/exe/是否过期/编译器）。
   19 项新测试（14 单测 + 5 冒烟，含**用真 csc 编 hello-world 并运行**）+ 3 轮变异验证全部 CAUGHT。
3. **验收**：12 样本全量回归（每个引擎至少一个样本走 orchestrator 全链，manifest 入案例库）。
   - ✅ 已跑通 7/9 引擎：Ren'Py（Swipe Right 2156 条）、KiriKiri（兼职人妻 2562 条 + 507 tlg→png）、
     **RPG Maker（常識改変学園 1585 条，图片 719/719、音频 866/866、视频 0/0）**、
     **Yu-Ris（あまねぇ 8201 条，图片 3484/3484、音频 4522/4522、视频 0/0，527.7 分钟）**、
     **AdvHD（ラブラブお痴験バイト性活 9032 条 + 48 个 `.pna`→2640 帧，图片 989+677+2640=4306、
     音频 7031/7031、视频 9/9，媒体 857.4 分钟）**、
     **ExHIBIT（夕凪荘的S级的女朋友们 11476 条 = `.gyu` 2184 + `.grp` 9185 + 散装 107，
     图片 2184/2184、音频 9291/9291、视频 1/1，媒体 1072.0 分钟，全链 930.3s 退出码 0；
     22 个加密 BGM 显式排除并在 `source.unsupported` 报出）**。
   - ⏳️ 剩 1 个引擎待接：Tyrano-Electron（目前只有 _fixtures/tyrano_game，没有真实样本）。
   - **Unity（第 8 条链路，2026-11-01）**：_unity_extract.py 用 AssetStudio JSON 枚举作地面真相
     （唯一出处）、Convert 分批导出（按 Texture2D/Sprite/AudioClip 三类）、FSB5 容器音频多轮累积
     （_as_audio_collect2.py，单次只出 ~30%）。侦察实测：Texture2D JSON 460 / Convert 455
     （差 5 个引用型资产）、Sprite 322/322 完美、AudioClip JSON 1168 / 单次 Convert 377（32%，需多轮）。
     全量跑进行中（raw 已有 1437 个文件 = 777 png + 660 wav）。
   - CatSystem2（第 7 条链路，2026-10-30）：`stage_extract_cs2` 逐包 + 总计两层对账、
     `_cs2_postprocess` 按魔数归一扩展名 + HG-3→png/（`consumed` 按路径排除、raw 不动）；
     **真实样本验证到 4 包**（bgm/config/fes/image00 = 1351/1351 零失败，含最大单包 image00 1163 条），
     **全量 51 包 / 53500 条已跑通并拿到绿色 manifest**（2026-11-01 复跑，`--reuse-raw`）：`extract` 36.59s 53500 个文件对账 0 差（逐包 51/51）、`postprocess` 178.35s HG-3 4502 → png/ 4499 张
      （同 stem 撞车 3）、`verify` 2008.81s 图片 4499/4499、**音频 23259/23259、视频 10/10、失败 0**、
      媒体 2291.0 分钟，`manifest.json` `ok=true`，全链 2261.6s 退出码 0。（上一次 `--reuse-raw` 跑出的「1 个偶发 ffprobe 失败」这次被 `ffprobe_ex` 的重试吸收掉了。）
      音频语料用**最后一个 Ogg 页 CRC** 全量校验过（23259/23259 通过，87.6% 的文件大小不是 8 的整数倍，
      证明「尾部零头在归档里就是明文」这条实现是对的）。
4. **案例库**：`cases/`（JSON per 样本：指纹、判定、耗时、失败与修复）——蓝图 2.7 自愈闭环的地基。

> **⭐ 接链路的正确姿势（2026-10-30 沉淀，接剩下 3 个引擎时照做）**
> - **地面真相只写一份**。RPG Maker 的候选筛选抽成 `_rpgmv_decrypt.iter_candidates()`、
>   Yu-Ris 的表解析抽成 `_ypf_extract.read_index()`，orchestrator 直接调它们。
>   各写一套必然漂移——一边算 7 个候选、另一边写 6 个文件，谁也说不清谁错。
> - **`EXTRACTORS` 存函数名不存函数对象**。存对象会在 import 时把引用焊死，
>   monkeypatch 模块属性就失效（实测 3 个 `run()` 退出码测试全红）。
> - **`--reuse-raw` 跳过解包但不许跳过对账**。KiriKiri 侧踩过一次（`expected` 变 None，
>   明明能列出条目却把「没对账」当结果），两条新链路都带 `reuse` 对账测试。
> - **双表必须同步**：`IMPLEMENTED`（orchestrator）与 `IMPLEMENTED_CHAINS`（planner）不一致时，
>   `test_implemented_flag_matches_orchestrator` 会红——这是设计好的防漂移护栏，别绕过它改测试。
> - **验收口径本身也要防漏**：AdvHD 的 `.mos` 是「内容就是 PNG、扩展名不认识」，没进 `IMG_EXT` 时
>   verify 把它归进 `nonmedia` **静默放过**、还照样报「失败 0」——**验收器漏掉一类文件是无声的**。
>   接新引擎时对着该引擎的扩展名清单逐条问「它现在会落进哪个分支」，别只看失败数是不是 0。
> - **有意排除的东西要显式报出，并且要进 manifest**。ExHIBIT 有 22 个加密 BGM 解不开（§15.3），
>   处理方式是「不复制进 raw + 记 `st.data["unsupported"]` + 写进 detail + 经 `source.unsupported`
>   落进 manifest」而不是「复制进去让 verify 报 22 个失败」——交付物的定义是**能用的**媒体。
>   两条路都诚实，但前者能让链路绿灯着把话说清楚；关键是**不许静默丢**（同 `.mos` 的教训）。
> - **超过 5 分钟的验证跑不进前台 shell**（本环境硬上限 300000 ms，`DETACHED_PROCESS` 也逃不掉）：
>   用 `run_in_background: true` 起后台 job 再 `job_output` 收；实在跑不完全链，退而求其次是
>   **对单条口径做定向实测**（如 677 个 `.mos` 直接过一遍 Pillow 全绿），并在报告里写明
>   这是定向验证、不是全链结论。


### 阶段 3：Windows 软件壳（M2 → M3）

> **进度（2026-11-01）：第 1 条冒烟已跑完，结论全在 `verified-findings.md` §19。**
> 环境 Python 3.14.6 + PyInstaller 6.22.3，onedir **66.3 MiB / 182 文件 / 冷启动 0.67s**。
> **能用的**：冻结后调原生 exe（ffprobe）与 .NET exe（GARbro 2562 条）都正常；CJK 路径正常；
> Pillow / numpy / pycryptodome 都进包可用；业务代码 in-process 直接调函数可行（`iter_candidates` 1585 条）。
> **必须改的（三条，按优先级）**：
> ① ~~**7 处 `subprocess.run([sys.executable, "<脚本>.py"])` 必须改 in-process**~~
>    ✅ **已完成（2026-11-02，见 verified-findings §19.2 第 1 条）**：7 兄弟脚本统一
>    `main(argv=None) -> int`，orchestrator 走 `_run_sibling(mod, argv)` + 顶部静态 import，
>    AST 护栏禁 `sys.executable`/`subprocess` 回潮，496 passed。
>    不选「随包带私有 python.exe」：多一份运行时、还要管 stdlib 路径。
> ② ~~**数据文件必须显式 `--add-data`**~~ ✅ **已完成（2026-11-02）**：清单唯一出处 **`build_exe.py`**
>    （rules/、cases/、两个 .cs、`_uia_item_rect.ps1`、可选 toolbridge.json）；冻结实测见 §19.2 第 2 条——
>    真样本全链 rc=0（1585 对账 0 差 + 验收 0 失败）。
> ③ ~~子进程环境~~ ✅ **实质已在 toolbridge**（`_sanitize_env`/`_clear_dll_dir` 覆盖全部 4 个
>    子进程出口），冻结全链 ffprobe 866/866 实证有效（§19.2 第 3 条）。
> 附带：动态 `importlib.import_module` 的模块 PyInstaller 静态分析看不到——orchestrator 已改为
>    全部顶部静态 import（必修第 1 条），产品包不需要 --hidden-import。

1. ~~PyInstaller onedir 冒烟：冻结 + subprocess 调外部 exe~~ ✅ **已完成（2026-11-01，见 §19）**。
2. ~~兄弟脚本 in-process~~ ✅ **已完成（2026-11-02，见 §19.2 第 1 条）**。
3. ~~打包数据文件清单 + 子进程环境卫生~~ ✅ **已完成（2026-11-02，见 §19.2 第 2、3 条）**；
   `build_exe.py` 可复跑，冻结全链真样本实证通过。
4. Inno Setup 打包；杀软误报应对文档（蓝图 §4.5，社区实践非官方结论）。
5. GUI 最小化：先 CLI + 简单托盘/表单（拖一个目录进去 → 出 manifest 报告），不抢在管线稳之前。

### 阶段 4：AI 兜底（M3 后，按蓝图 §2.4 阶梯）
- A1（规则检索增强）→ A2（错误日志归因）→ A3（参数求解）逐个上，每个都用案例库做回归；
- A4（生成解析器）最后，且必须先有蓝图 §2.6 沙箱。
- 触发面已收敛：现在规则覆盖率 12 引擎 + 加密 krkr 全自动，AI 只接「真正没见过的」。

## 4. 风险与依赖（引用蓝图编号，防散失）

| 风险 | 处置 | 出处 |
|---|---|---|
| KrkrExtract GPL v3 vs API license=null | 只做「独立进程聚合」使用；分发时附其源码链接与许可文本 | 蓝图 §5.2 / §7.1 |
| FreeMote 禁商用（CC BY-NC-SA） | E-mote 分支暂不纳入软件默认能力 | 蓝图 §7.3 |
| GARbro 需 .NET 4.6+ | 安装器检测提示 | 蓝图 §4.4 |
| PyInstaller 冻结环境继承给子进程 | 阶段 1 §3.5 + 阶段 3 §3.1 双重验证 | 蓝图 §4.3 |
| 大样本磁盘占用（解包≈原包） | orchestrator 启动前查盘（纪律 6 已实测） | AGENTS.md 纪律 6 |
| CJK 路径（引擎层） | krkr 系 stage 必须 ASCII——已沉淀进 krkr_auto_extract.py | verified-findings §17.2 |
| 跨进程 WM_DROPFILES 不可行 | 加密 krkr 自动化已解决（Explorer 拖拽法） | verified-findings §17.3 |

## 5. 立即可做的下一步（按序）

> **2026-10-29 更新**：原第 1 项（`rules/engines.json` 抽取）**不是纯重构**，已后置——
> 指纹散在 `scan()` 的 17 个 `hit()` 调用里，还依赖 5 个有副作用的探测函数
> （`find_unity_version()` 解析二进制、`biggest_files()`、`count_subdir_games()`、`demojibake()`、
> `garbro_probe()` 调 subprocess）。外置 = 把 `scan()` 重写成「规则表 + 解释器」，
> 属**有回归风险的重构**，不该排在新增工作前面。调整后的顺序：

1. ~~`toolbridge.py` + 五工具接入~~ ✅ **已完成（2026-10-29）**，101 项测试全绿。
2. ~~`orchestrator.py` 最小闭环~~ ✅ **已完成（2026-10-29）**，见 §3 阶段 1 第 6 条。
3. ~~manifest 契约在 `krkr_auto_extract.py` 试点~~ ✅ **已完成（2026-10-29）**：
   先把契约抽成独立模块 **`manifest.py`**（唯一实现，供 orchestrator 与 krkr_auto_extract 共用
   ——两处各写一遍必然漂移，而 manifest 是交付清单，漂移就等于两个工具对「交付了多少」说法不一致），
   再让 `krkr_auto_extract.py` 走 `write_manifest()` 产出三段式 manifest。
   顺带修掉三个真实缺陷：
   - **`toolbridge.tlg2png()` 幂等盲点**：`--reuse-raw` 复跑时 png/ 已有上次成品，
     「产物增量 ≥ 1」判据看到增量 0 → 把 507 张图全判成失败。修法 = 调工具前先验
     `dst` 是否已是合法 PNG，是则跳过并 ok=True。「本次没新增」≠「失败」，可能只是**已经干过了**。
   - **`--reuse-raw` 跳过对账**：复跑时 extract 直接 return，没填 `expected_total`，
     manifest 变成 `期望 None vs 落盘 2562 (diff=None)`。修法 = 跳过解包但仍用索引算地面真相并对账
     （加密 xp3 列不出条目时 expected 才保持 None，并标 `no-index-available`）。
   - **`krkr_auto_extract.STAGE_ROOT` 指向已废弃的 zcode 路径** → 改为脚本同目录 `_krkr_stage`。
   测试 176 passed / 3 skipped（新增 `tests/test_manifest.py` 19 项、`tests/test_krkr_manifest.py` 7 项、
   toolbridge 幂等护栏 2 项、reuse 对账护栏 3 项）。
4. ~~**其余 3 个工具补 `--manifest`**~~ ✅ **已完成（2026-10-30）**：
   `rpa_extract_organized.py` / `_rpgmv_decrypt.py` / `_ypf_extract.py` 全部接上，
   新增 `manifest.counts_flat()`（「落盘即成品」形态：raw == final、converted 为空）。
   三个真实样本实测 diff 0：`gui_resource.rpa` 122/122、`data.ypf` 195/195、
   `常識改変学園` 7 个加密媒体 7/7。测试 190 passed / 3 skipped
   （新增 `tests/test_flat_manifest.py` 14 项）。
5. ~~`rules/engines.json` 抽取~~ ✅ **已完成（2026-10-30）**：
   落地为 `rules/__init__.py`（解释器）+ `rules/engines.json`（9 个引擎的权重/证据文案/魔数/扩展名）。
   **不是「把表搬出去」，而是「规则表 + 解释器」**——原 `scan()` 的 17 个 `hit()` 调用散在
   if/elif 分支里，重写成数据后由 `evaluate()` 统一求值。
   三条不变量（测试锁着）：`gate` 表达嵌套（父信号没触发子信号不计分）、
   `alternatives` 表达 `elif`（只让第一个成立的计分，否则 MZ+MV 双计分）、
   `for_each` 逐项计分（多个 `*_Data` 目录各算一次）。
   有副作用的探测（读二进制/起子进程/stat）**不进 JSON**，改为具名探针注入，
   规则文件里用 `probes` 声明——`rules.validate()` 静态查「用了没声明 / 声明了没用」。
   **零漂移验证**：`python tests/make_golden.py --check` → 6 fixture + 11 真实样本全部一致；
   测试 255 passed / 3 skipped（新增 `tests/test_rules.py` 53 项，含 6 项 `validate()` 变异验证）。
   顺带修掉 `garbro_probe()` 的**差一错误**（`len(lines)-1` → `len(lines)`；
   GARbro 列表无表头，实测 2562 条，与 `toolbridge.garbro_list()` 口径统一，加了护栏测试）。
6. ~~`galgame_dispatch.py` 输出增加「建议 extractor + 参数」~~ ✅ **已完成（2026-10-30）**：
   落地为 **`planner.py`**（判定 → 提取计划），由 `dispatch --plan` / `--plan-json FILE` 驱动。
   职责分离的理由：dispatch 管**判定**（要稳定到能进 golden 逐字比对），planner 管**分派**
   （随工具与参数频繁变动）——混在一起，改个参数名就得重刷 golden。
   三条硬规矩（测试锁着）：① 只写「怎么跑」不写「跑不跑得通」（`implemented` 只表示 orchestrator
   有没有接这条链，能不能解一律实跑定——坑 2）；② 参数只从实测事实拼（归档取自 `Report.archives`，
   绝不猜包名、猜哪个加密）；③ **`argv` 是列表不是字符串**（`Swipe Right for Sugar Mama Sensei`
   这种含空格路径用 shell 字符串拼必然出错），`cmdline` 只给人复制、不参与执行。
   `Report.archives` **故意不放进 facts**——facts 是判定证据快照（golden 逐字比对），archives 是拼
   命令行的原料，混在一起每次新增一条计划就冲掉 golden。
   9 个 builder 全覆盖 `ADVICE` 的 9 个引擎；已接 orchestrator 的引擎（Ren'Py / KiriKiri）给
   「一条命令走完全链」+ 单工具兜底 `extras`，其余 7 个标「orchestrator 未接，需单独跑」。
   产物一律落 `<仓库>/_extracted/<游戏名>/`（**不写进游戏目录**：会污染原包，且加密 KiriKiri 链
   要 stage 纯 ASCII 副本，混在一起分不清谁产生的）。
   **测试 278 passed / 3 skipped**（新增 `tests/test_planner.py` 23 项，含 3 轮变异验证）；
   `make_golden.py --check` 零漂移。顺带修掉 `_gyu_tool.exe` 写成裸文件名（靠 PATH 查找，PATH 里没有）。
