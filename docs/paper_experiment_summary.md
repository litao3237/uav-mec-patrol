# Paper Experiment Summary

This file consolidates the paper-facing experimental evidence for the frozen
Proposed Hybrid ALNS. Unless noted otherwise, paper-scale runs use scenario
seeds 45/46/47, algorithm seeds 100/101/102, and a frozen ALNS budget of 100
iterations.

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
	ext{Generic ALNS Exploration}
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

| K | Stage-1 strict | Stage-2 strict | Mean Hybrid energy (J) | Mean delay (s) | Mean deadline slack (s) | Offload ratio | Contacts/UAV | Route distance (km) | Active-MEC BW util. | Active-MEC CPU util. | Fixed-energy share |
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

| E | Stage-1 strict | Stage-2 strict | Mean Hybrid energy (J) | Mean delay (s) | Mean deadline slack (s) | Offload ratio | Contacts/UAV | Route distance (km) | Active-MEC BW util. | Active-MEC CPU util. | Fixed-energy share |
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

| M | Stage-1 strict | Stage-2 strict | Mean Hybrid energy (J) | Mean delay (s) | Mean deadline slack (s) | Offload ratio | Contacts/UAV | Route distance (km) | Active-MEC BW util. | Active-MEC CPU util. | Fixed-energy share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 0/9 | 0/9 | - | - | - | - | - | - | - | - | - |
| 5 | 9/9 | 8/9 | 226768.196 | 217.543 | 123.068 | 0.125 | 1.050 | 11.498 | 1.000 | 0.489 | 0.983 |
| 8 | 9/9 | 8/9 | 224480.040 | 211.067 | 129.545 | 0.125 | 0.641 | 11.363 | 1.000 | 0.639 | 0.985 |

Interpretation:

- M=3 does not recover a strict-feasible terminal structure under the frozen
  100-iteration budget; this is not a proof of global mathematical infeasibility;
- M=5 and M=8 are both 9/9 strict Stage-1;
- moving from M=5 to M=8 reduces mean Hybrid energy by about 1.01%, reduces
  delay, increases deadline slack, and lowers contacts per UAV;
- the offload fraction stays nearly constant, so the main effect of additional
  UAVs is reduced route/service pressure and redistribution of contact work.

---

## 5. Baseline comparison

### 5.1 Moderate-load energy-quality comparison

Setting: (K=50,E=2).

| Method | Strict feasibility | Mean energy (J) | Median energy (J) |
|---|---:|---:|---:|
| Greedy + MEC repair | 2/3 unique scenarios | 230637.625 | 230637.625 |
| Fixed-Route Nearest-MEC (FR-NM) | 3/3 unique scenarios | 229613.102 | 229866.963 |
| Route-GA + deterministic MEC repair | 9/9 | 235438.000 | 227768.558 |
| Generic ALNS | 9/9 | 170323.586 | 172689.240 |
| Proposed Hybrid | 9/9 | **167015.350** | **170279.207** |

Paired comparisons:

- Hybrid vs FR-NM: 9/9 Hybrid better; mean paired advantage 27.297%; median
  26.629%.
- Hybrid vs Route-GA: 9/9 Hybrid better; mean paired advantage 28.884%; median
  28.771%.
- Hybrid vs Generic ALNS: 5/9 better, 4/9 equal, 0/9 worse; mean 1.803%;
  median 0.047%.

The deterministic Greedy/FR-NM methods are counted by unique scenarios rather
than repeated algorithm seeds.

### 5.2 High-load feasibility robustness

Setting: (K=80,E=2).

| Method | Strict feasibility |
|---|---:|
| Greedy + MEC repair | 0/3 unique scenarios |
| FR-NM | 0/3 unique scenarios |
| Route-GA + MEC repair | 0/3 in high-budget pilot |
| Generic ALNS | 9/9 |
| Proposed Hybrid | 9/9 |

For the Route-GA high-budget pilot, about 903-904 distinct route structures were
evaluated per scenario and the best proxy states still retained 6/4/4
constraint violations. This supports the conclusion that the high-load result
is not merely caused by an intentionally undersized GA budget.

For Hybrid vs Generic ALNS at K=80/E=2:

- 8/9 improved;
- 1/9 unchanged;
- 0/9 worse;
- mean paired gain 1.378%;
- median paired gain 1.154%.

This is the cleanest setting for demonstrating the incremental value of the
problem-specific elite structural intensification.

---

## 6. Elite-family ablation

Setting: (K=80,E=2). Each ablation shares exactly the same Generic ALNS
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
6. **Baseline figure:** K=50 mean energy of FR-NM, Route-GA, Generic ALNS, and
   Proposed Hybrid; Greedy may be shown separately because it is not 3/3 strict.
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
- standard Proposed Hybrid: seeds 100/101/102, 100 iterations, 2 elite rounds;
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
