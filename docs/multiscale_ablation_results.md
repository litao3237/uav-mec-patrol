# Multi-scale elite-family ablation results

## Provenance

- Branch: `experiment/multiscale-ablation-expansion`
- Corrected protocol commit: `78b5d6dd9c220496ac7c85fbadfbb7a73ba0a206`
- GitHub Actions run: `35829109278`
- Workloads: K = 30, 50, 70, 80
- Independent scenarios: S45-S47
- Algorithm repetitions: A100-A102
- Each (K, scenario, algorithm seed) uses one shared B-ALNS exploration, then forks into all five elite profiles.
- Strict pair definition: Stage-1 status is exactly `optimal` for both full and ablated solutions.
- `no-batch` disables explicit batch merge and batch split only; mode/batch reassignment remains enabled.

## Main findings

The table in `paper_results/multiscale_ablation_summary.csv` reports the paired advantage of full ESI-ALNS over each ablated profile using

[
100 (E_{ablated}-E_{full}) / E_{ablated}.
]

Route-compute relocation is the dominant family once workload reaches K >= 50:
- K30: 0/9 better, mean 0.000%
- K50: 5/9 better, mean 1.324%
- K70: 4/9 better, mean 0.767%
- K80: 6/9 better, mean 0.709%

Contact operations are inactive at K30-K50, become weakly relevant at K70, and are most visible at K80 (3 better / 5 equal / 1 ablated-better; mean full advantage 0.302%).

Explicit batch merge/split is intermittent: one improved pair at K30, one at K50, none at K70, and a mixed 2/6/1 result at K80. Progressive widening has zero aggregate difference at all four tested workloads.

These results support a workload-dependent mechanism interpretation. They do not support a claim that every ESI family contributes monotonically or uniformly across workloads.
