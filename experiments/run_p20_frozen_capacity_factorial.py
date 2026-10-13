"""P20: fixed-D MEC bandwidth/CPU factorial, downstream of P19.

Mechanism-only development experiment, NOT an algorithm improvement or new
independent holdout. The same frozen original K80 B endpoints and the
bit-identical P19 original cheapest/regret2 repaired D are checked against
unchanged physics except explicitly scaled MEC CPU/BW capacity. No ALNS
iteration, insertion ranking, contact route, or MEC assignment is changed.
Numerical Stage1 AND independent Stage2 must both qualify for strict success.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from run_p12_insertion_finish_audit import (
    CASES, _strict_numerical_check, queue_metrics,
)
from run_p19_repair_order_factorial import (
    KINDS, _original_task_order, replay,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState, operators as ops
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.evaluation.validator import validate_solution

# Predefined sensitivity factors; do not tune them after reading outcomes.
FACTORS = {
    "unchanged": (1.0, 1.0),
    "CPU_x2": (2.0, 1.0),
    "BW_x2": (1.0, 2.0),
    "CPU_BW_x2": (2.0, 2.0),
    "CPU_BW_x4": (4.0, 4.0),
}
CANDIDATES = ("B_frozen", "cheapest_P19", "regret2_P19")


def perturb_resources(instance, cpu_factor: float, bw_factor: float):
    if cpu_factor < 1.0 or bw_factor < 1.0:
        raise ValueError("P20 requires only upward capacity perturbations")
    changed = replace(
        instance,
        mecs={
            mid: replace(
                site,
                cpu_ghz=site.cpu_ghz * cpu_factor,
                bandwidth_mhz=site.bandwidth_mhz * bw_factor,
            )
            for mid, site in instance.mecs.items()
        },
    )
    if content_hash(changed.tasks) != content_hash(instance.tasks):
        raise RuntimeError("Task physics or deadlines changed")
    if content_hash(changed.uavs) != content_hash(instance.uavs):
        raise RuntimeError("UAV physics changed")
    if content_hash(changed.contact_points) != content_hash(instance.contact_points):
        raise RuntimeError("Contact geometry changed")
    return changed


def _restored_p19_candidate(instance, source_solution, seed, original, kind):
    base = UavMecState(
        instance, deepcopy(source_solution), ScreenedProxyObjectiveEvaluator()
    )
    destroyed = ops.critical_task_removal(
        base, np.random.default_rng(seed + 4356),
        config=ops.DestroyConfig(),
    )
    order = _original_task_order(destroyed, kind)
    snapshot, solution = replay(destroyed, kind, "original_order", order)
    expected = original["repairs"][kind]["policies"]["original_order"]["finished_sha"]
    if snapshot["finished_sha"] != expected:
        raise RuntimeError("Reconstructed P19 original repair D SHA mismatch")
    if snapshot["route_only_sha"] != (
        original["repairs"][kind]["policies"]["original_order"]["route_only_sha"]
    ):
        raise RuntimeError("P19 route-only identity drift")
    if content_hash(solution) != expected:
        raise RuntimeError("P19 completion identity drift")
    return solution


def run(source_path: Path, p19_path: Path, output: Path, selected):
    if output.exists():
        raise FileExistsError(output)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    previous = json.loads(p19_path.read_text(encoding="utf-8"))
    scene = int(source["protocol"]["independent_scenario_seed"])
    cases = [(profile, int(seed)) for profile, seed in selected]
    if (
        not source.get("complete")
        or not previous.get("complete")
        or source.get("errors")
        or previous.get("errors")
        or scene not in CASES
        or any(pair not in CASES[scene] for pair in cases)
        or scene != next(iter({r["scene"] for r in previous["rows"]}))
    ):
        raise ValueError("P20 accepts only the intact, seen P19 K80 source archive")
    if len(cases) != len(set(cases)):
        raise ValueError("Duplicate case supplied")
    lookup = {
        (r["profile"], int(r["seed"]), r["method"]): r
        for r in source["rows"]
    }
    p19rows = {
        (r["profile"], int(r["seed"])): r
        for r in previous["rows"]
    }
    if set(p19rows) != set(cases):
        raise ValueError("P19 experiment and requested source cases differ")

    data = {
        "complete": False,
        "protocol": {
            "id": "P20_P19_exact_frozen_D_resource_capacity_factorial_v1",
            "scene": scene,
            "source_archive_sha": content_hash(source),
            "source_P19_archive_sha": content_hash(previous),
            "factor_order": list(FACTORS),
            "capacities": FACTORS,
            "candidates": list(CANDIDATES),
            "original_ALNS_not_rerun": True,
            "all_original_routes_and_MEC_assignment_frozen": True,
            "no_algorithm_or_Stage1_Stage2_model_changes": True,
            "extra_independent_CVX_postpaid": True,
            "previously_inspected_development_scenarios": True,
            "not_a_matched_wall_budget_algorithm_comparison": True,
            "not_a_global_physical_feasibility_certificate": True,
        },
        "rows": [], "errors": [],
    }
    write_json(output, data)
    strict_cache = {}
    for profile, seed in cases:
        instance = restore_instance(source["profiles"][profile]["instance"])
        frozen_i = source["profiles"][profile]["instance_sha256"]
        if content_hash(instance) != frozen_i:
            raise RuntimeError("Frozen physical instance changed")
        src_row = lookup[profile, seed, "B-ALNS"]
        frozen = restore_solution(src_row["solution"])
        original_sha = src_row["solution_sha256"]
        old = p19rows[profile, seed]
        if content_hash(frozen) != original_sha:
            raise RuntimeError("Frozen B endpoint changed")
        if original_sha != old["original_source_B_sha"]:
            raise RuntimeError("P19 parent source B SHA mismatch")

        solutions = {"B_frozen": deepcopy(frozen)}
        for kind in KINDS:
            solutions[f"{kind}_P19"] = _restored_p19_candidate(
                instance, frozen, seed, old, kind
            )
        if tuple(solutions) != CANDIDATES:
            raise AssertionError("Missing fixed candidate")
        row = {
            "scene": scene,
            "profile": profile, "seed": seed,
            "instance_sha": frozen_i,
            "source_B_sha": original_sha,
            "methods": {},
        }
        data["rows"].append(row)
        write_json(output, data)

        for label, solution in solutions.items():
            fixed_D_sha = content_hash(solution)
            entry = {"fixed_D_sha": fixed_D_sha, "capacities": {}}
            row["methods"][label] = entry
            for factor, (cpu, bw) in FACTORS.items():
                try:
                    varied = perturb_resources(instance, cpu, bw)
                    assert content_hash(solution) == fixed_D_sha
                    validate_solution(varied, solution)
                    queue = queue_metrics(varied, solution)
                    key = (content_hash(varied), fixed_D_sha)
                    if key not in strict_cache:
                        strict_cache[key] = _strict_numerical_check(
                            varied, deepcopy(solution)
                        )
                    numerical = strict_cache[key]
                    entry["capacities"][factor] = {
                        "cpu_factor": cpu,
                        "bandwidth_factor": bw,
                        "instance_sha": content_hash(varied),
                        "fixed_D_sha": fixed_D_sha,
                        "queue": queue,
                        "strict": numerical,
                        "strict_both": numerical["Stage1_and_Stage2_strict"],
                    }
                except Exception as exc:
                    err = {
                        "scene": scene, "profile": profile,
                        "seed": seed, "candidate": label, "factor": factor,
                        "type": type(exc).__name__, "message": str(exc),
                    }
                    data["errors"].append(err)
                    entry["capacities"][factor] = {"error": err}
                    write_json(output, data)
                    raise
                write_json(output, data)
            before = entry["capacities"]["unchanged"]
            old_record = old["repairs"].get(label.removesuffix("_P19"), {})
            if old_record:
                original_bool = old_record["policies"]["original_order"][
                    "strict_posthoc"
                ]["Stage1_and_Stage2_strict"]
                if bool(before["strict_both"]) != bool(original_bool):
                    data["errors"].append({
                        "scene": scene, "profile": profile,
                        "seed": seed, "candidate": label,
                        "message": "Original P19 strict classification drift",
                    })
            summary = {
                "scene": scene, "profile": profile,
                "seed": seed, "candidate": label,
                "fixed_D_sha": fixed_D_sha,
                "MEC_offloaded_count": before["queue"]["MEC_offloaded_count"],
                "MEC_contact_count": before["queue"]["MEC_contact_count"],
                "queue_pass": {k: v["queue"]["queue_necessary_pass"]
                               for k, v in entry["capacities"].items()},
                "strict_pass": {k: v["strict_both"]
                                for k, v in entry["capacities"].items()},
                "stage1_status": {
                    k: v["strict"]["Stage1_solver_status"]
                    for k, v in entry["capacities"].items()
                },
            }
            print("P20_CAPACITY_CASE=" + json.dumps(summary), flush=True)
        if content_hash(frozen) != original_sha:
            raise RuntimeError("Source changed during P20 factorial")

    by_candidate = {}
    for label in CANDIDATES:
        records = [r["methods"][label]["capacities"] for r in data["rows"]]
        by_candidate[label] = {
            f: {
                "n": len(records),
                "queue_necessary_pass": sum(
                    bool(r[f]["queue"]["queue_necessary_pass"]) for r in records
                ),
                "stage1_strict": sum(
                    bool(r[f]["strict"]["Stage1_strict_qualified"]) for r in records
                ),
                "Stage1_and_Stage2_strict": sum(
                    bool(r[f]["strict_both"]) for r in records
                ),
                "gained_strict_vs_unchanged": sum(
                    bool(r[f]["strict_both"]) and
                    not bool(r["unchanged"]["strict_both"])
                    for r in records
                ),
                "lost_strict_vs_unchanged": sum(
                    bool(r["unchanged"]["strict_both"]) and
                    not bool(r[f]["strict_both"])
                    for r in records
                ),
            }
            for f in FACTORS
        }
    data["summary"] = {
        "scene": scene,
        "frozen_physical_cases": len(data["rows"]),
        "candidate_structures": len(data["rows"]) * len(CANDIDATES),
        "planned_capacity_numerical_checks": (
            len(data["rows"]) * len(CANDIDATES) * len(FACTORS)
        ),
        "unique_numerical_checks_executed": len(strict_cache),
        "by_candidate": by_candidate,
        "errors": len(data["errors"]),
    }
    data["complete"] = True
    write_json(output, data)
    print("P20_CAPACITY_SCENE_SUMMARY=" + json.dumps(data["summary"]), flush=True)
    if data["errors"]:
        raise RuntimeError("P20 capacity or original identity audit failed: " +
                           str(data["errors"][:2]))
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--p19", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", required=True)
    args = parser.parse_args()
    run(
        args.source, args.p19, args.output,
        [item.split(":") for item in args.cases.split(",")],
    )
