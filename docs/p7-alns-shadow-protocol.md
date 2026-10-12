# P7：原 B-ALNS 搜索轨迹的严格复现与中间候选可行性漏失诊断

**日期:** 2026-10-12；本轮不是新的候选算子开发，不更改原始 `develop`、B/ESI 的随机种子、100次迭代、RRT 接受准则或任何 P1-R/Stage1/Stage2 原模型。

## 研究动机：为何之前的后验修复方向频繁失败？

原实现 `src/uav_mec/algorithms/alns/hybrid.py` 当 B-ALNS 探索 `best_solution` 的原资源Stage1结果不合格，会直接**停止精英结构强化阶段**，即使搜索过程其他中间 D 曾短暂具备可行潜力。既有 P0–P6b 的探索几乎都试图在**原 B 搜索全部停止后**，从一个失败终点 D 用预算有限的 beam+邻域修复，未测量初始搜索**到底有没有访问过任何通过队列/共享CPU/联合BW-CPU三个必要层次的中间结构**。

这是研究方向的关键可证伪问题：A) 若B期间绝大部分 D 仍不能通过必要条件，后验筛选/精英强化并无可用候选；应该改搜索初始结构或采集/接触时序机制。B) 若搜索期间已有通过多个必要条件的 D，却被代理能耗/单标量1e9惩罚或 RRT 选择过程丢失，可优先研究在线**可行候选档案/精英状态选择**，避免继续堆加新邻域。

## 核心协议

`experiments/run_p7_alns_shadow_archive.py` 把原 `ScreenedProxyObjectiveEvaluator` 封装成**只观察不反馈**的 sidecar:
- 先调用、并原样返回原 scalar objective（包括原不合格惩罚和原Stage1求解）；不改变 RNG、ALNS、destroy/repair、RRT 参数、任意执行模式。
- 对每个首次出现的 D，在**返回原 objective 之外**记录：旧 task-only necessary precheck、FIFO/EDF queue-aware precheck、P2 静态CPU份额必要条件、P5 48格通信-计算联合必要条件；所有快照均去重、根据原搜索代理值排序，分层每组最多保留10个候选。
- B-ALNS 原初始离散解完全按照冻结 `build_greedy_initial_solution`→`build_mec_assisted_initial_solution` 生成，100次 ALNS 原程序 `run_uav_mec_alns`，算法种子与原 B 方法对齐。
- 关键复现门槛：**重放最后 `best_solution` 的 SHA-256 必须与原已归档 B-ALNS 原 SHA-256 全面一致**；一旦不一致实验必须失败，不能解释新日志为原始搜索的历史轨迹。
- 原 B 重放完成后才对分层保存的排名前三候选使用额外 Stage1 CVX + 严格Stage2验收。此处是**研究附加后验算力**，不能冒充原 B-ALNS 在同预算下本来已经完成了严格求解。
- `shadow_observation_wall_s` 独立计费，不能声称插桩不影响真实运行时间；仅有决策轨迹和原目标标量声称同一。
- 7个已观察的分层代表性case：S89/deadline×0.9/A128，S91/compute×1.5/A128，S93/compute×1.5/A130，S93/baseline/A129（原严格成功对照），S94/compute×1.5/A129，S95/compute×2/A130，S96/deadline×0.9/A130。**全部场景以前已经观察，不是新独立测试**。

## 判读准则

| 原搜索中间候选情况 | 应研究什么 |
|---|---|
| 从未出现通过原队列必要检查的中间D | 先修改 ALNS 生成/访问顺序、启动解和时限引导搜索，不宜追加CVX配额 |
| 有 queue-passing，但全部共享CPU/联合BW-CPU必要拒绝 | 需能改变整个MEC接触批次/虚拟对资源分配的动作，候选后处理只能安全剪枝 |
| 有大量 joint-passing，但额外Stage1仍失败 | 提示原联合界依旧不充分；下一步关注完整时序/电池/通信连续冲突 |
| 有额外严格Stage1+Stage2合格的中间D，但原 B endpoint 不合格 | 提出有实际数据依据的**在搜索过程中保留少量候选状态、且不改变原接受准则的在线档案**，随后才设计严格等wall预算对照；这是不同于 P0–P6b 的新算法机制假设 |

**数学与创新边界：** ALNS精英/档案搜索不新颖，须明确“利用 UAV-MEC 连续耦合必要条件保留多个具有资源多样性的离散结构”所需计算成本与对原算法的实际性能；有数据支持前不可以宣称恢复率或能耗收益，更不能把附加Stage1检查隐藏成无成本步骤。所有保留候选依然需通过原Stage1/Stage2与完整残差独立资格判定。
