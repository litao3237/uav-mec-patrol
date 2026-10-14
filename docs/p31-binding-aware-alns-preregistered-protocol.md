# P31 — Deadline-binding-aware ALNS repair: frozen development and first-use protocol

**Frozen before reading P31 first-use outcomes**; scope: experiment branch only.
No change to official \`develop\`, the paper's physical model, resource constraints,
frozen baseline config, original Stage1/Stage2 residuals, or archived paper results.

## Hypothesis and the positive precedent

P29 found a strictly valid K80 S91 compute×1.5 solution by moving S36
U2 → U1 and reusing U1's existing E2 contact G_U1_1 after a previously
observed P22 two-task swap. P30 independently reproduced the identical
structural SHA under Windows and Ubuntu, with both saved and reconstructed
Stage2 resource residual acceptance; it did **not** establish a full
equal-budget ALNS advantage or a statistically independent holdout.
P31 tests whether a **bounded operator**, not a bespoke posthoc solution,
helps the real original 3-destroy/2-repair ALNS on previously unseen scenes.

## Frozen mechanism and arms

After each original cheapest/regret2 full-MEC-builder repair (exactly one
original builder call), compute the exact original optimistic FIFO/EDF
necessary bound and static station-CPU-share necessary bound. Identify
up to **two** tasks from the most CPU-pressured (UAV,MEC) virtual pairs:
the binding deadline task and, if possible, one high-workload predecessor.
For each, consider up to **three** *different* destination UAVs and their
original top **two** insertion positions plus the earliest position.
For each candidate, allow local execution or reuse at most **two** existing
downstream contacts from an alternative MEC. Total <=**24** complete legal
candidates, no new contact inserted, no extra full MEC greedy builder,
no per-candidate exact Stage1/Stage2 CVX. Check queue/CPU necessary bounds,
then the joint BW-CPU optimistic necessary bound (**16** bins) when eligible.
Return a new state only on strict lexicographic ranking improvement;
protect a baseline already passing all necessary gates.

**Five arms**: original (no diagnostics), sham (same full diagnostics and
candidate generation but always returns the original repair), queue_only,
cpu_only, joint_cpu_bw. Within the *four* hooked arms, the same physical
candidate pool and exact same screening work are used; only the ranking or
actual return differs. This is a fair diagnostic-computation sham, not a
guarantee of matched iteration counts. The original operator registration
names/count, destroy RNG, roulette selection, time-scaled RRT, original
ScreenedProxy scalar objective, P1-R, elite oracle and all independent
strict acceptance remain unchanged.

## Frozen first-use holdout

Uninspected spatial seeds **S135, S136, S137, S138**, each at paper task
scale **K30, K50, K80** with 5 UAVs and 2 active MECs. Three per-layout/
scale physical profiles: **baseline**, **compute_x1p5**, **deadline_x0p9**.
One frozen ALNS seed **191** per paired physical/profile block. Thus
12 scene-scale blocks and 36 paired profile/seed inputs, five arms each,
total **180** full original hybrid algorithm executions.
**Independent spatial sample count is four**, not 36 or 180.

All arms share an identical initial discrete D and nested seed. Original
B-exploration clock **6s**, original ESI elite clock **2s**, time-scaled
acceptance, exactly the same original final Stage1+Stage2 strict residual
qualification. Real end-to-end wall time (including initialization,
uninterruptible solver/verification), iterations, candidates, accepted
cross-UAV modifications, original/sham/ablation outcomes are archived.
**6+2 seconds is not a hard 8-second complete-time deadline.**

A separate **already-seen** 100-iteration replay on frozen S91 and S93
checks the original and sham B endpoint SHA identity. Those historical
development scenes **never count** toward first-use gains.

## Interpretation and preregistered exploratory acceptance

Primary: paired changes in full ESI Stage1+Stage2 strict feasibility,
including both new successes and lost original successes.
Secondary: strict feasible energy comparison **only when both** arms
succeed on the exact same scene/scale/profile/seed; iterations, actual
end-to-end runtime and mechanism frequency. Every failed arm and numerical
solver exception is retained; no success-only average with different
denominators.

Exploratory gate: strict gains on **at least 2 independent new spatial
scenes** and **at least 2 K scales**, with **no lost original feasible
case**; report versus sham and other ablations. Even if this gate passes,
four scenes and one nested seed do **not** establish statistical
significance, publication-grade universal superiority, or a conclusive
runtime-normalized advantage. If it fails, report the negative result,
do not retune against the fresh samples, and start any revised mechanism
on a new preregistered branch and disjoint new scenes.

No P31 runs are merged into \`develop\` until verified and reviewed.
