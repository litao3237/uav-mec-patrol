"""P0 direct replacement: integrate cross-UAV moves into existing ESI budget.

For each identical frozen B-ALNS checkpoint, compare published ESI against
new ESI variants replacing the contact-family candidates. No original ESI
is ever run before a new variant; each variant independently starts directly
from the same B-ALNS endpoint. All variants use six shortlisted candidates
per ESI round and two ESI rounds, with strict resource/energy validation.
This fixed-search-budget pilot is NOT an equal wall-clock budget study.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from experiment_common import provenance, stage_snapshot, current_source_hashes
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.problem_operators import contact_mode_intensification
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config
from uav_mec.optimization.resource.cvx_solver import solve_stage2_realization
from uav_mec.analysis.constraint_audit import audit_both_timelines


PROFILES = {
    "original_esi": (),
    "replace_contact_swap": ("swap",),
    "replace_contact_two_opt_star": ("two_opt_star",),
    "replace_contact_block_relocate": ("block_relocate",),
    "replace_contact_combined": ("swap", "two_opt_star", "block_relocate"),
}


def parse_ids(values: str) -> list[int]:
    return [int(part.strip()) for part in values.split(",") if part.strip()]


def profile_config(base, profile: str, geometric_pool: int):
    if profile == "original_esi":
        return base
    return replace(
        base,
        elite_enable_contact_relocate=False,
        elite_enable_contact_point_replace=False,
        elite_enable_contact_remove=False,
        elite_interroute_families=PROFILES[profile],
        elite_interroute_geometry_pool=geometric_pool,
    )


def evaluate_stage2(instance, solution, stage1, enabled: bool):
    if not enabled or not stage1_is_qualified(stage1):
        return None
    info = build_event_info(instance, solution)
    started = perf_counter()
    stage2 = solve_stage2_realization(
        instance, solution, info,
        energy_star_j=stage1.energy_stage1_j,
        energy_tolerance_j=stage1.diagnostics["energy_tolerance_j"],
    )
    audit = None
    if stage2["raw_values"] is not None:
        audit = audit_both_timelines(
            instance, solution, stage2["raw_values"],
            energy_limit_j=stage1.energy_stage1_j
                + stage1.diagnostics["energy_tolerance_j"],
        )
    qualified = bool(
        stage2["accepted"] and audit is not None
        and all(record["complete"] and record["passed"] for record in audit.values())
    )
    return {
        "qualified": qualified,
        "status": stage2["status"],
        "solver": stage2["solver"],
        "runtime_s": perf_counter() - started,
        "energy_j": stage2["energy_j"],
        "values": stage2["raw_values"],
        "audit": audit,
        "attempts": stage2["attempts"],
    }


def summarize(rows):
    output = []
    for K in sorted(set(int(x["tasks"]) for x in rows)):
        for profile in PROFILES:
            sample = [x for x in rows if x["tasks"] == K and x["profile"] == profile]
            valid = [x for x in sample if x["strict_pair"]]
            by_scenario = {}
            for row in valid:
                by_scenario.setdefault(row["scenario_seed"], []).append(row)
            def equal_mean(key):
                if not by_scenario:
                    return None
                return mean(
                    mean(x[key] for x in v) for _,v in sorted(by_scenario.items())
                )
            output.append({
                "tasks": K, "profile": profile,
                "planned": len(sample),
                "paired_stage1_valid": len(valid),
                "scenarios": len(by_scenario),
                "mean_saving_vs_B_j": equal_mean("gain_vs_B_j"),
                "mean_saving_vs_B_pct": equal_mean("gain_vs_B_pct"),
                "mean_diff_vs_original_esi_j": equal_mean("gain_vs_original_esi_j"),
                "mean_diff_vs_original_esi_pct": equal_mean("gain_vs_original_esi_pct"),
                "wins_vs_original_esi": sum(
                    row["gain_vs_original_esi_j"] > 1.0 for row in valid
                ),
                "losses_vs_original_esi": sum(
                    row["gain_vs_original_esi_j"] < -1.0 for row in valid
                ),
                "mean_esi_runtime_s": mean(x["esi_runtime_s"] for x in sample),
                "mean_stage1_cvx_calls": mean(x["cvx_calls"] for x in sample),
                "mean_esi_candidates_evaluated": mean(
                    x["esi_stats"].get("candidates_evaluated",0) for x in sample
                ),
                "stage2_qualified": sum(
                    bool(x["stage2"] and x["stage2"]["qualified"]) for x in sample
                ),
            })
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="50")
    parser.add_argument("--scenarios", default="45,46")
    parser.add_argument("--seeds", default="100,101")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--geometric-pool", type=int, default=12)
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--with-stage2", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refuse to overwrite: {args.output}")

    config = load_paper_scale_config(args.config)
    payload = {
        "complete": False,
        "protocol": {
            "id": "p0_integrated_esi_replace_contact_v1",
            "tasks": parse_ids(args.tasks),
            "scenarios": parse_ids(args.scenarios),
            "seeds": parse_ids(args.seeds),
            "iterations": args.iterations,
            "elite_rounds": args.elite_rounds,
            "geometric_pool": args.geometric_pool,
            "profiles": {x: list(y) for x,y in PROFILES.items()},
            "same_B_ALNS_shared_checkpoint": True,
            "each_esi_begins_at_the_B_ALNS_checkpoint": True,
            "no_postprocessing": True,
            "strict_CVX_shortlist_limit": UavMecALNSConfig().problem.elite_shortlist_limit,
            "comparison": "fixed shortlist/round; true measured wall time separately reported",
            "note": "replaces legacy ESI contact family; other original families and Stage-2 unchanged",
            "with_stage2": args.with_stage2,
            "provenance": provenance(),
            "source_hashes": current_source_hashes(Path(__file__)),
        },
        "rows": [],
    }
    write_json(args.output, payload)
    try:
        for K in parse_ids(args.tasks):
            for S in parse_ids(args.scenarios):
                instance = build_paper_scale_instance(
                    config, num_tasks=K, num_uavs=5, num_mecs=2,
                    scenario_seed=S,
                )
                initial_started = perf_counter()
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=build_greedy_initial_solution(instance),
                )
                init_s = perf_counter() - initial_started
                for seed in parse_ids(args.seeds):
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    exploration_start = perf_counter()
                    explore = run_uav_mec_alns(
                        instance, initial_solution=deepcopy(initial),
                        config=UavMecALNSConfig(iterations=args.iterations,seed=seed),
                        evaluator=evaluator,
                    )
                    exploration_s = perf_counter() - exploration_start
                    base = deepcopy(explore.best_solution)
                    base_oracle = Stage1CVXObjectiveOracle()
                    base_result = base_oracle.solve(instance, base)
                    base_ok = stage1_is_qualified(base_result)
                    E_B = float(base_result.energy_stage1_j) if base_ok else None
                    profiles = []
                    for profile in PROFILES:
                        oracle = Stage1CVXObjectiveOracle()
                        oracle.prime(instance, base, base_result)
                        final = deepcopy(base)
                        esi_stats = {
                            "rounds":0,"candidates_evaluated":0,
                            "accepted_moves":[],"evaluated_moves":[],
                            "skipped":"unqualified_B_ALNS",
                        }
                        elapsed = 0.0
                        if base_ok:
                            started = perf_counter()
                            elite_state, esi_stats = contact_mode_intensification(
                                UavMecState(instance, deepcopy(base), evaluator),
                                config=profile_config(
                                    UavMecALNSConfig().problem,
                                    profile, args.geometric_pool,
                                ),
                                objective=oracle,
                                max_rounds=args.elite_rounds,
                            )
                            elapsed = perf_counter() - started
                            final = elite_state.solution
                        resource = oracle.solve(instance, final)
                        good = stage1_is_qualified(resource)
                        E_new = float(resource.energy_stage1_j) if good else None
                        profiles.append({
                            "profile":profile,
                            "solution":final,
                            "resource":resource,
                            "valid":good,
                            "energy":E_new,
                            "cvx_calls":oracle.calls,
                            "esi_runtime_s":elapsed,
                            "oracle_records":oracle.solve_records,
                            "esi_stats":esi_stats,
                        })
                    original = profiles[0]
                    original_energy = original["energy"]
                    original_ok = original["valid"]
                    for p in profiles:
                        both_ok = bool(base_ok and original_ok and p["valid"])
                        E = p["energy"]
                        gain_B = E_B-E if both_ok else None
                        gain_orig = original_energy-E if both_ok else None
                        final_stage2 = evaluate_stage2(
                            instance, p["solution"], p["resource"], args.with_stage2,
                        )
                        row = {
                            "tasks":K,"scenario_seed":S,"seed":seed,
                            "profile":p["profile"],
                            "instance_sha256":content_hash(instance),
                            "B_solution_sha256":content_hash(base),
                            "solution_sha256":content_hash(p["solution"]),
                            "B_energy_j":E_B,
                            "original_esi_energy_j":original_energy,
                            "energy_j":E,
                            "strict_pair":both_ok,
                            "gain_vs_B_j":gain_B,
                            "gain_vs_B_pct":(
                                100*gain_B/max(1,abs(E_B)) if both_ok else None
                            ),
                            "gain_vs_original_esi_j":gain_orig,
                            "gain_vs_original_esi_pct":(
                                100*gain_orig/max(1,abs(original_energy)) if both_ok else None
                            ),
                            "initialization_s":init_s,
                            "B_exploration_s":exploration_s,
                            "esi_runtime_s":p["esi_runtime_s"],
                            "cvx_calls":p["cvx_calls"],
                            "oracle_records":p["oracle_records"],
                            "esi_stats":p["esi_stats"],
                            "stage1":stage_snapshot(
                                instance, p["solution"], p["resource"], stage=1
                            ),
                            "stage2":final_stage2,
                        }
                        payload["rows"].append(row)
                        write_json(args.output,payload)
                        print(
                            f"P0_INT K{K} S{S} A{seed} {p['profile']} "
                            f"diff_orig={gain_orig} J, CVX={p['cvx_calls']} "
                            f"t={p['esi_runtime_s']:.3f}s "
                            f"stage2_ok={bool(final_stage2 and final_stage2['qualified'])}",
                            flush=True,
                        )
        payload["summary"]=summarize(payload["rows"])
        payload["complete"]=True
        write_json(args.output,payload)
        print("P0_INT_SUMMARY="+json.dumps(payload["summary"],ensure_ascii=False),flush=True)
    except Exception as exc:
        payload["execution_error"]={"type":type(exc).__name__,"message":str(exc)}
        write_json(args.output,payload)
        raise


if __name__=="__main__":
    main()
