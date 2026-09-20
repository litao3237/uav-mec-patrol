# Changelog v0.3.1

本版本不改变已锁定的 P1-R 数学模型，重点强化资源求解器验证边界。

## Added

- `instances/stress_validation.py`：定向 hard-regime 验证实例；
- `experiments/run_resource_stress_validation.py`：CVXPY/KKT 压力交叉验证；
- `tests/test_resource_stress_cases.py`：资源紧约束、FIFO、不可行分支回归测试；
- KKT diagnostics 中新增 `termination_reason` 与 `converged`。

## Changed

- CVXPY Stage-1 结果会再经过 reduced event-timeline evaluator 复算，记录 deadline/cycle/battery primal violations；
- 版本号升级至 `0.3.1`。

## Why

30 个随机 perturbation 已显示 Stage-1 能耗 CVX/KKT 最大相对 gap 约为 `1.1e-10`，本版本继续覆盖 MEC CPU 紧约束、平均时延紧约束、多 Local FIFO、多 contact FIFO、多 MEC 和不可行实例。
