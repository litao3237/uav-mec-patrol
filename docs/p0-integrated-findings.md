# P0 correction: direct replacement inside ESI, not postprocessing

**Experimental branch:** `experiment/p0-integrated-replacement` (forked fresh from `develop`)  
**GitHub Actions:** https://github.com/litao3237/uav-mec-patrol/actions/runs/38037433218  
**Workflow-tested commit:** `d46a4ce4eb937e4c83bc121839b8051b506271bd`  
**Result:** successful smoke + K50/K80 paired jobs; 32 regression tests passed.

## Correction of the earlier methodological mistake

The prior P0 round 2 did:

`B-ALNS -> original ESI -> additional swap/2-opt*/block search`

This **paid additional time** and was only a neighborhood potential probe, not
proof that the original algorithm had improved at the same computational cost.
The new experiment instead performs:

`B-ALNS -> either original ESI or integrated replacement ESI`

Every compared ESI arm starts from the exact same frozen B-ALNS checkpoint,
with the same original ESI loop (`contact_mode_intensification`),
`elite_shortlist_limit=6`, `max_rounds=2`, Stage-1 solver/acceptance
thresholds and final Stage-2 validation. There is **no additional sequential
post-ESI refinement**. The new algorithm does not have any special
guarantee of beating the original ESI: losing outcomes are preserved.

## What was actually replaced

The existing ablation showed limited benefit from contact-family refinement
in many cases. This pilot disables **contact relocation, contact point
replacement, and contact deletion**, replacing them with candidates from:

- `swap`: cross-UAV single-task exchange;
- `two_opt_star`: cross-UAV task-sequence suffix exchange;
- `block_relocate`: contiguous two-task transfer to another UAV;
- `combined`: the three families together.

Other original ESI families (route-computation relocation, merge/split and
mode/batch reassignment) remain unchanged. New candidates are rebuilt
with existing MEC repair and undergo the same full Stage-1 CVX and strict
residual acceptance tests. Each candidate family competes within the
**existing six-slot ESI shortlist**, not after it.

New operations are disabled by default: `develop` and existing paper
methods are not changed. Extra geometric generation can increase wall time
even with the same shortlist cap.

## Paired pilot

K=50,80; scenarios S45/S46; algorithm seeds 100/101, four paired
starts nested in two independent scenarios per task scale. The common
B-ALNS exploration ran 100 iterations; the original and new ESIs ran
with up to 2 rounds and shortlist of 6 each. The **40/40 final runs**
passed Stage-1 and independently audited Stage-2, as did the five K30
smoke arms.

Mean *signed* Stage-1 energy differences **new vs original ESI** (positive =
new ESI uses less energy), averaged within scenario then equally across
the two scenarios:

| K | Replacement | New savings vs original ESI (J) | Wins / losses / ties | ESI seconds (new) | Mean Stage-1 CVX calls (new) |
| --- | --- | ---: | --- | ---: | ---: |
| 50 | swap | +280.03 | 1 / 0 / 3 | 4.70 | 6.75 |
| 50 | 2-opt* | **+3367.21** | 2 / 0 / 2 | 6.52 | 8.00 |
| 50 | two-task block | +2296.31 | 1 / 0 / 3 | 5.27 | 6.75 |
| 50 | combined | **+3367.21** | 2 / 0 / 2 | 9.94 | 8.25 |
| 80 | swap | +193.11 | 3 / 1 / 0 | 8.90 | 11.50 |
| 80 | 2-opt* | +571.05 | 1 / 1 / 2 | 10.91 | 11.25 |
| 80 | two-task block | +1718.40 | 1 / 1 / 2 | 11.04 | 11.25 |
| 80 | combined | **+1988.72** | 3 / 1 / 0 | 14.48 | 11.50 |

Original ESI: **3.96 s and 6.75 CVX calls** (K50);
**9.17 s and 11.50 CVX calls** (K80). All times are the ESI
phase only, measured on the Actions Windows runner.

### Specific successes

K50/S45/seed100: the original ESI accepted two single-task route relocations
and saved 3559.88 J vs B-ALNS. Replacing contact candidates by 2-opt*
accepted `U3@8<->U4@4` and `U2@1<->U4@1`, saving 15370.10 J vs B-ALNS:
**an additional 11810.22 J** in the *same two ESI rounds* (12 strict CVX
candidate calls in each profile). This is genuine joint-candidate replacement,
not a postprocessing gain.

### Specific losses, and why they matter

K80/S46/seed101: original ESI accepted
`contact_remove::G_U3_1` (712.82 J) and a subsequent batch merge
(176.43 J). The replacement families could no longer perform that
contact deletion; replacing all contact operations was too aggressive.
The combined variant was **614.92 J worse** than original ESI and
2-opt*/block-only were **682.97 J worse**.

This is important evidence that *some* contact-family operators remain
useful on high-load cases. A targeted replacement should retain the
valuable contact removal while replacing less useful contact-point/position
adjustments.

## What this does and does not prove

- **Does:** demonstrate that P0 cross-route neighborhoods can beat the
  original ESI from identical B-ALNS starts in a *single integrated ESI
  search* using the same maximum rounds and shortlist slots, while
  preserving physical constraint verification.
- **Does not:** prove equal execution time; candidate enumeration and
  additional second-round triggers can increase runtime and CVX calls
  even if the maximum per-round shortlist is fixed.
- **Does not:** establish stable statistical superiority from two
  independent scenarios; bootstrap CIs from these four nested runs would
  be misleading.
- **Does not:** justify immediate paper changes or merging into develop.

## Next changes (do not merge yet)

1. **Retain contact deletion**, replacing only contact relocation/point
   replacement with new route families; rerun paired ablations.
2. Compare which candidates were actually validated, proxy-ranked, and
   accepted, together with wall-time and full CVX calls.
3. Run true nominal end-to-end equal-time comparisons on independent
   scenarios S47–S52, with the same total budget, final Stage-2, and
   exception/overrun reporting, plus larger scenario-level sampling.
4. Only adopt an integrated replacement if it gains energy reliably at
   reasonable runtime under matched time budgets.

Raw JSON and Windows logs are stored as Actions artifacts; frozen archived
paper results and `develop` are unchanged.
