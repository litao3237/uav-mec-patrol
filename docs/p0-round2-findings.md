# P0 round-2: cross-UAV structural neighborhoods — Actions pilot results

**Source experiment branch:** `experiment/p0-cross-uav-elite`  
**Workflow SHA tested:** `7946417976002bff75e89b6895c469d342cf2d0a`  
**Actions run:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38036328949  
**Result:** completed successfully; smoke tests and the K50/K80 matrix both succeeded.

## What changed

This round **does not replace the frozen original ESI shortlist**, unlike the
negative P0 first-round variants. Each (K, scenario, seed) is explored
with B-ALNS once (100 iterations) and processed by the original
CVX-validated ESI once (up to two rounds). Each new neighborhood then starts
from the **same original ESI endpoint**:

- `swap`: exchange tasks on two distinct UAVs;
- `two_opt_star`: exchange suffixes of task sequences across two UAVs;
- `block_relocate`: transfer a contiguous **two-task** block to another UAV;
- `combined`: give each of these families an initial shortlist quota, then
  fill the remaining slots by the common proxy rank.

After altering task sequences, rebuild contact positions so surviving batches
remain after their tasks, make cross-UAV transferred tasks local, remove empty
contacts, and run the original MEC repair. All accepted candidates must pass
fixed-structure Stage-1 CVXPY plus independent saved/reconstructed residuals
and a meaningful energy-improvement threshold. Stage-2 resource allocation
is separately run and audited for every recorded final result.

**Limits:** geometry pre-ranks at most 12 candidate reconstructions per family,
then strict CVX evaluates at most six additional candidates per round for
up to two additional rounds. This is *additional* search after the original
ESI and **NOT a fair end-to-end equal-time comparison**.

## Experimental scope / verification

- K = 50, 80; scenarios S45, S46; algorithm seeds A100, A101.
- Each scale: 4 paired starts nested in 2 independent scenarios.
- Five profiles per start; **40/40 main records passed Stage-1 and Stage-2**.
- Independent K30 smoke (one start, five profiles) also passed Stage-2.
- Windows frozen numerical environment; 34 focused tests passed.
- Output ZIP artifacts and raw JSON are stored under the Actions run.
- Zero regression versus the shared original-ESI endpoint is guaranteed
  **by construction**, at the cost of additional runtime.

## Stage-1 UAV energy savings, beyond the *original ESI* (two scenarios, seed-nested)

| K | Additional route family | Mean extra saving (J) | Mean extra saving (%) | Improved starts / 4 | Added time (s) | New strict CVX calls (mean) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 50 | swap | 28.14 | 0.015 | 1 | 3.82 | 7.5 |
| 50 | two_opt_star | **3437.00** | **1.880** | 2 | 4.14 | 9.0 |
| 50 | block_relocate | 2746.88 | 1.500 | 1 | 3.77 | 7.5 |
| 50 | combined | **3517.61** | **1.928** | 2 | 9.45 | 9.0 |
| 80 | swap | 589.60 | 0.255 | 4 | 10.61 | 11.5 |
| 80 | two_opt_star | 0.00 | 0.000 | 0 | 3.23 | 6.0 |
| 80 | block_relocate | **2035.37** | **0.879** | 3 | 8.29 | 10.5 |
| 80 | combined | **2350.07** | **1.015** | 4 | 17.89 | 12.0 |

Each percentage averages paired per-run percentages by seed within scenario,
then averages the two scenarios equally. Absolute savings are measured against
the common original-ESI endpoint, not against an algorithm granted
equal execution time.

### Total improvements over B-ALNS

The original ESI already saved 889.97 J at K50 and 1480.20 J at K80.
Combined original+new neighborhoods saved **4407.58 J (2.370%)** at K50
and **3830.28 J (1.633%)** at K80, vs the common B-ALNS checkpoints,
with extra time beyond the original ESI.

## Selected strictly validated case studies

**K50/S45/A100:**
- Original ESI: 183137.36 J, 9553 m flight route.
- Additional 2-opt-star: 169584.08 J, 8805 m flight route.
- Extra saving: **13553.28 J**, including 13475.21 J flight energy,
  from **748.62 m** reduced route distance.
- Accepted 2-opt-star moves: `U3@7<->U4@5` then `U2@5<->U3@6`.
- Stage-1 and Stage-2 both validated.

**K80/S45/A101:**
- Task-block relocation: **7046.22 J** extra savings; route distance
  reduced by **424.61 m**.
- Combined route families: **7103.24 J** extra savings;
  route distance reduced by **405.35 m**.
- Both methods passed Stage-1 and Stage-2 checks; changed MEC
  offloading/hover energy can offset part of flight savings.

### Important heterogeneity

At K50, almost all extra gains occur in S45: S46 produced no additional
improvements for any new family. The large 13.55 kJ gain in a single run
dominates the K50 mean.

At K80, 2-opt-star alone gave zero additional savings in all four pilot
starts, while swaps improved all four and two-task block moves improved
three. The K80 combined strategy improved all four starts, but paid
**17.89 s average extra runtime**.

### Candidate-screening finding

The K50/S45/A100 2-opt-star run generated ~897 geometric proposals;
only 12 of those were fully reconstructed/ranked in a round, and only
2 passed optimistic precheck in the first round. At K80, 2-opt-star
often found no strictly better feasible candidate after six CVX checks.
This suggests the contact-aware feasibility of large tail exchanges,
not raw proposal count, may be a bottleneck. It remains a hypothesis
requiring direct feasibility/rank diagnostics.

## Interpretation, limitations, and next experiment

**Promising structural improvement, not confirmed equal-budget superiority.**
This pilot establishes that new neighborhoods discover strictly feasible
low-energy structures the original ESI did not reach in the same fixed
100-iteration + 2-elite-round run. The original ESI results are protected
because additional neighborhoods start *after* it. Therefore the positive
energy differences must not be presented as independent fair-time
head-to-head evidence; baseline monotonicity is not itself an innovation.

The scenarios S45/S46 and only 2 random seeds are too small to establish
consistent out-of-sample gains. No confidence interval is warranted.

Next: (1) evaluate on independent holdout scenarios S47–S52, using
scenario-level resampling; (2) implement equal-end-to-end *nominal* runtime
comparisons among B-ALNS, original ESI-ALNS and ESI+new neighborhoods,
including initialization, strict Stage-1 checks, final Stage-2 and audit;
(3) test adaptive per-family allocation to avoid paying for unproductive
2-opt-star on high-load instances; (4) examine whether broader contact/mode
repair raises true feasibility without overstating proxy success.

**Decision:** Keep all code and evidence on the experiment branch and
**do not merge into develop yet**.
