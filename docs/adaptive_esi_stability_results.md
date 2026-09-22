# Adaptive ESI Stability Validation Results

Branch: `experiment/adaptive-esi-stability`

Formal validation workflow run: `35713742080`

Validation commit: `00944f833a4ff5e0106bf5a8bd4c4ed4f7d07092`

Protocol: `docs/adaptive_esi_stability_protocol.md`

## Execution status

- focused unit tests: success;
- 48/48 unseen-scenario seed-pair jobs: success;
- aggregate job: success;
- total GitHub Actions jobs: 50/50 success;
- scenario seeds: 53--60;
- algorithm seeds: 100/101/102;
- K: 50 and 80.

No result from seeds 45--52 was used to tune the experimental policy before
this run.

## Methods

- `legacy_b_alns`: current B-ALNS with legacy iteration-scaled RRT;
- `legacy_esi`: current fixed-split ESI;
- `time_b_alns`: B-ALNS with time-scaled RRT only;
- `adaptive_esi`: time-scaled RRT + strict incumbent archive +
  stagnation-triggered ESI.

## K=50 summary

| Method | Strict | Fully-strict scenarios | Mean energy (J) | Mean within-scenario CV | Mean runtime (s) | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|---:|
| legacy B-ALNS | 23/24 | 7/8 | 158590.776 | 4.311% | 15.241 | 0.241 |
| legacy ESI | **24/24** | **8/8** | 158902.368 | 4.143% | 14.023 | 0.107 |
| time-scaled B-ALNS | 23/24 | 7/8 | **158477.614** | **4.086%** | 15.238 | 0.238 |
| adaptive ESI | 23/24 | 7/8 | 158623.560 | 4.232% | 15.626 | 0.629 |

Adaptive ESI versus legacy ESI on common-strict pairs:

- better/equal/worse = 12/6/5;
- mean run-level gain = -0.029%;
- mean scenario-level gain = -0.258%;
- positive/negative scenarios = 6/2;
- worst scenario-level loss = -5.523%.

Adaptive ESI versus time-scaled B-ALNS:

- better/equal/worse = 6/10/7;
- mean scenario-level gain = -0.118%;
- positive/equal/negative scenarios = 3/2/3.

Time-scaled B-ALNS has a slightly lower mean energy and lower mean
within-scenario CV than legacy B-ALNS at K=50, but it does not improve strict
coverage.

## K=80 summary

| Method | Strict | Fully-strict scenarios | Mean energy (J) | Mean within-scenario CV | Mean runtime (s) | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|---:|
| legacy B-ALNS | **22/24** | **6/8** | 215254.546 | 2.881% | 45.656 | 0.656 |
| legacy ESI | **22/24** | **6/8** | **215198.902** | **2.731%** | 44.460 | 0.805 |
| time-scaled B-ALNS | 21/24 | 5/8 | 215918.790 | 2.868% | 45.254 | **0.254** |
| adaptive ESI | **22/24** | **6/8** | 215259.394 | 3.087% | 47.123 | 2.123 |

Adaptive ESI versus legacy ESI:

- better/equal/worse = 9/4/9;
- mean run-level gain = -0.078%;
- mean scenario-level gain = -0.079%;
- positive/negative scenarios = 5/3;
- worst scenario-level loss = -2.181%.

Adaptive ESI versus time-scaled B-ALNS:

- better/equal/worse = 10/5/6 on 21 common-strict pairs;
- mean scenario-level gain = -0.082%;
- positive/negative scenarios = 5/3.

Thus adaptive ESI restores the strict count lost by time-scaled B-ALNS, but it
does not reduce within-scenario seed variation and does not improve mean
same-budget quality.

## ESI trigger efficiency

Adaptive ESI diagnostics:

| K | Mean triggers/run | Mean improving triggers/run | Strict archive success |
|---:|---:|---:|---:|
| 50 | 1.042 | 0.208 | 23/24 |
| 80 | 0.833 | 0.500 | 22/24 |

At K=50, most stagnation-triggered ESI calls do not produce an accepted strict
improvement. The CVX/oracle cost therefore consumes budget without a compensating
quality gain in many runs.

At K=80, ESI improvements are more frequent, but restarting ALNS after a
stagnation phase plus strict oracle checks still produces mixed final quality.

## Runtime stability

The adaptive version has materially worse budget overrun:

- K=50 mean overrun 0.629 s, maximum 8.391 s;
- K=80 mean overrun 2.123 s, maximum 10.951 s.

This fails the pre-registered requirement that runtime overrun remain small.

The primary causes are indivisible screened-CVX calls, phase-boundary strict
verification, and elite oracle calls close to the nominal deadline.

## Decision

**Do not merge this adaptive version into develop.**

The pre-registered stability criteria are not met:

1. K=50 strict coverage is lower than legacy ESI (23/24 vs 24/24);
2. fully-strict scenario count is lower at K=50 (7/8 vs 8/8);
3. within-scenario CV does not consistently decrease;
4. scenario-level negative outcomes remain and include material losses;
5. adaptive ESI is not systematically better than time-scaled B-ALNS;
6. runtime overrun is substantially worse.

## What is worth retaining for further research

### Time-scaled RRT

This is the cleanest isolated mechanism:

- K=50: slightly lower mean energy and lower mean CV than legacy B-ALNS;
- K=80: strict coverage drops from 22/24 to 21/24.

It should remain experimental until a strict-feasibility safeguard can be added
without repeated expensive phase-boundary CVX calls.

### Strict incumbent idea

The concept is useful, especially because one K=80 run had an
`optimal_inaccurate` time-scaled terminal solution while adaptive ESI returned
a strict incumbent. However, checking strictness at every phase boundary is too
expensive and creates large deadline overruns.

A future version should reduce certification frequency, reserve explicit oracle
time, or certify only materially improved screened incumbents.

### Stagnation-triggered ESI

The current implementation restarts ALNS after each ESI burst. That resets
roulette-wheel adaptation and the RRT schedule. The unseen-scenario results do
not justify this restart-based design.

If this direction is revisited, ESI should be integrated into a continuous ALNS
search state (preserving operator weights and acceptance history) rather than
implemented as repeated fresh ALNS phases.

## Hold-out implication

Seeds 53--60 have now been observed and must be treated as development data for
any further adaptive-policy change.

If a second stability design is implemented, final validation must use a fresh
unseen block such as **61--68** and must not tune again after observing those
results.
