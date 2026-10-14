# P33 completed — strict CPU guard replication with exact-cost CPU sham

Date: 2026-10-14. GitHub workflow:
https://github.com/litao3237/uav-mec-patrol/actions/runs/38512929165

**Frozen preregistered protocol**:
[p33-exact-cpu-guard-replication-preregistered.md](p33-exact-cpu-guard-replication-preregistered.md)

**Completed summary artifact**:
`p33-cpu-replication-summary-38512929165`.

## Sample integrity

All 12 new S143–S146 × K30/K50/K80 matrix jobs, validation and
final summarization finished **successfully**, without missing
source/seed/arm or original Stage1+Stage2 numerical errors.
Each physical/profile has two independent nested ALNS RNG seeds
191 and 193; 4 spatial scenes × 3 K scales × 3 profiles × 2 nested
ALNS seeds = **72 matched evaluation inputs**, each with 3 full
ALNS arms = **216 complete original hybrid algorithm runs**.
The spatial layout independent sample count is **four**, not 72.
No S135–S142 data were used as first-use in P33.

P32's original `cpu_guard` code and physical resource parameters were
imported **unchanged**. The P33 `cpu_sham` calls the exact same
P32 cpu_guard candidate generation/ranking but rejects hypothetical
moves after diagnostics, returning the original fully repaired D.
No extra Stage1/Stage2 computation was used to rank any candidate.
6 seconds B exploration and 2 seconds ESI elite clocks are soft
per-phase budgets; complete wall-clock timing was measured.

## Full original Stage1+Stage2 strict feasibility

| ALNS arm | Strict ESI | K30 | K50 | K80 | B iterations total | Mean complete wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| original | 55/72 | 24/24 | 24/24 | 7/24 | 8,274 | 9.911 s |
| cpu_sham | 54/72 | 24/24 | 24/24 | 6/24 | 7,760 | 9.832 s |
| **unchanged P32 cpu_guard** | **56/72** | **23/24** | 24/24 | **9/24** | 7,885 | 9.717 s |

Against the same physical profile and nested seed:
- **cpu_guard vs original:** +2 new strict cases, **−1 lost strict**,
  both-strict energy comparison n=54. New cases:
  S144/K80/baseline/seed193, S145/K80/baseline/seed193.
  Lost: S146/K30/deadline×0.9/seed193.
- cpu_sham vs original: +0, −1
  (S143/K80/baseline/seed191). A sham with no D changes inside
  the repair still affects time-scaled algorithm trajectory.
- cpu_guard vs cpu_sham: +3, −1. These include the two
  genuinely new original-relative positives and the fact that
  cpu_guard preserved S143/K80/baseline/seed191 where sham lost it.

**The preregistered four-part P33 exploratory research gate FAILED**:
it had gains on two independent new spatial scenes and positive
net gains relative to the CPU diagnostic sham, but **both new gains
were at K80 only** and **one original success was lost**. It is not
valid to declare a no-regression guarantee, multi-scale superiority,
or publication-grade generalization from these results.

For matched both-strict original/cpu_guard evaluations only (n=54),
mean original-minus-CPU energy was +2,396.20 J. This is descriptive
energy difference only; average energy over different strictly
feasible sets would be invalid. Likewise the cpu_guard's observed
9.717 s average complete wall time vs 9.911 s original is not
evidence of a universal speedup; it also changed exploration
trajectory and total B iterations.

The new strict gains were both at nested seed 193, not 191:
seed-specific sensitivity remains. Across the full 72 source pairs,
the exact final original ESI discrete SHA was reproduced by
cpu_guard in only 22 cases, reflecting distinct algorithm paths,
not deterministic monotonic improvement. The sham explored
403 hypothetical repair updates but actually changed **zero**
postrepair Ds, demonstrating that per-step diagnostic work alone
can perturb the timed stochastic algorithm.

## Mechanistic synthesis and next stage

P29/P30 showed a verified original-hardware single-source
deadline-binding UAV/MEC task-transfer win. P31 and P32 actual full
ALNS gate trials failed their preregistered primary thresholds,
despite scattered genuinely strict new cases. P33 independently
replicated two K80 gains with the same frozen CPU-guard
mechanism, but exposed a lost easy K30 case.

This suggests a separately budgeted **incumbent-preserving,
strictly verified optional rescue stage**, rather than further
unverified changes to the stochastic base ALNS trajectory:
run original baseline first; *if* it is already strictly feasible,
return it unchanged; otherwise, use an explicitly measured extra
candidate/Stage1/Stage2 budget and choose from original-hardware
valid D. This can protect the baseline at the cost of extra
solver time, **not an equal-6+2-clock superiority result**.
To validate that future mechanism, preregister it on disjoint
new spatial seeds S147+, compare against an equal-extra-budget
random/queue control and retain every failure.

No changes were merged into `develop` or official paper
experiment archives.
