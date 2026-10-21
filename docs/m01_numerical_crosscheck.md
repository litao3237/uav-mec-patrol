# M0.1 frozen input numerical and cross-resource replay

Run the isolated GitHub Actions job on branch
\`experiment/m01-numerical-crosscheck\`; do **not** overwrite results/ or
rerun the 816-row main matrix.

## Frozen sources
- Old v26: workflow run 39429879939, SHA 0335b1251ee2ca85399c5b685814ad5b9f284267,
  artifact \`v26-formal-verification-39429879939\`.
- Fixed M0: workflow run 39456198442, SHA 540e7b3193d28feb9bca57eb9998a8098c91c2a3,
  artifact \`m0-pilot-verified-39456198442\`.

All use identical original instance and config fingerprints for K=30,50,80,
scenario seed=45 and algorithm seed=100. Never compare old and new outcomes
by merely juxtaposing original Joules: resource solvers have changed.

## Two separate examinations

1. **Recorded M0 Stage-2 rejection replay.** Independently audit saved and
   reconstructed CVX Stage-2 candidate variables. Quantify which frozen
   guard failed: lost on-time tasks, normalized tardiness beyond \`1e-8\`,
   or energy above Stage-1 energy + max(1e-5, 1e-6 * Stage-1 Joules).
   No rejected candidate is silently accepted or its energy used to replace
   the actual admitted Stage-1 result.
2. **Common-solver crossed experiment.** For each K, take two final discrete
   method solutions (B-ALNS and ESI-ALNS) from both the v26 and M0 artifacts.
   Restore each original solution; independently verify SHA-256 identity.
   Run the **same checked-out M0 recourse** by calling
   \`finalize_task_qos\` (algorithm-independent admission, guarded Stage-1,
   Stage-2, residual audit). This produces 12 new and independently accepted
   recourse outcomes. Important: \`finalize_task_qos\` does *not* rerun the
   discrete ALNS search. It only compares the two frozen search structures
   under one common resource policy.

Outcome CSV contains task count, actual normalized lateness, Joules, route
distance, physical acceptance, new task admission, provenance and recourse
runtime. Pair differences are **M0 search structure minus v26 structure**.
If the common solver drops tasks or loses physical acceptance, record it
explicitly and do not claim an energy-only ranking.

## Numerical interpretation

The current on-time classification tolerance is \`1e-6 s\`; the physical
residual audit has its own frozen tolerance and does not imply permission to
violate the task-success protection criteria. A candidate can be physically
valid yet be correctly rejected by a stricter QoS guard.

M0 Stage-1A remains a convex QoS surrogate, **not exact maximum cardinality**.
The scalar outer-search score still approximates real-valued lexicographic
ordering, so the diagnostic cannot certify a globally optimal search.

## Scope safeguards
- Do not modify or mix the v26/M0 stored raw artifacts.
- No automatic resume of the full formal 816-row experiment.
- Do not relabel B-ALNS with the shared ESI elite-stage improvement trace:
  historical rows in M0 contain shared diagnostics and the audit must treat
  B-ALNS as exploration only.
- The 12 new resource recourse outcomes must be saved separately from the
  21 original M0 pilot rows and the 816 original v26 rows.
