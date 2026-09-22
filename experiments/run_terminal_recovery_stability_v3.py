from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from uav_mec.algorithms import (
    ContinuousESIConfig,
    ScreenedProxyObjectiveEvaluator,
    TerminalRecoveryESIConfig,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
    run_uav_mec_continuous_esi_alns,
    run_uav_mec_hybrid_alns,
    run_uav_mec_terminal_recovery_esi_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


METHODS = (
    "legacy_b_alns",
    "legacy_esi",
    "time_b_alns",
    "continuous_esi_v2",
    "terminal_recovery_esi_v3",
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

    default_solver = CVXResourceSolver(run_stage2=False)
    started = perf_counter()
    default_result = default_solver.solve(instance, solution, info)
    runtime_s = perf_counter() - started

    payload: dict[str, Any] = {
        "stage1_status": _stage1_status(default_result),
        "energy_j": (
            float(default_result.energy_stage1_j)
            if _strict(default_result)
            else None
        ),
        "default_solver": default_result.solver,
        "recovery_verification_attempted": False,
        "recovery_stage1_status": None,
        "recovery_energy_j": None,
        "recovery_solver": None,
        "certified_strict": _strict(default_result),
        "certified_energy_j": (
            float(default_result.energy_stage1_j)
            if _strict(default_result)
            else None
        ),
    }

    if not _strict(default_result):
        recovery_solver = CVXResourceSolver(
            run_stage2=False,
            solver_profile="recovery",
        )
        recovery_started = perf_counter()
        recovery_result = recovery_solver.solve(
            instance,
            solution,
            info,
        )
        runtime_s += perf_counter() - recovery_started
        recovery_strict = _strict(recovery_result)

        payload.update(
            {
                "recovery_verification_attempted": True,
                "recovery_stage1_status": _stage1_status(
                    recovery_result
                ),
                "recovery_energy_j": (
                    float(recovery_result.energy_stage1_j)
                    if recovery_strict
                    else None
                ),
                "recovery_solver": recovery_result.solver,
                "certified_strict": recovery_strict,
                "certified_energy_j": (
                    float(recovery_result.energy_stage1_j)
                    if recovery_strict
                    else None
                ),
            }
        )

    return payload, runtime_s


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
    search_runtime_s: float,
    budget_s: float,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    verification, verification_runtime_s = _verify(
        instance,
        solution,
    )
    return {
        **verification,
        "search_runtime_s": search_runtime_s,
        "budget_s": budget_s,
        "budget_overrun_s": max(
            0.0,
            search_runtime_s - budget_s,
        ),
        "verification_runtime_s": verification_runtime_s,
        "diagnostics": diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Terminal-recovery ESI v3 hold-out validation."
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument("--scenario-seed", type=int, required=True)
    parser.add_argument("--algorithm-seed", type=int, required=True)
    parser.add_argument("--time-budget-s", type=float, required=True)
    parser.add_argument(
        "--legacy-esi-exploration-s",
        type=float,
        required=True,
    )
    parser.add_argument(
        "--legacy-esi-elite-s",
        type=float,
        required=True,
    )
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
        if method == "legacy_b_alns":
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                    max_runtime_s=args.time_budget_s,
                ),
                evaluator=evaluator,
            )
            runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                search_runtime_s=runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "completed_iterations": _completed_iterations(result),
                    "stop_reason": result.stop_reason,
                    "cvx_refinements": evaluator.stats.cvx_refinements,
                },
            )

        elif method == "legacy_esi":
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_hybrid_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                ),
                evaluator=evaluator,
                elite_rounds=2,
                exploration_max_runtime_s=(
                    args.legacy_esi_exploration_s
                ),
                elite_max_runtime_s=args.legacy_esi_elite_s,
            )
            runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                search_runtime_s=runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "completed_iterations": _completed_iterations(
                        result.exploration
                    ),
                    "elite_cvx_calls": result.elite_cvx_calls,
                    "accepted_moves": list(
                        result.elite_stats.get("accepted_moves", [])
                    ),
                },
            )

        elif method == "time_b_alns":
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
                search_runtime_s=runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "completed_iterations": _completed_iterations(result),
                    "stop_reason": result.stop_reason,
                    "cvx_refinements": evaluator.stats.cvx_refinements,
                },
            )

        elif method == "continuous_esi_v2":
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_continuous_esi_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                ),
                continuous=ContinuousESIConfig(
                    total_runtime_s=args.time_budget_s,
                ),
                evaluator=evaluator,
            )
            runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                search_runtime_s=runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
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
                    "certification_runtime_s": (
                        result.certification_runtime_s
                    ),
                    "oracle_calls": result.oracle_calls,
                    "completed_iterations": _completed_iterations(
                        result.exploration
                    ),
                },
            )

        elif method == "terminal_recovery_esi_v3":
            evaluator = ScreenedProxyObjectiveEvaluator()
            started = perf_counter()
            result = run_uav_mec_terminal_recovery_esi_alns(
                instance,
                initial_solution=deepcopy(initial),
                config=UavMecALNSConfig(
                    iterations=100,
                    seed=args.algorithm_seed,
                ),
                terminal=TerminalRecoveryESIConfig(
                    total_runtime_s=args.time_budget_s,
                ),
                continuous_config=ContinuousESIConfig(
                    total_runtime_s=args.time_budget_s,
                ),
                evaluator=evaluator,
            )
            runtime_s = perf_counter() - started
            methods[method] = _record(
                instance=instance,
                solution=result.best_solution,
                search_runtime_s=runtime_s,
                budget_s=args.time_budget_s,
                diagnostics={
                    "selection": result.selection,
                    "high_accuracy_attempted": (
                        result.high_accuracy_attempted
                    ),
                    "high_accuracy_succeeded": (
                        result.high_accuracy_succeeded
                    ),
                    "structural_recovery_attempted": (
                        result.structural_recovery_attempted
                    ),
                    "structural_recovery_succeeded": (
                        result.structural_recovery_succeeded
                    ),
                    "fallback_available": result.fallback_available,
                    "fallback_used": result.fallback_used,
                    "recovery_runtime_s": result.recovery_runtime_s,
                    "recovery_oracle_calls": (
                        result.recovery_oracle_calls
                    ),
                    "continuous_strict_archive_found": (
                        result.continuous.strict_incumbent_found
                    ),
                    "continuous_elite_triggers": (
                        result.continuous.elite_triggers
                    ),
                    "continuous_elite_injections": (
                        result.continuous.elite_injections
                    ),
                    "completed_iterations": _completed_iterations(
                        result.continuous.exploration
                    ),
                    "recovery_stats": result.recovery_stats,
                    "internal_final_status": _stage1_status(
                        result.final_cvx
                    ),
                    "internal_final_energy_j": (
                        float(result.final_cvx.energy_stage1_j)
                        if _strict(result.final_cvx)
                        else None
                    ),
                },
            )
        else:
            raise RuntimeError(method)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "complete": True,
        "experiment": {
            "tasks": args.tasks,
            "mecs": args.mecs,
            "uavs": args.uavs,
            "scenario_seed": args.scenario_seed,
            "algorithm_seed": args.algorithm_seed,
            "time_budget_s": args.time_budget_s,
            "holdout": True,
            "scenario_block": "69-76",
            "protocol": "docs/terminal_recovery_stability_v3_protocol.md",
        },
        "row": {
            "K": args.tasks,
            "scenario_seed": args.scenario_seed,
            "algorithm_seed": args.algorithm_seed,
            "execution_order": execution_order,
            "methods": methods,
        },
    }
    output.write_text(
        json.dumps(
            payload,
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
                    f"cert={methods[method]['certified_strict']}/"
                    f"{methods[method]['search_runtime_s']:.2f}s"
                )
                for method in METHODS
            ]
        )
    )
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
