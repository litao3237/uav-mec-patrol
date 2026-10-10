"""Replay *frozen, unmodified* UAV-MEC discrete structures across physical parameters.

Input: raw archive from the already completed coupling-sensitivity GitHub
workflow (run 38043248604), NOT regenerated optimizer trajectories.
For each original BASELINE B-ALNS/ESI route+contacts+offload decision, solve
all seven parameter profiles with exactly the same D. Only continuous
bandwidth/CPU/time may change.

This distinguishes solver/physics response at fixed D from the earlier
nonmonotone heuristic response caused by reoptimizing D. It does NOT show
that a different D could not be feasible for a stressed instance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
from statistics import mean
from time import perf_counter

from experiment_common import current_source_hashes, provenance
from run_model_sensitivity import METHODS, PROFILES, physical_metrics
from run_seven_methods import finalize
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource import fast_feasibility_precheck


def classify_precheck(instance, solution):
    pre = fast_feasibility_precheck(instance, solution, build_event_info(instance, solution))
    types = Counter()
    offenders = []
    for reason in pre.reasons:
        if reason.startswith("task "):
            task_id = reason.split(":", 1)[0].split()[1]
            mode = solution.task_decisions[task_id].mode.value
            types[f"task_{mode}"] += 1
            lb = pre.task_completion_lb_s.get(task_id)
            deadline = instance.tasks[task_id].release_s + instance.tasks[task_id].deadline_s
            offenders.append({
                "task_id": task_id,
                "mode": mode,
                "optimistic_completion_lb_s": lb,
                "absolute_deadline_s": deadline,
                "optimistic_deadline_gap_s": lb - deadline,
                "assigned_contact": solution.task_decisions[task_id].contact_visit_id,
            })
        elif reason.startswith("average delay:"):
            types["average_delay"] += 1
        elif reason.startswith("UAV "):
            types["patrol_cycle"] += 1
        else:
            types["other"] += 1
    return {
        "passed_necessary_precheck": pre.feasible,
        "reasons": list(pre.reasons),
        "reason_families": dict(types),
        "offending_tasks": offenders,
        "max_task_deadline_LB_excess_s": max(
            (item["optimistic_deadline_gap_s"] for item in offenders),
            default=0.0,
        ),
    }


def summarize(rows):
    result = []
    for method in METHODS:
        for profile in PROFILES:
            own = [
                r for r in rows if r["method"] == method and r["profile"] == profile
            ]
            qualifying = [r for r in own if r["both_qualified"]]
            no_precheck = sum(not r["precheck"]["passed_necessary_precheck"] for r in own)
            reason_counts = Counter()
            for r in own:
                reason_counts.update(r["precheck"]["reason_families"])
            paired = []
            base_energy_by_seed = {
                r["seed"]: r["energy_stage1_j"]
                for r in rows
                if r["method"] == method and r["profile"] == "baseline"
                and r["both_qualified"]
            }
            for r in qualifying:
                if r["seed"] in base_energy_by_seed:
                    paired.append(r["energy_stage1_j"] - base_energy_by_seed[r["seed"]])
            result.append({
                "method": method, "profile": profile,
                "attempted": len(own),
                "precheck_rejected": no_precheck,
                "precheck_reason_counts": dict(reason_counts),
                "stage1_strict_qualified": sum(r["stage1_qualified"] for r in own),
                "both_strict_qualified": len(qualifying),
                "stage1_status_counts": dict(Counter(r["stage1_status"] for r in own)),
                "mean_fixed_stage1_energy_j_qualified": (
                    mean(r["energy_stage1_j"] for r in qualifying)
                    if qualifying else None
                ),
                "mean_delta_fixed_energy_vs_baseline_j_paired": (
                    mean(paired) if paired else None
                ),
                "paired_qualified": len(paired),
                "mean_original_dynamic_energy_j_qualified": (
                    mean(
                        r["earlier_dynamic"]["energy_stage1_j"]
                        for r in own
                        if r["earlier_dynamic"]["both_qualified"]
                        and r["earlier_dynamic"]["energy_stage1_j"] is not None
                    )
                    if any(r["earlier_dynamic"]["both_qualified"] and
                           r["earlier_dynamic"]["energy_stage1_j"] is not None
                           for r in own) else None
                ),
                "mean_total_s": mean(r["total_s"] for r in own) if own else None,
            })
    return result


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    archive = json.loads(args.input.read_text(encoding="utf-8"))
    if not archive.get("complete"):
        raise RuntimeError("Source sensitivity run is incomplete")
    p = archive["protocol"]
    K, S = int(p["task_scale"]), int(p["independent_scenario_seed"])
    if p["id"] != "uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Expected frozen original sensitivity archive")
    instance_by_profile = {}
    for profile in PROFILES:
        entry = archive["profiles"][profile]
        instance = restore_instance(entry["instance"])
        if content_hash(instance) != entry["instance_sha256"]:
            raise RuntimeError(f"Source instance checksum mismatch: {profile}")
        instance_by_profile[profile] = instance

    source = {
        (row["profile"], row["seed"], row["method"]): row
        for row in archive["rows"]
    }
    payload = {
        "complete": False,
        "protocol": {
            "id": "fixed_D_coupling_replay_v1",
            "source_study_run_id": 38043248604,
            "source_study_branch": "experiment/model-coupling-sensitivity",
            "source_frozen_algorithm_commit": "0bdf3a26d4c042e13f96f84977261ffdd33cfc89",
            "source_input_sha256": content_hash(archive),
            "source_block": {"tasks": K, "scenario_seed": S},
            "fixed_structure": "BASELINE task owner / order / contact point / offload mode remain IDENTICAL",
            "profiles": list(PROFILES),
            "methods": list(METHODS),
            "independent_unit": "scenario; original algorithm seed nested",
            "stage1_stage2": "same exact strict resources and independent physical audit as original study",
            "failure_policy": "no infeasible result interpolated; every replay attempt retained",
            "source_hashes": current_source_hashes(Path(__file__)),
            "provenance": provenance(),
        },
        "rows": [],
    }
    write_json(args.output, payload)
    try:
        for seed in p["algorithm_seeds"]:
            for method in METHODS:
                anchor = source[("baseline", seed, method)]
                if not anchor.get("both_qualified"):
                    raise RuntimeError(
                        f"No strictly feasible baseline D to hold fixed: K{K} S{S} {seed} {method}"
                    )
                frozen = restore_solution(anchor["solution"])
                frozen_hash = content_hash(frozen)
                if frozen_hash != anchor["solution_sha256"]:
                    raise RuntimeError("Frozen baseline solution hash mismatch")
                for profile in PROFILES:
                    instance = instance_by_profile[profile]
                    earlier = source[(profile, seed, method)]
                    diagnostic = classify_precheck(instance, frozen)
                    start = perf_counter()
                    error = None
                    stage1 = None
                    stage2 = None
                    full = None
                    try:
                        full = finalize(
                            instance, deepcopy(frozen),
                            method=f"fixedD_{method}", seed=seed,
                            initialization_s=0.0, search_s=0.0,
                            diagnostics={
                                "source_solution_sha256": frozen_hash,
                                "no_discrete_changes": True,
                            },
                        )
                        stage1 = bool(full["stage1"]["qualified"])
                        stage2 = bool(full["stage2"]["qualified"])
                    except Exception as exc:
                        error = {"type": type(exc).__name__, "message": str(exc)}
                    elapsed = perf_counter() - start
                    both = bool(stage1 and stage2)
                    metrics = physical_metrics(instance, frozen, full) if both else None
                    diag = full["resources"].diagnostics if full else {}
                    result = {
                        "tasks": K, "scenario_seed": S, "seed": seed,
                        "method": method, "profile": profile,
                        "source_baseline_sha256": frozen_hash,
                        "replay_solution_sha256": content_hash(frozen),
                        "instance_sha256": content_hash(instance),
                        "precheck": diagnostic,
                        "stage1_status": diag.get("stage1_status", "error"),
                        "stage1_rejection_reason": diag.get("stage1_acceptance_reason"),
                        "stage2_status": diag.get("stage2_status", "not_run"),
                        "stage1_qualified": bool(stage1),
                        "stage2_qualified": bool(stage2),
                        "both_qualified": both,
                        "energy_stage1_j": (
                            float(full["resources"].energy_stage1_j)
                            if stage1 else None
                        ),
                        "physical": metrics,
                        "total_s": elapsed,
                        "earlier_dynamic": {
                            "solution_sha256": earlier.get("solution_sha256"),
                            "both_qualified": earlier.get("both_qualified", False),
                            "energy_stage1_j": earlier.get("energy_stage1_j")
                            if earlier.get("both_qualified") else None,
                            "stage1_status": (
                                earlier.get("resources", {})
                                .get("diagnostics", {})
                                .get("stage1_status", "exception")
                            ),
                            "stage1_precheck_reasons": (
                                earlier.get("resources", {})
                                .get("diagnostics", {})
                                .get("precheck_reasons", [])
                            ),
                        },
                        "error": error,
                    }
                    if args.keep_full_snapshots:
                        result["exact_solver_data"] = full
                    payload["rows"].append(result)
                    write_json(args.output, payload)
                    print(
                        f"FIXED_REPLAY K{K} S{S} A{seed} {method} {profile}: "
                        f"precheck={diagnostic['passed_necessary_precheck']} "
                        f"Stage1={stage1} Stage2={stage2} "
                        f"E={result['energy_stage1_j']} "
                        f"earlier_reoptimized={earlier.get('both_qualified')} "
                        f"t={elapsed:.2f}s",
                        flush=True,
                    )
        payload["summary"] = summarize(payload["rows"])
        payload["complete"] = True
        write_json(args.output, payload)
        print("FIXED_REPLAY_SUMMARY=" + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    except Exception as exc:
        payload["execution_error"] = {"type":type(exc).__name__, "message":str(exc)}
        write_json(args.output, payload)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--keep-full-snapshots", action="store_true")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
