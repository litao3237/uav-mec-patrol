from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result file: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No result rows found in {input_dir}")
    return rows


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
        }
    return {
        "mean": mean(values),
        "median": median(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _group(
    rows: list[dict[str, Any]],
    *,
    field: str,
    value: float,
) -> dict[str, Any]:
    subset = [
        row
        for row in rows
        if abs(float(row[field]) - value) <= 1e-12
    ]
    strict = [
        row
        for row in subset
        if row["hybrid_stage1_status"] == "optimal"
    ]
    stage2 = [
        row
        for row in strict
        if (
            row.get("paper_metrics") is not None
            and row["paper_metrics"].get("stage2_status") == "optimal"
        )
    ]

    energies = [
        float(row["hybrid_cvx_energy_j"])
        for row in strict
        if row["hybrid_cvx_energy_j"] is not None
    ]
    offloads = [
        float(row["hybrid_solution"]["offloaded"]) / max(1, int(row["K"]))
        for row in strict
    ]
    contacts = [
        float(row["hybrid_solution"]["contacts"]) / max(1, int(row["M"]))
        for row in strict
    ]
    distances = [
        float(row["hybrid_solution"]["distance_m"]) / 1000.0
        for row in strict
    ]
    delays = [
        float(row["paper_metrics"]["avg_delay_s"])
        for row in stage2
    ]
    slacks = [
        float(row["paper_metrics"]["mean_deadline_slack_s"])
        for row in stage2
    ]
    bandwidth = [
        float(
            row["paper_metrics"][
                "mean_active_mec_bandwidth_utilization"
            ]
        )
        for row in stage2
    ]
    cpu = [
        float(
            row["paper_metrics"][
                "mean_active_mec_cpu_utilization"
            ]
        )
        for row in stage2
    ]
    improvements = [
        float(row["improvement_pct"])
        for row in strict
        if row.get("improvement_pct") is not None
    ]
    runtimes = [
        float(row["total_runtime_s"])
        for row in subset
    ]

    return {
        "sensitivity_field": field,
        "scale": value,
        "runs": len(subset),
        "strict_stage1": len(strict),
        "strict_stage1_rate": len(strict) / len(subset) if subset else 0.0,
        "strict_stage2": len(stage2),
        "energy_j": _stats(energies),
        "offload_ratio": _stats(offloads),
        "contacts_per_uav": _stats(contacts),
        "route_distance_km": _stats(distances),
        "delay_s": _stats(delays),
        "deadline_slack_s": _stats(slacks),
        "active_mec_bandwidth_utilization": _stats(bandwidth),
        "active_mec_cpu_utilization": _stats(cpu),
        "hybrid_vs_generic_gain_pct": _stats(improvements),
        "runtime_s": _stats(runtimes),
    }


def _write_csv(path: Path, aggregate: list[dict[str, Any]]) -> None:
    fields = [
        "sensitivity_field",
        "scale",
        "runs",
        "strict_stage1",
        "strict_stage1_rate",
        "strict_stage2",
        "energy_mean_j",
        "energy_median_j",
        "offload_ratio_mean",
        "contacts_per_uav_mean",
        "route_distance_km_mean",
        "delay_mean_s",
        "deadline_slack_mean_s",
        "bandwidth_util_mean",
        "cpu_util_mean",
        "hybrid_vs_generic_gain_mean_pct",
        "runtime_mean_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for group in aggregate:
            writer.writerow(
                {
                    "sensitivity_field": group["sensitivity_field"],
                    "scale": group["scale"],
                    "runs": group["runs"],
                    "strict_stage1": group["strict_stage1"],
                    "strict_stage1_rate": group["strict_stage1_rate"],
                    "strict_stage2": group["strict_stage2"],
                    "energy_mean_j": group["energy_j"]["mean"],
                    "energy_median_j": group["energy_j"]["median"],
                    "offload_ratio_mean": group["offload_ratio"]["mean"],
                    "contacts_per_uav_mean": group["contacts_per_uav"]["mean"],
                    "route_distance_km_mean": group["route_distance_km"]["mean"],
                    "delay_mean_s": group["delay_s"]["mean"],
                    "deadline_slack_mean_s": group["deadline_slack_s"]["mean"],
                    "bandwidth_util_mean": (
                        group["active_mec_bandwidth_utilization"]["mean"]
                    ),
                    "cpu_util_mean": (
                        group["active_mec_cpu_utilization"]["mean"]
                    ),
                    "hybrid_vs_generic_gain_mean_pct": (
                        group["hybrid_vs_generic_gain_pct"]["mean"]
                    ),
                    "runtime_mean_s": group["runtime_s"]["mean"],
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate MEC bandwidth or coverage-radius sensitivity runs."
        )
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument(
        "--field",
        choices=("mec_bandwidth_scale", "mec_radius_scale"),
        required=True,
    )
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows = _load_rows(Path(args.input_dir))
    values = sorted({float(row[args.field]) for row in rows})
    aggregate = [
        _group(rows, field=args.field, value=value)
        for value in values
    ]

    json_path = Path(args.output_json)
    csv_path = Path(args.output_csv)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(
            {
                "complete": True,
                "sensitivity_field": args.field,
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
        "scale runs strict s2 energy-J offload contacts/UAV dist-km "
        "delay-s slack-s bw-util cpu-util gain-% runtime-s"
    )
    print("-" * 126)
    for group in aggregate:
        def fmt(block: str, key: str = "mean") -> str:
            value = group[block][key]
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{group['scale']:<5.2f} "
            f"{group['runs']:<4} "
            f"{group['strict_stage1']:<6} "
            f"{group['strict_stage2']:<2} "
            f"{fmt('energy_j'):<9} "
            f"{fmt('offload_ratio'):<7} "
            f"{fmt('contacts_per_uav'):<12} "
            f"{fmt('route_distance_km'):<7} "
            f"{fmt('delay_s'):<7} "
            f"{fmt('deadline_slack_s'):<7} "
            f"{fmt('active_mec_bandwidth_utilization'):<7} "
            f"{fmt('active_mec_cpu_utilization'):<8} "
            f"{fmt('hybrid_vs_generic_gain_pct'):<6} "
            f"{fmt('runtime_s')}"
        )

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
