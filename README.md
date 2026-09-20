# UAV-MEC Patrol Research Codebase

> 面向“大型林区固定监测节点周期巡护下的多无人机协同边缘计算”场景的研究代码。  
> 当前主线：**Route–Contact–Offloading–Resource Coupling**。

## 0. README 用法：任务清单 + 研究路线图

本 README 不仅用于说明如何运行代码，也作为论文第一项工作的**长期任务清单、阶段记录和开发参考**。

状态约定：

- [x] 已完成并通过当前验证；
- [ ] **[VERIFY]** 已实现，但还需要本地实验/回归测试确认；
- [ ] **[TODO]** 尚未实现；
- [ ] **[OPTIONAL]** 只有实验表明确有收益时才加入。

当前代码版本：**v0.5.0**  
主开发分支：**develop**

---

# 1. 研究目标

论文场景：

[
oxed{	ext{大型林区固定监测节点周期巡护下的多无人机协同边缘计算}}
]

系统链路：

[
	ext{固定监测节点}
ightarrow
	ext{多 UAV 巡护/采集/缓存/携带/有限机载计算}
ightarrow
	ext{稀疏异构 MEC 边缘站}
]

核心机制：

[
oxed{	ext{空间间歇边缘连接 / Contact Opportunity}}
]

核心耦合：

[
oxed{	ext{Route–Contact–Offloading–Resource Coupling}}
]

主目标：

[
oxed{min E_{mathrm{UAV}}^{mathrm{tot}}}
]

主要约束：

- 单任务 deadline；
- 平均任务时延；
- UAV 周期返航约束；
- UAV 电池约束；
- MEC 带宽容量；
- MEC CPU 容量；
- Store–Carry–Batch-Offload 时序与 FIFO/EDF 约束。

工作标题：

> 面向间歇边缘连接的大型林区多无人机巡护路径、计算卸载与资源分配联合优化

---

# 2. 总体求解架构

完整问题拆成：

[
(P1):quad
min_{mathbf D,mathbf R}
E_{mathrm{UAV}}(mathbf D,mathbf R)
]

其中离散变量：

[
mathbf D=
{	ext{UAV assignment, route, contact, Local/MEC, batch}}
]

连续资源变量：

[
mathbf R=
{	ext{UAV CPU, MEC bandwidth, MEC CPU, upload time, event times}}
]

采用：

[
V(mathbf D)
=
min_{mathbf Rinmathcal R(mathbf D)}
E_{mathrm{UAV}}(mathbf D,mathbf R)
]

外层：

[
(P1-D):quad min_{mathbf D}V(mathbf D)
]

内层：

[
(P1-Rmidmathbf D):quad min_{mathbf R}E_{mathrm{UAV}}
]

目标算法结构：

[
oxed{
	ext{Greedy Route Seed}
ightarrow
	ext{MEC Contact/Offloading Repair}
ightarrow
	ext{Problem-Specific ALNS}
ightarrow
	ext{KKT Resource Recourse}
}
]

定位说明：

- **Greedy**：主要用于初始解构造，也可额外作为 Greedy-only baseline；
- **VRP**：是路径子问题的结构，不是一种算法；
- **ALNS**：主元启发式搜索框架；
- **ACO / GA**：可作为外部元启发式 baseline，不属于当前主算法；
- **KKT / Convex**：负责固定离散解后的连续资源优化；
- **Chaos perturbation**：当前不加入，除非后续实验显示 ALNS 对初始解高度敏感。

---

# 3. 里程碑与当前进度

## M0. 场景与数学模型

- [x] 锁定大型林区固定监测节点周期巡护场景；
- [x] 固定多 UAV + 稀疏异构固定 MEC 架构；
- [x] 固定 Store–Carry–Batch-Offload 机制；
- [x] 固定周期内准静态带宽/CPU 切片；
- [x] 固定 UAV 本地 FIFO；
- [x] 固定 MEC 同 UAV/MEC 虚拟队列 FIFO、批内 EDF；
- [x] 明确 UAV 无需等待 MEC 完成计算；
- [x] 明确主目标为 UAV 总能耗最小化；
- [x] 完成 P1-D / P1-R 分解。

---

## M1. P1-R 连续资源层

### 模型

- [x] Event timeline；
- [x] Local FIFO；
- [x] MEC FIFO / EDF；
- [x] upload epigraph；
- [x] bandwidth capacity；
- [x] MEC CPU capacity；
- [x] deadline / avg-delay / cycle / battery；
- [x] CVXPY DCP 参考模型；
- [x] optimistic infeasibility precheck。

### KKT / Dual Solver

- [x] UAV CPU cube-root KKT；
- [x] MEC CPU square-root KKT；
- [x] bandwidth dual price + bisection；
- [x] event-graph shadow-price backward propagation；
- [x] KKT stationarity verifier；
- [x] primal feasibility；
- [x] dual feasibility；
- [x] complementary slackness；
- [x] complementarity-aware stopping rule；
- [x] lexicographic Stage-2 保留在 CVXPY oracle。

### 已验证结果

当前 hard-regime stress validation 中，所有可行测试均与 CVXPY Stage-1 高度一致：

[
oxed{
max 	ext{ relative energy gap}
=
1.233	imes 10^{-9}
}
]

当前记录：

- max KKT stationarity residual: (7.13	imes10^{-12})
- max primal residual: (1.876	imes10^{-3})
- max dual residual: (0)
- two-MEC 场景相对能耗 gap: (9.755	imes10^{-12})

结论：

[
oxed{	ext{P1-R 已冻结}}
]

当前定位：

[
oxed{	ext{CVXPY = correctness oracle}}
]

[
oxed{	ext{KKT = outer-search resource evaluator}}
]

---

## M2. Paper-scale Instance Generator

- [x] 1000 m × 1000 m 林区；
- [x] (K=30/50/80/100)；
- [x] (M=3/5/8)；
- [x] (E=2/3/4)；
- [x] fixed heterogeneous MEC sites；
- [x] MEC 连续覆盖区域离散为 candidate contact points；
- [x] seed-controlled monitoring nodes；
- [x] seed-controlled task size / cycles-per-bit；
- [x] optimistic individual-deadline lower-bound guard；
- [x] reproducibility tests；
- [x] geometry/range regression tests。

已完成 sanity scan：

| K | M | E | Contacts | Mean data (MB) | Mean workload (Gcy) | Mean deadline (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 5 | 3 | 37 | 2.501 | 20.529 | 324.67 |
| 50 | 5 | 3 | 37 | 2.476 | 19.983 | 329.23 |
| 80 | 5 | 3 | 37 | 2.511 | 20.063 | 336.58 |
| 100 | 5 | 3 | 37 | 2.486 | 20.013 | 336.15 |

注意：当前 cycle、avg-delay、deadline 区间、MEC 坐标等仍属于**实验校准参数**，不是理论常数。

---

## M3. Greedy Initial Route

当前 Greedy 的定位：

[
oxed{	ext{初始解构造器}}
]

实现结构：

[
	ext{Parallel Greedy Insertion}
ightarrow
	ext{2-opt}
]

- [x] Task-to-UAV assignment；
- [x] deadline-aware insertion；
- [x] cycle-aware insertion；
- [x] route-distance insertion cost；
- [x] route-local 2-opt；
- [x] deterministic construction；
- [x] solution validity；
- [x] all-local initial seed。

当前 paper-scale 路由 sanity：

| K | Total km | Max return (s) | Cycle overflow (s) | Tasks/UAV [min,max] |
|---:|---:|---:|---:|---:|
| 30 | 10.187 | 231.37 | 0.00 | [3,14] |
| 50 | 11.277 | 246.22 | 0.00 | [4,17] |
| 80 | 12.853 | 292.04 | 0.00 | [9,21] |
| 100 | 13.485 | 304.82 | 0.00 | [12,24] |

重要观察：

[
oxed{	ext{路径层可行} 
otRightarrow 	ext{计算层可行}}
]

K=30/50 的 all-local seed 均出现：

[
	exttt{kkt_no_feasible_iterate}
]

说明瓶颈主要来自 local FIFO / deadline / avg-delay，而不是纯巡护路径。

---

## M4. MEC Contact / Offloading Initial Repair

目标：

[
	ext{All-Local Seed}
ightarrow
	ext{Critical Task Detection}
ightarrow
	ext{Local}ightarrow	ext{MEC}
ightarrow
	ext{Contact Insertion / Reuse}
]

当前实现：

- [ ] **[VERIFY]** critical-local-task detection；
- [ ] **[VERIFY]** equal-share resource proxy；
- [ ] **[VERIFY]** normalized infeasibility ranking；
- [ ] **[VERIFY]** Local→MEC mode switch；
- [ ] **[VERIFY]** new contact insertion；
- [ ] **[VERIFY]** reuse existing later contact；
- [ ] **[VERIFY]** Store–Carry–Batch-Offload；
- [ ] **[VERIFY]** per-MEC candidate preservation；
- [ ] **[VERIFY]** deterministic MEC repair；
- [ ] **[VERIFY]** final exact KKT feasibility check。

当前待跑：

```powershell
uv run python experiments\run_mec_repair_sanity.py --tasks 30,50
```

关键判据：

[
oxed{
	ext{all-local infeasible}
ightarrow
	ext{MEC-repaired feasible}
}
]

---

## M5. Mature ALNS Framework Integration

当前使用成熟外部包：

[
oxed{	exttt{alns>=7.0,<8.0}}
]

通用机制交给外部框架：

- adaptive operator selection；
- RouletteWheel；
- Record-to-Record Travel；
- stopping criteria；
- iteration loop。

项目自身只实现领域相关逻辑。

### 当前已实现但待本地验证

Destroy：

- [ ] **[VERIFY]** random task removal；
- [ ] **[VERIFY]** deadline/compute-critical removal；
- [ ] **[VERIFY]** route-segment removal。

Repair：

- [ ] **[VERIFY]** cheapest insertion；
- [ ] **[VERIFY]** regret-2 insertion；
- [ ] **[VERIFY]** route repair 后 MEC repair。

Objective：

- [ ] **[VERIFY]** ProxyObjectiveEvaluator；
- [ ] **[VERIFY]** KKTObjectiveEvaluator；
- [ ] **[VERIFY]** solution-signature cache；
- [ ] **[VERIFY]** finite infeasibility penalty。

Runner：

- [ ] **[VERIFY]** external ALNS integration；
- [ ] **[VERIFY]** valid best-state return；
- [ ] **[VERIFY]** exact final KKT validation。

当前 smoke-test：

```powershell
uv run python experiments\run_alns_sanity.py --tasks 30 --iterations 30 --objective proxy
```

然后：

```powershell
uv run python experiments\run_alns_sanity.py --tasks 30 --iterations 10 --objective kkt
```

---

## M6. Problem-Specific ALNS Operators

这是后续论文算法的核心开发区。

### Route operators

- [ ] **[TODO]** relocate；
- [ ] **[TODO]** swap；
- [ ] **[TODO]** inter-route 2-opt / segment exchange；
- [ ] **[TODO]** compute-aware relocate；
- [ ] **[TODO]** deadline-critical route repair。

### Contact operators

- [ ] **[TODO]** contact insert；
- [ ] **[TODO]** contact remove；
- [ ] **[TODO]** contact replace；
- [ ] **[TODO]** candidate-point shift；
- [ ] **[TODO]** same-MEC repeated-contact restructuring。

### Batch / Offloading operators

- [ ] **[TODO]** Local→MEC；
- [ ] **[TODO]** MEC→Local；
- [ ] **[TODO]** MEC reassignment；
- [ ] **[TODO]** batch split；
- [ ] **[TODO]** batch merge；
- [ ] **[TODO]** batch reassign。

### Resource-aware repair

- [ ] **[TODO]** deadline dual (alpha_k) guided repair；
- [ ] **[TODO]** avg-delay dual (eta) guided repair；
- [ ] **[TODO]** bandwidth shadow price (lambda_e^B) guided repair；
- [ ] **[TODO]** MEC CPU shadow price (lambda_e^F) guided repair；
- [ ] **[TODO]** congestion-aware MEC switching；
- [ ] **[TODO]** shadow-price-assisted candidate pruning。

---

## M7. Local Search Layer

- [ ] **[TODO]** route-only local search；
- [ ] **[TODO]** contact-only local search；
- [ ] **[TODO]** Local/MEC mode local search；
- [ ] **[TODO]** mixed neighborhood；
- [ ] **[TODO]** first-improvement / best-improvement comparison；
- [ ] **[TODO]** runtime profile。

Local Search 既可以：

1. 单独作为 baseline；
2. 用于 ALNS repair 后的 intensification。

---

## M8. Baseline Algorithms

计划至少包含：

- [ ] **[TODO]** Greedy-only；
- [ ] **[TODO]** Route-only + KKT；
- [ ] **[TODO]** Local-only；
- [ ] **[TODO]** nearest-MEC offloading；
- [ ] **[TODO]** mature VRP routing baseline（优先考虑 PyVRP）；
- [ ] **[TODO]** generic metaheuristic baseline（ACO 或 GA 中至少一个）；
- [ ] **[TODO]** Proposed ALNS + KKT。

说明：

- Greedy 是初始解构造器，但“停在 Greedy 阶段”可以额外定义为 Greedy-only baseline；
- ACO 与 Greedy、ALNS 是不同算法；
- PyVRP 主要用于 routing baseline，而不是替代 Route–Contact–Offloading 联合搜索。

---

## M9. Small Exact / Strong Benchmark

- [ ] **[TODO]** (K=8sim12) 小规模 exact/near-exact benchmark；
- [ ] **[TODO]** Gurobi/SCIP/GBD 可行性评估；
- [ ] **[TODO]** optimality-gap comparison；
- [ ] **[TODO]** heuristic quality validation。

---

## M10. Experiment Calibration / Non-degeneracy

需要确保问题既不是“全部本地最优”，也不是“全部卸载最优”。

- [ ] **[TODO]** Local-only feasibility rate；
- [ ] **[TODO]** Offload ratio；
- [ ] **[TODO]** average deadline utilization；
- [ ] **[TODO]** cycle utilization；
- [ ] **[TODO]** battery utilization；
- [ ] **[TODO]** MEC bandwidth utilization；
- [ ] **[TODO]** MEC CPU utilization；
- [ ] **[TODO]** contact count / UAV；
- [ ] **[TODO]** repeated same-MEC contacts；
- [ ] **[TODO]** route detour caused by MEC；
- [ ] **[TODO]** nearest-MEC 与 resource-aware MEC 选择差异；
- [ ] **[TODO]** (T^{cycle}) calibration；
- [ ] **[TODO]** avg-delay budget calibration；
- [ ] **[TODO]** deadline distribution calibration。

---

## M11. Main Experiments

### Scale

- [ ] **[TODO]** (K=30,50,80,100)；
- [ ] **[TODO]** (M=3,5,8)；
- [ ] **[TODO]** (E=2,3,4)。

### Performance

- [ ] **[TODO]** total UAV energy；
- [ ] **[TODO]** average task delay；
- [ ] **[TODO]** worst deadline slack；
- [ ] **[TODO]** route distance；
- [ ] **[TODO]** contact count；
- [ ] **[TODO]** offload ratio；
- [ ] **[TODO]** runtime；
- [ ] **[TODO]** convergence curve；
- [ ] **[TODO]** feasibility rate。

### Ablation

- [ ] **[TODO]** without contact-specific operators；
- [ ] **[TODO]** without batch-aware repair；
- [ ] **[TODO]** without KKT dual guidance；
- [ ] **[TODO]** without adaptive operator selection；
- [ ] **[TODO]** Greedy initialization vs random initialization；
- [ ] **[OPTIONAL]** chaos initialization，仅在初始化敏感性明显时评估。

---

# 4. 当前代码结构

```text
uav-mec-patrol/
├── configs/
│   ├── small.yaml
│   └── baseline.yaml
├── src/uav_mec/
│   ├── domain/
│   ├── instances/
│   │   ├── small.py
│   │   ├── random_validation.py
│   │   ├── stress_validation.py
│   │   └── paper_scale.py
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
```

---

# 5. 环境与常用命令

安装/同步：

```powershell
uv sync --dev
```

全部测试：

```powershell
uv run pytest
```

Windows hardlink warning 不影响正确性。如需关闭：

```powershell
$env:UV_LINK_MODE="copy"
```

---

# 6. 已有验证脚本

P1-R small validation：

```powershell
uv run python experiments\run_small_validation.py
```

CVX/KKT cross validation：

```powershell
uv run python experiments\run_kkt_cross_validation.py --seeds 30
```

Hard-regime resource validation：

```powershell
uv run python experiments\run_resource_stress_validation.py
```

Paper-scale generator：

```powershell
uv run python experiments\run_instance_sanity.py
```

Greedy route seed：

```powershell
uv run python experiments\run_initial_solution_sanity.py --tasks 30,50,80,100
```

Greedy all-local + KKT：

```powershell
uv run python experiments\run_initial_solution_sanity.py --tasks 30,50 --solve-resources
```

MEC repair：

```powershell
uv run python experiments\run_mec_repair_sanity.py --tasks 30,50
```

ALNS proxy smoke test：

```powershell
uv run python experiments\run_alns_sanity.py --tasks 30 --iterations 30 --objective proxy
```

ALNS exact-KKT smoke test：

```powershell
uv run python experiments\run_alns_sanity.py --tasks 30 --iterations 10 --objective kkt
```

---

# 7. 当前“下一步”清单

按优先级执行：

1. [ ] **[VERIFY]** 拉取 v0.5.0 后运行 `uv sync --dev`；
2. [ ] **[VERIFY]** 运行完整 pytest；
3. [ ] **[VERIFY]** 跑 `run_mec_repair_sanity.py --tasks 30,50`；
4. [ ] **[VERIFY]** 跑 ALNS proxy smoke test；
5. [ ] **[VERIFY]** 跑 ALNS KKT smoke test；
6. [ ] **[TODO]** 根据结果决定是否先修 MEC repair；
7. [ ] **[TODO]** 加 Contact Remove/Replace/Shift；
8. [ ] **[TODO]** 加 Batch Split/Merge/Reassign；
9. [ ] **[TODO]** 加 KKT dual-guided repair；
10. [ ] **[TODO]** 做 non-degeneracy scan；
11. [ ] **[TODO]** 冻结最终 baseline 参数；
12. [ ] **[TODO]** 跑主实验、消融和 baseline comparison。

---

# 8. 研究开发原则

1. **不为了“看起来复杂”而堆算法模块。**
2. 通用算法机制优先复用成熟实现。
3. 论文贡献集中在问题特定结构：
   - route-dependent intermittent MEC contact；
   - Store–Carry–Batch-Offload；
   - contact/batch/mode joint operators；
   - KKT resource recourse；
   - shadow-price-aware repair。
4. Greedy、ACO、ALNS、VRP 必须区分层级与角色。
5. Chaos perturbation 只有在实验显示初始化敏感性时才考虑。
6. 所有新增模块都要通过：
   - validity test；
   - numerical sanity；
   - ablation；
   - runtime/benefit comparison。
7. 每次参数调整都要有 non-degeneracy 或实验依据，避免人为制造“算法优势”。

---

# 9. 当前阶段结论

已经完成并基本冻结：

[
oxed{	ext{System Model}}
]

[
oxed{	ext{P1-R Convex/KKT Resource Layer}}
]

[
oxed{	ext{Paper-scale Instance Generator}}
]

[
oxed{	ext{Greedy Route Initializer}}
]

当前正在打通：

[
oxed{
	ext{MEC Repair}
ightarrow
	ext{ALNS}
ightarrow
	ext{KKT}
}
]

当 v0.5.0 smoke tests 全部通过后，下一阶段重点将不再是搭框架，而是实现和验证真正的问题特定算子。
