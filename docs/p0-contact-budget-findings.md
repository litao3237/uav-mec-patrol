# P0 diagnostic gate 1: contact ablation, candidate ranking, and energy lower bound

**Branch:** `experiment/p0-contact-budget-diagnostics`  
**Actions:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38038975506  
**Tested commit:** `41394e190e6752f26d92a83fe5b5463071c14e38`  
**Status:** all jobs successful: K30 smoke, K50/K80 contact ablation, K50/K80 limited candidate CVX audits. All original/new unit and regression tests passed (41 focused tests).

## What this diagnostic does

Every comparison uses **one common B-ALNS endpoint per instance/algorithm seed**.
The original ESI and each replacement run independently from that endpoint
with 100 prior B-ALNS iterations, up to 2 ESI rounds and no more than
6 shortlisted strict-CVX candidates **per round**, followed by the same
Stage-2 full residual audit. **These are not equal-wall-clock-budget experiments**:
new candidate enumeration may add time and a second successful round may
add more CVX calls.

Profiles separately remove contact deletion / contact relocation /
contact-point replacement, then preserve deletion while replacing the latter
two with swap, cross-route 2-opt*, block relocation, or all three.

Previously-used P0 tuning scenarios S45/S46 were deliberately excluded from
this batch. Holdout scenarios here are S47/S49; algorithm seeds are A103/A104
(not used in original paper's A100–A102). Still, S47/S49 are part of the
paper's original scenario pool; they are **not completely unseen workloads**.

## Paired Stage-1 energy, new minus original ESI

Positive signed savings mean the variant consumes *less* UAV energy.
Independent observation unit = scenario (2 per scale); nested seeds are
averaged within scenarios, then scenarios weighted equally. K80 has only
3 strictly paired successful seeds because S49/A104's shared B-ALNS
anchor returned `optimal_inaccurate` and was not admitted as an elite
baseline. No failure record was silently omitted.

| Tasks | Variant | Mean saving vs original ESI (J) | Wins / losses / ties | ESI time (s) | Mean strict Stage-1 CVX calls | Stage-2 valid / planned |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| 50 | original ESI | 0.0 | — | 4.57 | 9.00 | 4/4 |
| 50 | without contact removal | 0.0 | 0/0/4 | 4.46 | 8.75 | 4/4 |
| 50 | without contact relocation | 0.0 | 0/0/4 | 4.65 | 9.00 | 4/4 |
| 50 | without contact-point replacement | 0.0 | 0/0/4 | 4.33 | 9.00 | 4/4 |
| 50 | preserve contact removal only (no new route family) | 0.0 | 0/0/4 | 4.60 | 9.00 | 4/4 |
| 50 | preserve removal + swap | +605.53 | 2/0/2 | 5.99 | 9.75 | 4/4 |
| 50 | preserve removal + 2-opt* | +1798.73 | 1/0/3 | 6.26 | 9.00 | 4/4 |
| 50 | preserve removal + block relocation | 0.0 | 0/0/4 | 6.14 | 9.00 | 4/4 |
| 50 | preserve removal + combined | **+2404.26** | 3/0/1 | 8.89 | 9.75 | 4/4 |
| 80 | original ESI | 0.0 | — | 2.81 | 5.50 | 3/4 |
| 80 | without contact removal | 0.0 | 0/0/3 | 2.56 | 5.00 | 3/4 |
| 80 | without contact relocation | 0.0 | 0/0/3 | 2.80 | 5.50 | 3/4 |
| 80 | without contact-point replacement | 0.0 | 0/0/3 | 2.82 | 5.50 | 3/4 |
| 80 | preserve contact removal only (no new route family) | 0.0 | 0/0/3 | 2.85 | 5.50 | 3/4 |
| 80 | preserve removal + swap | +1135.35 | 2/0/1 | 4.11 | 7.00 | 3/4 |
| 80 | preserve removal + 2-opt* | **+2318.61** | 1/0/2 | 3.36 | 5.50 | 3/4 |
| 80 | preserve removal + block relocation | 0.0 | 0/0/3 | 3.41 | 5.50 | 3/4 |
| 80 | preserve removal + combined | +1135.35 | 2/0/1 | 5.88 | 7.00 | 3/4 |

**Important:** `no_contact_remove` having no effect on these particular
holdout cases does **not** prove deletion is useless; previous S46/A101
demonstrated a 712.82 J saving via contact deletion. Keep this operator
as an insurance move until substantially more scenarios support removal.

## Direct operator utilization evidence

Across strictly validated original ESI runs in this batch:

| Tasks | Original contact-position / point-replacement candidate evaluations | Original contact-delete candidate evaluations | Accepted contact-family moves | Other accepted |
| --- | ---: | ---: | ---: | --- |
| 50 | 6 | 11 | **0** | 3 route relocations + 1 batch merge |
| 80 | 4 | 5 | **0** | 1 route relocation + 1 batch merge |

The contact-position/replacement operators used **10 strict
candidate-evaluation shortlist slots in 7 validated starts**, without
yielding an accepted move. This favors testing *selective* replacement,
not simply adding extra ESI rounds. However their importance can vary
by scenario. `contact_remove` also produced zero acceptance in these
heldout starts, but was important in earlier S46.

At K80/S49/A103, retaining only 2-opt* beat original by **4637.17 J**,
whereas combining all three route families returned **888.77 J**;
under identical 6-slot shortlist caps, family competition excluded an
important 2-opt* opportunity. Fixed one-per-family quotas can therefore
hurt; this is a more concrete next-stage mechanism than blindly
expanding all operator pools.

## Candidate rank and optimistic energy bound: separate CVX audit

Tested K50/S47/A103 and K80/S47/A103, with two operator profiles each:
original ESI and contact-deletion-preserving combined. This is a
**limited sample** of the default six-slot shortlist plus up to six
additional widened candidates, not the full combinatorial neighborhood.

| K | Profile | Evaluated candidates | Optimistic energy-bound excludes | Accepted if wrongly excluded | Strictly improving candidates outside default six |
| --- | --- | ---: | ---: | ---: | ---: |
| 50 | Original | 12 | 2 | 0 | 0 |
| 50 | Preserve delete + combined | 12 | 0 | 0 | 1 |
| 80 | Original | 12 | 0 | 0 | 0 |
| 80 | Preserve delete + combined | 12 | 1 | 0 | 1 |

**0/48 observed false exclusions.** All 48 candidates satisfied the
mathematical lower-bound consistency check against qualified CVX energies
where applicable. Yet only **3/48** candidates could be rejected by this
simple bound, and two of those already failed the existing necessary
feasibility precheck. Thus the **incremental** benefit of this bound as a
new algorithm mechanism currently looks **weak** (one additional CVX
infeasible candidate in this limited sample), not a proven performance
improvement.

The widened sample identified one improved swap solution outside the
default six in each of K50 and K80, but these were smaller savings than
the best improving swap already selected. This does *not* establish a
large proxy-ranking failure, only a candidate-selection effect worth
testing on larger, independently generated datasets.

## Research decisions

1. **Do not merge code or alter the original paper experiments.**
2. Retain contact deletion; a zero mean contribution in two new
   scenarios is not grounds for deleting a move useful in an older one.
3. Focus next on *cheap, scenario-aware allocation of existing ESI
   shortlist slots* between route relocation, swap and 2-opt*. The
   K80/S49/A103 combined failure is direct evidence that a fixed
   one-per-family quota can lose strong candidates.
4. Do **not** promote the simple energy lower bound to the main
   claimed innovation yet; measure incremental saved wall time after
   existing precheck first.
5. Verify whether cross-UAV path moves can be reconstructed with better
   MEC contact decisions without raising candidate evaluation cost.
6. Crucially, run a **matched nominal end-to-end time** comparison
   (B-ALNS, original ESI, selective integrated ESI) on more independent
   scenarios. Holdout tuning data must not be reused uncritically.
