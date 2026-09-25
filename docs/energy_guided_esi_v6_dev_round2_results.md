# Energy-Guided ESI v6 Development Round 2 Results

Workflow: `35732996091`

Execution commit: `8d752bfcac21bd5fe22874a5b937b01d043a7b86`

Development scenarios: S89--92.

This is development evidence only.

## Frozen change tested

Relative to development round 1, only one candidate-screening rule changed:

- positive proxy-gain candidates can still fill the exact shortlist;
- when fewer than three positive candidates exist, at most **one**
  high-hotspot exploratory fallback candidate is added.

All other energy-guided mechanisms are unchanged.

## K=50

| Method | Strict | Mean energy (J) | Mean seed CV | Mean runtime (s) | Mean elite exact CVX |
|---|---:|---:|---:|---:|---:|
| Time-B-ALNS | 12/12 | 146353.940 | 6.460% | 15.058 | - |
| budget v5 | 12/12 | 147870.869 | 5.714% | 14.755 | 2.08 |
| energy-guided no dual | 12/12 | 146888.684 | 6.536% | 14.750 | 2.25 |
| **energy-guided v6** | **12/12** | **145897.621** | 6.447% | 14.684 | 2.25 |

v6 versus budget v5:

- 5 better / 6 equal / 1 worse;
- scenario-level mean gain: **+1.273%**;
- positive/equal/negative scenarios: 4/0/0 at scenario mean level
  (all four scenario means are non-negative).

v6 versus Time-B-ALNS:

- 4 better / 7 equal / 1 worse;
- scenario-level mean gain: **+0.306%**.

Direct elite statistics:

- exact candidate checks: 27 total;
- accepted moves: 4;
- mean direct gain: 397.56 J/run;
- mean gain per exact CVX: 132.52 J/CVX;
- mean gain per exact second: 498.26 J/s;
- accepted/check hit rate: 11.1%.

Accepted move families include:

- energy-aware batch merge;
- energy-aware cross-route local relocation.

Unlike round 1, the stricter fallback does not suppress all useful K=50 ESI
moves.

## K=80

| Method | Strict | Full-strict scenarios | Mean strict energy (J) | Mean seed CV | Mean runtime (s) | Mean elite exact CVX |
|---|---:|---:|---:|---:|---:|---:|
| Time-B-ALNS | 9/12 | 2/4 | 215536.525 | 1.954% | 46.409 | - |
| budget v5 | 9/12 | 2/4 | 216252.150 | 2.018% | 47.304 | 2.58 |
| energy-guided no dual | 9/12 | 2/4 | 215243.832 | 2.219% | 47.451 | 1.75 |
| **energy-guided v6** | **9/12** | **2/4** | **214327.786** | 2.861% | 47.232 | **1.50** |

v6 versus budget v5:

- 3 better / 4 equal / 2 worse on 9 common-strict runs;
- scenario-level mean gain: **+0.945%**.

v6 versus Time-B-ALNS:

- 2 better / 5 equal / 2 worse;
- scenario-level mean gain: **+0.317%**.

Direct elite efficiency:

- mean exact candidate checks: 1.50/run;
- mean direct gain: 415.60 J/run;
- mean gain per exact CVX: 138.53 J/CVX;
- mean gain per exact second: **261.01 J/s**.

budget v5 comparison:

- mean exact candidate checks: 2.58/run;
- mean gain per exact second: 246.69 J/s.

Thus round 2 retains lower exact-CVX demand while preserving positive same-time
energy shifts.

## Dual-guidance decision

Development round 1:

- dual vs no-dual scenario-level mean gain:
  - K=50: +0.043%;
  - K=80: +0.402%.

Development round 2:

- K=50: **+0.635%**;
- K=80: **+0.334%**.

The dual version therefore has a positive scenario-level mean shift over the
no-dual version on both independent development blocks and both K values.

The dual terms remain deliberately small ranking modifiers:

- deadline dual weight = 0.10;
- cycle dual weight = 0.05.

They are now frozen for final validation.

## Development gate

1. K=50 strict rate not below budget v5: **pass**;
2. K=80 strict rate not materially below budget v5: **pass** (9/12 = 9/12);
3. positive energy shift versus budget v5 without large opposite-K loss:
   **pass**;
4. exact ESI candidate checks reduced / controlled: **pass**;
5. positive J/CVX and J/s on accepted-move regimes: **pass**;
6. coupled route/offload family demonstrated in round 1 and energy-aware
   relocation remains active in round 2: **pass**;
7. dual modifiers show repeatable positive mean effect across both development
   blocks: **pass**.

## Frozen v6 configuration for unseen validation

- hotspot task limit: 6;
- route options per task: 5;
- existing contacts per route option: 2;
- new contacts per MEC: 1;
- new-contact options per relocated route: 3;
- contact hotspot limit: 2;
- proxy pool limit: 10;
- exact shortlist maximum: 3;
- exploratory fallback maximum: **1**;
- deadline dual weight: **0.10**;
- cycle dual weight: **0.05**;
- one ESI round per continuous trigger;
- budget-aware terminal policy inherited unchanged from validated v5.

No v6 parameter may be changed after observing S93--100 and still call that
matrix unseen validation.
