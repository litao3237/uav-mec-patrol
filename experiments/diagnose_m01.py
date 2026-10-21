"""M0.1 frozen-input numerical audit and common-resource cross replay.

Never runs search, never reuses recorded metrics as if they were recomputed,
never edits results/. Both v26 and M0 discrete solutions are replayed by the
*same* checked-out M0 resource solver. Source and solution SHA identities
are checked before each replay.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_seven_methods import finalize_task_qos
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.evaluation.task_objective import (
    ON_TIME_TOL_S, LATENESS_TOL, measured_task_key,
)

OLD_RUN = "39429879939"
M0_RUN = "39456198442"
OLD_SHA = "0335b1251ee2ca85399c5b685814ad5b9f284267"
M0_SHA = "540e7b3193d28feb9bca57eb9998a8098c91c2a3"
METHODS = ("B-ALNS", "ESI-ALNS")


def read_block(path: Path, *, tasks: int, git_sha: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("complete") or data["tasks"] != tasks or data["scenario_seed"] != 45:
        raise ValueError(f"Wrong or incomplete snapshot: {path}")
    if data.get("provenance", {}).get("git_commit") != git_sha:
        raise ValueError(f"Frozen source version mismatch: {path}")
    if data["instance_sha256"] != content_hash(restore_instance(data["instance"])):
        raise ValueError(f"Instance SHA-256 mismatch: {path}")
    return data


def find_row(block: dict, method: str) -> dict:
    matches = [
        r for r in block["rows"]
        if r["method"] == method and r["algorithm_seed"] == 100
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one {method} seed=100, got {len(matches)}")
    row = matches[0]
    if content_hash(restore_solution(row["solution"])) != row["solution_sha256"]:
        raise ValueError(f"{method}: candidate solution fingerprint mismatch")
    return row


def numeric_stage2(block: dict) -> list[dict]:
    instance = restore_instance(block["instance"])
    outcome = []
    for row in block["rows"]:
        s2 = row["stage2"]
        record = {
            "tasks": block["tasks"], "method": row["method"],
            "seed": row["algorithm_seed"],
            "stage2_status": s2["status"],
            "stage2_accepted": bool(s2.get("qualified", False)),
            "source_solution_sha256": row["solution_sha256"],
        }
        if s2.get("status") != "rejected_task_qos_regression" or not s2.get("values"):
            outcome.append(record)
            continue
        solution = restore_solution(row["solution"])
        old_report = row["stage1"]["audit"]["reconstructed"]
        old_delays = old_report["timeline"]["task_delay_s"]
        old_energy = old_report["metrics"]["energy_j"]
        tol_j = max(1e-5, 1e-6 * max(1., abs(old_energy)))
        audit = audit_both_timelines(
            instance, solution, s2["values"],
            energy_limit_j=old_energy + tol_j,
        )
        if not all(a["complete"] and a["passed"] for a in audit.values()):
            record["physical_stage2_candidate_pass"] = False
            record["physical_rejection"] = {
                k: {
                    "complete": v.get("complete"), "passed": v.get("passed"),
                    "reason": v.get("reason"), "worst": v.get("worst_constraint"),
                }
                for k, v in audit.items()
            }
            outcome.append(record)
            continue
        new_report = audit["reconstructed"]
        new_delays = new_report["timeline"]["task_delay_s"]
        new_energy = new_report["metrics"]["energy_j"]
        old_key = measured_task_key(
            instance, old_delays, energy_j=old_energy,
            distance_m=old_report["metrics"]["total_distance_m"],
        )
        new_key = measured_task_key(
            instance, new_delays, energy_j=new_energy,
            distance_m=new_report["metrics"]["total_distance_m"],
        )
        task_flips = [
            {
                "task": t,
                "deadline_s": instance.tasks[t].deadline_s,
                "old_margin_s": instance.tasks[t].deadline_s - old_delays[t],
                "new_margin_s": instance.tasks[t].deadline_s - new_delays[t],
                "completion_shift_s": new_delays[t] - old_delays[t],
            }
            for t in instance.tasks
            if (old_delays[t] <= instance.tasks[t].deadline_s + ON_TIME_TOL_S)
            != (new_delays[t] <= instance.tasks[t].deadline_s + ON_TIME_TOL_S)
        ]
        score_reasons = []
        if new_key[1] > old_key[1]:
            score_reasons.append("success_count_decrease")
        if new_key[2] > old_key[2] + LATENESS_TOL:
            score_reasons.append("normalized_lateness_guard")
        if new_key[3] > old_key[3] + tol_j:
            score_reasons.append("energy_guard")
        record.update(
            physical_stage2_candidate_pass=True,
            stage1_quality=list(old_key), stage2_candidate_quality=list(new_key),
            success_delta=int(-new_key[1] + old_key[1]),
            lateness_delta=new_key[2] - old_key[2],
            lateness_excess_over_guard=new_key[2] - old_key[2] - LATENESS_TOL,
            energy_delta_j=new_key[3] - old_key[3],
            energy_tolerance_j=tol_j,
            energy_excess_over_guard_j=new_key[3] - old_key[3] - tol_j,
            crossed_on_time_tasks=task_flips,
            exact_rejection_reasons=score_reasons,
            note="Rejected Stage-2 candidates must NOT replace the accepted Stage-1 allocation",
        )
        if not score_reasons:
            raise AssertionError(
                f"Previously rejected Stage-2 has no reproducible reason: {block['tasks']} {row['method']}"
            )
        outcome.append(record)
    return outcome


def replay_block(old_path: Path, m0_path: Path, output: Path, tasks: int) -> None:
    old = read_block(old_path, tasks=tasks, git_sha=OLD_SHA)
    m0 = read_block(m0_path, tasks=tasks, git_sha=M0_SHA)
    if old["instance_sha256"] != m0["instance_sha256"]:
        raise ValueError("Old and M0 task scenario fingerprints differ")
    if old["config_file_sha256"] != m0["config_file_sha256"]:
        raise ValueError("Old and M0 configuration files are not identical")
    instance = restore_instance(m0["instance"])
    numeric = numeric_stage2(m0)
    rows = []
    for method in METHODS:
        for version, block in (("v26", old), ("m0", m0)):
            original = find_row(block, method)
            solution = restore_solution(original["solution"])
            started = perf_counter()
            entry = {
                "tasks": tasks, "scenario_seed": 45, "algorithm_seed": 100,
                "search_version": version, "method": method,
                "original_instance_sha256": block["instance_sha256"],
                "original_solution_sha256": original["solution_sha256"],
                "source_git_commit": block["provenance"]["git_commit"],
                "original_successes": original["metrics"]["on_time_tasks"],
                "original_energy_j": original["metrics"]["total_energy"],
                "original_distance_m": original["metrics"]["route_distance"],
                "original_resource_source": original["metrics"]["energy_source"],
                "original_stage2_status": original["stage2"]["status"],
            }
            try:
                # EXACT same M0 evaluator, admission, Stage-1A/Stage-1B,
                # Stage-2 and independent audit for all four structures.
                result = finalize_task_qos(
                    instance, solution, method=method, seed=100,
                    initialization_s=0., search_s=0.,
                    diagnostics={"m01_origin": version},
                )
                metrics = result["metrics"]
                late = sum(
                    x["tardiness_s"] / max(1.0, x["deadline_s"])
                    for x in metrics["task_outcomes"].values()
                    if x["tardiness_s"] is not None
                )
                # The common score subtracts the numeric classification
                # tolerance. This separate late metric is intentionally
                # reported only as raw lateness diagnostic.
                measured = result["stage2"]["audit"] if result["stage2"].get("qualified") else result["stage1"]["audit"]
                audited_quality = None
                if measured is not None:
                    reconstructed = measured["reconstructed"]
                    audited_quality = list(measured_task_key(
                        result["instance"] if "instance" in result else
                        __import__("dataclasses").replace(
                            instance, tasks={
                                t: instance.tasks[t] for t in metrics["task_outcomes"]
                                if metrics["task_outcomes"][t]["status"] != "unserved"
                            }),
                        reconstructed["timeline"]["task_delay_s"],
                        energy_j=reconstructed["metrics"]["energy_j"],
                        distance_m=reconstructed["metrics"]["total_distance_m"],
                    ))
                entry.update(
                    physical_feasible=metrics["physical_feasible"],
                    recalc_source=result["admission"]["source"],
                    recalc_energy_source=metrics["energy_source"],
                    recalc_solution_sha256=result["solution_sha256"],
                    removed_by_common_admission=metrics["unserved_tasks"],
                    recalc_successes=metrics["on_time_tasks"],
                    recalc_late_tasks=metrics["late_tasks"],
                    recalc_normalized_lateness_raw=late,
                    recalc_energy_j=metrics["total_energy"],
                    recalc_stage1_energy_j=metrics["stage1_energy"],
                    recalc_stage2_energy_j=metrics["stage2_energy"],
                    recalc_distance_m=metrics["route_distance"],
                    recalc_stage2_status=result["stage2"]["status"],
                    recalc_stage1_status=result["stage1"]["status"],
                    recalc_quality_tuple=audited_quality,
                    same_solution_after_common_admission=(
                        result["solution_sha256"] == original["solution_sha256"]
                    ),
                    recalc_compute_s=perf_counter() - started,
                )
            except Exception as exc:
                entry["recalc_error"] = {
                    "type": type(exc).__name__, "message": str(exc)
                }
                entry["recalc_compute_s"] = perf_counter() - started
            rows.append(entry)
            print(json.dumps({
                k: v for k, v in entry.items()
                if k in ("tasks", "method", "search_version", "recalc_successes",
                         "recalc_energy_j", "recalc_compute_s", "recalc_error")
            }), flush=True)
    write_json(output, {
        "schema": "M0.1-common-resource-cross-replay-v1",
        "origin_runs": {"v26": OLD_RUN, "m0": M0_RUN},
        "reference_solver_commit": M0_SHA,
        "current_branch_is_diagnostic": True,
        "tasks": tasks, "scenario": 45,
        "instance_sha256": m0["instance_sha256"],
        "config_file_sha256": m0["config_file_sha256"],
        "cross_replay": rows,
        "recorded_m0_stage2_numerical_audit": numeric,
    })
    # An error does not silently get treated as zero quality or a fake
    # physical solution. The checkpoint is saved before failing the job.
    failures = [x for x in rows if "recalc_error" in x]
    if failures:
        raise RuntimeError(f"{len(failures)} M0.1 cross-replays failed; see artifact")


def aggregate(input_dir: Path, output_dir: Path) -> None:
    all_rows, numeric = [], []
    for k in (30, 50, 80):
        p = input_dir / f"K{k}_cross.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["tasks"] != k or d["reference_solver_commit"] != M0_SHA:
            raise ValueError(f"Cross-run identity error: {p}")
        if len(d["cross_replay"]) != 4 or len(d["recorded_m0_stage2_numerical_audit"]) != 7:
            raise ValueError(f"Wrong per-scale row count: {p}")
        all_rows.extend(d["cross_replay"])
        numeric.extend(d["recorded_m0_stage2_numerical_audit"])
    if len(all_rows) != 12 or len(numeric) != 21:
        raise AssertionError("Require exactly 12 resource replays and 21 recorded numerical checks")
    if any("recalc_error" in r or not r.get("physical_feasible") for r in all_rows):
        raise AssertionError("Incomplete/failed common-resource recourse")
    comparisons = []
    for k in (30, 50, 80):
        for m in METHODS:
            q = {(r["tasks"], r["method"], r["search_version"]): r for r in all_rows}
            old, new = q[(k,m,"v26")], q[(k,m,"m0")]
            comparisons.append({
                "tasks":k, "method":m,
                "common_recourse_success_diff_m0_minus_v26":new["recalc_successes"]-old["recalc_successes"],
                "common_recourse_energy_diff_j_m0_minus_v26":new["recalc_energy_j"]-old["recalc_energy_j"],
                "route_distance_diff_m":new["recalc_distance_m"]-old["recalc_distance_m"],
                "m0_energy_better":new["recalc_energy_j"] < old["recalc_energy_j"],
                "both_served_every_task": old["removed_by_common_admission"] == new["removed_by_common_admission"] == 0,
            })
    output_dir.mkdir(parents=True,exist_ok=True)
    write_json(output_dir/"cross_summary.json",{
        "schema":"m01_verified_comparison_v1", "reference_solver_commit":M0_SHA,
        "origin_runs":{"v26":OLD_RUN,"m0":M0_RUN},
        "cross_rows":all_rows, "stage2_numerical_diagnostics":numeric,
        "paired_comparisons":comparisons,
    })
    for name, data in (("cross_rows.csv",all_rows),
                       ("paired_comparisons.csv",comparisons),
                       ("stage2_numerical.csv",numeric)):
        keys=sorted({k for x in data for k in x})
        with (output_dir/name).open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=keys)
            w.writeheader()
            w.writerows({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v)
                          for k,v in row.items()} for row in data)
    print("M0.1 verified:",len(all_rows),"common resource replays; ",
          len(numeric),"numerical diagnostics; 6 paired comparisons.",flush=True)
    print(json.dumps(comparisons,indent=2,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--v26",type=Path)
    parser.add_argument("--m0",type=Path)
    parser.add_argument("--tasks",type=int,choices=(30,50,80))
    parser.add_argument("--output",type=Path)
    parser.add_argument("--aggregate-input",type=Path)
    parser.add_argument("--aggregate-output",type=Path)
    args=parser.parse_args()
    if args.aggregate_input is not None:
        if args.aggregate_output is None:
            parser.error("--aggregate-output is required")
        aggregate(args.aggregate_input,args.aggregate_output)
    else:
        if any(x is None for x in (args.v26,args.m0,args.tasks,args.output)):
            parser.error("--v26, --m0, --tasks, and --output are required")
        replay_block(args.v26,args.m0,args.output,args.tasks)

if __name__=="__main__":
    main()
