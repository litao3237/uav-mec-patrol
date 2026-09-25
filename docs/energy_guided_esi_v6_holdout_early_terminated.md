# Energy-Guided ESI v6 Hold-out: Early-Terminated Result

Branch: `experiment/energy-guided-esi-v6`

Frozen hold-out run: `35734227589`

Frozen algorithm commit: `b56aca30280da4c5423435d188e9505a9155f327`

Protocol: `docs/energy_guided_esi_v6_holdout_protocol.md`

## Execution status

The hold-out matrix targeted:

- scenarios S93--100;
- algorithm seeds 100/101/102;
- K=50 and K=80;
- 48 seed-pair jobs.

Observed before termination:

- 47/48 seed-pair jobs completed successfully;
- K=50: 24/24 complete;
- K=80: 23/24 complete;
- missing pair: K=80 / S100 / A102;
- no algorithm job failed;
- the missing job stalled during dependency installation before the experiment
  itself started;
- the workflow was then cancelled because the already observed results made
  promotion implausible and further CI consumption was not justified.

The aggregate job was skipped because the matrix was intentionally incomplete.

## K=50 completed matrix

All 24 runs are strict for Time-B-ALNS, budget v5, and energy-guided v6.

Energy-guided v6 versus budget v5:

- better/equal/worse: 6/14/4;
- scenario-level mean paired gain: **-0.039%**;
- positive/equal/negative scenarios: 4/1/3.

Energy-guided v6 versus Time-B-ALNS:

- better/equal/worse: 5/11/8;
- scenario-level mean paired gain: **-0.227%**;
- positive/equal/negative scenarios: 2/0/6.

The pre-registered K=50 tolerance against Time-B was -0.25%, so the Time-B
criterion remained barely inside tolerance. However, the required non-negative
shift versus budget v5 was already missed.

## K=80 partial matrix

Completed pairs: 23/24.

Observed strict counts among completed pairs:

- Time-B-ALNS: 22/23;
- budget v5: 21/23;
- energy-guided v6: 21/23.

On common-strict completed pairs:

Energy-guided v6 versus budget v5:

- scenario-level mean paired gain: approximately **-0.646%**;
- positive/equal/negative scenario means over the eight partially/fully
  represented scenarios: 3/1/4.

Energy-guided v6 versus Time-B-ALNS:

- scenario-level mean paired gain: approximately **-0.082%**;
- positive/equal/negative scenario means: 5/0/3.

The frozen promotion criteria required:

- non-negative scenario-level mean gain versus budget v5;
- at least +0.25% scenario-level mean gain versus Time-B at K=80.

Given the 23 completed pairs, the missing S100/A102 pair would have needed
approximately **+12% paired improvement versus budget v5** to rescue the
non-negative K=80 v5 criterion. Such a result would be far outside the
observed effect scale and would not justify continued CI consumption.

Therefore the hold-out was terminated without waiting for the stalled runner.

## Important mechanism diagnosis

The failed promotion does **not** mean every energy-guided ESI move was bad.

Two inspected outliers show why integrated same-time results are noisy.

### K=50 / S94 / A101

The energy-guided run did not execute an ESI improvement, yet its final energy
was substantially worse than the other methods.

The main difference was the time-bounded base search trajectory:

- v5 completed about 55 ALNS iterations;
- v6 completed about 45.

Thus this gap cannot be attributed to an accepted Energy-Guided ESI move.

### K=80 / S100 / A101

Energy-guided v6 accepted two strict coupled offloading moves and reduced the
current strict objective by approximately **5141 J** in direct ESI gain.

Nevertheless the final v6 solution was worse than Time-B/v5 because the
underlying search trajectory entering intensification was already much worse.

Thus the energy-guided operator itself can produce real strict energy
improvements, but the current integrated wall-clock experiment confounds:

1. base ALNS trajectory quality;
2. number of iterations completed under wall-clock variation;
3. elite-trigger timing;
4. ESI marginal value.

## Decision

**Do not promote energy-guided v6 as the integrated paper algorithm.**

The unseen hold-out does not support the pre-registered claim that integrated
Energy-Guided ESI provides a robust same-time improvement over budget v5 or
Time-B-ALNS.

At the same time, development and inspected hold-out moves provide enough
evidence that the energy-guided coupled neighborhood itself remains worth
studying.

## Next experiment: paired marginal-value fork

The next experiment should no longer compare two independently evolving
time-bounded trajectories.

Instead, obtain one identical B-ALNS checkpoint and fork it into two equal-cost
continuations:

[
\text{same B-ALNS checkpoint}
\rightarrow
\begin{cases}
\text{continue B-ALNS for }\Delta T,\\
\text{Energy-Guided ESI for }\Delta T.
\end{cases}
]

Both arms must start from the same:

- current solution;
- best solution;
- adaptive operator weights;
- RNG state;
- elapsed-time reference / acceptance state where applicable.

Primary endpoint:

[
\Delta E_{ESI}/\Delta T
\quad\text{vs}\quad
\Delta E_{B-ALNS}/\Delta T.
]

Also report:

- direct J/s;
- J/exact-CVX;
- accepted exact-CVX hit rate;
- strict outcome;
- coupled move family.

This design directly answers the scientific question:

> Given the same already-obtained B-ALNS search state and the same additional
> computation budget, is Energy-Guided ESI a better use of the next second than
> simply continuing B-ALNS?

The next unseen scenario block should not reuse S93--100. Use a new block only
after the paired-fork mechanism has been developed and frozen.
