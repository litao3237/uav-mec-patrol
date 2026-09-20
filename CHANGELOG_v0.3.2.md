# Changelog v0.3.2

本版本是 v0.3.1 的建模健壮性 hotfix，不改变 P1-R 数学定义。

## Fixed

- 修复 `local_fifo` 压力场景中，UAV 没有 MEC contact 时 `return_time` 退化成 Python `float`，从而使 `cycle` 约束在建模阶段被求值为 Python `bool` 的问题；
- 所有 constant-only 时间/能耗分支现在显式使用 `cvxpy.Constant`；
- 空资源项统一通过 `cvx_sum(...)` 返回 CVXPY scalar expression；
- `add(...)` 对 Python bool 做语义保持的 CVXPY constant-constraint 归一化，并对非 CVXPY constraint 立即报错；
- `_snapshot_duals(...)` 增加约束类型防御检查。

## Added

- `test_cvx_stress_models_register_only_cvx_constraints`；
- `test_cvx_local_fifo_contactless_uav_case_solves_without_bool_constraint`。

## Root cause

无 MEC contact 的 UAV 会产生 constant-only return-time 约束。旧代码让 Python 先计算 `<=`，得到 `True/False` 而不是 CVXPY `Constraint`，随后 dual snapshot 访问 `con.dual_value` 时崩溃。
