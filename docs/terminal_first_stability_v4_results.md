# Terminal-First ESI v4 Hold-out Results

Branch: `experiment/terminal-first-stability-v4`

Formal hold-out workflow: `35721072968`

Frozen commit: `1295e72cf5f53e63ea5ea733008908173e7ec558`

Protocol: `docs/terminal_first_stability_v4_protocol.md`

## Execution completeness

- focused tests: success;
- full pytest suite: success;
- S77--84 seed-pair jobs: 48/48 success;
- aggregate: success;
- total Actions jobs: 50/50 success.

## K=50

| Method | Strict | Full-strict scenarios | Mean energy (J) | Mean seed CV | Mean runtime (s) | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|---:|
| Legacy B-ALNS | 24/24 | 8/8 | 166342.369 | 5.327% | 15.060 | 0.060 |
| Legacy ESI | 24/24 | 8/8 | 166289.803 | 5.196% | 13.617 | 0.082 |
| Time-scaled B-ALNS | 24/24 | 8/8 | 164319.155 | 8.334% | 15.057 | 0.057 |
| Continuous ESI v2 | 24/24 | 8/8 | 163958.008 | 7.792% | 13.736 | 0.000 |
| Terminal-First ESI v4 | **24/24** | **8/8** | **163879.887** | 7.714% | 13.774 | **0.000** |

v4 versus v2:

- common strict: 24/24;
- better/equal/worse: 3/21/0;
- mean run-level gain: +0.049%;
- mean scenario-level gain: +0.049%;
- positive/equal/negative scenarios: 2/6/0.

All 24 v4 runs returned `terminal_strict`.

## K=80

| Method | Strict | Full-strict scenarios | Mean energy (J) | Mean seed CV | Mean runtime (s) | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|---:|
| Legacy B-ALNS | 21/24 | 5/8 | 220827.013 | 3.335% | 46.078 | 1.078 |
| Legacy ESI | 21/24 | 5/8 | 220058.121 | 3.686% | 45.358 | 1.902 |
| Time-scaled B-ALNS | 20/24 | 4/8 | 222549.382 | 2.823% | 46.134 | 1.134 |
| Continuous ESI v2 | 20/24 | 4/8 | 224335.828 | 2.849% | 42.330 | 0.852 |
| Terminal-First ESI v4 | **20/24** | **4/8** | 224349.479 | **2.848%** | **42.190** | **0.814** |

v4 versus v2:

- common strict: 20/20;
- better/equal/worse: 1/18/1;
- mean run-level gain: -0.0068%;
- mean scenario-level gain: -0.0057%;
- positive/equal/negative scenarios: 1/6/1.

The difference is effectively negligible, but the pre-registered criterion
required a non-negative scenario-level mean, so v4 technically misses that
criterion.

Selection behavior:

- terminal strict: 20/24;
- terminal non-strict with no fallback: 4/24;
- strict incumbent available during the run: 13/24.

## Runtime behavior

v4 removes the v3 high-accuracy/structural recovery tail.

Compared with v3 K=80:

- mean overrun: 3.161 s -> **0.814 s**;
- maximum overrun: 32.051 s -> **11.997 s**.

The remaining maximum overrun is caused by an indivisible default Stage-1 solve,
not by a recovery solver.

## Promotion criteria

1. strict rate not lower than v2: pass;
2. fully-strict scenarios not lower than v2: pass;
3. non-negative scenario mean energy shift versus v2: **technical fail at
   K=80 (-0.0057%)**, effectively a tie;
4. K=80 seed CV no worse by more than 0.25 percentage points: pass;
5. mean overrun <=0.5 s / <=1.0 s: pass;
6. maximum overrun materially below v3: pass;
7. terminal-first used in the majority of strict runs: pass.

## Key remaining issue

The dominant weakness is no longer terminal selection. It is **budget
under-utilization**.

With a fixed 10% final certificate reserve:

- K=50 v4 mean method runtime is only 13.774 s of a 15 s budget;
- K=80 v4 mean method runtime is only 42.190 s of a 45 s budget.

Yet median terminal-certification cost is only:

- K=50: about 0.212 s;
- K=80: about 0.313 s.

Thus the fixed 10% reserve is conservative for the typical run and gives away
roughly 1--3 seconds that could be used for continued ALNS exploration.

The next version should keep terminal-first selection unchanged and change only
budget allocation:

1. reduce the fixed final-cert reserve to a small typical-case reserve;
2. optionally establish one strict checkpoint only when no strict archive has
   been created naturally;
3. spend the released time on the same continuous ALNS engine;
4. retain the strict archive solely as fallback.

Seeds 77--84 are now development evidence. The next unseen validation block is
**85--92**.
