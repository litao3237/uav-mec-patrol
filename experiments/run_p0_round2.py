"""P0 round-2: paired cross-route move families on a *shared original ESI elite*.

This is an additional-search quality pilot, not a matched-wall-clock study.
The original B-ALNS exploration and original ESI run only once per seed.
Every new route neighborhood forks from the same strictly validated original
ESI endpoint, so the baseline's best candidates can never be displaced.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from experiment_common import current_source_hashes, provenance, stage_snapshot
from run_p0_pilot import parse_numbers, stage2_check
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
from uav_mec.algorithms.alns.elite_route_neighborhoods import (
    CrossRouteConfig, FAMILIES, run_cross_route_refinement,
)
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


PROFILES = {
    "original": (),
    "swap": ("swap",),
    "two_opt_star": ("two_opt_star",),
    "block_relocate": ("block_relocate",),
    "combined": FAMILIES,
}


def summarize(rows):
    summary = []
    for tasks in sorted({x["tasks"] for x in rows}):
        for profile in PROFILES:
            relevant = [x for x in rows if x["tasks"] == tasks and x["profile"] == profile]
            valid = [x for x in relevant if x["strict_pair"]]
            by_scenario = {}
            for row in valid:
                by_scenario.setdefault(row["scenario_seed"], []).append(row)
            def scalar_mean(field):
                if not by_scenario:
                    return None
                return mean(
                    mean(item[field] for item in group)
                    for group in by_scenario.values()
                )
            summary.append({
                "tasks": tasks,
                "profile": profile,
                "planned": len(relevant),
                "strict_pairs": len(valid),
                "independent_scenarios": len(by_scenario),
                "mean_added_saving_j": scalar_mean("gain_vs_original_esi_j"),
                "mean_added_saving_pct": scalar_mean("gain_vs_original_esi_pct"),
                "mean_total_saving_vs_B_j": scalar_mean("gain_vs_B_j"),
                "mean_total_saving_vs_B_pct": scalar_mean("gain_vs_B_pct"),
                "added_improvements": sum(
                    item["gain_vs_original_esi_j"] > 1.0 for item in valid
                ),
                "additional_refinement_s_mean": mean(
                    item["additional_refinement_s"] for item in relevant
                ) if relevant else None,
                "additional_cvx_calls_mean": mean(
                    item["additional_cvx_calls"] for item in relevant
                ) if relevant else None,
                "stage2_qualified": sum(
                    bool(row["stage2"] and row["stage2"]["qualified"])
                    for row in relevant
                ),
            })
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="50")
    parser.add_argument("--scenarios", default="45,46")
    parser.add_argument("--seeds", default="100,101")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--geometry-pool", type=int, default=18)
    parser.add_argument("--cvx-per-round", type=int, default=6)
    parser.add_argument("--extra-rounds", type=int, default=2)
    parser.add_argument("--with-stage2", action="store_true")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite results at {args.output}")

    cfg = load_paper_scale_config(args.config)
    move_cfg = CrossRouteConfig(
        geometric_pool_per_family=args.geometry_pool,
        cvx_per_round=args.cvx_per_round,
        max_rounds=args.extra_rounds,
    )
    payload = {
        "complete": False,
        "protocol": {
            "id": "p0_round2_preserve_original_elite_v1",
            "tasks": parse_numbers(args.tasks),
            "scenarios": parse_numbers(args.scenarios),
            "seeds": parse_numbers(args.seeds),
            "iterations": args.iterations,
            "elite_rounds": args.elite_rounds,
            "extra_config": asdict(move_cfg),
            "profiles": {name: list(families) for name, families in PROFILES.items()},
            "shared_base_exploration": True,
            "shared_original_esi_endpoint": True,
            "baseline_preservation": "all extra arms fork from strict CVX-validated original ESI",
            "budget": "same additional 6 strict solves per round; measured extra work, NOT equal wall time",
            "with_stage2": args.with_stage2,
            "provenance": provenance(),
            "source_hashes": current_source_hashes(Path(__file__)),
        },
        "rows": [],
    }
    write_json(args.output, payload)
    try:
        for K in parse_numbers(args.tasks):
            for scenario in parse_numbers(args.scenarios):
                instance = build_paper_scale_instance(
                    cfg, num_tasks=K, num_uavs=5, num_mecs=2,
                    scenario_seed=scenario,
                )
                initial_start = perf_counter()
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=build_greedy_initial_solution(instance),
                )
                initialization_s = perf_counter() - initial_start
                for seed in parse_numbers(args.seeds):
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    started = perf_counter()
                    explore = run_uav_mec_alns(
                        instance, initial_solution=deepcopy(initial),
                        config=UavMecALNSConfig(iterations=args.iterations, seed=seed),
                        evaluator=evaluator,
                    )
                    exploration_s = perf_counter() - started
                    base_solution = deepcopy(explore.best_solution)
                    base_oracle = Stage1CVXObjectiveOracle()
                    base_res = base_oracle.solve(instance, base_solution)
                    base_ok = stage1_is_qualified(base_res)
                    base_energy = (
                        float(base_res.energy_stage1_j) if base_ok else None
                    )

                    original = deepcopy(base_solution)
                    original_stats = {"skipped": "B-ALNS not strictly validated"}
                    original_runtime = 0.0
                    if base_ok:
                        started = perf_counter()
                        original_state, original_stats = contact_mode_intensification(
                            UavMecState(
                                instance, deepcopy(base_solution), evaluator,
                            ),
                            config=UavMecALNSConfig().problem,
                            objective=base_oracle,
                            max_rounds=args.elite_rounds,
                        )
                        original_runtime = perf_counter() - started
                        original = original_state.solution
                    original_res = base_oracle.solve(instance, original)
                    original_ok = stage1_is_qualified(original_res)
                    original_energy = (
                        float(original_res.energy_stage1_j) if original_ok else None
                    )
                    original_sha = content_hash(original)

                    for profile, families in PROFILES.items():
                        oracle = Stage1CVXObjectiveOracle()
                        oracle.prime(instance, original, original_res)
                        candidate = deepcopy(original)
                        extra_stats = {}
                        additional_s = 0.0
                        if families and original_ok:
                            started = perf_counter()
                            candidate, extra_stats = run_cross_route_refinement(
                                instance, original, objective=oracle,
                                families=tuple(families), config=move_cfg,
                            )
                            additional_s = perf_counter() - started
                        final_res = oracle.solve(instance, candidate)
                        final_ok = stage1_is_qualified(final_res)
                        strict_pair = bool(base_ok and original_ok and final_ok)
                        final_energy = (
                            float(final_res.energy_stage1_j) if final_ok else None
                        )
                        added_gain = (
                            original_energy - final_energy if strict_pair else None
                        )
                        if strict_pair and added_gain < -1e-3:
                            raise RuntimeError(
                                f"P0-r2 energy regression K{K} S{scenario} A{seed} "
                                f"{profile}: {added_gain:.6f} J"
                            )
                        row = {
                            "tasks": K,
                            "scenario_seed": scenario,
                            "seed": seed,
                            "profile": profile,
                            "instance_sha256": content_hash(instance),
                            "initial_solution_sha256": content_hash(initial),
                            "base_solution_sha256": content_hash(base_solution),
                            "original_esi_solution_sha256": original_sha,
                            "final_solution_sha256": content_hash(candidate),
                            "strict_pair": strict_pair,
                            "base_energy_j": base_energy,
                            "original_esi_energy_j": original_energy,
                            "final_energy_j": final_energy,
                            "gain_vs_original_esi_j": added_gain,
                            "gain_vs_original_esi_pct": (
                                100.0 * added_gain / max(1.0, abs(original_energy))
                                if strict_pair else None
                            ),
                            "gain_vs_B_j": (
                                base_energy - final_energy if strict_pair else None
                            ),
                            "gain_vs_B_pct": (
                                100.0 * (base_energy - final_energy)
                                / max(1.0, abs(base_energy)) if strict_pair else None
                            ),
                            "initialization_s": initialization_s,
                            "exploration_s": exploration_s,
                            "original_esi_s": original_runtime,
                            "original_esi_cvx_calls": base_oracle.calls,
                            "original_esi_stats": original_stats,
                            "additional_refinement_s": additional_s,
                            "additional_cvx_calls": oracle.calls,
                            "additional_cache_hits": oracle.cache_hits,
                            "additional_oracle_records": oracle.solve_records,
                            "extra_stats": extra_stats,
                            "base_stage1": stage_snapshot(
                                instance, base_solution, base_res, stage=1,
                            ),
                            "original_esi_stage1": stage_snapshot(
                                instance, original, original_res, stage=1,
                            ),
                            "final_stage1": stage_snapshot(
                                instance, candidate, final_res, stage=1,
                            ),
                            "stage2": stage2_check(
                                instance, candidate, final_res, args.with_stage2,
                            ),
                        }
                        payload["rows"].append(row)
                        write_json(args.output, payload)
                        print(
                            f"P0R2_PROGRESS K{K} S{scenario} A{seed} {profile}: "
                            f"extra_gain={added_gain} J, extra_cvx={oracle.calls}, "
                            f"extra_s={additional_s:.3f}, "
                            f"stage2={bool(row['stage2'] and row['stage2']['qualified'])}",
                            flush=True,
                        )
        payload["summary"] = summarize(payload["rows"])
        payload["complete"] = True
        write_json(args.output, payload)
        print("P0R2_SUMMARY=" + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    except Exception as exc:
        payload["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(args.output, payload)
        raise


if __name__ == "__main__":
    main()
