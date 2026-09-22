# Terminal-Recovery ESI v3 Hold-out Results

Branch: `experiment/terminal-recovery-stability-v3`

Formal hold-out workflow: `35719137703`

Frozen execution tree: `63e599b198fe02688b60ea0a16c83c40c3e6fcac`

Protocol: `docs/terminal_recovery_stability_v3_protocol.md`

## Execution completeness

- focused tests: success;
- full pytest suite: success;
- S69--76 seed-pair jobs: 48/48 success;
- aggregate: success;
- total Actions jobs: 50/50 success.

## K=50

| Method | Strict | Full-strict scenarios | Mean energy (J) | Mean seed CV | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|
| Legacy B-ALNS | 24/24 | 8/8 | 158720.430 | 4.214% | 0.054 |
| Legacy ESI | 24/24 | 8/8 | 158879.399 | 4.296% | 0.044 |
| Time-scaled B-ALNS | 24/24 | 8/8 | 157485.848 | 5.094% | 0.078 |
| Continuous ESI v2 | 24/24 | 8/8 | 157607.037 | 5.005% | 0.000 |
| Terminal-Recovery ESI v3 | 24/24 | 8/8 | **157458.237** | 4.943% | 0.080 |

v3 versus v2 on 24 common-strict pairs:

- better/equal/worse = 6/16/2;
- mean run-level gain = +0.087%;
- mean scenario-level gain = +0.087%;
- positive/equal/negative scenarios = 4/3/1.

Terminal selection:

- terminal already strict: 23/24;
- high-accuracy recertification attempted: 1;
- high-accuracy recertification succeeded: 1;
- structural recovery attempted: 0;
- strict-archive fallback used: 0.

At K=50, terminal-first selection works and recovery cost is usually zero.

## K=80

| Method | Strict | Full-strict scenarios | Mean energy (J) | Mean seed CV | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|
| Legacy B-ALNS | 19/24 | 5/8 | 217567.948 | **4.456%** | 0.905 |
| Legacy ESI | 18/24 | 5/8 | 217781.028 | 5.616% | 1.447 |
| Time-scaled B-ALNS | 19/24 | 5/8 | 218585.592 | 4.708% | 0.759 |
| Continuous ESI v2 | **20/24** | **6/8** | 219293.799 | 4.485% | **0.454** |
| Terminal-Recovery ESI v3 | **20/24** | **6/8** | **218170.869** | 5.602% | 3.161 |

v3 versus v2 on all 20 common-strict pairs:

- better/equal/worse = 5/12/3;
- mean run-level gain = +0.512%;
- mean scenario-level gain = +0.437%;
- positive/equal/negative scenarios = 4/3/1.

Thus terminal-first selection recovers part of the energy-quality loss observed
in v2 without reducing strict coverage.

However, the recovery layer itself fails its purpose:

- terminal already strict: 20/24;
- high-accuracy recertification attempted: 4;
- high-accuracy recertification succeeded: **0/4**;
- structural recovery attempted: 2;
- structural recovery succeeded: **0/2**;
- strict-archive fallback used: 0;
- remaining 4 runs stayed non-strict.

Recovery runtime on K=80:

- mean: 2.968 s;
- median: 0 s;
- maximum: 26.760 s.

Total method overrun:

- mean: **3.161 s**;
- maximum: **32.051 s**.

One observed K=80 run reached about 73 s against a 45 s nominal budget and
still ended `optimal_inaccurate`.

## Decision

**Do not promote v3.**

Promotion criteria:

1. strict rate not lower than v2: pass;
2. full-strict scenarios not lower than v2: pass;
3. no negative scenario-level energy shift vs v2: pass on the mean
   (+0.437% at K=80);
4. K=80 seed CV comparable to v2: **fail** (4.485% -> 5.602%);
5. terminal-first policy actually used: pass;
6. mean runtime overrun <=1 s at K=80: **fail** (3.161 s);
7. secondary recovery explains strict gains: **fail**; high-accuracy recovery
   is 0/4 and structural recovery is 0/2 at K=80.

## Mechanistic conclusion

The useful part of v3 is **terminal-first selection**, not high-accuracy
recertification.

On this hold-out, 44 of 48 runs already had a strict terminal solution and
needed no recovery. For K=80, every expensive high-accuracy recovery attempt
failed to convert a non-strict terminal solution into a strict one.

Therefore the next version should:

1. keep the continuous single-engine search;
2. default-certify the terminal screened-best candidate;
3. return it immediately when strict;
4. otherwise fall back to the existing strict archive when available;
5. remove high-accuracy SCS recovery and terminal structural recovery from the
   default path.

This preserves the energy-quality benefit of terminal-first selection while
removing the demonstrated long-tail cost.

Seeds 69--76 are now development evidence. The next unseen validation block is
**77--84**.
