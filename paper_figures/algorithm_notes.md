# Hybrid ALNS 算法图配套说明

固定版采用“离散搜索—资源评价—结构操作示例”的组织方式；新增图形机制版采用“上方主线—中部操作变化—下方资源反馈”的布局。两版表达同一算法，均展示基线通过严格校验后的主路径。详细判断放在以下伪代码中，避免读者将图中的箭头理解为无条件接受或全局最优保证。

## 伪代码

```text
Algorithm 1: Hybrid ALNS with structural elite refinement
Input: instance I, exploration budget N, elite round limit R

1  Construct greedy routes and repair MEC contact / offloading feasibility.
2  Initialize operator weights, acceptance rule and exploration incumbent.
3  For iteration = 1, ..., N:
4      Select generic destroy and repair operators adaptively.
5      Generate a candidate; repair its route / MEC feasibility.
6      Evaluate using proxy screening and an optimistic feasibility precheck;
       invoke CVX for candidates requiring further verification.
7      Apply Record-to-Record Travel acceptance and update operator weights.
8      Track the best exploration solution D_explore.
9  Solve the fixed-D_explore continuous problem by Stage-1 CVX.
10 If the result is infeasible or its Stage-1 status is not strict optimal:
11     Return D_explore with its non-strict terminal status; skip refinement.
12 Set incumbent D = D_explore and retain its verified resource solution.
13 For round = 1, ..., R:
14     Generate route, contact, batch and task-mode candidates.
15     Form a family-diverse shortlist using proxy / precheck ranking.
16     If the shortlist is empty: stop refinement.
17     Evaluate shortlisted candidates by strict Stage-1 CVX;
       exclude infeasible and non-strict candidates.
18     Identify a candidate exceeding the meaningful energy-gain threshold.
19     If none qualifies but a positive CVX gain reaches the widening trigger:
20         Widen the same move family and evaluate the extra candidates
           using strict Stage-1 CVX.
21         Reapply the meaningful energy-gain acceptance rule.
22     If no candidate qualifies: stop refinement.
23     Accept the best qualifying move and update D and its resource solution.
24 Return D, the associated resource allocation, UAV energy and event times.
```

## 机制说明

- **探索阶段与精英阶段不同。** 泛用 ALNS 使用自适应算子选择和 Record-to-Record Travel 接受准则；探索过程不要求每一步都降低当前能耗。精英强化只接受通过严格 Stage-1 CVX 校验且超过有意义改进阈值的候选。
- **资源评价会反复调用。** 探索阶段主要使用代理评价和可行性预检查，并按需要调用 CVX；探索最优解的基线与精英候选使用严格 Stage-1 CVX。主图用成对箭头表示传入离散候选和返回评价结果。
- **严格校验针对连续子问题。** `strict optimal` 指固定离散结构下的 Stage-1 求解状态，不表示联合路径、接触、卸载问题已经得到全局最优解。
- **先求值，后判断 near miss。** 渐进扩展由已有 CVX 收益触发，扩展候选仍需经严格 CVX 评价。未达到接受阈值时保留 incumbent 并终止强化；达到轮数上限时也终止。
- **KKT 为理论分析与验证支持。** 它说明连续资源的最优结构，并与 CVX 进行小规模交叉验证；不表示 paper-scale 下额外执行一个 KKT 求解阶段，也不表示已经替代 CVXPY。
- **可选 Stage-2 未在主流程中展开。** 它用于 Stage-1 能耗约束下的 MEC CPU 占用择优，不替代主能耗目标。

当前实现中的有意义改进阈值结合数值容差、绝对能耗阈值及相对能耗阈值；近失扩展另有相对收益触发值。图与伪代码保留机制名称，实际参数以实验配置和代码为准。

## 三个结构操作示例

1. **Contact-point adjustment：** 在同一 MEC 覆盖区内把上传位置从 c 改为 c′，保持任务访问顺序 i → j；圈表示监测任务位置，菱形表示 MEC 接触位置。
2. **Batch merging：** 将接触 c₁ 对应的任务 a、b 与 c₂ 对应的任务 d 合并，在较晚的接触 c₂ 上传；三个任务均保留，且必须先采集后上传。
3. **Task-mode reassignment：** 将同一任务 a 的处理位置从 UAV 本地 CPU 切换到 MEC。机载计算用芯片表示，卸载计算用服务器表示。

三幅小图是独立的候选变化示例，并非同一个实验实例。示例不预先断言变化一定可行或节能，接受结果由上方的资源评价与改进准则决定。

## 图形机制版的读图说明

- **顶部主线：** 从初始化、ALNS 探索、严格基线校验到精英改进和最终方案。CVX 勾选图标表示该图展示了校验通过的主路径，不表示所有实例均能通过。最终路线是状态示意，不是实验最优解。
- **左侧破坏与修复：** 黑色小方块表示机库，带编号的圆点表示任务。当前顺序是机库 → 1 → 2 → 3 → 4 → 5 → 机库；移除任务 2、5 后，这两个任务仍以橙色虚线圆保留在固定位置；重插入后顺序变为机库 → 1 → 5 → 2 → 3 → 4 → 机库。淡虚线表示已移除的旧边，不是仍在执行的路线。评价后再按探索接受准则决定是否更新，迭代不保证每步降低能耗。
- **右侧四种操作：** 路线小图改变同一组任务的访问顺序；接触点由 c 移到 c′，两个任务的位置及先后不变；批次把 c₁ 的任务 1、2 与 c₂ 的任务 3 合并到较晚的 c₂；处理模式把同一任务 1 从机载芯片切换到 MEC。四个例子彼此独立，不表示它们会同时执行。
- **筛选和接受：** 漏斗表示候选筛选。右侧 `Accept if ΔE > τ` 表示达到有意义收益门槛的候选才可能被接受，且前提是严格求解可行、Stage-1 状态为 optimal。ΔE 是当前解与候选的 UAV 能耗差；τ 是数值容差、绝对及相对改进阈值的简写，不额外引入固定实验参数。
- **下方资源反馈：** 左侧 Proxy / precheck 表示代理评价及可行性预检查，按需要调用右侧 CVX。外围成对箭头分别传入候选、返回评分或能耗/状态；芯片与带宽条表示资源分配，长度没有实验数值含义。`E(D)` 是固定离散决策 D 下资源优化所得的 UAV 能耗；勾叉是可能返回的可行/不可行状态，不代表同一候选同时满足两种状态。
- **符号一致性：** 圆点表示任务、方块表示机库、菱形表示 MEC 接触点、虚线椭圆表示覆盖区。任务卡片表示批次中的数据；本地芯片和 MEC 机柜表示处理位置，任务到 MEC 的短虚线箭头表示上传。

KKT、非严格基线退出、近失渐进扩展、停止条件及可选 Stage-2 延用上文机制说明，未作为额外执行阶段加入图形机制版。

## 代码依据

- [hybrid.py](../src/uav_mec/algorithms/alns/hybrid.py)：探索结束后的严格基线校验与精英调用。
- [problem_operators.py](../src/uav_mec/algorithms/alns/problem_operators.py)：结构候选、家族筛选、渐进扩展、阈值接受和停止逻辑。
- [evaluator.py](../src/uav_mec/algorithms/alns/evaluator.py)：代理筛选及按需 CVX。

## 版式参考

版式采用总体方法与操作示意分开的表达方式，参考以下同类论文的组织思路，未复制其图像或算法：

- [Resource Allocation and Trajectory Optimization in OTFS-Based UAV-Assisted Mobile Edge Computing](https://doi.org/10.3390/electronics12102212)，Electronics，2023：Algorithm 1–3 分别呈现子算法与总体算法。
- [A Coordinated Vehicle–Drone Arc Routing Approach Based on Improved Adaptive Large Neighborhood Search](https://doi.org/10.3390/s22103702)，Sensors，2022：Algorithm 2 与 Fig. 4–11 分别描述总体框架与结构操作。
- [Adaptive Large Neighborhood Search for a Flexible Truck–Drone Routing Problem with Multi-Visit and Cost Trade-Offs](https://doi.org/10.3390/wevj16110612)，World Electric Vehicle Journal，2025：Algorithm 1 与 Fig. 3–5 分别描述总体算法和关键机制。
