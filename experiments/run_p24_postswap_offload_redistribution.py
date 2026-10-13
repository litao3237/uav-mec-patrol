"""P24: exact-MEC-CPU post-swap one-step offload rebalancing (development).

P23 found that one frozen two-UAV exchange repairs S91's optimistic queue
deadline, yet original MEC CPU leaves Stage1 infeasible while CPUx2 passes.
Here ORIGINAL hardware/model stays fixed. Reconstruct exactly the P22
queue-selected D by SHA and enumerate legal one-task CPU redistribution:
offload -> local, offload -> existing later alternate-MEC visit, or
offload -> one NEW alternate-MEC contact. The original solver and FIFO/EDF
constraints remain untouched. Test three cheap rankings over the IDENTICAL
generated candidate pool, with <=3 strict CVX posthoc checks per ranking.

This is NOT an original ALNS improvement or unseen independent validation.
Never use CPUx2 in any accepted candidate; report failed cases too.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from run_p12_insertion_finish_audit import (
    CASES, _strict_numerical_check, queue_metrics,
)
from run_p22_deadline_cross_uav_exchange import (
    ARMS as P22_ARMS, one_cross_uav_exchange, owner_map,
)
from uav_mec.algorithms.alns import operators as ops
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations, _existing_contacts_after_task,
    _next_visit_id,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.domain import (
    ContactVisit, ExecutionMode, Route, RouteStop, TaskDecision,
)
from uav_mec.evaluation import build_event_info, visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)

P24_POLICIES = ("cpu_lb_rank", "queue_rank", "heavy_task_rank")
PARENT_ARMS = ("deadline_critical_pairs", "random_cross_uav_pairs")
STRICT_SELECTED_PER_POLICY = 3
MAX_ALTERNATE_MEC_CONTACT_POINTS = 2


def _one_task_offload_moves(instance, source):
    """Exact legal candidate D with only one offload task decision changed."""
    validate_solution(instance, source)
    info = build_event_info(instance, source)
    original_sha = content_hash(source)
    seen = {solution_signature(source)}
    candidates = []
    skipped = Counter()
    for tid in sorted(instance.tasks):
        old_decision = source.task_decisions[tid]
        if old_decision.mode is not ExecutionMode.OFFLOAD:
            continue
        old_visit = old_decision.contact_visit_id
        old_mid = visit_mec_id(instance, source, old_visit)
        owner = info.task_owner[tid]
        actions = []

        local = deepcopy(source)
        local.task_decisions[tid] = TaskDecision.local()
        actions.append((f"local::{tid}", local))

        for visit_id in _existing_contacts_after_task(source, tid):
            if visit_mec_id(instance, source, visit_id) != old_mid:
                changed = deepcopy(source)
                changed.task_decisions[tid] = TaskDecision.offload(visit_id)
                actions.append((f"reuse::{tid}->{visit_id}", changed))

        diverse = _best_new_contact_locations(
            instance, source, tid,
            limit=max(8, len(instance.contact_points)),
            per_mec=MAX_ALTERNATE_MEC_CONTACT_POINTS,
        )
        by_mec = Counter()
        for detour, point_id, pos in diverse:
            mid = instance.contact_points[point_id].mec_id
            if mid == old_mid or by_mec[mid] >= MAX_ALTERNATE_MEC_CONTACT_POINTS:
                continue
            by_mec[mid] += 1
            changed = deepcopy(source)
            new_id = _next_visit_id(changed, owner)
            stops = list(changed.routes[owner].stops)
            stops.insert(pos, RouteStop.contact(new_id))
            changed.routes[owner] = Route(owner, tuple(stops))
            changed.contact_visits[new_id] = ContactVisit(new_id, owner, point_id)
            changed.task_decisions[tid] = TaskDecision.offload(new_id)
            actions.append((f"new::{tid}->{mid}:{point_id}@{pos}", changed))

        for label, candidate in actions:
            try:
                ops._cleanup_orphan_contacts(candidate)
                validate_solution(instance, candidate)
                signature = solution_signature(candidate)
                if signature in seen:
                    skipped["duplicate_physical_D"] += 1
                    continue
                seen.add(signature)
                if content_hash(source) != original_sha:
                    raise RuntimeError("P24 changed its frozen source D")
                candidates.append((label, tid, candidate))
            except (ValueError, KeyError) as exc:
                skipped["invalid_" + type(exc).__name__] += 1
    return candidates, dict(skipped)


def _audit_candidate(instance, candidate):
    t = perf_counter()
    q = queue_metrics(instance, candidate)
    bound = station_cpu_share_necessary_bound(instance, candidate)
    stations = bound["stations"]
    pressure = [
        x["min_cpu_pressure_ratio"]
        for x in stations.values()
        if x["min_cpu_pressure_ratio"] is not None
    ]
    excess = [
        x["excess_cpu_ghz_lb"]
        for x in stations.values()
        if x["excess_cpu_ghz_lb"] is not None
    ]
    return {
        "queue": q,
        "cpu_lb": {
            "certified_cpu_share_failure": bound["certified_cpu_share_failure"],
            "max_station_cpu_pressure_lb_ratio": max(pressure, default=0.),
            "sum_station_cpu_excess_lb_ghz": sum(excess),
            "per_station": {
                mid: {
                    "cpu_capacity": x["capacity_ghz"],
                    "required_cpu_ghz_lb": x["required_cpu_lb_ghz"],
                    "pressure_lb_ratio": x["min_cpu_pressure_ratio"],
                    "certified_violation": x["necessary_capacity_violation"],
                }
                for mid, x in stations.items()
            },
            "binding_pairs": [
                {
                    "pair": pair,
                    "needed_cpu_ghz_lb": info["needed_cpu_ghz_lb"],
                    "deadline_binding": info["deadline_binding"],
                }
                for pair, info in sorted(bound["pair_demands"].items())
            ],
        },
        "observation_wall_s": perf_counter() - t,
    }


def _key(record, policy):
    q = record["audit"]["queue"]
    cpu = record["audit"]["cpu_lb"]
    # No candidate may be called strictly feasible because the queue gate passes.
    gate = (not q["queue_necessary_pass"], q["queue_reason_count"])
    if policy == "cpu_lb_rank":
        return gate + (
            cpu["certified_cpu_share_failure"],
            cpu["sum_station_cpu_excess_lb_ghz"],
            cpu["max_station_cpu_pressure_lb_ratio"],
            q["total_normalized_all_constraint_excess"],
            q["route_total_distance_m"],
            record["label"],
        )
    if policy == "queue_rank":
        return gate + (
            q["total_normalized_all_constraint_excess"],
            q["worst_task_deadline_excess_s"],
            q["route_total_distance_m"],
            record["label"],
        )
    if policy == "heavy_task_rank":
        return gate + (
            -record["task_workload_gcycles"],
            q["total_normalized_all_constraint_excess"],
            record["label"],
        )
    raise ValueError(policy)


def run(source_path: Path, p22_path: Path, output: Path, cases):
    if output.exists():
        raise FileExistsError(output)
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    previous = json.loads(p22_path.read_text(encoding="utf-8"))
    scene = int(raw["protocol"]["independent_scenario_seed"])
    selected = [(p, int(s)) for p, s in cases]
    if (
        not raw.get("complete")
        or not previous.get("complete")
        or previous.get("errors")
        or scene not in CASES
        or any(s not in CASES[scene] for s in selected)
        or set(selected) != {
            (r["profile"], int(r["seed"])) for r in previous["rows"]
        }
    ):
        raise ValueError("P24 requires exact completed P22 previously exposed K80 sources")
    if previous["protocol"]["id"] != "P22_critical_deadline_two_UAV_task_swap_v1":
        raise ValueError("Not a frozen P22 source")
    lookup = {
        (r["profile"], int(r["seed"]), r["method"]): r
        for r in raw["rows"]
    }
    prior = {
        (r["profile"], int(r["seed"])): r
        for r in previous["rows"]
    }
    data = {
        "complete": False,
        "protocol": {
            "id": "P24_original_capacity_postswap_offload_one_task_redistribution_v1",
            "scene": scene,
            "original_source_sha": content_hash(raw),
            "P22_source_sha": content_hash(previous),
            "P22_arms": PARENT_ARMS,
            "policies": P24_POLICIES,
            "strict_checks_per_policy": STRICT_SELECTED_PER_POLICY,
            "identical_complete_candidate_pool_per_policy": True,
            "same_original_Stage1_Stage2_and_resource_capacity": True,
            "physical_MEC_hardware_unchanged": True,
            "expensive_strict_CVX_posthoc_after_cheap_rank_only": True,
            "already_inspected_development_cases": True,
            "not_equal_wall_ALNS_algorithm_comparison": True,
        },
        "rows": [], "errors": [],
    }
    write_json(output, data)

    for profile, seed in selected:
        instance = restore_instance(raw["profiles"][profile]["instance"])
        i_sha = raw["profiles"][profile]["instance_sha256"]
        if content_hash(instance) != i_sha:
            raise RuntimeError("Original physical instance SHA mismatch")
        source_row = lookup[profile, seed, "B-ALNS"]
        original = restore_solution(source_row["solution"])
        original_sha = source_row["solution_sha256"]
        if content_hash(original) != original_sha:
            raise RuntimeError("Frozen original B SHA mismatch")
        frozen_p22 = prior[profile, seed]
        row = {
            "scene": scene, "profile": profile, "seed": seed,
            "physical_instance_sha": i_sha, "original_B_SHA": original_sha,
            "P22_parent_arm_results": {},
        }
        data["rows"].append(row)
        write_json(output, data)

        for parent in PARENT_ARMS:
            ref = frozen_p22["policies"][parent]
            pair = tuple(ref["best"]["task_pair"])
            restored, base = one_cross_uav_exchange(
                instance, original, owner_map(original), pair
            )
            source_sha = content_hash(base)
            if source_sha != ref["best"]["finished_D_sha"]:
                raise RuntimeError("P24 failed to reproduce exact selected P22 D SHA")

            original_audit = _audit_candidate(instance, base)
            base_strict = _strict_numerical_check(instance, deepcopy(base))
            if (
                bool(base_strict["Stage1_and_Stage2_strict"])
                != bool(ref["strict_posthoc"]["Stage1_and_Stage2_strict"])
            ):
                raise RuntimeError("Original P22 fixed resource baseline disagrees")
            generated, skip = _one_task_offload_moves(instance, base)
            pool = []
            kept = {}
            for label, tid, proposal in generated:
                sha = content_hash(proposal)
                score = _audit_candidate(instance, proposal)
                entry = {
                    "label": label, "task": tid,
                    "task_workload_gcycles": instance.tasks[tid].workload_gcycles,
                    "candidate_SHA": sha,
                    "audit": score,
                }
                pool.append(entry)
                kept[sha] = proposal
            if not pool:
                raise RuntimeError("P24 found no legal one-task offload redistribution")

            out = {
                "frozen_swap_pair": list(pair),
                "exact_original_p22_D_SHA": source_sha,
                "original_postswap_queue_cpu": original_audit,
                "original_postswap_strict": base_strict,
                "complete_candidate_pool_n": len(pool),
                "skipped": skip,
                "candidate_pool": pool,
                "policies": {},
            }
            row["P22_parent_arm_results"][parent] = out
            write_json(output, data)
            strict_cache = {}
            for policy in P24_POLICIES:
                ranked = sorted(pool, key=lambda record: _key(record, policy))
                chosen = ranked[:STRICT_SELECTED_PER_POLICY]
                checked = []
                for proposal_record in chosen:
                    sha = proposal_record["candidate_SHA"]
                    if sha not in strict_cache:
                        strict_cache[sha] = _strict_numerical_check(
                            instance, deepcopy(kept[sha])
                        )
                    strict = strict_cache[sha]
                    checked.append({
                        "label": proposal_record["label"],
                        "candidate_SHA": sha,
                        "queue_pass": proposal_record["audit"]["queue"][
                            "queue_necessary_pass"
                        ],
                        "cpu_lb_certified_failure": proposal_record["audit"][
                            "cpu_lb"]["certified_cpu_share_failure"],
                        "stage1": strict["Stage1_strict_qualified"],
                        "strict_both": strict["Stage1_and_Stage2_strict"],
                        "strict": strict,
                    })
                out["policies"][policy] = {
                    "same_pool_sha": [
                        p["candidate_SHA"] for p in pool
                    ],
                    "checked": checked,
                    "strict_Stage1_and_Stage2_success": any(
                        x["strict_both"] for x in checked
                    ),
                    "strict_qualified_count": sum(
                        bool(x["strict_both"]) for x in checked
                    ),
                    "selected_budget": len(checked),
                }
                write_json(output, data)
                print("P24_OFFLOAD_CASE=" + json.dumps({
                    "scene": scene, "profile": profile, "seed": seed,
                    "parent": parent, "policy": policy,
                    "pool_n": len(pool),
                    "baseline_queue_pass": original_audit["queue"]["queue_necessary_pass"],
                    "baseline_CPU_bound": original_audit["cpu_lb"]["certified_cpu_share_failure"],
                    "baseline_strict": base_strict["Stage1_and_Stage2_strict"],
                    "selected": [
                        {
                            "action": v["label"],
                            "queue_pass": v["queue_pass"],
                            "cpu_necessary_fail": v["cpu_lb_certified_failure"],
                            "stage1": v["stage1"],
                            "strict": v["strict_both"],
                        }
                        for v in checked
                    ],
                }, ensure_ascii=False), flush=True)

        if content_hash(original) != original_sha:
            raise RuntimeError("Modified original paper B solution")
    data["complete"] = True
    data["summary"] = {
        "physical_cases": len(data["rows"]),
        "parent_arms": len(PARENT_ARMS),
        "policies": {
            policy: {
                "checked": sum(
                    len(r["P22_parent_arm_results"][parent]["policies"][
                        policy]["checked"])
                    for r in data["rows"] for parent in PARENT_ARMS
                ),
                "strict_positive_parents": sum(
                    bool(r["P22_parent_arm_results"][parent]["policies"][
                        policy]["strict_Stage1_and_Stage2_success"])
                    for r in data["rows"] for parent in PARENT_ARMS
                ),
            }
            for policy in P24_POLICIES
        },
        "errors": len(data["errors"]),
    }
    write_json(output, data)
    print("P24_OFFLOAD_SCENE_SUMMARY=" + json.dumps(
        {"scene": scene, **data["summary"]}, ensure_ascii=False
    ), flush=True)
    return data


if __name__ == "__main__":
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--source", type=Path, required=True)
    arg.add_argument("--p22", type=Path, required=True)
    arg.add_argument("--cases", required=True)
    arg.add_argument("--output", type=Path, required=True)
    args = arg.parse_args()
    run(
        args.source, args.p22, args.output,
        [x.split(":") for x in args.cases.split(",")],
    )
