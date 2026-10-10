# P0 verification gate 2: matched nominal end-to-end search budgets

**Source branch:** `experiment/p0-matched-budget`  
**Actions:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38039654240  
**Code tested:** `6665f7156dd0f8402f6612faa16a0d9701c99c41`  
**Status:** successful; Windows smoke and both K50/K80 jobs passed; 45 focused tests passed. `develop` was not modified.

## Protocol

- K50: nominal **15-second** end-to-end budget; K80: **45-second**.
- Independent scenarios S50/S51, algorithm seeds A105/A106 (new P0 seeds).
  Four paired attempts nested in **two** independent scenarios per scale.
- The B-ALNS arm allocates up to 80% of the budget to exploration.
- Each ESI arm allocates up to 60% to the *same shared* B-ALNS
  exploration checkpoint plus 20% to strictly validated baseline anchor
  and at most two ESI rounds. The remaining nominal 20% is reserved
  for full Stage-1 recomputation, Stage-2 resource allocation, and independent
  residual audit. Initialization is subtracted before allocating search.
- ESI arms use the **same six-slot maximum shortlist per round**, with
  identical resource feasibility and energy acceptance conditions.
- Comparison arms: B-ALNS, original ESI, preserve-contact-deletion + Swap,
  preserve-contact-deletion + 2-opt*, and preserve-contact-deletion + combined.
- An ESI variant **replaces** weaker contact-position/point-choice moves
  *inside* the original ESI (not after ESI), while retaining contact deletion.
- Timers for shared initialization and exploration are individually measured
  and added to each fork's recorded virtual end-to-end runtime. The time
  cap is soft (individual candidate/solver calls are not preempted).
  No run exceeded its nominal time budget in this batch.

## Summary: positive gains indicate lower UAV energy than reference

All **40/40 recorded full comparison attempts** passed both Stage-1 and
Stage-2 independent validation, and **40/40 finished within nominal budget**.
Paired differences aggregate seeds within scenario and then weigh the two
scenarios equally. These are descriptive small-sample means, *not*
statistically significant improvements.

| K | Method | Mean end-to-end time (s) | Gain vs original ESI (J) | Gain vs B-ALNS (J) | Wins/losses/ties vs original |
| --- | --- | ---: | ---: | ---: | --- |
| 50 | B-ALNS | 13.45 | +1046.23 | 0.00 | 3 / 1 / 0 |
| 50 | Original ESI | 13.26 | 0.00 | -1046.23 | — |
| 50 | Preserve delete + Swap | 13.49 | 0.00 | -1046.23 | 0 / 0 / 4 |
| 50 | Preserve delete + 2-opt* | **13.29** | **+1499.58** | **+2545.81** | **3 / 0 / 1** |
| 50 | Preserve delete + Combined | 13.39 | **-4120.77** | -3074.53 | 0 / 2 / 2 |
| 80 | B-ALNS | 38.85 | +157.21 | 0.00 | 3 / 1 / 0 |
| 80 | Original ESI | 39.98 | 0.00 | -157.21 | — |
| 80 | Preserve delete + Swap | 40.45 | -991.74 | -1148.94 | 1 / 1 / 2 |
| 80 | Preserve delete + 2-opt* | 41.54 | -247.90 | -405.11 | 0 / 1 / 3 |
| 80 | Preserve delete + Combined | 41.97 | -69.62 | -226.83 | 1 / 1 / 2 |

All gains are signed mean Stage-1 UAV-energy differences. Energy comparisons
on invalid runs are excluded; there were no invalid runs in this budget
batch. The 95% confidence interval is **not** estimated from only two
independent scenarios.

## Mechanism-specific observations

At **K50**, selectively replacing contact-position/point moves with the
2-opt* route-tail neighborhood produced three better results and one tie,
with approximately the *same measured end-to-end runtime* as original ESI.
This is more credible than the earlier postprocessing gains because the
new method starts from the same exploration endpoint and runs inside the
same ESI time slice. In S50/A105 it saved 2032.36 J relative to original
ESI and 937.1 J relative to B-ALNS; in S50/A106 it saved 2589.9 J
relative to original and 1117.9 J relative to B.

However, at **K80** the same 2-opt* version had zero wins, one loss,
three ties relative to original ESI (mean **247.90 J worse**). A blanket
replacement is thus unsupported. Furthermore, at K50/S51/A106,
the combined replacement lost the original ESI's accepted
`route_compute_relocate::S34->U4@12` and was **15.715 kJ worse**
than original ESI, despite identical shortlisting limit/time target.
This directly indicates destructive **candidate-family competition**.

B-ALNS can still beat all ESI variants in a given block. In K50/S51/A105,
the longer B search saved 8.963 kJ over the original ESI and 7.587 kJ
over selective 2-opt*. Thus ESI does **not** yet show stable superiority
over spending the same total time on B-ALNS.

## Joint interpretation with gate-1 diagnosis

Gate 1 (Actions https://github.com/litao3237/uav-mec-patrol/actions/runs/38038975506):
- On S47/S49 and fresh seeds, 10 position/point candidates were evaluated
  in the original ESI's contact family over the seven strictly validated
  paired starts, and **none** were accepted; route relocation/batch merge
  dominated accepted improvements.
- Keeping contact deletion is still appropriate because an earlier K80/S46
  run depended on it; two-scenario ablations cannot prove an operator useless.
- The simple optimistic energy bound excluded only **3/48** sampled
  candidate checks; two already failed the existing necessary
  feasibility precheck. Its incremental solver savings are presently
  weak. The bound is mathematically safe under the current model, but
  not yet a useful main algorithm contribution.

## Decision

**Do not merge experimental changes into `develop`.** The latest
evidence supports a narrower engineering and research hypothesis:

> Selective cross-UAV 2-opt* can improve K50 performance under the
> tested nominal budget, but unconditional multi-operator replacement
> is too costly and can evict strong original route improvements.

Next develop **budget-aware and structural-context-aware candidate
selection within the existing ESI** (protect at least one original route
relocation and preserve contact deletion, choose *which* cross-UAV family
gets remaining solver slots). Measure candidate-selection regret and
additional CPU time, without growing ESI's time allocation. Evaluate
on more independent workloads before calling this a general algorithmic
breakthrough.

The existing snapshot archives, figures and formal paper conclusions remain
unchanged.
