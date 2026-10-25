# v27 时效模型（代码说明）

v27 是独立的新模型，代码在 `src/uav_mec/v27/`，参数在 `configs/v27_timeliness.yaml`。它不引用也不修改 v25 的 `domain/`、`optimization/` 模块，所以 `results/` 中已存档的 v25 结果仍可原样复现。修改依据见 `无人机MEC论文资料/23_模型审查与重建_20261025/模型审查与重建方案.md`。

## 与 v25 的差异

| 项目 | v25 | v27 |
|---|---|---|
| 时限起点 | 任务开始时刻（r_i=0），δ_i 取周期的 0.55–0.95 倍 | **采集完成时刻**：AoI_i = c_i − t_i^col |
| 目标 | 无人机总能耗 | J = (1/K)Σ ω_i·AoI_i/δ_i + λ·E_total/(M·E_max)；离散层按“超时任务数 → 归一化超时 → J”字典序排序 |
| 推进功率 | 常数 180 W / 200 W | Zeng 旋翼模型（TWC 2019）：悬停 168.5 W，10 m/s 时 126.0 W |
| 上传 | 每个“无人机—站点对”整周期静态预留带宽 b_ue | 站点 TDMA：按到达先后（FCFS）依次服务，每次上传独占全部带宽 B_e |
| MEC 计算 | 每个“无人机—站点对”静态预留 F_ue | 单服务器全速处理：按上传完成先后 FIFO，批内按截止时刻 EDF |
| 第二阶段 | 在能耗容差内最小化 CPU 预留量 | 删除 |
| 平均时延约束 D̄、周期 T_cyc | 有 | 删除；任务时长由电池约束决定 |
| 机载计算 | κ=1e-27、f_max=1 GHz（满载约 1 W） | κ̄ = P_max/f_max³，按 Jetson 级 15 W、2 Gcycles/s 校准 |
| 任务类别 | 单一类别 | 轻任务（单帧检测）和重任务（视频/多光谱分析），重任务可设为只能卸载 |
| 覆盖范围 | 人为设定半径 | 由链路预算反推：全带宽速率 ≥ min_rate_mbps 的最大水平距离 |
| 飞行高度 | 30 m | 100 m |

## 模块

| 文件 | 内容 |
|---|---|
| `params.py` | 参数数据类与 YAML 读取、校验 |
| `physics.py` | Zeng 推进功率、信道 SNR 系数、Shannon 速率、覆盖半径 |
| `instance.py` | 可复现实例：站点、接触候选点、轻重任务 |
| `solution.py` | 离散结构 D（路线、接触访问、上传分配）及结构可行性检查 |
| `timeline.py` | 事件时间线：飞行、采集、TDMA 上传、MEC 单服务器排队 |
| `dvfs.py` | 每架无人机的机载 DVFS 凸子问题（SLSQP，带解析梯度） |
| `evaluate.py` | 汇总目标、能耗分解、AoI、超时统计 |
| `audit.py` | 独立残差验收：不重跑仿真，直接按约束逐条核对已记录的调度，并从头重算能耗和目标 |
| `routing.py` | 只考虑距离的扫描分区 + 最近邻 + 2-opt，用于冻结路线 |
| `offload_search.py` | 路线不变时，对计算模式、上传接触和接触插入做局部搜索 |

## 固定结构下的连续子问题

在 v27 中，飞行、上传和 MEC 时间线与机载频率无关，因为机载计算与飞行并行。因此对固定的 D，连续部分可以按无人机拆开：

```
min  Σ_k a_k c_k + μ κ̄ Σ_k w_k^3 / p_k^2
s.t. c_k ≥ t_k + p_k,  c_k ≥ c_{k-1} + p_k,  w_k/f_max ≤ p_k ≤ w_k/f_min,
     κ̄ Σ_k w_k^3 / p_k^2 ≤ E_max − E_fixed,u
```

其中 p_k = w_k/f_k，a_k = ω_k/(K δ_k)，μ = λ/(M E_max)。目标是关于 c 的线性项加上关于 p 的可分凸函数，约束除电池为凸下水平集外都是线性的，所以是凸问题。单任务时的驻点条件给出 f* = (a/(2μκ̄))^{1/3}，投影到 [f_min, f_max] 上，与 v25 式 (25) 的立方根形式一致，测试中已核对。

SLSQP 的结果与另一种求解方法（scipy trust-constr，多起点）在 30 个随机算例上做过对比，前者从未更差。`tests/test_v27_model.py` 中还有一个与 cvxpy 对拍的测试，在装有 cvxpy 的环境下会自动运行。

## 运行

```powershell
python -m pytest tests/test_v27_model.py
python experiments/v27_coupling_check.py --tasks 30 50 80 --seeds 45 46 47 48 --workers 4 --output outputs/v27/coupling
```

GitHub Actions 中对应的工作流是 **v27 coupling check (frozen routes)**，按三个变体并行运行，结果写入运行页面的 Summary。

## 参数状态

`configs/v27_timeliness.yaml` 是在运行任何搜索算法之前设定的暂定参数，标有 `verify` 的项需要先补上文献页码再冻结。冻结后不得根据算法或耦合检验结果回头调参。耦合检验中的三个变体（base、weak_onboard、heavy_edge_only）是事先声明的敏感性网格，用来描述“联合决策在哪些条件下起作用”，不是调参。
