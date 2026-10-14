# P33 preregistration — exact P32 CPU guard two-seed independent replication

**Frozen before first S143–S146 numerical run**, October 14, 2026.
Branch: `experiment/p33-cpu-guard-exact-replication`.
No changes to `develop`, paper resources/geometry/task constraints,
the original 3-destroy/2-repair ALNS, original Stage1 and Stage2, or
frozen previously archived experiment results.

## Why this is a replication, not a rescue retune

The original P29/P30 fixed-source strict S91 repair motivated P31. P31
actual first-use S135–S138 failed its preregistered joint-CPU/BW
success gate. P32 then preregistered queue_guard as primary and
evaluated real 216 full ALNS runs on disjoint S139–S142; **that P32
primary gate failed**. P32's exploratory `cpu_guard` arm did show
31/36 strictly feasible versus 30/36 original: S141/K80/compute×1.5
was gained and no original strict case was lost. These **observed
S141 findings are hypothesis-generation data**; by themselves they
do NOT prove generalization.

To avoid further tuning on those cases, P33 imports the `cpu_guard`
implementation and P32 original hybrid runner **literally unchanged**.
No alteration of targets, candidate pool, eligibility threshold,
tie-breaks, CPU pressure metric, original greedy builder, numerical
acceptance, or exploration clock. P32 outcomes shall not be included
in P33 first-use counts.

## Fixed arms and fair diagnostic-control logic

Run exactly three arms, fixed order:
`original`, `cpu_sham`, `cpu_guard`.

`original`: original unpatched B-ALNS + ESI hybrid.
`cpu_guard`: the exact original P32 `cpu_guard` hook imported from
`experiments/p32_staged_queue_repair.py`. Every original full MEC
greedy repair happens exactly once; returns complete original D if
optimistic queue and static CPU necessary tests both pass. Otherwise,
find up to two binding tasks, generate at most 24 complete legal
cross-UAV candidates and rank cheap queue-and-CPU-necessary passing
structures by the original P32 static CPU pressure rule. Original
Stage1/Stage2 solvers run ONLY at final hybrid qualification.
`cpu_sham`: invoke the exact SAME P32 `cpu_guard` refinement,
candidate generation, safe queue and static CPU tests and ranking, but
discard any hypothetical chosen D, returning the untouched original
greedy fully repaired D. No additional CVX within repair, no physics
changes. Because stochastic ALNS is time-scaled, identical per-call
diagnostics do NOT ensure identical iteration counts/accepted D
sequences. Record hypothetical chosen D separately from real moves.

Every arm receives the same initial D, physical profile, nested seed,
time-scaled RRT and original 6 s B exploration + 2 s ESI elite
SOFT per-phase clock. Full end-to-end wall including initialization,
optimizer and independent Stage2 residual audit is measured; no
hard 8-second complete-time performance claim. Original MEC CPU/BW,
5 UAVs, 2 MEC sites, task work/deadlines remain unchanged.

## New sealed independent sample

Fresh spatial geometry seeds **S143, S144, S145, S146**,
never inspected during P0–P32 mechanism selection.
Each has `K30,K50,K80` tasks and the three nested physical
profiles `baseline,compute_x1p5,deadline_x0p9`.
Nested original algorithm RNG seeds are **191 and 193**.
Therefore 4 spatial layouts × 3 K scales × 3 physical profiles ×
2 algorithm seeds = **72 paired layout/scale/profile/seed rows**,
each with three original Stage1+Stage2 hybrid arms =
**216 actual ALNS runs**.

Physical independent spatial sample n=**4**, not 72 or 216.
Two algorithm seeds are correlated repeats of the same physical
layout/profile and do not double the number of independent scenes.
All failures and successes, SHA IDs, original strict residuals,
operator calls, hypothetical sham moves, B iteration counts and
full clock/wall times are retained. No cherry-picked exclusions.

## Preregistered primary endpoint and exploratory thresholds

**Primary `cpu_guard` endpoint is binary independently verified
full ESI Stage1+Stage2 strict feasibility**, paired against original
within exactly the same S/K/profile/seed and compared against the
equal-diagnostic `cpu_sham`.

P33 exploratory replication only clears all thresholds if:
1. Strict gains over original on at least **two independent NEW
   spatial scenes**;
2. Strict gains on at least **two different K task scales**;
3. **No lost originally strict case**;
4. A **strict positive net paired feasible advantage over
   `cpu_sham`**, counting losses as well as gains.

Secondary outcomes: by-scene and nested-algorithm-seed heterogeneity,
true total wall times, per-iteration overhead, original/Sham D identity
in unchanged original repair, energy **only among matched both-strict
pairs**. No different-denominator mean energy claim.

If any primary gate criterion fails, freeze and report it as negative
without modifying/relaunching P33 on S143–S146. Even if exploratory
thresholds pass, n=4 spatial scenes is inadequate to declare
publication-grade statistical generality. Any next algorithm change
must be preregistered on yet newer disjoint S147+ layouts.

Do not merge P33 into `develop` until separately reviewed.
