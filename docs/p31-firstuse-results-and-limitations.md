# P31 first-use ALNS experiment — completed results, October 14, 2026

**Repository:** litao3237/uav-mec-patrol  
**Experimental branch:** experiment/p31-binding-aware-alns-repair-holdout  
**GitHub Actions:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38495005297  
**First-use artifact:** p31-binding-firstuse-summary-38495005297  
**Frozen protocol:** docs/p31-binding-aware-alns-preregistered-protocol.md

> Important: P31 is a full ALNS operator embedded into the original algorithm;
> P29 and P30 were single-source, posthoc feasibility recovery experiments.
> Their existence does not establish that P31 is superior. These results
> **do not meet the preregistered exploratory success thresholds**.

## Sample and fixed resource constraints

Previously unseen independent spatial layouts S135–S138; task scales
K30/K50/K80; baseline/compute×1.5/deadline×0.9; one nested ALNS seed 191.
12 scene-scale blocks, **36 paired physical/profile/algorithm-seed inputs**.
Five arms each — 180 complete hybrid ALNS executions. Physical independent
layout count is **four**, NOT 36 or 180. Original Stage1+Stage2 numerical
model, MEC CPU/BW, five UAVs, two MECs, original greedy MEC builder,
ScreenedProxy objective and numerical residual acceptance unchanged.

All results retained; no missing or failed holdout arm; repository workflow
summary concluded **success**. The hard-complete wall time is not restricted
to 8 seconds: B exploration nominal 6s and ESI elite nominal 2s with
non-interruptible numerical solves and final independent audits recorded.

## Original/sham and ablation comparison

| Arm | ESI strict both | K30 | K50 | K80 | B iterations total | Mean true complete wall time |
|---|---:|---:|---:|---:|---:|---:|
| original | 29/36 | 12/12 | 12/12 | 5/12 | 4,030 | 9.629 s |
| sham (equal diagnosis work, old D returned) | 28/36 | 12/12 | 11/12 | 5/12 | 3,906 | 9.753 s |
| queue_only | **30/36** | 12/12 | 12/12 | 6/12 | 3,487 | 9.930 s |
| cpu_only | 29/36 | 12/12 | 11/12 | 6/12 | 3,353 | 10.074 s |
| joint_cpu_bw | 29/36 | 12/12 | 11/12 | 6/12 | 3,357 | 10.053 s |

The B exploration and ESI final strictly qualified counts coincide in
this dataset, so ESI did not additionally recover strict failure in the
36 matched rows.

**Paired strict changes relative to original:**
- sham: 0 new, **1 lost** — S135, K50, baseline, seed191.
- queue_only: **1 new**, **0 lost** — S135, K80, deadline×0.9, seed191.
- cpu_only: **1 new, 1 lost** — new S135/K80/deadline×0.9; lost
  S137/K50/compute×1.5.
- joint_cpu_bw: **1 new, 1 lost**, same two rows as cpu_only.

The joint algorithm was slower than original on the descriptive mean
end-to-end metric (10.053s vs 9.629s) and used fewer B iterations.
Only same-row **jointly strictly qualified** solutions are compared for
energy. Among 28 such pairs, mean original minus joint energy was
**+278.47 J**. This small descriptive difference is not a demonstrated
robust energy-saving claim.

## Precise positive and negative examples

**S135 / K80 / deadline×0.9 / seed191**:
- original and diagnostic sham fail Stage1+Stage2 strict qualification.
- queue_only, cpu_only and joint_cpu_bw all return a strict Stage1+Stage2
  qualified physical D, with ESI energy **234,112.8074 J**.
- each enabled ranking chose 2 cross-UAV alterations in this run.
- full elapsed complete times: original 6.998s, sham 7.336s,
  queue 12.857s, cpu 12.877s, joint 12.862s.
- The single positive case is **not unique to the joint BW+CPU ranking**.

**S137 / K50 / compute×1.5 / seed191**:
- original, sham and queue_only remain strictly qualified at
  **203,843.0377 J**.
- cpu_only and joint_cpu_bw lose strict feasibility despite two actual
  repair modifications each.
- complete wall times: original 12.032s, sham 11.639s, queue 11.721s,
  cpu 19.622s, joint 19.666s.
- This is a scientifically material **strict original-success regression**.

## Preregistered gate and interpretation

| Preregistered requirement | Observed |
|---|---|
| Strict gains in at least two independent first-use spatial scenes | **FAIL — one S135 only** |
| Gains at two or more task scales | **FAIL — only K80** |
| Preserve all originally strictly feasible cases | **FAIL — joint loses S137/K50** |
| Joint scheme decisively beats queue-only ablation | **NOT DEMONSTRATED** |

Consequently, **P31 first-use exploratory superiority threshold is NOT met**.
It is valid to report that incorporating cross-UAV relocation inside actual
ALNS can rescue one uninspected high-pressure sample. It is not valid to
claim that the new CPU/BW-ranked ALNS generally outperforms original ESI-ALNS
or that increased computation is worthwhile. The queue-only ablation is
at least as strong on the strict success metric in this small sample.

The separate previously-inspected 100-iteration source/SHA replay is a
code-identity diagnostic and is *not* included in these first-use counts.
Its job-level completion status is separate from the first-use aggregate.

## Suggested follow-on (new P32, disjoint spatial layouts)

Freeze P31 results as-is. Hypothesize that the *ranking* needs
a baseline-preservation guard and a runtime-cost gate: only apply
targeted relocation to genuinely promising complete candidates and
never trade an already strictly qualified result for unverified
necessary-bound gains. Test a lightweight queue-first rule before
additional CPU/BW screening; use a held-out untouched S139+ cohort and
compare fixed-clock output with true full wall and preserved feasible
endpoints. Do **not** tune P31 code or reuse first-use S135–S138 as
unseen data for a revised variant.

No change has been made to develop or official paper experiment results.
