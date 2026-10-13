"""P22 frozen K80 two-task cross-UAV exchange diagnostic.

Question: can a complete two-UAV task reassignment repair the task-level
FIFO/EDF deadline necessary violations identified by P20/P21?

Each arm performs the same <=12 ORIGINAL MEC-rebuilder calls for two-task
cross-UAV exchanges. Arm A pairs the 3 worst normalized overdue tasks with
a low-overdue counterpart on each other UAV. Arm B chooses 12 seeded
random valid cross-UAV pairs. Both apply the EXACT same cheapest insertion
rule restricted to the two opposite UAVs and one unchanged original MEC
builder. The original queue necessary check is used to CHOOSE just ONE
posthoc candidate for original Stage1/Stage2 strict CVX verification.

This is a development diagnostic on previously inspected P19 frozen D,
NOT a six-second matched-runtime full ALNS improvement, not a new holdout
and not a proof of global feasibility. No original model/ALNS code changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from run_p12_insertion_finish_audit import (
    CASES, _strict_numerical_check, queue_metrics, queue_rank,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState, operators as ops
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)

MAX_PAIRS = 12
ARMS = ("deadline_critical_pairs", "random_cross_uav_pairs")


def owner_map(solution):
    mapping = {}
    for uid, route in sorted(solution.routes.items()):
        for tid in route.task_ids():
            if tid in mapping:
                raise RuntimeError("One task appears in two UAV routes")
            mapping[tid] = uid
    return mapping


def _pressure(instance, original):
    result = queue_aware_feasibility_precheck(
        instance, original, build_event_info(instance, original)
    )
    return {
        tid: max(
            0., float(result.task_completion_lb_s[tid]) -
            (task.release_s + task.deadline_s)
        ) / max(1., task.deadline_s)
        for tid, task in instance.tasks.items()
    }


def choose_pair_arms(instance, original, seed, max_pairs=MAX_PAIRS):
    owners = owner_map(original)
    stress = _pressure(instance, original)
    by_uav = {
        uid: list(route.task_ids())
        for uid, route in sorted(original.routes.items())
    }
    critical = sorted(
        owners, key=lambda tid: (
            -stress[tid], -instance.tasks[tid].workload_gcycles, tid
        )
    )[:3]
    targeted = []
    for a in critical:
        other_uavs = sorted(uid for uid in by_uav if uid != owners[a]
                            and by_uav[uid])
        for uid in other_uavs:
            b = min(by_uav[uid], key=lambda tid: (
                stress[tid], instance.tasks[tid].workload_gcycles, tid
            ))
            pair = (a, b)
            if pair not in targeted:
                targeted.append(pair)
    targeted = targeted[:max_pairs]

    # Random matched-count control, from the same admissible cross-UAV space.
    all_pairs = [
        (a, b) for i, a in enumerate(sorted(owners))
        for b in sorted(owners)[i+1:]
        if owners[a] != owners[b]
    ]
    if not all_pairs or not targeted:
        raise RuntimeError("No legal cross-UAV task pairs in original physical D")
    rng = np.random.default_rng(seed + 221100)
    indices = rng.choice(
        len(all_pairs), size=min(len(targeted), len(all_pairs)),
        replace=False,
    )
    random_pairs = [all_pairs[int(i)] for i in indices]
    if len(random_pairs) != len(targeted):
        raise RuntimeError("Not exactly matched real MEC builder quotas")
    return {ARMS[0]: targeted, ARMS[1]: random_pairs}, stress, critical


def one_cross_uav_exchange(instance, original, owners, pair):
    a, b = pair
    if a == b or owners[a] == owners[b]:
        raise ValueError("A P22 exchange requires two distinct UAVs")
    t = perf_counter()
    frozen_sha = content_hash(original)
    state = UavMecState(
        instance, deepcopy(original), ScreenedProxyObjectiveEvaluator()
    )
    state = ops._destroy_tasks(state, (a, b))
    if set(state.removed_tasks) != {a, b}:
        raise RuntimeError("Cross-UAV destroy removed the wrong tasks")
    choices_a = [
        opt for opt in ops._options_for_task(state, a)
        if opt.uav_id == owners[b]
    ]
    if not choices_a:
        raise RuntimeError("Cannot insert A into original B UAV")
    chosen_a = choices_a[0]  # unchanged original insertion key, target UAV restricted
    ops._apply_local_insertion(state, a, chosen_a)
    choices_b = [
        opt for opt in ops._options_for_task(state, b)
        if opt.uav_id == owners[a]
    ]
    if not choices_b:
        raise RuntimeError("Cannot insert B into original A UAV")
    chosen_b = choices_b[0]
    ops._apply_local_insertion(state, b, chosen_b)
    complete = ops._finish_repair(state)
    validate_solution(instance, complete.solution)
    new_owners = owner_map(complete.solution)
    if new_owners[a] != owners[b] or new_owners[b] != owners[a]:
        raise RuntimeError("Cross-UAV paired exchange did not change ownership")
    if content_hash(original) != frozen_sha:
        raise RuntimeError("Source D was mutated by trial")
    q = queue_metrics(instance, complete.solution)
    return {
        "task_pair": [a, b],
        "new_UAV_for_a": new_owners[a],
        "new_UAV_for_b": new_owners[b],
        "after": q,
        "finished_D_sha": content_hash(complete.solution),
        "original_key_a": list(chosen_a.key),
        "original_key_b": list(chosen_b.key),
        "complete_rebuild_wall_s": perf_counter() - t,
    }, complete.solution


def run(source: Path, output: Path, cases):
    if output.exists():
        raise FileExistsError(output)
    frozen = json.loads(source.read_text(encoding="utf-8"))
    scene = int(frozen["protocol"]["independent_scenario_seed"])
    selected = [(p, int(s)) for p, s in cases]
    if (
        not frozen.get("complete") or scene not in CASES
        or any(x not in CASES[scene] for x in selected)
    ):
        raise ValueError("Only previously inspected frozen original K80 B endpoints")
    index = {
        (r["profile"], int(r["seed"]), r["method"]): r
        for r in frozen["rows"]
    }
    result = {
        "complete": False,
        "protocol": {
            "id": "P22_critical_deadline_two_UAV_task_swap_v1",
            "scene": scene,
            "original_frozen_source_SHA": content_hash(frozen),
            "max_pair_trials_per_policy": MAX_PAIRS,
            "policies": list(ARMS),
            "same_original_MEC_builder_and_legal_insertion_key": True,
            "same_Stage1_Stage2_and_physical_model": True,
            "strict_CVX_only_after_queue_ranked_selected_candidates": True,
            "not_equal_wall_clock_ALNS_claim": True,
            "not_unseen_holdout": True,
        },
        "rows": [], "errors": [],
    }
    write_json(output, result)
    for profile, seed in selected:
        instance = restore_instance(frozen["profiles"][profile]["instance"])
        if content_hash(instance) != frozen["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Physical frozen source changed")
        src = index[profile, seed, "B-ALNS"]
        old_D = restore_solution(src["solution"])
        frozen_sha = src["solution_sha256"]
        if content_hash(old_D) != frozen_sha:
            raise RuntimeError("Original B-ALNS frozen solution SHA mismatch")
        before = queue_metrics(instance, old_D)
        pair_arms, pressure, critical = choose_pair_arms(instance, old_D, seed)
        n = len(pair_arms[ARMS[0]])
        row = {
            "scene": scene, "profile": profile, "seed": seed,
            "frozen_B_SHA": frozen_sha,
            "original_queue": before,
            "critical_tasks": [
                {"task": t, "normalized_excess": pressure[t]}
                for t in critical
            ],
            "equal_builder_trials_per_policy": n,
            "policies": {},
        }
        result["rows"].append(row)
        write_json(output, result)
        original_strict = _strict_numerical_check(instance, old_D)
        row["original_strict"] = original_strict
        for arm in ARMS:
            owners = owner_map(old_D)
            trials = []
            alive = []
            for pair in pair_arms[arm]:
                try:
                    record, candidate = one_cross_uav_exchange(
                        instance, old_D, owners, pair
                    )
                    trials.append(record)
                    alive.append(candidate)
                except Exception as exc:
                    msg = {
                        "scene": scene, "profile": profile, "seed": seed,
                        "arm": arm, "pair": pair,
                        "type": type(exc).__name__, "message": str(exc),
                    }
                    result["errors"].append(msg)
                    trials.append({"error": msg})
            valid = [
                (r, solution) for r, solution in zip(trials, alive)
                if "after" in r
            ]
            if len(valid) != n:
                raise RuntimeError("Pair trial error; no equal budget claim allowed")
            best, solution = min(
                valid, key=lambda pair: (
                    queue_rank(pair[0]["after"]),
                    pair[0]["task_pair"],
                )
            )
            best_strict = _strict_numerical_check(instance, solution)
            row["policies"][arm] = {
                "trials": trials,
                "best": best,
                "strict_posthoc": best_strict,
                "strict_selection_cvx_calls": 0,
                "actual_candidate_CVX_posthoc_calls": 1,
            }
            write_json(output, result)
            print("P22_EXCHANGE_CASE=" + json.dumps({
                "scene": scene, "profile": profile, "seed": seed,
                "arm": arm, "trials": len(trials),
                "original_queue_pass": before["queue_necessary_pass"],
                "best_queue_pass": best["after"]["queue_necessary_pass"],
                "original_queue_reasons": before["queue_reason_count"],
                "best_queue_reasons": best["after"]["queue_reason_count"],
                "original_worst_late_s": before["worst_task_deadline_excess_s"],
                "best_worst_late_s": best["after"]["worst_task_deadline_excess_s"],
                "original_strict": original_strict["Stage1_and_Stage2_strict"],
                "best_strict": best_strict["Stage1_and_Stage2_strict"],
                "chosen_pair": best["task_pair"],
            }, ensure_ascii=False), flush=True)
        if content_hash(old_D) != frozen_sha:
            raise RuntimeError("Source D changed while P22 compared")
    result["complete"] = True
    summary = {
        "scene": scene,
        "source_cases": len(result["rows"]),
        "original_strict": sum(
            x["original_strict"]["Stage1_and_Stage2_strict"]
            for x in result["rows"]
        ),
        "policy": {
            arm: {
                "evaluated_cases": len(result["rows"]),
                "original_queue_pass": sum(
                    x["original_queue"]["queue_necessary_pass"]
                    for x in result["rows"]
                ),
                "best_queue_pass": sum(
                    x["policies"][arm]["best"]["after"]["queue_necessary_pass"]
                    for x in result["rows"]
                ),
                "best_strict": sum(
                    x["policies"][arm]["strict_posthoc"]["Stage1_and_Stage2_strict"]
                    for x in result["rows"]
                ),
                "new_strict_rescue_vs_original": sum(
                    x["policies"][arm]["strict_posthoc"]["Stage1_and_Stage2_strict"]
                    and not x["original_strict"]["Stage1_and_Stage2_strict"]
                    for x in result["rows"]
                ),
                "lost_original_strict": sum(
                    x["original_strict"]["Stage1_and_Stage2_strict"]
                    and not x["policies"][arm]["strict_posthoc"]["Stage1_and_Stage2_strict"]
                    for x in result["rows"]
                ),
            } for arm in ARMS
        },
        "errors": len(result["errors"]),
    }
    result["summary"] = summary
    write_json(output, result)
    print("P22_EXCHANGE_SCENE_SUMMARY=" +
          json.dumps(summary, ensure_ascii=False), flush=True)
    if result["errors"]:
        raise RuntimeError("P22 paired source evidence is incomplete")
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--cases", required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    run(args.source, args.output, [x.split(":") for x in args.cases.split(",")])
