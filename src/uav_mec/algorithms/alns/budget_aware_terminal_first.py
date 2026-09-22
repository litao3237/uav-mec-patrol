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

from .continuous import (
    ContinuousESIConfig,
    _ContinuousESIController,
    _strict,
)
from .evaluator import ScreenedProxyObjectiveEvaluator
from .hybrid import Stage1CVXObjectiveOracle
from .runner import (
    UavMecALNSConfig,
    UavMecALNSResult,
    _TimeScaledRecordToRecordTravel,
    run_uav_mec_alns,
)
from .state import ObjectiveEvaluator, UavMecState


@dataclass(frozen=True)
class BudgetAwareTerminalFirstConfig:
    """Budget-aware terminal-first policy for continuous ESI v5."""

    total_runtime_s: float
    final_cert_reserve_fraction: float = 0.03
    checkpoint_fraction: float = 0.60
    stagnation_fraction: float = 0.20
    min_exploration_fraction: float = 0.35
    elite_pool_fraction: float = 0.12
    elite_burst_fraction: float = 0.06
    max_elite_triggers: int = 2
    elite_rounds_per_trigger: int = 1
    proxy_injection_tolerance_rel: float = 1e-9
    strict_energy_tolerance_rel: float = 1e-9


@dataclass
class BudgetAwareTerminalFirstResult:
    exploration: UavMecALNSResult
    terminal_solution: DiscreteSolution
    terminal_cvx: ResourceSolveResult
    best_solution: DiscreteSolution
    final_cvx: ResourceSolveResult
    selection_source: str
    strict_incumbent_found: bool
    strict_incumbent_updates: int
    checkpoint_attempted: bool
    checkpoint_succeeded: bool
    checkpoint_runtime_s: float
    elite_triggers: int
    elite_strict_improvements: int
    elite_injections: int
    elite_runtime_s: float
    in_search_certification_runtime_s: float
    terminal_certification_runtime_s: float
    search_runtime_s: float
    total_runtime_s: float
    oracle_calls: int
    oracle_cache_hits: int
    events: list[dict[str, Any]]

    @property
    def final_energy_j(self) -> float:
        return float(self.final_cvx.energy_stage1_j)


def _validate(policy: BudgetAwareTerminalFirstConfig) -> None:
    if policy.total_runtime_s <= 0.0:
        raise ValueError("total_runtime_s must be positive")

    for name, value in (
        (
            "final_cert_reserve_fraction",
            policy.final_cert_reserve_fraction,
        ),
        ("checkpoint_fraction", policy.checkpoint_fraction),
        ("stagnation_fraction", policy.stagnation_fraction),
        (
            "min_exploration_fraction",
            policy.min_exploration_fraction,
        ),
        ("elite_pool_fraction", policy.elite_pool_fraction),
        ("elite_burst_fraction", policy.elite_burst_fraction),
    ):
        if not 0.0 < value < 1.0:
            raise ValueError(f"{name} must be in (0,1)")

    if policy.checkpoint_fraction >= (
        1.0 - policy.final_cert_reserve_fraction
    ):
        raise ValueError(
            "checkpoint_fraction must occur before the search deadline"
        )
    if (
        policy.final_cert_reserve_fraction
        + policy.elite_pool_fraction
        >= 0.80
    ):
        raise ValueError(
            "Too much runtime reserved away from exploration"
        )
    if policy.max_elite_triggers < 0:
        raise ValueError("max_elite_triggers must be non-negative")
    if policy.elite_rounds_per_trigger <= 0:
        raise ValueError(
            "elite_rounds_per_trigger must be positive"
        )


def _continuous_policy(
    policy: BudgetAwareTerminalFirstConfig,
) -> ContinuousESIConfig:
    return ContinuousESIConfig(
        total_runtime_s=policy.total_runtime_s,
        final_cert_reserve_fraction=(
            policy.final_cert_reserve_fraction
        ),
        stagnation_fraction=policy.stagnation_fraction,
        min_exploration_fraction=(
            policy.min_exploration_fraction
        ),
        elite_pool_fraction=policy.elite_pool_fraction,
        elite_burst_fraction=policy.elite_burst_fraction,
        max_elite_triggers=policy.max_elite_triggers,
        elite_rounds_per_trigger=policy.elite_rounds_per_trigger,
        proxy_injection_tolerance_rel=(
            policy.proxy_injection_tolerance_rel
        ),
        strict_energy_tolerance_rel=(
            policy.strict_energy_tolerance_rel
        ),
    )


class _BudgetAwareController(_ContinuousESIController):
    """Continuous ESI controller with one opportunistic strict checkpoint."""

    def __init__(
        self,
        *,
        checkpoint_at_s: float,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.checkpoint_at_s = checkpoint_at_s
        self.checkpoint_attempted = False
        self.checkpoint_succeeded = False
        self.checkpoint_runtime_s = 0.0

    def __call__(
        self,
        rng,
        best: UavMecState,
        current: UavMecState,
    ) -> bool:
        should_stop = super().__call__(rng, best, current)
        if should_stop:
            return True

        if self.checkpoint_attempted or self.strict_result is not None:
            return False

        now = perf_counter()
        elapsed_s = now - self.started_at
        if elapsed_s < self.checkpoint_at_s:
            return False
        if now >= self.search_deadline_at:
            return False

        self.checkpoint_attempted = True
        screened_objective = float(best.objective())
        result, runtime_s, updated = self._certify(
            best.solution,
            screened_objective=screened_objective,
        )
        self.checkpoint_runtime_s = runtime_s
        self.checkpoint_succeeded = _strict(result)
        self.events.append(
            {
                "event": "strict_checkpoint",
                "elapsed_s": elapsed_s,
                "runtime_s": runtime_s,
                "stage1_status": str(
                    result.diagnostics.get(
                        "stage1_status",
                        result.status,
                    )
                ),
                "archive_updated": updated,
            }
        )
        return False


def run_uav_mec_budget_aware_terminal_first_esi_alns(
    instance: Instance,
    *,
    budget_aware: BudgetAwareTerminalFirstConfig,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    elite_oracle: Stage1CVXObjectiveOracle | None = None,
) -> BudgetAwareTerminalFirstResult:
    """Run continuous ESI with a smaller reserve and one fallback checkpoint."""

    _validate(budget_aware)
    base_cfg = config or UavMecALNSConfig()
    objective_evaluator = (
        evaluator or ScreenedProxyObjectiveEvaluator()
    )
    oracle = elite_oracle or Stage1CVXObjectiveOracle()
    continuous = _continuous_policy(budget_aware)

    if initial_solution is None:
        route_seed = build_greedy_initial_solution(instance)
        initial_solution = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )
    else:
        initial_solution = deepcopy(initial_solution)
    validate_solution(instance, initial_solution)

    started = perf_counter()
    search_budget_s = (
        budget_aware.total_runtime_s
        * (1.0 - budget_aware.final_cert_reserve_fraction)
    )
    search_deadline = started + search_budget_s
    checkpoint_at_s = (
        budget_aware.total_runtime_s
        * budget_aware.checkpoint_fraction
    )

    initial_objective = float(
        objective_evaluator(instance, initial_solution)
    )
    accept = _TimeScaledRecordToRecordTravel(
        initial_objective,
        base_cfg.rrt_start_gap,
        base_cfg.rrt_end_gap,
        search_budget_s,
        started_at=started,
    )
    controller = _BudgetAwareController(
        instance=instance,
        evaluator=objective_evaluator,
        problem_config=base_cfg.problem,
        oracle=oracle,
        policy=continuous,
        started_at=started,
        search_deadline_at=search_deadline,
        checkpoint_at_s=checkpoint_at_s,
    )

    exploration_cfg = replace(
        base_cfg,
        enable_problem_operators=False,
        max_runtime_s=search_budget_s,
        time_scaled_rrt=False,
        stagnation_runtime_s=None,
    )
    exploration = run_uav_mec_alns(
        instance,
        initial_solution=initial_solution,
        config=exploration_cfg,
        evaluator=objective_evaluator,
        acceptance_criterion=accept,
        stopping_criterion=controller,
    )
    search_runtime_s = perf_counter() - started

    terminal_solution = deepcopy(exploration.best_solution)
    cert_started = perf_counter()
    terminal_cvx = oracle.solve(
        instance,
        terminal_solution,
    )
    terminal_certification_runtime_s = (
        perf_counter() - cert_started
    )

    if _strict(terminal_cvx):
        best_solution = deepcopy(terminal_solution)
        final_cvx = terminal_cvx
        selection_source = "terminal_strict"
    elif (
        controller.strict_solution is not None
        and controller.strict_result is not None
    ):
        best_solution = deepcopy(controller.strict_solution)
        final_cvx = controller.strict_result
        selection_source = "strict_incumbent_fallback"
    else:
        best_solution = deepcopy(terminal_solution)
        final_cvx = terminal_cvx
        selection_source = "terminal_nonstrict_no_fallback"

    validate_solution(instance, best_solution)
    return BudgetAwareTerminalFirstResult(
        exploration=exploration,
        terminal_solution=terminal_solution,
        terminal_cvx=terminal_cvx,
        best_solution=best_solution,
        final_cvx=final_cvx,
        selection_source=selection_source,
        strict_incumbent_found=(
            controller.strict_solution is not None
            and controller.strict_result is not None
        ),
        strict_incumbent_updates=(
            controller.strict_incumbent_updates
        ),
        checkpoint_attempted=controller.checkpoint_attempted,
        checkpoint_succeeded=controller.checkpoint_succeeded,
        checkpoint_runtime_s=controller.checkpoint_runtime_s,
        elite_triggers=controller.elite_triggers,
        elite_strict_improvements=(
            controller.elite_strict_improvements
        ),
        elite_injections=controller.elite_injections,
        elite_runtime_s=controller.elite_runtime_s,
        in_search_certification_runtime_s=(
            controller.certification_runtime_s
        ),
        terminal_certification_runtime_s=(
            terminal_certification_runtime_s
        ),
        search_runtime_s=search_runtime_s,
        total_runtime_s=perf_counter() - started,
        oracle_calls=oracle.calls,
        oracle_cache_hits=oracle.cache_hits,
        events=controller.events
        + [
            {
                "event": "terminal_selection",
                "terminal_screened_objective": float(
                    exploration.best_objective
                ),
                "terminal_stage1_status": str(
                    terminal_cvx.diagnostics.get(
                        "stage1_status",
                        terminal_cvx.status,
                    )
                ),
                "selection_source": selection_source,
            }
        ],
    )
