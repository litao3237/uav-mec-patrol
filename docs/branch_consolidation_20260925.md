# develop 分支整合记录（2026-09-25）

## 整理范围与保留原则

按项目要求，将GitHub各分支的最新成果和进展汇总到`develop`，最终仅保留该分支并设为默认分支。使用真正的merge保留历史，不以覆盖文件或删除未合并提交代替整合。本地`_work/`和`paper_figures/revisions/`原有未跟踪论文资料保持原状，Word/PDF未在本轮修改。

清理前共13个远端分支，无活动Actions作业，无分支保护或ruleset；旧PR #1为develop→main。整合完成后该PR已关闭，未向main反向合并。推送成功并再次确认各分支头均包含于develop后，使用精确SHA租约和原子推送删除其余12个远端分支。本地main及过期远端引用也已清理。

## 最终核验

- GitHub及本地均仅保留`develop`；GitHub默认分支与`origin/HEAD`均为`develop`。
- 合并提交`31dd81411628d33a1e3c34d7c55a7c8c5a84ef97`已推送，13个原分支头的历史均保留。
- [远端完整测试](https://github.com/litao3237/uav-mec-patrol/actions/runs/36099931404)通过。
- [远端论文数据校验](https://github.com/litao3237/uav-mec-patrol/actions/runs/36099931432)通过。
- 未触发新实验矩阵；本地未跟踪论文资料仍保留。

## 合并内容及冲突处理

- `b45c657`：合入多规模消融末端分支，带入v1–v7算法验证、共享检查点、正式8×3绘图数据、消融结果及历史结论。
- `970b97b`：合入修正后的多规模五方法基线runner和验证工作流。
- `3209168`：合入独立的v5预算检查点实验；同时保留动态预留版本与检查点版本，保留各自回归测试。
- 两个v5实现原先均导出`BudgetAwareTerminalFirstConfig/Result`。动态预留版本继续使用原公共名称，检查点版本通过`CheckpointBudgetAwareTerminalFirstConfig/Result`导出；其runner改用对应配置，模块内类名与运行函数均保留。
- README保留最新六规模、等预算和补充实验方案，修正“v7下一步尚未实现”等过期入口；现有session/fork与终点成本分析可以复用，完整快照、严格时间轨迹及全约束残差仍属待补项。
- 原始ESI-ALNS仍为论文方法；v5–v7保持实验用途，保留无一致等时间优势的负结果。未启动新增正式实验或更改历史数据值。
- 已整合的旧实验工作流移除指向待删除分支的push事件，保留workflow_dispatch。常规测试及论文数据校验使用develop。

## 提交完整性

以下清理前分支头已逐一通过`git merge-base --is-ancestor <SHA> develop`，全部可由develop追溯。完整机器可读清单见[JSON](branch_consolidation_20260925.json)。

| 原分支 | 清理前提交 | develop包含情况 |
|---|---|---|
| `develop` | `8157b3fc9bee751d5190ccc8f4e9a69197ac251f` | 已包含 |
| `experiment/adaptive-esi-stability` | `b26f361d5a6ca197839631ef48f4930f0f60101f` | 已包含 |
| `experiment/budget-aware-terminal-first-v5` | `f7fa7f09331edc806a961684fc987d6d5314fd3e` | 已包含 |
| `experiment/budget-utilization-v5` | `a4374a52598bc2fe426bd0990eca2c0bde6decb7` | 已包含 |
| `experiment/continuous-esi-stability-v2` | `b9e1e847676d65ce27ef4fdfc1f4dbb78f2be41c` | 已包含 |
| `experiment/energy-guided-esi-v6` | `a662238d1a70941f78c85a6a8aaedf4c10e64f8a` | 已包含 |
| `experiment/multiscale-ablation-expansion` | `936739fedadafba6d8710a55788b2f56070d1aec` | 已包含 |
| `experiment/multiscale-baseline-corrected` | `2d2fd7960a14b9c8fd9c0f13abd285ecb7477e46` | 已包含 |
| `experiment/multiscale-baseline-expansion` | `5d0961f6960d898d5aad7d69665b661160ed57c9` | 已包含 |
| `experiment/paired-checkpoint-fork-v7` | `139ec2e3dc0bd467f963dba633cd5066f1a71194` | 已包含 |
| `experiment/terminal-first-stability-v4` | `28a819b8dd4c013d40a4278bdb365de98c7b95d4` | 已包含 |
| `experiment/terminal-recovery-stability-v3` | `f94b1e7da06a690036c9c72d5180353c98e3e434` | 已包含 |
| `main` | `84f09160961e97abd2c79e751b4975f35b4a5749` | 已包含 |

## 验证与恢复

- 合并后的完整pytest：80项通过，包括两套v5控制逻辑及v7 checkpoint/fork测试；本地Python 3.14.5。
- 论文数据接口109项汇总校验通过，K50/K80共同配对数24/21且better/equal/worse为14/10/0与17/4/0；正式数据快照哈希检查通过。
- 全部Python源文件语法检查及src/experiments/tests的ruff F821检查通过；全部工作流YAML可解析且jobs内容与合并前一致。本次推送仅匹配tests和Paper Figure Data Validation两个工作流。
- 清理前Git完整bundle已保存并通过`git bundle verify`：`_work/branch_consolidation_20260925/before-consolidation.bundle`。备份留在本地，不纳入仓库。
- 各历史分支均可用上述SHA重建；删除分支名称不删除合并历史中的算法、实验结果或文档。
