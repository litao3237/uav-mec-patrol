# Terminal-Recovery ESI v3 Hold-out Protocol

Branch: `experiment/terminal-recovery-stability-v3`

Parent: `experiment/continuous-esi-stability-v2`

Previously observed scenario blocks 45--52, 53--60, and 61--68 are development
evidence. This v3 policy is frozen before observing seeds 69--76.

## Goal

v2 improved strict-certification robustness but often returned an older,
higher-energy strict archive instead of the lower-energy terminal screened
solution. v3 changes only terminal selection and numerical recovery.

The intended priority is:

1. return the terminal screened-best structure when it is strict;
2. if not strict, recertify the same terminal structure with a fresh
   high-accuracy conic solve;
3. if still non-strict and budget remains, search a small proxy-ranked
   structural neighborhood for the lowest strict candidate;
4. only then fall back to the best strict archive retained by continuous ESI.

No route/contact/batch neighborhood parameters are tuned in v3.

## Frozen runtime allocation

Total nominal method budget remains:

- K=50: 15 s;
- K=80: 45 s.

v3 reserves 8% of the outer budget for terminal recovery. The inner continuous
ESI therefore receives 92% of T.

Inside that inner run, the final-certificate reserve is reduced to 2% of the
inner budget. This keeps the generic exploration share approximately equal to
v2:

- v2 generic search target: 0.90 T;
- v3 generic search target: 0.92 x 0.98 T = 0.9016 T.

Thus terminal recovery is not funded by materially shrinking the generic ALNS
exploration budget.

## High-accuracy terminal recertification

If the terminal structure is not already the returned strict archive, v3 uses
a fresh recovery solver that does not reuse the default-oracle cache.

Recovery solver profile:

1. SCS first with `eps=2e-7`, `max_iters=300000`;
2. then Clarabel;
3. then ECOS when installed.

Exact `optimal` remains required. `optimal_inaccurate` is not promoted to a
strict certificate.

## Structural terminal recovery

If high-accuracy recertification remains non-strict and nominal time remains,
v3 evaluates one existing proxy-ranked structural shortlist around the terminal
state.

Unlike normal ESI, the terminal baseline itself is allowed to be non-strict.
The recovery step selects the lowest-energy candidate for which the strict
Stage-1 oracle returns a finite exact value.

No progressive tuning is performed after observing the hold-out.

## Uniform verification for all methods

To avoid conflating solver precision with algorithm quality, every returned
solution in the hold-out is evaluated by:

1. the historical default Stage-1 verifier;
2. only if that verifier is non-strict, a fresh high-accuracy recovery verifier.

Paper-compatible primary strict counts use the default verifier. The secondary
recoverable-strict count is diagnostic and is reported for all methods.

## Hold-out matrix

Fresh unseen scenarios:

- **69--76** (8 independent scenarios).

Nested stochastic repeats:

- 100, 101, 102.

Problem settings:

- K=50, M=5, E=2;
- K=80, M=5, E=2.

Total: 48 seed-pair jobs.

## Compared methods

1. `legacy_b_alns`;
2. `legacy_esi`;
3. `time_b_alns`;
4. `continuous_esi_v2`;
5. `terminal_recovery_esi_v3`.

## Promotion criteria

v3 is suitable for promotion only if, on the same S69--76 hold-out:

1. default strict rate is not lower than continuous ESI v2 at either K;
2. fully-strict scenario count is not lower than continuous ESI v2;
3. on common-default-strict pairs, v3 does not have a negative scenario-level
   mean energy shift versus v2;
4. K=80 within-scenario seed CV improves or is at least comparable with v2;
5. fallback-to-old-strict-archive is uncommon enough that v3 actually uses the
   terminal-first policy;
6. mean runtime overrun remains small (target <=0.5 s at K=50 and <=1.0 s at
   K=80);
7. any apparent strict advantage is checked against the uniform secondary
   recovery verifier for all competing methods.

Seeds 69--76 may not be reused as unseen validation after any v3 parameter is
changed.
