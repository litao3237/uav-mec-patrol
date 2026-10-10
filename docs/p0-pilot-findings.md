# P0 cross-UAV elite pilot: first GitHub Actions result (negative)

Source branch: `experiment/p0-cross-uav-elite`  
Source commit tested: `0e5aafd13f813213bc1c7d6e3820c94ff5842b4a`  
Actions run: https://github.com/litao3237/uav-mec-patrol/actions/runs/38034574463  
Run status: **success** (both Windows matrix jobs; focused tests: 27 passed).

## Frozen pilot protocol

- K = 50 and 80 tasks; independent scenario seeds S45 and S46;
  nested stochastic seeds 100 and 101, hence **four paired starts per K**.
- Every algorithm seed builds one B-ALNS solution after **100 exploration iterations**.
  The *same discrete checkpoint* and strictly validated Stage-1 energy anchor
  are supplied to three ESI variants.
- **baseline:** unchanged ESI route insertions and shortlist.
- **cross_uav:** opt-in one local alternative plus one alternative on a
  different UAV (when available), while retaining the per-task candidate cap.
- **cross_uav_route2:** cross_uav plus two reserved route-family shortlist
  positions. All profiles retain shortlist length 6, up to two ESI rounds,
  strict Stage-1 CVXPY evaluation, and identical acceptance thresholds.
- Stage-2 postprocessing and independent validation was run for each result.
  All **24 profile runs** passed both Stage-1 and Stage-2 checks.
- **Not an equal-wall-clock-budget experiment.** Report actual CVXPY calls,
  actual runtime, and sample scope. This pilot must not replace the paper's
  matched-time evaluation.

## Results: scenario-equal paired averages vs the common B-ALNS checkpoint

| Tasks | Variant | Mean Stage-1 gain (J) | Gain (%) | Strict pairs | Stage-2 passed | Mean ESI s | Mean new CVX calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | baseline | 889.971 | 0.477 | 4/4 | 4/4 | 3.750 | 6.75 |
| 50 | cross_uav | 185.372 | 0.099 | 4/4 | 4/4 | 3.968 | 6.75 |
| 50 | cross_uav_route2 | 185.372 | 0.099 | 4/4 | 4/4 | 4.042 | 6.75 |
| 80 | baseline | 1480.204 | 0.623 | 4/4 | 4/4 | 12.973 | 11.50 |
| 80 | cross_uav | 1480.204 | 0.623 | 4/4 | 4/4 | 13.072 | 11.50 |
| 80 | cross_uav_route2 | 1480.204 | 0.623 | 4/4 | 4/4 | 13.146 | 11.00 |

The P0 variants do **not** improve upon the original ESI on these
samples. For K=50 they are markedly worse in one paired case and identical
in the other three. For K=80 all three strategies return the same Stage-1
energy in all four cases.

### Case-level diagnosis: K50, S45, seed100

- Original ESI saves **3559.884 J** in two accepted route moves:
  `S47->U4@2` (**2777.254 J**) and `S36->U2@15` (**782.630 J**).
- P0 cross_uav saves **741.490 J**:
  `S8->U4@6` (**636.046 J**) plus `S45->U3@9` (**105.444 J**).
- The high-value original `S47->U4@2` candidate was CVX-evaluated by the
  baseline, but was **absent from the P0 evaluated shortlist**.
- Thus forcing a local-and-cross-UAV pair within a **fixed limit of two
  candidate insertions per task** can replace an existing strong cross-UAV
  alternative. It is *not* a safe dominance-preserving modification.
  Shortlist scoring changes also contribute; the present pilot does not
  isolate which restriction removed this particular candidate.
- Raising the route-family minimum quota to 2 evaluated more route moves
  in some other cases, but produced no additional accepted improvements.

### Search diversity and work

Across K=50, the mean **generated route candidates per ESI round** rose
from 9.2 (baseline) to 14.8 (cross_uav), while the mean shortlisted route
candidates remained 1.4 in both; forcing two reserved positions changed the
latter to 2.0 without improving final energy.

Across K=80, generated route candidates rose from 10.0 to 15.1 per round;
again, no energy improvement was observed. Additional candidate generation
and ranking are not themselves evidence of greater search quality.

## Decisions

1. **Do not merge P0 into develop.** Keep opt-in changes and this negative
   evidence on the experiment branch.
2. Next route experiment should be **legacy-preserving**: generate extra
   cross-UAV/swap/2-opt-star candidates without deleting the original
   top-two insertions. Record candidate origin and proxy rank; use a capped
   independent evaluation budget so increased CVX effort is explicit.
3. Test whether *ranking* is the bottleneck: compare each shortlisted
   candidate's proxy score to its strict CVX Stage-1 energy, and measure
   high-value moves that rank below the shortlist.
4. Only when the route move improves within fixed-search experiments,
   run a fresh **end-to-end equal-time** trial and enlarge the independent
   scenario set. Paired random seeds in two scenarios are too few for
   inferential claims.

Archived paper evidence in `results/` and the `develop` branch were
not changed. The run artifacts are on the linked Actions run.
