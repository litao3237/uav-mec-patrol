# Adaptive ESI Stability Validation Protocol

Branch: `experiment/adaptive-esi-stability`

Base revision: `develop@ed2f185b6ebc150fbaaaef35f77b8c0305cc5238`

This branch is experimental. No result from it replaces the frozen paper-facing
algorithm unless the stability criteria below are met on unseen scenarios.

## Purpose

The goal is not to tune ESI until it beats B-ALNS. The goal is to reduce:

- algorithm-seed sensitivity;
- scenario-to-scenario variance;
- strict-Stage-1 certification loss;
- instability caused by iteration-scaled acceptance under wall-clock stopping.

## Experimental changes

Three stability mechanisms are tested:

1. **Time-scaled RRT**
   - RRT threshold follows elapsed wall-clock fraction rather than iteration
     count when a runtime cap is active.
2. **Strict incumbent archive**
   - adaptive ESI retains the best strict `Stage-1=optimal` solution observed
     at phase boundaries / elite refinement;
   - if the final screened state is numerically ambiguous, the algorithm can
     return the best strict incumbent instead.
3. **Stagnation-triggered ESI**
   - generic B-ALNS exploration stops a phase only after a minimum exploration
     period plus a measured no-improvement window;
   - ESI is triggered only after stagnation;
   - generic exploration resumes with remaining wall-clock time.

The frozen `develop` implementation and defaults are not modified.

## Unseen validation scenarios

Seeds 45--52 are frozen historical paper scenarios and are not used to tune this
branch.

The first validation matrix uses:

- scenario seeds: **53--60** (8 independent instances);
- algorithm seeds: **100,101,102** (nested repetitions);
- K: **50 and 80**;
- M=5, E=2.

Total: 48 seed-pair jobs.

## Methods compared

1. `legacy_b_alns`
   - existing B-ALNS;
   - legacy iteration-scaled RRT;
   - full common wall-clock cap.

2. `legacy_esi`
   - existing fixed-split ESI-ALNS;
   - K=50: 11 s exploration + 4 s elite;
   - K=80: 38 s exploration + 7 s elite.

3. `time_b_alns`
   - B-ALNS with time-scaled RRT only;
   - no ESI;
   - full common wall-clock cap.

4. `adaptive_esi`
   - time-scaled RRT;
   - strict incumbent archive;
   - stagnation-triggered ESI;
   - same total nominal wall-clock cap.

## Adaptive policy frozen before results

For total budget T:

- stagnation window = 0.20 T;
- minimum first exploration = 0.35 T;
- each ESI burst <= 0.15 T;
- max ESI triggers = 2;
- one elite round per trigger.

Thus:

- K=50, T=15 s:
  - stagnation = 3.0 s;
  - minimum first exploration = 5.25 s;
  - elite burst <= 2.25 s.
- K=80, T=45 s:
  - stagnation = 9.0 s;
  - minimum first exploration = 15.75 s;
  - elite burst <= 6.75 s.

These values are ratio-based and frozen before observing seeds 53--60.

## Stability criteria

The adaptive version is considered promising only if it improves robustness
without relying on a single favorable mean.

Primary criteria:

1. strict Stage-1 rate is not lower than legacy ESI;
2. number of fully-strict independent scenarios (3/3 algorithm seeds) does not
   decrease;
3. within-scenario algorithm-seed CV/spread decreases or remains comparable;
4. adaptive-vs-legacy ESI has fewer materially negative scenario-level outcomes;
5. adaptive-vs-time-B-ALNS does not show a systematic negative scenario-level
   shift;
6. mean wall-clock overrun remains small and explicitly reported.

Energy is a secondary criterion after strictness/stability. A higher mean gain
with larger scenario variance is not considered a stability improvement.

## Hold-out rule

If seeds 53--60 are used to change any adaptive policy parameter after this run,
they become development data. A later final validation must then use a fresh
unseen block (recommended seeds 61--68) with no further tuning.
