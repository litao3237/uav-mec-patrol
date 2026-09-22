# Paper Experiment Summary

This file consolidates the paper-facing experimental evidence for the frozen
ESI-ALNS. The main baseline comparison now uses **8 independent scenario
instances (seeds 45--52) x 3 algorithm repetitions (seeds 100/101/102)** with a
frozen ALNS budget of 100 iterations. Earlier sensitivity/ablation experiments
that have not yet been expanded retain their original 3-scenario setting
(seeds 45/46/47).

The primary objective is total UAV energy. A result is counted as a strict
resource optimum only when the Stage-1 CVX status is exactly `optimal`.
Resource/QoS tie-break metrics use only runs whose lexicographic Stage-2 status
is also exactly `optimal`.

---

## 1. Proposed algorithm

The frozen paper-facing algorithm is

[
	ext{Greedy Route Seed}
ightarrow
	ext{MEC Contact/Offloading Repair}
ightarrow
	ext{B-ALNS Exploration}
ightarrow
	ext{Elite Structural Intensification}
ightarrow
	ext{Strict Stage-1 CVX Acceptance}.
]

The continuous fixed-discrete resource layer is analyzed by KKT structure and
verified by CVXPY. CVXPY remains the paper-scale correctness oracle.

---

## 2. Main workload sensitivity

Setting: (M=5), (E=2), (Kin{50,80,100}).

| K | Stage-1 strict | Stage-2 strict | Mean ESI-ALNS energy (J) | Mean delay (s) | Mean deadline slack (s) | Offload ratio | Contacts/UAV | Route distance (km) | Active-MEC BW util. | Active-MEC CPU util. | Fixed-energy share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 9/9 | 8/9 | 167015.350 | 204.607 | 132.680 | 0.080 | 0.533 | 8.655 | 1.000 | 0.441 | 0.992 |
| 80 | 9/9 | 8/9 | 226768.196 | 217.543 | 123.068 | 0.122 | 1.044 | 11.494 | 1.000 | 0.489 | 0.983 |
| 100 | 3/9 | 3/9 | 249008.510 | 220.135 | 122.442 | 0.167 | 1.467 | 12.362 | 1.000 | 0.594 | 0.974 |

Interpretation:

- workload growth increases offload demand, contact frequency, route length, and
  MEC CPU pressure;
- active-MEC bandwidth is consistently saturated;
- K=100/E=2 is a high-pressure regime with only 3/9 strict Stage-1 runs, so the
  K=100 means above are strict-subset statistics rather than full 9-run means;
- fixed flight/collection energy remains dominant, but its share falls as load
  rises, so communication/resource-coupled energy becomes more relevant.

---

## 3. MEC-count sensitivity

Setting: (K=100), (M=5), (Ein{2,3,4}).

| E | Stage-1 strict | Stage-2 strict | Mean ESI-ALNS energy (J) | Mean delay (s) | Mean deadline slack (s) | Offload ratio | Contacts/UAV | Route distance (km) | Active-MEC BW util. | Active-MEC CPU util. | Fixed-energy share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 3/9 | 3/9 | 249008.510 | 220.135 | 122.442 | 0.167 | 1.467 | 12.362 | 1.000 | 0.594 | 0.974 |
| 3 | 8/9 | 5/8 | 248254.117 | 227.245 | 114.610 | 0.202 | 1.440 | 12.490 | 1.000 | 0.475 | 0.976 |
| 4 | 8/9 | 5/8 | 249309.489 | 227.642 | 113.393 | 0.208 | 1.600 | 12.469 | 1.000 | 0.378 | 0.978 |

Interpretation:

- increasing MEC count strongly improves strict feasibility at K=100;
- offload ratio rises while mean active-MEC CPU utilization falls, showing CPU
  load spreading across more MECs;
- active-MEC bandwidth remains saturated, so additional MEC sites do not remove
  the communication bottleneck;
- energy is not monotone in E over the available strict subsets. The primary
  supported claim is improved feasibility/resource availability, not a monotone
  energy-reduction claim.

---

## 4. UAV-count sensitivity

Setting: (K=80), (E=2), (Min{3,5,8}).

| M | Stage-1 strict | Stage-2 strict | Mean ESI-ALNS energy (J) | Mean delay (s) | Mean deadline slack (s) | Offload ratio | Contacts/UAV | Route distance (km) | Active-MEC BW util. | Active-MEC CPU util. | Fixed-energy share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 0/9 | 0/9 | - | - | - | - | - | - | - | - | - |
| 5 | 9/9 | 8/9 | 226768.196 | 217.543 | 123.068 | 0.125 | 1.050 | 11.498 | 1.000 | 0.489 | 0.983 |
| 8 | 9/9 | 8/9 | 224480.040 | 211.067 | 129.545 | 0.125 | 0.641 | 11.363 | 1.000 | 0.639 | 0.985 |

Interpretation:

- M=3 does not recover a strict-feasible terminal structure under the frozen
  100-iteration budget; this is not a proof of global mathematical infeasibility;
- M=5 and M=8 are both 9/9 strict Stage-1;
- moving from M=5 to M=8 reduces mean ESI-ALNS energy by about 1.01%, reduces
  delay, increases deadline slack, and lowers contacts per UAV;
- the offload fraction stays nearly constant, so the main effect of additional
  UAVs is reduced route/service pressure and redistribution of contact work.

---

## 5. Baseline comparison

The main comparison has been expanded to **8 independent scenarios x 3
algorithm repetitions**. The 24 stochastic runs are nested within 8 independent
scenario instances and must not be described as 24 independent scenarios.
Deterministic GR-MR and FTR-NM are counted once per scenario.

### 5.1 Moderate-load energy-quality comparison

Setting: (K=50,M=5,E=2), scenario seeds 45--52, algorithm seeds 100/101/102.

| Method | Strict feasibility | Mean energy (J) | Median energy (J) |
|---|---:|---:|---:|
| GR-MR | 7/8 unique scenarios | 226449.279 | 227768.558 |
| FTR-NM | 8/8 unique scenarios | 227825.225 | 227281.171 |
| RGA-MR | 24/24 | 227955.557 | 227001.502 |
| B-ALNS | 24/24 | 165966.950 | 166786.002 |
| ESI-ALNS | 24/24 | **163189.844** | **165558.602** |

Paired ESI-ALNS comparisons:

- versus FTR-NM: ESI-ALNS is lower in all 24 nested comparisons (all 8
  independent scenarios); mean paired advantage 28.378%, median 27.424%;
- versus RGA-MR: 24/24 lower; mean paired advantage 28.341%, median 28.248%;
- versus B-ALNS: 14/24 lower, 10/24 equal, 0/24 worse; mean paired advantage
  1.549%, run-level median 0.079%.

After averaging the three algorithm repetitions inside each independent
scenario, the ESI-ALNS-vs-B-ALNS gain is positive in 7/8 scenarios and zero in
scenario 46. The mean of the eight scenario-level gains is 1.549% and the
scenario-level median is about 1.187%. Thus the gain is heterogeneous rather
than uniformly large, but it is no longer confined to the original three
scenarios.

### 5.2 High-load feasibility robustness

Setting: (K=80,M=5,E=2), scenario seeds 45--52, algorithm seeds 100/101/102.

| Method | Strict feasibility | Interpretation |
|---|---:|---|
| GR-MR | 1/8 unique scenarios | deterministic construction rarely recovers a strict solution |
| FTR-NM | 1/8 unique scenarios | fixed task route + nearest-MEC repair rarely recovers a strict solution |
| RGA-MR | 3/24 | all three strict runs occur in scenario 49 |
| B-ALNS | 21/24 | strict in every scenario at least once |
| ESI-ALNS | 21/24 | same strict set as B-ALNS; ESI is an energy intensification stage |

The three non-strict B-ALNS/ESI-ALNS runs are:

- scenario 49 / algorithm seed 100: `optimal_inaccurate`;
- scenario 52 / algorithm seed 100: `infeasible_precheck`;
- scenario 52 / algorithm seed 102: `infeasible_precheck`.

Thus 6/8 independent scenarios are strict in all three repetitions, while
scenarios 49 and 52 are partially strict. No independent scenario has zero
strict B-ALNS/ESI-ALNS repetitions.

On the 21 common-strict B-ALNS/ESI-ALNS pairs:

- ESI-ALNS better: 17/21;
- equal: 4/21;
- worse: 0/21;
- mean paired energy reduction: 0.673%;
- median paired reduction: 0.197%;
- mean strict energy: 226006.074 J -> 224416.886 J.

The scenario-averaged ESI improvement is positive in all eight scenarios when
computed over their available strict repetitions, although scenarios 49 and 52
have incomplete strict coverage and must be interpreted conditionally.

RGA-MR has only 3/24 strict runs, and only two of those are simultaneously
strict with ESI-ALNS. Therefore its K=80 conditional energy difference is not
used as a broad energy-quality claim; K=80 primarily demonstrates feasibility
robustness. The clean RGA-MR energy comparison remains K=50.

The expanded result changes the earlier 3-scenario statement: K=80 is no longer
reported as 9/9 universally strict. The correct main-comparison result is
**21/24 strict over 8 independent scenarios x 3 repetitions**.


---

## 6. Elite-family ablation

Setting: (K=80,E=2). Each ablation shares exactly the same B-ALNS
exploration and branches only at the elite-refinement stage.

| Ablation | Full better | Equal | Ablated better | Mean Full advantage |
|---|---:|---:|---:|---:|
| w/o Route-compute relocation | 6 | 3 | 0 | 0.709% |
| w/o Contact family | 3 | 5 | 1 | 0.302% |
| w/o explicit Batch family | 2 | 6 | 1 | 0.009% |
| w/o Progressive widening | 0 | 9 | 0 | 0.000% |

Interpretation:

- route-compute relocation is the dominant elite mechanism;
- contact operations provide a smaller positive auxiliary contribution;
- explicit batch moves are useful in selected states but marginal in aggregate
  at K=80/E=2;
- progressive widening is a fallback mechanism rather than a typical source of
  solution improvement.

Do not claim that every module contributes equally.

---

## 7. Main system-level conclusion

Across the workload, MEC-count, and UAV-count sweeps, active-MEC bandwidth is
consistently near full utilization, while MEC CPU utilization retains more
headroom and changes materially with E and M.

The recurring systems interpretation is therefore

[
oxed{
	ext{intermittent contact / bandwidth opportunity}
	ext{ is the persistent bottleneck}
}
]

rather than pure MEC CPU capacity.

This supports the central optimization argument:

[
oxed{
	ext{Route}
leftrightarrow
	ext{Contact}
leftrightarrow
	ext{Offloading}
leftrightarrow
	ext{Batch/Resource}
}
]

must be treated as a coupled decision process.

---

## 8. Recommended paper figures

1. **Workload figure:** K vs mean UAV energy and strict-feasibility rate.
2. **Workload structure figure:** K vs offload ratio, contacts/UAV, and route
   distance.
3. **Resource figure:** K vs active-MEC bandwidth and CPU utilization.
4. **MEC-count figure:** E vs strict-feasibility rate and offload ratio.
5. **UAV-count figure:** M vs strict-feasibility rate, mean delay, and
   contacts/UAV.
6. **Baseline figure:** K=50 mean energy of FTR-NM, Route-GA, B-ALNS, and
   ESI-ALNS; Greedy may be shown separately because it is not 3/3 strict.
7. **Ablation figure/table:** paired Full-vs-ablated advantage for Route,
   Contact, Batch, and Widening families.

Error bars should use run-level standard deviation only where the underlying
sample is comparable and fully strict. For strict-subset settings such as
K=100/E=2, show the strict sample count explicitly instead of visually implying
a complete 9-run sample.

---

## 9. Reduced-scale best-known strong-reference benchmark

The final paper-strengthening experiment is a **best-known strong reference**,
not a global-optimality certificate.

### 9.1 Protocol

Scale scouting with the original baseline parameters showed that very small
instances are not structurally representative: K=8/M=2 and K=16/M=2 converge
to all-local references, while K=12/M=1 is too tight to recover a strict
solution. K=28/M=2/E=2 is the smallest tested setting whose strong pilot is both
strict-feasible and nondegenerate.

The formal benchmark fixes:

- K=28, M=2, E=2;
- scenario seeds 45/46/47;
- standard ESI-ALNS: seeds 100/101/102, 100 iterations, 2 elite rounds;
- strong reference: seeds 700-711, 1000 iterations, 6 elite rounds;
- expanded elite exact shortlist/task/route-position budgets;
- strict Stage-1 CVX verification for every reported energy.

For each scenario, the best-known energy is the minimum strict Stage-1 energy
over the union of the 3 standard runs and 12 strong runs.

### 9.2 Results

| Scenario | Best-known energy (J) | Contacts | Offloaded tasks | Strong hits | Mean standard gap | Median standard gap |
|---:|---:|---:|---:|---:|---:|---:|
| 45 | 97905.087437 | 1 | 2 | 4/12 | 9.695% | 8.610% |
| 46 | 99503.124192 | 2 | 2 | 5/12 | 0.071% | 0.071% |
| 47 | 103608.196273 | 1 | 1 | 1/12 | 8.137% | 9.203% |

Aggregate:

- standard strict: 9/9;
- strong strict: 36/36;
- mean standard-to-best-known gap: 5.968%;
- median gap: 8.610%;
- maximum gap: 11.866%;
- standard runs within 0.01% / 0.1% / 1% of best-known:
  0/9, 3/9, and 3/9;
- formal strong reference hits: 10/36 (27.8%);
- mean runtime: 3.990 s for standard versus 31.380 s for strong.

All three best-known solutions are structurally nondegenerate and retain actual
MEC contact/offloading decisions.

Because S47 had only one formal hit, a confirmation batch added 12 new strong
seeds (712-723), with seed 707 included as an anchor. No new seed improved the
103608.196273 J reference. Therefore the best-known value is retained, while
its low repeat frequency is explicitly interpreted as a narrow search basin.

### 9.3 Interpretation

The result supports a computational-budget interpretation rather than a
near-optimality claim. The frozen 100-iteration configuration can be very close
to the best-known reference in some scenarios (S46), but can retain several
percent gap in harder reduced-scale instances (S45/S47). More intensive search
improves solution quality at substantially higher runtime.

The discrete search remains heuristic. CVXPY is exact only for the continuous
fixed-discrete resource subproblem. Therefore these results must be described as
**empirical best-known gaps**, not global-optimality gaps.

---

## 10. Experimental status

The planned experiment set is now complete:

- workload sensitivity: complete;
- MEC-count sensitivity: complete;
- UAV-count sensitivity: complete;
- baseline comparison: complete;
- elite-family ablation: complete;
- reduced-scale best-known strong benchmark: complete.

The remaining work is presentation: final figures, compact paper tables, and
integration into the manuscript.


---

# 补充实验：Dense Workload 与 Iteration-Budget Convergence

## A. Dense Workload Curve

为增强主负载图的连续性，在原 \(K=50/80/100\) detailed table 之外，新增：

\[
K\in\{30,40,50,60,70,80\},\quad M=5,\quad E=2
\]

每个 K 使用 scenario seeds 45/46/47 与 algorithm seeds 100/101/102，共 9 runs。

| K | Generic strict | ESI-ALNS strict | Generic Mean Energy (J) | Hybrid Mean Energy (J) | Mean ESI-ALNS Gain | Offload Ratio | Contacts/UAV | Route Distance (km) | Runtime (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 9/9 | 9/9 | 122917.377 | 122914.052 | 0.003% | 5.9% | 0.267 | 6.465 | 3.611 |
| 40 | 9/9 | 9/9 | 135783.361 | 135693.420 | 0.066% | 8.9% | 0.378 | 7.034 | 5.491 |
| 50 | 9/9 | 9/9 | 170323.586 | 167015.350 | 1.803% | 8.0% | 0.533 | 8.655 | 14.449 |
| 60 | 9/9 | 9/9 | 186149.891 | 182822.562 | 1.807% | 9.6% | 0.667 | 9.385 | 24.501 |
| 70 | 9/9 | 9/9 | 205019.285 | 202464.782 | 1.271% | 9.8% | 0.689 | 10.342 | 28.862 |
| 80 | 9/9 | 9/9 | 230038.323 | 226768.196 | 1.378% | 12.2% | 1.044 | 11.494 | 52.303 |

该结果显示：

- \(K=30/40\) 时 Hybrid 相对 B-ALNS 的额外结构收益接近 0；
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

| Spatial Profile | Stage-1 Strict | Mean Energy on Strict Subset (J) | Mean ESI-ALNS Gain | Offload Ratio | Contacts/UAV | Route Distance (km) | BW Relative Shadow |
|---|---:|---:|---:|---:|---:|---:|---:|
| uniform | **9/9** | 226768.196 | 1.378% | 12.2% | 1.044 | 11.494 | 0.005 |
| clustered | 7/9 | 146764.392 | 0.200% | 27.5% | 0.971 | 6.981 | **0.013** |
| boundary-biased | 6/9 | 226126.636 | 0.381% | 13.1% | 0.933 | 11.485 | 0.004 |

该实验的主要用途是验证 distribution shift，而不是比较三个 profile 的绝对能耗高低。特别是 clustered profile 的几何路径显著更短，因此绝对能耗天然更低。

可以支持的结论：

- ESI-ALNS 在三种空间分布下均能恢复一定比例的 strict solutions；
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

| \(C_{\max}\) | Stage-1 Strict | Stage-2 Strict | Mean Energy on Strict Subset (J) | Offload Ratio | Contacts/UAV | Route Distance (km) | BW Relative Shadow | CPU Relative Shadow | Mean ESI-ALNS Gain | Runtime (s) |
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


---

## 11. GIS-driven Real-Geography Case Study: Stanislaus National Forest

A GIS-driven external-geography validation is constructed around the Groveland
Ranger District of Stanislaus National Forest, California.

The case uses USDA Forest Service historical FireOccurrence point records as
prospective fixed monitoring-node locations. The Groveland Ranger District
Office is the UAV depot and one modeled infrastructure/edge anchor; Smith Peak
Lookout is the second real facility anchor. Latitude/longitude records are
projected to local metric coordinates before entering the unchanged UAV-MEC
optimizer.

The model interpretation is intentionally limited: the real facility
coordinates are geographic anchors for modeled MEC deployment and do not imply
that the assumed MEC hardware is physically deployed there. Historical
fire-occurrence coordinates are prospective monitoring-node locations, not
claims of existing sensor installations.

For reproducibility, the formal experiment uses the pinned snapshot
\`data/real_case/stanislaus/usfs_fire_occurrences_selected59_2026-09-22.json\`,
containing 59 unique historical USFS fire-occurrence coordinates from 1992--2024.

### Formal setting

- \(K=59\), \(M=5\), \(E=2\);
- scenario seeds 45/46/47;
- algorithm seeds 100/101/102;
- 100 Hybrid iterations, 2 elite rounds;
- patrol cycle 2400 s;
- average-delay budget 1000 s;
- per-UAV energy budget 500 kJ;
- projected task/facility extent about 7.78 km x 5.02 km.

Absolute energy is not compared directly with the synthetic 1-km-scale cases.

### Formal results

| Method | Strict feasibility | Mean energy over strict solutions |
|---|---:|---:|
| GR-MR | 0/3 unique scenarios | - |
| FTR-NM | 0/3 unique scenarios | - |
| B-ALNS | **8/9** | 883683.621 J |
| ESI-ALNS | **8/9** | **878690.613 J** |

For Hybrid versus Generic on the eight common-strict pairs:

- Hybrid better: 2;
- equal: 6;
- Generic better: 0;
- mean paired Hybrid advantage: **0.543%**;
- median paired advantage: 0%.

ESI-ALNS strict-run summaries:

- Stage-2 strict: 8/8;
- mean route distance: 48.154 km;
- mean delay: 646.164 s;
- mean deadline slack: 446.796 s;
- mean offload ratio: 0.212%;
- mean contacts/UAV: 0.025.

Only one strict run retains an actual MEC contact/offloaded task; most strict
solutions are all-local. The experiment therefore provides external geography
robustness evidence, not evidence of frequent MEC use.

Supported conclusion: the search framework remains effective on a real
historical-fire spatial distribution whose geometry differs strongly from the
synthetic square map. Controlled contact-budget and bandwidth experiments remain
the primary evidence for the Route--Contact--Offloading mechanism itself.

This is a GIS-driven real-geography case study, not a field UAV flight
experiment.
