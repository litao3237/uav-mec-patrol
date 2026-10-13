# P19 多任务修复顺序 vs 最后任务插入位置：完整同源反事实归因报告

**执行完成:** [GitHub Actions #38357446482](https://github.com/litao3237/uav-mec-patrol/actions/runs/38357446482)，2026-10-13，`validate`、S89/S91/S93/S95/S96五个已观察空间场景、`summarize`全部成功，无程序错误。原冻结B-ALNS源物理D及完整实验SHA保持一致；在`experiment/p19-repair-order-causal-diagnostic`分支研究，**从未改变`develop`的原插入函数、原MEC重构、原Stage1/Stage2、物理模型和正式论文数据**。

## 一、样本与干预口径

6个冻结原B-ALNS源D，每个原本用`critical_task_removal`删除同样的 **12/80个任务**，随后分别按原 `cheapest_insertion_repair`和`regret2_insertion_repair`重演。测试五种固定完整D：
1. `original_order`：旧函数的真实任务恢复顺序、对每步都选旧`_options_for_task`排名第一的插入位置，最后执行**原`_finish_repair`**；
2. `reverse_order`：同一12任务删除集合、按原任务顺序完全反转，但每个任务插入位置**仍用原评分函数的rank1**；
3. `deadline_pressure_order`：按任务workload/deadline及最早期限等静态排序，每任务插入位置仍用原rank1；
4. `original_order_last_rank2`：全部旧任务顺序和前11个old-rank1，只最后任务改old-rank2；
5. `original_order_last_rank3`：全部旧任务顺序和前11个old-rank1，只最后任务改old-rank3。

因此顺序干预**会间接改变各任务位置**（因为早插任务改变后面插入排名），但没有更改任何一个候选位置的评分规则。全部60个完整D经原MEC重构和原FIFO/EDF乐观必要检查。**仅`original_order`、`reverse_order`两组执行额外原Stage1+Stage2数值/独立残差资格审计，每组12次，共24个严格后验检查。**其它三组**没有**严格Stage1/Stage2结果，不得说其严格成功0。所有这些试验均为先前多次观察过的研发数据，**不是新独立holdout或全ALNS等墙钟对照**。

原旧 `cheapest` / `regret2` 在同被删集合下，每一个old-original重放结构SHA与原生产repair输出完全相同，单元验证与CI都通过。

## 二、真实结果：改变恢复顺序未解决完整资源可行性问题

| 冻结12个源D×repair配对 | 原顺序 | 反转顺序 | 静态deadline压力排序 | 原顺序末项rank2 | 原顺序末项rank3 |
|---|---:|---:|---:|---:|---:|
| 完整结构数 | 12 | 12 | 12 | 12 | 12 |
| FIFO/EDF必要时间约束通过 | **2/12** | **2/12** | **2/12** | **1/12** | **0/12** |
| 原Stage1+Stage2严格通过 | **0/12** | **0/12** | **未测试** | **未测试** | **未测试** |
| 旧完整Stage1求解状态 | 7×`infeasible_precheck`、5×`infeasible` | 同样7×`infeasible_precheck`、5×`infeasible` | 未测试 | 未测试 | 未测试 |

**注意因果边界：** 不能把反向插入顺序 0/12 严格合格结果推广成“所有任务顺序不重要”；它只证伪了**固定已失败源D、固定同一12任务集合、仅反转恢复顺序就应稳定修好**的假设。两个FIFO/EDF必要检查通过D，都来自 **S93/baseline/A129 的旧cheapest、regret2**：原/反转/deadline都保持通过，但原Stage1都是`infeasible`，说明**时间必要通过并不能代表真正MEC联合资源严格可行**。在其他10个完整D上，原和反转均不能越过时间必要线。

细分，反转对必要违约理由总数：12个配对中仅 **1项变少、1项变多、10项不变**。其中：
- S91/compute×1.5/A128，`cheapest`反转令理由数2→3，`regret2`反转反而3→2；两者仍不符合必要条件，也都严格资源失败。
- `deadline_pressure_order`只有1项理由数变坏、11项不变，没有新增任何必要通过D。
- `last_rank2`共有1项改善必要理由、3项变坏、8项不变；`last_rank3`共有1项改善、4项变坏、7项不变；两者在两个原来必要通过的正常S93/B源中至少损失一个，说明盲目改变最后任务位置可能破坏正确结构。

## 三、目前更准确的研究判断

1. **拒绝把P19“反转任务恢复顺序”或“所有任务按workload/deadline排序”视为独立有效的新ALNS改进。** 本轮没有一例新的严格Stage1/2合格结构、没有新的FIFO/EDF必要合格来源，且顺序反转影响方向因repair而异。
2. **真正ALNS的多任务修复不仅顺序，也受`_finish_repair`集中重卸载、原`ProxyScore`与完整共享BW/CPU限制影响。** S93正常源已通过乐观队列必要测试却Stage1仍`infeasible`，所以只靠时限先后排序难解决更深一层资源冲突。
3. **P17/P18的改进证据仍应保留但不能夸大。** P17首用K80 S121–S124有3个严格配对新增/0损失；P18首用K30/K50/K80 S125–S128总72配对只有K50增加1例，没有稳定跨规模优势；P19也不支持“仅修复顺序是主瓶颈”的强结论。可按已检验机制继续做更严格路径-接触联合构造研究，但**避免再次重排仅最后一项任务、加大TopK和昂贵额外完整MEC预览**。
4. **下一步应该先比较在修复后的完整固定D中，FIFO/EDF必要失败 vs共享BW/CPU资源必要失败 vs真实严格Stage1失败各占多少，**特别针对两个S93 baseline已有队列必要通过却Stage1 `infeasible`的具体多UAV-MEC资源约束，检查已有P5联合必要条件和是否有真实严格Stage1+Stage2阳性对照。如果压力场景确实整体很紧，应当用真实构造性可行解作问题难度参考；全局乐观必要条件通过不能作为整体可行证明。
5. 如果要提出新机制，先研究**一次完整多任务`destroy→restore→MEC builder`中实际哪一个接触批次、计算/通信资源瓶颈被引入或消除**，不要直接把本轮“12次没有成功”报告成任务恢复顺序不重要或原插入函数有bug。原产出论文不修改。

### 完整复核材料
- 可信完整摘要：Actions artifact `p19-order-summary-38357446482`。
- 每个场景源结构/任务序列/原MEC重构前后所有队列指标及真实原Stage1状态：对应`p19-order-S89/S91/S93/S95/S96-38357446482` 五个Artifacts。
- 开发分支`experiment/p19-repair-order-causal-diagnostic`新增 `experiments/run_p19_repair_order_factorial.py`、`tests/test_p19_repair_order_factorial.py`、`.github/workflows/p19-repair-order-factorial.yml`。原`develop`保持不变。
