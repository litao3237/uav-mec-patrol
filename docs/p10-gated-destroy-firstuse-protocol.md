# P10 队列时限触发的原关键任务删除回退：S109–S112 首用验证冻结协议

**冻结时间：** 2026-10-12；这四个物理场景 S109/S110/S111/S112 在 P0–P10 开发中没有被用来挑选或调整本方法。P9 S105–S108 的 5/40（原方法）→8/40（queue-chain/queue-task）及其2/1条丢失原有成功的事实构成P10研发依据；新P10代码和触发规则在本次S109–S112结果生成、下载或查看前冻结。GitHub Actions: [本轮首用 P10](https://github.com/litao3237/uav-mec-patrol/actions/workflows/p10-fresh-queue-gated-clock.yml)。

## 五个预注册方案（严格一换一 destroy）

| 代码标识 | 具体任务deadline必要违反时 | 无具体任务deadline必要违反时 |
|---|---|---|
| original | 原 `critical_task_removal` | 原 `critical_task_removal` |
| queue_chain | FIFO/EDF deadline及强制前驱任务 | 旧P9无回退排序 |
| queue_guarded_task | FIFO/EDF必要违约任务 | **完全回退原critical** |
| queue_guarded_chain | FIFO/EDF必要违约链及强制前驱 | **完全回退原critical** |
| workload_guarded | 同规模负载/期限任务 | **完全回退原critical** |

条件回退使用 `deadline_violators==0`，并非任何任务优化数学上保证已严格可行。原critical使用**同一个 RNG对象**、`DestroyConfig`、`rng.choice`、原算子名称/插入配对，所有其它destroy与repair、原`ScreenedProxyObjectiveEvaluator`、RRT、连续资源Stage1/Stage2全部不变。已有单元测试验证无必要任务期限越界时，在相同RNG初态下产生的destroy结构字节哈希与原critical完全相同。

## 全流程实验口径

4个独立场景 × 5个不同单因素配对压力（含正常负载） × 嵌套算法seed149/150 = 40个物理压力/随机重复**配对**。共5个方案、每个方案原B-ALNS探索时钟上限6s，原ESI精英时钟上限2s，原 ALNS `time_scaled_rrt`按真实运行时钟冷却，且每组使用完全相同的**只读**P7 FIFO/EDF→P2 CPU→P5 BW/CPU必要判定观察器，成本计入搜索阶段预算。

每次报告：
- 访问不同离散D数、通过FIFO/EDF和BW/CPU必要条件数；
- B终点Stage1严格合格，最终ESI的 Stage1和Stage2 **均严格合格**数；
- ESI严格双合格的**同源配对**能耗；不拿各方案仅成功样本的均值直接相减；
- 原探索计时、精英计时、原真实两阶段资源完整重新求解/独立残差验收成本与**真实全流程总时间**。探索+精英目标时钟固定，不等于全流程绝对硬停6+2s（正在执行的CVX和最终验收不可强行抢占），故同预算结论应按这一限制表达；
- 所有原严格失败、`infeasible`、`optimal_inaccurate`、例外都保存。没有求解器状态即可证明原**全物理实例**整体无解的主张。

## 预先明确的研究决策

成功证据必须同时具备：时间/计算耦合修复的真实严格两阶段成功超过原方法，不损失更多原可行解，且比相同触发回退的负载对照更有作用；真实完整成本不能严重增加。 `queue_guarded_chain` 如果生成更多 necessary-passing 但没有实际严格通过，**不算实质提升**。如果新场景没有支持原有成功保护，应公开负面结果并转向原 `_options_for_task` 插入与 `_finish_repair` 任务接触调整的核心时序一致性。

**创新边界：** ALNS时间窗算子/解档案/前驱关键路径已有成熟领域研究；若需投稿，必须说明本项目多UAV本地FIFO、远端 EDF+跨batch FIFO、资源共享以及任务采集/接触路径的特殊耦合，不能把“deadline-aware destroy”描述为普适首创。只完成4个空间场景没有足够统计推广度。正式 `develop` 算法和原论文基准仍保持不变。
