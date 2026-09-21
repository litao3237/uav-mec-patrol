from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


def _load(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete benchmark file: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No benchmark rows found in {input_dir}")
    return rows


def _pct_within(values: list[float], threshold: float) -> float:
    if not values:
        return 0.0
    return sum(value <= threshold for value in values) / len(values)


def _group(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    subset = [row for row in rows if int(row["K"]) == k]
    standards = [row for row in subset if row["mode"] == "standard"]
    strong = [row for row in subset if row["mode"] == "strong"]
    standard_strict = [
        row for row in standards if row["strict_energy_j"] is not None
    ]
    strong_strict = [
        row for row in strong if row["strict_energy_j"] is not None
    ]
    standard_gaps = [
        float(row["gap_to_best_known_pct"])
        for row in standard_strict
        if row["gap_to_best_known_pct"] is not None
    ]

    scenarios = sorted({int(row["scenario_seed"]) for row in subset})
    scenario_refs: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_rows = [
            row
            for row in subset
            if int(row["scenario_seed"]) == scenario
        ]
        ref_values = {
            float(row["best_known_energy_j"])
            for row in scenario_rows
            if row["best_known_energy_j"] is not None
        }
        if len(ref_values) > 1:
            raise ValueError(
                f"Inconsistent best-known values for K={k}, scenario={scenario}"
            )
        best_known = next(iter(ref_values)) if ref_values else None
        strong_rows = [
            row for row in scenario_rows if row["mode"] == "strong"
        ]
        standard_rows = [
            row for row in scenario_rows if row["mode"] == "standard"
        ]
        strong_hits = sum(
            bool(row["is_best_known_hit"]) for row in strong_rows
        )
        standard_hits = sum(
            bool(row["is_best_known_hit"]) for row in standard_rows
        )
        hit_rows = [
            row
            for row in scenario_rows
            if row["is_best_known_hit"]
            and row["strict_energy_j"] is not None
        ]
        best_structure = (
            hit_rows[0]["solution"] if hit_rows else None
        )
        scenario_refs.append(
            {
                "scenario_seed": scenario,
                "best_known_energy_j": best_known,
                "best_known_contacts": (
                    best_structure["contacts"]
                    if best_structure is not None
                    else None
                ),
                "best_known_offloaded": (
                    best_structure["offloaded"]
                    if best_structure is not None
                    else None
                ),
                "best_known_distance_m": (
                    best_structure["distance_m"]
                    if best_structure is not None
                    else None
                ),
                "nondegenerate_reference": bool(
                    best_structure is not None
                    and (
                        best_structure["contacts"] > 0
                        or best_structure["offloaded"] > 0
                    )
                ),
                "strong_hits": strong_hits,
                "strong_runs": len(strong_rows),
                "standard_hits": standard_hits,
                "standard_runs": len(standard_rows),
            }
        )

    strong_runtimes = [
        float(row["runtime_s"]) for row in strong
    ]
    standard_runtimes = [
        float(row["runtime_s"]) for row in standards
    ]

    return {
        "K": k,
        "scenarios": len(scenarios),
        "standard_runs": len(standards),
        "standard_strict": len(standard_strict),
        "strong_runs": len(strong),
        "strong_strict": len(strong_strict),
        "standard_gap_mean_pct": (
            mean(standard_gaps) if standard_gaps else None
        ),
        "standard_gap_median_pct": (
            median(standard_gaps) if standard_gaps else None
        ),
        "standard_gap_std_pct": (
            stdev(standard_gaps) if len(standard_gaps) > 1 else 0.0
        ),
        "standard_gap_max_pct": (
            max(standard_gaps) if standard_gaps else None
        ),
        "standard_within_0_01pct": _pct_within(
            standard_gaps,
            0.01,
        ),
        "standard_within_0_1pct": _pct_within(
            standard_gaps,
            0.1,
        ),
        "standard_within_1pct": _pct_within(
            standard_gaps,
            1.0,
        ),
        "nondegenerate_reference_scenarios": sum(
            bool(ref["nondegenerate_reference"])
            for ref in scenario_refs
        ),
        "strong_best_known_hits": sum(
            bool(row["is_best_known_hit"]) for row in strong
        ),
        "strong_best_known_hit_rate": (
            sum(bool(row["is_best_known_hit"]) for row in strong)
            / len(strong)
            if strong
            else 0.0
        ),
        "standard_best_known_hits": sum(
            bool(row["is_best_known_hit"]) for row in standards
        ),
        "mean_standard_runtime_s": (
            mean(standard_runtimes) if standard_runtimes else None
        ),
        "mean_strong_runtime_s": (
            mean(strong_runtimes) if strong_runtimes else None
        ),
        "scenario_references": scenario_refs,
    }


def _write_csv(path: Path, aggregate: list[dict[str, Any]]) -> None:
    fields = [
        "K",
        "scenarios",
        "standard_runs",
        "standard_strict",
        "strong_runs",
        "strong_strict",
        "standard_gap_mean_pct",
        "standard_gap_median_pct",
        "standard_gap_std_pct",
        "standard_gap_max_pct",
        "standard_within_0_01pct",
        "standard_within_0_1pct",
        "standard_within_1pct",
        "nondegenerate_reference_scenarios",
        "strong_best_known_hits",
        "strong_best_known_hit_rate",
        "standard_best_known_hits",
        "mean_standard_runtime_s",
        "mean_strong_runtime_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in aggregate:
            writer.writerow(
                {field: row.get(field) for field in fields}
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate small best-known strong-reference benchmarks."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows = _load(Path(args.input_dir))
    task_counts = sorted({int(row["K"]) for row in rows})
    aggregate = [_group(rows, k) for k in task_counts]

    json_path = Path(args.output_json)
    csv_path = Path(args.output_csv)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(
            {
                "complete": True,
                "benchmark_type": "best_known_strong_reference",
                "global_optimality_claim": False,
                "aggregate": aggregate,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_csv(csv_path, aggregate)

    print(
        "K    std-strict strong-strict mean-gap-% med-gap-% max-gap-% "
        "<=0.01% <=0.1% <=1% strong-hit-rate std-s strong-s"
    )
    print("-" * 118)
    for group in aggregate:
        def fmt(value: float | None) -> str:
            return "-" if value is None else f"{value:.6f}"

        print(
            f"{group['K']:<4} "
            f"{group['standard_strict']}/{group['standard_runs']:<8} "
            f"{group['strong_strict']}/{group['strong_runs']:<10} "
            f"{fmt(group['standard_gap_mean_pct']):<10} "
            f"{fmt(group['standard_gap_median_pct']):<9} "
            f"{fmt(group['standard_gap_max_pct']):<9} "
            f"{group['standard_within_0_01pct']:<8.3f} "
            f"{group['standard_within_0_1pct']:<7.3f} "
            f"{group['standard_within_1pct']:<5.3f} "
            f"{group['strong_best_known_hit_rate']:<15.3f} "
            f"{fmt(group['mean_standard_runtime_s']):<6} "
            f"{fmt(group['mean_strong_runtime_s'])}"
        )

    print("\nScenario references")
    for group in aggregate:
        for ref in group["scenario_references"]:
            best = ref["best_known_energy_j"]
            best_text = "-" if best is None else f"{best:.6f}"
            print(
                f"K={group['K']} S={ref['scenario_seed']} "
                f"best_known={best_text} J "
                f"contacts={ref['best_known_contacts']} "
                f"offloaded={ref['best_known_offloaded']} "
                f"nondegenerate={ref['nondegenerate_reference']} "
                f"strong_hits={ref['strong_hits']}/{ref['strong_runs']} "
                f"standard_hits={ref['standard_hits']}/{ref['standard_runs']}"
            )

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
