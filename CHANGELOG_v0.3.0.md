# Changelog v0.3.0

## 目标

v0.3.0 将 `P1-R` 从“仅由 CVXPY 验证的凸模型”推进到“CVXPY 参考解 + 可独立运行的解析 KKT/Dual 求解器”。

## 新增

- `optimization/resource/analytic.py`
  - 上传速率、上传时间及其导数；
  - UAV 本地 CPU 立方根 KKT 闭式；
  - MEC CPU 平方根水位分配；
  - 带宽价格双层二分。
- `optimization/resource/reduced.py`
  - 消去 CVXPY 中的时间 epigraph 变量；
  - 按固定 FIFO/EDF 规则直接重建采集、上传、本地计算、MEC 计算和返航时间线。
- `optimization/resource/kkt_solver.py`
  - Stage-1 UAV 能耗问题的解析 KKT / 对偶迭代求解器；
  - 时间影子价格沿 Local FIFO 和 MEC FIFO/EDF 事件图反向传播；
  - 自动输出近似 dual prices，供后续 ALNS resource-aware repair 使用。
- `optimization/resource/solver.py`
  - `ResourceSolver` 统一接口；
  - `CVXResourceSolver` 与 `KKTResourceSolver` 可互换，便于后续注入 ALNS。
- `instances/random_validation.py`
  - 基于已人工核验 K=5 拓扑的 seeded perturbation generator；
  - 用于 CVX/KKT 交叉验证，不是最终论文规模实例生成器。
- `experiments/run_kkt_cross_validation.py`
  - 批量比较 CVXPY Stage-1 与 KKT Stage-1 的能耗与运行时间。
- 新增 KKT solver 与 solver-interface pytest。

## 修改

- `run_small_validation.py` 明确拆分 Stage-1、shadow prices、Stage-2 与 KKT Stage-1 结果。
- `cvx_solver.py` 增加 Stage-1 平均时延与返航时间快照。
- `resource/__init__.py` 对 CVXPY 使用 lazy import。
- 版本提升到 `0.3.0`。

## 当前边界

KKT solver v0.3.0 只替代 **Stage-1 UAV energy minimization**。Stage-2 的“在能耗最优集合中最小化 MEC CPU 占用”仍由 CVXPY 参考求解器负责。

## 开发侧校验

固定 K=5 实例上 Stage-1 UAV energy 为 `35440.746287 J`，KKT stationarity max residual 约 `4e-12`。
