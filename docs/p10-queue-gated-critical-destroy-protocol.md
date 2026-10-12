# P10：队列证书触发的 ALNS critical 删除算子——仅在必要期限违约时介入

**研究起点：** 原P9冻结独立新场景S105–S108首次验证中，原 `ESI` 严格 Stage1+Stage2 合格 5/40，`queue_task` 和 `queue_chain` 均8/40；`workload_control` 同原5/40。两种有时限依据的算子均新增合格，但也损失已存在的原严格成功（`queue_task` 新增5丢2；`queue_chain` 新增4丢1），配对合格能耗正负混杂，尚不能宣称论文优势。本轮只研究**为什么重排原ALNS某个已安全状态仍会发生已有成功的丢失**。

## 事前方法

原P9在当前D已经**没有任何具体任务的FIFO/EDF期限必要超额**时，`queue_chain` 所有任务直观超额都是0，任务排序最终退化到计算工作量和任务字符串，而原 `critical_task_removal` 采用其保守代理的真实QoS压力。这可能让原ALNS离开已经接近严格可行的结构区。

P10 由此提出**无自适应经验系数**的“必要冲突触发/原行为回退”：
- 如果任意具体任务满足 `t_i^{FIFO/EDF LB}>d_i+10^{-4}s`，允许选择 `queue_task`、`queue_chain` 或同等目标数的 `workload_control`；
- 否则（包括 FIFO/EDF 整体已通过，或只剩平均时延/巡检周期等 aggregate 必要违反但无可追踪具体任务期限链），同一个 destroy 算子槽**原封不动调用** `critical_task_removal(current,rng,config)`，保持原 `rng.choice` 次数/随机参数和 `DestroyConfig.count/pool`；
- 保持其余两个随机删除/路径区间删除、全部 `cheapest`/`regret2` 和MEC修复、RRT/roulette、原标量 `ScreenedProxyObjectiveEvaluator`、Stage1/Stage2及资源残差全部不变。未添加额外ALNS操作或CVX允许预算。

## 五个真正可比的臂

| 方法 | 处于任务期限必要违约时 | 处于没有任务期限必要违约时 |
|---|---|---|
| `original` | 原proxy-critical | 原proxy-critical |
| `queue_chain`（P9对照） | FIFO/EDF违约任务+强制前驱 | 原P9任务零值排序（**无回退**） |
| `queue_guarded_task` | 直接期限必要违约任务 | **原critical完全回退** |
| `queue_guarded_chain` | 期限必要违约+强制前驱 | **原critical完全回退** |
| `workload_guarded` | 工作量/期限比高的任务 | **相同原critical回退** |

新策略的可证伪主张是：`queue_guarded_chain` 应在已明显队列必要违反的状态提供结构修复，同时相较无保护的P9减少**必要合格状态被工作量零分排序破坏**的风险。等规模工作量负对照 `workload_guarded` 是检验“仅保护原算子就有用”还是“链式时间约束的任务选择有特殊价值”。

## 实验计划和停止门槛

1. 在此前已检查过的7个 P9/P7 K80 案例（6高压、1正常可行）使用相同100次ALNS探索、同初始D/随机种子、全部原真实资源/Stage2验收，诊断 `original` 端点 SHA256 再次7/7复现；**这只匹配迭代数，完整运行时间必须单独报告**。
2. 独立代码单元验证：对于无具体期限任务违约的D，三个guarded方法调用原critical后的结构哈希与原critical在**相同随机数生成器状态**下完全相同，不能只是“原则上回退”；对于真实队列任务期限失败，仍移除原配置q个任务。
3. 如果预实验能保留P9有价值的两例高压恢复，同时不丢正常严格成功且计算代价合理，冻结实现在 **从未使用过** 的S109–S112、2个嵌套算法种子上执行原搜索每臂6秒+原ESI精英期2秒的同表严格Stage1+Stage2。必须报告**原B搜索、真实 Stage1/2完整验收、全部实际wall-clock**，不能把“原 ALNS 搜索预算相同”直接称为整个算法严格硬墙钟相同。
4. 即使出现可行率正向，只有4个独立空间场景远不够发表统计优越性；需要在更多空间场景和原论文不同K尺度、常规负载/高压负载与ESI真实能耗中检验，并考虑与基本时间窗ALNS/资源约束邻域研究的先例对比。
5. **停止门槛：** 如果P10依然损失原严格成功，或在未见场景相比P9没有改善/能耗更差，不要堆叠“更强的前驱权重”，转而做反事实诊断旧 `_options_for_task` 逐任务时间乐观及 `_finish_repair` 的任务重卸载MEC修复与 FIFO/EDF强制序之间的不一致。

**安全性边界：** 队列预检是固定离散D的必要条件，若通过绝不表示原Stage1真实资源可行，回退也不是数学上保证保持整个ALNS最终成功；真正严格判定完全由原 Stage1+Stage2 双阶段资格决定。所有代码与结果均留在实验分支，不修改 `develop`。
