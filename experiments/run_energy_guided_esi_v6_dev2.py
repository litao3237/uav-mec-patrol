from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from uav_mec.algorithms import (
    BudgetAwareTerminalFirstConfig,
    EnergyGuidedESIConfig,
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    make_energy_guided_intensifier,
    run_uav_mec_alns,
    run_uav_mec_budget_aware_terminal_first_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


METHODS = (
    "time_b_alns",
    "budget_v5",
    "energy_guided_no_dual",
    "energy_guided_v6",
)


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def _stage1_status(result) -> str:
    return str(result.diagnostics.get("stage1_status", result.status))


def _strict(result) -> bool:
    return bool(
        result.feasible
        and _stage1_status(result) == "optimal"
    )


def _verify(instance, solution) -> tuple[dict[str, Any], float]:
    solver = CVXResourceSolver(run_stage2=False)
    info = build_event_info(instance, solution)
    started = perf_counter()
    result = solver.solve(instance, solution, info)
    runtime_s = perf_counter() - started
    strict = _strict(result)
    return {
        "stage1_status": _stage1_status(result),
        "energy_j": (
            float(result.energy_stage1_j)
            if strict
            else None
        ),
        "strict": strict,
    }, runtime_s


def _iterations(result) -> int:
    return sum(
        sum(values)
        for values in result.operator_pair_counts.values()
    )


def _elite_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = 0
    exact_calls = 0
    strict_candidates = 0
    accepted = 0
    gain_j = 0.0
    exact_runtime_s = 0.0
    generated = 0
    ranked = 0
    accepted_moves: list[dict[str, Any]] = []
    hotspots: list[dict[str, Any]] = []

    for event in events:
        stats = event.get("elite_stats")
        if not isinstance(stats, dict):
            continue
        candidates += int(stats.get("candidates_evaluated", 0))
        exact_calls += int(
            stats.get(
                "exact_cvx_calls",
                stats.get("candidates_evaluated", 0),
            )
        )
        strict_candidates += int(
            stats.get("strict_candidates", 0)
        )
        accepted += int(stats.get("improvements", 0))
        gain_j += float(
            stats.get(
                "exact_improvement_j",
                sum(
                    float(move.get("improvement_j", 0.0))
                    for move in stats.get("accepted_moves", [])
                ),
            )
        )
        exact_runtime_s += float(
            stats.get("exact_runtime_s", 0.0)
        )
        generated += int(stats.get("generated_candidates", 0))
        ranked += int(stats.get("proxy_ranked_candidates", 0))
        accepted_moves.extend(
            list(stats.get("accepted_moves", []))
        )
        hotspots.extend(
            list(stats.get("hotspot_tasks", []))[:6]
        )

    return {
        "generated_candidates": generated,
        "proxy_ranked_candidates": ranked,
        "candidates_evaluated": candidates,
        "exact_cvx_calls": exact_calls,
        "strict_candidates": strict_candidates,
        "accepted_improvements": accepted,
        "accepted_gain_j": gain_j,
        "elite_exact_runtime_s": exact_runtime_s,
        "gain_per_cvx_j": (
            gain_j / exact_calls
            if exact_calls > 0
            else 0.0
        ),
        "gain_per_exact_second_jps": (
            gain_j / exact_runtime_s
            if exact_runtime_s > 1e-12
            else 0.0
        ),
        "strict_candidate_hit_rate": (
            strict_candidates / candidates
            if candidates > 0
            else 0.0
        ),
        "accepted_candidate_hit_rate": (
            accepted / candidates
            if candidates > 0
            else 0.0
        ),
        "accepted_moves": accepted_moves,
        "hotspot_tasks": hotspots,
    }


def _record(
    *,
    instance,
    solution,
    runtime_s: float,
    budget_s: float,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    verified, verification_runtime_s = _verify(
        instance,
        solution,
    )
    return {
        **verified,
        "method_runtime_s": runtime_s,
        "budget_s": budget_s,
        "budget_overrun_s": max(
            0.0,
            runtime_s - budget_s,
        ),
        "budget_utilization_pct": (
            100.0 * runtime_s / budget_s
        ),
        "verification_runtime_s": verification_runtime_s,
        "diagnostics": diagnostics,
    }


def _run_budget_method(
    *,
    instance,
    initial,
    algorithm_seed: int,
    budget_s: float,
    intensifier=None,
):
    evaluator = ScreenedProxyObjectiveEvaluator()
    started = perf_counter()
    result = run_uav_mec_budget_aware_terminal_first_alns(
        instance,
        initial_solution=deepcopy(initial),
        config=UavMecALNSConfig(
            iterations=100,
            seed=algorithm_seed,
        ),
        budget_aware=BudgetAwareTerminalFirstConfig(
            total_runtime_s=budget_s,
        ),
        evaluator=evaluator,
        elite_intensifier=intensifier,
    )
    runtime_s = perf_counter() - started
    diagnostics = {
        "selection_source": result.selection_source,
        "elite_triggers": result.elite_triggers,
        "elite_strict_improvements": (
            result.elite_strict_improvements
        ),
        "elite_injections": result.elite_injections,
        "elite_runtime_s": result.elite_runtime_s,
        "certification_runtime_s": (
            result.in_search_certification_runtime_s
        ),
        "terminal_certification_runtime_s": (
            result.terminal_certification_runtime_s
        ),
        "initial_reserve_s": result.initial_reserve_s,
        "final_reserve_s": result.final_reserve_s,
        "completed_iterations": _iterations(
            result.exploration
        ),
        "screened_cvx_refinements": (
            evaluator.stats.cvx_refinements
        ),
        "elite_efficiency": _elite_metrics(
            result.events
        ),
    }
    return result.best_solution, runtime_s, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument("--scenario-seed", type=int, required=True)
    parser.add_argument("--algorithm-seed", type=int, required=True)
    parser.add_argument("--time-budget-s", type=float, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=args.tasks,
        num_uavs=args.uavs,
        num_mecs=args.mecs,
        scenario_seed=args.scenario_seed,
    )
    route_seed = build_greedy_initial_solution(instance)
    initial = build_mec_assisted_initial_solution(
        instance,
        base_solution=route_seed,
    )

    methods: dict[str, Any] = {}
    order = list(METHODS)
    offset = args.algorithm_seed % len(order)
    order = order[offset:] + order[:offset]

    for method in order:
        if method == "time_b_alns":
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                    max_runtime_s=args.time_budget_s,
                    time_scaled_rrt=True,
                ),
                evaluator=evaluator,
            )
            runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                runtime_s=runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "completed_iterations": _iterations(result),
                    "screened_cvx_refinements": (
                        evaluator.stats.cvx_refinements
                    ),
                },
            )
            continue

        if method == "budget_v5":
            intensifier = None
        elif method == "energy_guided_no_dual":
            intensifier = make_energy_guided_intensifier(
                EnergyGuidedESIConfig(
                    deadline_dual_weight=0.0,
                    cycle_dual_weight=0.0,
                )
            )
        elif method == "energy_guided_v6":
            intensifier = make_energy_guided_intensifier(
                EnergyGuidedESIConfig()
            )
        else:
            raise RuntimeError(method)

        solution, runtime_s, diagnostics = _run_budget_method(
            instance=instance,
            initial=initial,
            algorithm_seed=args.algorithm_seed,
            budget_s=args.time_budget_s,
            intensifier=intensifier,
        )
        methods[method] = _record(
            instance=instance,
            solution=solution,
            runtime_s=runtime_s,
            budget_s=args.time_budget_s,
            diagnostics=diagnostics,
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "development": True,
                "experiment": {
                    "tasks": args.tasks,
                    "scenario_seed": args.scenario_seed,
                    "algorithm_seed": args.algorithm_seed,
                    "time_budget_s": args.time_budget_s,
                    "scenario_block": "89-92",
                },
                "row": {
                    "K": args.tasks,
                    "scenario_seed": args.scenario_seed,
                    "algorithm_seed": args.algorithm_seed,
                    "execution_order": order,
                    "methods": methods,
                },
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )

    print(
        " | ".join(
            [
                f"K={args.tasks}",
                f"S={args.scenario_seed}",
                f"A={args.algorithm_seed}",
            ]
            + [
                (
                    f"{method}:"
                    f"{methods[method]['stage1_status']}/"
                    f"{methods[method]['energy_j']}/"
                    f"{methods[method]['method_runtime_s']:.2f}s"
                )
                for method in METHODS
            ]
        )
    )


if __name__ == "__main__":
    main()
