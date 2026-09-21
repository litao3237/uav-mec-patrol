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
            raise ValueError(f"Incomplete workload file: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No workload rows found in {input_dir}")
    return rows


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "std": None}
    return {
        "mean": mean(values),
        "median": median(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
    }


def _group(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    subset = [row for row in rows if int(row["K"]) == k]
    generic = [
        row
        for row in subset
        if row["base_stage1_status"] == "optimal"
        and row["base_cvx_energy_j"] is not None
    ]
    hybrid = [
        row
        for row in subset
        if row["hybrid_stage1_status"] == "optimal"
        and row["hybrid_cvx_energy_j"] is not None
    ]
    paired = [
        row
        for row in subset
        if row["base_stage1_status"] == "optimal"
        and row["hybrid_stage1_status"] == "optimal"
        and row["base_cvx_energy_j"] is not None
        and row["hybrid_cvx_energy_j"] is not None
    ]
    return {
        "K": k,
        "runs": len(subset),
        "generic_strict": len(generic),
        "hybrid_strict": len(hybrid),
        "generic_strict_rate": len(generic) / len(subset) if subset else 0.0,
        "hybrid_strict_rate": len(hybrid) / len(subset) if subset else 0.0,
        "generic_energy_j": _stats(
            [float(row["base_cvx_energy_j"]) for row in generic]
        ),
        "hybrid_energy_j": _stats(
            [float(row["hybrid_cvx_energy_j"]) for row in hybrid]
        ),
        "paired_gain_pct": _stats(
            [
                float(row["improvement_pct"])
                for row in paired
                if row["improvement_pct"] is not None
            ]
        ),
        "offload_ratio": _stats(
            [
                float(row["hybrid_solution"]["offloaded"])
                / max(1, int(row["K"]))
                for row in hybrid
            ]
        ),
        "contacts_per_uav": _stats(
            [
                float(row["hybrid_solution"]["contacts"])
                / max(1, int(row["M"]))
                for row in hybrid
            ]
        ),
        "route_distance_km": _stats(
            [
                float(row["hybrid_solution"]["distance_m"]) / 1000.0
                for row in hybrid
            ]
        ),
        "runtime_s": _stats(
            [float(row["total_runtime_s"]) for row in subset]
        ),
    }


def _write_csv(path: Path, aggregate: list[dict[str, Any]]) -> None:
    fields = [
        "K",
        "runs",
        "generic_strict",
        "hybrid_strict",
        "generic_strict_rate",
        "hybrid_strict_rate",
        "generic_energy_mean_j",
        "hybrid_energy_mean_j",
        "paired_gain_mean_pct",
        "offload_ratio_mean",
        "contacts_per_uav_mean",
        "route_distance_km_mean",
        "runtime_mean_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for group in aggregate:
            writer.writerow(
                {
                    "K": group["K"],
                    "runs": group["runs"],
                    "generic_strict": group["generic_strict"],
                    "hybrid_strict": group["hybrid_strict"],
                    "generic_strict_rate": group["generic_strict_rate"],
                    "hybrid_strict_rate": group["hybrid_strict_rate"],
                    "generic_energy_mean_j": group["generic_energy_j"]["mean"],
                    "hybrid_energy_mean_j": group["hybrid_energy_j"]["mean"],
                    "paired_gain_mean_pct": group["paired_gain_pct"]["mean"],
                    "offload_ratio_mean": group["offload_ratio"]["mean"],
                    "contacts_per_uav_mean": group["contacts_per_uav"]["mean"],
                    "route_distance_km_mean": group["route_distance_km"]["mean"],
                    "runtime_mean_s": group["runtime_s"]["mean"],
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate dense workload headline metrics."
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
                "study": "dense_workload_curve",
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
        "K runs G-strict H-strict G-E-J H-E-J gain-% offload "
        "contacts/UAV dist-km runtime-s"
    )
    print("-" * 98)
    for group in aggregate:
        def fmt(block: str) -> str:
            value = group[block]["mean"]
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{group['K']:<3} {group['runs']:<4} "
            f"{group['generic_strict']:<8} {group['hybrid_strict']:<8} "
            f"{fmt('generic_energy_j'):<10} "
            f"{fmt('hybrid_energy_j'):<10} "
            f"{fmt('paired_gain_pct'):<7} "
            f"{fmt('offload_ratio'):<7} "
            f"{fmt('contacts_per_uav'):<12} "
            f"{fmt('route_distance_km'):<7} "
            f"{fmt('runtime_s')}"
        )

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
