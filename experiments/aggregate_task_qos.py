"""Aggregate only freshly executed task-QoS runs; never infer curves from v25.

Scenario-first averaging avoids treating nested algorithm seeds as independent maps.
All planned rows count toward completion, regardless of whether their tasks were late.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
from statistics import mean

from uav_mec.analysis.task_metrics import REQUIRED_TASK_QOS_FIELDS

SUMMARY_METRICS = (
    "success_rate", "mean_delay_all", "p95_delay_all", "total_energy",
    "energy_per_successful_task", "mec_cpu_utilization", "runtime",
    "deadline_violation_rate", "strict_all_tasks_success",
    "served_tasks", "stage1_energy", "stage2_energy",
    "route_distance", "unserved_rate",
)


def _expected_schedule_rows(data: dict) -> set[tuple]:
    expected = set()
    for group, seed in data["execution_schedule"]:
        methods = ("B-ALNS", "ESI-ALNS") if group == "B/ESI" else (group,)
        for method in methods:
            expected.add((method, seed))
    return expected


def read_verified_blocks(inputs: list[Path]) -> list[dict]:
    if not inputs:
        raise ValueError("No new experimental files; old results must not be used")
    rows = []
    identities = set()
    for path in inputs:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("protocol", {}).get("qos_mode") != "task_level_soft_deadline":
            raise ValueError(f"{path}: not a v26 task-level experiment")
        if not data.get("complete"):
            raise ValueError(f"{path}: interrupted block is not a publishable complete run")
        expected = _expected_schedule_rows(data)
        seen = set()
        for row in data.get("rows", []):
            key = (row["method"], row["algorithm_seed"])
            if key in seen:
                raise ValueError(f"{path}: duplicate algorithm+seed {key}")
            seen.add(key)
            identity = (data["protocol_sha256"], data["tasks"], data["scenario_seed"], *key)
            if identity in identities:
                raise ValueError(f"{path}: duplicate planned run {identity}")
            identities.add(identity)
            metrics = row.get("metrics", {})
            if not set(REQUIRED_TASK_QOS_FIELDS) <= set(metrics):
                raise ValueError(f"{path}: missing mandatory task-QoS field {key}")
            if metrics["physical_feasible"] is not True:
                raise ValueError(f"{path}: no independently certified physical run {key}")
            if not (0 <= metrics["success_rate"] <= 1):
                raise ValueError(f"{path}: success rate outside [0,1] {key}")
            count = metrics["planned_tasks"]
            if metrics["served_tasks"] + metrics["unserved_tasks"] != count:
                raise ValueError(f"{path}: served/unserved accounting mismatch {key}")
            if (metrics["on_time_tasks"] + metrics["late_tasks"] +
                    metrics["unserved_tasks"] != count):
                raise ValueError(f"{path}: outcome accounting mismatch {key}")
            if (len(metrics["task_outcomes"]) != count or
                    any(x["status"] not in {"unserved","on_time","late"}
                        for x in metrics["task_outcomes"].values())):
                raise ValueError(f"{path}: missing task outcomes {key}")
            for name in ("success_rate", "mean_delay_all", "p95_delay_all", "total_energy",
                         "mec_cpu_utilization", "runtime", "stage1_energy", "route_distance"):
                v = metrics[name]
                if v is None or not math.isfinite(float(v)):
                    raise ValueError(f"{path}: invalid measured metric {name} in {key}")
            rows.append({
                "tasks": data["tasks"], "scenario_seed": data["scenario_seed"],
                "algorithm_seed": row["algorithm_seed"], "method": row["method"],
                "protocol_id": data["protocol"]["id"],
                "study": data["protocol"].get("study","main"),
                "level": data["protocol"].get("level","baseline"),
                "metrics": metrics,
            })
        if seen != expected:
            raise ValueError(f"{path}: planned rows missing/extra: {sorted(expected-seen)}, {sorted(seen-expected)}")
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["study"], str(row["level"]), row["tasks"], row["method"])].append(row)
    summaries = []
    for (study, level, tasks, method), unit in sorted(grouped.items()):
        scenarios = sorted({r["scenario_seed"] for r in unit})
        for metric in SUMMARY_METRICS:
            observations = []
            for scenario in scenarios:
                samples = [r["metrics"][metric] for r in unit
                           if r["scenario_seed"] == scenario and r["metrics"][metric] is not None]
                if samples:
                    observations.append(mean(float(v) for v in samples))
            summaries.append({
                "study": study, "level": level, "tasks": tasks, "method": method,
                "metric": metric,
                "planned_runs": len(unit),
                "physical_feasible_runs": sum(r["metrics"]["physical_feasible"] for r in unit),
                "observed_runs": sum(r["metrics"][metric] is not None for r in unit),
                "independent_scenarios": len(observations),
                "value": mean(observations) if observations else None,
                "missing_reason": None if observations else "not_defined_in_sample",
                "aggregation": "equal_weight_by_scenario_after_seed_average",
            })
    return summaries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-root", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    files = sorted(args.input_root.rglob("*.json"))
    rows = read_verified_blocks(files)
    summaries = summarize(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "task_qos_summary.json").write_text(
        json.dumps({"source_files": [str(p) for p in files],
                    "planned_runs": len(rows), "summary": summaries},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "task_qos_summary.csv").open(
            "w", encoding="utf-8", newline="") as stream:
        columns = list(summaries[0])
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summaries)
    print(f"Verified {len(files)} blocks, {len(rows)} planned runs; "
          f"saved {len(summaries)} scenario-weighted statistics")


if __name__ == "__main__":
    main()
