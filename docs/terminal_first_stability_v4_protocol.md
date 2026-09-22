# Terminal-First ESI v4 Hold-out Protocol

Branch: `experiment/terminal-first-stability-v4`

Parent: `experiment/terminal-recovery-stability-v3`

Observed scenario blocks 45--52, 53--60, 61--68, and 69--76 are development
evidence. This v4 policy is frozen before observing seeds 77--84.

## Motivation

v3 showed that terminal-first selection is useful, while expensive terminal
recovery is not:

- K=80 v3 preserved 20/24 strict and improved mean paired energy versus v2;
- high-accuracy recovery succeeded in 0/4 K=80 attempts;
- structural recovery succeeded in 0/2 K=80 attempts;
- mean K=80 overrun increased to 3.16 s, with a 32.05 s maximum.

v4 therefore removes both recovery layers from the default path.

## Frozen algorithm

One uninterrupted continuous ALNS engine is retained.

At termination:

1. take the final screened-best discrete structure;
2. run exactly one default Stage-1 certification, reusing the existing oracle
   cache when possible;
3. if the terminal structure is strict `optimal`, return it;
4. otherwise, if a strict incumbent was already certified during continuous
   ESI, return that incumbent;
5. otherwise return the non-strict terminal solution with its status.

There is:

- no high-accuracy SCS recertification;
- no terminal structural recovery;
- no ALNS restart;
- no change to route/contact/batch operators;
- no change to ESI trigger ratios.

## Frozen timing

Total nominal budgets:

- K=50: 15 s;
- K=80: 45 s.

The continuous search reserves 10% of T for final certification, exactly as v2:

- generic/ESI live-search deadline: 0.90 T;
- final terminal certification uses the remaining reserve.

The continuous ESI policy remains:

- stagnation window: 0.20 T;
- minimum exploration before first ESI: 0.35 T;
- ESI/oracle pool: 0.12 T;
- maximum ESI burst: 0.06 T;
- maximum ESI triggers: 2;
- one elite round per trigger.

## Hold-out matrix

Fresh unseen scenarios:

- **77--84** (8 independent scenarios).

Nested algorithm repeats:

- 100, 101, 102.

Settings:

- K=50, M=5, E=2;
- K=80, M=5, E=2.

Total: 48 seed-pair jobs.

## Compared methods

1. `legacy_b_alns`;
2. `legacy_esi`;
3. `time_b_alns`;
4. `continuous_esi_v2`;
5. `terminal_first_esi_v4`.

All returned solutions use the same default Stage-1 verifier. No secondary
high-accuracy verifier is used in the primary hold-out.

## Promotion criteria

v4 is suitable for promotion only if:

1. strict rate is not lower than continuous ESI v2 at either K;
2. fully-strict independent-scenario count is not lower than v2;
3. scenario-level mean energy shift versus v2 is non-negative at both K;
4. K=80 within-scenario seed CV is no worse than v2 by more than 0.25
   percentage points;
5. mean runtime overrun is <=0.5 s at K=50 and <=1.0 s at K=80;
6. maximum overrun is materially below the v3 long tail;
7. terminal-first selection is actually used in the majority of strict runs,
   rather than merely reproducing strict-incumbent fallback.

Seeds 77--84 may not be reused as unseen validation after changing any v4
parameter.
