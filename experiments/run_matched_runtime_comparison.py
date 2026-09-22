from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from uav_mec.analysis import build_paper_metrics
from uav_mec.algorithms import (
    GARouteConfig,
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_fixed_route_nearest_mec_solution,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_route_ga,
    run_uav_mec_alns,
    run_uav_mec_hybrid_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _stage1_status(result) -> str:
    return str(result.diagnostics.get("stage1_status", result.status))


def _strict_energy(result) -> float | None:
    if result.feasible and _stage1_status(result) == "optimal":
        return float(result.energy_stage1_j)
    return None


def _solution_summary(instance, solution) -> dict[str, Any]:
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


def _verify_stage1(instance, solution) -> tuple[Any, float]:
    solver = CVXResourceSolver(run_stage2=False)
    info = build_event_info(instance, solution)
    started = perf_counter()
    result = solver.solve(instance, solution, info)
    return result, perf_counter() - started


def _extract_paper_metrics(
    instance,
    solution,
    *,
    verified_energy_j: float,
    reference_distance_m: float,
) -> tuple[dict[str, Any] | None, str | None, float]:
    info = build_event_info(instance, solution)
    solver = CVXResourceSolver(
        run_stage2=True,
        energy_tol_rel=1e-5,
    )
    started = perf_counter()
    result = solver.solve(instance, solution, info)
    runtime_s = perf_counter() - started
    status = _stage1_status(result)
    if not result.feasible or status != "optimal":
        return (
            None,
            (
                "metrics_recompute_not_strict: "
                f"stage1={status}, "
                f"stage2={result.diagnostics.get('stage2_status')}"
            ),
            runtime_s,
        )

    delta = abs(float(result.energy_stage1_j) - verified_energy_j)
    tolerance = max(
        1e-3,
        2e-6 * max(1.0, abs(verified_energy_j)),
    )
    if delta > tolerance:
        return (
            None,
            f"metrics_energy_mismatch: delta={delta:.6g}J",
            runtime_s,
        )

    return (
        build_paper_metrics(
            instance,
            solution,
            result,
            info=info,
            reference_distance_m=reference_distance_m,
        ),
        None,
        runtime_s,
    )


def _finalize_method(
    instance,
    solution,
    *,
    search_runtime_s: float,
    search_budget_s: float | None,
    reference_distance_m: float,
    paper_metrics: bool,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verified, verification_runtime_s = _verify_stage1(
        instance,
        solution,
    )
    status = _stage1_status(verified)
    energy_j = _strict_energy(verified)

    metrics = None
    metrics_error = None
    metrics_runtime_s = 0.0
    if paper_metrics and energy_j is not None:
        metrics, metrics_error, metrics_runtime_s = (
            _extract_paper_metrics(
                instance,
                solution,
                verified_energy_j=energy_j,
                reference_distance_m=reference_distance_m,
            )
        )

    return {
        "stage1_status": status,
        "stage1_feasible": bool(verified.feasible),
        "energy_j": energy_j,
        "search_runtime_s": search_runtime_s,
        "search_budget_s": search_budget_s,
        "search_budget_overrun_s": (
            max(0.0, search_runtime_s - search_budget_s)
            if search_budget_s is not None
            else None
        ),
        "stage1_verification_runtime_s": verification_runtime_s,
        "stage2_metrics_runtime_s": metrics_runtime_s,
        "paper_metrics": metrics,
        "paper_metrics_error": metrics_error,
        "solution": _solution_summary(instance, solution),
        "diagnostics": diagnostics or {},
    }


def _write(
    path: Path,
    *,
    experiment: dict[str, Any],
    rows: list[dict[str, Any]],
    complete: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "complete": complete,
                "experiment": experiment,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _method_order(seed: int) -> list[str]:
    base = ["rga_mr", "b_alns", "esi_alns"]
    offset = {100: 0, 101: 1, 102: 2}.get(seed, seed % 3)
    return base[offset:] + base[:offset]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Matched wall-clock comparison for RGA-MR, B-ALNS and ESI-ALNS "
            "with unified Stage-1 verification and optional Stage-2 metrics."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument("--scenario-seeds", default="45")
    parser.add_argument("--algorithm-seeds", default="100")
    parser.add_argument("--time-budget-s", type=float, required=True)
    parser.add_argument(
        "--esi-exploration-budget-s",
        type=float,
        required=True,
    )
    parser.add_argument(
        "--esi-elite-budget-s",
        type=float,
        required=True,
    )
    parser.add_argument(
        "--rrt-iterations",
        type=int,
        required=True,
        help=(
            "RRT threshold schedule horizon; wall-clock stopping still "
            "controls the actual B-ALNS/ESI exploration runtime"
        ),
    )
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--ga-population", type=int, default=24)
    parser.add_argument(
        "--ga-max-generations",
        type=int,
        default=100000,
    )
    parser.add_argument(
        "--include-deterministic",
        action="store_true",
        help="also evaluate GR-MR and FTR-NM once for this scenario",
    )
    parser.add_argument("--paper-metrics", action="store_true")
    parser.add_argument("--budget-factor", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.time_budget_s <= 0:
        raise ValueError("--time-budget-s must be positive")
    if args.esi_exploration_budget_s < 0:
        raise ValueError("--esi-exploration-budget-s must be non-negative")
    if args.esi_elite_budget_s < 0:
        raise ValueError("--esi-elite-budget-s must be non-negative")
    if (
        args.esi_exploration_budget_s + args.esi_elite_budget_s
        > args.time_budget_s + 1e-9
    ):
        raise ValueError(
            "ESI phase budgets may not exceed the total time budget"
        )
    if args.rrt_iterations <= 0:
        raise ValueError("--rrt-iterations must be positive")

    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)
    cfg = load_paper_scale_config(args.config)
    out = Path(args.output)
    experiment = {
        "tasks": args.tasks,
        "mecs": args.mecs,
        "uavs": args.uavs,
        "scenario_seeds": scenario_seeds,
        "algorithm_seeds": algorithm_seeds,
        "time_budget_s": args.time_budget_s,
        "esi_exploration_budget_s": args.esi_exploration_budget_s,
        "esi_elite_budget_s": args.esi_elite_budget_s,
        "rrt_iterations": args.rrt_iterations,
        "elite_rounds": args.elite_rounds,
        "ga_population": args.ga_population,
        "ga_max_generations": args.ga_max_generations,
        "budget_factor": args.budget_factor,
        "paper_metrics": args.paper_metrics,
        "include_deterministic": args.include_deterministic,
        "timing_protocol": "docs/compute_budget_protocol.md",
    }
    rows: list[dict[str, Any]] = []

    for scenario_seed in scenario_seeds:
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=args.tasks,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=scenario_seed,
        )

        route_started = perf_counter()
        route_seed = build_greedy_initial_solution(instance)
        route_seed_runtime_s = perf_counter() - route_started
        route_seed_info = build_event_info(instance, route_seed)
        route_seed_distance_m = sum(
            route_seed_info.route_distance_m.values()
        )

        repair_started = perf_counter()
        initial = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )
        mec_repair_runtime_s = perf_counter() - repair_started

        deterministic: dict[str, Any] = {}
        if args.include_deterministic:
            deterministic["gr_mr"] = _finalize_method(
                instance,
                initial,
                search_runtime_s=(
                    route_seed_runtime_s + mec_repair_runtime_s
                ),
                search_budget_s=None,
                reference_distance_m=route_seed_distance_m,
                paper_metrics=args.paper_metrics,
                diagnostics={
                    "route_seed_runtime_s": route_seed_runtime_s,
                    "mec_repair_runtime_s": mec_repair_runtime_s,
                    "independence_unit": "scenario",
                },
            )

            ftr_started = perf_counter()
            ftr_solution = build_fixed_route_nearest_mec_solution(
                instance,
                base_solution=route_seed,
            )
            ftr_repair_runtime_s = perf_counter() - ftr_started
            deterministic["ftr_nm"] = _finalize_method(
                instance,
                ftr_solution,
                search_runtime_s=(
                    route_seed_runtime_s + ftr_repair_runtime_s
                ),
                search_budget_s=None,
                reference_distance_m=route_seed_distance_m,
                paper_metrics=args.paper_metrics,
                diagnostics={
                    "route_seed_runtime_s": route_seed_runtime_s,
                    "nearest_mec_repair_runtime_s": (
                        ftr_repair_runtime_s
                    ),
                    "independence_unit": "scenario",
                },
            )

        for algorithm_seed in algorithm_seeds:
            methods: dict[str, Any] = dict(deterministic)
            execution_order = _method_order(algorithm_seed)

            for method in execution_order:
                if method == "rga_mr":
                    started = perf_counter()
                    ga_result = run_route_ga(
                        instance,
                        seed=algorithm_seed,
                        config=GARouteConfig(
                            population_size=args.ga_population,
                            generations=args.ga_max_generations,
                            max_runtime_s=args.time_budget_s,
                        ),
                    )
                    search_runtime_s = perf_counter() - started
                    methods[method] = _finalize_method(
                        instance,
                        ga_result.best_solution,
                        search_runtime_s=search_runtime_s,
                        search_budget_s=args.time_budget_s,
                        reference_distance_m=route_seed_distance_m,
                        paper_metrics=args.paper_metrics,
                        diagnostics={
                            "completed_generations": (
                                ga_result.generations
                            ),
                            "distinct_evaluations": (
                                ga_result.evaluations
                            ),
                            "cache_hits": ga_result.cache_hits,
                            "proxy_feasible": (
                                ga_result.best_proxy.score
                                .violated_constraints
                                == 0
                            ),
                        },
                    )

                elif method == "b_alns":
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    started = perf_counter()
                    result = run_uav_mec_alns(
                        instance,
                        initial_solution=initial,
                        config=UavMecALNSConfig(
                            iterations=args.rrt_iterations,
                            seed=algorithm_seed,
                            max_runtime_s=args.time_budget_s,
                        ),
                        evaluator=evaluator,
                    )
                    search_runtime_s = perf_counter() - started
                    completed_iterations = sum(
                        sum(counts)
                        for counts in result.operator_pair_counts.values()
                    )
                    methods[method] = _finalize_method(
                        instance,
                        result.best_solution,
                        search_runtime_s=search_runtime_s,
                        search_budget_s=args.time_budget_s,
                        reference_distance_m=route_seed_distance_m,
                        paper_metrics=args.paper_metrics,
                        diagnostics={
                            "completed_iterations": (
                                completed_iterations
                            ),
                            "screened_cvx_refinements": (
                                evaluator.stats.cvx_refinements
                            ),
                            "screened_precheck_rejects": (
                                evaluator.stats.precheck_rejects
                            ),
                            "alns_internal_runtime_s": float(
                                result.raw_result.statistics.total_runtime
                            ),
                        },
                    )

                elif method == "esi_alns":
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    started = perf_counter()
                    result = run_uav_mec_hybrid_alns(
                        instance,
                        initial_solution=initial,
                        config=UavMecALNSConfig(
                            iterations=args.rrt_iterations,
                            seed=algorithm_seed,
                        ),
                        evaluator=evaluator,
                        elite_rounds=args.elite_rounds,
                        exploration_max_runtime_s=(
                            args.esi_exploration_budget_s
                        ),
                        elite_max_runtime_s=(
                            args.esi_elite_budget_s
                        ),
                    )
                    search_runtime_s = perf_counter() - started
                    completed_iterations = sum(
                        sum(counts)
                        for counts
                        in result.exploration.operator_pair_counts.values()
                    )
                    methods[method] = _finalize_method(
                        instance,
                        result.best_solution,
                        search_runtime_s=search_runtime_s,
                        search_budget_s=args.time_budget_s,
                        reference_distance_m=route_seed_distance_m,
                        paper_metrics=args.paper_metrics,
                        diagnostics={
                            "completed_iterations": (
                                completed_iterations
                            ),
                            "exploration_budget_s": (
                                args.esi_exploration_budget_s
                            ),
                            "elite_budget_s": args.esi_elite_budget_s,
                            "exploration_runtime_s": (
                                result.exploration_runtime_s
                            ),
                            "elite_phase_runtime_s": (
                                result.elite_phase_runtime_s
                            ),
                            "elite_intensification_runtime_s": (
                                result.elite_runtime_s
                            ),
                            "elite_cvx_calls": result.elite_cvx_calls,
                            "elite_cvx_cache_hits": (
                                result.elite_cvx_cache_hits
                            ),
                            "elite_budget_exhausted": bool(
                                result.elite_stats.get(
                                    "budget_exhausted",
                                    False,
                                )
                            ),
                            "accepted_moves": list(
                                result.elite_stats.get(
                                    "accepted_moves",
                                    [],
                                )
                            ),
                            "screened_cvx_refinements": (
                                evaluator.stats.cvx_refinements
                            ),
                            "screened_precheck_rejects": (
                                evaluator.stats.precheck_rejects
                            ),
                        },
                    )
                else:
                    raise RuntimeError(f"Unknown method {method}")

            row = {
                "K": args.tasks,
                "M": args.uavs,
                "E": args.mecs,
                "scenario_seed": scenario_seed,
                "algorithm_seed": algorithm_seed,
                "budget_factor": args.budget_factor,
                "time_budget_s": args.time_budget_s,
                "rrt_iterations": args.rrt_iterations,
                "execution_order": execution_order,
                "common_route_seed_runtime_s": route_seed_runtime_s,
                "common_mec_repair_runtime_s": mec_repair_runtime_s,
                "route_seed_distance_m": route_seed_distance_m,
                "methods": methods,
            }
            rows.append(row)
            _write(
                out,
                experiment=experiment,
                rows=rows,
                complete=False,
            )

            parts = [
                f"K={args.tasks}",
                f"S={scenario_seed}",
                f"A={algorithm_seed}",
                f"B={args.time_budget_s:.0f}s",
            ]
            for name in (
                "rga_mr",
                "b_alns",
                "esi_alns",
            ):
                record = methods[name]
                energy = record["energy_j"]
                parts.append(
                    f"{name}:{record['stage1_status']}/"
                    + (f"{energy:.1f}J" if energy is not None else "-")
                    + f"/{record['search_runtime_s']:.1f}s"
                )
            print(" | ".join(parts))

    _write(
        out,
        experiment=experiment,
        rows=rows,
        complete=True,
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
