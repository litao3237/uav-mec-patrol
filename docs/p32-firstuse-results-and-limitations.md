# P32 completed S139–S142 first-use: negative primary gate, CPU guard pilot

**Date:** 2026-10-14. **Repository:** `litao3237/uav-mec-patrol`.
**Frozen code and research criteria:** [P32 preregistered protocol](p32-staged-queue-shield-preregistered-protocol.md).
**GitHub Actions:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38512110840
**Full results artifact:** `p32-staged-firstuse-summary-38512110840`.

All **12 first-use jobs and the summary** completed successfully. All
**216** real original model ALNS runs are present: S139–S142 independent
spatial scenes, K30/K50/K80, profiles baseline/compute×1.5/deadline×0.9,
one nested ALNS seed 191, six paired arms. There are only **four
independent spatial layouts**, not 36 or 216. The original paper
physical UAV/MEC CPU, BW, FIFO/EDF, original ALNS 6-second exploration +
2-second elite *soft* clocks and final strict Stage1+Stage2 were unchanged.

## Original-EISI strict acceptance and true wall time

| Arm | Original Stage1+Stage2 strict | K30 | K50 | K80 | B iterations | Mean true complete wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| original | 30 / 36 | 12 / 12 | 12 / 12 | 6 / 12 | 5,031 | 9.659 |
| p31_queue_only reference | 30 / 36 | 11 / 12 | 12 / 12 | 7 / 12 | 4,513 | 9.980 |
| sham_joint | 30 / 36 | 12 / 12 | 12 / 12 | 6 / 12 | 4,784 | 9.715 |
| queue_guard (P32 **predeclared primary**) | **29 / 36** | 11 / 12 | 12 / 12 | 6 / 12 | 4,694 | 10.315 |
| cpu_guard | **31 / 36** | 12 / 12 | 12 / 12 | 7 / 12 | 4,886 | 9.814 |
| joint_gate | 30 / 36 | 12 / 12 | 12 / 12 | 6 / 12 | 4,730 | 10.195 |

The P31 reference in this table was **rerun on P32's same new physical
samples**, not copied from old S135–S138 data. These are stochastic
time-budgeted runs. In particular, a sham that returns the original
postrepair D is not guaranteed to have the same full ALNS trajectory
because per-iteration diagnostic time changes how many iterations fit.

### Strict paired changes versus the same-case original

- `p31_queue_only`: +2 new: S140/K80/baseline and
  S142/K80/deadline×0.9; −2 original strict cases: S140/K30/baseline
  and S140/K80/compute×1.5.
- `sham_joint`: +0, −0.
- **`queue_guard`**: +0, **−1** original strict:
  S140/K30/baseline.
- **`cpu_guard`**: **+1, −0**. The new strict case is
  S141/K80/compute×1.5/ALNS-seed191.
- `joint_gate`: +0, −0.

`cpu_guard` had only **one new positive spatial scene and one K scale**;
it is an interesting NEW hypothesis, not an independently
replicated/generalizable advantage. The preregistered `queue_guard`
required gains in at least two scenes, two scales and zero lost original
strict cases. **All three criteria failed**, hence P32's primary
exploratory gate **FAILED**. Do not relabel cpu_guard as the original
preregistered primary method posthoc.

For both-strict pairs only, original minus `cpu_guard` energy averaged
+1,362.04 J (30 matched pairs); this descriptive number is not a
general energy improvement finding. `joint_gate` made 572 joint
BW–CPU necessary-bound calls; the unmodified P31 queue reference made
4,701. Yet mean true complete time was **10.195 seconds for joint_gate
versus 9.659 seconds for original**. Lower joint DP calls did not yield
a demonstrated full-run speedup.

## Next reproducibility test, fixed before any new sample

Replicate the **unchanged P32 cpu_guard code** on disjoint S143–S146
with two nested ALNS seeds and an additional **equal-diagnostic
cpu-sham** (P32's original sham matched joint, not cpu). New physical
layouts, no tuning from S139–S142. Favor paired gains/losses and full
timings over the headline success count. Even if this replicates, a
small number of spatial scenes does not establish significance.

No P32 changes were merged into `develop`.
