"""P0 gate 3: matched budget, protected ESI candidate selection.

Pre-registered study: four previously unused independent instance seeds
S53-S56, nested algorithm seeds A107-A108, K50 and K80. The analysis
includes failure/overrun coverage and does NOT tune profiles on these seeds.

Every method receives the same *nominal end-to-end* wall-time budget.
B-ALNS: 80% to exploration, 20% reserved for final strict resources.
ESI arms: 60% exploration + 20% total anchor/ESI, 20% reserved for final
resources. All ESI arms share one exactly identical 60%-budget B-ALNS
checkpoint. They fork from it rather than running the original ESI first.

Limits are soft: a single uninterruptible CVXPY call or route-generation
operation may overrun. Every duration, overrun and failed Stage-2 run is
recorded; no failed run is replaced with a synthetic energy.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import numpy as np

from experiment_common import provenance, current_source_hashes
from run_seven_methods import finalize
from run_p0_contact_diagnostics import profile_config
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
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


METHODS = (
    "B-ALNS",
    "original_esi",
    "fixed_two_opt_star",
    "replace_contact_slot",
    "protected_two_opt_star",
    "protected_two_opt_swap",
)
BUDGET_S = {50: 15.0, 80: 45.0}


def selection_profile(base, method: str, geometric_pool: int):
    """The baseline is untouched; others replace *within* the ESI phase."""
    if method == "original_esi":
        return base
    if method == "fixed_two_opt_star":
        return profile_config(
            base, "retain_remove_two_opt_star", geometric_pool
        )
    policy_kwargs = dict(
        elite_interroute_geometry_pool=geometric_pool,
        elite_reuse_cross_proxy_scores=True,
        elite_cross_min_remaining_s=0.65,
    )
    if method == "replace_contact_slot":
        # Generate old contact candidates; only their SELECTED slots can be
        # replaced by new cross-route 2-opt* moves. Original route, contact
        # deletion, batch and mode moves are protected from displacement.
        return replace(
            base,
            elite_interroute_families=("two_opt_star",),
            elite_selection_policy="replace_contact_slot",
            **policy_kwargs,
        )
    if method in {"protected_two_opt_star", "protected_two_opt_swap"}:
        families = (
            ("two_opt_star",) if method == "protected_two_opt_star"
            else ("two_opt_star", "swap")
        )
        # Discard only low-yield contact relocation/point replacement;
        # ALWAYS retain contact deletion, old route and batch moves.
        return replace(
            base,
            elite_enable_contact_relocate=False,
            elite_enable_contact_point_replace=False,
            elite_enable_contact_remove=True,
            elite_interroute_families=families,
            elite_selection_policy="protected_priority",
            **policy_kwargs,
        )
    raise ValueError(f"Unknown selection profile: {method}")


def slices(budget_s: float, init_s: float) -> dict[str, float]:
    """Budget allocations keep initialization inside the total budget."""
    if budget_s <= 0 or init_s < 0:
        raise ValueError("Budget must be positive and initialization nonnegative")
    return {
        "base_search_s": max(0.0, 0.8 * budget_s - init_s),
        "esi_exploration_s": max(0.0, 0.6 * budget_s - init_s),
        "esi_total_s": 0.2 * budget_s,
        "reserved_finalization_s": 0.2 * budget_s,
    }


def wall_clock_alns_config(seed: int, cap_s: float):
    return UavMecALNSConfig(
        seed=seed,
        iterations=100,
        max_runtime_s=cap_s,
        time_scaled_rrt=cap_s > 0.0,
        enable_problem_operators=False,
    )


def summarize(rows):
    output = []
    for K in sorted(set(r["tasks"] for r in rows)):
        per_k = [r for r in rows if r["tasks"] == K]
        blocks = {}
        for r in per_k:
            key = (r["scenario_seed"], r["algorithm_seed"])
            blocks.setdefault(key, {})[r["method"]] = r

        for method in METHODS:
            subset = [r for r in per_k if r["method"] == method]
            qualified = [r for r in subset if r["both_qualified"]]
            within_and_qualified = [
                r for r in qualified if r["within_nominal_budget"]
            ]
            def paired(metric_ref):
                pairs = []
                for (scenario, seed), block in blocks.items():
                    if method not in block or metric_ref not in block:
                        continue
                    curr, ref = block[method], block[metric_ref]
                    if not (curr["both_qualified"] and ref["both_qualified"]):
                        continue
                    pairs.append((scenario, ref["stage1_energy_j"] - curr["stage1_energy_j"]))
                groups = {}
                for scenario, gain in pairs:
                    groups.setdefault(scenario, []).append(gain)
                return {
                    "pairs": len(pairs),
                    "scenarios": len(groups),
                    "mean_gain_j": (
                        mean(mean(values) for values in groups.values())
                        if groups else None
                    ),
                    "per_scenario_mean_j": {
                        str(s): mean(gains) for s,gains in sorted(groups.items())
                    },
                    "wins": sum(diff > 1.0 for _,diff in pairs),
                    "losses": sum(diff < -1.0 for _,diff in pairs),
                    "ties": sum(abs(diff) <= 1.0 for _,diff in pairs),
                }

            output.append({
                "tasks": K,
                "method": method,
                "planned": len(subset),
                "both_qualified": len(qualified),
                "within_and_qualified": len(within_and_qualified),
                "overruns": sum(not r["within_nominal_budget"] for r in subset),
                "mean_end_to_end_s": mean(
                    r["measured_end_to_end_s"] for r in subset
                ),
                "mean_energy_j_qualified": (
                    mean(r["stage1_energy_j"] for r in qualified)
                    if qualified else None
                ),
                "vs_B_ALNS": paired("B-ALNS"),
                "vs_original_ESI": paired("original_esi"),
            })
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="50")
    parser.add_argument("--scenarios", default="53,54,55,56")
    parser.add_argument("--seeds", default="107,108")
    parser.add_argument("--geometric-pool", type=int, default=10)
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    task_sizes = [int(x) for x in args.tasks.split(",") if x.strip()]
    scenarios = [int(x) for x in args.scenarios.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    for K in task_sizes:
        if K not in BUDGET_S:
            raise ValueError(f"Unsupported task size {K} (budgets: {BUDGET_S})")
    cfg = load_paper_scale_config(args.config)
    payload = {
        "complete": False,
        "protocol": {
            "id": "p0_protected_elite_selector_holdout_v1",
            "tasks": task_sizes,
            "scenarios": scenarios,
            "seeds": seeds,
            "methods": list(METHODS),
            "budget_s": BUDGET_S,
            "time_allocation": "B 80% search; ESI arms 60% exploration + 20% anchor/ESI; all 20% reserved final validation",
            "selection_policy": "frozen before holdout S53-S56; single ESI phase and max six CVX candidate slots per round",
            "nested_samples": "2 algorithm seeds per independent scenario; scenarios weighted equally",
            "same_initial_solution_per_block": True,
            "same_60pct_B_ALNS_checkpoint_for_all_ESI_arms": True,
            "no_postprocessing": True,
            "time_limit": "soft: uninterruptible solves can overrun",
            "all_failures_preserved": True,
            "provenance": provenance(),
            "source_hashes": current_source_hashes(Path(__file__)),
        },
        "rows": [],
    }
    write_json(args.output, payload)
    try:
        for K in task_sizes:
            for scenario in scenarios:
                instance = build_paper_scale_instance(
                    cfg, num_tasks=K, num_uavs=5,
                    num_mecs=2, scenario_seed=scenario,
                )
                for seed in seeds:
                    init_started = perf_counter()
                    initial = build_mec_assisted_initial_solution(
                        instance,
                        base_solution=build_greedy_initial_solution(instance),
                    )
                    init_s = perf_counter() - init_started
                    init_hash = content_hash(initial)
                    budget = BUDGET_S[K]
                    alloc = slices(budget, init_s)
                    rows = []

                    def record(method, solution, *, search_s, stats):
                        # The time components are *individually measured*
                        # and added to describe what each fork would spend.
                        row = finalize(
                            instance, solution, method=method, seed=seed,
                            initialization_s=init_s, search_s=search_s,
                            diagnostics=stats,
                        )
                        actual = float(row["timing"]["total_with_audit_s"])
                        stage1_ok = bool(row["stage1"]["qualified"])
                        stage2_ok = bool(row["stage2"]["qualified"])
                        row.update(
                            tasks=K,
                            scenario_seed=scenario,
                            algorithm_seed=seed,
                            initial_sha256=init_hash,
                            method=method,
                            nominal_budget_s=budget,
                            measured_end_to_end_s=actual,
                            overrun_s=max(0.0, actual - budget),
                            within_nominal_budget=actual <= budget,
                            both_qualified=stage1_ok and stage2_ok,
                            stage1_energy_j=(
                                float(row["resources"].energy_stage1_j)
                                if stage1_ok else None
                            ),
                        )
                        rows.append(row)
                        payload["rows"].append(row)
                        write_json(args.output, payload)
                        print(
                            f"SELECTOR_BUDGET K{K} S{scenario} A{seed} {method}: "
                            f"qualified={stage1_ok and stage2_ok}, "
                            f"energy={row['stage1_energy_j']}, "
                            f"total_s={actual:.3f}/{budget}, "
                            f"overrun_s={row['overrun_s']:.3f}",
                            flush=True,
                        )

                    order = list(np.random.default_rng(
                        [20261010, K, scenario, seed],
                    ).permutation(["B", "ESI"]))
                    for component in order:
                        if component == "B":
                            started = perf_counter()
                            B = run_uav_mec_alns(
                                instance,
                                initial_solution=deepcopy(initial),
                                config=wall_clock_alns_config(
                                    seed, alloc["base_search_s"],
                                ),
                                evaluator=ScreenedProxyObjectiveEvaluator(),
                            )
                            elapsed = perf_counter() - started
                            record(
                                "B-ALNS", B.best_solution,
                                search_s=elapsed,
                                stats={
                                    "stop_reason": B.stop_reason,
                                    "stop_elapsed_s": B.stop_elapsed_s,
                                    "operator_pairs": B.operator_pair_counts,
                                    "exploration_budget_s": alloc["base_search_s"],
                                },
                            )
                        else:
                            evaluator = ScreenedProxyObjectiveEvaluator()
                            started = perf_counter()
                            exploration = run_uav_mec_alns(
                                instance, initial_solution=deepcopy(initial),
                                config=wall_clock_alns_config(
                                    seed, alloc["esi_exploration_s"],
                                ),
                                evaluator=evaluator,
                            )
                            exploration_s = perf_counter() - started
                            shared = deepcopy(exploration.best_solution)
                            shared_sha = content_hash(shared)
                            base_oracle = Stage1CVXObjectiveOracle()
                            started = perf_counter()
                            anchor = base_oracle.solve(instance, shared)
                            anchor_s = perf_counter() - started
                            anchor_valid = stage1_is_qualified(anchor)

                            esi_methods = list(np.random.default_rng(
                                [20261010, K, scenario, seed, 1],
                            ).permutation(list(METHODS[1:])))
                            for method in esi_methods:
                                oracle = Stage1CVXObjectiveOracle()
                                started = perf_counter()
                                oracle.prime(instance, shared, anchor)
                                prime_s = perf_counter() - started
                                remaining = max(
                                    0.0,
                                    alloc["esi_total_s"] - anchor_s - prime_s,
                                )
                                stats = {
                                    "shared_exploration_sha256": shared_sha,
                                    "exploration_s": exploration_s,
                                    "exploration_budget_s": alloc["esi_exploration_s"],
                                    "baseline_anchor_s": anchor_s,
                                    "prime_audit_s": prime_s,
                                    "esi_runtime_limit_s": remaining,
                                    "B_checkpoint_qualified": anchor_valid,
                                }
                                final = deepcopy(shared)
                                elite_s = 0.0
                                if anchor_valid:
                                    elite_started = perf_counter()
                                    final_state, elite_stats = contact_mode_intensification(
                                        UavMecState(
                                            instance, deepcopy(shared), evaluator,
                                        ),
                                        config=selection_profile(
                                            UavMecALNSConfig().problem,
                                            method, args.geometric_pool,
                                        ),
                                        objective=oracle,
                                        max_rounds=2,
                                        max_runtime_s=remaining,
                                    )
                                    elite_s = perf_counter() - elite_started
                                    final = final_state.solution
                                    stats["elite_stats"] = elite_stats
                                else:
                                    stats["elite_skipped"] = "B_checkpoint_not_strict_optimal"
                                stats["elite_s"] = elite_s
                                stats["cvx_calls"] = oracle.calls
                                record(
                                    method, final,
                                    search_s=exploration_s + anchor_s + prime_s + elite_s,
                                    stats=stats,
                                )

                    assert len(rows) == len(METHODS)
        payload["summary"] = summarize(payload["rows"])
        payload["complete"] = True
        write_json(args.output, payload)
        print("SELECTOR_SUMMARY=" + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    except Exception as exc:
        payload["execution_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        write_json(args.output, payload)
        raise


if __name__ == "__main__":
    main()
