# 创新证据补充实验资料

本目录持久保留2026-09-25实验的原始归档、来源哈希和分析结果。执行状态与解释见[实验记录](../../docs/innovation_execution_results.md)，预算、冻结规则和残差容差见[执行协议](../../docs/innovation_execution_protocol.md)。论文主算法的历史数据与新增机制诊断分别使用。

## 数据分组

| 文件 | 含义 |
|---|---|
| `archives/matched.zip`、`v7_dev.zip`、`v7_unseen.zip` | 原有实验原始制品，按冻结ID与SHA256下载 |
| `existing_evidence_summary.json` | 本地重分析：96组matched、各48组v7开发/unseen、54次dense |
| `archives/existing_run36122779851.zip`及对应summary/provenance | Actions远端重分析，summary与本地逐字段一致 |
| `archives/pilot_v1_run36121819858.zip`、`pilot_v1_summary.json` | v1先导，保留固定路径探索退化，不用于正式证据 |
| `archives/pilot_v2_run36122774290.zip`及对应summary/provenance | 修正共同探索入口后的v2先导18次运行，仅作实现验收 |
| `archives/formal_v2_run36123390700.zip`及对应summary/provenance | v2正式矩阵144次运行，已完成并归档 |
| `formal_tables/` | 从正式快照导出的逐运行与配对解释指标；`stage_metrics.csv`同时包含合格标志和未合格原值 |

各ZIP保持下载原字节，provenance记录Actions运行、制品元数据及SHA256。解压出的`parts/mechanism_K*_S*.json`包含完整实例/结构、两阶段变量、独立残差及日志，不只是汇总均值。先导和正式文件绝不池化；数值失败记录不能删除或填零。

`manifest.json`记录本目录各文件与后处理脚本的SHA256。仓库文本统一为LF换行后生成清单，由`.gitattributes`保证跨平台检出一致；原始ZIP不进行任何字节转换。

## 复核与导出

将正式ZIP解压至工作目录后执行：

```powershell
uv run python experiments/aggregate_innovation_mechanism.py --input-dir <解压目录>/parts --phase formal --output <工作目录>/rechecked_summary.json
uv run python experiments/export_innovation_tables.py --input-dir <解压目录>/parts --phase formal --output-dir <工作目录>/tables
```

复核不运行搜索或资源优化。原始文件SHA256严格比对；跨平台离线浮点复算仅允许协议所列的末位差异，状态与合格标志必须相同。保存与最早重建时序分别审计，解释指标中的时延差采用后者。

主能耗配对只用双方Stage-1原状态与两套残差均合格的样本；Stage-2/Stage-1比较须两阶段均合格。统计先在同一场景内平均算法种子，再对场景等权汇总。表中24次运行来自8场景×3算法重复，不是24个独立场景。没有合格配对的比较保持缺失，不能解释为零差异。

正式协议的`full`是三臂共享诊断搜索的完整自由度臂，并非历史ESI-ALNS主比较结果。候选冻结过滤的拒绝成本、实际耗时和搜索结构数用于界定解释范围。B重分析仍保留无稳定等追加时间优势的结果。
