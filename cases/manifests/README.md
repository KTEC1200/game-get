# 历史 manifest 存档

真实样本跑完一轮的 `manifest.json` 原件。用途：复盘「当时到底解出多少、验了多少」，
以及给 `cases/` 里的结论提供可追溯的证据。

## 清单

| 文件 | 引擎 | raw | final | ok | 来源 |
|---|---|---|---|---|---|
| `Toshiue Kanojo.json` | Artemis | 4008 | 4008 | true | `_extracted/Toshiue Kanojo/`（原件 `cases/_toshiue_manifest.json` 被 test_cases 引用，勿删） |
| `Happiness Double Room.json` | Unity | 3500 | 3500 | true | `_extracted/Happiness Double Room/` |
| `常識改変学園-製品版--frozen.json` | RPG Maker | 1585 | 1585 | true | 冻结包全链实测 |
| `krkr-feedback.json` | KiriKiri | 2562 | 2562 | true | 用户反馈验证 |
| `krkr_dynamic_carve_only.json` | KiriKiri | 0 | 0 | null | 空跑（验证 carve 分支） |
| `krkr_dynamic_natural.json` | KiriKiri | 0 | 0 | null | 空跑（验证自然窗口分支） |

后两份 `ok=null` 是当时那次运行没有收尾写 `ok`，不是失败——它们本来就是「只验证某一分支
能不能列出/提取」的空跑，产物 0 个是预期结果。

## 来历（2026-11-04 清理 `_extracted`）

`_extracted/` 累积到 **12 G**（6 个样本的产物 + 若干调试目录）。清理前把其中 6 个
`manifest.json` 复制出来存档，再删产物，最后把存档移进本目录（随仓库保存）。

**操作教训**：第一次把备份放在 `_extracted/manifests-archive/` —— 那是**被删除的目录内部**。
虽然执行顺序上先移走才幸免，但这是典型的「备份放进火场」错误。以后任何
「清空前留证据」的操作，备份必须落在目标目录之外。

## 影响

删产物不影响仓库（`_extracted/` 在 `.gitignore` 里），但删掉后**不能再 `--reuse-raw` 复跑**，
需要时只能重解：Happiness Double Room ≈ 十几分钟（Unity 音频补齐是大头），
常識改変学園 ≈ 2 分钟，Toshiue ≈ 几分钟。
