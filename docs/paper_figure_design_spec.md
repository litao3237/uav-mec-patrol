# 论文绘图规范与 Figure 任务清单（供 Codex 执行）

> 项目：UAV-MEC Patrol Research  
> 分支：\`develop\`  
> 用途：指导 Codex 统一生成论文正式图、准备 Visio 绘图素材、整理实验数据图。  
> 重要约束：**系统模型图、算法框架图必须按正式论文 Visio 矢量图标准制作，不得使用 Python/Matplotlib 代替。**

---

# 1. 总体原则

论文中的图分为三类：

1. **概念/结构图**
   - 系统模型图；
   - Hybrid ALNS 算法框架图；
   - 必要时的两层优化/KKT 结构图。
   - **必须采用 Visio 风格矢量图。**
   - 不允许使用 Python、Matplotlib、NetworkX 等直接生成最终论文图。

2. **实验数据图**
   - workload；
   - baseline；
   - ablation；
   - sensitivity；
   - convergence；
   - strong-reference。
   - 可使用 Python + Matplotlib。
   - 不使用 Seaborn。

3. **真实地理图**
   - Stanislaus National Forest / Groveland Ranger District case。
   - 使用 GIS/真实地理坐标绘制。
   - 不应画成普通 synthetic scatter。
   - 推荐使用 GIS 底图、真实 USFS 历史火灾点、真实设施锚点和优化路径。

---

# 2. 统一论文绘图风格

## 2.1 论文风格

所有图都应遵循正式论文风格：

- 白底；
- 扁平化；
- 不使用渐变；
- 不使用 3D；
- 不使用投影阴影；
- 不使用花哨图标；
- 不使用大面积高饱和色；
- 线条、字号、marker 风格统一；
- 所有图应保证缩小到双栏论文宽度后仍可读；
- 图中文字优先使用英文；
- 公式符号与论文正文保持一致。

建议字体：

- Times New Roman 或与论文模板一致的 serif 字体；
- 图内数学符号使用 LaTeX/数学字体；
- 不使用中文作为最终图中文字，中文说明放在文档中即可。

---

## 2.2 输出格式

概念/结构图：

- 首选：\`.vsdx\`；
- 同时导出：\`.pdf\` 或 \`.svg\`；
- 如期刊需要 Office 矢量：可附 \`.emf\`；
- 不使用截图 PNG 作为最终源文件。

数据图：

- 必须至少输出：
  - PDF；
  - SVG；
- 可额外输出 300–600 dpi PNG 便于预览。

真实 GIS 图：

- 推荐输出：
  - PDF；
  - SVG；
  - 高分辨率 PNG；
- 地理图中保留比例尺、图例、北箭头中的必要元素，但不要让地图风格喧宾夺主。

---

# 3. 系统模型图：必须使用 Visio

## 3.1 Figure 目标

系统模型图要表达本文核心场景：

\[
\boxed{
\text{Fixed Monitoring Nodes}
\rightarrow
\text{Multi-UAV Patrol / Store-Carry}
\rightarrow
\text{Intermittent MEC Contacts}
\rightarrow
\text{Local or MEC Computing}
}
\]

必须能从图中直观看出：

- 大型林区；
- 固定监测节点；
- 多 UAV 周期巡检；
- UAV depot；
- UAV 本地计算；
- UAV 缓存/携带任务；
- MEC coverage；
- intermittent contact；
- task upload；
- batch offloading；
- heterogeneous MEC；
- UAV return cycle。

---

## 3.2 推荐布局

采用横向论文版式。

建议分成三层：

### 左侧：Monitoring Area

包含：

- forest region；
- fixed monitoring nodes；
- task labels，例如 \(i,j,k\)；
- UAV depot；
- UAV 起飞路径。

### 中间：UAV Patrol / Store-Carry Layer

包含：

- UAV 1 / UAV 2 / UAV 3；
- 不同路径；
- route direction arrows；
- local computation 标志；
- onboard cache / carried tasks；
- contact points。

### 右侧或上侧：Heterogeneous MEC Layer

包含：

- MEC 1；
- MEC 2；
- 必要时 MEC 3；
- 不同 coverage circle；
- \(B_e\)、\(F_e\) 异构参数；
- batch upload；
- MEC computing。

---

## 3.3 必须表达的链路

区分以下线型：

### UAV route

- 实线；
- 带方向箭头；
- 不同 UAV 可以使用不同线型或低饱和颜色。

### MEC coverage

- 虚线圆/椭圆；
- 标注 “Intermittent MEC coverage”。

### Task collection

- monitoring node → UAV；
- 不宜画成无线长链路；
- 可用短箭头 + “Collect”。

### MEC upload

- UAV → MEC；
- 用单独线型；
- 标注 “Batch upload”。

### Local computing

在 UAV 旁：

\[
\text{Local Computing}
\]

### Store-Carry

在 UAV route 中部：

\[
\text{Store / Carry}
\]

---

## 3.4 推荐图中英文标签

可采用：

- Fixed Monitoring Node
- UAV Depot
- Patrol Route
- UAV Local Computing
- Onboard Cache
- Store-Carry
- MEC Contact
- Batch Offloading
- Heterogeneous MEC
- MEC Coverage
- Task Upload
- Return to Depot

MEC 旁可用：

\[
(B_1,F_1),\quad(B_2,F_2)
\]

表达 bandwidth / CPU 异构。

---

## 3.5 不允许出现的内容

不要：

- 画成卡通风；
- 使用照片；
- 使用复杂树木贴图；
- 过多装饰图标；
- 在正文图中写“示意图”“待插入”；
- 使用 Python 生成最终系统模型图；
- 把所有约束公式堆在图里；
- 把控制链路和任务上传链路混成一种线。

---

# 4. Hybrid ALNS 算法框架图：必须使用 Visio

## 4.1 Figure 目标

算法图需要体现：

\[
\boxed{
\text{B-ALNS Exploration}
+
\text{Problem-Specific Elite Intensification}
+
\text{Strict Stage-1 CVX}
}
\]

并明确：

\[
\boxed{
\text{KKT = analytical continuous-resource structure}
}
\]

\[
\boxed{
\text{CVXPY = paper-scale correctness oracle}
}
\]

---

## 4.2 推荐主流程

整体流程：

1. Problem Instance
2. Greedy Route Seed
3. MEC Contact / Offloading Repair
4. B-ALNS Exploration
5. Exploration Best
6. Strict Stage-1 CVX
7. Elite Structural Intensification
8. Family-Diverse Shortlist
9. Near-Miss Progressive Widening
10. Strict Stage-1 CVX Evaluation
11. Monotone Accept / Reject
12. Final Discrete Solution
13. Continuous Resource Allocation
14. Final UAV Energy and Schedule

---

## 4.3 B-ALNS 模块内部

作为一个大框：

### Destroy operators

- Random Task Removal
- Critical Task Removal
- Route-Segment Removal

### Repair operators

- Cheapest Insertion + MEC Repair
- Regret-2 Insertion + MEC Repair

### Search mechanism

- RouletteWheel
- Record-to-Record Travel
- Screened Proxy Evaluation
- Optimistic Precheck
- Gray-Zone CVX Refinement

不要把每个模块画成十几个小框导致图失控。

---

## 4.4 Elite Structural Intensification

作为第二个明显的大框：

- Route-Compute Relocation
- Contact Relocation
- Contact-Point Replacement
- Contact Removal
- Batch Merge
- Batch Split / New Contact
- Task Mode Reassignment
- Batch Reassignment

然后进入：

- Family-Diverse Shortlist
- Progressive Widening

---

## 4.5 Decision 节点

使用 Visio 标准菱形：

### Near miss?

Yes：

\[
\rightarrow \text{Progressive Widening}
\]

No：

\[
\rightarrow \text{Strict CVX Evaluation}
\]

### Energy improved?

Yes：

\[
\rightarrow \text{Accept}
\]

No：

\[
\rightarrow \text{Reject}
\]

---

## 4.6 连续资源层

图的下方可以单独画一个横向模块：

\[
\boxed{\text{Continuous Resource Layer}}
\]

包含：

### KKT Analytical Structure

- UAV CPU cube-root law；
- MEC CPU square-root law；
- bandwidth dual price；
- event-graph shadow prices。

### Strict CVX Verification

- Stage-1 minimum UAV energy；
- feasibility oracle；
- exact continuous solution for fixed discrete structure。

最终输出：

- resource allocation；
- upload schedule；
- UAV energy；
- task completion times。

---

## 4.7 算法图颜色建议

不要超过 3 类强调色。

例如：

- Generic Exploration：一种浅色；
- Elite Intensification：第二种浅色；
- CVX/KKT Continuous Layer：第三种浅色；
- 其余流程框白底灰边。

具体颜色由 Visio/论文模板统一决定，不要使用鲜艳彩虹配色。

---

# 5. 可选：两层优化/KKT 结构图

如果论文版面允许，可以增加一张非常简洁的 optimization decomposition figure。

结构：

\[
P1
\]

分成：

### Discrete Layer

\[
\mathbf D=
\{
\text{assignment},
\text{route},
\text{contact},
\text{Local/MEC},
\text{batch}
\}
\]

由：

\[
\text{Hybrid ALNS}
\]

求解。

### Continuous Layer

\[
\mathbf R=
\{
f^{UAV},
b^{MEC},
f^{MEC},
t
\}
\]

由：

\[
\text{KKT structure + CVX verification}
\]

求解。

中间用：

\[
V(\mathbf D)
=
\min_{\mathbf R}E_{\rm UAV}(\mathbf D,\mathbf R)
\]

连接。

该图同样必须用 Visio，不使用 Python。

---

# 6. 实验 Figure 规划

下面的数据图可以使用 Python/Matplotlib。

建议最终主文约 11–13 组 Figure。

---

# 7. Fig. 3 — Dense Workload Performance

设置：

\[
K=30,40,50,60,70,80
\]

推荐：

## Fig. 3(a)

**Line chart + markers + error bars**

x：

\[
K
\]

y：

\[
\text{Mean UAV Energy (J)}
\]

两条线：

- B-ALNS
- ESI-ALNS

使用 mean ± std。

---

## Fig. 3(b)

**Line chart**

x：

\[
K
\]

y：

\[
\text{Hybrid Improvement over Generic (\%)}
\]

数据重点：

- K30 ≈ 0.003%
- K40 ≈ 0.066%
- K50 ≈ 1.803%
- K60 ≈ 1.807%
- K70 ≈ 1.271%
- K80 ≈ 1.378%

目的：

展示负载升高后问题特定 elite refinement 的价值增强。

---

# 8. Fig. 4 — Workload Structural Evolution

采用 3-panel line charts。

## Fig. 4(a)

Offload Ratio vs \(K\)

## Fig. 4(b)

Contacts per UAV vs \(K\)

## Fig. 4(c)

Route Distance vs \(K\)

三个 panel 使用完全一致的 x 轴。

主要表达：

\[
K\uparrow
\Rightarrow
\text{offload/contact/route pressure}\uparrow
\]

---

# 9. Fig. 5 — Baseline Comparison

## Fig. 5(a): K=50 Energy

推荐：

**strip/scatter + mean marker**

横轴：

- FTR-NM
- Route-GA
- B-ALNS
- ESI-ALNS

纵轴：

\[
E_{\rm UAV}
\]

不要只画平均值柱子。

显示实际 run 分布。

Greedy 可单独标注 strict coverage，因为只有 2/3 unique scenarios strict。

---

## Fig. 5(b): K=80 Strict Feasibility

使用：

**bar chart**

- Greedy
- FTR-NM
- Route-GA
- Generic
- Hybrid

显示：

- deterministic baseline 使用 unique scenarios；
- stochastic algorithm 使用 9 runs。

不要伪装成相同独立样本量。

---

# 10. Fig. 6 — Generic vs Hybrid Paired Comparison

强烈推荐：

\[
\boxed{\text{Paired slope / dumbbell plot}}
\]

每个：

\[
(\text{scenario seed},\text{algorithm seed})
\]

是一对。

### Fig. 6(a)

K=50

### Fig. 6(b)

K=80

左：

B-ALNS

右：

ESI-ALNS

每条线连接同一 pair。

K80 核心结论：

\[
8\text{ better}+1\text{ equal}+0\text{ worse}
\]

该图用于证明 paired improvement，而不是只报告 aggregate mean。

---

# 11. Fig. 7 — Elite-Family Ablation

推荐：

**horizontal bar chart**

横轴：

\[
\text{Mean Full-Hybrid Advantage (\%)}
\]

纵轴：

- w/o Route
- w/o Contact
- w/o Batch
- w/o Widening

数据：

- Route: 0.709%
- Contact: 0.302%
- Batch: 0.009%
- Widening: 0.000%

可以在每个 bar 尾部标注：

- Full better
- Equal
- Ablated better

例如：

\[
6/3/0
\]

不要使用雷达图。

---

# 12. Fig. 8 — MEC/UAV Sensitivity

可组合成一组 Figure。

## Fig. 8(a): MEC-count strict feasibility

x：

\[
E=2,3,4
\]

y：

strict rate。

数据：

\[
3/9,\ 8/9,\ 8/9
\]

推荐 point/line chart。

---

## Fig. 8(b): MEC-count offload ratio / CPU utilization

推荐两个小 panel，不使用双 y 轴。

---

## Fig. 8(c): UAV-count strict feasibility

x：

\[
M=3,5,8
\]

数据：

\[
0/9,\ 9/9,\ 9/9
\]

推荐 bar chart。

---

## Fig. 8(d): UAV-count delay / contacts

只在 strict settings：

\[
M=5,8
\]

画点图/折线图。

不要对 M=3 填造不存在的数据。

---

# 13. Fig. 9 — Contact-Opportunity Sensitivity

这是论文主文重点图。

设置：

\[
C_{\max}=1,2,3,4
\]

推荐 3-panel line charts。

## Fig. 9(a)

Strict feasibility：

\[
6/9,\ 7/9,\ 9/9,\ 9/9
\]

y 轴可以使用：

\[
0\%-100\%
\]

---

## Fig. 9(b)

Strict-subset mean energy：

- 239095.092 J
- 234636.497 J
- 226768.196 J
- 227632.234 J

---

## Fig. 9(c)

Contacts/UAV：

- 0.733
- 1.029
- 1.044
- 1.222

主要论证：

\[
\boxed{
\text{too few contact opportunities}
\rightarrow
\text{smaller feasible region and higher energy}
}
\]

当 \(C_{\max}\ge3\) 后出现边际收益递减。

---

# 14. Fig. 10 — Bandwidth Sensitivity and KKT Shadow Prices

另一张主文重点图。

## Fig. 10(a)

Bandwidth scale：

\[
0.5B_0,\ B_0,\ 1.5B_0
\]

推荐：

**line chart**

y：

mean strict-subset UAV energy。

在 marker 旁标 strict：

- 8/9
- 9/9
- 9/9

---

## Fig. 10(b)

推荐：

\[
\boxed{\text{Grouped bar chart}}
\]

每个 bandwidth scale 两根柱：

- Bandwidth Relative Shadow
- CPU Relative Shadow

主要数据：

| Bandwidth | BW Shadow | CPU Shadow |
|---:|---:|---:|
| 0.5x | 0.011 | 0.000 |
| 1.0x | 0.005 | 0.000 |
| 1.5x | 0.005 | 0.008 |

该图用于展示资源压力转移。

---

# 15. Fig. 11 — Iteration-Budget Convergence

注意：

不同总 iteration budget 下的 RRT acceptance schedule 不完全相同。

因此不要伪装成：

> 同一条搜索轨迹在 25/50/100/200 的前缀。

论文应称：

\[
\boxed{\text{Iteration-Budget Sensitivity}}
\]

---

## Fig. 11(a)

line chart：

x：

\[
25,50,100,200
\]

y：

strict-subset mean energy。

在每个点旁标：

- 6/9
- 8/9
- 9/9
- 7/9

---

## Fig. 11(b)

line chart：

x：

iterations

y：

mean runtime。

数据约：

- 20.8 s
- 26.3 s
- 50.0 s
- 88.6 s

用于支持：

\[
100\text{ iterations}
\]

是 feasibility / runtime / quality 的 operating point，而不是完全收敛点。

---

# 16. Fig. 12 — Strong-Reference Benchmark

设置：

\[
K=28,\quad M=2,\quad E=2
\]

## Fig. 12(a)

推荐：

**scatter plot**

x：

- S45
- S46
- S47

y：

\[
\text{Gap to Best-Known (\%)}
\]

每个 standard algorithm seed 一个点。

不要只画三根 mean bar。

---

## Fig. 12(b)

推荐：

**two-bar chart**

- Standard Hybrid runtime
- Strong Search runtime

约：

\[
3.99s
\]

vs

\[
31.38s
\]

用于展示：

\[
\boxed{\text{solution quality vs computation budget}}
\]

---

# 17. Fig. 13 — GIS-Driven Real-Geography Case

这是外部真实性重点 Figure。

---

## Fig. 13(a): Real Geography Map

必须使用真实地理坐标。

数据：

\`data/real_case/stanislaus/usfs_fire_occurrences_selected59_2026-09-22.json\`

内容：

- real historical USFS fire-occurrence points；
- UAV depot；
- modeled MEC/facility anchors；
- real AOI；
- optimized UAV routes；
- MEC coverage；
- contact/offloaded task。

优先选择：

\[
\boxed{\text{S45/A100}}
\]

作为 route visualization，因为该 run 有：

- 1 realized MEC contact；
- 1 offloaded task。

这样图中能体现 Route–Contact–Offloading。

---

## Fig. 13(b): Real-Case Strict Feasibility

bar chart：

- Greedy: 0/3
- FTR-NM: 0/3
- Generic: 8/9
- Hybrid: 8/9

---

## Fig. 13(c): Generic vs Hybrid

推荐 paired plot。

common strict：

\[
2\text{ better}+6\text{ equal}+0\text{ worse}
\]

mean Hybrid advantage：

\[
0.543\%
\]

该 case 的作用是：

\[
\boxed{\text{external geography robustness}}
\]

而不是证明大量 MEC offloading。

---

# 18. Supplementary Figure A — Spatial Robustness

三个 profiles：

- Uniform
- Clustered
- Boundary-biased

推荐 3 个小 bar/point panels：

### (a)

Strict rate：

\[
9/9,\ 7/9,\ 6/9
\]

### (b)

Offload ratio：

\[
12.2\%,\ 27.5\%,\ 13.1\%
\]

### (c)

Bandwidth relative shadow：

\[
0.005,\ 0.013,\ 0.004
\]

不要把 absolute energy 作为主比较指标，因为三个 profile 的路线几何本身不同。

---

# 19. Supplementary Figure B — MEC Coverage Radius

设置：

\[
R/R_0=0.75,1.0,1.25
\]

推荐：

### (a)

Energy vs radius scale

### (b)

Route distance vs radius scale

或 contacts/UAV。

该实验定位为：

\[
\boxed{\text{contact geometry robustness}}
\]

不要声称 radius 越大越好。

---

# 20. 不推荐使用的图表

禁止或尽量避免：

- Pie chart；
- Radar chart；
- 3D bar；
- 3D surface；
- 渐变面积图；
- 过多双 y 轴；
- 颜色过多；
- 每个指标一张孤立柱状图；
- 用柱状图代替有顺序的连续趋势；
- 把 strict-subset energy 和完整样本 energy 混画而不标样本数。

---

# 21. 实验数据口径

## 21.1 Stage-1

主 UAV energy 始终使用：

\[
\boxed{\text{strict Stage-1 CVX energy}}
\]

只有：

\[
\text{stage1\_status}=\texttt{optimal}
\]

的结果才能进入主能耗统计。

---

## 21.2 Stage-2

Stage-2 仅用于获得稳定的 resource/QoS realization。

Stage-2：

\[
\min \text{ normalized MEC CPU occupation}
\]

under Stage-1 energy guard。

因此：

- CPU utilization 可作为 CPU-minimizing tie-break 下的稳定指标；
- bandwidth utilization 只是该 realization 的描述值；
- bandwidth utilization 本身不能证明 bandwidth bottleneck。

---

## 21.3 Resource Bottleneck

使用：

\[
\boxed{
\text{Stage-1 capacity shadow price}
+
\text{explicit resource scaling}
}
\]

relative shadow：

\[
\frac{\lambda_r C_r}{E^\star}
\]

Bandwidth / CPU bottleneck 判断优先看：

- BW relative shadow；
- CPU relative shadow；
- bandwidth scaling response。

---

## 21.4 K=100,E=2

只有：

\[
3/9
\]

strict。

所以该设置所有能耗/QoS必须写成：

> strict-subset statistics

不能画成完整 9-run mean。

---

## 21.5 M=3

\[
0/9
\]

strict 只表示：

> frozen search budget 下没有恢复 strict-feasible terminal solution。

不能标成：

> globally infeasible。

---

## 21.6 Deterministic baseline

Greedy / FTR-NM 是 deterministic。

因此：

\[
3\text{ scenario seeds}
\]

是 3 个独立结果。

不要把：

\[
3\text{ scenario}\times3\text{ algorithm seeds}
\]

伪装成 deterministic baseline 的 9 个独立结果。

---

# 22. 系统图与算法图的 Codex 任务要求

Codex 在处理系统模型图和算法框架图时，应遵循：

1. **不要调用 Python/Matplotlib 绘制最终系统图/算法图。**
2. 如果当前执行环境无法直接控制 Microsoft Visio：
   - 先生成完整 Visio construction specification；
   - 准备所有英文标签；
   - 准备节点、尺寸、坐标、连线、层次和分组；
   - 准备可导入 Visio 的矢量素材；
   - 不得用 Python raster 流程图冒充最终图。
3. 最终目标是可编辑的 Visio 矢量图。
4. 所有公式符号必须与论文正文一致。
5. 图中不要出现开发状态、TODO、debug 字样。

---

# 23. 推荐文件结构

建议新增：

\`\`\`
paper_figures/
├── visio/
│   ├── fig01_system_model.vsdx
│   ├── fig02_hybrid_alns_framework.vsdx
│   ├── fig02b_optimization_decomposition.vsdx   # optional
│   └── assets/
├── data/
│   ├── fig03_dense_workload.csv
│   ├── fig04_workload_structure.csv
│   ├── fig05_baselines.csv
│   ├── fig06_paired_generic_hybrid.csv
│   ├── fig07_ablation.csv
│   ├── fig08_mec_uav_sensitivity.csv
│   ├── fig09_contact_budget.csv
│   ├── fig10_bandwidth_shadow.csv
│   ├── fig11_iteration_budget.csv
│   ├── fig12_strong_reference.csv
│   └── fig13_real_geography.csv
├── scripts/
│   ├── plot_dense_workload.py
│   ├── plot_workload_structure.py
│   ├── plot_baselines.py
│   ├── plot_paired_comparison.py
│   ├── plot_ablation.py
│   ├── plot_sensitivity.py
│   ├── plot_contact_budget.py
│   ├── plot_bandwidth_shadow.py
│   ├── plot_iteration_budget.py
│   ├── plot_strong_reference.py
│   └── plot_real_geography.py
└── output/
    ├── pdf/
    ├── svg/
    └── png/
\`\`\`

---

# 24. 推荐主文 Figure 顺序

最终建议：

1. **Fig. 1 — System Model** — Visio
2. **Fig. 2 — Hybrid ALNS Framework** — Visio
3. Fig. 3 — Dense Workload Performance
4. Fig. 4 — Workload Structural Evolution
5. Fig. 5 — Baseline Comparison
6. Fig. 6 — Generic vs Hybrid Paired Comparison
7. Fig. 7 — Elite-Family Ablation
8. Fig. 8 — MEC/UAV Sensitivity
9. **Fig. 9 — Contact-Opportunity Sensitivity**
10. **Fig. 10 — Bandwidth Sensitivity + KKT Shadow Prices**
11. Fig. 11 — Iteration-Budget Sensitivity
12. Fig. 12 — Strong-Reference Benchmark
13. **Fig. 13 — GIS-Driven Real-Geography Case Study**

Supplement:

- Fig. S1 — Spatial Distribution Robustness
- Fig. S2 — Coverage-Radius Sensitivity
- 其他详细 QoS/resource plots 视版面决定。

---

# 25. 当前已有数据文档

Codex 在生成图之前优先读取：

- \`docs/current_research_achievements.md\`
- \`docs/paper_experiment_summary.md\`
- \`README.md\`

真实地理数据：

- \`data/real_case/stanislaus/usfs_fire_occurrences_selected59_2026-09-22.json\`

正式 real-case workflow：

- \`.github/workflows/stanislaus_real_geography_formal.yml\`

正式 real-case run：

- GitHub Actions Run \`35679546095\`

---

## 25.1 Codex 优先使用的已跟踪绘图数据

最终论文作图时，Codex **优先读取 Git 中已跟踪的 `paper_results/*.csv`**，
而不是依赖本地是否存在 `outputs/results/` 或手工下载 GitHub Actions artifact。

当前已跟踪：

- `paper_results/dense_workload.csv`
- `paper_results/baseline_summary.csv`
- `paper_results/ablation.csv`
- `paper_results/mec_count.csv`
- `paper_results/uav_count.csv`
- `paper_results/contact_budget.csv`
- `paper_results/bandwidth_sensitivity.csv`
- `paper_results/coverage_radius.csv`
- `paper_results/spatial_robustness.csv`
- `paper_results/iteration_budget.csv`
- `paper_results/strong_reference.csv`
- `paper_results/real_geography.csv`

这些文件是最终论文绘图的 compact publication interface。
原始 per-run JSON、日志和 Actions artifact 仍作为审计/复现实验依据，不要求
`git pull` 自动获取。

读取这些 CSV 前必须同时阅读：

- `paper_results/README.md`

其中定义了 strict-subset、deterministic baseline、Stage-1/Stage-2、
shadow price、real-geography 等统计口径。

---

# 26. 最终绘图目标

最终图集应体现清晰的论文证据链：

\[
\boxed{
\text{System}
\rightarrow
\text{Algorithm}
\rightarrow
\text{Baseline}
\rightarrow
\text{Ablation}
\rightarrow
\text{Workload}
\rightarrow
\text{Contact/Bandwidth Mechanism}
\rightarrow
\text{Convergence}
\rightarrow
\text{Strong Reference}
\rightarrow
\text{Real Geography}
}
\]

其中：

\[
\boxed{
\text{Fig. 9 Contact Budget}
+
\text{Fig. 10 Bandwidth/Shadow}
+
\text{Fig. 13 Real Geography}
}
\]

应作为实验章节最重点的新增图组。

---

# 27. 最重要的硬性要求

\[
\boxed{\text{System Model Figure: Visio only}}
\]

\[
\boxed{\text{Algorithm Framework Figure: Visio only}}
\]

\[
\boxed{\text{Do not use Python to imitate Visio diagrams}}
\]

Python 仅用于**数值实验图**。

系统图和算法图的最终版本必须达到正式论文矢量图标准，而不是开发文档中的草图或自动流程图。
