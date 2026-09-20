# UAV-MEC Patrol Research Codebase

> 面向“大型林区固定监测节点周期巡护下的多无人机协同边缘计算”场景。  
> 当前主线：**Route–Contact–Offloading–Resource Coupling**。

## 0. README 的用途

本 README 同时作为项目说明、论文第一项工作的整体路线图、开发任务清单、实验进度记录和下一步工作的参考入口。

状态约定：

- [x] 已完成并通过当前验证；
- [ ] **[VERIFY]** 已实现，但仍需本地实验或回归测试确认；
- [ ] **[TODO]** 尚未实现；
- [ ] **[OPTIONAL]** 仅在实验表明确有收益时加入。

当前代码版本：**v0.5.0**  
主开发分支：**develop**

---

# 1. 研究目标

论文场景：

\[
\boxed{\text{大型林区固定监测节点周期巡护下的多无人机协同边缘计算}}
\]

系统链路：

\[
\text{固定监测节点}
\rightarrow
\text{多 UAV 巡护/采集/缓存/携带/有限机载计算}
\rightarrow
\text{稀疏异构 MEC 边缘站}
\]

核心机制：

\[
\boxed{\text{空间间歇边缘连接 / Contact Opportunity}}
\]

核心耦合：

\[
\boxed{\text{Route–Contact–Offloading–Resource Coupling}}
\]

主目标：

\[
\boxed{\min E_{\mathrm{UAV}}^{\mathrm{tot}}}
\]

主要约束包括任务 deadline、平均任务时延、UAV 周期返航、UAV 电池、MEC 带宽容量、MEC CPU 容量、Store–Carry–Batch-Offload 时序、UAV 本地 FIFO，以及 MEC 虚拟队列 FIFO + 批内 EDF。

工作标题：

> 面向间歇边缘连接的大型林区多无人机巡护路径、计算卸载与资源分配联合优化

---

# 2. 总体求解架构

完整问题：

\[
(P1):\quad
\min_{\mathbf D,\mathbf R}
E_{\mathrm{UAV}}(\mathbf D,\mathbf R)
\]

离散变量：

\[
\mathbf D=
\{\text{UAV assignment, route, contact, Local/MEC, batch}\}
\]

连续资源变量：

\[
\mathbf R=
\{\text{UAV CPU, MEC bandwidth, MEC CPU, upload/event times}\}
\]

固定离散解后的资源价值函数：

\[
V(\mathbf D)
=
\min_{\mathbf R\in\mathcal R(\mathbf D)}
E_{\mathrm{UAV}}(\mathbf D,\mathbf R)
\]

因此：

\[
(P1-D):\quad \min_{\mathbf D}V(\mathbf D)
\]

\[
(P1-R\mid\mathbf D):\quad
\min_{\mathbf R}E_{\mathrm{UAV}}(\mathbf D,\mathbf R)
\]

目标算法结构：

\[
\boxed{
\text{Greedy Route Seed}
\rightarrow
\text{MEC Contact/Offloading Repair}
\rightarrow
\text{Problem-Specific ALNS}
\rightarrow
\text{KKT Resource Recourse}
}
\]

角色说明：

- **Greedy**：主要是初始解构造器，也可作为 Greedy-only baseline；
- **VRP**：描述路径子问题结构，不是一种具体算法；
- **ALNS**：外层主元启发式；
- **ACO / GA**：可作为独立的元启发式 baseline；
- **KKT / Convex**：固定离散解后的连续资源优化；
- **Chaos perturbation**：当前不加入，只有在初始化敏感性实验表明确有收益时再考虑。

---

# 3. 里程碑与当前进度

## M0. 场景与数学模型

- [x] 固定林区监测节点周期巡护场景；
- [x] 多 UAV + 稀疏异构固定 MEC；
- [x] Store–Carry–Batch-Offload；
- [x] 周期内准静态带宽/CPU 切片；
- [x] UAV 本地 FIFO；
- [x] MEC 同 UAV/MEC 虚拟 FIFO；
- [x] 批内 EDF；
- [x] UAV 不等待 MEC 计算完成；
- [x] 主目标为 UAV 总能耗最小化；
- [x] 完成 P1-D / P1-R 分解。

---

## M1. P1-R 连续资源层

### 已完成模型

- [x] Event timeline；
- [x] Local FIFO；
- [x] MEC FIFO / EDF；
- [x] upload time；
- [x] bandwidth capacity；
- [x] MEC CPU capacity；
- [x] deadline / avg-delay / cycle / battery；
- [x] CVXPY DCP oracle；
- [x] optimistic feasibility precheck。

### KKT / Dual Solver

- [x] UAV CPU cube-root KKT；
- [x] MEC CPU square-root KKT；
- [x] bandwidth dual price + bisection；
- [x] event-graph shadow-price backward propagation；
- [x] stationarity / primal / dual / complementarity diagnostics；
- [x] complementarity-aware stopping rule；
- [x] Stage-2 仍由 CVXPY oracle 负责。

### 已验证的小规模 / stress 结果

此前 hard-regime validation：

\[
\max \text{ relative Stage-1 energy gap}
=
1.233\times 10^{-9}
\]

记录：

- max stationarity residual: \(7.13\times10^{-12}\)
- max primal residual: \(1.876\times10^{-3}\)
- max dual residual: \(0\)
- two-MEC relative gap: \(9.755\times10^{-12}\)

当前定位：

\[
\boxed{\text{CVXPY = correctness oracle}}
\]

\[
\boxed{\text{KKT = intended outer-search evaluator}}
\]

### 当前新增问题：paper-scale primal recovery

Paper-scale MEC-repaired 解已经存在**明确的构造式可行资源点**，但原 KKT dual iteration 仍可能在 3000 次迭代内没有重新进入可行域，从而错误返回：

~~~text
kkt_no_feasible_iterate
~~~

这不能直接解释为 P1-R 数学不可行，更可能是 paper-scale dual/primal recovery 的数值问题。

已加入修复并完成首个 paper-scale 验证：

- [x] KKT 保留初始 equal-share / max-local-CPU 的已验证可行 primal seed；
- [x] 若 dual iteration 未恢复可行点，则返回 feasible_seed，而不是错误的 kkt_no_feasible_iterate；
- [x] K=30, seed=42 的 repaired state 已由 CVXPY 验证为 Stage-1 optimal；
- [x] 同一状态下 feasible_seed energy = 190059.701 J；
- [x] CVXPY Stage-1 optimum = 189740.470 J；
- [x] reported-vs-CVX gap = 0.168%；
- [x] 已对 scenario seeds 42/43/44，repaired + proxy-ALNS-best 共 6 个状态执行 gap scan；
- [x] 当前 mean gap = 0.173%，max gap = 0.274%；
- [x] 6 个状态中 5 个使用 feasible_seed fallback，1 个得到 feasible_approx；
- [x] 已区分 CVXPY Stage-1 与 Stage-2 status；当前 6 个 gap-scan 状态的 Stage-1 均为 optimal；
- [x] proxy ranking scan 已覆盖 3 个 scenario seed × 每 seed 6 个唯一候选，共 18 个状态；
- [x] ranking scan mean gap = 0.192%，max gap = 0.274%；
- [x] 三个场景的 Spearman rank correlation 均为 1.0；
- [x] 三个场景的 pairwise ordering agreement 均为 1.0；
- [ ] **[VERIFY]** 在冻结两层评价策略前，检查总能耗是否被 flight/fixed-route 项过度支配；
- [ ] **[VERIFY]** 检查资源优化对 variable energy 的实际改善幅度；
- [ ] **[VERIFY]** 检查 deadline / avg-delay / cycle / bandwidth / MEC CPU 是否存在有效紧约束；
- [ ] **[TODO]** 通过 non-degeneracy scan 后，冻结 fast proxy outer search + elite/final CVX refinement；
- [ ] **[TODO]** dual-guided operators 仍需等待可用 dual certificate，不能使用 feasible_seed 伪造影子价格。

因此：

> **P1-R 数学模型和小规模 KKT 推导保持冻结，但 paper-scale KKT 数值收敛仍需继续验证。**

---

## M2. Paper-scale Instance Generator

- [x] 1000 m × 1000 m 林区；
- [x] \(K=30/50/80/100\)；
- [x] \(M=3/5/8\)；
- [x] \(E=2/3/4\)；
- [x] fixed heterogeneous MEC sites；
- [x] MEC coverage candidate points；
- [x] seed-controlled monitoring nodes；
- [x] task data / workload generator；
- [x] optimistic individual-deadline lower bound；
- [x] reproducibility tests；
- [x] geometry/range tests。

当前 sanity：

| K | M | E | Contacts | Mean data MB | Mean workload Gcy | Mean deadline s |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 5 | 3 | 37 | 2.501 | 20.529 | 324.67 |
| 50 | 5 | 3 | 37 | 2.476 | 19.983 | 329.23 |
| 80 | 5 | 3 | 37 | 2.511 | 20.063 | 336.58 |
| 100 | 5 | 3 | 37 | 2.486 | 20.013 | 336.15 |

当前 cycle、avg-delay、deadline 区间、MEC 坐标等仍是待 non-degeneracy 校准的实验参数。

---

## M3. Greedy Initial Route

定位：

\[
\boxed{\text{Greedy = 初始解构造器}}
\]

实现：

\[
\text{Parallel Greedy Insertion}
\rightarrow
\text{2-opt}
\]

- [x] Task-to-UAV assignment；
- [x] deadline-aware insertion；
- [x] cycle-aware insertion；
- [x] route-distance insertion；
- [x] route-local 2-opt；
- [x] deterministic construction；
- [x] valid all-local seed。

当前 paper-scale 路由结果：

| K | Total km | Max return s | Cycle overflow s | Tasks/UAV [min,max] |
|---:|---:|---:|---:|---:|
| 30 | 10.187 | 231.37 | 0.00 | [3,14] |
| 50 | 11.277 | 246.22 | 0.00 | [4,17] |
| 80 | 12.853 | 292.04 | 0.00 | [9,21] |
| 100 | 13.485 | 304.82 | 0.00 | [12,24] |

关键观察：

\[
\boxed{
\text{几何路径可行}
\not\Rightarrow
\text{计算/QoS 可行}
}
\]

K=30/50 的 all-local 解会产生明显 local FIFO / deadline 压力。

---

## M4. MEC Contact / Offloading Initial Repair

目标：

\[
\text{All-Local}
\rightarrow
\text{Critical Task Detection}
\rightarrow
\text{Local}\rightarrow\text{MEC}
\rightarrow
\text{Contact Insertion / Reuse}
\]

当前实现：

- [x] critical-local-task detection；
- [x] equal-share capacity-feasible resource proxy；
- [x] normalized infeasibility ranking；
- [x] Local→MEC；
- [x] new contact insertion；
- [x] reuse existing later contact；
- [x] Store–Carry–Batch-Offload；
- [x] per-MEC candidate preservation；
- [x] deterministic MEC repair；
- [x] K=30 repaired state 的 CVX/feasible-seed Stage-1 首次对照；
- [ ] **[VERIFY]** 多 seed / ALNS-best 的 resource gap scan。

当前实测：

| K | Proxy violations before | after | Contacts | Offloaded | Proxy max violation |
|---:|---:|---:|---:|---:|---:|
| 30 | 2 | 0 | 1 | 1 | 0 |
| 50 | 4 | 0 | 1 | 2 | 0 |

说明 MEC repair 已经能够用很少的 offloading/contact 动作把构造式 resource proxy 恢复到可行。

但原 KKT dual iteration 在这两个解上均跑满 3000 次而未产生可行 iterate，因此当前优先排查 KKT paper-scale primal recovery，而不是继续盲目增加 offloading 数量。

---

## M5. Mature ALNS Framework Integration

使用：

~~~text
alns>=7.0,<8.0
~~~

成熟框架负责 iteration loop、adaptive operator selection、RouletteWheel、Record-to-Record Travel 和 stopping criteria。

### Destroy

- [x] random task removal；
- [x] deadline/compute-critical removal；
- [x] route-segment removal。

### Repair

- [x] cheapest insertion；
- [x] regret-2 insertion；
- [x] route repair 后继续 MEC repair。

### Objective / State

- [x] ProxyObjectiveEvaluator；
- [ ] **[VERIFY]** KKTObjectiveEvaluator on paper-scale；
- [x] solution-signature cache；
- [x] finite infeasibility penalty；
- [x] partial destroyed-state support；
- [x] ALNS v7 operator metadata compatibility。

### 当前 proxy smoke test

K=30, 30 iterations：

~~~text
initial proxy objective = 190059.701
best proxy objective    = 116581.701
proxy improvement       = 38.660%
contacts                = 2
evaluator calls         = 31
cache hits              = 17
runtime                 = 1.44 s
~~~

说明：

\[
\boxed{\text{destroy} \rightarrow \text{repair} \rightarrow \text{ALNS acceptance/adaptation}}
\]

这条外层链路已经能正常工作。

但 **38.660% 目前只能解释为 proxy objective 改善**，不能写成“真实最优 UAV 能耗降低 38.660%”，因为最终 KKT paper-scale recourse 尚未收敛验证。

---

## M6. Problem-Specific ALNS Operators

后续论文算法重点。

### Route

- [ ] **[TODO]** relocate；
- [ ] **[TODO]** swap；
- [ ] **[TODO]** inter-route segment exchange；
- [ ] **[TODO]** compute-aware relocate；
- [ ] **[TODO]** deadline-critical route repair。

### Contact

- [ ] **[TODO]** contact insert；
- [ ] **[TODO]** contact remove；
- [ ] **[TODO]** contact replace；
- [ ] **[TODO]** candidate-point shift；
- [ ] **[TODO]** repeated same-MEC restructuring。

### Batch / Mode

- [ ] **[TODO]** Local→MEC；
- [ ] **[TODO]** MEC→Local；
- [ ] **[TODO]** MEC reassignment；
- [ ] **[TODO]** batch split；
- [ ] **[TODO]** batch merge；
- [ ] **[TODO]** batch reassign。

### Resource-aware

- [ ] **[TODO]** deadline dual \(\alpha_k\) guided repair；
- [ ] **[TODO]** avg-delay dual \(\beta\) guided repair；
- [ ] **[TODO]** bandwidth shadow price \(\lambda_e^B\)；
- [ ] **[TODO]** MEC CPU shadow price \(\lambda_e^F\)；
- [ ] **[TODO]** congestion-aware MEC switch；
- [ ] **[TODO]** dual-aware candidate pruning。

---

## M7. Local Search

- [ ] **[TODO]** route-only local search；
- [ ] **[TODO]** contact-only local search；
- [ ] **[TODO]** mode local search；
- [ ] **[TODO]** mixed neighborhood；
- [ ] **[TODO]** intensification after ALNS repair。

---

## M8. Baselines

- [ ] **[TODO]** Greedy-only；
- [ ] **[TODO]** Local-only；
- [ ] **[TODO]** Route-only + resource allocation；
- [ ] **[TODO]** nearest-MEC；
- [ ] **[TODO]** mature VRP baseline（优先考虑 PyVRP）；
- [ ] **[TODO]** ACO 或 GA 中至少一个；
- [ ] **[TODO]** Proposed ALNS + KKT。

---

## M9. Small Exact / Strong Benchmark

- [ ] **[TODO]** \(K=8\sim12\) exact/near-exact benchmark；
- [ ] **[TODO]** Gurobi / SCIP / GBD feasibility；
- [ ] **[TODO]** optimality-gap comparison。

---

## M10. Non-degeneracy / Parameter Calibration

- [ ] **[TODO]** Local-only feasibility；
- [ ] **[TODO]** offload ratio；
- [ ] **[TODO]** deadline utilization；
- [ ] **[TODO]** avg-delay utilization；
- [ ] **[TODO]** cycle utilization；
- [ ] **[TODO]** battery utilization；
- [ ] **[TODO]** MEC bandwidth / CPU utilization；
- [ ] **[TODO]** contacts/UAV；
- [ ] **[TODO]** MEC selection distribution；
- [ ] **[TODO]** route detour caused by contacts；
- [ ] **[TODO]** nearest-MEC vs resource-aware MEC；
- [ ] **[TODO]** final cycle/deadline/avg-delay calibration。

---

## M11. Main Experiments

### Scale

- [ ] **[TODO]** \(K=30,50,80,100\)；
- [ ] **[TODO]** \(M=3,5,8\)；
- [ ] **[TODO]** \(E=2,3,4\)。

### Metrics

- [ ] **[TODO]** total UAV energy；
- [ ] **[TODO]** average delay；
- [ ] **[TODO]** deadline slack；
- [ ] **[TODO]** route distance；
- [ ] **[TODO]** contacts；
- [ ] **[TODO]** offload ratio；
- [ ] **[TODO]** runtime；
- [ ] **[TODO]** convergence；
- [ ] **[TODO]** feasibility rate。

### Ablation

- [ ] **[TODO]** without contact-specific operators；
- [ ] **[TODO]** without batch-aware repair；
- [ ] **[TODO]** without dual guidance；
- [ ] **[TODO]** without adaptive operator selection；
- [ ] **[TODO]** Greedy vs random initialization；
- [ ] **[OPTIONAL]** chaos initialization。

---

# 4. 当前代码结构

~~~text
uav-mec-patrol/
├── configs/
├── src/uav_mec/
│   ├── domain/
│   ├── instances/
│   ├── evaluation/
│   ├── optimization/resource/
│   │   ├── cvx_solver.py
│   │   ├── kkt_solver.py
│   │   ├── kkt_temporal.py
│   │   ├── kkt_resources.py
│   │   ├── kkt_verify.py
│   │   └── solver.py
│   └── algorithms/
│       ├── initial/
│       │   ├── greedy.py
│       │   └── mec_repair.py
│       └── alns/
│           ├── state.py
│           ├── evaluator.py
│           ├── operators.py
│           └── runner.py
├── experiments/
├── tests/
├── outputs/
└── CHANGELOG_v*.md
~~~

---

# 5. 常用命令

同步环境：

~~~powershell
uv sync --dev
~~~

测试：

~~~powershell
uv run pytest
~~~

Windows hardlink warning 不影响正确性。可选：

~~~powershell
$env:UV_LINK_MODE="copy"
~~~

资源 stress validation：

~~~powershell
uv run python experiments\run_resource_stress_validation.py
~~~

Paper-scale generator：

~~~powershell
uv run python experiments\run_instance_sanity.py
~~~

Greedy route：

~~~powershell
uv run python experiments\run_initial_solution_sanity.py --tasks 30,50,80,100
~~~

MEC repair：

~~~powershell
uv run python experiments\run_mec_repair_sanity.py --tasks 30,50
~~~

MEC repair + CVXPY oracle：

~~~powershell
uv run python experiments\run_mec_repair_sanity.py --tasks 30 --cvx-check
~~~

多状态 resource recourse gap scan：

~~~powershell
uv run python experiments\run_recourse_gap_scan.py --tasks 30 --seeds 42,43,44 --candidate both --alns-iterations 20
~~~

Proxy ranking preservation scan：

~~~powershell
uv run python experiments\run_proxy_ranking_scan.py --tasks 30 --scenario-seeds 42,43,44 --algorithm-seeds 100,101,102,103,104 --iterations 20
~~~

Objective / constraint non-degeneracy scan：

~~~powershell
uv run python experiments\run_nondegeneracy_scan.py --tasks 30 --seeds 42,43,44 --candidate both --alns-iterations 20
~~~

新版 non-degeneracy scan 还会输出 active UAV-MEC pair 数、shared-MEC 数和 max pairs/MEC，用于判断 bandwidth/CPU allocation 是否真正存在多 UAV 竞争。

Cheap shared-MEC competition sweep：

~~~powershell
uv run python experiments\run_shared_mec_scan.py --tasks 30,50,80 --mecs 2,3,4 --seeds 42,43,44 --candidate both --alns-iterations 20
~~~

该脚本不调用 CVXPY，只扫描不同 K/E 组合下 active pair、shared MEC 与 max pairs/MEC，用于先判断“资源竞争是否自然出现”，再选择少量代表性状态做精确 CVX non-degeneracy 分析。

ALNS proxy：

~~~powershell
uv run python experiments\run_alns_sanity.py --tasks 30 --iterations 30 --objective proxy
~~~

---

# 6. 当前最高优先级任务

当前**不要继续堆新的 ALNS 算子**，先把 resource recourse 在 paper-scale 上确认清楚。

执行顺序：

1. [x] K=30/50 MEC repair 已恢复为 proxy-feasible，KKT 正确保留 feasible_seed；
2. [x] K=30, seed=42 已完成 CVXPY oracle check，gap = 0.168%；
3. [x] recourse gap scan 已覆盖多个 scenario seed；
4. [x] gap scan 已覆盖 repaired 与 proxy-ALNS-best 状态；
5. [x] 当前 6 个状态 mean gap = 0.173%，max gap = 0.274%；
6. [x] 新版 gap scan 已确认 6/6 Stage-1 status = optimal；
7. [x] proxy ranking scan：18 个候选，mean gap = 0.192%，max gap = 0.274%，mean Spearman = 1.0，mean pairwise order = 1.0；
8. [x] 首轮 non-degeneracy scan 已完成：fixed-route energy 平均占比 99.72%，资源层主要影响 variable energy 与 QoS；
9. [x] deadline / avg-delay / cycle / bandwidth / MEC CPU utilization 已完成首轮检查；
10. [x] K=30 新版 non-degeneracy scan：shared MEC = 0/6，max pairs/MEC = 1；
11. [x] shared-MEC scale sweep 已覆盖 K=30/50/80 与 E=2/3；
12. [x] K=30：shared-state rate = 0%，属于轻载/无跨 UAV MEC 竞争；
13. [x] K=50：shared-state rate = 16.7%，属于过渡负载；
14. [x] K=80：E=2 与 E=3 均为 shared-state rate = 100%，max pairs/MEC = 4，资源竞争自然出现；
15. [x] 当前 baseline 无需为了制造 shared MEC 而修改 deadline/B/F 等参数；
16. [ ] **[VERIFY]** 对 K=80, E=2/3 的代表性 shared-MEC 状态运行 CVX non-degeneracy；
17. [ ] **[VERIFY]** 检查 shared-MEC 状态下 bandwidth/CPU capacity dual 是否真正活跃；
18. [ ] **[TODO]** 参数只允许基于 non-degeneracy 与文献/物理依据校准，不通过任意权重放大资源能耗；
19. [ ] **[TODO]** 完成后冻结 fast proxy outer search + elite/final CVX refinement；
20. [ ] **[TODO]** 随后进入 Contact / Batch / resource-aware ALNS operators。

暂时**不建议**运行长时间 exact-KKT ALNS。当前最需要回答的问题是：

\[
\boxed{
\text{paper-scale fixed } \mathbf D
\text{ 下，KKT recourse 能否稳定恢复接近 CVX optimum 的 primal 解}
}
\]

---

# 7. 研究开发原则

1. 不为了“复杂”而堆算法模块；
2. 通用机制优先复用成熟库；
3. 创新集中在问题特定结构；
4. Greedy / ACO / ALNS / VRP 明确区分层级；
5. Chaos 只有有实验依据才加入；
6. 所有新模块必须做 validity / sanity / ablation；
7. 参数调整必须有 non-degeneracy 依据；
8. **Proxy improvement 不等价于 final optimal-energy improvement**；
9. **Solver failure 不等价于 mathematical infeasibility**。

---

# 8. 当前阶段结论

已完成：

\[
\boxed{\text{System Model}}
\]

\[
\boxed{\text{Paper-scale Generator}}
\]

\[
\boxed{\text{Greedy Route Initializer}}
\]

\[
\boxed{\text{MEC Proxy Repair}}
\]

\[
\boxed{\text{External ALNS Structural Integration}}
\]

当前主要待确认项：

\[
\boxed{\text{Fast feasible-seed/proxy 对不同离散状态的 resource-optimality gap}}
\]

当前 18 个 paper-scale 候选状态的 proxy/CVX mean gap 为 0.192%，max gap 为 0.274%，三个场景的 Spearman 与 pairwise ordering agreement 均为 1.0。说明 fast proxy 目前不仅绝对误差小，而且保持了候选解排序。

首轮 non-degeneracy scan（K=30, seeds 42/43/44, repaired + ALNS-best）得到：

- mean fixed-route energy fraction = 99.72%；
- mean variable-resource gain = 126.51%；
- max variable-resource gain = 264.62%；
- max deadline utilization = 1.000；
- avg-delay utilization ≈ 0.667；
- cycle utilization ≈ 0.580；
- offloading states 的 bandwidth utilization = 1.000；
- offloading states 的 MEC CPU utilization 约 0.74~0.78。

这说明总 UAV 能耗确实被飞行/采集项强烈支配，因此 0.2% 左右的总能耗 gap 不能单独作为“资源 proxy 很精确”的充分证据；但资源优化对 variable energy 的影响很大，而且 deadline 处于活跃边界，资源层仍然对 QoS 可行性具有实际作用。

K/E scale sweep 已确认资源竞争会随任务规模自然出现：

| K | E | shared-state rate | mean offload | mean active pairs | max pairs/MEC |
|---:|---:|---:|---:|---:|---:|
| 30 | 2 | 0.0% | 0.83 | 0.67 | 1 |
| 30 | 3 | 0.0% | 1.17 | 0.83 | 1 |
| 50 | 2 | 16.7% | 2.50 | 1.83 | 2 |
| 50 | 3 | 16.7% | 2.67 | 2.00 | 2 |
| 80 | 2 | 100.0% | 9.50 | 4.00 | 4 |
| 80 | 3 | 100.0% | 11.00 | 5.17 | 4 |

因此当前 baseline 不需要人为收紧 deadline 或降低 B/F 来“制造”资源竞争。更自然的负载分层已经形成：

[
oxed{
K=30	ext{：轻载}
;ightarrow;
K=50	ext{：过渡负载}
;ightarrow;
K=80	ext{：高负载/共享 MEC 竞争}
}
]

下一步只需要对 K=80 的 shared-MEC 状态做精确 CVX non-degeneracy，验证 bandwidth/CPU capacity 是否不仅结构上共享，而且对应 dual/shadow price 也真正活跃。
