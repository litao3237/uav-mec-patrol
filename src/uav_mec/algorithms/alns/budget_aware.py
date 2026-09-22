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
from .state import ObjectiveEvaluator


@dataclass(frozen=True)
class BudgetAwareTerminalFirstConfig:
    """Budget-utilization policy for terminal-first continuous ESI.

    The policy starts with a compact final-certification reserve, then enlarges
    it only when actual in-search Stage-1 certification samples indicate that
    the current instance/solver path is slower than expected.
    """

    total_runtime_s: float
    initial_reserve_fraction: float = 0.03
    max_reserve_fraction: float = 0.08
    observed_runtime_multiplier: float = 2.0
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
    elite_triggers: int
    elite_strict_improvements: int
    elite_injections: int
    elite_runtime_s: float
    in_search_certification_runtime_s: float
    terminal_certification_runtime_s: float
    certification_samples_s: list[float]
    initial_reserve_s: float
    final_reserve_s: float
    search_horizon_s: float
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
    if not 0.0 < policy.initial_reserve_fraction < 1.0:
        raise ValueError(
            "initial_reserve_fraction must be in (0,1)"
        )
    if not (
        policy.initial_reserve_fraction
        <= policy.max_reserve_fraction
        < 1.0
    ):
        raise ValueError(
            "max_reserve_fraction must be >= initial reserve and < 1"
        )
    if policy.observed_runtime_multiplier < 1.0:
        raise ValueError(
            "observed_runtime_multiplier must be >= 1"
        )

    for name, value in (
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

    if (
        policy.max_reserve_fraction
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
    # The continuous controller still needs a policy object for ESI ratios.
    # Its fixed reserve field is not used for the adaptive stopping decision.
    return ContinuousESIConfig(
        total_runtime_s=policy.total_runtime_s,
        final_cert_reserve_fraction=(
            policy.initial_reserve_fraction
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


class _BudgetAwareESIController(_ContinuousESIController):
    def __init__(
        self,
        *,
        budget_policy: BudgetAwareTerminalFirstConfig,
        hard_deadline_at: float,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.budget_policy = budget_policy
        self.hard_deadline_at = hard_deadline_at
        self.initial_reserve_s = (
            budget_policy.total_runtime_s
            * budget_policy.initial_reserve_fraction
        )
        self.max_reserve_s = (
            budget_policy.total_runtime_s
            * budget_policy.max_reserve_fraction
        )
        self.final_reserve_s = self.initial_reserve_s
        self.reserve_history_s: list[float] = [
            self.initial_reserve_s
        ]

    def current_reserve_s(self) -> float:
        observed_need = 0.0
        if self.certification_samples_s:
            observed_need = (
                self.budget_policy.observed_runtime_multiplier
                * max(self.certification_samples_s)
            )
        reserve = min(
            self.max_reserve_s,
            max(self.initial_reserve_s, observed_need),
        )
        self.final_reserve_s = reserve
        return reserve

    def __call__(self, rng, best, current) -> bool:
        reserve_s = self.current_reserve_s()
        self.search_deadline_at = (
            self.hard_deadline_at - reserve_s
        )
        self.reserve_history_s.append(reserve_s)
        return super().__call__(rng, best, current)


def run_uav_mec_budget_aware_terminal_first_alns(
    instance: Instance,
    *,
    budget_aware: BudgetAwareTerminalFirstConfig,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    elite_oracle: Stage1CVXObjectiveOracle | None = None,
) -> BudgetAwareTerminalFirstResult:
    """Run terminal-first ESI with adaptive final-certification reserve."""

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
    hard_deadline_at = (
        started + budget_aware.total_runtime_s
    )
    initial_reserve_s = (
        budget_aware.total_runtime_s
        * budget_aware.initial_reserve_fraction
    )
    search_horizon_s = (
        budget_aware.total_runtime_s - initial_reserve_s
    )

    initial_objective = float(
        objective_evaluator(instance, initial_solution)
    )
    accept = _TimeScaledRecordToRecordTravel(
        initial_objective,
        base_cfg.rrt_start_gap,
        base_cfg.rrt_end_gap,
        search_horizon_s,
        started_at=started,
    )

    controller = _BudgetAwareESIController(
        instance=instance,
        evaluator=objective_evaluator,
        problem_config=base_cfg.problem,
        oracle=oracle,
        policy=continuous,
        started_at=started,
        search_deadline_at=(
            hard_deadline_at - initial_reserve_s
        ),
        budget_policy=budget_aware,
        hard_deadline_at=hard_deadline_at,
    )

    exploration_cfg = replace(
        base_cfg,
        enable_problem_operators=False,
        max_runtime_s=search_horizon_s,
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
        certification_samples_s=list(
            controller.certification_samples_s
        ),
        initial_reserve_s=initial_reserve_s,
        final_reserve_s=controller.current_reserve_s(),
        search_horizon_s=search_horizon_s,
        search_runtime_s=search_runtime_s,
        total_runtime_s=perf_counter() - started,
        oracle_calls=oracle.calls,
        oracle_cache_hits=oracle.cache_hits,
        events=controller.events
        + [
            {
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
                "initial_reserve_s": initial_reserve_s,
                "final_reserve_s": controller.current_reserve_s(),
            }
        ],
    )
