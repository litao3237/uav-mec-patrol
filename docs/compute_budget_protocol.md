# Unified Compute-Budget and Timing Protocol

This protocol is frozen before the remaining fairness experiment is interpreted.
It applies to the paper-facing methods GR-MR, FTR-NM, RGA-MR, B-ALNS and
ESI-ALNS.

## Experimental units

- Independent scenario instances: seeds 45--52 (8 instances).
- Stochastic repetitions within each instance: algorithm seeds 100, 101, 102.
- Main settings: K=50 and K=80, M=5, E=2.
- The scenario is the independent unit. Algorithm seeds are nested repetitions.
- Deterministic GR-MR and FTR-NM are evaluated once per scenario.

## Timing boundaries

All wall-clock timing uses `time.perf_counter()` on the same GitHub Actions
runner within each seed-pair job.

The following times are recorded separately:

1. common instance / route-seed construction;
2. method search or constructive phase;
3. fresh strict Stage-1 CVX verification;
4. optional Stage-2 paper-metric extraction.

Only item 2 is the stochastic search budget. Final Stage-1 verification and
Stage-2 metric extraction are reported separately and are not charged against
the common stochastic search budget.

ESI-ALNS is the exception only in the algorithmically necessary sense: its
internal strict CVX oracle calls used to accept or reject elite structural moves
are part of the ESI search phase and therefore count against its search budget.
The separate fresh Stage-1 verification performed after search is still outside
the search budget, exactly as for RGA-MR and B-ALNS.

## Wall-clock stopping

- B-ALNS uses the ALNS package `MaxRuntime` stopping criterion.
- RGA-MR checks the wall-clock budget at generation boundaries; a generation
  already in progress is allowed to finish, and any overrun is recorded.
- ESI-ALNS splits the same total search budget into B-ALNS exploration and ESI
  exact elite refinement. Exact CVX calls are indivisible, so a candidate solve
  already in progress may finish after the nominal deadline; overrun is
  recorded rather than silently truncated.

The original fixed-iteration / fixed-generation defaults remain unchanged for
all previously completed experiments.

## Frozen budget points

The budget points are calibrated from runtime only, not from solution quality,
using the completed 8x3 fixed-configuration experiment.

Observed fixed-configuration medians:

| K | ESI-ALNS total median | B-ALNS median | ESI overhead median |
|---:|---:|---:|---:|
| 50 | 11.01 s | 7.93 s | 3.32 s |
| 80 | 41.35 s | 34.23 s | 6.61 s |

The matched-runtime experiment uses rounded budgets:

| K | Budget point | Total stochastic budget | ESI exploration budget | ESI elite/oracle budget | RRT schedule horizon |
|---:|---:|---:|---:|---:|---:|
| 50 | 1x | 15 s | 11 s | 4 s | 100 |
| 50 | 2x | 30 s | 22 s | 8 s | 200 |
| 80 | 1x | 45 s | 38 s | 7 s | 100 |
| 80 | 2x | 90 s | 76 s | 14 s | 200 |

RGA-MR and B-ALNS receive the full total stochastic budget. ESI-ALNS receives
the same total nominal budget split into exploration and elite/oracle phases.

The 1x point is the primary fairness comparison. The 2x point is a budget
sensitivity check and must not be used to retune the algorithm after seeing the
results.

## Execution order

To reduce systematic order effects while keeping every method on the same runner,
the three stochastic methods are rotated by algorithm seed:

- seed 100: RGA-MR -> B-ALNS -> ESI-ALNS;
- seed 101: B-ALNS -> ESI-ALNS -> RGA-MR;
- seed 102: ESI-ALNS -> RGA-MR -> B-ALNS.

Each method owns its own RNG initialized from the same algorithm seed, so
execution order does not share random state.

## Required reporting

For every method / setting:

- strict Stage-1 success count and true denominator;
- strict-subset energy distribution;
- actual search runtime and budget overrun;
- Stage-1 verification runtime;
- Stage-2 extraction runtime where available;
- search work count (ALNS iterations or GA generations/evaluations);
- solution structure summary;
- QoS/resource metrics on valid strict solutions.

For ESI-ALNS vs B-ALNS and ESI-ALNS vs RGA-MR:

- common-strict paired energy gain;
- better/equal/worse counts;
- scenario-level aggregation across the three nested algorithm repetitions.

No failed run is filled with zero energy. Conditional means are explicitly
labelled as strict-subset statistics.
