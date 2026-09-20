# UAV-MEC Patrol Research Codebase v0.3.2

面向当前已锁定的论文第一项工作：

[
\text{Multi-UAV Patrol}
+\text{Optional MEC Contact}
+\text{Store-Carry-Batch-Offload}
+\text{CPU/Bandwidth Allocation}
]

主目标为 UAV 机群总能耗最小化；任务 deadline、平均时延、巡护周期和 UAV 电量为硬约束。

v0.3.2 修复 contactless/idle UAV 在 CVXPY 模型中产生 Python bool 约束的问题；v0.3.1 延续 v0.3.0 的 KKT/Dual/Bisection 资源求解器，并新增 **hard-regime stress validation**、CVX Stage-1 reduced-timeline 复核与 KKT termination diagnostics。v0.3.0 的核心能力是：**`P1-R` 已同时具备 CVXPY correctness oracle 与独立的 KKT/Dual/Bisection Stage-1 求解器。** 后续外层 Greedy / Local Search / ALNS 可以通过统一 `ResourceSolver` 接口选择资源评价器，而不再与具体求解实现耦合。

## 1. 当前开发状态

```text
P1-D: Route + Contact + Batch + Local/Offload
        ↓
Fixed discrete solution D
        ↓
P1-R resource recourse
        ├── CVXResourceSolver   # correctness oracle + Stage 2
        └── KKTResourceSolver   # fast Stage-1 evaluator
```

当前已完成：

- 强类型领域模型与离散解表示；
- Store-Carry-Offload validator；
- event timeline / FIFO / EDF 构造；
- `P1-R` DCP 凸模型；
- 不可行候选的 optimistic precheck；
- CVXPY 两阶段字典序资源求解；
- KKT 驻点验证；
- **独立 KKT/Dual/Bisection Stage-1 solver**；
- seeded small validation generator；
- CVX/KKT 交叉验证脚本；
- pytest 回归测试。

尚未开始正式实现：

- paper-scale instance generator；
- greedy initial solution；
- local search；
- problem-specific ALNS operators；
- shadow-price-assisted repair；
- exact/GBD small benchmark。

## 2. 工程结构

```text
uav_mec_research_v0_3_2/
├── pyproject.toml
├── README.md
├── CHANGELOG_v0.3.0.md
├── CHANGELOG_v0.3.1.md
├── CHANGELOG_v0.3.2.md
├── configs/
│   ├── small.yaml
│   └── baseline.yaml
├── src/uav_mec/
│   ├── domain/
│   ├── instances/
│   ├── evaluation/
│   ├── optimization/resource/
│   └── algorithms/alns/
├── experiments/
├── tests/
└── outputs/
```

## 3. uv 环境

项目根目录执行：

```powershell
uv sync --dev
```

运行所有测试：

```powershell
uv run pytest
```

如果 Windows 上出现 uv hardlink warning，只影响安装方式，不影响结果；可选：

```powershell
uv sync --dev --link-mode=copy
```

## 4. 最小验证

```powershell
uv run python experiments\run_small_validation.py
```

已知基准 Stage-1 UAV energy 应约为：

```text
35440.746287 J
```

## 5. CVX/KKT 批量交叉验证

```powershell
uv run python experiments\run_kkt_cross_validation.py --seeds 30
```

输出：

```text
outputs/results/kkt_cross_validation.json
```

这里比较的是：

[
\boxed{\text{CVXPY Stage-1}\quad vs\quad\text{KKT Stage-1}}
]

## 6. hard-regime stress validation

```powershell
uv run python experiments\run_resource_stress_validation.py
```

当前包含：

- `tight_bandwidth`
- `tight_mec_cpu`
- `tight_avg_delay`
- `local_fifo`
- `same_mec_multi_contact`
- `two_mec`
- `infeasible_deadline`

## 7. 统一 ResourceSolver 接口

```python
from uav_mec.optimization.resource import CVXResourceSolver, KKTResourceSolver

resource_solver = KKTResourceSolver()
result = resource_solver.solve(instance, discrete_solution, event_info)
```

调试或 correctness check 时可替换为 `CVXResourceSolver`。

## 8. 当前求解器定位

```text
CVXPY = correctness oracle + final reporting
KKT   = fast outer-search evaluator
```

## 9. 下一开发阶段

在 CVX/KKT seeded validation 与 hard-regime validation 均通过后冻结 P1-R，进入 P1-D：

1. paper-scale instance generator；
2. greedy initial solution；
3. route/contact/mode 基础 local search；
4. 接入 `alns` 框架；
5. contact insert/remove/replace；
6. batch split/merge/reassign；
7. shadow-price-assisted repair。
