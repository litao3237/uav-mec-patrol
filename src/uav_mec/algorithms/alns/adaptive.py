from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any

from uav_mec.algorithms.initial import (
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
)
from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import ResourceSolveResult

from .evaluator import ScreenedProxyObjectiveEvaluator
from .hybrid import Stage1CVXObjectiveOracle
from .problem_operators import contact_mode_intensification
from .runner import UavMecALNSConfig, run_uav_mec_alns
from .state import ObjectiveEvaluator, UavMecState


@dataclass(frozen=True)
class AdaptiveESIConfig:
    """Experimental stability-oriented ESI orchestration."""

    total_runtime_s: float
    stagnation_runtime_s: float
    min_exploration_runtime_s: float
    elite_burst_runtime_s: float
    max_elite_triggers: int = 2
    elite_rounds_per_trigger: int = 1
    phase_seed_stride: int = 1009
    min_remaining_runtime_s: float = 0.10


@dataclass
class AdaptiveESIResult:
    best_solution: DiscreteSolution
    final_cvx: ResourceSolveResult
    strict_incumbent_found: bool
    strict_incumbent_updates: int
    elite_triggers: int
    elite_improvements: int
    total_runtime_s: float
    oracle_calls: int
    oracle_cache_hits: int
    phase_records: list[dict[str, Any]]

    @property
    def final_energy_j(self) -> float:
        return float(self.final_cvx.energy_stage1_j)


def _stage1_status(result: ResourceSolveResult) -> str:
    return str(
        result.diagnostics.get(
            "stage1_status",
            result.status,
        )
    )


def _strict(result: ResourceSolveResult) -> bool:
    return bool(
        result.feasible
        and _stage1_status(result) == "optimal"
    )


def _validate_config(config: AdaptiveESIConfig) -> None:
    if config.total_runtime_s <= 0.0:
        raise ValueError("total_runtime_s must be positive")
    if config.stagnation_runtime_s <= 0.0:
        raise ValueError(
            "stagnation_runtime_s must be positive"
        )
    if config.min_exploration_runtime_s < 0.0:
        raise ValueError(
            "min_exploration_runtime_s must be non-negative"
        )
    if config.elite_burst_runtime_s <= 0.0:
        raise ValueError(
            "elite_burst_runtime_s must be positive"
        )
    if config.max_elite_triggers < 0:
        raise ValueError(
            "max_elite_triggers must be non-negative"
        )
    if config.elite_rounds_per_trigger <= 0:
        raise ValueError(
            "elite_rounds_per_trigger must be positive"
        )
    if config.phase_seed_stride <= 0:
        raise ValueError(
            "phase_seed_stride must be positive"
        )
    if config.min_remaining_runtime_s < 0.0:
        raise ValueError(
            "min_remaining_runtime_s must be non-negative"
        )


def run_uav_mec_adaptive_esi_alns(
    instance: Instance,
    *,
    adaptive: AdaptiveESIConfig,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    elite_oracle: Stage1CVXObjectiveOracle | None = None,
) -> AdaptiveESIResult:
    """Run stability-oriented ALNS with stagnation-triggered ESI.

    The experimental policy is deliberately conservative:

    1. use wall-clock-scaled RRT during every ALNS phase;
    2. stop a phase early only after a minimum exploration period and a
       measured best-objective stagnation window;
    3. validate each phase best with the strict Stage-1 oracle and retain the
       best strict incumbent seen so far;
    4. trigger a short exact ESI burst only on stagnation;
    5. resume generic exploration with the remaining wall-clock budget;
    6. return the best strict-certified incumbent whenever one exists.

    This is an experimental branch entry point. The frozen paper algorithm is
    intentionally left unchanged on develop.
    """

    _validate_config(adaptive)
    base_cfg = config or UavMecALNSConfig()
    objective_evaluator = (
        evaluator or ScreenedProxyObjectiveEvaluator()
    )
    oracle = elite_oracle or Stage1CVXObjectiveOracle()

    if initial_solution is None:
        route_seed = build_greedy_initial_solution(instance)
        current_solution = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )
    else:
        current_solution = deepcopy(initial_solution)
    validate_solution(instance, current_solution)

    started = perf_counter()
    strict_solution: DiscreteSolution | None = None
    strict_result: ResourceSolveResult | None = None
    strict_updates = 0
    elite_triggers = 0
    elite_improvements = 0
    phase_records: list[dict[str, Any]] = []
    phase = 0

    while True:
        elapsed = perf_counter() - started
        remaining = adaptive.total_runtime_s - elapsed
        if remaining <= adaptive.min_remaining_runtime_s:
            break

        allow_stagnation = (
            elite_triggers < adaptive.max_elite_triggers
            and remaining
            > adaptive.elite_burst_runtime_s
            + adaptive.min_remaining_runtime_s
        )
        phase_min_runtime = (
            adaptive.min_exploration_runtime_s
            if phase == 0
            else min(
                adaptive.stagnation_runtime_s,
                max(0.0, remaining * 0.25),
            )
        )

        phase_cfg = replace(
            base_cfg,
            seed=(
                base_cfg.seed
                + phase * adaptive.phase_seed_stride
            ),
            enable_problem_operators=False,
            max_runtime_s=remaining,
            time_scaled_rrt=True,
            stagnation_runtime_s=(
                adaptive.stagnation_runtime_s
                if allow_stagnation
                else None
            ),
            min_runtime_s=min(
                phase_min_runtime,
                remaining,
            ),
        )

        phase_started = perf_counter()
        exploration = run_uav_mec_alns(
            instance,
            initial_solution=current_solution,
            config=phase_cfg,
            evaluator=objective_evaluator,
        )
        phase_runtime_s = perf_counter() - phase_started

        phase_cvx_started = perf_counter()
        phase_cvx = oracle.solve(
            instance,
            exploration.best_solution,
        )
        phase_cvx_runtime_s = (
            perf_counter() - phase_cvx_started
        )

        strict_updated = False
        if _strict(phase_cvx):
            if (
                strict_result is None
                or float(phase_cvx.energy_stage1_j)
                < float(strict_result.energy_stage1_j) - 1e-9
            ):
                strict_solution = deepcopy(
                    exploration.best_solution
                )
                strict_result = phase_cvx
                strict_updates += 1
                strict_updated = True

        current_solution = deepcopy(
            exploration.best_solution
        )
        record: dict[str, Any] = {
            "phase": phase,
            "seed": phase_cfg.seed,
            "stop_reason": exploration.stop_reason,
            "phase_runtime_s": phase_runtime_s,
            "phase_cvx_runtime_s": phase_cvx_runtime_s,
            "screened_best_objective": (
                exploration.best_objective
            ),
            "stage1_status": _stage1_status(phase_cvx),
            "strict_updated": strict_updated,
            "elite_triggered": False,
            "elite_improved": False,
            "elite_stats": None,
        }

        elapsed = perf_counter() - started
        remaining = adaptive.total_runtime_s - elapsed
        should_trigger_elite = (
            exploration.stop_reason == "stagnation"
            and allow_stagnation
            and remaining
            > adaptive.min_remaining_runtime_s
        )

        if should_trigger_elite:
            if _strict(phase_cvx):
                elite_base_solution = deepcopy(
                    exploration.best_solution
                )
                elite_base_result = phase_cvx
            elif strict_solution is not None:
                elite_base_solution = deepcopy(strict_solution)
                assert strict_result is not None
                elite_base_result = strict_result
            else:
                elite_base_solution = None
                elite_base_result = None

            if elite_base_solution is not None:
                elite_budget_s = min(
                    adaptive.elite_burst_runtime_s,
                    max(0.0, remaining),
                )
                if (
                    elite_budget_s
                    > adaptive.min_remaining_runtime_s
                ):
                    elite_triggers += 1
                    record["elite_triggered"] = True
                    state = UavMecState(
                        instance,
                        elite_base_solution,
                        objective_evaluator,
                    )
                    elite_started = perf_counter()
                    intensified, elite_stats = (
                        contact_mode_intensification(
                            state,
                            config=base_cfg.problem,
                            objective=oracle,
                            max_rounds=(
                                adaptive.elite_rounds_per_trigger
                            ),
                            max_runtime_s=elite_budget_s,
                        )
                    )
                    elite_runtime_s = (
                        perf_counter() - elite_started
                    )
                    elite_cvx_started = perf_counter()
                    elite_cvx = oracle.solve(
                        instance,
                        intensified.solution,
                    )
                    elite_cvx_runtime_s = (
                        perf_counter() - elite_cvx_started
                    )

                    improved = bool(
                        _strict(elite_cvx)
                        and elite_base_result is not None
                        and float(elite_cvx.energy_stage1_j)
                        < float(elite_base_result.energy_stage1_j)
                        - 1e-9
                    )
                    if _strict(elite_cvx):
                        if (
                            strict_result is None
                            or float(elite_cvx.energy_stage1_j)
                            < float(strict_result.energy_stage1_j)
                            - 1e-9
                        ):
                            strict_solution = deepcopy(
                                intensified.solution
                            )
                            strict_result = elite_cvx
                            strict_updates += 1

                    if improved:
                        elite_improvements += 1
                        current_solution = deepcopy(
                            intensified.solution
                        )
                    elif strict_solution is not None:
                        # Resume from a known strict state rather than a
                        # numerically ambiguous screened incumbent.
                        current_solution = deepcopy(
                            strict_solution
                        )

                    record.update(
                        {
                            "elite_improved": improved,
                            "elite_runtime_s": elite_runtime_s,
                            "elite_cvx_runtime_s": (
                                elite_cvx_runtime_s
                            ),
                            "elite_stage1_status": (
                                _stage1_status(elite_cvx)
                            ),
                            "elite_stats": elite_stats,
                        }
                    )

        phase_records.append(record)
        phase += 1

        if exploration.stop_reason != "stagnation":
            break

    # A strict incumbent is preferred. If none was encountered at a phase
    # boundary, perform one final strict check on the final screened solution.
    if strict_solution is None or strict_result is None:
        fallback = oracle.solve(
            instance,
            current_solution,
        )
        if _strict(fallback):
            strict_solution = deepcopy(current_solution)
            strict_result = fallback
            strict_updates += 1

    if strict_solution is not None and strict_result is not None:
        best_solution = strict_solution
        final_cvx = strict_result
        strict_found = True
    else:
        best_solution = deepcopy(current_solution)
        final_cvx = oracle.solve(
            instance,
            best_solution,
        )
        strict_found = _strict(final_cvx)

    validate_solution(instance, best_solution)
    return AdaptiveESIResult(
        best_solution=best_solution,
        final_cvx=final_cvx,
        strict_incumbent_found=strict_found,
        strict_incumbent_updates=strict_updates,
        elite_triggers=elite_triggers,
        elite_improvements=elite_improvements,
        total_runtime_s=perf_counter() - started,
        oracle_calls=oracle.calls,
        oracle_cache_hits=oracle.cache_hits,
        phase_records=phase_records,
    )
