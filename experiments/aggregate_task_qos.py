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
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash, restore_instance, restore_solution
from uav_mec.evaluation import build_event_info
from dataclasses import replace

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


def verify_physical_record(data: dict, row: dict, path: Path) -> None:
    """Reconstruct hard-constraint residuals independently from stored raw values."""
    original = restore_instance(data["instance"])
    if original.qos_hard:
        raise ValueError(f"{path}: expected explicitly soft v26 instance snapshot")
    if content_hash(original) != data["instance_sha256"]:
        raise ValueError(f"{path}: source instance hash mismatch")
    metrics = row["metrics"]
    served = {t for t, outcome in metrics["task_outcomes"].items()
              if outcome["status"] != "unserved"}
    partial = replace(original, tasks={t: original.tasks[t] for t in served})
    solution = restore_solution(row["solution"])
    if content_hash(solution) != row["solution_sha256"]:
        raise ValueError(f"{path}: accepted solution hash mismatch")
    event = build_event_info(partial, solution)  # validates route, contacts, visit order
    if metrics["served_tasks"] != len(served):
        raise ValueError(f"{path}: inconsistent admitted task population")
    if not served:
        if (any(event.base_return_s.values()) or metrics["total_energy"] != 0 or
                row["admission"]["source"] != "verified_idle"):
            raise ValueError(f"{path}: invalid idle physical certificate")
        return
    stage1 = row["stage1"]
    if stage1.get("values") is None:
        raise ValueError(f"{path}: no Stage-1 physical variables")
    first = audit_both_timelines(partial, solution, stage1["values"])
    if not all(x["complete"] and x["passed"] for x in first.values()):
        raise ValueError(f"{path}: independent Stage-1 physical failure")
    if abs(metrics["stage1_energy"] - first["reconstructed"]["metrics"]["energy_j"]) > 1e-5 * max(1., metrics["stage1_energy"]):
        raise ValueError(f"{path}: Stage-1 reported energy differs from audited Joules")
    if row["stage2"].get("qualified"):
        second = audit_both_timelines(
            partial, solution, row["stage2"]["values"],
            energy_limit_j=metrics["stage1_energy"] + max(1e-5, 1e-6 * max(1., metrics["stage1_energy"])))
        if not all(x["complete"] and x["passed"] for x in second.values()):
            raise ValueError(f"{path}: independent Stage-2 physical failure")
        if metrics["stage2_energy"] is None:
            raise ValueError(f"{path}: qualified Stage-2 energy must exist")
        if abs(metrics["stage2_energy"] - second["reconstructed"]["metrics"]["energy_j"]) > 1e-5 * max(1., metrics["stage2_energy"]):
            raise ValueError(f"{path}: Stage-2 reported energy differs from audited Joules")
        final_audit = second
    else:
        if metrics["stage2_energy"] is not None:
            raise ValueError(f"{path}: disqualified Stage-2 energy must remain null")
        final_audit = first
    physical_energy = final_audit["reconstructed"]["metrics"]["energy_j"]
    if abs(metrics["total_energy"] - physical_energy) > 1e-5 * max(1., physical_energy):
        raise ValueError(f"{path}: final energy is not independently audited")
    delays = final_audit["reconstructed"]["timeline"]["task_delay_s"]
    for t, delta in delays.items():
        expected = metrics["task_outcomes"][t]["delay_s"]
        if expected is None or abs(delta - expected) > 1e-4:
            raise ValueError(f"{path}: task delay does not match physical timeline: {t}")


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
            verify_physical_record(data, row, path)
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
    ap.add_argument("--phase", choices=["pilot", "formal"], default=None,
                    help="When set, require every planned main-matrix method/seed/scenario")
    args = ap.parse_args()
    files = sorted(args.input_root.rglob("*.json"))
    rows = read_verified_blocks(files)
    if args.phase:
        from run_seven_methods import expected_keys
        expected = expected_keys(args.phase)
        actual = {(r["tasks"], r["scenario_seed"], r["algorithm_seed"], r["method"])
                  for r in rows}
        if actual != expected or len(rows) != len(expected):
            raise ValueError(
                f"Incomplete {args.phase} matrix: found {len(rows)} runs, "
                f"expected {len(expected)}; missing={len(expected-actual)}, "
                f"extra={len(actual-expected)}"
            )
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
