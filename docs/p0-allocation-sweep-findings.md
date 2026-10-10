# P0 gate 4: end-to-end exploration/ESI time allocation

**Branch:** `experiment/p0-time-allocation-sweep` (not merged)  
**Frozen tested commit:** `dfa837489e093c9f26c7c50577cec0e1ac1fcf2e`  
**GitHub Actions:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38041435467  
**Run result:** all 9 jobs succeeded (one smoke, eight scale/scenario blocks), 41 relevant tests passed.

## Motivation and protocol

Gate 3 showed the upgraded cross-UAV 2-opt* ESI helped relative to the
original ESI, but **continuing B-ALNS exploration often performed better
at the same nominal end-to-end time cap**. Instead of adding operators,
we froze the successful cross-UAV 2-opt* repair and tested the allocation
between B-ALNS exploration and ESI.

- Workloads: K50 and K80; **four new** independent scenario seeds
  S57/S58/S59/S60, nested algorithm seeds A109/A110.
- Same nominal **15s/45s** end-to-end limit for all methods, including
  shared initialization, algorithm, full Stage-1/Stage-2 resource solves,
  and independent residual audit. CVX is not interruptible, so
  overruns are fully reported rather than ignored.
- All methods reserve 20% of nominal time for final validation.
- Five budget allocations (percent of total nominal budget):
  B-ALNS exploration 80/ESI 0; original ESI 60/20; cross-UAV 2-opt*
  ESI 60/20, 65/15, 70/10, and 75/05.
- Original and 2-opt* ESI 60/20 **share exactly the same B-ALNS checkpoint**.
  Other allocations use independent B-ALNS exploration from the exact
  same initial solution and algorithm seed; the length of exploration
  intentionally differs.
- No appended postprocessing; ESI candidates remain subject to
  the original Stage-1 strict CVX/residual acceptance and at most two
  elite rounds with a six-slot shortlist.
- Signed energy savings mean **lower** Stage-1 UAV energy than the
  method being compared. Seeds are averaged within their scenario and
  scenarios are equally weighted.

## Reconstructed raw-record results

All **96 planned method records** were saved; all eight experimental
scenario jobs completed. The output below was independently recomputed
from their eight Actions ZIP archives (not merely copied from printed
summaries). `qualified` means *both* Stage-1 and Stage-2 pass the
independent residual audit. `qualified within` additionally requires
actual runtime <= nominal budget.

| K | Method (explore/ESI fraction) | Qualified | Qualified within | Mean full time (s) | Mean paired saving vs B-ALNS (J) | CVX elite candidates/run |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 50 | B-ALNS 80/0 | 7/8 | 6/8 | 14.38 | 0 | 0 |
| 50 | Original ESI 60/20 | 7/8 | 6/8 | 14.09 | **-2507** | 4.63 |
| 50 | 2-opt* 60/20 | 7/8 | 6/8 | 14.28 | -381 | 2.88 |
| 50 | 2-opt* 65/15 | 7/8 | 6/8 | 14.35 | **+554** | 1.75 |
| 50 | 2-opt* 70/10 | 7/8 | 6/8 | 14.71 | -173 | 0.63 |
| 50 | 2-opt* 75/05 | 7/8 | 4/8 | 15.29 | -43 | **0.00** |
| 80 | B-ALNS 80/0 | **4/8** | 4/8 | 42.20 | 0 | 0 |
| 80 | Original ESI 60/20 | 6/8 | 6/8 | 37.13 | +1077 | 5.25 |
| 80 | 2-opt* 60/20 | 6/8 | 6/8 | 38.90 | +2341 | 4.38 |
| 80 | 2-opt* 65/15 | 6/8 | 6/8 | 38.76 | +3339 | 3.88 |
| 80 | 2-opt* 70/10 | 6/8 | 6/8 | 38.96 | **+4220** | 1.63 |
| 80 | 2-opt* 75/05 | 5/8 | 5/8 | 43.66 | -279 | **0.00** |

**CRITICAL:** Each signed saving vs B is computed on that method's
*common strictly qualified paired subset*, not across incomparable
method-wide means. K50 uses **7 paired seeds across 4 scenarios**.
K80 uses only **4 paired seeds across 3 scenarios**, because B-ALNS
failed strict validation in four attempts. The 80-task energy means
cannot be advertised as broad generalization across all four scenes.

### End-to-end within-budget pairs

Requiring *both* methods to pass full validation **and** finish inside
the nominal budget:

- K50 original ESI vs B: **-2804 J**, 6 paired starts, 4 scenes.
- K50 2-opt* 60/20 vs B: **+176 J**, 6 starts, 4 scenes.
- K50 2-opt* 65/15 vs B: **+1603 J**, 6 starts, 4 scenes,
  **but only 1 win / 3 losses / 2 ties**, so this positive mean
  is dominated by limited large improvements.
- K50 2-opt* 70/10 vs B: **-303 J**, 6 starts, 4 scenes.
- K50 75/05: only 4 within-budget paired starts across 3 scenes.
- K80 2-opt* 70/10 vs B: **+4220 J** on only **4 paired
  starts across 3 scenes**, with 4 wins / 0 losses on that
  conditioning set. This is promising but far too small for a
  definitive superiority claim.

### Crucial failure / timeout details

K50/S58/A109: **every method** returned `optimal_inaccurate` at the
final strict Stage-1 verification and exceeded the time cap. We retain
the failed sample and do not treat the energy as feasible.

K80/S59: **every method on both seeds** failed strict Stage-1
qualification. Failures were either `optimal_inaccurate` or an
optimistic feasibility-precheck rejection of the fixed structure
(`infeasible_precheck`). Neither observation proves the
*whole problem instance* is mathematically infeasible.

K80 B-ALNS additionally failed qualification for S58/A109 and
S60/A109. That explains the 4/8 B success coverage and shrinks
paired energy comparisons.

The 75/05 strategy almost never had time to validate a single
elite candidate after its Stage-1 anchor; mean evaluated candidates
was zero on both scales. It also had frequent nominal overruns
(K50 4/8, K80 3/8). **Reject 75/05 as an ESI allocation.**

## Small-sample bootstrap diagnostics only

For the three K80 independent scenarios with any common B-valid
comparison, the 70/10 mean +4220 J had a descriptive scenario
bootstrap 95% interval of approximately **[+2182,+6332] J**.
This positive interval is **not a statistically strong general
superiority claim**, because there are only 3 independently
qualified scenarios, 4 nested paired seeds, and heavy
quality/feasibility selection.

For K50, the 65/15 allocation's energy-only mean +554 J against B
had a scenario bootstrap 95% interval **[-1335,+3096] J**.
This does not establish an energy advantage.

## Scientific decision

1. Retain ESI 2-opt* as a promising quality component, but do not
   merge into `develop` or rewrite the paper's numerical conclusions.
2. Moving time from ESI to B exploration can help in some workloads
   (K80 70/10 here), but a single global fixed fraction is not
   established. The primary performance bottleneck is now **search
   effort allocation and high-load strict-qualification coverage**,
   not merely route neighborhood breadth.
3. A genuinely differentiated next method should detect exploration
   stagnation and remaining strict-CVX budget, and invoke/stop
   contact-aware elite refinement **based on measured marginal gain
   per unit time**, rather than hard-coding any one split.
4. Improve/diagnose high-load Stage-1 numerical conditioning and
   repeat strict audits equally for *all methods*, without selectively
   relaxing tolerances. Report feasibility and timing coverage alongside
   energy (especially K80).
5. Confirm any adaptive policy on more newly generated independent
   scenarios and matched end-to-end budgets, and ideally provide
   anytime best-qualified objective vs wall-clock trajectories.

**The existing paper baseline and source `develop` remain unchanged.**
