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
            raise ValueError(f"Incomplete convergence file: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No convergence rows found in {input_dir}")
    return rows


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "std": None}
    return {
        "mean": mean(values),
        "median": median(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
    }


def _group(rows: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    subset = [row for row in rows if int(row["iterations"]) == budget]
    strict = [
        row for row in subset if row["hybrid_energy_j"] is not None
    ]
    return {
        "iterations": budget,
        "runs": len(subset),
        "strict_runs": len(strict),
        "strict_rate": len(strict) / len(subset) if subset else 0.0,
        "hybrid_energy_j": _stats(
            [float(row["hybrid_energy_j"]) for row in strict]
        ),
        "gap_to_pair_best_pct": _stats(
            [
                float(row["gap_to_pair_best_pct"])
                for row in strict
                if row["gap_to_pair_best_pct"] is not None
            ]
        ),
        "hybrid_vs_generic_gain_pct": _stats(
            [
                float(row["hybrid_vs_generic_gain_pct"])
                for row in strict
                if row["hybrid_vs_generic_gain_pct"] is not None
            ]
        ),
        "runtime_s": _stats(
            [float(row["total_runtime_s"]) for row in subset]
        ),
        "elite_cvx_calls": _stats(
            [float(row["elite_cvx_calls"]) for row in subset]
        ),
    }


def _write_csv(path: Path, aggregate: list[dict[str, Any]]) -> None:
    fields = [
        "iterations",
        "runs",
        "strict_runs",
        "strict_rate",
        "energy_mean_j",
        "energy_median_j",
        "gap_mean_pct",
        "gap_median_pct",
        "gain_mean_pct",
        "runtime_mean_s",
        "elite_cvx_calls_mean",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for group in aggregate:
            writer.writerow(
                {
                    "iterations": group["iterations"],
                    "runs": group["runs"],
                    "strict_runs": group["strict_runs"],
                    "strict_rate": group["strict_rate"],
                    "energy_mean_j": group["hybrid_energy_j"]["mean"],
                    "energy_median_j": group["hybrid_energy_j"]["median"],
                    "gap_mean_pct": group["gap_to_pair_best_pct"]["mean"],
                    "gap_median_pct": group["gap_to_pair_best_pct"]["median"],
                    "gain_mean_pct": (
                        group["hybrid_vs_generic_gain_pct"]["mean"]
                    ),
                    "runtime_mean_s": group["runtime_s"]["mean"],
                    "elite_cvx_calls_mean": group["elite_cvx_calls"]["mean"],
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate paired iteration-budget convergence runs."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows = _load(Path(args.input_dir))
    budgets = sorted({int(row["iterations"]) for row in rows})
    aggregate = [_group(rows, budget) for budget in budgets]

    json_path = Path(args.output_json)
    csv_path = Path(args.output_csv)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "complete": True,
                "study": "iteration_budget_convergence",
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
        "iters runs strict rate energy-J gap-% gain-% runtime-s elite-cvx"
    )
    print("-" * 78)
    for group in aggregate:
        def fmt(block: str, key: str = "mean") -> str:
            value = group[block][key]
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{group['iterations']:<5} "
            f"{group['runs']:<4} "
            f"{group['strict_runs']:<6} "
            f"{group['strict_rate']:<5.3f} "
            f"{fmt('hybrid_energy_j'):<9} "
            f"{fmt('gap_to_pair_best_pct'):<6} "
            f"{fmt('hybrid_vs_generic_gain_pct'):<6} "
            f"{fmt('runtime_s'):<9} "
            f"{fmt('elite_cvx_calls')}"
        )

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
