# v26 protocol: physical feasibility + task-level QoS

**Status: experimental, independent from v25.** The archived v25 results in
`results/` and figures under `figures/` remain unchanged. No v26 figures may
be derived from archived strict-acceptance records.

## Research question (paper Section III)

Under route, MEC coverage, communication/upload, MEC bandwidth and CPU capacity,
UAV return-cycle, UAV CPU bounds and UAV battery constraints, compare seven
heuristics' **task success count, normalized lateness, UAV energy and route distance**.
The individual deadline and aggregate mean-delay budget are *not* conditions for
admitting a physical solution. A task is on time iff its reconstructed earliest
completion time satisfies `c_i <= release_i + deadline_i`.

The discrete heuristic objective ranks **physically admissible candidates first**,
then lexicographically by `(-on_time_count, sum(max(0, delay/deadline - 1)),
energy_j, route_distance_m)`. SA/PSO and ALNS use a documented bounded scalar
encoding of this rank. In the continuous subproblem, lateness/latency are
optimized by a convex weighted surrogate, not falsely described as an exact
mixed-integer maximum-success solver. Stage-2 additionally protects tasks
already on time and aggregate normalized tardiness.

## Task admission (Section IV)

Each of the seven algorithms first attempts its full candidate. If the solver
and/or physical certificate rejects it, the common admission algorithm removes
the task ranked most difficult by: deadline exceedance ratio, delay ratio,
marginal route detour, MEC load pressure, then ascending task identifier.
After **each** removal it drops orphaned contact visits, rebuilds event
timelines and solves/revalidates resources. A numerical CVX failure may use a
deterministic equal-share resource certificate **only if both independent
physical residual audits pass**. Such runs are labeled `constructive_verified`
and not represented as optimal continuous solves.

If all nonempty subsets fail, a validated `depot -> depot` mission is produced;
its zero flight/compute/communication energy is genuinely measured by the
model rather than an imputation for missing experiments. All removed tasks have
explicit `unserved` outcomes. The rank is shared across methods, but is a
deterministic repair **of each method's candidate**, not a common new search
heuristic.

## Dataset and indicators (Section V)

One row per planned algorithm/method-seed run; deterministic GR-MR/FTR-NM are
recorded once per scenario, other five methods three times. The 6 x 8 scenario
matrix contains **816 planned rows**. Each row records the compulsory fields:
`physical_feasible`, `served_tasks`, `success_rate`,
`mean_delay_all`, `mean_delay_success`, `p95_delay_all`,
`deadline_violation_rate`, `stage1_energy`, `stage2_energy`,
`route_distance`, `mec_cpu_utilization`, `runtime`,
`strict_all_tasks_success`.

Definitions:
- `success_rate`: on-time completed / planned K, including unserved tasks in denominator.
- `deadline_violation_rate`: **served but late** / K.
- `unserved_rate`: physically rejected / K. Together with success rate they sum to one.
- `mean_delay_all` and `p95_delay_all`: served completion delay measured
  from the resource timeline, unserved items assigned **cycle-end censoring
  value** solely for plotting. These are censored-surrogate summaries, **not**
  measured mean times to completion for tasks never completed. Retain the
  `task_outcomes` missing actual delays for unserved tasks.
- `mean_delay_success`: measured only on successful tasks; `null` when
  there are none, with an explicit undefined status. Do not replace with zero.
- `total_energy`: physical energy from accepted Stage-2 if available,
  otherwise from verified Stage-1 / constructed physical allocation. Stage-2
  energy is `null` if unavailable; not replaced with Stage-1 and not claimed
  as a Stage-2 optimum.
- `energy_per_successful_task`: total_energy/on-time count, undefined as null
  if no task succeeds.
- `mec_cpu_utilization`: mean CPU allocation / MEC capacity over *all* MECs.
  This is **allocation fraction**, not time-averaged observed hardware CPU.
- `strict_all_tasks_success`: every one of original K tasks served by
  the solution and on time; reported separately from physical feasibility.

For Table III report planned, physical-feasible and observed task-success
rates, with scene-equal averaging after seed-level averaging. Do not select
the intersection of methods with all tasks on time. The original strict
acceptance rate remains an auxiliary statistic.

Figure captions should state: *All independently physically feasible planned
runs; task success is assessed per original task, not restricted to runs with
100% of tasks on time. All-task delays use an explicit cycle-end right-censoring
surrogate for unserved tasks.*

## Reproducibility

New outputs are written **only** under `outputs/task_qos/`. No command here
writes to `results/` or `figures/`.

Pilot:
```bash
python experiments/run_seven_methods.py --qos-mode task-level --phase pilot --tasks 30 --scenario 45 --output outputs/task_qos/pilot/K30_S45.json
python experiments/run_seven_methods.py --qos-mode task-level --phase pilot --tasks 50 --scenario 45 --output outputs/task_qos/pilot/K50_S45.json
python experiments/run_seven_methods.py --qos-mode task-level --phase pilot --tasks 80 --scenario 45 --output outputs/task_qos/pilot/K80_S45.json
python experiments/aggregate_task_qos.py --input-root outputs/task_qos/pilot --output-dir outputs/task_qos/aggregate
python experiments/plot_task_qos.py --summary outputs/task_qos/aggregate/task_qos_summary.csv --output-dir outputs/task_qos/figures
```

Formal runs use `--phase formal` with all frozen sizes and scenario seeds in
the original v25 matrix. After pilot approval re-run
`run_extension.py --qos-mode task-level` for contact, bandwidth, GIS;
`run_multiscale_ablation.py --qos-mode task-level` and
`run_budget_check.py --qos-mode task-level` under their separate **new**
output directories. Existing v25 numerical claims must not be transplanted
into v26's title, comparison or conclusion until all measurements finish.

## Proposed conclusion language (not a result claim)

The changed formulation evaluates the joint trade-off among on-time task
completion, delay, and UAV energy **under independently checked physical
constraints**. It does not claim all tasks meet deadlines; the actual
performance and energy trade-off must be determined from the re-run v26 data.
