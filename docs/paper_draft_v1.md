# 面向间歇边缘连接的大型林区多无人机巡护路径、计算卸载与资源分配联合优化

## 摘要

大型林区中的固定监测节点通常具有分布范围广、基础通信设施稀疏和任务产生位置离散等特点。多无人机可以通过周期巡护完成监测数据采集，但当林区仅部署少量固定边缘计算站点时，无人机并不能持续接入移动边缘计算（Mobile Edge Computing, MEC）资源，而只能在飞行路径进入边缘站覆盖区域时获得有限的通信与计算卸载机会。此时间歇连接使无人机访问路径、MEC 接触位置、任务本地/卸载决策、批量上传以及连续带宽与计算资源分配之间形成紧密耦合。针对上述问题，本文构建大型林区固定监测节点周期巡护下的多无人机协同边缘计算模型，以无人机总能耗最小化为目标，同时考虑任务截止时间、平均时延、周期返航、电池、MEC 带宽与计算容量以及 Store–Carry–Batch-Offload 时序等约束。

为求解离散路径决策与连续资源分配混合耦合问题，本文首先将原问题划分为离散结构层和固定离散结构下的连续资源层，并提出精英结构强化自适应大邻域搜索算法（Elite Structural Intensification Adaptive Large Neighborhood Search, ESI-ALNS）。该方法利用通用 ALNS 完成大范围离散探索，并在搜索获得的精英解上执行路径–计算联合迁移、MEC 接触位置调整、批次合并/拆分以及计算模式重分配等问题特定结构操作。候选精英解由严格 Stage-1 凸优化进行能耗验证，并仅接受严格可行且能耗下降的结构，从而使精英阶段成为固定探索结果上的单调后强化过程。对于连续资源层，本文利用 KKT 条件分析 UAV 本地 CPU、MEC CPU 与带宽分配的最优结构，并以 CVXPY 求解结果作为大规模实验中的正确性验证基准。

在 8 个独立场景、每场景 3 次随机算法重复的主比较中，K=50 时 ESI-ALNS 在 24 个严格运行上平均能耗为 163.190 kJ，相比 B-ALNS 的 165.967 kJ，逐对平均降低 1.549%，14 次改善、10 次相同且无劣化；K=80 的 21 个共同严格样本中，ESI-ALNS 17 次改善、4 次相同，平均降低 0.673%。接触机会实验表明，当每架 UAV 的最大接触次数由 1 增至 3 时，严格求解比例由 6/9 提升至 9/9，条件平均能耗由 239.095 kJ 降至 226.768 kJ。带宽缩放与影子价格结果进一步表明，间歇接触和通信资源是高负载场景中的关键约束来源。GIS 驱动的 Stanislaus 林区案例中，B-ALNS 与 ESI-ALNS 均达到 8/9 严格结果，ESI-ALNS 在共同严格样本上的平均能耗优势为 0.543%。此外，统一 wall-clock 预算实验显示 B-ALNS 与 ESI-ALNS 的同时间解质量总体接近，因此本文将 ESI 定位为固定全局探索后的问题特定结构精修机制，而不主张其单位时间效率始终高于继续运行 B-ALNS。

**关键词：** 多无人机；移动边缘计算；间歇连接；路径规划；计算卸载；自适应大邻域搜索；KKT；资源分配

---

# 1 引言

森林火险、生态环境与基础设施状态监测通常依赖大量固定传感或监测节点。对于面积大、地形复杂且蜂窝网络覆盖不连续的林区，完全依靠地面通信基础设施进行数据回传不仅部署成本高，而且难以覆盖偏远区域。无人机具有机动性强、部署灵活和巡护范围大的特点，可周期访问监测节点完成数据采集，并在飞行过程中进行有限的机载计算或将任务卸载至固定边缘站。

与典型 UAV-MEC 模型不同，本文考虑的 MEC 节点数量较少且固定部署，无人机只有进入 MEC 覆盖区域时才能建立上传链路。因此，是否访问某个边缘站、何时进入覆盖区以及一次接触中上传哪些任务，会直接受到无人机路径的影响；反过来，任务计算需求、截止时间和边缘资源紧张程度又可能促使无人机改变访问顺序或产生额外的 MEC 接触。由此形成路径、接触、计算卸载和资源分配之间的闭环耦合关系。

现有 UAV 边缘计算研究大体可以分为三类：一类侧重无人机作为移动边缘服务器或中继节点，重点优化轨迹与通信资源；一类研究多无人机任务分配和路径规划，但往往将计算资源简化为固定服务时长或预设卸载模式；另一类研究计算卸载和连续资源分配，但通常假设边缘连接长期可用。对于大型林区固定监测节点周期巡护问题，如果忽略 MEC 接触机会的空间离散性，就难以准确描述 Store–Carry–Batch-Offload 所产生的等待、携带和批量上传过程。

另一方面，本文问题同时包含任务分配、访问顺序、接触点选择、计算模式、上传批次和连续 CPU/带宽资源。直接构建统一混合整数非线性模型并进行大规模精确求解代价较高。为此，本文采用“通用全局探索 + 问题特定后强化 + 连续资源严格验证”的求解思路：在离散层利用 ALNS 快速探索大规模组合空间，在精英解附近使用结构化操作显式搜索路径–接触–卸载耦合关系，同时通过固定离散结构下的连续资源优化评价真实 UAV 能耗。

本文的主要工作如下。

1. 面向稀疏固定 MEC 的林区周期巡护场景，建立包含多 UAV 路径、MEC 接触、Local/MEC 计算模式、批量卸载和连续资源分配的联合优化模型，并通过 Store–Carry–Batch-Offload 与事件时序描述间歇连接过程。
2. 提出 ESI-ALNS。算法先利用通用 B-ALNS 完成全局探索，再在精英状态上执行路径–计算联合迁移、接触位置调整、批次重构和计算模式重分配，并采用严格 Stage-1 CVX 能耗进行单调接受。
3. 对固定离散结构下的连续资源子问题进行 KKT 分析，获得 UAV 本地 CPU、MEC CPU 和带宽资源的结构性规律，并通过严格凸优化求解和影子价格分析连接算法层与资源机理层。
4. 构建覆盖 8 个独立场景的主比较、消融、负载、MEC/UAV 数量、接触预算、带宽、迭代预算、强搜索参考和真实地理案例。实验表明 ESI 在固定 B-ALNS 探索结果上具有稳定非劣的后强化能力，同时揭示了接触机会和通信资源在高负载条件下的重要作用。

---

# 2 系统模型与问题描述

## 2.1 系统场景

考虑一个大型林区巡护周期。林区中分布 \(K\) 个固定监测节点、\(M\) 架同构或近似同构 UAV，以及 \(E\) 个固定 MEC 边缘站。所有 UAV 从共同或预设起降点出发，在一个巡护周期内访问监测节点、采集任务数据并返回。

如 Fig. 1 所示，监测节点本身不直接连接 MEC。任务只有在 UAV 到达监测节点后才被采集并进入机载缓存。UAV 可以选择在本地完成任务计算，也可以继续携带任务，并在后续进入某个 MEC 覆盖区域时批量上传。边缘站具有有限无线带宽和 CPU 容量，不同 MEC 的覆盖位置、带宽与计算能力允许存在异构性。

该场景的关键特征不是“是否存在 MEC”，而是 UAV 只能在有限空间区域内获得 MEC 接触机会。记离散接触结构为 UAV 路径与候选覆盖区域的交互结果，则任务卸载决策必须同时满足任务已经被采集、UAV 尚未离开可上传区域以及 MEC 资源能够在截止时间内完成服务等条件。

## 2.2 任务与计算模式

每个监测任务包含输入数据规模、计算工作量和截止时间等属性。任务完成方式包括：

- **Local**：由携带该任务的 UAV 使用机载 CPU 计算；
- **MEC**：任务由 UAV 携带至某次 MEC 接触，并在该接触对应的上传批次中发送至 MEC 计算。

对于 MEC 模式，同一 UAV 在同一 MEC 接触中可以上传多个已采集任务，形成 batch。该机制体现 Store–Carry–Batch-Offload：任务在监测节点被采集后存储于 UAV，随 UAV 路径携带，并在之后的接触机会中成批卸载。

## 2.3 决策变量

本文将决策变量分为离散结构变量和连续资源变量。

离散变量记为

\[
\mathbf D=
\{
\text{UAV assignment},
\text{route},
\text{contact},
\text{Local/MEC mode},
\text{batch}
\}.
\]

其含义包括任务由哪架 UAV 服务、各 UAV 的节点访问顺序、是否访问或经过某个 MEC 接触位置、任务采用本地还是 MEC 计算以及卸载任务属于哪个上传批次。

固定离散结构后，连续变量记为

\[
\mathbf R=
\{
f^{\mathrm{UAV}},
b^{\mathrm{MEC}},
f^{\mathrm{MEC}},
\mathbf t
\},
\]

其中分别表示 UAV 本地 CPU 频率、MEC 带宽分配、MEC CPU 分配以及上传和任务完成相关事件时刻。

## 2.4 能耗与约束

系统目标为最小化一个巡护周期内所有 UAV 的总能耗：

\[
\min E_{\mathrm{UAV}}^{\mathrm{tot}}.
\]

总能耗由飞行/路径相关能耗、监测采集能耗、本地计算能耗以及与 MEC 上传相关的通信和悬停能耗组成。MEC 侧能耗不作为主目标，但 MEC 带宽和 CPU 受到容量约束。

主要约束包括：

1. 每个监测节点在一个周期内由指定 UAV 完成访问；
2. 各 UAV 从起点出发并在周期上限内返回；
3. 单 UAV 飞行、通信和计算总能耗不超过电池预算；
4. 每个任务在截止时间前完成；
5. 平均任务时延满足系统服务质量要求；
6. MEC 接触只允许发生在覆盖区域对应的可行位置；
7. MEC 上传只能发生在任务被采集之后；
8. 同一 UAV 的本地任务遵循 FIFO 执行关系；
9. 同一 UAV–MEC 虚拟队列遵循既定批次服务顺序，批内任务按 EDF 规则调度；
10. 各 MEC 的总带宽和 CPU 分配不超过可用容量。

## 2.5 两层优化结构

对于给定离散结构 \(\mathbf D\)，定义连续资源价值函数

\[
V(\mathbf D)
=
\min_{\mathbf R\in\mathcal R(\mathbf D)}
E_{\mathrm{UAV}}(\mathbf D,\mathbf R),
\]

其中 \(\mathcal R(\mathbf D)\) 表示满足事件时序、任务截止时间、MEC 容量和 UAV 资源约束的连续可行域。

于是原问题可表示为离散外层

\[
(P1-D):\quad
\min_{\mathbf D} V(\mathbf D),
\]

与固定离散结构下的连续资源子问题

\[
(P1-R\mid\mathbf D):
\quad
\min_{\mathbf R}
E_{\mathrm{UAV}}(\mathbf D,\mathbf R).
\]

该分解使大规模组合结构搜索与凸资源分配可以采用不同求解机制处理。

---

# 3 ESI-ALNS 求解方法

## 3.1 总体框架

Fig. 2 给出了 ESI-ALNS 的整体流程：

\[
\text{Greedy Route Seed}
\rightarrow
\text{MEC Repair}
\rightarrow
\text{B-ALNS Exploration}
\rightarrow
\text{Elite Structural Intensification}
\rightarrow
\text{Strict Stage-1 CVX Acceptance}.
\]

该结构的核心不是将所有问题特定操作直接塞入同一个 ALNS 算子池，而是让通用邻域承担主要探索任务，再在精英解附近显式强化 Route–Contact–Offloading–Batch 耦合结构。

## 3.2 初始路径与 MEC 可行性修复

首先利用并行贪心插入构造任务–UAV 分配和访问顺序。插入评价同时考虑任务截止时间、UAV 周期约束和附加路径距离，并对单条路线执行局部 2-opt 调整。

仅考虑路径后，一些计算密集型任务可能因本地 CPU 或截止时间限制而不可行。为此，在初始路径上执行 MEC-assisted repair：识别关键本地任务，尝试 Local→MEC 模式转换，优先复用已有接触；当现有接触不足时，在候选 MEC 覆盖位置中插入新接触并构造上传 batch，从而得到用于后续搜索的初始联合解。

## 3.3 B-ALNS 全局探索

B-ALNS 使用成熟的自适应大邻域搜索框架。Destroy 算子包括随机任务移除、关键任务移除和路线片段移除；Repair 算子包括 cheapest insertion + MEC repair 与 regret-2 insertion + MEC repair。

算子选择采用 Roulette Wheel 自适应权重机制，接受规则采用 Record-to-Record Travel。由于每个离散候选都执行完整连续 CVX 求解代价较高，探索阶段采用 screened proxy evaluator：先使用快速结构预检查与近似资源评价筛除明显无效候选，仅在灰区状态触发 Stage-1 CVX refinement。该机制使 ALNS 能够在有限预算内完成更多离散结构探索。

## 3.4 精英结构强化

B-ALNS 结束后，算法对其 best state 执行问题特定的 Elite Structural Intensification。主要候选操作包括：

- route-compute relocation：同时改变任务所属 UAV、路线插入位置和计算模式；
- contact relocation：改变已有 MEC 接触在路线中的位置；
- contact-point / cross-MEC replacement：更换接触位置或 MEC；
- contact removal：移除收益较低或冗余接触；
- batch merge：将多个卸载任务合并至更合适的后续接触；
- batch split / new contact：拆分拥塞 batch 或增加新接触；
- Local/MEC mode reassignment；
- batch reassignment。

候选首先通过快速代理进行筛选，并保持不同操作 family 的多样性。若首轮候选无法产生有效改进，可执行有限 progressive widening。

精英阶段的接受准则与 B-ALNS 探索阶段不同。对于严格可行的 exploration incumbent，候选必须由 Stage-1 CVX 得到严格 optimal 状态，并满足真实 UAV 能耗下降条件后才被接受。因此，ESI 是固定 B-ALNS exploration 上的单调精修过程，而不是另一个随机接受搜索阶段。

## 3.5 连续资源层与 KKT 结构

固定离散结构后，连续资源问题由 Stage-1 CVX 进行严格能耗优化。KKT 分析用于揭示资源分配规律，包括 UAV 本地 CPU 的 cube-root 型结构、MEC CPU 的 square-root 型结构以及由容量约束产生的带宽 dual price。

在小规模 hard-regime 验证中，KKT 与 CVX 的 Stage-1 能耗最大相对差达到 \(1.233\times10^{-9}\) 量级，说明解析结构能够准确反映连续子问题。对于 paper-scale 实例，CVXPY 仍作为严格 correctness oracle；KKT 则用于解析解释、shadow-price 分析和快速近似。

---

# 4 实验设置

## 4.1 场景与参数

实验使用固定异构 MEC 的 paper-scale 实例生成器。除专门的敏感性实验外，默认采用 \(M=5\) 架 UAV、\(E=2\) 个 MEC。任务位置和属性由 scenario seed 控制，随机算法由 algorithm seed 控制。

主基线比较使用 S45–S52 共 8 个独立场景。B-ALNS、ESI-ALNS 和 RGA-MR 在每个场景分别使用 A100、A101 和 A102 三个随机重复；GR-MR 与 FTR-NM 为确定性方法，因此每个场景只计一个独立结果。

B-ALNS 与 ESI-ALNS 主实验采用 100 次 ALNS iterations；ESI-ALNS 在相同完成的 B-ALNS exploration 后执行 2 个 elite rounds。

连续负载、消融和多数系统敏感性实验使用 S45–S47 × A100–A102 的 3×3 设置，用于机制和趋势分析。主比较的 8×3 结果优先于早期 3×3 统计。

## 4.2 对比方法

本文比较以下五种方法。

1. **GR-MR**：Greedy Route + MEC Repair；
2. **FTR-NM**：Fixed-Task-Route Nearest-MEC；
3. **RGA-MR**：Route-GA + MEC Repair；
4. **B-ALNS**：Base ALNS，仅执行通用探索；
5. **ESI-ALNS**：本文方法，在 B-ALNS exploration 后执行精英结构强化。

## 4.3 评价指标与统计规则

主优化指标为 strict Stage-1 UAV energy。只有 Stage-1 状态严格为 optimal 的结果进入能耗统计；optimal_inaccurate、precheck failure 或其他非严格结果均不以 0 替代。

Stage-2 仅用于获得 QoS 和资源占用等 lexicographic tie-break realization，对应指标只在 Stage-2 严格有效样本上统计。

对于 stochastic methods，3 个 algorithm seeds 是同一 scenario 内的重复，不视为新的独立地理实例。配对比较按相同 scenario seed 和 algorithm seed 对齐；场景级结论先在场景内部聚合重复，再以 8 个 scenario 作为独立单位解释。

---

# 5 实验结果与分析

## 5.1 任务负载对能耗与解结构的影响

Fig. 3 给出 \(K=30,40,50,60,70,80\) 下 B-ALNS 与 ESI-ALNS 的能耗变化。随着任务数增加，两种方法的 UAV 总能耗持续上升。ESI-ALNS 相对 B-ALNS 的平均 paired improvement 分别约为 0.003%、0.066%、1.803%、1.807%、1.271% 和 1.378%。在 K=30 和 K=40 时，通用探索已经能够找到接近精英强化结果的结构；当负载增加到 K≥50 后，路径、接触与计算模式之间的耦合增强，精英结构操作获得更明显的改进空间。

Fig. 4 从离散结构角度解释这一趋势。随着 K 增大，ESI-ALNS 解中的 offload ratio、contacts per UAV 和总路线距离总体上升。K=30 时平均 offload ratio 为 5.9%、contacts/UAV 为 0.267、总路线距离约 6.465 km；到 K=80 时分别增至 12.2%、1.044 和 11.494 km。这表明高负载不仅增加任务数量，也会提高任务对 MEC 接触机会和边缘资源的依赖程度。

## 5.2 与基线方法的总体比较

Fig. 5 使用扩展后的 8 个独立场景给出正式基线比较。

### K=50

| Method | Strict | Mean energy (kJ) | Median energy (kJ) |
|---|---:|---:|---:|
| GR-MR | 7/8 | 226.449 | 227.769 |
| FTR-NM | 8/8 | 227.825 | 227.281 |
| RGA-MR | 24/24 | 227.956 | 227.002 |
| B-ALNS | 24/24 | 165.967 | 166.786 |
| ESI-ALNS | 24/24 | **163.190** | **165.559** |

ESI-ALNS 相对 FTR-NM 在 24 个嵌套配对运行中全部能耗更低，平均 paired advantage 为 28.378%；相对 RGA-MR 同样为 24/24 更低，平均优势 28.341%。这说明仅采用固定路径或 GA 路线搜索难以充分利用 Route–Contact–Offloading 耦合。

相对 B-ALNS，ESI-ALNS 为 14 better、10 equal、0 worse，平均逐对能耗降低 1.549%。将同一场景内的三个随机重复先取均值后，8 个独立场景中有 7 个场景得到进一步降低，1 个场景保持相同。Fig. 6(a) 以场景级配对形式展示了这一结果。

### K=80

高负载下，构造型和 GA 基线的主要问题转变为 strict-feasibility robustness。GR-MR 与 FTR-NM 分别只有 1/8 独立场景获得 strict 解，RGA-MR 仅有 3/24 strict，且三个严格运行都来自同一场景。B-ALNS 与 ESI-ALNS 均达到 21/24 strict，并且所有 8 个场景至少有一次严格重复。

在 21 个共同 strict 的 B-ALNS / ESI-ALNS pairs 中，ESI-ALNS 为 17 better、4 equal、0 worse，mean paired energy reduction 为 0.673%，平均能耗由 226.006 kJ 降至 224.417 kJ。按场景聚合后，Fig. 6(b) 中 8 个场景的 ESI-ALNS 条件平均能耗均不高于 B-ALNS。

这些结果说明 B-ALNS 是主要的全局探索与可行性恢复机制，而 ESI 的贡献是对已经形成的高质量联合结构进行严格后强化。

## 5.3 精英结构操作消融

Fig. 7 比较 Full ESI-ALNS 与删除不同 elite family 的变体。所有消融共享完全相同的 B-ALNS exploration，从而只比较后强化操作本身。

删除 route-compute relocation 后，Full ESI-ALNS 在 9 个配对中 6 次更优、3 次相同，平均优势 0.709%，为所有 family 中最大的影响。删除 contact family 后，Full 为 3 better、5 equal、1 worse，平均优势 0.302%。删除 explicit batch family 的平均影响仅 0.009%，而删除 progressive widening 在当前 K=80 设置下几乎没有 aggregate difference。

因此，route-compute relocation 是 ESI 的主导结构强化机制。Contact 操作提供较弱但具有解释意义的辅助价值；显式 batch 与 progressive widening 更适合作为特定状态下的补充机制，而不应宣称所有模块贡献相同。

## 5.4 MEC 数量与 UAV 数量敏感性

Fig. 8 上半部分改变 MEC 数 \(E=2,3,4\)，并保持 K=100、M=5。Stage-1 strict 数量由 3/9 提升到 8/9 和 8/9，说明增加 MEC 部署能够显著扩大有限搜索预算下可恢复的严格可行区域。与此同时，活动 MEC 的平均 CPU utilization 由约 59.4% 下降至 47.5% 和 37.8%，表明更多边缘站能够分散计算负载。

但能耗并不随 MEC 数单调下降：严格子集的平均能耗分别为 249.009、248.254 和 249.309 kJ。因此该实验支持的是“更多 MEC 改善可用资源与严格可行性”，而不是“边缘站越多能耗必然越低”。

Fig. 8 下半部分改变 UAV 数 \(M=3,5,8\)，保持 K=80、E=2。M=3 在固定搜索预算下为 0/9 strict；M=5 和 M=8 均为 9/9 strict。M 从 5 增至 8 后，平均能耗由 226.768 kJ 降至 224.480 kJ，约降低 1.01%；平均任务时延由 217.543 s 降至 211.067 s，contacts/UAV 由 1.050 降至 0.641。Offload ratio 基本保持不变，说明增加 UAV 的主要作用是缓解单机路线与服务压力，而不是简单增加卸载比例。

## 5.5 接触机会的作用

Fig. 9 直接改变每架 UAV 的最大接触次数 \(C_{\max}=1,2,3,4\)。对应 Stage-1 strict 数分别为 6/9、7/9、9/9 和 9/9，严格子集平均能耗分别为 239.095、234.636、226.768 和 227.632 kJ。

当最大接触次数由 1 增至 3 时，更多任务能够在合适的路径位置获得卸载机会，严格可行性提高且能耗显著下降。当 \(C_{\max}\) 从 3 增至 4 后，严格率不再提高，条件平均能耗也没有继续下降。该现象表明接触机会具有明显边际收益递减：接触过少会限制可行域，而超过一定数量后，进一步增加候选接触并不保证有限预算启发式搜索获得更低能耗。

## 5.6 带宽敏感性与资源影子价格

Fig. 10 将 MEC 带宽缩放为基准值的 0.5、1.0 和 1.5 倍。严格样本数为 8/9、9/9 和 9/9，严格子集平均能耗分别为 230.893、226.768 和 227.433 kJ。

Stage-1 relative shadow price 为进一步解释提供了资源边际价值。0.5× 带宽下，平均 bandwidth relative shadow 为 0.011，高于基准和 1.5× 设置的约 0.005，说明低带宽时增加通信容量具有更高局部价值。CPU relative shadow 在 0.5× 和 1.0× 设置中接近当前显示精度的 0，而在 1.5× 带宽时上升至约 0.008，体现当通信约束放松后部分资源压力会向计算侧转移。

因此，本文不将某一单独的 Stage-2 utilization 值直接等同于系统瓶颈，而是结合显式资源缩放和 Stage-1 shadow price 判断资源约束的边际作用。

## 5.7 迭代预算与强搜索参考

Fig. 11 给出 25、50、100 和 200 iterations 的预算敏感性。对应 strict 结果分别为 6/9、8/9、9/9 和 7/9，条件平均能耗由 245.028 kJ 降至 238.429、226.768 和 217.985 kJ，平均运行时间则由 20.798 s 增至 88.577 s。

需要指出，不同 iteration budget 对应独立搜索，其 RRT acceptance schedule 也随总预算变化，因此 Fig. 11 表示 iteration-budget sensitivity，而不是单次搜索轨迹的收敛曲线。100 iterations 在 strict robustness、能耗质量和计算成本之间提供了较均衡 operating point。

Fig. 12 使用 K=28、M=2、E=2 的 reduced-scale 实例构建 empirical best-known strong reference。标准 ESI-ALNS 9/9 strict，强搜索 36/36 strict。标准设置相对 best-known 的 mean gap 为 5.968%，median gap 为 8.610%。该结果说明冻结的 100-iteration 方法仍可能在困难实例中保留进一步搜索空间，因此本文将 strong reference 明确称为经验 best-known，而不将其解释为全局最优证明。

## 5.8 GIS 驱动真实地理案例

为验证算法对真实空间分布的适用性，Fig. 13 使用 Stanislaus 区域历史 USFS 火点构建 59 个监测位置，并在真实地理坐标上设置 UAV depot 与建模 MEC 部署。

GR-MR 和 FTR-NM 在三个确定性场景中均未获得严格结果；B-ALNS 与 ESI-ALNS 分别达到 8/9 strict。ESI-ALNS 的严格子集平均能耗为 878.691 kJ，B-ALNS 为 883.684 kJ。在 8 个共同 strict pairs 中，ESI-ALNS 2 次改善、6 次相同、0 次劣化，mean paired advantage 为 0.543%。

该案例的意义是验证 GIS 驱动任务分布下的路线–接触–卸载联合求解能力，而不是模拟实际无人机实飞或真实基站部署。由于该案例中实际保留的 MEC 接触和卸载较稀疏，强耦合机制的主要证据仍来自受控的 contact-budget 与 bandwidth 实验。

## 5.9 计算预算公平性

固定 100-iteration 实验回答的是：在相同完成的 B-ALNS exploration 后，加入 ESI 是否能够继续改善解。该问题得到明确支持。

进一步的统一 wall-clock 实验则让 B-ALNS 使用同样的总计算时间继续通用探索。K=50 的 15 s 主预算下，ESI-ALNS 与 B-ALNS 的场景级平均优势为 -0.385%；K=80 的 45 s 主预算下为 +0.387%，两者均表现为小幅、混合差异。由此，本文不声称 ESI 在相同 wall-clock 下计算效率始终优于 continued B-ALNS，而将其定位为利用问题结构对固定 exploration incumbent 进行严格单调精修的机制。

---

# 6 讨论

实验结果揭示了三个值得关注的现象。

首先，多 UAV 林区边缘计算中的主要困难并非单独的路径或单独的资源分配，而是接触机会决定了卸载“何时可以发生”。在接触预算较低时，严格可行性和能耗质量同时受到明显影响；当通信资源增加后，shadow price 又表现出资源压力向 CPU 侧转移的现象。因此 Route–Contact–Offloading–Resource coupling 是该场景中不可忽略的系统结构。

其次，B-ALNS 与 ESI 的角色具有明显分工。B-ALNS 提供大范围组合探索和主要的可行性恢复能力；ESI 则利用问题结构在精英解附近搜索通用 destroy/repair 不容易直接构造的联合调整。消融结果表明 route-compute relocation 是最主要的后强化来源。

最后，启发式离散搜索与连续严格优化需要区分。本文对固定离散结构的 Stage-1 连续资源问题使用严格凸优化，因此可以准确比较已给定离散结构的 UAV 能耗；但外层离散问题仍属于启发式搜索。Strong-reference 实验进一步说明，即使标准配置在多数主实验中表现稳定，也不能将其输出解释为全局最优解。

---

# 7 结论

本文研究大型林区固定监测节点周期巡护条件下的多无人机协同边缘计算问题，重点考虑稀疏固定 MEC 造成的间歇边缘连接。针对路径、接触、计算卸载、上传批次和连续资源分配之间的耦合，建立以 UAV 总能耗最小化为目标的联合优化模型，并提出 ESI-ALNS 求解框架。

ESI-ALNS 采用通用 B-ALNS 进行全局探索，再通过精英结构强化显式调整路线–计算与 MEC 接触结构，并以 strict Stage-1 CVX 对候选进行单调能耗接受。KKT 分析进一步给出连续资源层的结构规律和影子价格解释。

正式 8 场景主比较显示，K=50 时 ESI-ALNS 相对 B-ALNS 在 24 个 paired runs 中 14 次改善、10 次相同、无劣化，平均降低 1.549%；K=80 的 21 个共同 strict pairs 中 17 次改善、4 次相同，平均降低 0.673%。接触机会和带宽敏感性实验表明，间歇连接及通信资源是高负载条件下的重要限制因素。真实地理案例进一步验证了该方法在实际空间分布驱动问题上的适用性。

同时，统一 wall-clock 比较表明 ESI 与继续 B-ALNS 在同时间预算下总体表现接近。因此，本文的主要贡献不是声称一种计算时间上全面支配 B-ALNS 的新元启发式，而是提出一种面向间歇 MEC 路径–接触–卸载耦合结构的严格后强化机制，并通过系统模型、资源分析和多组实验验证其增量价值与适用边界。
