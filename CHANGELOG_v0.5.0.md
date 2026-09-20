# Changelog v0.5.0

## Milestone

The project now enters the first complete outer-search prototype. The generic
metaheuristic loop is delegated to the mature N-Wouda ALNS package; this
repository implements only UAV-MEC state representation, domain-specific
destroy/repair operators, and P1-R recourse evaluation.

## Added

- algorithms/alns/evaluator.py
  - cached solution signatures;
  - ProxyObjectiveEvaluator for fast structural validation;
  - KKTObjectiveEvaluator for exact Stage-1 P1-R recourse;
  - finite infeasibility penalties so the search can move through infeasible
    discrete regions without using infinity as the ALNS objective.
- algorithms/alns/operators.py
  - random task removal;
  - deadline/compute-critical task removal;
  - route-segment removal;
  - global cheapest insertion repair;
  - regret-2 insertion repair;
  - every route repair is followed by the existing problem-specific MEC
    contact/offloading repair.
- algorithms/alns/runner.py
  - external ALNS integration;
  - RouletteWheel adaptive operator selection;
  - Record-to-Record Travel acceptance;
  - MaxIterations stopping criterion.
- experiments/run_alns_sanity.py
  - proxy or exact-KKT objective modes;
  - reports initial/best objective, contact count, exact final KKT feasibility,
    cache statistics, and runtime.
- tests/test_alns_framework.py
  - destroy/repair completeness;
  - objective-cache regression;
  - short external ALNS integration run.

## Dependency

The project now pins the ALNS API to:

    alns>=7.0,<8.0

This matches the public v7 operator-selection and acceptance interfaces used by
the implementation.

## Search architecture

    Greedy route seed
        -> MEC contact/offloading repair
        -> ALNS destroy/repair
        -> KKT P1-R recourse

The mature ALNS package handles operator adaptation and acceptance. The research
contribution remains in Route-Contact-Offloading-aware move design and the
resource-aware recourse/evaluation layer.

## Next

1. Validate v0.4.2 MEC repair on K=30/50.
2. Smoke-test v0.5.0 ALNS with the proxy objective.
3. Repeat short runs with exact KKT objective.
4. Add contact-specific destroy operators and KKT-dual-guided repair only after
   the basic search loop is numerically stable.
