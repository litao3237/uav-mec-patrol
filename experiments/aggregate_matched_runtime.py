from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


METHODS = (
    "gr_mr",
    "ftr_nm",
    "rga_mr",
    "b_alns",
    "esi_alns",
)


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


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result: {path}")
        for row in payload.get("rows", []):
            enriched = dict(row)
            enriched["_source"] = path.name
            rows.append(enriched)
    if not rows:
        raise ValueError(f"No result rows found in {input_dir}")
    return rows


def _method_records(
    rows: list[dict[str, Any]],
    *,
    k: int,
    budget_factor: int,
    method: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    result = []
    for row in rows:
        if int(row["K"]) != k:
            continue
        if int(row["budget_factor"]) != budget_factor:
            continue
        record = row.get("methods", {}).get(method)
        if record is not None:
            result.append((row, record))
    return result


def _method_summary(
    rows: list[dict[str, Any]],
    *,
    k: int,
    budget_factor: int,
    method: str,
) -> dict[str, Any] | None:
    records = _method_records(
        rows,
        k=k,
        budget_factor=budget_factor,
        method=method,
    )
    if not records:
        return None

    strict = [
        (row, record)
        for row, record in records
        if record["energy_j"] is not None
        and record["stage1_status"] == "optimal"
    ]
    energies = [float(record["energy_j"]) for _, record in strict]
    search_runtime = [
        float(record["search_runtime_s"])
        for _, record in records
    ]
    overrun = [
        float(record["search_budget_overrun_s"])
        for _, record in records
        if record["search_budget_overrun_s"] is not None
    ]
    verify_runtime = [
        float(record["stage1_verification_runtime_s"])
        for _, record in records
    ]
    metrics_runtime = [
        float(record["stage2_metrics_runtime_s"])
        for _, record in records
    ]

    contacts = [
        float(record["solution"]["contacts"])
        for _, record in strict
    ]
    offloaded = [
        float(record["solution"]["offloaded"])
        for _, record in strict
    ]
    distance_km = [
        float(record["solution"]["distance_m"]) / 1000.0
        for _, record in strict
    ]

    stage2 = [
        record["paper_metrics"]
        for _, record in strict
        if (
            record.get("paper_metrics") is not None
            and record["paper_metrics"].get("stage2_status") == "optimal"
        )
    ]

    def pm(name: str) -> list[float]:
        return [
            float(metrics[name])
            for metrics in stage2
            if metrics.get(name) is not None
        ]

    diagnostics = [record.get("diagnostics", {}) for _, record in records]
    work_values: dict[str, list[float]] = defaultdict(list)
    for diag in diagnostics:
        for key in (
            "completed_iterations",
            "completed_generations",
            "distinct_evaluations",
            "elite_cvx_calls",
            "screened_cvx_refinements",
        ):
            if diag.get(key) is not None:
                work_values[key].append(float(diag[key]))

    return {
        "K": k,
        "budget_factor": budget_factor,
        "time_budget_s": float(records[0][0]["time_budget_s"]),
        "method": method,
        "runs": len(records),
        "independent_scenarios": len(
            {int(row["scenario_seed"]) for row, _ in records}
        ),
        "strict_optimal": len(strict),
        "strict_rate": len(strict) / len(records),
        "energy_j": _stats(energies),
        "search_runtime_s": _stats(search_runtime),
        "search_budget_overrun_s": _stats(overrun),
        "stage1_verification_runtime_s": _stats(verify_runtime),
        "stage2_metrics_runtime_s": _stats(metrics_runtime),
        "contacts": _stats(contacts),
        "offloaded_tasks": _stats(offloaded),
        "route_distance_km": _stats(distance_km),
        "stage2_strict": len(stage2),
        "avg_delay_s": _stats(pm("avg_delay_s")),
        "mean_deadline_slack_s": _stats(
            pm("mean_deadline_slack_s")
        ),
        "max_cycle_utilization": _stats(
            pm("max_cycle_utilization")
        ),
        "max_battery_utilization": _stats(
            pm("max_battery_utilization")
        ),
        "mean_active_mec_bandwidth_relative_shadow": _stats(
            pm("mean_active_mec_bandwidth_relative_shadow")
        ),
        "mean_active_mec_cpu_relative_shadow": _stats(
            pm("mean_active_mec_cpu_relative_shadow")
        ),
        "work": {
            key: _stats(values)
            for key, values in sorted(work_values.items())
        },
    }


def _paired(
    rows: list[dict[str, Any]],
    *,
    k: int,
    budget_factor: int,
    baseline: str,
) -> dict[str, Any]:
    gains: list[float] = []
    scenario_gains: dict[int, list[float]] = defaultdict(list)
    strict_pairs = 0

    for row in rows:
        if int(row["K"]) != k:
            continue
        if int(row["budget_factor"]) != budget_factor:
            continue
        methods = row.get("methods", {})
        base = methods.get(baseline)
        esi = methods.get("esi_alns")
        if base is None or esi is None:
            continue
        base_energy = base.get("energy_j")
        esi_energy = esi.get("energy_j")
        if base_energy is None or esi_energy is None:
            continue
        if (
            base.get("stage1_status") != "optimal"
            or esi.get("stage1_status") != "optimal"
        ):
            continue

        strict_pairs += 1
        gain = (
            100.0
            * (float(base_energy) - float(esi_energy))
            / max(1.0, abs(float(base_energy)))
        )
        gains.append(gain)
        scenario_gains[int(row["scenario_seed"])].append(gain)

    scenario_means = {
        scenario: mean(values)
        for scenario, values in sorted(scenario_gains.items())
    }
    scenario_values = list(scenario_means.values())

    return {
        "baseline": baseline,
        "strict_pairs": strict_pairs,
        "better": sum(value > 1e-9 for value in gains),
        "equal": sum(abs(value) <= 1e-9 for value in gains),
        "baseline_better": sum(value < -1e-9 for value in gains),
        "run_level_gain_pct": _stats(gains),
        "scenario_level_gain_pct": _stats(scenario_values),
        "scenario_means_pct": scenario_means,
        "positive_scenarios": sum(
            value > 1e-9 for value in scenario_values
        ),
        "equal_scenarios": sum(
            abs(value) <= 1e-9 for value in scenario_values
        ),
        "baseline_better_scenarios": sum(
            value < -1e-9 for value in scenario_values
        ),
    }


def _write_csv(
    path: Path,
    summaries: list[dict[str, Any]],
) -> None:
    fields = [
        "K",
        "budget_factor",
        "time_budget_s",
        "method",
        "runs",
        "independent_scenarios",
        "strict_optimal",
        "strict_rate",
        "mean_energy_j",
        "median_energy_j",
        "mean_search_runtime_s",
        "mean_budget_overrun_s",
        "mean_stage1_verify_s",
        "stage2_strict",
        "mean_avg_delay_s",
        "mean_deadline_slack_s",
        "mean_contacts",
        "mean_offloaded_tasks",
        "mean_route_distance_km",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in summaries:
            writer.writerow(
                {
                    "K": item["K"],
                    "budget_factor": item["budget_factor"],
                    "time_budget_s": item["time_budget_s"],
                    "method": item["method"],
                    "runs": item["runs"],
                    "independent_scenarios": item[
                        "independent_scenarios"
                    ],
                    "strict_optimal": item["strict_optimal"],
                    "strict_rate": item["strict_rate"],
                    "mean_energy_j": item["energy_j"]["mean"],
                    "median_energy_j": item["energy_j"]["median"],
                    "mean_search_runtime_s": item[
                        "search_runtime_s"
                    ]["mean"],
                    "mean_budget_overrun_s": item[
                        "search_budget_overrun_s"
                    ]["mean"],
                    "mean_stage1_verify_s": item[
                        "stage1_verification_runtime_s"
                    ]["mean"],
                    "stage2_strict": item["stage2_strict"],
                    "mean_avg_delay_s": item["avg_delay_s"]["mean"],
                    "mean_deadline_slack_s": item[
                        "mean_deadline_slack_s"
                    ]["mean"],
                    "mean_contacts": item["contacts"]["mean"],
                    "mean_offloaded_tasks": item[
                        "offloaded_tasks"
                    ]["mean"],
                    "mean_route_distance_km": item[
                        "route_distance_km"
                    ]["mean"],
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    rows = _load_rows(Path(args.input_dir))
    ks = sorted({int(row["K"]) for row in rows})
    factors = sorted(
        {int(row["budget_factor"]) for row in rows}
    )

    summaries: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []
    for k in ks:
        for factor in factors:
            for method in METHODS:
                summary = _method_summary(
                    rows,
                    k=k,
                    budget_factor=factor,
                    method=method,
                )
                if summary is not None:
                    summaries.append(summary)

            for baseline in ("b_alns", "rga_mr"):
                paired.append(
                    {
                        "K": k,
                        "budget_factor": factor,
                        **_paired(
                            rows,
                            k=k,
                            budget_factor=factor,
                            baseline=baseline,
                        ),
                    }
                )

    output_json = Path(args.output_json)
    output_csv = Path(args.output_csv)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {
                "complete": True,
                "summaries": summaries,
                "paired": paired,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_csv(output_csv, summaries)

    for item in summaries:
        print(
            f"K={item['K']} "
            f"B={item['time_budget_s']:.0f}s "
            f"{item['method']}: "
            f"strict={item['strict_optimal']}/{item['runs']} "
            f"E={item['energy_j']['mean']} "
            f"search={item['search_runtime_s']['mean']:.3f}s "
            f"overrun={item['search_budget_overrun_s']['mean']}"
        )
    for item in paired:
        print(
            f"PAIR K={item['K']} x{item['budget_factor']} "
            f"ESI vs {item['baseline']}: "
            f"n={item['strict_pairs']} "
            f"gain={item['run_level_gain_pct']['mean']}% "
            f"scenario_gain={item['scenario_level_gain_pct']['mean']}%"
        )

    print(f"Saved JSON: {output_json}")
    print(f"Saved CSV:  {output_csv}")


if __name__ == "__main__":
    main()
