# Final Algorithm Freeze

> Status: frozen after the v7 paired-checkpoint unseen validation.
>
> Paper-facing branch target: `develop`.
>
> Experimental provenance branch: `experiment/paired-checkpoint-fork-v7`.

## 1. Final paper-facing algorithm

The final proposed method remains the original ESI-ALNS design already present
on `develop`:

[
oxed{
	ext{Greedy Route Seed}
ightarrow
	ext{MEC Contact/Offloading Repair}
ightarrow
	ext{Generic ALNS Exploration}
ightarrow
	ext{Elite Structural Intensification}
ightarrow
	ext{Strict Stage-1 CVX Acceptance}
}
]

Paper display name:

- English: **ESI-ALNS — Adaptive Large Neighborhood Search with Elite Structural Intensification**
- Chinese: **精英结构强化自适应大邻域搜索算法**

The internal exploration baseline remains:

- **B-ALNS — Base ALNS**

The final algorithm is **not** v5, v6, or v7. Those branches are retained as
budget-fairness and mechanism-validation evidence.

## 2. Frozen implementation mapping

The paper-facing implementation is the `develop` version of:

- `src/uav_mec/algorithms/alns/runner.py`
  - Generic ALNS backbone.
  - `enable_problem_operators=False` in the proposed method.
  - Screened outer objective.
  - Roulette-wheel operator adaptation and RRT acceptance.
- `src/uav_mec/algorithms/alns/hybrid.py`
  - `run_uav_mec_hybrid_alns(...)`.
  - Generic ALNS exploration first.
  - Strict Stage-1 verification of the exploration incumbent.
  - Problem-specific elite refinement second.
- `src/uav_mec/algorithms/alns/problem_operators.py`
  - `contact_mode_intensification(...)`.
  - Route-compute relocation.
  - Contact relocation / replacement / removal.
  - Batch merge / split / new-contact structure.
  - Mode / batch reassignment.
  - Candidate acceptance is monotone under strict Stage-1 CVX.
- `src/uav_mec/algorithms/alns/evaluator.py`
  - `ScreenedProxyObjectiveEvaluator` for efficient exploration.
- `CVXResourceSolver(run_stage2=False)`
  - Paper-scale Stage-1 correctness oracle.

The continuous resource layer may still be analyzed using KKT structure, but
CVXPY remains the paper-facing correctness oracle.

## 3. Frozen main-experiment parameters

The primary fixed-exploration paper experiment retains the configuration already
used for the 8-scenario main baseline comparison:

- ALNS iterations: **100**
- Algorithm seeds: **100, 101, 102**
- Independent scenario seeds: **45--52**
- Elite rounds: **2**
- Generic ALNS problem-specific peer operators: **disabled**
- Elite acceptance: **strict Stage-1 `optimal` only**

The key methodological comparison is:

> Given the same completed B-ALNS exploration trajectory, does the ESI
> post-refinement improve the returned solution?

For this question, ESI is monotone by construction.

## 4. What remains part of the paper algorithm

### 4.1 Keep: Generic ALNS exploration

Generic ALNS remains the main global exploration mechanism. It is responsible
for most feasibility recovery and large-scale structural search.

Problem-specific operators should **not** be reintroduced as equal-status
roulette-wheel exploration operators. Existing ablations already showed that
they can consume exploration budget without improving the generic backbone.

### 4.2 Keep: Legacy Elite Structural Intensification

The original elite phase is retained.

Its role is narrow and explicit:

1. start from the completed Generic ALNS elite solution;
2. enumerate a restricted set of problem-specific structural candidates;
3. use cheap screening to reduce the exact candidate set;
4. evaluate selected candidates with strict Stage-1 CVX;
5. accept only strict energy-improving candidates.

This is a post-refinement / polishing mechanism, not a replacement for Generic
ALNS.

### 4.3 Keep: Strict Stage-1 monotone acceptance

This is the most important correctness property of ESI.

When the exploration incumbent is strict `optimal`, the elite phase does not
accept an exact-energy-worse candidate. Therefore:

[
E_{	ext{ESI final}} le E_{	ext{exploration incumbent}}
]

for accepted strict elite moves.

If the exploration incumbent is not strict, the elite phase is skipped rather
than comparing against an inaccurate reference.

## 5. Experimental versions that are NOT the final algorithm

| Version | Main idea | Final status | Paper-algorithm action |
|---|---|---|---|
| v1 | ALNS -> ESI -> restarted ALNS | breaks learned selector/RNG trajectory | discard |
| v2 | Continuous ESI | improved strict stability but conservative terminal behavior | discard |
| v3 | Terminal Recovery | expensive recovery, poor K=80 recovery success | discard |
| v4 | Terminal-First | cleaner engineering, no meaningful same-time gain | discard |
| v5 | Budget-Aware Reserve | improves budget utilization | keep as engineering evidence only |
| v6 | Energy-Guided ESI | better development-set CVX efficiency, failed unseen promotion | discard from formal algorithm |
| v7 | Paired Checkpoint Fork | fair marginal-value validation framework | keep as validation infrastructure only |

None of v1--v7 should change the formal ESI-ALNS definition in the paper.

## 6. What may be retained as engineering / validation infrastructure

These components are useful and may remain on experimental branches or be
selectively merged later, but they are **not** components of ESI-ALNS itself.

### v5 dynamic reserve

Supported engineering conclusion:

- fixed 10% reserve wastes search time;
- dynamic reserve improves budget utilization.

However, v5 did not establish superior same-time solution quality over
Time-B-ALNS. Therefore the reserve controller should not be introduced as a
paper contribution of the final algorithm.

### v7 resumable session/checkpoint

Useful for reproducibility and fairness experiments:

- current state preservation;
- historical best preservation;
- Roulette Wheel state preservation;
- RNG state preservation;
- logical RRT progress preservation;
- deterministic paired continuation.

This is an **experimental control mechanism**, not an optimization operator.

### v7 time-scaled RRT and incumbent retention

These are valid fairness-experiment controls:

- waiting between fork arms must not cool the RRT schedule;
- a branch must not discard an already known exact strict checkpoint incumbent.

They belong to the paired-checkpoint experiment protocol, not the final
paper-facing ESI-ALNS algorithm.

## 7. Evidence supporting the final ESI role

### 7.1 Fixed exploration: supported incremental value

Main 8-scenario x 3-repetition comparison:

#### K=50

- common strict: 24/24;
- ESI better/equal/worse vs B-ALNS: **14 / 10 / 0**;
- mean paired improvement: **1.549%**;
- scenario-averaged improvement positive in 7/8 scenarios and zero in 1/8.

#### K=80

- common strict: 21 pairs;
- ESI better/equal/worse: **17 / 4 / 0**;
- mean paired improvement: **0.673%**;
- available strict repetitions give positive scenario-level improvement in all
  eight scenarios.

This supports the statement:

> ESI provides a monotone problem-specific refinement of a fixed Generic ALNS
> exploration result.

### 7.2 Matched runtime: no supported superiority claim

Primary matched-runtime experiment:

- K=50 / 15 s: ESI vs B-ALNS scenario-level mean advantage **-0.385%**;
- K=80 / 45 s: scenario-level mean advantage **+0.387%**;
- uncertainty intervals cross zero in both cases.

The v7 paired-checkpoint experiment strengthened this conclusion.

### 7.3 v7 unseen validation

Frozen unseen block: **S101--108**, algorithm seeds 100/101/102.

#### K=50

- strict checkpoints: 24/24;
- continued B-ALNS mean marginal improvement: **634.4 J**;
- Energy-Guided ESI mean marginal improvement: **994.6 J**;
- independent scenarios: **3 better / 2 equal / 3 worse**.

No stable ESI marginal-efficiency advantage is established.

#### K=80

- strict checkpoints: 21/24;
- continued B-ALNS mean marginal improvement: **3547.7 J**;
- Energy-Guided ESI mean marginal improvement: **2748.6 J**;
- Energy-Guided ESI vs continued B-ALNS: **3 better / 0 equal / 5 worse**;
- scenario-level mean marginal-energy difference: **-1475.7 J**;
- scenario-level mean J/s difference: **-103.0 J/s**.

The positive K=80 development signal did not reproduce on unseen scenarios.

Therefore:

[
oxed{
	ext{Same-time ESI superiority over continued B-ALNS is not supported.}
}
]

## 8. Final paper claims

### Supported

The paper may state that:

1. B-ALNS provides the main global exploration and feasibility-recovery power.
2. ESI exploits UAV-MEC-specific Route--Contact--Offloading--Batch structure
   after Generic ALNS exploration.
3. Strict Stage-1 CVX acceptance makes ESI a monotone exact post-refinement
   mechanism on strict exploration incumbents.
4. Under the same completed exploration trajectory, ESI produces measurable
   additional energy reductions.
5. Route-compute relocation is the dominant elite family in the existing
   ablation; contact operations have a smaller auxiliary contribution.
6. ESI-ALNS substantially outperforms the simpler constructive/evolutionary
   baselines in the supported comparisons.

### Not supported

The paper must **not** state that:

1. ESI is always better than giving the same extra wall-clock time to B-ALNS.
2. ESI has uniformly higher J/s or J/CVX than continued B-ALNS.
3. Energy-Guided ESI v6/v7 is the final proposed algorithm.
4. Every elite family contributes equally.
5. Non-strict solver outcomes prove mathematical infeasibility.
6. The empirical strong-reference solution is a global optimum.

## 9. Final code-integration policy

### Merge to / keep on `develop`

Keep the existing paper-facing implementation unchanged unless a bug fix is
required:

- Generic ALNS runner;
- legacy `run_uav_mec_hybrid_alns`;
- legacy `contact_mode_intensification`;
- screened evaluator;
- strict Stage-1 correctness oracle;
- existing paper experiment scripts and results.

Documentation from v5--v7 should be merged so that the final claim boundary is
visible from `develop`.

### Do not merge as paper algorithm

Do not replace the `develop` algorithm with:

- `AdaptiveESI`;
- `ContinuousESI`;
- `TerminalRecoveryESI`;
- `TerminalFirstESI`;
- `BudgetAwareTerminalFirst`;
- `EnergyGuidedESI`;
- paired-checkpoint continuation logic.

These can remain on experimental branches for provenance and reproducibility.

### Optional later cleanup

After the paper is frozen, a separate cleanup branch may:

1. retain experimental modules under a clearly named experimental namespace;
2. remove them from top-level public exports;
3. keep v7 checkpoint/session only in experiment-support code;
4. add a regression test that the frozen `develop` ESI configuration remains
   unchanged.

This cleanup is optional and should not alter paper results.

## 10. Single source of truth going forward

For all subsequent paper work:

- algorithm definition: **this file**;
- naming: `docs/algorithm_naming.md`;
- main evidence: `docs/paper_experiment_summary.md`;
- matched-runtime evidence: `docs/matched_runtime_results.md`;
- compute-budget protocol: `docs/compute_budget_protocol.md`;
- v5--v7 branches: provenance / validation only.

Do not start a v8 algorithm branch unless a genuinely new research question is
introduced. The current optimization-method development phase is frozen.
