# Changelog v0.4.0

## Milestone

The validated P1-R resource layer is frozen as the reference recourse model. The
codebase now starts the P1-D outer-search stage.

Hard-regime validation covers baseline, tight bandwidth, tight MEC CPU, tight
average delay, local FIFO, repeated contact with the same MEC, two-MEC routing,
and an intentionally infeasible deadline. After the v0.3 dual-convergence fix,
all feasible cases agree with the CVXPY Stage-1 oracle to about 1e-9 relative
energy or better in the current validation set.

## Added

- instances/paper_scale.py
  - reproducible K/M/E-scale forest instance generator;
  - typed PaperScaleConfig;
  - fixed heterogeneous MEC infrastructure;
  - configurable continuous-coverage discretization into candidate contact
    points;
  - seed-controlled task geometry and workload generation;
  - deadline generation with only an optimistic individual-task lower-bound
    guard, avoiding artificial global feasibility.
- experiments/run_instance_sanity.py
  - K=30/50/80/100 generation sanity scan.
- tests/test_paper_scale_instance.py
  - reproducibility, range, geometry and K/M/E-sweep regression tests.

## Baseline generation assumptions

The baseline generator currently uses a 1000 m x 1000 m forest, K=50, M=5,
E=3, 450 s patrol cycle, 300 s mean-delay budget, task size U(1,4) MB and
cycles/bit U(800,1200). MEC site coordinates and the cycle/deadline calibration
remain experiment parameters rather than mathematical constants and should be
recalibrated during the non-degeneracy scan.

## Next

1. Greedy initial route/task assignment.
2. Initial Local/MEC mode and contact insertion heuristic.
3. Feasibility-aware local search.
4. Problem-specific ALNS operators.
