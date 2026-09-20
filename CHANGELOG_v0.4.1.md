# Changelog v0.4.1

## Added

- algorithms/initial/greedy.py
  - deterministic parallel task insertion across UAVs;
  - earliest-deadline/farthest-node construction priority;
  - lexicographic cycle/deadline/distance insertion score;
  - route-local 2-opt improvement;
  - returns a fully valid all-local DiscreteSolution.
- experiments/run_initial_solution_sanity.py
  - reports route distance, route-time balance and optional KKT feasibility.
- tests/test_greedy_initial.py
  - validity, determinism, task uniqueness and multi-UAV-use regression tests.

## Design note

This version intentionally stops after task-to-UAV assignment and route ordering.
It does not yet insert MEC contacts. The all-local seed is a measurement baseline:
the next phase will add problem-specific Local-to-MEC mode switching and contact
insertion only where the resource/QoS diagnostics show they are needed.

The construction follows standard mature VRP ideas (parallel insertion and 2-opt)
rather than embedding a new routing metaheuristic inside the project.
