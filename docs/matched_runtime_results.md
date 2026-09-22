# Matched-Runtime Fairness Experiment

This document records the completed paper-facing wall-clock fairness experiment
for RGA-MR, B-ALNS, and ESI-ALNS.

The execution protocol was frozen before interpretation in
`docs/compute_budget_protocol.md`.

## Matrix completeness

Formal workflow run: `35706790157`.

Frozen code revision:

`b182b64e302b56a737db276cc6cf1399e5e6a4f7`

The run completed successfully with:

- 96/96 expected seed-pair jobs;
- 1/1 aggregate job;
- 97/97 GitHub Actions jobs successful;
- 8 independent scenario instances (45--52);
- 3 algorithm repetitions per scenario (100/101/102);
- K in {50,80};
- 1x and 2x wall-clock budget caps.

The aggregate file passed the explicit 96-pair coverage check. Earlier
pre-fix/cancelled runs must not be merged into this result.

## Timing protocol

Primary 1x budgets:

- K=50: 15 s total stochastic search cap;
- K=80: 45 s total stochastic search cap.

ESI-ALNS splits the same nominal cap into B-ALNS exploration plus strict
elite/oracle refinement:

- K=50: 11 s exploration + 4 s elite;
- K=80: 38 s exploration + 7 s elite.

RGA-MR and B-ALNS receive the whole cap for their search. Fresh final Stage-1
verification and Stage-2 metric extraction are timed separately and are not
charged against the stochastic search cap.

The 2x budgets (30 s and 90 s) are budget-sensitivity checks, not the primary
fairness result.

## Primary 1x result

### K=50, 15 s

| Method | Strict Stage-1 | Mean strict energy (J) | Median strict energy (J) | Mean search runtime (s) |
|---|---:|---:|---:|---:|
| GR-MR | 7/8 scenarios | 226449.279 | 227768.558 | 0.063 |
| FTR-NM | 8/8 scenarios | 227825.225 | 227281.171 | 0.039 |
| RGA-MR | 22/24 | 227377.426 | 227768.558 | 15.891 |
| B-ALNS | 24/24 | **162840.509** | 164814.956 | 15.056 |
| ESI-ALNS | 24/24 | 163305.576 | 164884.881 | 14.539 |

On the 24 common-strict B-ALNS/ESI-ALNS pairs:

- ESI better: 7;
- equal: 9;
- B-ALNS better: 8;
- mean run-level ESI advantage: **-0.385%**;
- median run-level advantage: 0%;
- scenario-level mean advantage: **-0.385%**;
- scenario-level median: -0.164%;
- positive/equal/negative independent scenarios: 4/0/4;
- scenario-bootstrap 95% interval for the mean gain: approximately
  **[-1.61%, +0.59%]**.

Thus there is no supported equal-runtime claim that ESI-ALNS is better than
B-ALNS at K=50. The point estimate is slightly negative and the eight-scenario
uncertainty interval crosses zero.

Against RGA-MR, however, ESI-ALNS is lower-energy on all 22 common-strict pairs.
The mean run-level paired advantage is **28.540%**, and all eight independent
scenarios have positive scenario-averaged gains.

### K=80, 45 s

| Method | Strict Stage-1 | Mean strict energy (J) | Median strict energy (J) | Mean search runtime (s) |
|---|---:|---:|---:|---:|
| GR-MR | 1/8 scenarios | 262762.349 | 262762.349 | 0.506 |
| FTR-NM | 1/8 scenarios | 258429.809 | 258429.809 | 0.281 |
| RGA-MR | 3/24 | 262762.349 | 262762.349 | 47.101 |
| B-ALNS | 23/24 | 223868.579 | 223527.492 | 45.795 |
| ESI-ALNS | 23/24 | **222376.257** | 224882.328 | 44.956 |

On the 22 common-strict B-ALNS/ESI-ALNS pairs:

- ESI better: 8;
- equal: 5;
- B-ALNS better: 9;
- mean run-level ESI advantage: **+0.328%**;
- median run-level advantage: 0%;
- scenario-level mean advantage: **+0.387%**;
- scenario-level median: +0.110%;
- positive/equal/negative independent scenarios: 5/0/3;
- scenario-bootstrap 95% interval for the mean gain: approximately
  **[-0.16%, +1.01%]**.

The point estimate favors ESI slightly, but the result is heterogeneous and the
eight-scenario interval crosses zero. Therefore the supported conclusion is
again **comparable same-time quality**, not a robust same-time superiority
claim.

RGA-MR remains primarily a feasibility baseline at K=80: only 3/24 runs are
strict, all in one independent scenario. ESI is lower-energy on all three
common-strict pairs, but this tiny conditional subset must not be generalized as
a broad K=80 energy comparison.

## 2x budget sensitivity

### K=50, 30 s cap

- RGA-MR: 23/24 strict, mean strict energy 228056.629 J;
- B-ALNS: 22/24 strict, mean strict energy 158822.813 J;
- ESI-ALNS: 24/24 strict, mean strict energy 158536.624 J.

On 22 common-strict B-ALNS/ESI pairs:

- ESI better/equal/worse = 5/13/4;
- mean paired ESI advantage = +0.352%;
- scenario-level mean = +0.481%;
- positive/equal/negative scenarios = 4/1/3;
- bootstrap 95% interval approximately [-0.18%, +1.50%].

ESI uses only 24.45 s on average because the elite phase can terminate early,
whereas B-ALNS uses 30.26 s on average. This is therefore best interpreted as an
equal-cap budget sensitivity, not equal consumed CPU time.

### K=80, 90 s cap

- RGA-MR: 3/24 strict;
- B-ALNS: 16/24 strict;
- ESI-ALNS: 18/24 strict.

All non-strict B-ALNS/ESI outcomes at this point are predominantly
`optimal_inaccurate` certificates rather than structural precheck failures:
B-ALNS has 8 `optimal_inaccurate` runs and ESI-ALNS has 6. Hence the lower
strict counts do not mean longer search mathematically destroyed feasibility;
they indicate that lower-energy/tighter terminal structures are harder for the
current conic solver stack to certify with exact `optimal` status.

On the 16 common-strict B-ALNS/ESI pairs:

- ESI better/equal/worse = 8/4/4;
- mean paired ESI advantage = +0.010%;
- scenario-level mean = +0.116%;
- positive/equal/negative scenarios = 5/0/3;
- bootstrap 95% interval approximately [-0.12%, +0.46%].

The 2x result again does not support a same-budget superiority claim.

## What the experiment changes in the paper

The earlier fixed-iteration experiment remains valid for a different question:

> Given exactly the same completed B-ALNS exploration trajectory, does adding
> the ESI post-refinement improve the returned solution?

For that paired question, ESI is monotone by construction and the 8x3
fixed-iteration experiment showed:

- K=50: 14 better / 10 equal / 0 worse, mean +1.549%;
- K=80: 17 better / 4 equal / 0 worse on 21 common-strict pairs, mean +0.673%.

The matched-runtime experiment answers the stricter fairness question:

> If B-ALNS is allowed to spend the elite-refinement time on further generic
> exploration instead, is ESI still consistently better?

The answer from the current eight scenarios is **no**. Same-time B-ALNS and
ESI-ALNS are broadly comparable, with small mixed paired differences.

Therefore the paper must distinguish:

1. **incremental post-refinement value at fixed exploration** -- supported;
2. **same-wall-clock superiority over B-ALNS** -- not supported;
3. **substantial advantage over simpler constructive/evolutionary baselines** --
   supported, especially at K=50, while K=80 is primarily a feasibility result.

The ESI contribution should be presented as a problem-specific, monotone
intensification mechanism that buys additional solution quality for a modest
extra oracle budget, not as an unqualified computationally dominant replacement
for B-ALNS.

## Unified Stage-2 metric coverage

The repaired Stage-2 pipeline completed without crashing. Stage-2/QoS records
are included only when both Stage 1 and the lexicographic Stage 2 are strict
`optimal`.

Primary 1x coverage:

| K | Method | Stage-1 strict | Stage-2 strict |
|---:|---|---:|---:|
| 50 | GR-MR | 7/8 | 6/8 |
| 50 | FTR-NM | 8/8 | 8/8 |
| 50 | RGA-MR | 22/24 | 19/24 |
| 50 | B-ALNS | 24/24 | 19/24 |
| 50 | ESI-ALNS | 24/24 | 22/24 |
| 80 | GR-MR | 1/8 | 1/8 |
| 80 | FTR-NM | 1/8 | 1/8 |
| 80 | RGA-MR | 3/24 | 3/24 |
| 80 | B-ALNS | 23/24 | 18/24 |
| 80 | ESI-ALNS | 23/24 | 19/24 |

Missing Stage-2 records are retained as explicit
`metrics_recompute_not_strict` diagnostics, primarily
`optimal_inaccurate`. They are excluded from QoS/resource averages but their
strict Stage-1 energy remains valid.

This completes the cross-method metric collection requirement without silently
substituting inaccurate Stage-2 primals.

## Paper-facing conclusion

The final comparison story should be:

- GR-MR/FTR-NM are fast constructive/decomposition baselines but lose solution
  quality and, at K=80, strict-feasibility robustness;
- RGA-MR remains much weaker than the ALNS family under both fixed-configuration
  and matched-runtime protocols;
- B-ALNS provides the main global exploration and feasibility-recovery power;
- ESI provides a verified monotone refinement of a fixed B-ALNS elite solution;
- the extra ESI refinement produces measurable gains when added after the same
  exploration trajectory, but when total wall-clock budget is held fixed the
  ESI/B-ALNS difference is small and mixed.

No claim of same-time ESI superiority over B-ALNS should appear in the paper.
