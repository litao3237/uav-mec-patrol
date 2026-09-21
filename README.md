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

当前代码版本：**v0.6.0**  
主开发分支：**develop**

**当前阶段：主算法冻结，进入消融与主实验阶段。**

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

当前冻结的论文主算法结构：

\[
\boxed{
\text{Greedy Route Seed}
\rightarrow
\text{MEC Contact/Offloading Repair}
\rightarrow
\text{Generic ALNS Exploration}
\rightarrow
\text{Elite Structural Intensification}
\rightarrow
\text{Strict Stage-1 CVX Acceptance}
}
\]

其中外层 Generic ALNS 使用 screened proxy 进行高效搜索；问题特定的
Route/Contact/Offloading/Batch 结构不再作为 RouletteWheel 的同级算子抢占
探索预算，而是在 generic elite 上进行小规模、精确接受的结构强化。

角色说明：

- **Greedy**：主要是初始解构造器，也可作为 Greedy-only baseline；
- **VRP**：描述路径子问题结构，不是一种具体算法；
- **ALNS**：外层主元启发式；当前论文主线采用 Generic ALNS exploration；
- **Elite structural intensification**：在 generic best state 上执行 route-compute relocation、contact relocation/replacement/removal、batch merge/split/new-contact、mode/batch reassignment，并由严格 Stage-1 CVX 单调接受；
- **ACO / GA / VRP heuristic**：仅作为后续独立 baseline 候选，不属于 Proposed Algorithm；
- **CVXPY / Convex**：固定离散解后的 Stage-1 correctness oracle，也是 elite/final paper-facing 能耗的严格验证器；
- **KKT**：连续资源子问题 P1-R 的已实现解析/数值求解层；用于闭式资源关系、dual/shadow-price 分析、小规模交叉验证和 fast resource approximation。paper-scale primal recovery 尚未完全稳定，因此当前不替代 CVXPY correctness oracle；
- **Dual-guided ALNS**：属于可选增强，不是当前冻结主算法的必需组成；只有在 paper-scale dual certificate 足够稳定且消融有收益时才考虑加入；
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
\boxed{\text{KKT = analytical validation / dual-structure tool}}
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
- [x] non-degeneracy 已确认 total energy 被 flight/fixed-route 强烈支配，但 variable energy 与 QoS/resource dual 均非退化；
- [x] K=80 高负载下 shared MEC bandwidth dual 在全部已验证可行状态中为正，shared MEC CPU dual 在多数状态中为正；
- [x] fast proxy 用于常规候选排序，CVX 用于 correctness/refinement 的总体方向已成立；
- [ ] **[VERIFY]** ScreenedProxyObjectiveEvaluator：precheck hard reject + proxy fast path + gray-zone Stage-1 CVX refinement；
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
- [x] optimistic precheck 作为 fixed-discrete hard-infeasibility certificate；
- [ ] **[VERIFY]** ScreenedProxyObjectiveEvaluator：只对 precheck-feasible / proxy-infeasible gray zone 调用 Stage-1 CVX；
- [x] KKTObjectiveEvaluator 保留为诊断/解析验证工具，不作为 paper-scale 默认主路径；
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

## M6. Frozen Proposed Hybrid ALNS

当前论文主算法已经冻结为：

\[
\boxed{
\text{Generic ALNS Exploration}
\rightarrow
\text{Problem-Specific Elite Structural Intensification}
\rightarrow
\text{Strict Stage-1 CVX Monotone Acceptance}
}
\]

### Generic exploration

- [x] random task removal；
- [x] critical task removal；
- [x] route-segment removal；
- [x] cheapest insertion + MEC repair；
- [x] regret-2 insertion + MEC repair；
- [x] RouletteWheel adaptive selection；
- [x] Record-to-Record Travel acceptance；
- [x] ScreenedProxyObjectiveEvaluator；
- [x] optimistic precheck hard reject；
- [x] gray-zone Stage-1 CVX refinement。

### Elite structural neighborhood

- [x] route-compute relocation；
- [x] contact relocation；
- [x] contact-point / cross-MEC replacement；
- [x] contact removal；
- [x] batch merge；
- [x] batch split / new contact；
- [x] task-level Local/MEC / batch reassignment；
- [x] diversity-preserving family shortlist；
- [x] exact positive near-miss progressive widening；
- [x] meaningful improvement threshold；
- [x] strict Stage-1 CVX acceptance；
- [x] `optimal_inaccurate` candidate rejection。

多组 K=50/80/100 实验中，`route_compute_relocate` 持续是最主要的有效
结构操作，因此下一阶段优先做该 family 的消融，而不是继续增加新算子。

### 不再作为主算法必需项的旧候选

以下模块保留为研究候选或 baseline，不再视为“主算法没写完”：

- standalone swap / inter-route segment exchange；
- peer-level problem-specific RouletteWheel profiles（core/full 已被消融证明弱于 generic exploration）；
- 独立 route/contact/mode local-search loop；
- repeated same-MEC restructuring；
- chaos initialization。

### KKT 与 dual guidance

KKT **属于已实现的连续资源层**，不是被删除的模块：

- [x] UAV CPU cube-root KKT；
- [x] MEC CPU square-root KKT；
- [x] bandwidth dual price + bisection；
- [x] temporal/event-graph shadow-price propagation；
- [x] stationarity/primal/dual/complementarity diagnostics；
- [x] 小规模 KKT-CVX 高精度交叉验证；
- [x] paper-scale feasible-seed fallback；
- [ ] **[VERIFY]** paper-scale primal recovery / 收敛稳定性；
- [ ] **[OPTIONAL]** dual-guided ALNS operators，仅在可靠 dual certificate 和消融收益同时成立后加入。

当前论文定位：

\[
\boxed{
\text{KKT = resource analytical solver / structural analysis}
}
\]

\[
\boxed{
\text{CVXPY Stage-1 = paper-scale correctness oracle}
}
\]

---

## M7. Algorithm Validation / Ablation

当前重点从“继续开发主算法”切换为“证明主算法为何有效”。

- [x] Generic ALNS vs peer-level core/full problem operators；
- [x] Generic ALNS vs Hybrid elite intensification；
- [x] shortlist widening / diversity / progressive widening 诊断；
- [x] K=80,E=2 out-of-sample paired validation；
- [x] K=50/80/100 workload sensitivity（E=2）；
- [x] K=100 MEC-count sensitivity（E=2/3/4）；
- [ ] **[NEXT]** Full Hybrid vs **w/o route-compute relocation**；
- [ ] **[TODO]** w/o contact family；
- [ ] **[TODO]** w/o batch family；
- [ ] **[TODO]** w/o progressive widening；
- [ ] **[OPTIONAL]** w/o adaptive ALNS selection。

---

## M8. Baselines

主算法已经具备独立运行能力，剩余工作是构建论文对照组：

- [ ] **[TODO]** Greedy + MEC repair；
- [x] Generic ALNS（天然 baseline）；
- [ ] **[TODO]** Route-only + resource allocation；
- [ ] **[TODO]** nearest-MEC / nearest-contact heuristic；
- [ ] **[TODO]** ACO 或 GA 至少一个独立元启发式 baseline；
- [ ] **[OPTIONAL]** mature VRP baseline（如 PyVRP，需保证与计算/接触约束的比较公平）；
- [x] Proposed Hybrid ALNS + exact Stage-1 resource verification。

---

## M9. Small Exact / Strong Benchmark

- [ ] **[TODO]** K=8~12 exact / near-exact benchmark；
- [ ] **[TODO]** 评估 SCIP / Gurobi / enumeration / decomposition 的可行实现；
- [ ] **[TODO]** Proposed Algorithm 对 best-known 的 optimality gap。

---

## M10. Parameter / Non-degeneracy Validation

已完成主要 non-degeneracy 诊断：

- [x] workload / route / deadline / avg-delay / cycle 检查；
- [x] shared-MEC competition sweep；
- [x] bandwidth/CPU dual 活跃性检查；
- [x] proxy vs CVX ranking / gap 验证；
- [x] 高负载 feasibility robustness scan；
- [x] E=2/3/4 fixed-infrastructure sensitivity；
- [x] MEC-count sweep task-instance invariance regression test。

论文最终表格仍需整理：

- [ ] **[TODO]** offload ratio；
- [ ] **[TODO]** contacts/UAV；
- [ ] **[TODO]** MEC selection distribution；
- [ ] **[TODO]** route detour；
- [ ] **[TODO]** deadline slack / utilization；
- [ ] **[TODO]** bandwidth / CPU utilization；
- [ ] **[TODO]** runtime / convergence。

---

## M11. Main Paper Experiments

### 已形成的主实验骨架

- [x] K=50/80/100 workload behavior；
- [x] K=100, E=2/3/4 MEC-count sensitivity；
- [x] multi-scenario / multi-algorithm-seed paired hybrid validation；
- [x] strict-optimal filtering 和 solver-status reporting。

### 尚需完成

- [ ] **[NEXT]** 核心 family ablation；
- [ ] **[TODO]** baseline comparison；
- [ ] **[TODO]** UAV 数量 M=3/5/8 sensitivity；
- [ ] **[TODO]** 小规模 exact/near-exact benchmark；
- [ ] **[TODO]** 汇总 total energy、delay、slack、distance、contacts、offload ratio、runtime、feasibility rate；
- [ ] **[TODO]** 最终绘图、统计与论文表格。

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
│           ├── problem_operators.py
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

主算法结构已经冻结，当前不再以“增加更多算子”为目标。

优先级：

1. [x] 完成 Hybrid 主算法与严格 CVX acceptance；
2. [x] 完成 K=100,E=2/3/4 高负载 MEC-count sensitivity；
3. [ ] **[NEXT]** `w/o route_compute_relocate` 核心消融；
4. [ ] **[TODO]** contact / batch / progressive-widening 消融；
5. [ ] **[TODO]** Greedy / nearest-MEC / route-only / ACO-or-GA baselines；
6. [ ] **[TODO]** K=8~12 strong benchmark；
7. [ ] **[TODO]** M=3/5/8 sensitivity 与最终指标汇总；
8. [ ] **[VERIFY]** paper-scale KKT primal recovery；KKT 继续作为资源解析层完善，但不阻塞 Hybrid 主算法消融与 baseline 实验。

当前原则：

\[
\boxed{
\text{Freeze Proposed Algorithm}
\rightarrow
\text{Ablation}
\rightarrow
\text{Baselines}
\rightarrow
\text{Scale/Sensitivity}
\rightarrow
\text{Final Paper Tables}
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


## K=80 CVX non-degeneracy：当前诊断注意事项

首轮 K=80 CVX non-degeneracy 输出中，每个 E 本应有 3 个 scenario seed × 2 类 candidate = 6 个状态，但控制台只打印了 3 行。原因是旧版脚本在 `cvx.feasible == False` 时只写 JSON、不打印控制台，因此：

- 当前看到的 fixed-route / var-gain / dual 聚合只基于**打印出来的 CVX-feasible 子集**；
- 不能据此写成“6/6 全部可行”或“所有 K=80 状态都满足相同 dual 结论”；
- 新版脚本已改为打印全部状态，并额外输出 `p-vio`、`cvx-s1`、`sh-bw`、`sh-cpu`；
- `sh-bw` / `sh-cpu` 只统计**shared MEC 本身**的正 bandwidth/CPU dual，比原先的全局 dual 计数更适合判断真实多 UAV 资源竞争。

新版 K=80 结果已经确认：被旧脚本省略的状态主要是 `infeasible_precheck`，不是 CVXPY 数值失败。

对 K=80：

- E=2：6 个状态中 3 个 Stage-1 CVX optimal，3 个 optimistic precheck infeasible；
- E=3：6 个状态中 3 个 Stage-1 CVX optimal，3 个 optimistic precheck infeasible；
- 所有 CVX-feasible shared-MEC 状态均满足 shared bandwidth dual > 0；
- 其中 2/3 状态还满足 shared MEC CPU dual > 0；
- 因此资源竞争本身已经通过 non-degeneracy 验证；
- 当前新的算法性问题是：现有 20-iteration generic ALNS 在高负载 seed=43 上还不能稳定修复 fixed-discrete infeasibility。

另一个重要现象是 E=2, seed=42 repaired：`p-vio=1` 但 Stage-1 CVX 仍为 optimal。这说明 equal-share/max-local-CPU proxy 是**保守可行点**，`proxy violation > 0` 不等价于真实 P1-R infeasible。后续 outer evaluator 必须区分：
1. optimistic precheck infeasible：固定离散解确定不可行；
2. precheck feasible + proxy infeasible：资源层不确定区，不能直接当成结构不可行；
3. proxy feasible：已有构造式可行资源点。


## High-load feasibility robustness scan

K=80, scenario seed=43 的 budget scan 已完成，结果表明此前 20-iteration 不可行主要是**搜索预算不足**，而不是当前 neighborhood 完全无法恢复可行性。

- E=2：20 iter 为 0/3 precheck-feasible；100 iter 为 2/3；300 iter 为 3/3，且所有被 CVX 检查的状态均 Stage-1 optimal；
- E=3：20 iter 为 1/3；100 iter 为 3/3；300 iter 为 3/3，且所有被 CVX 检查的状态均 Stage-1 optimal；
- 所有 remaining precheck infeasibility 都来自 task-deadline lower bound，未观察到 avg-delay 或 cycle precheck violation；
- 因此项目默认的 300 iterations 在该高负载困难 seed 上已有充分的可行性恢复能力；M6 新算子应主要服务于**搜索效率、解质量和问题特定创新**，而不是为了弥补“完全无法找到可行解”。

用于复现实验：

~~~powershell
uv run python experiments\run_high_load_feasibility_scan.py --tasks 80 --mecs 2,3 --scenario-seeds 43 --algorithm-seeds 100,101,102 --iterations 20,100,300
~~~

输出同时区分：

- proxy violations；
- optimistic precheck 是否可行；
- precheck 中 task-deadline / avg-delay / cycle 原因数；
- 对 precheck-feasible 最终状态的 Stage-1 CVX 确认。

判定规则：

- 若 100/300 iterations 后大多数 algorithm seed 能恢复 precheck/CVX feasibility，则当前 neighborhood 基本足够，问题主要是搜索预算与参数；
- 若 300 iterations 后 seed=43 仍大量 `infeasible_precheck`，则进入 M6，优先实现 deadline-critical compute-aware relocate / contact restructure，而不是继续增加迭代数。


## Screened outer evaluator

高负载实验还确认了一个关键现象：

[
\text{proxy violation}>0
\not\Rightarrow
P1\text{-R infeasible}.
]

因此新增 `ScreenedProxyObjectiveEvaluator`，采用三段式判断：

[
\boxed{
\text{Optimistic Precheck}
\rightarrow
\begin{cases}
\text{fail} & \Rightarrow \text{hard infeasible penalty}\\
\text{pass + proxy feasible} & \Rightarrow \text{fast proxy energy}\\
\text{pass + proxy infeasible} & \Rightarrow \text{Stage-1 CVX gray-zone refinement}
\end{cases}}
]

这样避免把“equal-share resource point 不可行”误判为“固定离散解不可行”，同时绝大多数正常候选仍走快速 proxy 路径。

验证命令：

~~~powershell
uv run python experiments\run_alns_sanity.py --tasks 80 --mecs 2 --seed 42 --iterations 100 --objective screened
~~~

重点观察 JSON 中：

- `precheck_rejects`
- `ambiguous_proxy_calls`
- `cvx_refinements`
- runtime
- best solution 最终可行性

若该 smoke test 通过，resource/evaluator 阶段即可冻结，项目正式进入 M6 Problem-Specific ALNS Operators。


## Proxy vs screened evaluator trade-off

K=80, E=2, scenario seed=42, 100 ALNS iterations 已完成同场景对照：

### Screened evaluator

- initial objective = 255297.483 J；
- best search objective = 196267.040 J；
- final Stage-1 CVX energy = 196035.484 J；
- evaluator calls = 101；
- cache hits = 23；
- unique evaluated states = 78；
- precheck hard rejects = 30；
- gray-zone CVX refinements = 17；
- runtime = 63.93 s。

因此 unique states 的 evaluator 分流约为：

- precheck hard reject: 30/78 = 38.5%；
- fast proxy path: 31/78 = 39.7%；
- gray-zone Stage-1 CVX refinement: 17/78 = 21.8%。

最终 best search objective 与 Stage-1 CVX 的相对差约 0.118%。

### Pure proxy evaluator

同一场景、同一 100 iterations：

- initial objective = 2.0459e9，说明初始状态因 proxy violation 被大惩罚；
- best proxy objective = 215215.929 J；
- final best state Stage-1 CVX status = optimal；
- evaluator calls = 101；
- cache hits = 28；
- runtime = 51.55 s。

因此：

1. pure proxy 在高负载 gray-zone 状态上确实会产生 false negative，并使初始“improvement %”被 penalty 主导，不能作为论文能耗改善率；
2. screened evaluator 相比 pure proxy 只增加约 12.4 s（约 24% 相对 runtime），说明当前 paper-scale 运行时间并不主要由 gray-zone CVX refinement 决定，repair/operator candidate evaluation 本身也占较大成本；
3. pure proxy 当前 best proxy objective 明显高于 screened 最终 CVX energy；需用保存的 `best_cvx_energy_j` 做最终 apples-to-apples 对比，但 pure proxy 不再适合作为高负载默认 evaluator；
4. 当前默认方向调整为：`ScreenedProxyObjectiveEvaluator` 作为 robust paper-scale evaluator，`ProxyObjectiveEvaluator` 保留用于快速 smoke test / ablation；最终 elite/best state 统一做 Stage-1 CVX verification。

`run_alns_sanity.py` 已进一步修正：
- 若 initial objective 明显包含 infeasibility penalty，则 `improve-%` 输出 `n/a`，避免出现 99.989% 这类无物理意义的“改善率”；
- 控制台直接打印 `best-cvx-E-J` 与 `best-vs-cvx gap-%`。


## Evaluator decision after apples-to-apples CVX check

K=80, E=2, scenario seed=42, 100 ALNS iterations:

| evaluator | final Stage-1 CVX energy (J) | runtime (s) |
|---|---:|---:|
| screened | 196035.484 | 63.93 |
| pure proxy | 214759.456 | 51.55 |

Compared with pure proxy, screened finds a final CVX-verified solution with about 8.72% lower energy, while runtime increases by about 24.0%.

The pure-proxy best search objective is 215215.929 J versus its own final Stage-1 CVX energy 214759.456 J, i.e. about 0.213% resource-evaluation error on that final discrete state. The larger gap between pure proxy and screened therefore comes mainly from **search guidance / false-negative gray-zone rejection**, not from final resource refinement alone.

Decision for the development default:

[
\boxed{\text{ScreenedProxyObjectiveEvaluator = default paper-scale ALNS evaluator}}
]

[
\boxed{\text{ProxyObjectiveEvaluator = fast smoke-test / ablation evaluator}}
]

[
\boxed{\text{CVXPY Stage-1 = final correctness oracle}}
]

[
\boxed{\text{KKT = analytical / dual-structure validation tool}}
]

This default is now wired into `run_uav_mec_alns(...)` when no evaluator is explicitly supplied. The current numerical comparison is still a single scenario-level design check; the final paper should report multi-seed comparisons rather than generalize the 8.72% figure universally.


## v0.6.0 M6 verification

首批问题特定 neighborhood 已实现，但在本地测试和 paper-scale ablation 通过前统一标记为 **[VERIFY]**。

建议验证顺序：

~~~powershell
git pull
uv sync --dev
uv run pytest
~~~

先做短 smoke test：

~~~powershell
uv run python experiments\run_alns_sanity.py --tasks 30 --mecs 3 --seed 42 --iterations 20 --objective screened
~~~

再做同场景 generic/proposed 小规模消融：

~~~powershell
uv run python experiments\run_operator_ablation.py --tasks 80 --mecs 2 --scenario-seeds 42 --algorithm-seeds 100 --iterations 50
~~~

若 smoke test 与单 seed ablation 正常，再扩展：

~~~powershell
uv run python experiments\run_operator_ablation.py --tasks 50,80 --mecs 2,3 --scenario-seeds 42,43,44 --algorithm-seeds 100,101,102 --iterations 100
~~~

核心比较指标不是 ALNS 内部 proxy/search objective，而是每个最终离散解统一经过 **Stage-1 CVX** 后的：

- CVX feasibility rate；
- final CVX UAV energy；
- runtime；
- contacts / offload / active UAV-MEC pairs；
- gray-zone CVX refinement 次数。

只有多 seed 消融确认 proposed operator family 在可行率、能耗或收敛速度上有稳定收益后，才把 M6 对应条目从 **[VERIFY]** 改为 **[x]**。


## v0.6.0 first operator-level ablation: full profile diagnosis

K=80, E=2, scenario seed=42, algorithm seeds 100/101/102, 100 iterations:

| mode | mean Stage-1 CVX energy (J) | mean runtime (s) |
|---|---:|---:|
| generic | 210810.848 | 61.11 |
| full problem-specific | 221220.773 | 60.00 |

The first full-profile implementation is therefore about 4.94% worse in mean final CVX energy on this three-seed diagnostic, although one seed (102) is about 0.66% better. The result is treated as an operator-design diagnostic, not as a paper claim.

Aggregated operator outcomes from the full profile reveal a clear hierarchy:

- `mode_batch_repair`: 86 uses, 22 BEST + 12 BETTER; strongest new repair family;
- `contact_opportunity_repair`: 78 uses, 17 BEST + 1 BETTER; useful global-best generator;
- `shared_mec_pressure_removal`: 69 uses, 13 BEST + 3 BETTER; useful high-load destroy family;
- `mec_batch_pressure_removal`: 37 uses, only 7 improving outcomes but 28 accepted; mainly diversification;
- `compute_aware_insertion_repair`: 23 uses, 3 improving outcomes, 17 rejected; currently weak;
- `route_segment_removal`: 16 uses, 0 improving outcomes, 15 rejected; clearly weak in this setting.

Because ALNS outcome counts are attributed separately to the selected destroy and repair operators, they are not causal pairwise scores. The next design iteration therefore does **not** add more operators. Instead it introduces:

1. a `core` problem-specific profile;
2. semantic destroy/repair coupling;
3. explicit `generic/core/full` profile ablation.

The new default `core` profile keeps:

Destroy:
- `random_task_removal`
- `critical_task_removal`
- `shared_mec_pressure_removal`

Repair:
- `cheapest_insertion_mec_repair`
- `regret2_insertion_mec_repair`
- `contact_opportunity_repair`
- `mode_batch_repair`

It temporarily excludes `route_segment_removal`, `mec_batch_pressure_removal` and `compute_aware_insertion_repair` from the main proposed profile, while retaining them in `full` for ablation/research.

Semantic coupling also prevents MEC-specific destroy operators from being paired with repairs that cannot meaningfully restructure contact/offloading decisions.

Recommended next command:

~~~powershell
git pull
uv run pytest
uv run python experiments\run_operator_ablation.py --tasks 80 --mecs 2 --scenario-seeds 42 --algorithm-seeds 100,101,102 --iterations 100 --profiles generic,core,full
~~~

The core profile must outperform or at least match generic consistently before it is promoted from **[VERIFY]** to a validated paper algorithm component.


## v0.6.0 second operator ablation: objective-alignment diagnosis

The generic/core/full comparison on K=80, E=2, scenario seed=42, algorithm seeds
100/101/102, 100 iterations produced:

| profile | mean Stage-1 CVX energy (J) | mean runtime (s) |
|---|---:|---:|
| generic | 210810.848 | 61.29 |
| core | 220054.542 | 58.46 |
| full | 223612.984 | 41.87 |

The core profile is therefore still about 4.39% worse than generic in mean final
CVX energy, while full is about 6.07% worse. Core is better than generic on
algorithm seed 102, but worse on 100 and 101. This is not sufficient to validate
the proposed operator family.

A structural issue was identified in the implementation: problem-specific local
moves were internally ranked by a key that placed **proxy violation count ahead
of energy** after the optimistic precheck. This conflicts with the already
validated screened-evaluator rule:

[
\text{proxy violation}>0
\not\Rightarrow
P1\text{-R infeasible}.
]

The effect is visible in the final discrete structures: core/full often reduce
contacts/offloaded tasks/active pairs relative to generic, pushing the search
toward proxy-feasible low-contention states even when a gray-zone state can be
better after Stage-1 CVX resource optimization.

The implementation is therefore changed as follows:

1. optimistic precheck remains the only hard structural feasibility screen;
2. among precheck-feasible local candidates, the cheap shortlist is energy-first
   rather than proxy-violation-first;
3. contact and mode/batch intensification choose only one cheap promising move;
4. that selected move is accepted locally only if the injected outer evaluator
   (normally ScreenedProxyObjectiveEvaluator) confirms improvement over the
   repaired baseline;
5. destroy-repair **pair outcome tracking** is added, because separate destroy
   and repair BEST/BETTER counts do not identify causal operator pairings.

This preserves cheap candidate generation while aligning local intensification
with the exact same objective logic used by the outer ALNS.

Next verification:

~~~powershell
git pull
uv run pytest
uv run python experiments\run_operator_ablation.py --tasks 80 --mecs 2 --scenario-seeds 42 --algorithm-seeds 100,101,102 --iterations 100 --profiles generic,core,full
~~~

The new output additionally reports destroy-repair pair outcomes. The next
decision should be based on final Stage-1 CVX energy and pair-level BEST/BETTER
evidence, not on individual operator counts alone.


## v0.6.0 third ablation: core still trapped, switch to hybrid exploration + elite intensification

After objective-alignment and pair-level diagnostics, K=80, E=2, scenario
seed=42, algorithm seeds 100/101/102, 100 iterations produced:

| profile | mean Stage-1 CVX energy (J) | mean runtime (s) | mean screened gray-zone CVX refinements |
|---|---:|---:|---:|
| generic | 210810.848 | 61.15 | 25.33 |
| core | 218614.859 | 80.09 | 49.33 |
| full | 226440.743 | 84.76 | 56.33 |

One core final state (algorithm seed 102) was `optimal_inaccurate`, so the exact
core mean should not be treated as a final paper number. The qualitative
conclusion is nevertheless clear: making contact/mode operators peer members of
the RouletteWheel still degrades the search on seeds 100/101, increases gray-zone
CVX calls, and increases runtime.

Pair-level outcomes show that the problem-specific mechanisms are not useless:
for example, random-task removal paired with contact opportunity or mode/batch
repair repeatedly produces BEST/BETTER outcomes. The issue is therefore search
architecture rather than absence of useful local moves.

The next architecture is:

[
\boxed{
\text{Generic ALNS exploration}
\rightarrow
\text{elite solution}
\rightarrow
\text{problem-specific Contact/Mode intensification}
\rightarrow
\text{Stage-1 CVX acceptance}
}
]

A new `hybrid` profile has been added to the ablation experiment. Its main ALNS
trajectory is intentionally identical to `generic` for the same random seed.
Only after the generic search finishes, the best state receives at most two
rounds of problem-specific contact opportunity and mode/batch intensification.

The elite moves are shortlisted cheaply, but acceptance is based on a cached
Stage-1 CVX oracle. Therefore an accepted elite move is monotone with respect to
the actual fixed-discrete P1-R objective, rather than the proxy feasibility
classification.

This is the cleanest next test because it isolates the real question:

> can problem-specific Contact/Offloading/Batch structure improve the best state
> found by a strong generic ALNS, without stealing exploration budget from it?

Recommended next experiment:

~~~powershell
git pull
uv run pytest
uv run python experiments\run_operator_ablation.py --tasks 80 --mecs 2 --scenario-seeds 42 --algorithm-seeds 100,101,102 --iterations 100 --profiles generic,hybrid
~~~

Only if hybrid shows useful improvement/equality with modest extra runtime should
the contact/mode elite intensification be promoted into the main proposed
algorithm. Core/full remain diagnostic ablations for now.


## v0.6.0 fourth ablation: hybrid route-contact intensification starts to pay off

K=80, E=2, scenario seed=42, algorithm seeds 100/101/102, 100 iterations:

| mode | mean Stage-1 CVX energy (J) | mean runtime (s) | mean elite CVX calls |
|---|---:|---:|---:|
| generic | 210810.848 | 61.04 | 0.00 |
| hybrid | 209386.873 | 69.58 | 10.67 |

Paired outcomes:

- seed 100: 196035.484 -> 192521.023 J, about 1.79% lower;
- seed 101: 214080.691 -> 213323.227 J, about 0.35% lower;
- seed 102: unchanged at 222316.370 J.

The mean paired reduction on this one scenario is about 0.68%, while runtime
increases by about 14%. The result is encouraging but is **not yet a paper-level
claim**, because it covers only scenario seed 42.

The accepted elite moves reveal the important mechanism:

- seed 100: `route_compute_relocate::S64->U2@11`;
- seed 101: `route_compute_relocate::S80->U4@3`;
- seed 102: no improving elite move.

Therefore the first material hybrid gain comes from **route-compute relocation
followed by MEC/contact reconstruction and exact resource recourse**, not from
fixed-route contact-point tuning alone.

This supports the paper's main hypothesis:

[
\boxed{
\text{shortest/geometric route decisions}
\neq
\text{best computing-aware route decisions}
}
]

but more scenario-level evidence is required.

### Main API change

The default `run_uav_mec_alns(...)` trajectory is now generic exploration
(`enable_problem_operators=False` by default), because core/full peer-operator
profiles were empirically weaker.

A new high-level proposed runner is added:

~~~python
run_uav_mec_hybrid_alns(...)
~~~

It implements:

[
\boxed{
\text{Generic ALNS Exploration}
\rightarrow
\text{Elite Structural Neighborhood}
\rightarrow
\text{Stage-1 CVX Monotone Acceptance}
}
]

The elite neighborhood contains route-compute relocation, contact relocation,
contact insertion/removal, contact-point/MEC replacement, batch merge/split and
task-level mode/batch reassignment.

### Paired validation script

A dedicated script now runs generic exploration **once** and compares the
exploration elite against its exact intensified descendant, avoiding duplicate
generic searches:

~~~powershell
uv run python experiments\run_hybrid_validation.py --tasks 80 --mecs 2,3 --scenario-seeds 42,43,44 --algorithm-seeds 100,101,102 --iterations 100
~~~

It reports paired Stage-1 CVX energies, improvement rate, accepted structural
moves, elite CVX calls and elite runtime. This should be the next validation
before further neighborhood tuning.


## Cross-scenario hybrid validation: promising mechanism, insufficient robustness

Paired validation on K=80, E=2, scenario seeds 42/43/44 and algorithm seeds
100/101/102 (100 ALNS iterations) produced 9 runs:

- 8 runs had paired Stage-1-feasible generic/hybrid states;
- 2/8 paired runs improved;
- 6/8 were unchanged;
- mean paired energy reduction = 0.268%;
- median paired reduction = 0.000%;
- all observed improvements occurred in scenario seed 42;
- both accepted improvements were `route_compute_relocate` moves.

Therefore the current evidence supports the **mechanism** (route-compute relocation
can improve an elite solution), but does not yet support a robust cross-scenario
performance claim.

Scenario seed 43 also exposes numerical/search difficulty:

- algorithm seeds 100/101 end at `optimal_inaccurate`;
- algorithm seed 102 remains `infeasible_precheck` after 100 iterations.

For exact elite acceptance, the hybrid runner now requires the exploration
Stage-1 status to be strictly `optimal`. `optimal_inaccurate` states are
reported but skipped by elite refinement, avoiding paper claims based on
approximate oracle comparisons and saving unnecessary CVX work.

The next diagnostic is to determine whether the no-improvement cases arise
because:

1. the current top-6 proxy shortlist misses useful route-compute candidates, or
2. the generated neighborhood genuinely contains no improving move.

`run_hybrid_validation.py` now exposes elite-budget controls and records exact
candidate deltas. A clean next test uses the numerically stable scenario seed 44:

~~~powershell
uv run python experiments\run_hybrid_validation.py --tasks 80 --mecs 2 --scenario-seeds 44 --algorithm-seeds 100,101,102 --iterations 100 --elite-shortlist-limit 12 --elite-task-limit 6 --elite-route-options-per-task 3
~~~

If wider exact shortlists reveal improving `route_compute_relocate` moves, the
candidate-screening budget is the bottleneck. If the best rejected candidate is
still non-improving in all runs, the next algorithmic step should be a stronger
joint Route-Contact neighborhood rather than a larger CVX budget.


## Wide-shortlist seed-44 diagnostic: screening is part of the bottleneck

For K=80, E=2, scenario seed=44, algorithm seeds 100/101/102, the elite budget
was widened to:

- shortlist limit: 12;
- elite task limit: 6;
- route options per task: 3.

Results:

- seed 100: 210916.901 -> 210734.204 J (0.087% reduction), accepting
  `route_compute_relocate::S30->U4@19` followed by
  `batch_merge::G_U1_2->G_U1_1`;
- seeds 101/102 reported structurally accepted new-contact/batch-split moves but
  no meaningful change at the printed energy precision;
- aggregate mean gain: 0.029%;
- mean elite CVX calls: 22.67;
- mean elite runtime: 22.95 s.

This shows that the original top-6 global proxy shortlist can indeed miss an
improving structural move. However, simply doubling the exact-CVX budget is too
expensive for the small average gain.

Two refinements are therefore introduced instead of making 12 the default:

1. **diversity-preserving elite shortlist**: the top-k budget now preserves a
   quota from route relocate, contact, contact removal, batch merge, batch
   split/new contact, and mode/batch families before filling remaining slots by
   global proxy rank;
2. **meaningful improvement threshold**: exact elite moves must improve Stage-1
   energy by at least max(1 J, 1e-4 relative), preventing solver-level numerical
   noise from being recorded as a structural improvement.

The default shortlist remains small. The next test should rerun scenario seed 44
with the default elite budget (no explicit shortlist widening) and check whether
family-diverse screening recovers the route-compute improvement with much fewer
CVX calls.


## Default diverse-shortlist seed-44 rerun: route family needs targeted widening

With the family-diverse default elite budget restored (roughly 6 exact candidates
per round), K=80, E=2, scenario seed=44, algorithm seeds 100/101/102 produced:

- seed 100: no accepted move; best exact candidate was
  `route_compute_relocate::S72->U1@19` with only 0.007% improvement;
- seed 101: best exact candidate was a new-contact/batch-split move with
  approximately zero improvement;
- seed 102: best exact candidate was slightly non-improving;
- aggregate mean gain returned to 0.000%;
- mean elite CVX calls dropped from the wide-budget 22.67 to 6.67.

Combined with the previous wide-budget result, this isolates the bottleneck:
family diversity prevents whole-family starvation, but **one route-family
representative is still insufficient**. The useful seed-100 move
`route_compute_relocate::S30->U4@19` appears only when the route candidate
generation/ranking is widened.

The next refinement is **exact near-miss progressive widening**:

1. evaluate the small family-diverse shortlist first;
2. if no move clears the meaningful acceptance threshold, inspect the exact-CVX
   best candidate;
3. only when that candidate is a positive near miss (default trigger about
   0.002% relative improvement), widen the *same structural family*;
4. expand task/route-option generation for that family and evaluate only a few
   additional exact candidates;
5. clearly flat or non-improving states do not pay the wider CVX cost.

This should make seed 100 widen the route family because its 0.007% candidate is
promising, while seeds 101/102 should normally stay on the cheap path.

Recommended verification:

~~~powershell
git pull
uv run pytest
uv run python experiments\run_hybrid_validation.py --tasks 80 --mecs 2 --scenario-seeds 44 --algorithm-seeds 100,101,102 --iterations 100
~~~

The output now reports `progressive widening` diagnostics and the number of
additional exact candidates evaluated.


## Progressive widening seed-44 verification: keep the adaptive policy

K=80, E=2, scenario seed=44, algorithm seeds 100/101/102, default small
family-diverse shortlist with exact near-miss progressive widening:

| alg seed | base Stage-1 CVX (J) | hybrid Stage-1 CVX (J) | gain | elite CVX | outcome |
|---:|---:|---:|---:|---:|---|
| 100 | 210916.901 | 210748.036 | 0.080% | 16 | route-compute relocate accepted |
| 101 | 214161.876 | 214161.876 | 0.000% | 6 | no widening / no meaningful move |
| 102 | 215420.390 | 215420.390 | 0.000% | 7 | no widening / no meaningful move |

For seed 100, the initial exact shortlist found
`route_compute_relocate::S72->U1@19` with a 0.0066% near miss. This correctly
triggered route-family widening and recovered the stronger
`route_compute_relocate::S30->U4@19`, producing a 0.080% accepted reduction.

Round 2 then observed a `batch_merge` near miss of about 0.0066%; widening was
triggered, but the move remained below the configured meaningful acceptance
threshold and was not accepted. This is intentional: a positive exact delta is
not automatically promoted to a paper-relevant structural improvement.

Compared with the earlier always-wide 12-candidate experiment on the same three
algorithm seeds:

- mean elite CVX calls: 22.67 -> 9.67 (about 57% lower);
- mean elite runtime: 22.95 s -> 9.58 s (about 58% lower);
- seed-100 elite CVX calls: 24 -> 16;
- seed-100 accepted energy reduction retains most of the wide-search gain.

The adaptive elite-screening policy is therefore frozen for the next validation
stage:

[
\boxed{
\text{small diverse exact shortlist}
\rightarrow
\text{exact positive near-miss detection}
\rightarrow
\text{same-family progressive widening}
\rightarrow
\text{meaningful Stage-1 CVX acceptance}
}
]

The next work item is no longer shortlist tuning. It is cross-scenario and
cross-load validation of the frozen hybrid algorithm.

The paired validation script now also aggregates strict-optimal pairs, accepted
move families, widening frequency, exact-CVX budget and elite runtime overhead.


## Out-of-sample scenario 45/46/47 validation: hybrid mechanism is now robust

K=80, E=2, scenario seeds 45/46/47, algorithm seeds 100/101/102,
100 iterations, frozen adaptive elite-screening policy:

- 9/9 exploration baselines reached Stage-1 `optimal`;
- 8/9 hybrid runs reported a positive reduction before strict-final filtering;
- one run (scenario 45, algorithm seed 101) ended at
  `optimal_inaccurate` after elite refinement and must not be used as an
  exact-oracle paper datapoint;
- among the remaining 8 strict `optimal -> optimal` pairs, 7 improved and
  1 was unchanged;
- strict-pair mean of the per-run reductions: about 1.514%;
- strict-pair median reduction: about 1.223%;
- strict mean energy: 229858.489 -> 226262.535 J.

Accepted strict-optimal move families were diverse but route-compute relocation
dominated:

- `route_compute_relocate`: 7 accepted moves;
- `batch_merge`: 2;
- `contact_remove`: 2;
- `contact_point_replace`: 1;
- `contact_relocate`: 1.

This is much stronger evidence than the earlier scenario-42/44 diagnostics:
the proposed elite phase is no longer improving only one tuned scenario, and
the dominant accepted move remains the intended computing-aware route
relocation.

### Correctness hardening after this validation

The scenario-45/algorithm-101 `optimal_inaccurate` result exposed one remaining
oracle bug: the elite oracle rejected inaccurate *baselines* but still returned
the energy of an `optimal_inaccurate` *candidate* as a finite objective.

This is now fixed. `Stage1CVXObjectiveOracle.__call__` returns infinity unless
the candidate Stage-1 status is strictly `optimal`. Therefore an inaccurate
candidate cannot be accepted by the elite search.

The paired validation aggregate is also changed so its primary reported energy,
improvement, and improved/unchanged counts use only strict
`optimal -> optimal` pairs. Feasible-but-inaccurate rows remain available in
JSON as diagnostics, but no longer contaminate the paper-facing aggregate.

The next verification should rerun only the affected scenario-45 algorithm seed
101, then proceed to cross-load validation rather than further tuning the
K=80/E=2 neighborhood.


## Corrected scenario-45 seed-101 rerun and frozen K=80/E=2 out-of-sample result

After strict rejection of `optimal_inaccurate` elite candidates, the affected
scenario-45 / algorithm-seed-101 run was repeated:

- base Stage-1: `optimal`, 231476.995 J;
- hybrid Stage-1: `optimal`, 230813.478 J;
- reduction: 0.287%;
- accepted move: `route_compute_relocate::S35->U5@2`;
- elite CVX calls: 13.

Therefore the corrected out-of-sample scenario set 45/46/47 now contains nine
strict `optimal -> optimal` pairs:

- 8/9 improved;
- 1/9 unchanged;
- mean of per-run percentage reductions: about 1.378%;
- median reduction: 1.154%;
- mean base energy: about 230038.323 J;
- mean hybrid energy: about 226768.196 J;
- reduction of the mean energies: about 1.422%.

The corrected accepted-move counts are:

- `route_compute_relocate`: 8;
- `batch_merge`: 2;
- `contact_remove`: 2;
- `contact_point_replace`: 1;
- `contact_relocate`: 1.

This is sufficient to freeze the current K=80/E=2 hybrid algorithm for
cross-load validation. Further tuning on the same setting risks overfitting the
evaluation scenarios.

### Validation output preservation

`run_hybrid_validation.py` no longer overwrites a single
`outputs/results/hybrid_validation.json` file by default. It now writes a
parameterized deterministic filename such as:

~~~text
outputs/results/hybrid_validation_K80_E3_S45-46-47_A100-101-102_I100.json
~~~

An explicit `--output` path can still be supplied. The JSON also records the
experiment arguments so later cross-load aggregation remains reproducible.


## Workload sweep robustness: K=50 result and K=100 CVX primal guard

The first K=50, E=2 workload validation over scenario seeds 45/46/47 and
algorithm seeds 100/101/102 completed with 9/9 strict optimal pairs:

- 5/9 improved and 4/9 were unchanged;
- mean paired gain: 1.746%;
- median paired gain: 0.047%;
- accepted moves were dominated by `route_compute_relocate` (8), with one
  `batch_merge`.

The large gap between mean and median shows that K=50 currently has a
heterogeneous/outlier-driven gain distribution; it should not be summarized as
"light load always gives larger/smaller gain" without more seeds.

The first K=100, E=2 run exposed a solver robustness bug during a gray-zone CVX
refinement. CVXPY returned a nominal Stage-1 solution whose bandwidth primal
violated the modeled positive lower bound strongly enough that reduced
post-evaluation raised `ValueError: bandwidth_mhz must be positive`.

The CVX solver now:

1. validates bandwidth, MEC CPU, and local CPU primal values before reciprocal
   reduced-form evaluation;
2. clips only tiny numerical lower-bound violations;
3. retries another installed conic solver for material/non-finite primal
   violations;
4. returns a non-feasible `invalid_primal` result if all solver candidates
   produce unusable resource primals, allowing the screened ALNS evaluator to
   penalize the state instead of terminating the experiment.

The hybrid validation script also checkpoints its JSON after every completed
run with `complete=false`, so later failures no longer discard expensive
earlier workload results. A successful completion rewrites the same file with
the aggregate and `complete=true`.


## Workload sensitivity checkpoint: K=50/80/100 at E=2

With the frozen hybrid algorithm and scenario seeds 45/46/47:

| K | strict pairs / runs | strict improved | mean paired gain | median paired gain | base status issue |
|---:|---:|---:|---:|---:|---|
| 50 | 9/9 | 5/9 | 1.746% | 0.047% | none |
| 80 | 9/9 | 8/9 | 1.378% | 1.154% | none |
| 100 | 2/9 | 2/2 | 0.665% | 0.665% | 3 infeasible-precheck, 4 optimal-inaccurate |

The K=100 result must not be interpreted as a directly comparable 0.665% hybrid
gain over the full nine-run workload sample. Only two runs reached strict
`optimal -> optimal` Stage-1 status. The dominant K=100 effect under the current
100-iteration budget is therefore **search/solver robustness loss**, not a clean
energy-gain trend.

The three `infeasible_precheck` outcomes certify only that the final fixed
discrete states fail optimistic lower bounds; they do not prove that the entire
K=100 scenario instance is globally infeasible. Likewise,
`optimal_inaccurate` is treated as a numerical-oracle failure for paper-facing
statistics.

K=50 also shows a skewed gain distribution: the mean 1.746% is driven by a few
large improvements (including 4.952% and 8.584%), while the median is only
0.047%. K=80 is currently the most consistently informative operating point.

The validation aggregate now reports strict-pair rate and the Stage-1 status mix
explicitly so overload/search-failure regimes are not hidden behind conditional
energy averages.

The next most informative experiment is K=100, E=3. It tests whether adding one
MEC restores strict feasibility/numerical stability under high task load while
holding the workload fixed.


## High-load MEC-count checkpoint: K=100, E=3 partially restores robustness

With the frozen hybrid algorithm, scenario seeds 45/46/47, algorithm seeds
100/101/102, and 100 ALNS iterations:

| E | strict pairs / runs | strict rate | strict improved | strict unchanged | infeasible-precheck | optimal-inaccurate | strict mean gain | strict median gain |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 2/9 | 0.222 | 2/2 | 0/2 | 3 | 4 | 0.665% | 0.665% |
| 3 | 6/9 | 0.667 | 5/6 | 1/6 | 1 | 2 | 0.562% | 0.255% |

Adding the third MEC therefore raises the strict-pair rate from 22.2% to 66.7%
and reduces non-strict baseline outcomes from seven runs to three. This is a
clear **partial robustness recovery**, but it is not yet a full recovery.

For E=3, the six strict runs contain five meaningful improvements and one
unchanged run. Accepted structural moves remain dominated by the intended
computing-aware route neighborhood:

- `route_compute_relocate`: 5 accepted moves;
- `batch_merge`: 3;
- `contact_point_replace`: 1.

The three non-strict E=3 runs are:

- scenario 45 / algorithm 100: `optimal_inaccurate`;
- scenario 46 / algorithm 101: `optimal_inaccurate`;
- scenario 46 / algorithm 102: `infeasible_precheck`.

Crucially, scenarios 45 and 46 also have other algorithm seeds that reach strict
`optimal -> optimal` status. Thus these failures cannot be interpreted as
evidence that the corresponding K=100/E=3 scenario instance is globally
infeasible. They are consistent with **search-trajectory and numerical-oracle
sensitivity at the current 100-iteration budget**.

The E=2 and E=3 conditional gain means must not be compared as if they covered
the same population: 0.665% for E=2 is based on only 2 strict pairs, whereas
0.562% for E=3 is based on 6 strict pairs. The robust conclusion at this stage is
about **strict feasibility/numerical stability**, not a monotone energy-gain
trend with MEC count.

### Next diagnostic

Before changing the physical MEC count again, rerun only the three failed E=3
seed pairs with a larger search budget. This isolates search-budget sensitivity
without paying for another full nine-run sweep:

~~~powershell
uv run python experiments\run_hybrid_validation.py --tasks 100 --mecs 3 --scenario-seeds 45 --algorithm-seeds 100 --iterations 200
uv run python experiments\run_hybrid_validation.py --tasks 100 --mecs 3 --scenario-seeds 46 --algorithm-seeds 101 --iterations 200
uv run python experiments\run_hybrid_validation.py --tasks 100 --mecs 3 --scenario-seeds 46 --algorithm-seeds 102 --iterations 200
~~~

If these runs recover strict Stage-1 status, the remaining E=3 failures are
primarily a search-budget issue. If they remain non-strict, the next full
physical-resource sensitivity point should be K=100, E=4 at the frozen
100-iteration budget.


## K=100, E=3 search-budget diagnostic: only the precheck failure recovers

The three non-strict K=100/E=3 seed pairs were rerun with the ALNS budget
increased from 100 to 200 iterations:

| scenario | alg seed | I=100 status | I=200 status | I=200 gain | interpretation |
|---:|---:|---|---|---:|---|
| 45 | 100 | optimal_inaccurate | optimal_inaccurate | - | unchanged numerical-oracle/stagnation case |
| 46 | 101 | optimal_inaccurate | optimal_inaccurate | - | unchanged numerical-oracle/stagnation case |
| 46 | 102 | infeasible_precheck | optimal | 0.512% | recovered with larger search budget |

The two persistent `optimal_inaccurate` runs also return exactly the same
Stage-1 energies as at 100 iterations:

- scenario 45 / alg 100: 247361.688 J;
- scenario 46 / alg 101: 251179.504 J.

Thus doubling the ALNS budget does **not** generally resolve the remaining
K=100/E=3 failures. One failure is clearly search-budget sensitive, while the
two inaccurate cases are better treated as persistent solver-conditioning or
search-stagnation diagnostics.

The recovered scenario-46 / alg-102 run is structurally informative:

- base Stage-1: 244505.144 J;
- hybrid Stage-1: 243252.611 J;
- reduction: 0.512%;
- accepted moves:
  `route_compute_relocate::S61->U3@13` and
  `batch_split_or_new_contact::S22::E1_C@26`.

This continues to support the joint route-compute/contact mechanism at high
load.

The validation script now records and prints Stage-1 solver/fallback diagnostics
for non-strict runs, so future `optimal_inaccurate` outcomes can distinguish
which conic solver returned which status.

### Next full sensitivity point

Keep the paper-facing search budget frozen at 100 iterations and increase the
physical MEC count:

~~~powershell
git pull
uv run python experiments\run_hybrid_validation.py --tasks 100 --mecs 4 --scenario-seeds 45,46,47 --algorithm-seeds 100,101,102 --iterations 100
~~~

This is the clean next comparison because it changes only MEC availability while
keeping workload, seeds, algorithm, and search budget fixed.


## K=100 MEC-count sensitivity completed: E=4 restores strict robustness

With K=100, scenario seeds 45/46/47, algorithm seeds 100/101/102, and the
paper-facing ALNS budget frozen at 100 iterations, the MEC-count sweep is now:

| E | strict pairs / runs | strict rate | strict improved | strict unchanged | infeasible-precheck | optimal-inaccurate | strict mean gain | strict median gain |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 2/9 | 0.222 | 2/2 | 0/2 | 3 | 4 | 0.665% | 0.665% |
| 3 | 6/9 | 0.667 | 5/6 | 1/6 | 1 | 2 | 0.562% | 0.255% |
| 4 | 9/9 | 1.000 | 8/9 | 1/9 | 0 | 0 | 0.555% | 0.063% |

The strongest result is the strict-pair recovery:

\[
\boxed{
22.2\% \; (E=2)
\rightarrow
66.7\% \; (E=3)
\rightarrow
100\% \; (E=4)
}
\]

under the same workload, scenario seeds, algorithm seeds, and search budget.

Therefore increasing MEC availability clearly improves fixed-discrete
resource-solve robustness at K=100. In this sampled sweep, E=4 completely removes
the observed `infeasible_precheck` and `optimal_inaccurate` outcomes.

For E=4, 8/9 strict pairs improve and one is unchanged. Accepted move families:

- `route_compute_relocate`: 6;
- `batch_merge`: 4;
- `contact_point_replace`: 1;
- `contact_relocate`: 1.

The intended computing-aware route mechanism therefore remains active even when
MEC deployment is denser.

The E=4 paired gains are highly skewed:

- mean strict per-run gain: 0.555%;
- median strict per-run gain: 0.063%;
- large gains include 1.430%, 0.973%, 0.838%, and 1.636%.

Thus the mean should not be interpreted as a typical per-instance gain. The
median shows that many E=4 runs have only small residual room for elite
structural improvement.

This pattern is consistent with the working hypothesis that denser MEC
availability weakens Route-Contact-Offloading coupling and reduces the marginal
value of structural intensification. However, the E=2 conditional mean is based
on only two strict pairs, so a formal monotone energy-gain claim across E should
not be made from this sweep alone.

The robust paper-facing conclusion from this experiment is instead:

> Under high task load, sparse MEC deployment strongly increases search/resource
> difficulty. Adding MEC opportunities progressively restores strict Stage-1
> feasibility/numerical stability, while the proposed hybrid structural phase
> continues to produce non-increasing exact energy on strict pairs.

The K=100 MEC-count sensitivity is now considered complete for the frozen
100-iteration algorithm.
