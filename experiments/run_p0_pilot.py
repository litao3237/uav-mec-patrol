"""P0 paired elite-neighborhood pilot: one frozen B-ALNS checkpoint per seed.

This experiment is deliberately separate from the paper's archived runs.
The three elite arms have the same starting discrete solution, Stage-1 oracle,
acceptance threshold, shortlist size and maximum rounds. Actual runtimes
and actual CVX solve counts are reported rather than called equal.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from experiment_common import current_source_hashes, provenance, stage_snapshot
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


PROFILES = ("baseline", "cross_uav", "cross_uav_route2")


def parse_numbers(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def experiment_config(base, profile: str):
    if profile == "baseline":
        return base
    if profile == "cross_uav":
        return replace(base, elite_diversify_route_uavs=True)
    if profile == "cross_uav_route2":
        return replace(
            base,
            elite_diversify_route_uavs=True,
            elite_route_shortlist_quota=2,
        )
    raise ValueError(profile)


def report_summary(rows: list[dict]) -> list[dict]:
    result = []
    for tasks in sorted({row["tasks"] for row in rows}):
        for profile in PROFILES:
            subset = [
                row for row in rows
                if row["tasks"] == tasks and row["profile"] == profile
            ]
            qualified = [row for row in subset if row["strict_pair"]]
            per_scenario: dict[int, list[dict]] = {}
            for row in qualified:
                per_scenario.setdefault(row["scenario_seed"], []).append(row)
            scenario_means = [
                mean(x["saving_pct"] for x in group)
                for _, group in sorted(per_scenario.items())
            ]
            result.append({
                "tasks": tasks,
                "profile": profile,
                "planned": len(subset),
                "strict_pairs": len(qualified),
                "independent_scenarios": len(per_scenario),
                "mean_saving_pct_scenario_equal": (
                    mean(scenario_means) if scenario_means else None
                ),
                "mean_saving_j_scenario_equal": (
                    mean(
                        mean(x["saving_j"] for x in group)
                        for group in per_scenario.values()
                    ) if per_scenario else None
                ),
                "improved_runs": sum(x["saving_j"] > 1.0 for x in qualified),
                "unchanged_runs": sum(abs(x["saving_j"]) <= 1.0 for x in qualified),
                "mean_elite_runtime_s": (
                    mean(x["elite_runtime_s"] for x in subset) if subset else None
                ),
                "mean_oracle_cvx_calls": (
                    mean(x["oracle_cvx_calls"] for x in subset) if subset else None
                ),
                "stage2_qualified_runs": sum(
                    bool(x["stage2"] and x["stage2"]["qualified"])
                    for x in subset
                ),
            })
    return result


def stage2_check(instance, solution, stage1, enabled: bool):
    if not enabled or not stage1_is_qualified(stage1):
        return None
    started = perf_counter()
    outcome = solve_stage2_realization(
        instance, solution, build_event_info(instance, solution),
        energy_star_j=stage1.energy_stage1_j,
        energy_tolerance_j=stage1.diagnostics["energy_tolerance_j"],
    )
    # The Stage-2 function already audits saved and earliest physical
    # timelines, including the energy guard, before setting accepted.
    return {
        "qualified": bool(outcome["accepted"]),
        "status": outcome["status"],
        "solver": outcome["solver"],
        "energy_j": outcome["energy_j"],
        "runtime_s": perf_counter() - started,
        "attempts": outcome["attempts"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="50")
    parser.add_argument("--scenarios", default="45,46")
    parser.add_argument("--seeds", default="100,101")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--with-stage2", action="store_true")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite experiment: {args.output}")

    cfg = load_paper_scale_config(args.config)
    payload = {
        "complete": False,
        "protocol": {
            "id": "p0_cross_uav_elite_paired_v1",
            "tasks": parse_numbers(args.tasks),
            "scenarios": parse_numbers(args.scenarios),
            "seeds": parse_numbers(args.seeds),
            "iterations": args.iterations,
            "elite_rounds": args.elite_rounds,
            "with_stage2": args.with_stage2,
            "profiles": list(PROFILES),
            "shared_initial_and_B_ALNS_checkpoint": True,
            "time_budget": "fixed exploration iterations and elite shortlist/round limits; NOT matched wall clock",
            "analysis_metric": "strictly validated Stage-1 UAV energy; Stage-2 check separately recorded",
            "source_hashes": current_source_hashes(Path(__file__)),
            "provenance": provenance(),
        },
        "rows": [],
    }
    write_json(args.output, payload)

    try:
        for tasks in parse_numbers(args.tasks):
            for scenario in parse_numbers(args.scenarios):
                instance = build_paper_scale_instance(
                    cfg, num_tasks=tasks, num_uavs=5, num_mecs=2,
                    scenario_seed=scenario,
                )
                started = perf_counter()
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=build_greedy_initial_solution(instance),
                )
                initialization_s = perf_counter() - started
                for seed in parse_numbers(args.seeds):
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    started = perf_counter()
                    explore = run_uav_mec_alns(
                        instance,
                        initial_solution=deepcopy(initial),
                        config=UavMecALNSConfig(iterations=args.iterations, seed=seed),
                        evaluator=evaluator,
                    )
                    exploration_s = perf_counter() - started
                    baseline = deepcopy(explore.best_solution)
                    baseline_sha = content_hash(baseline)

                    baseline_oracle = Stage1CVXObjectiveOracle()
                    baseline_cvx = baseline_oracle.solve(instance, baseline)
                    base_ok = stage1_is_qualified(baseline_cvx)
                    base_energy = (
                        float(baseline_cvx.energy_stage1_j) if base_ok else None
                    )
                    for profile in PROFILES:
                        oracle = Stage1CVXObjectiveOracle()
                        oracle.prime(instance, baseline, baseline_cvx)
                        final_solution = deepcopy(baseline)
                        elite_stats = {
                            "rounds": 0,
                            "candidates_evaluated": 0,
                            "improvements": 0,
                            "selection_traces": [],
                            "evaluated_moves": [],
                            "accepted_moves": [],
                            "skipped": "unqualified_baseline",
                        }
                        started = perf_counter()
                        if base_ok:
                            state = UavMecState(
                                instance, deepcopy(baseline), evaluator,
                            )
                            refined, elite_stats = contact_mode_intensification(
                                state,
                                config=experiment_config(
                                    UavMecALNSConfig().problem, profile,
                                ),
                                objective=oracle,
                                max_rounds=args.elite_rounds,
                            )
                            final_solution = refined.solution
                        elite_runtime_s = perf_counter() - started
                        final_cvx = oracle.solve(instance, final_solution)
                        final_ok = stage1_is_qualified(final_cvx)
                        final_energy = (
                            float(final_cvx.energy_stage1_j) if final_ok else None
                        )
                        strict_pair = base_ok and final_ok
                        saving_j = (
                            base_energy - final_energy if strict_pair else None
                        )
                        if strict_pair and saving_j < -1e-3:
                            raise RuntimeError(
                                f"ESI accepted worsening result: {profile} K{tasks} "
                                f"S{scenario} seed{seed}: {saving_j:.4f} J"
                            )

                        row = {
                            "tasks": tasks,
                            "scenario_seed": scenario,
                            "algorithm_seed": seed,
                            "profile": profile,
                            "instance_sha256": content_hash(instance),
                            "initial_sha256": content_hash(initial),
                            "base_solution_sha256": baseline_sha,
                            "final_solution_sha256": content_hash(final_solution),
                            "initialization_s": initialization_s,
                            "exploration_s": exploration_s,
                            "baseline_oracle_cvx_calls": baseline_oracle.calls,
                            "base_energy_j": base_energy,
                            "final_energy_j": final_energy,
                            "strict_pair": strict_pair,
                            "saving_j": saving_j,
                            "saving_pct": (
                                100.0 * saving_j / max(1.0, abs(base_energy))
                                if strict_pair else None
                            ),
                            "elite_runtime_s": elite_runtime_s,
                            "oracle_cvx_calls": oracle.calls,
                            "oracle_cache_hits": oracle.cache_hits,
                            "oracle_solve_records": oracle.solve_records,
                            "elite_stats": elite_stats,
                            "base_stage1": stage_snapshot(
                                instance, baseline, baseline_cvx, stage=1,
                            ),
                            "final_stage1": stage_snapshot(
                                instance, final_solution, final_cvx, stage=1,
                            ),
                            "stage2": stage2_check(
                                instance, final_solution, final_cvx, args.with_stage2,
                            ),
                        }
                        payload["rows"].append(row)
                        write_json(args.output, payload)
                        print(
                            f"P0_PROGRESS K{tasks} S{scenario} seed{seed} "
                            f"{profile}: gain={saving_j}J "
                            f"cvx_calls={oracle.calls} elite_s={elite_runtime_s:.3f} "
                            f"stage2_ok={bool(row['stage2'] and row['stage2']['qualified'])}",
                            flush=True,
                        )
        payload["summary"] = report_summary(payload["rows"])
        payload["complete"] = True
        write_json(args.output, payload)
        print("P0_RESULT=" + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    except Exception as exc:
        payload["execution_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        write_json(args.output, payload)
        raise


if __name__ == "__main__":
    main()
