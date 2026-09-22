# Budget Utilization v5 Protocol

Branch: `experiment/budget-utilization-v5`

Parent: `experiment/terminal-first-stability-v4`

This study changes only final-certification budget allocation. The continuous
ALNS engine, ESI trigger policy, structural operators, and terminal-first return
policy are frozen.

## Development evidence

The v4 hold-out block S77--84 is now development evidence.

Observed v4 terminal Stage-1 certification runtime:

| K | Median | P90 | P95 | Max |
|---:|---:|---:|---:|---:|
| 50 | 0.212 s | 0.323 s | 0.351 s | 0.364 s |
| 80 | 0.313 s | 0.609 s | 6.709 s | 9.770 s |

The original fixed 10% reserve provides:

- K=50: 1.50 s;
- K=80: 4.50 s.

Thus it is much larger than the typical certification cost. At K=80 there is a
rare heavy-tail solver regime; no small fixed reserve can eliminate that tail
without again under-utilizing the normal case.

## Frozen v5 reserve rule

The budget-aware method starts with a compact reserve:

[
R_0 = 0.03T.
]

Thus:

- K=50: R0 = 0.45 s;
- K=80: R0 = 1.35 s.

This covers the historical K=50 P95 and the historical K=80 P90 with margin.

During the continuous search, actual strict Stage-1 certification runtimes are
recorded. Before each stopping decision, the reserve becomes

[
R(t)=min(0.08T,max(0.03T,2max_j c_j)),
]

where (c_j) are certification runtimes already observed in the current run.

Therefore:

- the reserve never falls below 3% T;
- a slow observed oracle call can increase the reserve;
- the reserve is capped at 8% T;
- unseen terminal-solve heavy tails can still overrun because a CVX solve is
  indivisible; such overruns are measured, not hidden.

No result from S85--92 may be used to change these constants.

## Compared budget policies

1. `time_b_alns`
   - time-scaled B-ALNS;
   - full nominal search budget;
   - no terminal reserve mechanism.

2. `terminal_fixed10`
   - v4 terminal-first continuous ESI;
   - fixed final reserve = 10% T.

3. `terminal_fixed3`
   - same v4 algorithm and terminal policy;
   - fixed final reserve = 3% T.

4. `terminal_budget_aware_v5`
   - same terminal-first continuous ESI;
   - initial reserve = 3% T;
   - reserve expands adaptively using the frozen rule above.

The fixed-3% arm is required to determine whether any benefit comes merely from
releasing search time or from adaptive reserve growth.

## Hold-out matrix

Fresh unseen scenario seeds:

- **85--92** (8 independent scenarios).

Nested stochastic repeats:

- algorithm seeds 100, 101, 102.

Problem settings:

- K=50, M=5, E=2, T=15 s;
- K=80, M=5, E=2, T=45 s.

Total: 48 seed-pair jobs.

## Required outputs

Per method/run:

- strict Stage-1 status and strict energy;
- total method runtime;
- ALNS search runtime;
- final certification runtime;
- budget utilization ratio;
- overrun and unused nominal budget;
- completed ALNS iterations;
- ESI trigger/improvement counts where applicable.

For v5 additionally:

- initial reserve;
- final adaptive reserve;
- certification runtime samples;
- number of runs where the reserve expanded above 3% T;
- selection source.

## Primary questions

1. Does releasing the unused fixed 10% reserve improve energy?
2. Does the 3% reserve preserve strict feasibility?
3. Does adaptive reserve expansion reduce runtime-risk relative to fixed 3%?
4. Does v5 use more of the nominal budget without recreating v3-like long
   tails?

## Promotion criteria

v5 is considered a successful budget-utilization improvement only if:

1. strict rate is not lower than `terminal_fixed10` at either K;
2. fully-strict scenario count is not lower than `terminal_fixed10`;
3. scenario-level mean energy shift versus `terminal_fixed10` is non-negative
   at both K;
4. mean total-runtime utilization is at least 96% at both K;
5. mean overrun is <=0.5 s at K=50 and <=1.0 s at K=80;
6. maximum overrun is materially below the v3 32.05 s tail;
7. v5 strict rate is not lower than `terminal_fixed3`;
8. v5 scenario-level mean energy is not worse than `terminal_fixed3` by more
   than 0.25%;
9. if reserve expansion occurs, it must correspond to observed slow
   certification rather than unconditional reserve growth.

If fixed 3% matches or beats v5 on quality, strictness, and runtime risk, the
simpler fixed-3% policy is preferred.

Seeds 85--92 become development evidence immediately after this hold-out is
observed.
