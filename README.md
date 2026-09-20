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
- [ ] **[VERIFY]** 区分 CVXPY Stage-1 与 Stage-2 status，避免将 Stage-2 optimal_inaccurate 误认为 Stage-1 oracle 不可靠；
- [ ] **[VERIFY]** 验证 proxy 是否保持候选解之间的能耗排序，而不只检查绝对 gap；
- [ ] **[TODO]** 若 ranking preservation 也稳定，则将 feasible-seed proxy 作为 outer-search 快速评价，并仅对 elite/final states 做精确 refinement；
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
6. [ ] **[VERIFY]** 重跑新版 gap scan，确认 CVXPY Stage-1 status；
7. [ ] **[VERIFY]** 运行 proxy ranking preservation scan；
8. [ ] **[TODO]** 若排序一致性高，则正式采用 fast proxy outer search + elite/final CVX refinement；
9. [ ] **[TODO]** dual-guided operators 仅在 dual_certificate_available=True 时启用；
10. [ ] **[TODO]** 完成上述验证后进入 Contact / Batch / resource-aware ALNS operators。

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

当前 6 个 paper-scale 状态的 mean gap 为 0.173%，max gap 为 0.274%，因此 paper-scale KKT primal recovery 已从“可行性 blocker”降级为“精度/效率验证问题”。下一步不再只看绝对 gap，而要验证 fast proxy 是否保持不同候选离散解之间的排序；只有 ranking preservation 也稳定，才正式冻结为 fast outer search + elite/final CVX refinement 的两层评价策略。
