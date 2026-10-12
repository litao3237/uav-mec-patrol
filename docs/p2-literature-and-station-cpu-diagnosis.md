# P2 文献调研与原模型 MEC 共享 CPU 必要可行性诊断（2026-10-12）

## 研究边界与原始证据

本报告不是新算法完成证明，**只针对原仓库已有严格 Stage-1/Stage-2 资源模型 P1-R**。原始 `develop` SHA `0bdf3a26d4c042e13f96f84977261ffdd33cfc89` 不变。

- P1 原始 S85–S88 场景和原始 B/ESI 结果：Actions [38134649545](https://github.com/litao3237/uav-mec-patrol/actions/runs/38134649545)。
- P1 已严格求解前8候选及真实弹性约束：Actions [38196891133](https://github.com/litao3237/uav-mec-patrol/actions/runs/38196891133)。
- **本轮新资源必要界实验：Actions [38199060117](https://github.com/litao3237/uav-mec-patrol/actions/runs/38199060117)，四场景、测试及汇总全部成功**，无异常。
- 本轮分支 `experiment/p2-station-cpu-share-diagnostics`，所有新诊断和对照不合入 `develop`；论文能耗、可行率和冻结图表无修改。
- 四个场景 S85–S88 **此前已经用于算法开发，不是独立新样本**。算法随机种子 A125/A126 嵌套在场景之内，不能算独立场景。

## 一、相关研究的真实覆盖面（按研究问题，不按算子名字排序）

| 优先级 | 论文、期刊与年 | DOI | 与本研究相关的方法；不可直接宣称的创新 |
|---|---|---|---|
| 高 | Sun et al., *Multi-Objective Optimization for Multi-UAV-Assisted Mobile Edge Computing*, IEEE TMC, 2024 | `10.1109/TMC.2024.3446819` | 离散卸载、计算资源和 UAV 轨迹已经通过分块、KKT、SCA 等方式联合优化；单纯“联合轨迹/卸载/资源”并不是新意。其飞行平台/MEC组织不同，不能无模型差异比较。 |
| 高 | Kasapidis et al., *A unified solution framework for flexible job shop scheduling problems with multiple resource constraints*, EJOR, 2025 | `10.1016/j.ejor.2024.08.010` | ALNS-CP 融合多种资源约束和记忆引导搜索；“资源感知/反馈式 ALNS”的抽象思想已有研究。 |
| 高 | Avgerinos et al., *One Benders cut to rule all schedules in the neighbourhood*, EJOR, 2025 | `10.1016/j.ejor.2024.12.009` | 利用子问题/局部邻域结构构造割；若本项目宣称 Benders cut，必须给出严格证明而非仅数值松弛诊断。 |
| 高 | *More powerful energetic reasoning for the cumulative scheduling problem*, Discrete Applied Mathematics, 2026 | `10.1016/j.dam.2025.07.016` | 基于资源需求/时间窗的必要可行性检验是成熟方向；本项目的 CPU 份额界只可能作为 **冻结 UAV–MEC 虚拟队列的模型特化引理**，不是首次提出 energetic reasoning。 |
| 中 | Wang et al., *Solving the Integrated-tasks satellite range scheduling problem: A surrogate-assisted variable neighborhood search approach*, TRC, 2025 | `10.1016/j.trc.2025.105312` | 代理模型筛选候选、再调用昂贵评价的思想已有先例；不能把“简单学习排序”包装成全新机制。 |
| 中 | Xu et al., *ALNS-DR: An Optimization Method for Large-Scale Task Offloading in UAV-Assisted Edge Computing*, CSCWD, 2025 | `10.1109/CSCWD64889.2025.11033293` | UAV-assisted edge computing 中已有 ALNS 算法；仅调整算子权重缺乏区别。 |
| 中 | *Logic-based Benders decomposition for bi-objective parallel machine selection and job scheduling with release dates and resource consumption*, COR, 2024 | `10.1016/j.cor.2023.106528` | 资源可行性与离散调度的分解反馈已有方法；严格 cut 与启发式候选评分要区分。 |

文献检索不足以证明世界范围内“从未有人研究某组合”；投稿前需要基于真实模型逐项对比队列建模、CPU时变性、候选排序与可行性证明，不得仅凭名称判断创新性。

## 二、新的模型特有必要可行性界：静态 (UAV,MEC) CPU 份额

在**本论文冻结的**连续 Stage-1 资源模型内，同一个 (UAV,MEC) 虚拟队列 `p=(u,e)` 使用在整个求解时域内固定的 CPU 配额 `F_p`（GHz）；一个 MEC e 的所有活跃虚拟队列必须满足 `Σ_{p∈P_e} F_p≤F_e^max`。同一对内接触批次按 FIFO，批次内任务按 EDF。

对虚拟队列 p：
- `a_p^LB` = 首批次在**独占最大带宽**且此前接触也以乐观最短上传完成的最早 MEC 到达下界；
- 将该对所有批次中的任务按强制 FIFO/EDF 展平为 `i=1,…`，`W_i` 为 Gcycles；
- 任何任务 i 的真实完成不可能早于 `a_p^LB + (Σ_{j≤i}W_j)/F_p`；
- 要满足原始真实截止时间 `d_i`，**必要** `F_p ≥ (Σ_{j≤i}W_j)/(d_i-a_p^LB)`，若分母≤0而前缀工作量>0则此固定离散结构必然不合格；
- 于是 `F_p^LB=max_i (Σ_{j≤i}W_j)/(d_i-a_p^LB)`，且对每个 MEC 站点 `Σ_{p∈P_e}max(F_p^LB, 10^{-4}) ≤ F_e^max` 必须成立。

> **数学安全性的关键假设：** 站点 CPU 分配 `F_{u,e}` 在 P1-R 中是整段时域的静态数值，而非可以任意时间复用的动态 CPU 调度。如果以后改变该建模约束，禁止继续把该界当成安全剪枝。推导也依赖原始的强制 FIFO/EDF 队列和 release=0 口径。

方法只需计算固定结构的最早乐观首批到达与强制前缀工作量，**不求解 CVX**。它是必要条件，不是充分条件，且不能解决 Stage-2 能耗优化；数学上已有 energetic reasoning 的思想，因此创新性需由和本问题其它耦合机制结合后的方法价值和实测收益决定。

## 三、实际 GitHub Actions 验证结果（新实验，并非推测）

实验程序依次恢复原始物理实例、原始离散结构及 SHA-256，与已经归档的严格求解结果比对。判定只用本次新必要条件，不修改任何原程序。

### 冻结 B-ALNS/ESI 输出，共80条记录

| 指标 | 结果 |
|---|---:|
| 全部原方法记录 | 80 |
| 去重的 (物理实例,固定离散结构) | **48** |
| 原 Stage-1 严格合格（记录/去重结构） | **30 / 23** |
| 原 Stage-1 未严格合格（记录/去重结构） | **50 / 25** |
| 旧 FIFO/EDF 乐观队列必要检查直接拒绝 | **48 / 24** |
| 新 CPU 份额必要界直接拒绝 | **46 / 23** |
| 新界相比旧 FIFO/EDF **独立额外拒绝** | **2 条记录 / 1 个不同结构** |
| **误拒绝原 Stage-1 严格合格控制** | **0 / 30（去重0/23）** |

两个原方法记录指向同一个额外检出的结构：**S88、计算密度×1.5、A126**，此前 Stage-1 状态 `optimal_inaccurate`、旧队列必要检查通过；新界显示 **E1 最小 CPU 份额需求达到原 CPU 上限的1.111598倍**。本结果来自*数学必要条件*的违反，而不是简单把 `optimal_inaccurate` 当作数学不可行的证据。该特定 D 不能用原静态 CPU 资源满足所有强制时序/期限，**不等于整个 UAV 规划实例无解**。

对这批源输出，旧必要检查与新必要界的并集覆盖了全部50条尚未严格合格记录，但这仅是**研发样本的描述性观察，绝不代表这两项条件构成充分条件**。

### 之前已用原 Stage-1 严格评价的42个候选

原 P1 资源审计 Action `38196891133` 留下的 22 个失败源 D 中，只包含42个**进入旧乐观队列预检通过并已实际调用 Stage-1 的候选**，不是22个独立场景，也不是原搜索全部候选。

| 真实求解状态 | 个数 | 新 CPU 必要界提前排除 |
|---|---:|---:|
| Stage-1 严格合格 | 13 | **0** |
| Stage-1 不合格 | 29 | **23** |
| **合计** | **42** | **23** |

旧队列必要检查对上述42个全部放行（它们原本就是旧方法的候选短名单）。新界**可以对其中23个已知严格求解失败候选给出无需调用 CVX 的模型必要性拒绝**，占本次29个失败候选约79.3%；余下6个旧 Stage-1 失败候选也通过新界，说明**通过仍远不是可行证明**。

此处所有42个候选都通过 SHA-256 与原已求解资源档案一一配对；全部四个场景代码/归档检查成功，未发生异常。结果不能用作新样本上的无偏分类准确率，也不能声称真正节省了23次在线 CVX 调用——后者必须把新界嵌入候选选择后**重新运行正式同预算实验**才能检验。

### 关键样例：S85、计算×1.5、A125

| 旧代理排名 | 候选类别 | E1 最小 CPU 配额总需求/物理容量 | 旧 Stage-1 |
|---:|---|---:|---|
| 1 | 新建接触 | 0.99693 | infeasible（新必要界仍放行） |
| 2 | 新建接触 | **1.01187** | infeasible（新必要界正确排除） |
| 3 | 新建接触 | **1.01371** | infeasible（新必要界正确排除） |
| 4 | 新建接触 | 0.99358 | infeasible（新必要界仍放行） |
| 5 | 复用接触 | **0.92852** | optimal，最终两阶段合格 |
| 6–8 | 复用接触 | 0.89689–0.92861 | 全部Stage-1及两阶段合格 |

此例四个最优代理分数完全相同。仅靠旧算子名称字典序，前3个都无法通过原 Stage-1；新 CPU 必要界安全排除其中2个，令后排严格合格候选有机会进入原始3个 CVX名额。然而某些 `min_CPU_ratio<1` 的候选仍不可行，说明还存在批次具体时序、通信资源或者其它约束的耦合压力，**不能用一个 CPU 指标直接替代完整连续资源求解**。

## 四、科研决定

这轮诊断把此前“共享 MEC 竞争可能造成候选失效”的假设升级成了**一个可证明、成本很低、能在现有代码中直接检验的必要条件**，但其数学原理并非首创。下一道验证门槛是：

1. 同样源 D、同样邻域、最多3次严格 Stage-1 候选检查，比较旧候选选择与“CPU 必要界安全筛掉 + 补入下一候选”的恢复数、CPU时间、候选精确调用次数。
2. 在新未观察场景中检查必要界不排除任何严格合格解（更大规模和不同空间/MEC 拓扑），再比较整个 B-ALNS/ESI 端到端相同墙钟预算的严格合格率和条件总 UAV 能耗。
3. 如果简单安全剪枝的收益不足，优先寻找**共享静态 CPU 份额压力的冲突任务/虚拟队列**如何指导实际跨 UAV/MEC/接触的离散修复，而非继续给普通搜索加深度。
4. 同等 CVX调用上限不等于同等完整运行时间；必须报告筛选自身开销、无法抢占的求解器超时、所有不合格实例。

**现阶段不得修改论文 ESI-ALNS 的主结论，或直接声称提出了更优且普遍有效的新算法。**
