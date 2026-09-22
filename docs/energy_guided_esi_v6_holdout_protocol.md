# Energy-Guided ESI v6 Final Hold-out Protocol

Branch: `experiment/energy-guided-esi-v6`

Parent line: validated budget-aware terminal policy v5 plus the frozen
energy-guided ESI candidate policy from development rounds S85--88 and S89--92.

Fresh validation scenarios: **S93--100**.

No parameter may be changed after observing this matrix and still be described
as unseen validation.

## Frozen algorithm

The search keeps the validated v5 infrastructure:

- one continuous ALNS engine;
- time-scaled RRT;
- budget-aware final certification reserve;
- terminal-first final selection;
- no high-accuracy terminal recovery;
- no ALNS restart.

Only the elite intensifier differs from v5.

### Energy hotspot ranking

For a strict Stage-1 elite solution, task priority uses:

- marginal route-flight energy;
- exact local-compute energy for local tasks;
- attributed exact contact/upload energy for offloaded tasks;
- deadline-dual modifier weight 0.10;
- UAV-cycle-dual modifier weight 0.05.

### Coupled structural candidates

For high-energy tasks, candidate construction can jointly change:

- UAV assignment;
- route position;
- execution mode;
- existing contact/batch reuse;
- new MEC contact insertion.

High-energy contacts can also generate batch-merge / removal opportunities.

### Cost-aware exact shortlist

Frozen candidate limits:

- hotspot tasks: 6;
- route options/task: 5;
- existing contacts/route option: 2;
- new contacts/MEC: 1;
- new-contact options/route: 3;
- contact hotspots: 2;
- proxy pool: 10;
- exact Stage-1 shortlist: at most 3;
- if positive proxy-gain candidates are insufficient, at most **one**
  high-hotspot exploratory fallback candidate;
- legacy structural fallback only when the new neighborhood is sparse.

## Compared methods

1. `time_b_alns`
   - B-ALNS with time-scaled RRT;
   - full common wall-clock budget.

2. `budget_v5`
   - validated budget-aware terminal-first continuous ESI;
   - legacy ESI structural shortlist.

3. `energy_guided_v6`
   - same v5 search/timing/terminal infrastructure;
   - only the elite intensifier is replaced by the frozen energy-guided
     coupled intensifier.

This isolates the value of the redesigned ESI rather than mixing it with
another budget-policy change.

## Hold-out matrix

- scenario seeds: **93--100** (8 independent instances);
- algorithm seeds: 100, 101, 102;
- K=50 and K=80;
- M=5, E=2;
- K=50 nominal budget: 15 s;
- K=80 nominal budget: 45 s.

Total: 48 seed-pair jobs.

## Primary endpoints

### Solution quality

For strict-common pairs:

[
G_{A\to B}
=
100\frac{E_A-E_B}{E_A}.
]

Report:

- run-level better/equal/worse;
- scenario-level mean paired gain;
- positive/equal/negative independent scenarios.

### Strict robustness

Report:

- strict run count;
- fully-strict independent scenarios;
- non-strict status categories.

### Exact-ESI efficiency

For each method with ESI:

- exact elite CVX calls;
- strict candidate hit rate;
- accepted candidate hit rate;
- direct accepted energy reduction;
- J per exact CVX call;
- J per exact-CVX second;
- accepted move families.

### Runtime

Report:

- total runtime;
- mean/max overrun;
- completed ALNS iterations.

## Promotion criteria

Energy-Guided ESI v6 is considered to establish a real same-time algorithmic
improvement only if all of the following hold.

1. Strict rate is not lower than `budget_v5` at either K.
2. Fully-strict scenario count is not lower than `budget_v5`.
3. Scenario-level mean paired energy gain versus `budget_v5` is non-negative
   at both K.
4. At K=80, scenario-level mean paired gain versus `time_b_alns` is at least
   **+0.25%**.
5. At K=50, v6 is not materially worse than `time_b_alns`:
   scenario-level mean gain must be >= -0.25%.
6. At K=80, positive scenarios versus Time-B must outnumber negative scenarios.
7. Mean exact elite CVX calls are not higher than budget v5 at either K.
8. At K=80, pooled/mean accepted-energy efficiency in J/CVX or J/s must improve
   over budget v5; at least one of the two must improve materially and neither
   may show a large regression.
9. Mean runtime overrun remains <=0.5 s at K=50 and <=1.0 s at K=80.
10. The energy-guided neighborhood must accept at least one genuinely
    energy-guided structural move on the full hold-out; otherwise any final
    difference is attributed to time-allocation noise rather than the proposed
    mechanism.

The +0.25% K=80 same-time threshold is intentionally stronger than merely
requiring a positive sign. Development observed approximately +0.85% and
+0.32% on two separate four-scenario blocks; the final hold-out should retain a
non-trivial fraction of that effect.

## Interpretation rule

Passing this protocol supports the narrow claim:

> energy-guided, coupled elite structural intensification uses expensive exact
> resource re-optimization more efficiently than the legacy ESI shortlist and
> yields a positive same-time energy shift over continued B-ALNS under high
> load.

It does not imply global optimality and does not convert non-strict solver
outcomes into mathematical infeasibility claims.
