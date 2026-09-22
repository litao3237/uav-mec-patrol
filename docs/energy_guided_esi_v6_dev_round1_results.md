# Energy-Guided ESI v6 Development Round 1 Results

Workflow: `35731914277`

Execution commit: `04a6f9a820ca6069c2bc3e9633d6ce38df85f688`

Development scenarios: S85--88.

This is development evidence only.

## Summary

### K=50

| Method | Strict | Mean energy (J) | Mean CV | Mean runtime (s) | Mean exact elite CVX |
|---|---:|---:|---:|---:|---:|
| Time-B-ALNS | 12/12 | 155703.775 | 4.307% | 15.122 | - |
| budget v5 | 12/12 | 155568.427 | 4.214% | 14.689 | 4.58 |
| energy-guided no dual | 12/12 | 155604.035 | 4.224% | 14.630 | 2.17 |
| energy-guided v6 | 12/12 | **155530.485** | **4.186%** | 14.671 | **2.42** |

v6 versus budget v5:

- 1 better / 8 equal / 3 worse at run level;
- scenario-level mean gain: +0.022%;
- all methods strict 12/12.

However, direct ESI evidence is weak at K=50:

- budget v5: 55 exact elite candidate checks, 1 accepted move, 87 J total direct gain;
- energy-guided v6: 29 exact candidate checks, **0 accepted moves**;
- energy-guided no-dual: 26 exact checks, **0 accepted moves**.

Thus K=50 final quality is mainly explained by lower elite overhead and more
remaining generic ALNS exploration, not by accepted energy-guided moves.

## K=80

| Method | Strict | Mean strict energy (J) | Mean runtime (s) | Mean exact elite CVX |
|---|---:|---:|---:|---:|
| Time-B-ALNS | 9/12 | 226561.329 | 45.140 | - |
| budget v5 | 8/12 | 228097.201 | 46.240 | 2.58 |
| energy-guided no dual | 9/12 | 225370.038 | 45.076 | 1.42 |
| energy-guided v6 | **9/12** | **224955.663** | **44.915** | **1.42** |

v6 versus budget v5 on 8 common-strict pairs:

- 4 better / 4 equal / 0 worse;
- scenario-level mean gain: +0.131%.

v6 versus Time-B-ALNS on 9 common-strict pairs:

- 5 better / 3 equal / 1 worse;
- scenario-level mean gain: **+0.853%**.

This is the first same-time development matrix in which the redesigned ESI
shows a non-trivial positive shift versus continued B-ALNS.

## Exact-efficiency evidence

Pooled K=80 direct elite statistics:

### budget v5

- exact candidate checks: 31;
- accepted moves: 4;
- accepted direct energy reduction: 6990.08 J;
- pooled direct gain per exact check: **225.5 J/CVX**;
- pooled direct gain per elite-phase second: **413.8 J/s**;
- accepted/check hit rate: 12.9%.

### energy-guided v6

- exact candidate checks: 17;
- accepted moves: 5;
- accepted direct energy reduction: 8392.54 J;
- pooled direct gain per exact check: **493.7 J/CVX**;
- pooled direct gain per elite-phase second: **871.4 J/s**;
- accepted/check hit rate: **27.8%**.

Thus v6 approximately doubles both exact-call efficiency and elite-phase
energy reduction per second on the K=80 development set.

## Accepted v6 move families at K=80

Five exact improvements were accepted:

1. `energy_route_local::S76->U3@16`: +2421.11 J;
2. `energy_batch_merge::G_U4_2->G_U4_3`: +106.20 J;
3. `energy_route_offload_new::S34->U2@17::E1_C@18`: **+1780.22 J**;
4. `energy_route_local::S18->U5@11`: +3007.78 J;
5. `energy_batch_merge::G_U5_3->G_U5_1`: +1077.23 J.

The explicit coupled Route--Offload--New-Contact move is therefore not merely
generated; it produced a strict accepted improvement.

## Dual-guidance finding

The no-dual and dual variants accepted the same five direct K=80 moves and
obtained the same total direct elite gain. The dual variant has better final
same-time energy in two runs, but this is mediated through subsequent
time-bounded ALNS trajectory differences rather than a different accepted ESI
move set.

Therefore dual modifiers are not yet justified as a core mechanism.

## Development change for round 2

The first-round screen fills all exact slots with high-hotspot candidates when
fewer than k candidates have non-negative proxy gain. At K=50 this causes exact
CVX spending with zero accepted improvement.

Round 2 will therefore test a stricter exploration fallback:

- positive proxy-gain candidates remain eligible for all exact slots;
- when positive candidates are insufficient, at most **one** high-hotspot
  exploratory candidate may be added;
- the exact shortlist maximum remains three;
- all other v6 mechanisms are unchanged.

Development scenarios S89--92, already observed by the v5 budget study, will be
used. Fresh S93--100 remain untouched.
