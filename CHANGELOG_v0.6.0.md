# CHANGELOG v0.6.0

## Focus

v0.6.0 starts the paper's core **Problem-Specific ALNS** implementation for
Route-Contact-Offloading-Resource coupling.

## Added

### Problem-specific destroy operators

- `mec_batch_pressure_removal`
  - targets high-pressure offloading batches using deadline ratio, upload time
    and MEC sharing pressure;
  - removes batch tasks so route/contact/batch decisions can be rebuilt.

- `shared_mec_pressure_removal`
  - detects MEC sites serving multiple active UAV-MEC pairs;
  - preferentially destroys tasks routed through the most contended MEC;
  - falls back to batch-pressure removal when no shared MEC exists.

### Problem-specific repair operators

- `contact_opportunity_repair`
  - performs ordinary task repair first;
  - then searches restricted contact-point candidates across MEC sites;
  - jointly changes route detour, channel quality and MEC selection while
    preserving Store-Carry-Offload order.

- `mode_batch_repair`
  - performs regret-2 route repair;
  - then explores Local -> MEC, MEC -> Local and task-to-contact reassignment;
  - orphan contacts are removed automatically;
  - task reassignment can restructure batches without changing the system model.

- `compute_aware_insertion_repair`
  - uses optimistic local-FIFO completion pressure when reinserting destroyed
    tasks;
  - balances geometric insertion cost against downstream deadline pressure;
  - finishes with MEC repair and a mode/batch improvement step.

### Configuration and ablation

- added `ProblemOperatorConfig` with restricted candidate budgets;
- `UavMecALNSConfig.enable_problem_operators` controls the proposed operator
  family and provides a clean generic-ALNS ablation;
- problem-specific operators are enabled by default;
- `run_alns_sanity.py --disable-problem-operators` enables a quick ablation;
- added `experiments/run_operator_ablation.py` for matched generic vs proposed
  comparisons using the same screened evaluator and final Stage-1 CVX oracle.

### Tests

- added factory/metadata checks for problem-specific operators;
- added destroy-state and repair-validity regression tests.

## Evaluator decision carried into v0.6.0

The default outer evaluator remains `ScreenedProxyObjectiveEvaluator`:

1. optimistic precheck failure -> hard infeasibility penalty;
2. proxy-feasible state -> fast proxy objective;
3. precheck-feasible but proxy-infeasible gray zone -> Stage-1 CVX refinement.

Pure proxy remains available for smoke tests and ablations. CVXPY Stage-1 remains
the final correctness oracle; KKT remains an analytical/dual-structure tool.

## Verification required

The code in this changelog has been committed to `develop`, but local tests and
paper-scale operator ablations must be run before marking the M6 items as
validated.
