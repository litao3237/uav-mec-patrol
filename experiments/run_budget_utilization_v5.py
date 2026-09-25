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
    ScreenedProxyObjectiveEvaluator,
    TerminalFirstESIConfig,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
    run_uav_mec_budget_aware_terminal_first_alns,
    run_uav_mec_terminal_first_esi_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


METHODS = (
    "time_b_alns",
    "terminal_fixed10",
    "terminal_fixed3",
    "terminal_budget_aware_v5",
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
    return bool(result.feasible and _stage1_status(result) == "optimal")


def _verify(instance, solution) -> tuple[dict[str, Any], float]:
    info = build_event_info(instance, solution)
    solver = CVXResourceSolver(run_stage2=False)
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
        "solver": result.solver,
    }, runtime_s


def _completed_iterations(result) -> int:
    return sum(
        sum(values)
        for values in result.operator_pair_counts.values()
    )


def _method_order(seed: int) -> list[str]:
    base = list(METHODS)
    offset = seed % len(base)
    return base[offset:] + base[:offset]


def _record(
    *,
    instance,
    solution,
    method_runtime_s: float,
    budget_s: float,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    verification, verification_runtime_s = _verify(
        instance,
        solution,
    )
    return {
        **verification,
        "method_runtime_s": method_runtime_s,
        "budget_s": budget_s,
        "budget_utilization_pct": (
            100.0 * method_runtime_s / budget_s
        ),
        "budget_overrun_s": max(
            0.0,
            method_runtime_s - budget_s,
        ),
        "unused_budget_s": max(
            0.0,
            budget_s - method_runtime_s,
        ),
        "verification_runtime_s": verification_runtime_s,
        "diagnostics": diagnostics,
    }


def _terminal_diagnostics(result) -> dict[str, Any]:
    return {
        "selection_source": result.selection_source,
        "strict_incumbent_found": result.strict_incumbent_found,
        "strict_incumbent_updates": (
            result.strict_incumbent_updates
        ),
        "elite_triggers": result.elite_triggers,
        "elite_strict_improvements": (
            result.elite_strict_improvements
        ),
        "elite_injections": result.elite_injections,
        "elite_runtime_s": result.elite_runtime_s,
        "in_search_certification_runtime_s": (
            result.in_search_certification_runtime_s
        ),
        "terminal_certification_runtime_s": (
            result.terminal_certification_runtime_s
        ),
        "oracle_calls": result.oracle_calls,
        "oracle_cache_hits": result.oracle_cache_hits,
        "internal_search_runtime_s": result.search_runtime_s,
        "completed_iterations": _completed_iterations(
            result.exploration
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Budget-utilization v5 hold-out comparison."
    )
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
    execution_order = _method_order(args.algorithm_seed)

    for method in execution_order:
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
            method_runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                method_runtime_s=method_runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "internal_search_runtime_s": method_runtime_s,
                    "completed_iterations": _completed_iterations(result),
                    "stop_reason": result.stop_reason,
                    "cvx_refinements": evaluator.stats.cvx_refinements,
                },
            )

        elif method in {"terminal_fixed10", "terminal_fixed3"}:
            reserve_fraction = (
                0.10 if method == "terminal_fixed10" else 0.03
            )
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_terminal_first_esi_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                ),
                terminal_first=TerminalFirstESIConfig(
                    total_runtime_s=args.time_budget_s,
                    final_cert_reserve_fraction=reserve_fraction,
                ),
                evaluator=evaluator,
            )
            method_runtime_s = perf_counter() - started
            diagnostics = _terminal_diagnostics(result)
            diagnostics.update(
                {
                    "reserve_policy": "fixed",
                    "reserve_fraction": reserve_fraction,
                    "initial_reserve_s": (
                        args.time_budget_s * reserve_fraction
                    ),
                    "final_reserve_s": (
                        args.time_budget_s * reserve_fraction
                    ),
                    "reserve_expanded": False,
                }
            )
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                method_runtime_s=method_runtime_s,
                budget_s=args.time_budget_s,
                diagnostics=diagnostics,
            )

        elif method == "terminal_budget_aware_v5":
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_budget_aware_terminal_first_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                ),
                budget_aware=BudgetAwareTerminalFirstConfig(
                    total_runtime_s=args.time_budget_s,
                    initial_reserve_fraction=0.03,
                    max_reserve_fraction=0.08,
                    observed_runtime_multiplier=2.0,
                ),
                evaluator=evaluator,
            )
            method_runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                method_runtime_s=method_runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "selection_source": result.selection_source,
                    "strict_incumbent_found": (
                        result.strict_incumbent_found
                    ),
                    "strict_incumbent_updates": (
                        result.strict_incumbent_updates
                    ),
                    "elite_triggers": result.elite_triggers,
                    "elite_strict_improvements": (
                        result.elite_strict_improvements
                    ),
                    "elite_injections": result.elite_injections,
                    "elite_runtime_s": result.elite_runtime_s,
                    "in_search_certification_runtime_s": (
                        result.in_search_certification_runtime_s
                    ),
                    "terminal_certification_runtime_s": (
                        result.terminal_certification_runtime_s
                    ),
                    "certification_samples_s": (
                        result.certification_samples_s
                    ),
                    "initial_reserve_s": result.initial_reserve_s,
                    "final_reserve_s": result.final_reserve_s,
                    "reserve_expanded": (
                        result.final_reserve_s
                        > result.initial_reserve_s + 1e-12
                    ),
                    "reserve_policy": "adaptive",
                    "search_horizon_s": result.search_horizon_s,
                    "internal_search_runtime_s": (
                        result.search_runtime_s
                    ),
                    "oracle_calls": result.oracle_calls,
                    "oracle_cache_hits": result.oracle_cache_hits,
                    "completed_iterations": _completed_iterations(
                        result.exploration
                    ),
                },
            )
        else:
            raise RuntimeError(method)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "experiment": {
                    "tasks": args.tasks,
                    "mecs": args.mecs,
                    "uavs": args.uavs,
                    "scenario_seed": args.scenario_seed,
                    "algorithm_seed": args.algorithm_seed,
                    "time_budget_s": args.time_budget_s,
                    "holdout": True,
                    "scenario_block": "85-92",
                    "protocol": "docs/budget_utilization_v5_protocol.md",
                },
                "row": {
                    "K": args.tasks,
                    "scenario_seed": args.scenario_seed,
                    "algorithm_seed": args.algorithm_seed,
                    "execution_order": execution_order,
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
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
