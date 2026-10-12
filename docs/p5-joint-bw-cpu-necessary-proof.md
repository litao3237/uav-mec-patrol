# P5 通信带宽—批次到达—静态 MEC CPU 份额联合必要可行性条件

> 研发证明与冻结协议。原始 `develop` 不动；P5 只测试先前已经检查过的 P1 S85–S88、P4 S89–S92 严格 CVX 结果。**不得把其中任何组当成新独立 holdout，也不能据此改变论文曲线或声称新主算法最优。**

## 1. 为什么单独的两个必要界可能一起漏判？

P4 [完整离线数值诊断](https://github.com/litao3237/uav-mec-patrol/blob/experiment/p4-postbound-resource-attribution/docs/p4-postbound-resource-findings.md) 已在原固定 D、原严格 P1-R 中表明：某候选在 FIFO/EDF 乐观下界与静态 MEC CPU 份额下界各自通过后，仍可能因为带宽/到达时序/计算的**联合**耦合无法完成真实任务截止约束。分开假设“每个虚拟队列独占 MEC 全带宽”，即使把其最低 CPU 相加，也不代表一组真实带宽分配能同时满足所有队列。

## 2. 精确模型假设与数学推导

原 P1-R 中同一 MEC e 的 (UAV,MEC) 虚拟对 p 拥有**整段时间固定** `b_p` MHz、`F_p` GHz，且
`Σ_p b_p≤B_e`、`Σ_p F_p≤C_e`、`b_p≥0.001 MHz`、`F_p≥0.0001 GHz`。同一 p 的 MEC 批次按照 UAV 接触顺序 FIFO，批次内部按照任务截止时间 EDF，原始任务 `release_s=0`，上传最短时长 `τ_v≥D_v/R_v(b_p)`，其中 `R_v(b)=b log₂(1+γ_v/b)`。不同 MEC 站点之前接触的上传以各自**独占全站带宽**给出安全乐观下界。

设对固定队列 p、第 h 次 MEC 接触：
- `A_h^LB(b)` 是从路径飞行/采集基础接触到达开始，加上之前所有真实上传的**乐观最短时间**与当前上传时长，得到 MEC 本批最早可能开始计算的时间；该队列自己的上传按照同一静态 b 计算，而之前其它 MEC 接触均用其对应站点的全部带宽。
- `W_{h:i}` 是从该 p 的 h 次批次开始、按 FIFO/EDF 到目标任务 i 完成以前**强制串行**的 Gcycles 工作量。
- `d_i` 是任务 i 的真实完成期限。

原 Stage1 的 `batch_arrival`、`batch_fifo`、`batch_complete`、`mec_task_complete` 保证，对于任何在 i 之前/所在批次的 h，

```math
c_i \ge A_h^{LB}(b_p)+\frac{W_{h:i}}{F_p}.
```

于是必要条件

```math
F_p \ge L_p(b_p):= \max\left(10^{-4},\;\max_{h\preceq i}\frac{W_{h:i}}{d_i+\epsilon_t-A_h^{LB}(b_p)}\right).
```

如果 `d_i+ε_t≤A_h^LB` 且 `W_{h:i}>0`，定义 `L_p=∞`。微小的正 `ε_t=10^{-4}s` 对时窗更加乐观；拒绝另加 `10^{-4}GHz` 容量数值容差。这样数值浮点近临界不会轻易误拒。

因为 Shannon 速率 `R_v(b)` 随 b 单调增加，上传时间随 b 单调减小，因此 **`L_p(b)` 对 b 单调不增**。

> 注意这依赖本论文 **(UAV,MEC) 对的静态 F/b 配额** 和真正强制的 EDF/FIFO。若未来改成按时间片动态分配 CPU 或带宽，必须重新证明，不允许将该界当通用剪枝。

## 3. 避免“近似优化导致误拒”的安全离散动态规划

为了不在每个候选上再运行一个昂贵的 CVX 子问题，按 MEC e 全带宽 `B_e` 等宽划分 N 个网格，`δ=B_e/N`。

对于任一**真实可行带宽份额** `b_p`，定义向上取整的网格端点 `\bar b_p=δ\lceil b_p/δ\rceil≥b_p`，它满足：
- 每个 `\bar b_p≤B_e`；
- `Σ\bar b_p < B_e + mδ`，其中 m 为该站点活跃虚拟对数；
- 因单调性，`L_p(\bar b_p)≤L_p(b_p)≤F_p`。

因此对**放宽到 `B_e+mδ` 的网格总带宽约束**，用有限 DP 精确计算

```math
C_e^{DP,LB} = \min_{k_p\in\{1,\ldots,N\},\,\sum k_p\le N+m}
       \sum_{p\in P_e} L_p(k_p\delta).
```

任何真实 P1-R 可行点都隐含存在一个 DP 网格选择满足 `C_e^{DP,LB}≤ΣF_p≤C_e`。所以只有当 **`C_e^{DP,LB}>C_e+10^{-4}GHz`** 才可作为针对**此固定离散结构**的安全必要拒绝。N 改变只影响强度/成本；**向上取整加超额带宽预算不允许漏掉任何真实可行解，最多漏判不合格结构。**

网格有限枚举不是对原连续可行域进行向下离散，也不是把离散DP搜索中的 `infeasible` 当作严格数值优化器证书。这里的**反向乐观扩容**是保持必要条件数学安全的核心。

P5 代码：
- `src/uav_mec/optimization/resource/joint_station_bw_cpu_bound.py`：必要下界、按 MEC 独立 DP、单对 CPU 瓶颈见证；
- `tests/test_joint_station_bw_cpu_bound.py`：严格原模型 Stage1 阳性、网格分辨率、单调关系、容量极端值与源 D 完整性；
- `experiments/run_p5_joint_bound_audit.py`：两批 SHA-256 匹配原始严格结果，不执行新的 Stage1 CVX 以避免误报“新算法更快”；
- `.github/workflows/p5-joint-bw-cpu-audit.yml`：共8个场景，旧 P1 42个严格 Stage1 候选、旧P4 6个严格 Stage1 候选，外加全部 B/ESI 物理源结构，全部异常/误拒必须 fail CI。

## 4. 事前固定的判定与实验口径

| 优先测量 | 具体问题 | 判定 |
|---|---|---|
| **数值安全** | 旧 Stage1 原严格合格的结构是否被新必要界错误拒绝？ | 一例即停止，修复或撤回界 |
| **严格拒绝增量** | 在已同时通过旧队列和 P2 CPU 必要界的 P4 6个失败候选中，新条件是否有**额外**安全拒绝？ | 增益>0是正向线索，不是统计泛化 |
| **分辨率敏感性** | N=12/24/48 逐步提高对假想带宽分配的精度，是否增加/保持拒绝，代价多大？ | 不准用未知现场挑N当新独立验证 |
| **工程成本** | DP 分组/批次前缀计算耗时与原精确 Stage1 运行耗时相比是否值得？ | 必须等时预算与减少求解次数双报告 |
| **下一阶段** | 如额外拒绝成立，能否替代字典序释放 CVX 名额且提高真实 Stage1/2 严格恢复？ | 需要另用从未观察的新场景，与已有 ALNS 真正匹配端到端时间 |

**数学创新边界：** 联合带宽/CPU MEC 调度、广义Benders、经典 energetic reasoning 等都已有研究。本研究要提出可发表主算法贡献，须解释静态 UAV-MEC 虚拟队列/接触 FIFO-EDF 特化的可证明信息如何改进候选修复，并在独立新场景有稳定价值；**仅提出一个安全必要网格预检并不能自动证明新型 ALNS 创新。**

相关研究参考：
- Cang et al. (2024), [Joint User Scheduling and Computing Resource Allocation Optimization in Asynchronous Mobile Edge Computing Networks](https://arxiv.org/abs/2401.11377)，原问题含时变异步任务调度、分解反馈，与本论文静态配额有本质差异。
- Discrete Applied Mathematics 378 (2026), [More powerful energetic reasoning for the cumulative scheduling problem](https://doi.org/10.1016/j.dam.2025.07.016)，显示必要资源判断/能量推理本身已有研究脉络。
- IEEE/Elsevier 已有 MEC 计算与通信资源联合优化，不能把二者联立单独作为论文新意。
