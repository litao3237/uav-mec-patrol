# Continuous ESI Stability v2 Results

Branch: `experiment/continuous-esi-stability-v2`

Formal hold-out workflow: `35716006343`

Validation commit: `967055d676b1d0aa7cce1698d998650d9bed6bca`

Protocol: `docs/continuous_esi_stability_v2_protocol.md`

## Execution status

- focused ALNS tests: success;
- full pytest suite: success;
- hold-out seed-pair jobs: 48/48 success;
- aggregate job: success;
- total GitHub Actions jobs: 50/50 success;
- hold-out scenarios: seeds 61--68;
- algorithm repetitions: 100/101/102;
- K: 50 and 80.

The hold-out matrix is complete and must not be reused for further parameter
tuning while still being described as unseen validation.

## K=50

| Method | Strict | Fully-strict scenarios | Mean energy (J) | Mean within-scenario CV | Mean runtime (s) | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|---:|
| legacy B-ALNS | 24/24 | 8/8 | 158818.197 | 4.588% | 15.164 | 0.164 |
| legacy ESI | 24/24 | 8/8 | 159784.652 | 4.978% | 14.860 | 0.512 |
| time-scaled B-ALNS | 24/24 | 8/8 | **156597.567** | 4.004% | 15.166 | 0.166 |
| continuous ESI | 24/24 | 8/8 | 157197.256 | **3.833%** | 14.163 | 0.271 |

Continuous ESI versus legacy ESI:

- common-strict: 24/24;
- better/equal/worse: 13/6/5;
- mean run-level gain: +1.492%;
- mean scenario-level gain: +1.492%;
- positive/negative independent scenarios: 7/1.

Continuous ESI versus legacy B-ALNS:

- better/equal/worse: 12/6/6;
- mean scenario-level gain: +0.917%;
- positive/negative scenarios: 6/2.

Continuous ESI versus time-scaled B-ALNS:

- better/equal/worse: 6/8/10;
- mean scenario-level gain: **-0.386%**;
- positive/negative scenarios: 3/5.

Thus continuous ESI improves seed CV and outperforms legacy ESI on this K=50
hold-out, but time-scaled B-ALNS remains the strongest same-time mean-energy
variant.

## K=80

| Method | Strict | Fully-strict scenarios | Mean energy (J) | Mean within-scenario CV | Mean runtime (s) | Mean overrun (s) |
|---|---:|---:|---:|---:|---:|---:|
| legacy B-ALNS | 18/24 | 5/8 | 214590.196 | 3.124% | 45.347 | 0.347 |
| legacy ESI | 17/24 | 5/8 | **211606.925** | 3.467% | 43.536 | 1.197 |
| time-scaled B-ALNS | 17/24 | 5/8 | 212429.834 | **3.039%** | 45.721 | 0.721 |
| continuous ESI | **20/24** | **6/8** | 216016.563 | 4.201% | 41.688 | **0.313** |

Continuous ESI clearly improves strict-certification robustness:

- strict count: 20/24 versus 17/24 for legacy ESI;
- fully-strict scenarios: 6/8 versus 5/8;
- runtime overrun: 0.313 s mean versus 1.197 s for legacy ESI and 2.123 s
  observed for adaptive ESI v1.

However, solution quality is worse.

Continuous ESI versus legacy ESI on the 17 common-strict pairs:

- better/equal/worse: 2/3/12;
- mean run-level gain: -1.320%;
- mean scenario-level gain: -1.074%;
- positive/negative independent scenarios: 1/6.

Continuous ESI versus time-scaled B-ALNS:

- better/equal/worse: 4/4/9;
- mean scenario-level gain: -0.704%;
- positive/equal/negative scenarios: 2/1/4.

Continuous ESI versus legacy B-ALNS:

- better/equal/worse: 7/3/7;
- mean scenario-level gain: -0.677%.

Thus the strict archive is doing what it was designed to do: it returns more
strictly certified solutions, but often returns an earlier conservative
incumbent instead of the lower-energy terminal screened solution. The result is
higher certification robustness at the expense of energy quality.

## Continuous-controller diagnostics

### K=50

- mean ESI triggers/run: 1.208;
- mean strict ESI improvements/run: 0.333;
- mean live ALNS reinjections/run: 0.292;
- mean ESI runtime: 1.146 s;
- mean certification runtime: 0.466 s;
- strict archive success: 24/24;
- final certification performed: 14/24.

### K=80

- mean ESI triggers/run: 0.875;
- mean strict ESI improvements/run: 0.333;
- mean live ALNS reinjections/run: 0.333;
- mean ESI runtime: 1.307 s;
- mean certification runtime: 0.926 s;
- strict archive success: 20/24;
- final certification performed: 20/24.

One K=80 certification call remained numerically expensive, with the maximum
certification runtime around 10.84 s. The explicit reserve reduces average
overrun substantially, but indivisible solver calls can still produce rare
large overruns.

## Comparison with adaptive ESI v1

The v2 architecture fixes the two main implementation problems found in v1:

1. ALNS is no longer restarted after ESI, so roulette weights, RNG trajectory,
   and RRT state remain continuous.
2. strict certification is no longer performed at every phase boundary.

Observed improvements relative to v1:

- K=50 mean overrun: 0.629 s -> 0.271 s;
- K=80 mean overrun: 2.123 s -> 0.313 s;
- K=50 within-scenario CV: 4.232% -> 3.833%;
- K=80 strict count: 22/24 in v1 development data and 20/24 on the new v2
  hold-out, while the local legacy ESI control on the same v2 hold-out is only
  17/24.

The v2 architecture is therefore technically cleaner and more predictable, but
its K=80 energy tradeoff is too large for promotion as the default paper
algorithm.

## Frozen decision

**Do not merge continuous ESI v2 into develop as the main algorithm.**

It does not meet all pre-registered criteria:

1. strict rate is improved at K=80 and preserved at K=50 -- pass;
2. fully-strict scenario count is preserved/improved -- pass;
3. K=50 seed CV improves, but K=80 CV worsens -- fail;
4. continuous ESI shows a negative scenario-level shift versus time-scaled
   B-ALNS at both K, especially K=80 -- fail;
5. runtime overrun is much better than v1 -- pass;
6. K=80 energy quality is systematically worse than legacy ESI -- fail.

## Research implication

The experiment exposes a real multi-objective tradeoff:

> returning the best strict-certified incumbent improves certificate robustness,
> but can sacrifice energy because the lowest screened-energy terminal state is
> sometimes only `optimal_inaccurate`.

A future design should not choose between these two outcomes silently. It should
report or optimize a two-level terminal policy, for example:

1. primary candidate: lowest-energy terminal screened solution;
2. fallback candidate: best strict-certified incumbent;
3. attempt a targeted numerical recertification/recovery only when the primary
   candidate is non-strict.

That would preserve low-energy search quality while using the strict archive
only as a fallback rather than as the unconditional returned solution.

## Hold-out rule

Seeds 61--68 have now been observed. Any further algorithm modification must
treat 61--68 as development evidence. A new final validation block is required
for a v3 design; recommended next unseen block: **69--76**.
