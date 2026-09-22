# Budget-Aware Terminal-First ESI v5 Hold-out Protocol

Branch: `experiment/budget-aware-terminal-first-v5`

Parent: `experiment/terminal-first-stability-v4`

Observed scenario blocks 45--84 are development evidence. This v5 policy is
frozen before observing seeds 85--92.

## Motivation

v4 showed that terminal-first selection is stable and removes the v3 recovery
tail, but its fixed 10% final-certification reserve leaves substantial search
time unused:

- K=50 mean runtime: about 13.77 s of a 15 s nominal budget;
- K=80 mean runtime: about 42.19 s of a 45 s nominal budget;
- typical final Stage-1 certification is much cheaper than the fixed reserve.

v5 changes only budget allocation. The ALNS/ESI operators, trigger ratios,
terminal-first selection rule, and strict fallback semantics are unchanged.

## Frozen v5 policy

For total nominal runtime T:

- final certification reserve: **0.03 T**;
- live-search deadline: **0.97 T**;
- one opportunistic strict checkpoint at **0.60 T**, but only when no strict
  incumbent has already been created naturally;
- stagnation window: 0.20 T;
- minimum exploration before first ESI trigger: 0.35 T;
- ESI/oracle pool: 0.12 T;
- maximum ESI burst: 0.06 T;
- maximum ESI triggers: 2;
- one elite round per trigger.

Terminal selection remains:

1. certify final screened-best structure once with the default Stage-1 solver;
2. return terminal candidate if strict;
3. otherwise return the best existing strict incumbent if available;
4. otherwise return the terminal non-strict candidate with its status.

There is no high-accuracy recovery and no terminal structural recovery.

## Hold-out matrix

Fresh unseen scenarios:

- **85--92** (8 independent scenarios).

Nested stochastic repeats:

- algorithm seeds 100, 101, 102.

Problem settings:

- K=50, M=5, E=2;
- K=80, M=5, E=2.

Total: 48 seed-pair jobs.

## Compared methods

1. `legacy_b_alns`;
2. `legacy_esi`;
3. `time_b_alns`;
4. `terminal_first_esi_v4`;
5. `budget_aware_terminal_first_v5`.

## Promotion criteria

v5 is suitable for promotion only if:

1. strict Stage-1 rate is not lower than v4 at either K;
2. fully-strict scenario count is not lower than v4;
3. scenario-level mean energy shift versus v4 is non-negative at both K;
4. K=80 within-scenario seed CV is no worse than v4 by more than 0.25
   percentage points;
5. mean runtime is closer to the nominal budget than v4 without increasing
   mean overrun above 1.0 s at K=80 or 0.5 s at K=50;
6. maximum overrun remains materially below the v3 recovery tail;
7. checkpoint cost is justified: either it contributes strict fallback
   availability in runs where terminal certification fails, or it is cheap
   enough not to erase the released search-time benefit.

Seeds 85--92 may not be reused as unseen validation after changing any v5
parameter.
