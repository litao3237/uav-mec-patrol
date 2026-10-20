# M0: frozen task QoS comparison and numeric model correction

This is a separate M0 research run, created from
`experiment/task-qos-physical-v26` without altering `develop` or historical
`results/` and `figures/`. The original 816 v26 records **cannot** be mixed
with M0 results.

## Common ordering

Physical admissibility is a hard gate. Within physical solutions, use the
**reconstructed earliest** completion times and order lexicographically:
1. larger number of on-time tasks;
2. lower sum of normalized positive lateness;
3. lower UAV energy in real joules;
4. shorter route in physical meters.

Task classification uses the single frozen `ON_TIME_TOL_S = 1e-6` for
numeric robustness. This is not a relaxation of radio, route, CPU, battery,
coverage or return-cycle constraints. On-time classification is used in
`task_metrics`, `ProxyScore`, Stage-2 checks and CVX elite oracle.

The ALNS/SA/PSO libraries require scalar objective values; their score is a
**monotone, bounded surrogate** normalized using each instance's UAV energy
budgets and maximal flight distance over the cycle. The scalar **cannot**
mathematically preserve strict priority for arbitrarily tiny real lateness
differences. Exact tuple comparison is enforced for the elite CVX candidates,
and all final physical/QoS metrics are recomputed independently.

## Continuous resource recourse

Stage-1A: solve the existing convex latency/lateness surrogate (it does not
exactly maximize on-time cardinality, which contains integer decisions).
Stage-1B: run a separate convex **Joule minimization** subject to all physical
constraints, preservation of Stage-1A on-time task deadlines, and a frozen
total normalized lateness guard. Accept the new numerical solution only if its
saved and reconstructed physical audits pass and its measured QoS tuple does
not regress. On failure, retain Stage-1A with an explicit reason; never label
the failed refinement optimal.

Stage-2: minimize MEC CPU allocation with the preserved Stage-1 energy guard
and the same on-time/normalized-lateness tolerance, using physical
reconstruction for the baseline. Stage-2 energy is null on failure.

The reported Stage-1 Joules represent a **QoS-constrained** result, not an
unconstrained energy optimum and not a mathematical proof of global
maximum-success solution. Labels in experiments must keep that distinction.

## Required evaluation

- Small deterministic unit tests: microsecond deadline classification;
  exact success priority; actual-Joule elite improvement, including an
  adverse scalar counterexample; independent physical residuals.
- Frozen 30/50/80-task pilots: 21 planned seven-method rows, source fingerprints,
  no missing records, task outcomes consistent and all original hard
  physical constraints independently replayable.
- Budget fairness: compare against v26 only under matched settings, disclose
  any additional Stage-1B runtime rather than hiding it.
- Do **not** launch a new 816-run matrix until M0 pilot is accepted and the
  optimization benefit/cost trade-off is independently assessed.
