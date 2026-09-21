from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


METRICS = (
    "energy_stage1_j",
    "avg_delay_s",
    "avg_delay_utilization",
    "mean_deadline_slack_s",
    "min_deadline_slack_s",
    "max_cycle_utilization",
    "max_battery_utilization",
    "total_distance_m",
    "route_detour_pct_vs_reference",
    "offload_ratio",
    "contacts_per_uav",
    "active_uav_mec_pairs",
    "mean_active_mec_bandwidth_utilization",
    "max_active_mec_bandwidth_utilization",
    "mean_active_mec_cpu_utilization",
    "max_active_mec_cpu_utilization",
    "fixed_energy_ratio",
    "communication_energy_ratio",
    "local_compute_energy_ratio",
)


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result file: {path}")
        for row in payload.get("rows", []):
            enriched = dict(row)
            enriched["_source"] = path.name
            rows.append(enriched)
    if not rows:
        raise ValueError(f"No result rows found in {input_dir}")
    return rows


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "std": None,
            "median": None,
            "min": None,
            "max": None,
        }
    return {
        "mean": mean(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def _group(
    rows: list[dict[str, Any]],
    key: tuple[int, int, int],
) -> dict[str, Any]:
    k, m, e = key
    subset = [
        row
        for row in rows
        if (
            int(row["K"]) == k
            and int(row["M"]) == m
            and int(row["E"]) == e
        )
    ]
    metric_rows = [
        row for row in subset if row.get("paper_metrics") is not None
    ]
    metrics: dict[str, Any] = {}
    for metric in METRICS:
        values = [
            float(row["paper_metrics"][metric])
            for row in metric_rows
            if row["paper_metrics"].get(metric) is not None
        ]
        metrics[metric] = _stats(values)

    stage2_counts: dict[str, int] = {}
    for row in metric_rows:
        status = str(row["paper_metrics"]["stage2_status"])
        stage2_counts[status] = stage2_counts.get(status, 0) + 1

    return {
        "K": k,
        "M": m,
        "E": e,
        "runs": len(subset),
        "strict_hybrid_runs": sum(
            row["hybrid_stage1_status"] == "optimal"
            for row in subset
        ),
        "paper_metric_runs": len(metric_rows),
        "paper_metric_errors": sum(
            row.get("paper_metrics_error") is not None
            for row in subset
        ),
        "stage2_status_counts": stage2_counts,
        "mean_algorithm_runtime_s": (
            mean(float(row["total_runtime_s"]) for row in subset)
            if subset
            else None
        ),
        "mean_metric_stage2_runtime_s": (
            mean(
                float(row.get("paper_metrics_stage2_runtime_s", 0.0))
                for row in subset
            )
            if subset
            else None
        ),
        "metrics": metrics,
    }


def _write_csv(path: Path, aggregate: list[dict[str, Any]]) -> None:
    fields = [
        "K",
        "M",
        "E",
        "runs",
        "strict_hybrid_runs",
        "paper_metric_runs",
        "paper_metric_errors",
        "stage2_optimal_runs",
        "mean_algorithm_runtime_s",
        "mean_metric_stage2_runtime_s",
    ]
    for metric in METRICS:
        fields.extend(
            [
                f"{metric}_mean",
                f"{metric}_std",
                f"{metric}_median",
            ]
        )

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for group in aggregate:
            row: dict[str, Any] = {
                "K": group["K"],
                "M": group["M"],
                "E": group["E"],
                "runs": group["runs"],
                "strict_hybrid_runs": group["strict_hybrid_runs"],
                "paper_metric_runs": group["paper_metric_runs"],
                "paper_metric_errors": group["paper_metric_errors"],
                "stage2_optimal_runs": group[
                    "stage2_status_counts"
                ].get("optimal", 0),
                "mean_algorithm_runtime_s": group[
                    "mean_algorithm_runtime_s"
                ],
                "mean_metric_stage2_runtime_s": group[
                    "mean_metric_stage2_runtime_s"
                ],
            }
            for metric in METRICS:
                stats = group["metrics"][metric]
                row[f"{metric}_mean"] = stats["mean"]
                row[f"{metric}_std"] = stats["std"]
                row[f"{metric}_median"] = stats["median"]
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate unified paper metrics by (K, M, E)."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows = _load_rows(Path(args.input_dir))
    keys = sorted(
        {
            (int(row["K"]), int(row["M"]), int(row["E"]))
            for row in rows
        }
    )
    aggregate = [_group(rows, key) for key in keys]

    json_path = Path(args.output_json)
    csv_path = Path(args.output_csv)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(
            {
                "complete": True,
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
        "K    M    E    runs strict metrics s2-opt "
        "energy-J delay-s slack-s offload contacts/UAV dist-km "
        "bw-util cpu-util fixed-share runtime-s"
    )
    print("-" * 154)
    for group in aggregate:
        metrics = group["metrics"]

        def m(name: str) -> str:
            value = metrics[name]["mean"]
            return "-" if value is None else f"{value:.3f}"

        distance = metrics["total_distance_m"]["mean"]
        distance_km = (
            "-"
            if distance is None
            else f"{float(distance) / 1000.0:.3f}"
        )
        print(
            f"{group['K']:<4} {group['M']:<4} {group['E']:<4} "
            f"{group['runs']:<4} "
            f"{group['strict_hybrid_runs']:<6} "
            f"{group['paper_metric_runs']:<7} "
            f"{group['stage2_status_counts'].get('optimal', 0):<6} "
            f"{m('energy_stage1_j'):<9} "
            f"{m('avg_delay_s'):<7} "
            f"{m('mean_deadline_slack_s'):<7} "
            f"{m('offload_ratio'):<7} "
            f"{m('contacts_per_uav'):<12} "
            f"{distance_km:<7} "
            f"{m('mean_active_mec_bandwidth_utilization'):<7} "
            f"{m('mean_active_mec_cpu_utilization'):<8} "
            f"{m('fixed_energy_ratio'):<11} "
            f"{group['mean_algorithm_runtime_s']:.3f}"
        )

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
