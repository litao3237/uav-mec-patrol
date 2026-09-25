# Energy-Guided ESI v6 Development Plan

Branch: `experiment/energy-guided-esi-v6`

Parent: `experiment/budget-utilization-v5`

This branch returns to the algorithmic question that remains unresolved after
v1--v5:

> under the same wall-clock budget, can ESI produce more energy reduction per
> unit time than simply continuing B-ALNS?

The v5 budget-aware terminal policy is retained. This development stage changes
only the ESI candidate-generation and exact-evaluation policy.

## Mechanism hypotheses

### H1. Energy-hotspot task ranking

The legacy elite task list is driven mainly by deadline criticality and route
removal distance. v6 instead attributes the current strict Stage-1 UAV energy
to each task:

- marginal route-flight energy;
- local-compute energy from exact Stage-1 local CPU;
- allocated contact/upload energy for offloaded tasks.

Deadline and cycle duals are used only as small ranking modifiers, not as an
energy estimate.

### H2. Coupled Route--Offload relocation

A candidate is no longer limited to:

`remove task -> reinsert task -> generic MEC repair`.

For a high-energy task, v6 explicitly constructs:

`task -> target UAV/route position -> local or existing contact or new contact`.

Thus route assignment, route position, execution mode, contact and batch choice
can change in one structured move.

### H3. Cost-aware exact shortlist

All generated candidates first pass:

1. deterministic structural validation;
2. optimistic feasibility precheck;
3. cheap proxy energy evaluation.

The exact shortlist is globally ranked by proxy energy gain divided by a small
CVX model-complexity proxy. There is no mandatory one-candidate-per-family
quota.

Default exact shortlist:

- at most 3 candidate checks per ESI round;
- one ESI round per continuous trigger, inherited from v5.

The proxy is allowed to be conservative: if fewer than three positive
proxy-gain candidates exist, remaining exact slots are filled using the
highest-energy hotspots that still pass the optimistic precheck.

## New efficiency metrics

Every ESI trigger records:

- candidates generated;
- candidates surviving cheap ranking;
- exact candidate evaluations;
- actual new CVX calls;
- strict-candidate hit rate;
- accepted-candidate hit rate;
- accepted energy reduction;
- energy reduction per CVX call (J/CVX);
- energy reduction per exact-CVX second (J/s);
- accepted move family.

These metrics are required before any same-time performance claim.

## Development matrix

The first run uses **development-only** scenarios that were already observed in
the v5 budget study:

- scenarios 85--88;
- algorithm seeds 100, 101, 102;
- K=50 and K=80;
- 15 s and 45 s nominal budgets respectively.

Methods:

1. `time_b_alns`;
2. `budget_v5` -- the validated legacy ESI policy;
3. `energy_guided_no_dual` -- H1/H2/H3 without dual modifiers;
4. `energy_guided_v6` -- H1/H2/H3 with frozen small dual modifiers.

This is **not** a hold-out validation and may be used to reject or simplify the
v6 design.

## Development gate

Before consuming fresh scenarios 93--100, v6 should satisfy all of the
following on the development matrix:

1. no strict-rate degradation versus budget_v5 at K=50;
2. no material strict-rate degradation at K=80;
3. positive scenario-level mean energy shift versus budget_v5 at at least one K
   and no large negative shift at the other;
4. exact ESI candidate evaluations are lower than or equal to the legacy ESI
   candidate count on average;
5. J/CVX and J/s are positive and materially above the legacy ESI values on runs
   with accepted moves;
6. the coupled route-offload family is actually selected or appears among the
   best exact candidates;
7. adding dual modifiers must show a repeatable benefit; otherwise the simpler
   no-dual design is preferred.

Only after passing this gate will parameters be frozen and scenarios **93--100**
be used for final unseen validation.
