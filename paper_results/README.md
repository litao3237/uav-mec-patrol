# Paper Results for Final Figures

This directory contains **tracked, paper-facing aggregate results** so a local
`git pull` is sufficient for Codex/plotting scripts to reproduce the final
paper figures.

It intentionally does **not** replace `outputs/results/`. Raw per-run JSON,
logs, and GitHub Actions artifacts remain ignored because they are bulky and
include intermediate/debug information.

The separately versioned [innovation evidence archive](innovation_20260925/README.md)
is an exception: it tracks compact original ZIP artifacts and provenance so the
new mechanism and resource audits remain available after Actions artifacts expire.
Its additional qualification rules do not rewrite the historical CSV statuses below.

## Files

| File | Intended figure / use |
|---|---|
| `dense_workload.csv` | Dense workload energy/gain/structure trends |
| `baseline_summary.csv` | Baseline energy/strict-feasibility comparison |
| `ablation.csv` | Elite-family ablation |
| `mec_count.csv` | MEC-count sensitivity |
| `uav_count.csv` | UAV-count sensitivity |
| `contact_budget.csv` | Direct contact-opportunity sensitivity |
| `bandwidth_sensitivity.csv` | Bandwidth sensitivity + Stage-1 shadow prices |
| `coverage_radius.csv` | Contact-geometry robustness |
| `spatial_robustness.csv` | Spatial-distribution robustness |
| `iteration_budget.csv` | Iteration-budget sensitivity |
| `strong_reference.csv` | Reduced-scale best-known reference benchmark |
| `real_geography.csv` | Stanislaus real-geography formal summary |

## Statistical rules

- Main energy uses **strict Stage-1 CVX energy only**.
- A row marked as a strict subset must not be described as if all scheduled runs
  were strict.
- Stage-2 QoS/resource metrics exclude non-strict Stage-2 rows.
- Greedy and FR-NM are deterministic: repeated algorithm seeds are not
  independent baseline samples.
- K=100,E=2 energy/QoS values are from the 3/9 strict subset.
- M=3 with 0/9 strict means no strict terminal solution was recovered under the
  frozen search budget; it is not a global infeasibility claim.
- Stage-2 bandwidth utilization is descriptive only. Resource bottleneck claims
  use Stage-1 relative shadow prices plus explicit scaling experiments.
- Strong-reference gaps are gaps to an empirical best-known solution, **not**
  global-optimality gaps.
- The Stanislaus experiment is a GIS-driven real-geography case study, not a
  field-flight experiment.

## Source-of-truth notes

These CSVs are compact publication summaries transcribed from completed formal
workflows and the repository experiment summaries. Keep the raw workflow
artifacts for audit/reproduction, but use these files as the plotting interface.

See also:

- `docs/paper_figure_design_spec.md`
- `docs/paper_experiment_summary.md`
- `docs/current_research_achievements.md`
