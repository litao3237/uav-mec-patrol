# Changelog v0.4.2

## Added

- algorithms/initial/mec_repair.py
  - critical-local-task detection from a max-local-CPU/equal-MEC-share proxy;
  - restricted candidate list for new MEC contact insertion;
  - reuse of existing contacts for Store-Carry-Batch-Offload;
  - lexicographic normalized infeasibility ranking before energy/distance;
  - deterministic Local-to-MEC greedy repair.
- experiments/run_mec_repair_sanity.py
  - compares the all-local seed and MEC-repaired seed;
  - invokes the exact analytical KKT recourse only after the cheap repair loop.
- tests/test_mec_repair.py
  - validity, monotonic proxy improvement, offloading activation and determinism.

## Why

The route-only seed is cycle-feasible at K=30/50 but P1-R reports
kkt_no_feasible_iterate. This is the desired signal that local FIFO compute
pressure exists even though pure patrol geometry is easy. v0.4.2 therefore adds
the first problem-specific Route-Contact-Offloading repair stage rather than
loosening the scenario parameters.

## Mature implementation pattern

The repair follows the standard ALNS/VRP pattern of critical-request selection,
restricted candidate lists and greedy best insertion. The domain-specific part
is the move definition and evaluation: a request can switch Local-to-MEC, reuse
a later contact for batching, or create a route-dependent MEC contact.
