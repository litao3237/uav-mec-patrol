# M0.2: B-ALNS search score, acceptance and selection diagnosis

## Fixed factors

- Base: M0.1 branch, frozen M0 resource physics (\`cvx_solver.py\` and \`problem.py\`
  content hashes checked at runtime). The search state, initial route builder,
  task deadlines (ON_TIME_TOL_S=1e-6), contact-point model, solver, constraint
  audit and final admission **must not differ** among arms.
- Exactly 100 ALNS iterations, same fixed scenario and algorithm seed, same
  greedy+MEC initial solution; no other algorithm is modified.
- Scalar arms (ONLY change is \`E/(1+E)\` and \`L/(1+L)\` vs physically
  normalized \`E/(E+sumBattery)\` and \`L/(L+sumCycleDistance)\`):
  \`legacy_adaptive_rrt\` and \`m0_adaptive_rrt\`.
  **Not** full v26 code replay: the CVX refinement, on-time tolerance,
  and physical screening are M0 for both.
- Factorial at K50/S45/A100 only: both scalar arms also run with
  frozen selector (decay=1, no learning) and with zero-gap RRT
  (greedy relative to current best).
- Search sequence trace stores pair/outcome/candidate scalar, structure hash,
  distance and contact count per iteration; optional logging uses no RNG or
  added numerical solver calls, and each score profile has a new evaluator
  cache.

## Frozen matrix

- K30: S45 seed100 (2 arms).
- K50: S45/46/47, seeds100/101/102 (9 pairs), with the four extra
  factorial controls on S45/A100.
- K80: S45 seed100 (2 arms).
- Primary: 11 matched seed-level pairs, six additional scalar arms in the
  K50 factorial (11*2 + 4=26 separate ALNS search runs).
- Scenarios, not seeds, are independent units for inference. K50 has just
  3 independent scenarios; these are diagnostic results, **not** significance
  evidence nor the new 816 formal dataset.

The archived M0 S45 A100 B-ALNS candidate fingerprint is a mandatory
replication control; fail if it changes without explanation. Every arm
recalculates admission, Stage-1, Stage-2 and independent physical hard
constraints under the exact same M0 resource solver.

## Diagnostics and interpretation

If both score profiles disagree at the first candidate-structure step but
not at operator selection, the acceptance/current state split is a candidate
mechanism. If their operator choices first diverge after a different
accept/reject outcome, adaptive operator reward feedback may amplify early
differences. Distinguish this from *proof* of causality; use frozen-weight
and zero-gap controls to isolate effects.

Compare on-time task count **before** Joules, and Joules before route distance
only for comparable success/lateness outcomes. Record search, resource and
total runtime; fixed-iteration arms do not establish equal-wall-clock
superiority. A large performance difference does not prove statistical
significance across only 3 independent K50 scenarios.

All outputs are new GitHub Actions artifacts in outputs/m02. Historical v26,
M0, M0.1 and \`results/\` stay unchanged. Do not launch the 816 formal matrix.
