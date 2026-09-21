# 当前研究成果与实验总览

> 项目：UAV-MEC Patrol Research Codebase  
> 分支：\`develop\`  
> 当前状态：**主算法、基线、消融、三类敏感性实验、统一论文指标与 reduced-scale strong-reference benchmark 均已完成；下一阶段进入论文图表与正文整合。**

---

## 1. 当前研究问题已经固定

论文场景为：

> **大型林区固定监测节点周期巡护下的多无人机协同边缘计算。**

系统链路：

\[
\text{固定监测节点}
\rightarrow
\text{多 UAV 采集 / 缓存 / 携带 / 有限机载计算}
\rightarrow
\text{稀疏、异构、固定 MEC 边缘站}
\]

核心系统特征是：

\[
\boxed{\text{间歇 MEC 连接 / Contact Opportunity}}
\]

与传统“UAV 始终可连接边缘服务器”的模型不同，本文中 UAV 只有进入 MEC 覆盖区域时才能上传任务，因此路径、接触机会、卸载决策与连续资源分配彼此耦合。

当前主优化目标为：

\[
\boxed{\min E_{\mathrm{UAV}}^{\mathrm{tot}}}
\]

主要约束包括：

- 单任务 deadline；
- 平均任务时延；
- UAV 周期返航；
- UAV 电池预算；
- MEC 带宽容量；
- MEC CPU 容量；
- Store–Carry–Batch-Offload 时序；
- UAV 本地 FIFO；
- MEC 虚拟 FIFO；
- 批内 EDF。

---

## 2. 当前论文创新点

当前已经形成并冻结的核心创新点为：

> **提出一种面向间歇 MEC 的路径–接触–卸载联合 Hybrid ALNS，并利用 KKT 揭示连续资源最优结构。**

对应两层求解结构：

### 2.1 离散层

离散变量：

\[
\mathbf D=
\{
\text{UAV assignment},
\text{route},
\text{contact},
\text{Local/MEC},
\text{batch}
\}
\]

需要联合决定：

- 哪架 UAV 访问哪个监测任务；
- UAV 的访问顺序；
- 是否经过 MEC contact point；
- 每个任务本地计算还是 MEC 卸载；
- 卸载任务属于哪个 contact / batch。

### 2.2 连续资源层

固定离散结构后求解：

\[
(P1-R\mid\mathbf D):
\quad
\min_{\mathbf R}
E_{\mathrm{UAV}}(\mathbf D,\mathbf R)
\]

其中连续资源包括：

\[
\mathbf R=
\{
\text{UAV CPU},
\text{MEC bandwidth},
\text{MEC CPU},
\text{upload/event times}
\}
\]

最终整体形式为：

\[
V(\mathbf D)
=
\min_{\mathbf R\in\mathcal R(\mathbf D)}
E_{\mathrm{UAV}}(\mathbf D,\mathbf R)
\]

\[
(P1-D):
\quad
\min_{\mathbf D}V(\mathbf D)
\]

---

## 3. 已完成的 Proposed Hybrid ALNS

当前论文主算法已经冻结为：

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

完整角色如下。

### 3.1 Greedy Route Seed

实现：

- Parallel Greedy Insertion；
- Task-to-UAV assignment；
- deadline-aware insertion；
- cycle-aware insertion；
- route-distance insertion；
- route-local 2-opt；
- deterministic construction。

Greedy 的定位是：

\[
\boxed{\text{初始路径构造器}}
\]

而不是最终提出算法。

### 3.2 MEC Contact / Offloading Repair

针对几何路径可行、但 QoS / 计算约束不可行的问题，实现：

- critical local task detection；
- Local \(\rightarrow\) MEC；
- existing contact reuse；
- new contact insertion；
- batch construction；
- Store–Carry–Batch-Offload；
- equal-share resource proxy；
- normalized feasibility ranking。

因此初始解链路为：

\[
\text{Greedy Route}
\rightarrow
\text{MEC-assisted feasibility repair}
\]

### 3.3 Generic ALNS Exploration

Destroy operators：

- random task removal；
- critical task removal；
- route-segment removal。

Repair operators：

- cheapest insertion + MEC repair；
- regret-2 insertion + MEC repair。

框架机制：

- mature \`alns>=7\` package；
- RouletteWheel adaptive operator selection；
- Record-to-Record Travel acceptance；
- screened proxy evaluator；
- optimistic feasibility precheck；
- solution signature cache；
- gray-zone Stage-1 CVX refinement。

### 3.4 Elite Structural Intensification

Generic ALNS 找到较好的 elite solution 后，再进行问题特定的结构强化。

已实现：

- route-compute relocation；
- contact relocation；
- contact-point / cross-MEC replacement；
- contact removal；
- batch merge；
- batch split / new contact；
- Local/MEC mode reassignment；
- batch reassignment；
- family-diverse shortlist；
- progressive widening；
- strict Stage-1 CVX monotone acceptance。

最终算法不是简单地把所有 problem-specific operators 塞进 ALNS RouletteWheel，而是：

\[
\boxed{
\text{Generic exploration}
+
\text{problem-specific elite refinement}
}
\]

这也是当前消融实验支持的最终结构。

---

## 4. KKT 与 CVXPY 连续资源层成果

KKT 没有被放弃，而是明确承担连续资源解析层的角色。

### 4.1 已实现 KKT 结构

已实现：

- UAV local CPU cube-root KKT；
- MEC CPU square-root KKT；
- bandwidth dual price；
- bandwidth bisection；
- event-graph shadow-price backward propagation；
- stationarity residual；
- primal residual；
- dual residual；
- complementarity diagnostics；
- complementarity-aware stopping。

### 4.2 小规模 KKT-CVX 验证

此前 hard-regime validation 中：

\[
\max\text{ relative Stage-1 energy gap}
=
1.233\times10^{-9}
\]

并验证了双 MEC 状态下的高精度一致性。

因此：

\[
\boxed{
\text{KKT = 连续资源解析结构 / 数值近似 / 小规模交叉验证}
}
\]

### 4.3 Paper-scale 的当前定位

paper-scale 下 KKT primal recovery 尚未完全稳定，因此：

\[
\boxed{
\text{CVXPY Stage-1 = paper-scale correctness oracle}
}
\]

而 KKT 保留为：

- analytical structure；
- dual / shadow-price analysis；
- small-instance exact cross-check；
- fast resource approximation；
- paper-scale feasible-seed fallback。

**不能写成 KKT 被删除，也不能写成 paper-scale KKT 已完全替代 CVX。**

---

## 5. 已完成的实例与公平性验证

Paper-scale generator 已支持：

- \(K=30/50/80/100\)；
- \(M=3/5/8\)；
- \(E=2/3/4\)；
- 固定异构 MEC；
- seed-controlled monitoring nodes；
- heterogeneous task data/workload；
- contact candidate points；
- deadline lower bound；
- reproducibility tests。

同时已完成：

### MEC-count sweep fairness

改变 \(E\) 时：

- tasks 不变；
- deadlines 不变；
- monitoring-node realization 不变；
- MEC 采用 prefix nesting。

### UAV-count sweep fairness

改变 \(M\) 时：

- tasks 不变；
- deadlines 不变；
- MEC 不变；
- contact points 不变；
- 只改变 UAV 数量。

因此当前 sensitivity sweep 不是重新随机生成不同问题实例。

---

# 6. 已完成的实验总览

目前已经完成六大类论文实验：

1. **算法验证与 workload sensitivity**
2. **MEC-count sensitivity**
3. **UAV-count sensitivity**
4. **Baseline comparison**
5. **Elite-family ablation**
6. **Reduced-scale best-known strong-reference benchmark**

此外还完成：

- KKT-CVX validation；
- resource recourse gap scan；
- proxy ranking preservation；
- non-degeneracy scan；
- shared-MEC competition scan；
- paper-facing unified metrics pipeline。

---

# 7. Workload Sensitivity

设置：

\[
M=5,\quad E=2,\quad K\in\{50,80,100\}
\]

scenario seeds：

\[
45,46,47
\]

algorithm seeds：

\[
100,101,102
\]

ALNS：

\[
100\text{ iterations}
\]

最终统一指标如下。

| K | Stage-1 strict | Stage-2 strict | Mean Hybrid Energy (J) | Mean Delay (s) | Mean Deadline Slack (s) | Offload Ratio | Contacts/UAV | Route Distance (km) | Active-MEC BW Util. | Active-MEC CPU Util. |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 9/9 | 8/9 | 167015.350 | 204.607 | 132.680 | 8.0% | 0.533 | 8.655 | ≈100% | 44.1% |
| 80 | 9/9 | 8/9 | 226768.196 | 217.543 | 123.068 | 12.2% | 1.044 | 11.494 | ≈100% | 48.9% |
| 100 | 3/9 | 3/9 | 249008.510 | 220.135 | 122.442 | 16.7% | 1.467 | 12.362 | ≈100% | 59.4% |

主要趋势：

\[
K\uparrow
\Rightarrow
\text{offload ratio}\uparrow
\]

\[
K\uparrow
\Rightarrow
\text{contacts/UAV}\uparrow
\]

\[
K\uparrow
\Rightarrow
\text{route distance}\uparrow
\]

同时 MEC bandwidth 在 strict resource solutions 中基本始终接近满载。

### 关于 \(K=100,E=2\)

只有：

\[
3/9
\]

个 standard runs 是 strict Stage-1 optimal。

因此 \(K=100,E=2\) 的能耗、delay、slack 等只能写成：

> strict-subset statistics

不能写成完整九组平均。

---

# 8. MEC-count Sensitivity

设置：

\[
K=100,\quad M=5,\quad E\in\{2,3,4\}
\]

结果：

| E | Stage-1 Strict | Stage-2 Strict | Mean Energy (J) | Offload Ratio | Contacts/UAV | Active-MEC BW Util. | Active-MEC CPU Util. |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 3/9 | 3/9 | 249008.510 | 16.7% | 1.467 | ≈100% | 59.4% |
| 3 | 8/9 | 5/8 | 248254.117 | 20.2% | 1.440 | ≈100% | 47.5% |
| 4 | 8/9 | 5/8 | 249309.489 | 20.8% | 1.600 | ≈100% | 37.8% |

主要结论：

\[
\boxed{
E\uparrow
\Rightarrow
\text{strict feasibility robustness}\uparrow
}
\]

同时：

\[
E\uparrow
\Rightarrow
\text{MEC CPU load 更分散}
\]

但是不能写：

\[
E\uparrow\Rightarrow E_{\mathrm{UAV}}\downarrow
\]

因为 strict 子集上的能耗并不单调。

---

# 9. UAV-count Sensitivity

设置：

\[
K=80,\quad E=2,\quad M\in\{3,5,8\}
\]

结果：

| M | Stage-1 Strict | Stage-2 Strict | Mean Energy (J) | Mean Delay (s) | Mean Slack (s) | Offload Ratio | Contacts/UAV | Route Distance (km) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 0/9 | 0/9 | - | - | - | - | - | - |
| 5 | 9/9 | 8/9 | 226768.196 | 217.543 | 123.068 | 12.5% | 1.050 | 11.498 |
| 8 | 9/9 | 8/9 | 224480.040 | 211.067 | 129.545 | 12.5% | 0.641 | 11.363 |

从 \(M=5\rightarrow8\)：

\[
\text{mean energy}\downarrow \approx 1.01\%
\]

同时：

- mean delay 下降约 6.48 s；
- mean deadline slack 增加约 6.48 s；
- contacts/UAV 从 1.050 降到 0.641；
- offload ratio 基本不变。

因此增加 UAV 的主要作用不是“更多卸载”，而是：

> **缓解路径与服务压力，并在更多 UAV 之间分摊接触任务。**

### 关于 \(M=3\)

当前 frozen 100-iteration search budget 下：

\[
0/9\text{ strict}
\]

这只能写成：

> 当前搜索预算下没有恢复 strict-feasible terminal structure。

不能写成：

> \(M=3\) 时原数学问题全局不可行。

---

# 10. Baseline Comparison

当前 baseline 已经完整包含：

1. Greedy + MEC Repair
2. Fixed-Route Nearest-MEC（FR-NM）
3. Route-GA + deterministic MEC repair
4. Generic ALNS
5. Proposed Hybrid ALNS

---

## 10.1 中等负载能耗质量对比

设置：

\[
K=50,\quad E=2
\]

| Method | Strict Feasibility | Mean Energy (J) | Median Energy (J) |
|---|---:|---:|---:|
| Greedy + MEC Repair | 2/3 unique scenarios | 230637.625 | 230637.625 |
| FR-NM | 3/3 unique scenarios | 229613.102 | 229866.963 |
| Route-GA + MEC Repair | 9/9 | 235438.000 | 227768.558 |
| Generic ALNS | 9/9 | 170323.586 | 172689.240 |
| Proposed Hybrid | **9/9** | **167015.350** | **170279.207** |

### Hybrid vs FR-NM

\[
\boxed{9\text{ better}+0\text{ equal}+0\text{ worse}}
\]

Mean paired advantage：

\[
\boxed{27.297\%}
\]

Median：

\[
26.629\%
\]

### Hybrid vs Route-GA

\[
\boxed{9\text{ better}+0\text{ equal}+0\text{ worse}}
\]

Mean paired advantage：

\[
\boxed{28.884\%}
\]

Median：

\[
28.771\%
\]

### Hybrid vs Generic ALNS

\[
5\text{ better}+4\text{ equal}+0\text{ worse}
\]

Mean：

\[
1.803\%
\]

Median：

\[
0.047\%
\]

这说明轻负载下 Generic ALNS 已经可能接近较优结构，所以 elite structural refinement 的增益更加偏态。

---

## 10.2 高负载可行性鲁棒性

设置：

\[
K=80,\quad E=2
\]

| Method | Strict Feasibility |
|---|---:|
| Greedy + MEC Repair | 0/3 unique scenarios |
| FR-NM | 0/3 unique scenarios |
| Route-GA + MEC Repair | 0/3 high-budget pilot |
| Generic ALNS | **9/9** |
| Proposed Hybrid | **9/9** |

Hybrid vs Generic：

\[
\boxed{8\text{ better}+1\text{ equal}+0\text{ worse}}
\]

Mean paired gain：

\[
\boxed{1.378\%}
\]

Median gain：

\[
\boxed{1.154\%}
\]

该设置是当前最适合说明：

> **problem-specific elite structural intensification 相对 Generic ALNS 的稳定增量价值**

的一组实验。

---

# 11. Elite-family Ablation

设置：

\[
K=80,\quad E=2
\]

每个 ablation 与 Full Hybrid 共享同一 Generic ALNS exploration，然后只在 elite refinement 阶段分叉。

| Ablation | Full Better | Equal | Ablated Better | Mean Full Advantage |
|---|---:|---:|---:|---:|
| w/o Route-compute relocation | 6 | 3 | 0 | **0.709%** |
| w/o Contact family | 3 | 5 | 1 | **0.302%** |
| w/o explicit Batch family | 2 | 6 | 1 | 0.009% |
| w/o Progressive widening | 0 | 9 | 0 | 0.000% |

当前支持的结论：

### Route-compute relocation

是主要结构强化机制：

\[
\boxed{\text{dominant elite family}}
\]

### Contact family

具有正向但较弱的辅助价值。

### Explicit batch family

在个别状态有价值，但 \(K=80,E=2\) 下 aggregate effect 很小。

### Progressive widening

当前主要是 near-miss fallback，而不是典型能耗改善来源。

因此不能写：

> 所有模块都同等重要。

---

# 12. Reduced-scale Best-Known Strong Reference

最后一个实验用于评估：

> 标准 100-iteration Proposed Hybrid 与更高预算强搜索之间仍有多大解质量空间。

**该实验不是 global optimum benchmark。**

---

## 12.1 为什么最终使用 \(K=28,M=2,E=2\)

scale scout 结果：

- \(K=8,M=2\)：strict，但退化为 all-local；
- \(K=12,M=1\)：过紧，强搜索仍 precheck infeasible；
- \(K=16,M=2\)：strict，但 best-known 仍 all-local；
- \(K=24,M=2\)：部分解出现 offloading，但 best-known 仍 all-local；
- \(K=28,M=2\)：strict，且 best-known 保持真实 contact/offload；
- \(K=32,M=2\)：standard S45/A100 已 CVX infeasible。

因此最终固定：

\[
\boxed{K=28,\quad M=2,\quad E=2}
\]

保持原 \`configs/baseline.yaml\` 参数不变。

---

## 12.2 Standard 与 Strong 配置

Standard Proposed Hybrid：

- scenario seeds 45/46/47；
- algorithm seeds 100/101/102；
- 100 iterations；
- 2 elite rounds。

Strong Reference：

- seeds 700–711；
- 1000 iterations；
- 6 elite rounds；
- larger exact shortlist；
- larger task pool；
- larger route-position pool；
- strict Stage-1 CVX verification。

---

## 12.3 最终结果

| Scenario | Best-known Energy (J) | Contacts | Offloaded | Strong Hits | Mean Standard Gap | Median Gap |
|---:|---:|---:|---:|---:|---:|---:|
| 45 | 97905.087437 | 1 | 2 | 4/12 | 9.695% | 8.610% |
| 46 | 99503.124192 | 2 | 2 | 5/12 | **0.071%** | 0.071% |
| 47 | 103608.196273 | 1 | 1 | 1/12 | 8.137% | 9.203% |

aggregate：

\[
\boxed{\text{standard strict}=9/9}
\]

\[
\boxed{\text{strong strict}=36/36}
\]

\[
\boxed{\text{mean standard-to-best-known gap}=5.968\%}
\]

\[
\boxed{\text{median gap}=8.610\%}
\]

\[
\boxed{\text{maximum gap}=11.866\%}
\]

标准 9 个 runs 中：

- within 0.01%：0/9；
- within 0.1%：3/9；
- within 1%：3/9。

strong best-known hit：

\[
10/36=27.8\%
\]

runtime：

- Standard mean：3.990 s；
- Strong mean：31.380 s。

### S47 confirmation

由于 S47 正式 12 个 strong seeds 只有 1 个命中 best-known，又额外运行：

- new strong seeds 712–723；
- seed707 作为 anchor。

没有找到低于：

\[
103608.196273\text{ J}
\]

的新解。

所以该值继续保留为：

> **empirical best-known reference**

而不是 global optimum。

---

# 13. Unified Paper Metrics Pipeline

为了避免不同实验表格口径不一致，已经建立统一 paper metric extractor。

统一提取：

- Stage-1 UAV energy；
- average delay；
- deadline slack；
- cycle utilization；
- battery utilization；
- total route distance；
- route detour；
- offload ratio；
- contacts/UAV；
- active UAV–MEC pairs；
- MEC selection distribution；
- bandwidth utilization；
- CPU utilization；
- fixed flight/collection energy share；
- communication energy share；
- local-compute energy share；
- algorithm runtime。

### Stage-1 / Stage-2 口径

主优化能耗永远使用：

\[
\boxed{\text{strict Stage-1 CVX}}
\]

资源利用率与 QoS tie-break 则使用 lexicographic Stage-2：

- Stage-1 energy guard：\(10^{-5}\) relative；
- Stage-2 minimize normalized MEC CPU occupation。

原因是 MEC CPU 不直接进入 UAV energy objective，Stage-1 primal allocation 可能不唯一。

因此：

> **Stage-2 只用于获得可重复的资源利用率，不替换 Stage-1 主目标能耗。**

---

# 14. 当前最重要的系统层发现

多个实验中，CPU-minimizing Stage-2 解经常出现较高的 MEC bandwidth allocation；但 Stage-2 并未最小化 bandwidth，因此该利用率只能作为描述性指标，不能单独证明带宽约束是瓶颈。

例如 workload：

\[
44.1\%
\rightarrow
48.9\%
\rightarrow
59.4\%
\]

MEC-count sweep：

\[
59.4\%
\rightarrow
47.5\%
\rightarrow
37.8\%
\]

因此当前场景最稳定的系统结论之一是：

\[
\boxed{
\text{间歇 contact opportunity / wireless bandwidth}
\text{ 是持续瓶颈}
}
\]

而不是单纯的 MEC CPU 不足。

这直接支撑：

\[
\boxed{
\text{Route}
\leftrightarrow
\text{Contact}
\leftrightarrow
\text{Offloading}
\leftrightarrow
\text{Resource}
}
\]

联合优化的必要性。

---

# 15. 当前可以支撑的论文结论

当前实验可以较有把握地支持：

1. **固定路径 + 最近 MEC 的分解式策略会显著损失能耗质量。**
2. **独立 Route-GA 在中等负载可行，但解质量明显弱于 Hybrid；高负载下可行性恢复能力也更弱。**
3. **Generic ALNS 是强内部 baseline。**
4. **Hybrid elite refinement 在 \(K=80,E=2\) 下稳定优于或等于 Generic ALNS。**
5. **Route-compute relocation 是最主要的 elite family。**
6. **Contact family 具有正向辅助作用。**
7. **负载升高后 offload/contact/route pressure 同时上升。**
8. **增加 MEC 数量显著改善高负载 strict feasibility。**
9. **增加 UAV 数量可缓解 route/service pressure，并降低 contacts/UAV。**
10. **无线带宽 / contact opportunity 是当前场景持续瓶颈。**
11. **KKT 推导能准确揭示固定离散解下的连续资源结构。**
12. **100-iteration Hybrid 是计算预算与解质量之间的折中，而不是全局最优保证。**

---

# 16. 当前不能过度声称的内容

以下表述目前不应该出现在论文中：

### 16.1 不能声称全局最优

Strong benchmark 是：

> best-known strong reference

不是：

> exact global optimum。

### 16.2 不能说 K=100/E=2 的 249 kJ 是完整九组均值

因为只有 3/9 strict。

### 16.3 不能说 M=3 数学问题全局不可行

只能说当前 frozen search budget 下 0/9 strict。

### 16.4 不能说 MEC 数量越多能耗越低

E=2/3/4 能耗不单调。

### 16.5 不能说每个 elite family 都同等重要

消融明确显示 route family 远强于 batch / widening。

### 16.6 不能说 KKT 已完全替代 paper-scale CVXPY

当前：

\[
\boxed{\text{CVXPY = paper-scale correctness oracle}}
\]

仍然成立。

---

# 17. 当前仓库中的核心实验脚本

主要实验脚本包括：

- \`experiments/run_hybrid_validation.py\`
- \`experiments/run_elite_family_ablation.py\`
- \`experiments/run_core_baseline_comparison.py\`
- \`experiments/run_ga_baseline_comparison.py\`
- \`experiments/run_small_strong_benchmark.py\`
- \`experiments/aggregate_small_strong_benchmark.py\`
- \`experiments/aggregate_paper_metrics.py\`
- \`experiments/aggregate_core_baselines.py\`
- \`experiments/aggregate_ga_baselines.py\`
- \`experiments/aggregate_uav_sensitivity.py\`

连续资源验证相关：

- \`experiments/run_resource_stress_validation.py\`
- \`experiments/run_recourse_gap_scan.py\`
- \`experiments/run_proxy_ranking_scan.py\`
- \`experiments/run_nondegeneracy_scan.py\`
- \`experiments/run_shared_mec_scan.py\`

---

# 18. 当前论文实验链是否完整

截至目前，计划内主要实验已经全部完成：

- [x] Proposed Hybrid 主算法；
- [x] KKT-CVX continuous-resource validation；
- [x] workload sensitivity；
- [x] MEC-count sensitivity；
- [x] UAV-count sensitivity；
- [x] Greedy baseline；
- [x] FR-NM baseline；
- [x] Route-GA baseline；
- [x] Generic ALNS baseline；
- [x] Hybrid vs Generic paired comparison；
- [x] Route family ablation；
- [x] Contact family ablation；
- [x] Batch family ablation；
- [x] Progressive widening ablation；
- [x] paper metric unification；
- [x] reduced-scale best-known strong benchmark；
- [x] S47 additional strong-reference confirmation。

因此：

\[
\boxed{\text{核心实验阶段已经完成}}
\]

---

# 19. 下一阶段工作

目前不建议继续无目的增加算法模块或 baseline。

下一阶段应切换到论文表达：

1. 生成最终主图；
2. 生成 compact paper tables；
3. 整理 convergence / runtime 图；
4. 绘制系统模型图；
5. 绘制算法流程图；
6. 将实验结果写入论文“实验设置—对比—消融—敏感性—讨论”章节；
7. 将 KKT 推导与 CVX verification 写入算法/理论章节；
8. 检查论文所有结论是否严格匹配 strict/sample 口径。

建议最终论文图表至少包括：

- workload vs energy / strict feasibility；
- workload vs offload ratio / contacts / distance；
- workload vs BW/CPU utilization；
- MEC count vs strict feasibility / offload ratio；
- UAV count vs delay / contacts/UAV；
- baseline energy comparison；
- elite-family ablation；
- strong-reference gap / runtime comparison。

---

# 20. 当前成果一句话总结

当前已经从“一个无人机 MEC 算法想法”推进为一套完整、可复现的研究工作：

\[
\boxed{
\text{间歇 MEC 场景建模}
+
\text{Route–Contact–Offloading 联合 Hybrid ALNS}
+
\text{KKT 连续资源结构}
+
\text{Strict CVX 验证}
+
\text{Baseline / Ablation / Sensitivity / Strong Reference 完整实验}
}
\]

当前真正剩下的主要工作已经不是继续补算法，而是：

\[
\boxed{\text{把已有结果转换成高质量论文图表与正文}}
\]

---

## 相关文档

- \`README.md\`：开发路线、算法结构、实验进度与命令；
- \`docs/paper_experiment_summary.md\`：论文实验结果汇总；
- 本文档：当前研究成果、实验与论文结论的中文总览。


---

# 补充实验：Dense Workload 与 Iteration-Budget Convergence

## A. Dense Workload Curve

为增强主负载图的连续性，在原 \(K=50/80/100\) detailed table 之外，新增：

\[
K\in\{30,40,50,60,70,80\},\quad M=5,\quad E=2
\]

每个 K 使用 scenario seeds 45/46/47 与 algorithm seeds 100/101/102，共 9 runs。

| K | Generic strict | Hybrid strict | Generic Mean Energy (J) | Hybrid Mean Energy (J) | Mean Hybrid Gain | Offload Ratio | Contacts/UAV | Route Distance (km) | Runtime (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 9/9 | 9/9 | 122917.377 | 122914.052 | 0.003% | 5.9% | 0.267 | 6.465 | 3.611 |
| 40 | 9/9 | 9/9 | 135783.361 | 135693.420 | 0.066% | 8.9% | 0.378 | 7.034 | 5.491 |
| 50 | 9/9 | 9/9 | 170323.586 | 167015.350 | 1.803% | 8.0% | 0.533 | 8.655 | 14.449 |
| 60 | 9/9 | 9/9 | 186149.891 | 182822.562 | 1.807% | 9.6% | 0.667 | 9.385 | 24.501 |
| 70 | 9/9 | 9/9 | 205019.285 | 202464.782 | 1.271% | 9.8% | 0.689 | 10.342 | 28.862 |
| 80 | 9/9 | 9/9 | 230038.323 | 226768.196 | 1.378% | 12.2% | 1.044 | 11.494 | 52.303 |

该结果显示：

- \(K=30/40\) 时 Hybrid 相对 Generic ALNS 的额外结构收益接近 0；
- 从 \(K=50\) 起，Hybrid 的 paired energy gain 明显增大；
- 随 K 增加，offload、contacts/UAV、route distance 与 runtime 总体上升；
- 这支持“Route–Contact–Offloading coupling 越紧，problem-specific elite refinement 越有价值”的解释。

## B. Iteration-Budget Convergence / Budget Sensitivity

设置：

\[
K=80,\quad M=5,\quad E=2
\]

比较 25/50/100/200 iterations。各预算使用相同 scenario/algorithm seed 组合，但由于 RRT acceptance schedule 会随总 iteration budget 改变，因此这些是 paired budget runs，不是同一搜索轨迹的简单前缀。

| Iterations | Strict | Conditional Mean Energy (J) | Mean Gap to Pair-Best | Mean Runtime (s) |
|---:|---:|---:|---:|---:|
| 25 | 6/9 | 245028.040 | 14.452% | 20.798 |
| 50 | 8/9 | 238428.651 | 9.580% | 26.343 |
| 100 | **9/9** | 226768.196 | 2.568% | 50.011 |
| 200 | 7/9 | 217985.012 | 0.000% on its strict subset | 88.577 |

在 100 与 200 都 strict 的 7 个 paired runs 中：

- 200 iterations：7/7 energy lower；
- mean 200-vs-100 energy advantage：约 **3.172%**；
- 但 200 iterations 有 2/9 runs 退化为 \`optimal_inaccurate\`，因此 strict robustness 低于 100 iterations。

因此论文中 100 iterations 的定位应写成：

> **固定计算预算下兼顾 strict-feasibility robustness、runtime 与 solution quality 的 operating point。**

不能写成“100 iterations 后算法已经完全收敛”。


---

# 补充实验：Bandwidth / Contact Geometry / Spatial Robustness

## C. MEC Bandwidth Sensitivity

设置：

\[
K=80,\quad M=5,\quad E=2,\quad B/B_0\in\{0.5,1.0,1.5\}
\]

任务、deadline、UAV、MEC 坐标和随机种子全部固定，仅缩放 MEC bandwidth。

| Bandwidth Scale | Stage-1 Strict | Mean Energy (J) | Offload Ratio | Contacts/UAV | Mean BW Relative Shadow | Mean CPU Relative Shadow | Mean Runtime (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 | 8/9 | 230892.958 | 12.8% | 1.125 | **0.011** | 0.000 | 61.768 |
| 1.00 | **9/9** | **226768.196** | 12.2% | 1.044 | 0.005 | 0.000 | 51.825 |
| 1.50 | **9/9** | 227432.750 | 13.1% | 1.089 | 0.005 | **0.008** | 52.077 |

其中 relative shadow 定义为 Stage-1 capacity dual 乘以对应容量，再除以 Stage-1 最优能耗；它反映按比例放宽该资源容量时的局部边际价值。

结果支持：

- bandwidth 减半后 strict feasibility 从 9/9 降为 8/9；
- 条件平均 UAV energy 上升；
- bandwidth relative shadow 从约 0.005 上升至约 0.011，说明低带宽状态下额外通信容量具有更高边际价值；
- bandwidth 放大到 1.5× 后，bandwidth shadow 不再明显下降，而 CPU relative shadow 上升，说明资源压力可能从通信侧部分转移到 MEC compute 侧；
- 因此“通信资源紧张”应由 **capacity shadow + explicit scaling response** 支撑，而不是由某个 Stage-2 bandwidth utilization 数值单独证明。

## D. MEC Coverage-Radius / Contact-Geometry Sensitivity

设置：

\[
R/R_0\in\{0.75,1.0,1.25\}
\]

| Radius Scale | Stage-1 Strict | Mean Energy (J) | Offload Ratio | Contacts/UAV | Route Distance (km) | BW Relative Shadow |
|---:|---:|---:|---:|---:|---:|---:|
| 0.75 | 9/9 | 229060.049 | 13.1% | 0.978 | 11.645 | 0.004 |
| 1.00 | 9/9 | **226768.196** | 12.2% | 1.044 | **11.494** | 0.005 |
| 1.25 | 9/9 | 231151.142 | 11.9% | 0.889 | 11.754 | 0.004 |

覆盖半径变化并未产生单调能耗趋势。原因是半径变化同时改变可选 contact-point 几何位置、绕行距离、通信距离和最终卸载结构。因此这组实验应解释为：

> **contact geometry sensitivity / robustness**

而不是“coverage 越大一定越优”的单调容量实验。

更直接的 Contact Opportunity 约束实验采用独立的 per-UAV contact-budget sweep \(C_{\max}=1/2/3/4\)。

## E. Spatial-Distribution Robustness

固定：

\[
K=80,\quad M=5,\quad E=2
\]

任务 data size 与 cycles-per-bit 随机流保持一致，仅改变监测节点空间分布：

- uniform；
- clustered；
- boundary-biased。

| Spatial Profile | Stage-1 Strict | Mean Energy on Strict Subset (J) | Mean Hybrid Gain | Offload Ratio | Contacts/UAV | Route Distance (km) | BW Relative Shadow |
|---|---:|---:|---:|---:|---:|---:|---:|
| uniform | **9/9** | 226768.196 | 1.378% | 12.2% | 1.044 | 11.494 | 0.005 |
| clustered | 7/9 | 146764.392 | 0.200% | 27.5% | 0.971 | 6.981 | **0.013** |
| boundary-biased | 6/9 | 226126.636 | 0.381% | 13.1% | 0.933 | 11.485 | 0.004 |

该实验的主要用途是验证 distribution shift，而不是比较三个 profile 的绝对能耗高低。特别是 clustered profile 的几何路径显著更短，因此绝对能耗天然更低。

可以支持的结论：

- Proposed Hybrid 在三种空间分布下均能恢复一定比例的 strict solutions；
- clustered/boundary shift 会降低 strict-feasibility robustness，说明空间分布本身是重要难度来源；
- clustered 情况虽然路线更短，但 offload ratio 显著上升且 bandwidth shadow 更高，表明“几何距离更短”并不等价于“通信/计算耦合更弱”；
- 因此后续论文可以把这组实验定位为 **out-of-distribution spatial robustness**。


---

# 补充实验：Per-UAV Contact-Budget Sensitivity

为直接验证“间歇 MEC / Contact Opportunity”这一核心机制，固定：

\[
K=80,\quad M=5,\quad E=2
\]

并保持任务、deadline、UAV、MEC、contact candidate geometry、scenario seeds
和 algorithm seeds 不变，仅改变每架 UAV 在一个周期内允许的最大 contact visits：

\[
C_{\max}\in\{1,2,3,4\}
\]

| \(C_{\max}\) | Stage-1 Strict | Stage-2 Strict | Mean Energy on Strict Subset (J) | Offload Ratio | Contacts/UAV | Route Distance (km) | BW Relative Shadow | CPU Relative Shadow | Mean Hybrid Gain | Runtime (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6/9 | 2/6 | 239095.092 | 12.5% | 0.733 | 12.180 | 0.004 | 0.000 | 1.155% | 36.967 |
| 2 | 7/9 | 5/7 | 234636.497 | 12.5% | 1.029 | 11.938 | 0.004 | 0.000 | 0.213% | 50.179 |
| 3 | **9/9** | 8/9 | **226768.196** | 12.2% | 1.044 | **11.494** | 0.005 | 0.000 | 1.378% | 45.932 |
| 4 | **9/9** | 6/9 | 227632.234 | 13.5% | 1.222 | 11.561 | 0.004 | 0.001 | 0.987% | 78.473 |

主要结论：

1. 当 \(C_{\max}=1\) 时，strict feasibility 仅为 6/9；提高到 2 后为 7/9；
2. 当 \(C_{\max}=3\) 时恢复到 9/9 strict，并且 strict-subset mean energy
   相比 \(C_{\max}=1\) 下降约 5.16%；
3. 继续放宽到 \(C_{\max}=4\) 后 strict rate 仍为 9/9，但平均能耗并未继续下降，
   runtime 反而明显增加；
4. 因此 contact opportunity 对高负载系统存在明显的“受限—充足”区间：
   **过少 contact 会缩小可行域并推高能耗，而在达到足够接触机会之后，继续增加
   contact budget 的边际收益很小。**
5. 这组实验比 coverage-radius sweep 更直接，因为它不改变 MEC 几何或通信距离，
   只改变离散 contact opportunity budget。

论文中可以用这组实验直接支撑：

\[
\boxed{
\text{intermittent contact availability}
\text{ directly affects feasibility and energy quality}
}
\]

但不应把 \(C_{\max}=4\) 能耗略高于 \(C_{\max}=3\) 解释成“更多 contact 有害”；
Hybrid 是有限预算启发式搜索，额外 action space 同时也会扩大搜索空间。
