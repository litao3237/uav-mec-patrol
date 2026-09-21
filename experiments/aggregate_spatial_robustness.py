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
            raise ValueError(f"Incomplete spatial file: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No spatial rows found in {input_dir}")
    return rows


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "std": None}
    return {
        "mean": mean(values),
        "median": median(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
    }


def _group(rows: list[dict[str, Any]], profile: str) -> dict[str, Any]:
    subset = [
        row
        for row in rows
        if row.get("task_spatial_profile", "uniform") == profile
    ]
    strict = [
        row
        for row in subset
        if row["hybrid_stage1_status"] == "optimal"
        and row["hybrid_cvx_energy_j"] is not None
    ]
    stage2 = [
        row
        for row in strict
        if (
            row.get("paper_metrics") is not None
            and row["paper_metrics"].get("stage2_status") == "optimal"
        )
    ]
    paired = [
        row
        for row in strict
        if row["base_stage1_status"] == "optimal"
        and row["base_cvx_energy_j"] is not None
    ]

    return {
        "profile": profile,
        "runs": len(subset),
        "strict_stage1": len(strict),
        "strict_stage1_rate": len(strict) / len(subset) if subset else 0.0,
        "strict_stage2": len(stage2),
        "hybrid_energy_j": _stats(
            [float(row["hybrid_cvx_energy_j"]) for row in strict]
        ),
        "hybrid_vs_generic_gain_pct": _stats(
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
                for row in strict
            ]
        ),
        "contacts_per_uav": _stats(
            [
                float(row["hybrid_solution"]["contacts"])
                / max(1, int(row["M"]))
                for row in strict
            ]
        ),
        "route_distance_km": _stats(
            [
                float(row["hybrid_solution"]["distance_m"]) / 1000.0
                for row in strict
            ]
        ),
        "delay_s": _stats(
            [
                float(row["paper_metrics"]["avg_delay_s"])
                for row in stage2
            ]
        ),
        "deadline_slack_s": _stats(
            [
                float(row["paper_metrics"]["mean_deadline_slack_s"])
                for row in stage2
            ]
        ),
        "bandwidth_utilization": _stats(
            [
                float(
                    row["paper_metrics"][
                        "mean_active_mec_bandwidth_utilization"
                    ]
                )
                for row in stage2
            ]
        ),
        "cpu_utilization": _stats(
            [
                float(
                    row["paper_metrics"][
                        "mean_active_mec_cpu_utilization"
                    ]
                )
                for row in stage2
            ]
        ),
        "runtime_s": _stats(
            [float(row["total_runtime_s"]) for row in subset]
        ),
    }


def _write_csv(path: Path, aggregate: list[dict[str, Any]]) -> None:
    fields = [
        "profile",
        "runs",
        "strict_stage1",
        "strict_stage1_rate",
        "strict_stage2",
        "energy_mean_j",
        "gain_mean_pct",
        "offload_ratio_mean",
        "contacts_per_uav_mean",
        "route_distance_km_mean",
        "delay_mean_s",
        "deadline_slack_mean_s",
        "bandwidth_util_mean",
        "cpu_util_mean",
        "runtime_mean_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for group in aggregate:
            writer.writerow(
                {
                    "profile": group["profile"],
                    "runs": group["runs"],
                    "strict_stage1": group["strict_stage1"],
                    "strict_stage1_rate": group["strict_stage1_rate"],
                    "strict_stage2": group["strict_stage2"],
                    "energy_mean_j": group["hybrid_energy_j"]["mean"],
                    "gain_mean_pct": (
                        group["hybrid_vs_generic_gain_pct"]["mean"]
                    ),
                    "offload_ratio_mean": group["offload_ratio"]["mean"],
                    "contacts_per_uav_mean": (
                        group["contacts_per_uav"]["mean"]
                    ),
                    "route_distance_km_mean": (
                        group["route_distance_km"]["mean"]
                    ),
                    "delay_mean_s": group["delay_s"]["mean"],
                    "deadline_slack_mean_s": (
                        group["deadline_slack_s"]["mean"]
                    ),
                    "bandwidth_util_mean": (
                        group["bandwidth_utilization"]["mean"]
                    ),
                    "cpu_util_mean": group["cpu_utilization"]["mean"],
                    "runtime_mean_s": group["runtime_s"]["mean"],
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate spatial-distribution robustness runs."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows = _load(Path(args.input_dir))
    order = ["uniform", "clustered", "boundary"]
    present = {str(row.get("task_spatial_profile", "uniform")) for row in rows}
    profiles = [profile for profile in order if profile in present]
    profiles.extend(sorted(present.difference(profiles)))
    aggregate = [_group(rows, profile) for profile in profiles]

    json_path = Path(args.output_json)
    csv_path = Path(args.output_csv)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "complete": True,
                "study": "spatial_distribution_robustness",
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
        "profile runs strict s2 energy-J gain-% offload contacts/UAV "
        "dist-km delay-s slack-s bw-util cpu-util runtime-s"
    )
    print("-" * 125)
    for group in aggregate:
        def fmt(block: str) -> str:
            value = group[block]["mean"]
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{group['profile']:<10} "
            f"{group['runs']:<4} "
            f"{group['strict_stage1']:<6} "
            f"{group['strict_stage2']:<2} "
            f"{fmt('hybrid_energy_j'):<9} "
            f"{fmt('hybrid_vs_generic_gain_pct'):<6} "
            f"{fmt('offload_ratio'):<7} "
            f"{fmt('contacts_per_uav'):<12} "
            f"{fmt('route_distance_km'):<7} "
            f"{fmt('delay_s'):<7} "
            f"{fmt('deadline_slack_s'):<7} "
            f"{fmt('bandwidth_utilization'):<7} "
            f"{fmt('cpu_utilization'):<8} "
            f"{fmt('runtime_s')}"
        )

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
