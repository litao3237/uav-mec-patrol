# v0.2.1

This patch addresses robust handling of infeasible fixed-discrete P1-R instances.

## Changes

- Added `fast_feasibility_precheck()` using optimistic lower bounds for:
  - per-task deadlines,
  - average delay,
  - patrol-cycle duration.
- Added conic-solver fallback:
  - try CLARABEL first,
  - fall back to SCS when CLARABEL raises `cvxpy.error.SolverError`.
- Treat infeasibility as a normal `ResourceSolveResult` rather than an exception.
- Added solver diagnostics (`stage1_solver`, fallback errors, etc.).

The precheck is intentionally optimistic, so it only rejects a fixed discrete solution when even an unrealistically favorable allocation (full MEC bandwidth/CPU and no competing queues) cannot satisfy QoS.
