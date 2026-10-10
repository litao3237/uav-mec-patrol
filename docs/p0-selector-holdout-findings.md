# P0 gate 3: protected ESI shortlist, pre-registered fresh-scene holdout

Branch: `experiment/p0-protected-elite-selection`  
**Tested code:** `c8bff58b32447b12038419360f3254ccf9aaab40`  
Actions: https://github.com/litao3237/uav-mec-patrol/actions/runs/38040862588  
Result: all jobs succeeded; 54 focused regression tests passed.

## Fixed protocol, not cherry-picked

- K = 50, 80; **four new independent instance seeds** S53/S54/S55/S56;
  two nested algorithm seeds A107/A108, 8 attempts per K and method.
- Nominal end-to-end soft time cap: K50 15s, K80 45s.
- B-ALNS: 80% exploration; ESI arms: 60% exploration + 20%
  Stage-1 anchor/intensification; all arms reserve 20% for final
  Stage-1 + Stage-2 strict solver and independent residual audit.
- Each ESI method at a (K,S,algorithm seed) uses exactly the same
  shortened B-ALNS checkpoint; B-ALNS competes using its longer search.
- Five-way experimental comparisons were frozen **before** examining
  the new S53–S56 results: original ESI, fixed 2-opt* replacement,
  contact-slot-only replacement, route/contact-delete/batch protected
  2-opt*, and protected 2-opt*+swap (with reusable proxy scores and a
  cheap remaining-time guard).
- A single ESI phase, no appended postprocessing, at most 2 rounds,
  at most 6 strict candidate validations per round.
- Candidate generation, final solve and audit are included in reported
  end-to-end times. Solver calls are not interruptible (soft budget).
- Positive signed energy delta means the variant is better than the
  stated reference. Values are scenario-equally averaged; nested
  algorithm seeds do **not** count as independent scenario replicates.

## Results: Stage-1 UAV energy (paired valid, equal scenario weights)

| K | Method | Both stages valid | Within nominal budget | Mean total s | Saving vs original ESI (J) | Saving vs B-ALNS (J) | Wins/losses/ties vs ESI |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 50 | B-ALNS | 8/8 | 7/8 | 13.37 | +2376 | 0 | 4/1/3 |
| 50 | original ESI | 8/8 | 8/8 | 12.73 | 0 | -2376 | — |
| 50 | fixed 2-opt* (legacy selection) | 8/8 | 8/8 | 13.17 | **+2665** | +289 | 2/0/6 |
| 50 | replace only selected contact slots | 8/8 | 8/8 | 13.15 | +820 | -1556 | 2/0/6 |
| 50 | protect route/delete/batch + 2-opt* | 8/8 | 8/8 | 13.12 | +784 | -1593 | 2/1/5 |
| 50 | protect route/delete/batch + 2-opt*+swap | 8/8 | 8/8 | 13.07 | +1532 | -845 | 2/1/5 |
| 80 | B-ALNS | 7/8 | 7/8 | 38.15 | +3898 | 0 | 6/1/0 (7 paired) |
| 80 | original ESI | 8/8 | 8/8 | 36.89 | 0 | -3898 | — |
| 80 | fixed 2-opt* | 8/8 | 8/8 | 38.15 | **+1697** | -2201 | 4/0/4 |
| 80 | replace only selected contact slots | 8/8 | 8/8 | 38.43 | **+1697** | -2201 | 4/0/4 |
| 80 | protected 2-opt* | 8/8 | 8/8 | 38.47 | +1617 | -2281 | 4/0/4 |
| 80 | protected 2-opt*+swap | 8/8 | 8/8 | 38.76 | +1698 | -2207 | 6/0/2 |

Notes: paired gain vs B-ALNS at K80 is conditioned on the 7 runs
where B also passed both stages; this smaller common subset must not
be confused with all 8 ESI-valid runs. At K50, B has **one** soft-budget
overrun, so energy-only pair means include one result beyond the strict
time cap. Within-budget-only results require separately conditioning on
both methods finishing in time; coverage should always accompany them.

## Descriptive scenario bootstrap intervals (4 independent scenarios only)

These intervals are diagnostics, **not** reliable claims of statistical
significance from a large population:

- K50 fixed 2-opt* vs original ESI: mean +2665 J;
  scenario bootstrap 95% interval **[0, 7854] J**.
- K50 fixed 2-opt* vs B-ALNS: mean +289 J;
  interval **[-5709, 7174] J**.
- K80 fixed 2-opt* vs original ESI: mean +1697 J;
  interval **[555, 2451] J**.
- K80 fixed 2-opt* vs B-ALNS (7 common-valid runs):
  mean -2201 J; interval **[-8550, 1771] J**.

## Core diagnostic finding

**Improving six-slot candidate selection alone is not enough to establish
an equal-time advantage over continuing B-ALNS.** The simple fixed 2-opt*
replacement *matched or beat the old ESI on all 16 valid starts* but
the mean advantage over the longer B exploration is near zero at K50
and negative at K80.

On K50/S55 the mean B advantage over original ESI was 7.65 kJ.
On K80/S56 a single common-valid B instance was 11.82 kJ better than
the original ESI. This is evidence that lost exploration time matters
more than small elite-only improvements in some workloads.

The smarter selection policies are not uniformly better:
- Protecting existing original-route, contact-delete, batch moves did
  prevent those families from being evicted, but sometimes lost good
  2-opt* opportunities and did not improve averaged quality.
- Reusing precomputed cross-route scores and checking remaining time
  did not consistently save enough wall time to create an advantage.
- Jointly generating both swap and 2-opt* increased preparation work.

**Decision:** Keep frozen `develop` untouched; do not promote the
protected selector to the main method. Instead test a pre-registered
**exploration/intensification time allocation sweep** under the same
end-to-end caps. Candidate scoring and look-ahead MEC repair should
be reconsidered if fair-budget performance remains weak.

No paper figures or archived results were overwritten.
