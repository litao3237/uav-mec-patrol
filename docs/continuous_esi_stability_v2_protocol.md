# Continuous ESI Stability v2 Protocol

Branch: `experiment/continuous-esi-stability-v2`

Parent branch: `experiment/adaptive-esi-stability`

The v1 results on seeds 53--60 are development evidence only. This v2 policy
is frozen before observing the final hold-out seeds 61--68.

## Changes relative to v1

1. **One uninterrupted ALNS engine**
   - no phase restart after ESI;
   - roulette-wheel weights are preserved;
   - RNG state is preserved;
   - one time-scaled RRT object runs continuously.

2. **Low-frequency strict certification**
   - strict Stage-1 certification occurs only when a stagnation-triggered ESI
     event is attempted and, optionally, once at the end;
   - there is no Stage-1 certification at every ALNS phase boundary.

3. **Explicit final-certificate reserve**
   - part of the nominal wall-clock budget is reserved for final strict
     certification instead of allowing oracle work to consume the entire
     exploration budget.

4. **Safe ESI reinjection**
   - an ESI solution may be stored in the strict archive when strict energy
     improves;
   - it is reinjected into the live ALNS trajectory only when its screened
     objective is also non-worsening;
   - otherwise ALNS continues from its existing screened-best trajectory.

## Frozen policy

For total nominal runtime T:

- final strict-certificate reserve: 0.10 T;
- stagnation window: 0.20 T;
- minimum exploration before first ESI trigger: 0.35 T;
- total ESI/oracle pool target: 0.12 T;
- maximum ESI burst per trigger: 0.06 T;
- maximum ESI triggers: 2;
- elite rounds per trigger: 1;
- final recertification is skipped when a strict archive already exists and
  the final screened best has improved by less than 0.2% since the last
  certified screened state;
- ESI reinjection requires non-worsening screened objective.

The total nominal budgets remain:

- K=50: 15 s;
- K=80: 45 s.

## Hold-out matrix

Fresh unseen scenario seeds:

- **61--68** (8 independent scenarios).

Nested stochastic repeats:

- algorithm seeds 100, 101, 102.

Problem points:

- K=50, M=5, E=2;
- K=80, M=5, E=2.

Total: 48 seed-pair jobs.

## Compared methods

- `legacy_b_alns`;
- `legacy_esi`;
- `time_b_alns`;
- `continuous_esi`.

## Acceptance criteria

Continuous ESI v2 is considered suitable for promotion only if:

1. strict Stage-1 rate is not lower than legacy ESI at either K;
2. fully-strict scenario count is not lower than legacy ESI;
3. mean within-scenario algorithm-seed CV is no worse at both K, or any small
   degradation is offset by a clear reduction in negative scenario outcomes;
4. continuous ESI does not show a systematic negative scenario-level shift
   against time-scaled B-ALNS;
5. mean runtime overrun is materially lower than adaptive ESI v1 and remains
   operationally small;
6. any mean energy improvement is supported by scenario-level behavior rather
   than one or two outlier scenarios.

No parameter may be changed after viewing seeds 61--68 and still call the same
matrix a hold-out validation.
