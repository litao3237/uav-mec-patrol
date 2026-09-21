from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_hybrid_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def _compact_list_tag(values: list[int]) -> str:
    return "-".join(str(value) for value in values)


def _default_output_path(
    *,
    task_counts: list[int],
    mec_counts: list[int],
    scenario_seeds: list[int],
    algorithm_seeds: list[int],
    iterations: int,
) -> Path:
    name = (
        "hybrid_validation"
        f"_K{_compact_list_tag(task_counts)}"
        f"_E{_compact_list_tag(mec_counts)}"
        f"_S{_compact_list_tag(scenario_seeds)}"
        f"_A{_compact_list_tag(algorithm_seeds)}"
        f"_I{iterations}.json"
    )
    return Path("outputs/results") / name


def _parse_int_list(text: str) -> list[int]:
    return [
        int(item.strip())
        for item in text.split(",")
        if item.strip()
    ]


def _move_family(label: str) -> str:
    if label.startswith("route_compute_relocate::"):
        return "route_compute_relocate"
    if label.startswith("contact_relocate::"):
        return "contact_relocate"
    if label == "contact_point_replace":
        return "contact_point_replace"
    if label.startswith("contact_remove::"):
        return "contact_remove"
    if label.startswith("batch_merge::"):
        return "batch_merge"
    if label.startswith("batch_split_or_new_contact::"):
        return "batch_split_or_new_contact"
    if label == "task_mode_or_batch_reassign":
        return "task_mode_or_batch_reassign"
    return "other"


def _stage1_status(result) -> str:
    return str(
        result.diagnostics.get(
            "stage1_status",
            result.status,
        )
    )


def _summary(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    return {
        "contacts": len(solution.contact_visits),
        "offloaded": sum(
            decision.mode.value == "offload"
            for decision in solution.task_decisions.values()
        ),
        "active_pairs": len(info.active_uav_mec_pairs),
        "distance_m": sum(info.route_distance_m.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Paired validation of generic ALNS exploration versus the "
            "same trajectory followed by exact elite structural refinement."
        )
    )
    parser.add_argument(
        "--config",
        default="configs/baseline.yaml",
    )
    parser.add_argument("--tasks", default="80")
    parser.add_argument("--mecs", default="2,3")
    parser.add_argument(
        "--scenario-seeds",
        default="42,43,44",
    )
    parser.add_argument(
        "--algorithm-seeds",
        default="100,101,102",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--elite-rounds",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--elite-shortlist-limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--elite-task-limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--elite-route-options-per-task",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--uavs",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "optional JSON output path; if omitted, a deterministic "
            "parameterized filename is used so validation runs do not "
            "overwrite one another"
        ),
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    task_counts = _parse_int_list(args.tasks)
    mec_counts = _parse_int_list(args.mecs)
    scenario_seeds = _parse_int_list(
        args.scenario_seeds
    )
    algorithm_seeds = _parse_int_list(
        args.algorithm_seeds
    )

    rows: list[dict[str, Any]] = []

    print(
        "K    E    scen   alg    base-s1      hybrid-s1    "
        "base-E-J       hybrid-E-J     improve-%   "
        "elite-cvx   accepted   search-s   elite-s   total-s"
    )
    print("-" * 154)

    for k in task_counts:
        for e in mec_counts:
            for scenario_seed in scenario_seeds:
                instance = build_paper_scale_instance(
                    cfg,
                    num_tasks=k,
                    num_uavs=args.uavs,
                    num_mecs=e,
                    scenario_seed=scenario_seed,
                )
                route_seed = build_greedy_initial_solution(
                    instance
                )
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=route_seed,
                )

                for algorithm_seed in algorithm_seeds:
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    base_config = UavMecALNSConfig(
                        iterations=args.iterations,
                        seed=algorithm_seed,
                    )
                    problem_config = base_config.problem
                    if args.elite_shortlist_limit is not None:
                        problem_config = replace(
                            problem_config,
                            elite_shortlist_limit=(
                                args.elite_shortlist_limit
                            ),
                        )
                    if args.elite_task_limit is not None:
                        problem_config = replace(
                            problem_config,
                            elite_task_limit=args.elite_task_limit,
                        )
                    if (
                        args.elite_route_options_per_task
                        is not None
                    ):
                        problem_config = replace(
                            problem_config,
                            elite_route_options_per_task=(
                                args.elite_route_options_per_task
                            ),
                        )
                    config = replace(
                        base_config,
                        problem=problem_config,
                    )

                    t0 = perf_counter()
                    result = run_uav_mec_hybrid_alns(
                        instance,
                        initial_solution=initial,
                        config=config,
                        evaluator=evaluator,
                        elite_rounds=args.elite_rounds,
                    )
                    total_runtime_s = perf_counter() - t0

                    base_status = _stage1_status(
                        result.exploration_cvx
                    )
                    final_status = _stage1_status(
                        result.final_cvx
                    )
                    base_energy = (
                        result.exploration_cvx_energy_j
                        if result.exploration_cvx.feasible
                        else None
                    )
                    final_energy = (
                        result.final_cvx_energy_j
                        if result.final_cvx.feasible
                        else None
                    )
                    improvement_pct = (
                        result.improvement_pct
                        if (
                            base_energy is not None
                            and final_energy is not None
                        )
                        else None
                    )
                    accepted_moves = list(
                        result.elite_stats.get(
                            "accepted_moves",
                            [],
                        )
                    )
                    search_runtime_s = float(
                        result.exploration.raw_result.statistics.total_runtime
                    )

                    row = {
                        "K": k,
                        "E": e,
                        "scenario_seed": scenario_seed,
                        "algorithm_seed": algorithm_seed,
                        "iterations": args.iterations,
                        "elite_rounds": args.elite_rounds,
                        "base_stage1_status": base_status,
                        "hybrid_stage1_status": final_status,
                        "base_cvx_feasible": (
                            result.exploration_cvx.feasible
                        ),
                        "hybrid_cvx_feasible": (
                            result.final_cvx.feasible
                        ),
                        "base_cvx_energy_j": base_energy,
                        "hybrid_cvx_energy_j": final_energy,
                        "improvement_pct": improvement_pct,
                        "elite_stats": result.elite_stats,
                        "elite_widenings": int(
                            result.elite_stats.get(
                                "widenings",
                                0,
                            )
                        ),
                        "elite_widened_candidates": int(
                            result.elite_stats.get(
                                "widened_candidates_evaluated",
                                0,
                            )
                        ),
                        "elite_config": {
                            "shortlist_limit": (
                                config.problem.elite_shortlist_limit
                            ),
                            "task_limit": (
                                config.problem.elite_task_limit
                            ),
                            "route_options_per_task": (
                                config.problem.elite_route_options_per_task
                            ),
                        },
                        "elite_cvx_calls": (
                            result.elite_cvx_calls
                        ),
                        "elite_cvx_cache_hits": (
                            result.elite_cvx_cache_hits
                        ),
                        "screened_cvx_refinements": (
                            evaluator.stats.cvx_refinements
                        ),
                        "screened_precheck_rejects": (
                            evaluator.stats.precheck_rejects
                        ),
                        "exploration_runtime_s": (
                            search_runtime_s
                        ),
                        "elite_runtime_s": (
                            result.elite_runtime_s
                        ),
                        "total_runtime_s": total_runtime_s,
                        "base_solution": _summary(
                            instance,
                            result.exploration.best_solution,
                        ),
                        "hybrid_solution": _summary(
                            instance,
                            result.best_solution,
                        ),
                    }
                    rows.append(row)

                    base_text = (
                        f"{base_energy:.3f}"
                        if base_energy is not None
                        else "-"
                    )
                    final_text = (
                        f"{final_energy:.3f}"
                        if final_energy is not None
                        else "-"
                    )
                    improve_text = (
                        f"{improvement_pct:.3f}"
                        if improvement_pct is not None
                        else "-"
                    )
                    move_text = (
                        ",".join(
                            str(move["move"])
                            for move in accepted_moves
                        )
                        if accepted_moves
                        else "-"
                    )
                    evaluated_moves = list(
                        result.elite_stats.get(
                            "evaluated_moves",
                            [],
                        )
                    )
                    best_rejected = None
                    comparable_moves = [
                        item
                        for item in evaluated_moves
                        if item["improvement_pct"] is not None
                    ]
                    if comparable_moves:
                        best_rejected = max(
                            comparable_moves,
                            key=lambda item: (
                                item["improvement_pct"]
                            ),
                        )
                    print(
                        f"{k:<4} "
                        f"{e:<4} "
                        f"{scenario_seed:<6} "
                        f"{algorithm_seed:<6} "
                        f"{base_status:<12} "
                        f"{final_status:<12} "
                        f"{base_text:<14} "
                        f"{final_text:<14} "
                        f"{improve_text:<11} "
                        f"{result.elite_cvx_calls:<11} "
                        f"{move_text:<10} "
                        f"{search_runtime_s:<10.2f} "
                        f"{result.elite_runtime_s:<9.2f} "
                        f"{total_runtime_s:.2f}"
                    )
                    if (
                        not accepted_moves
                        and best_rejected is not None
                    ):
                        print(
                            "  best elite candidate: "
                            f"{best_rejected['move']} "
                            f"delta={best_rejected['improvement_pct']:.3f}%"
                        )
                    widened_families = list(
                        result.elite_stats.get(
                            "widened_families",
                            [],
                        )
                    )
                    if widened_families:
                        print(
                            "  progressive widening: "
                            f"{widened_families} "
                            "extra_exact="
                            f"{result.elite_stats.get('widened_candidates_evaluated', 0)}"
                        )
                    skipped = result.elite_stats.get("skipped")
                    if skipped:
                        print(
                            f"  elite skipped: {skipped}"
                        )

    aggregate: list[dict[str, Any]] = []
    for k in task_counts:
        for e in mec_counts:
            subset = [
                row
                for row in rows
                if row["K"] == k and row["E"] == e
            ]
            if not subset:
                continue

            paired = [
                row
                for row in subset
                if (
                    row["base_cvx_feasible"]
                    and row["hybrid_cvx_feasible"]
                )
            ]
            strict_paired = [
                row
                for row in paired
                if (
                    row["base_stage1_status"] == "optimal"
                    and row["hybrid_stage1_status"] == "optimal"
                )
            ]
            improvements = [
                row["improvement_pct"]
                for row in paired
                if row["improvement_pct"] is not None
            ]
            strict_improvements = [
                row["improvement_pct"]
                for row in strict_paired
                if row["improvement_pct"] is not None
            ]
            strict_improved_runs = sum(
                value > 1e-9
                for value in strict_improvements
            )
            strict_unchanged_runs = sum(
                abs(value) <= 1e-9
                for value in strict_improvements
            )

            accepted_family_counts: dict[str, int] = {}
            accepted_move_count = 0
            for row in subset:
                for move in row["elite_stats"].get(
                    "accepted_moves",
                    [],
                ):
                    family = _move_family(str(move["move"]))
                    accepted_family_counts[family] = (
                        accepted_family_counts.get(family, 0) + 1
                    )
                    accepted_move_count += 1
            group = {
                "K": k,
                "E": e,
                "runs": len(subset),
                "paired_feasible_runs": len(paired),
                "strict_paired_runs": len(strict_paired),
                "strict_improved_runs": strict_improved_runs,
                "strict_unchanged_runs": strict_unchanged_runs,
                "strict_base_optimal_runs": sum(
                    row["base_stage1_status"] == "optimal"
                    for row in subset
                ),
                "strict_hybrid_optimal_runs": sum(
                    row["hybrid_stage1_status"] == "optimal"
                    for row in subset
                ),
                "improved_runs": sum(
                    value > 1e-9
                    for value in improvements
                ),
                "unchanged_runs": sum(
                    abs(value) <= 1e-9
                    for value in improvements
                ),
                "mean_base_cvx_energy_j": (
                    mean(
                        row["base_cvx_energy_j"]
                        for row in paired
                    )
                    if paired
                    else None
                ),
                "strict_mean_base_cvx_energy_j": (
                    mean(
                        row["base_cvx_energy_j"]
                        for row in strict_paired
                    )
                    if strict_paired
                    else None
                ),
                "mean_hybrid_cvx_energy_j": (
                    mean(
                        row["hybrid_cvx_energy_j"]
                        for row in paired
                    )
                    if paired
                    else None
                ),
                "strict_mean_hybrid_cvx_energy_j": (
                    mean(
                        row["hybrid_cvx_energy_j"]
                        for row in strict_paired
                    )
                    if strict_paired
                    else None
                ),
                "mean_improvement_pct": (
                    mean(improvements)
                    if improvements
                    else None
                ),
                "strict_mean_improvement_pct": (
                    mean(strict_improvements)
                    if strict_improvements
                    else None
                ),
                "median_improvement_pct": (
                    median(improvements)
                    if improvements
                    else None
                ),
                "strict_median_improvement_pct": (
                    median(strict_improvements)
                    if strict_improvements
                    else None
                ),
                "max_improvement_pct": (
                    max(improvements)
                    if improvements
                    else None
                ),
                "mean_elite_cvx_calls": mean(
                    row["elite_cvx_calls"]
                    for row in subset
                ),
                "mean_elite_widenings": mean(
                    row["elite_widenings"]
                    for row in subset
                ),
                "mean_elite_widened_candidates": mean(
                    row["elite_widened_candidates"]
                    for row in subset
                ),
                "mean_exploration_runtime_s": mean(
                    row["exploration_runtime_s"]
                    for row in subset
                ),
                "mean_elite_runtime_s": mean(
                    row["elite_runtime_s"]
                    for row in subset
                ),
                "mean_runtime_overhead_pct": mean(
                    100.0
                    * row["elite_runtime_s"]
                    / max(1e-12, row["exploration_runtime_s"])
                    for row in subset
                ),
                "widened_runs": sum(
                    row["elite_widenings"] > 0
                    for row in subset
                ),
                "mean_widened_candidates": mean(
                    row["elite_widened_candidates"]
                    for row in subset
                ),
                "accepted_move_count": accepted_move_count,
                "accepted_family_counts": accepted_family_counts,
                "mean_total_runtime_s": mean(
                    row["total_runtime_s"]
                    for row in subset
                ),
            }
            aggregate.append(group)

    print("\nAggregate")
    print(
        "K    E    runs   strict   s-improved   s-unchanged   "
        "strict-base-E-J strict-hybrid-E-J mean-gain-%   "
        "median-gain-%   elite-cvx   elite-s   widened   overhead-%"
    )
    print("-" * 126)
    for group in aggregate:
        base_text = (
            f"{group['strict_mean_base_cvx_energy_j']:.3f}"
            if group["strict_mean_base_cvx_energy_j"] is not None
            else "-"
        )
        final_text = (
            f"{group['strict_mean_hybrid_cvx_energy_j']:.3f}"
            if group["strict_mean_hybrid_cvx_energy_j"] is not None
            else "-"
        )
        mean_gain = (
            f"{group['strict_mean_improvement_pct']:.3f}"
            if group["strict_mean_improvement_pct"] is not None
            else "-"
        )
        median_gain = (
            f"{group['strict_median_improvement_pct']:.3f}"
            if group["strict_median_improvement_pct"] is not None
            else "-"
        )
        print(
            f"{group['K']:<4} "
            f"{group['E']:<4} "
            f"{group['runs']:<6} "
            f"{group['strict_paired_runs']:<8} "
            f"{group['strict_improved_runs']:<12} "
            f"{group['strict_unchanged_runs']:<13} "
            f"{base_text:<14} "
            f"{final_text:<14} "
            f"{mean_gain:<13} "
            f"{median_gain:<15} "
            f"{group['mean_elite_cvx_calls']:<11.2f} "
            f"{group['mean_elite_runtime_s']:<9.2f} "
            f"{group['widened_runs']:<9} "
            f"{group['mean_runtime_overhead_pct']:.2f}"
        )
        if group["accepted_family_counts"]:
            print(
                "  accepted families: "
                + ", ".join(
                    f"{name}={count}"
                    for name, count in sorted(
                        group["accepted_family_counts"].items()
                    )
                )
            )

    out = (
        Path(args.output)
        if args.output is not None
        else _default_output_path(
            task_counts=task_counts,
            mec_counts=mec_counts,
            scenario_seeds=scenario_seeds,
            algorithm_seeds=algorithm_seeds,
            iterations=args.iterations,
        )
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "experiment": {
                    "tasks": task_counts,
                    "mecs": mec_counts,
                    "scenario_seeds": scenario_seeds,
                    "algorithm_seeds": algorithm_seeds,
                    "iterations": args.iterations,
                    "elite_rounds": args.elite_rounds,
                    "uavs": args.uavs,
                },
                "aggregate": aggregate,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
