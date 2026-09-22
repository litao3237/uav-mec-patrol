# Budget Utilization v5 Hold-out Results

Branch: `experiment/budget-utilization-v5`

Formal hold-out workflow: `35723676331`

Frozen execution commit: `64757f34ee3da8c7f2176be435a52b6ee4f2e7fa`

Protocol: `docs/budget_utilization_v5_protocol.md`

## Execution completeness

- focused ALNS tests: success;
- full pytest suite: success;
- S85--92 seed-pair jobs: 48/48 success;
- aggregate job: success;
- total Actions jobs: 50/50 success;
- no failed jobs.

The experiment compares only budget-allocation policies. Structural operators,
continuous ESI logic, and terminal-first selection are unchanged.

## K=50

| Method | Strict | Full-strict scenarios | Mean strict energy (J) | Mean seed CV | Mean runtime (s) | Budget utilization | Mean overrun (s) | Mean unused budget (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Time-B-ALNS | 24/24 | 8/8 | **151369.627** | 4.773% | 15.084 | 100.56% | 0.084 | 0.000 |
| Terminal fixed 10% | 24/24 | 8/8 | 153093.161 | **4.129%** | 14.105 | 94.03% | 0.161 | 1.056 |
| Terminal fixed 3% | 24/24 | 8/8 | 151989.221 | 4.932% | 15.000 | 100.00% | 0.209 | 0.208 |
| **Budget-aware v5** | **24/24** | **8/8** | **151399.251** | 5.004% | 14.860 | **99.07%** | **0.150** | 0.290 |

v5 versus fixed 10%:

- common strict: 24/24;
- better/equal/worse: 6/14/4;
- mean scenario-level energy gain: **+1.070%**;
- positive/equal/negative scenarios: 4/2/2;
- eight-scenario bootstrap 95% interval for mean gain:
  approximately **[-0.17%, +2.67%]**.

v5 versus fixed 3%:

- better/equal/worse: 5/16/3;
- mean scenario-level gain: **+0.388%**;
- positive/equal/negative scenarios: 4/2/2;
- bootstrap 95% interval: approximately **[-0.03%, +0.95%]**.

v5 versus Time-B-ALNS:

- better/equal/worse: 3/18/3;
- mean scenario-level shift: **-0.012%**;
- operationally a tie.

Thus at K=50 the compact reserve recovers almost all of the search time lost by
the 10% policy. v5 is essentially tied with the full-budget time-scaled B-ALNS
while retaining terminal-first strict certification.

## K=80

| Method | Strict | Full-strict scenarios | Mean strict energy (J) | Mean seed CV | Mean runtime (s) | Budget utilization | Mean overrun (s) | Max overrun (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Time-B-ALNS | 20/24 | 4/8 | 221750.512 | **3.327%** | 45.825 | 101.83% | 0.825 | 5.944 |
| Terminal fixed 10% | 17/24 | 4/8 | 224436.281 | 3.613% | 42.880 | 95.29% | 1.097 | 10.598 |
| Terminal fixed 3% | 18/24 | 4/8 | 222606.746 | 4.441% | 45.987 | 102.19% | 1.570 | 17.856 |
| **Budget-aware v5** | **19/24** | **4/8** | **221733.774** | 4.476% | **45.011** | **100.02%** | **0.733** | **8.157** |

v5 versus fixed 10% on 17 common-strict pairs:

- better/equal/worse: **8/9/0**;
- mean scenario-level energy gain: **+1.029%**;
- positive/equal/negative scenarios: 5/3/0;
- bootstrap 95% interval: approximately **[+0.23%, +1.94%]**.

v5 versus fixed 3% on 18 common-strict pairs:

- better/equal/worse: **6/12/0**;
- mean scenario-level energy gain: **+0.716%**;
- positive/equal/negative scenarios: 4/4/0;
- bootstrap 95% interval: approximately **[+0.11%, +1.47%]**.

v5 versus Time-B-ALNS on 19 common-strict pairs:

- better/equal/worse: 4/7/8;
- mean scenario-level shift: **+0.016%**;
- bootstrap 95% interval crosses zero, approximately
  **[-1.12%, +1.38%]**.

Thus the v5 terminal-first method reaches essentially the same same-time energy
quality as full-budget Time-B-ALNS while retaining a dedicated strict
certification path.

## Budget-adaptation behavior

### K=50

- initial reserve: 0.45 s;
- reserve expanded in 13/24 runs;
- mean final reserve: 0.543 s;
- median final reserve: 0.489 s;
- maximum final reserve: 0.733 s;
- terminal strict: 24/24.

The expansions correspond to observed in-search certification costs around
0.24--0.37 s. The adaptive rule therefore increases reserve only when the
observed sample requires it.

### K=80

- initial reserve: 1.35 s;
- reserve expanded in only 2/24 runs;
- mean final reserve: 1.537 s;
- median final reserve: 1.35 s;
- maximum final reserve: 3.60 s (the frozen 8% cap);
- terminal strict: 19/24;
- terminal non-strict without fallback: 5/24.

The two K=80 expansions were exactly the slow-certification cases:

1. S90/A101 observed an in-search certificate taking about 9.57 s, so reserve
   expanded to the 3.60 s cap;
2. S91/A100 observed about 5.09 s, again expanding to the cap.

In these two cases the adaptive policy reduced runtime exposure relative to the
fixed-3% arm. It did not convert the terminal solutions to strict optima, which
shows that the reserve policy is controlling runtime risk rather than fabricating
feasibility.

## Fixed 3% versus adaptive reserve

The fixed-3% arm establishes that most of the quality improvement comes from
releasing the overly conservative 10% reserve.

However, the adaptive rule adds measurable value, especially at K=80:

- strict: 18/24 -> **19/24**;
- mean energy: 222606.746 J -> **221733.774 J**;
- mean overrun: 1.570 s -> **0.733 s**;
- max overrun: 17.856 s -> **8.157 s**;
- scenario-level paired v5 gain: **+0.716%**;
- no common-strict scenario has a negative scenario-level mean.

Therefore the dynamic rule is justified over simply hard-coding a 3% reserve.

## Promotion-criterion audit

1. strict rate not below fixed 10%: **pass**;
2. fully-strict scenario count not below fixed 10%: **pass**;
3. non-negative scenario-level energy shift versus fixed 10%:
   **pass at both K**;
4. mean runtime utilization >=96%:
   - K=50: **99.07%**;
   - K=80: **100.02%**;
   **pass**;
5. mean overrun <=0.5 s / <=1.0 s:
   - K=50: **0.150 s**;
   - K=80: **0.733 s**;
   **pass**;
6. max overrun materially below v3 32.05 s tail:
   - v5 K=80 max: **8.157 s**;
   **pass**;
7. strict rate not below fixed 3%:
   - K=50: 24/24 = 24/24;
   - K=80: 19/24 > 18/24;
   **pass**;
8. energy not worse than fixed 3% by >0.25%:
   v5 is better at both K;
   **pass**;
9. reserve expansion tied to observed slow certification:
   **pass**.

## Decision

**Budget-aware terminal-first ESI v5 passes all pre-registered promotion
criteria.**

This is the first stability/budget variant in the v1--v5 sequence to satisfy
the complete frozen criterion set.

The main mechanism is now clear:

- the old 10% reserve materially under-utilizes the search budget;
- an unconditional 3% reserve recovers quality but exposes larger solver
  overrun tails;
- the adaptive 3% -> observed-cost-based reserve keeps the quality benefit while
  cutting runtime risk.

The recommended experimental candidate is therefore:

> continuous ESI + terminal-first selection + budget-aware final-certification
> reserve.

No further reserve tuning should be performed on S85--92. These seeds are now
development evidence.
