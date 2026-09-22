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
from .runner import (
    UavMecALNSConfig,
    UavMecALNSResult,
    _TimeScaledRecordToRecordTravel,
    run_uav_mec_alns,
)
from .state import ObjectiveEvaluator, UavMecState


@dataclass(frozen=True)
class ContinuousESIConfig:
    """Stability-oriented continuous ESI policy.

    ESI is injected into one uninterrupted ALNS engine. The roulette-wheel
    weights, RNG trajectory, and time-scaled RRT object are therefore never
    reset by an elite event.
    """

    total_runtime_s: float
    final_cert_reserve_fraction: float = 0.10
    stagnation_fraction: float = 0.20
    min_exploration_fraction: float = 0.35
    elite_pool_fraction: float = 0.12
    elite_burst_fraction: float = 0.06
    max_elite_triggers: int = 2
    elite_rounds_per_trigger: int = 1
    final_cert_min_screened_gain_rel: float = 0.002
    proxy_injection_tolerance_rel: float = 1e-9
    strict_energy_tolerance_rel: float = 1e-9


@dataclass
class ContinuousESIResult:
    exploration: UavMecALNSResult
    best_solution: DiscreteSolution
    final_cvx: ResourceSolveResult
    strict_incumbent_found: bool
    strict_incumbent_updates: int
    elite_triggers: int
    elite_strict_improvements: int
    elite_injections: int
    elite_runtime_s: float
    certification_runtime_s: float
    final_certification_performed: bool
    search_runtime_s: float
    total_runtime_s: float
    oracle_calls: int
    oracle_cache_hits: int
    events: list[dict[str, Any]]

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


def _validate_policy(policy: ContinuousESIConfig) -> None:
    if policy.total_runtime_s <= 0.0:
        raise ValueError("total_runtime_s must be positive")

    for name, value in (
        (
            "final_cert_reserve_fraction",
            policy.final_cert_reserve_fraction,
        ),
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
        policy.final_cert_reserve_fraction
        + policy.elite_pool_fraction
        >= 0.80
    ):
        raise ValueError(
            "Too much runtime reserved away from generic exploration"
        )
    if policy.max_elite_triggers < 0:
        raise ValueError("max_elite_triggers must be non-negative")
    if policy.elite_rounds_per_trigger <= 0:
        raise ValueError(
            "elite_rounds_per_trigger must be positive"
        )
    if policy.final_cert_min_screened_gain_rel < 0.0:
        raise ValueError(
            "final_cert_min_screened_gain_rel must be non-negative"
        )
    if policy.proxy_injection_tolerance_rel < 0.0:
        raise ValueError(
            "proxy_injection_tolerance_rel must be non-negative"
        )
    if policy.strict_energy_tolerance_rel < 0.0:
        raise ValueError(
            "strict_energy_tolerance_rel must be non-negative"
        )


class _ContinuousESIController:
    """Stopping criterion that injects ESI without restarting ALNS."""

    def __init__(
        self,
        *,
        instance: Instance,
        evaluator: ObjectiveEvaluator,
        problem_config,
        oracle: Stage1CVXObjectiveOracle,
        policy: ContinuousESIConfig,
        started_at: float,
        search_deadline_at: float,
        elite_intensifier=contact_mode_intensification,
    ) -> None:
        self.instance = instance
        self.evaluator = evaluator
        self.problem_config = problem_config
        self.oracle = oracle
        self.policy = policy
        self.started_at = started_at
        self.search_deadline_at = search_deadline_at
        self.elite_intensifier = elite_intensifier

        self.stagnation_s = (
            policy.total_runtime_s * policy.stagnation_fraction
        )
        self.min_exploration_s = (
            policy.total_runtime_s
            * policy.min_exploration_fraction
        )
        self.elite_pool_s = (
            policy.total_runtime_s * policy.elite_pool_fraction
        )
        self.elite_burst_s = (
            policy.total_runtime_s * policy.elite_burst_fraction
        )

        self._last_best_objective: float | None = None
        self._last_improvement_at = started_at
        self._last_elite_at: float | None = None

        self.strict_solution: DiscreteSolution | None = None
        self.strict_result: ResourceSolveResult | None = None
        self.last_certified_screened_objective: float | None = None

        self.strict_incumbent_updates = 0
        self.elite_triggers = 0
        self.elite_strict_improvements = 0
        self.elite_injections = 0
        self.elite_runtime_s = 0.0
        self.certification_runtime_s = 0.0
        self.certification_samples_s: list[float] = []
        self.events: list[dict[str, Any]] = []

        self.stop_reason: str | None = None
        self.elapsed_s = 0.0
        self.last_improvement_elapsed_s = 0.0

    def _update_strict_incumbent(
        self,
        solution: DiscreteSolution,
        result: ResourceSolveResult,
        *,
        screened_objective: float,
    ) -> bool:
        if not _strict(result):
            return False

        energy = float(result.energy_stage1_j)
        tolerance = (
            self.policy.strict_energy_tolerance_rel
            * max(1.0, abs(energy))
        )
        if (
            self.strict_result is None
            or energy
            < float(self.strict_result.energy_stage1_j) - tolerance
        ):
            self.strict_solution = deepcopy(solution)
            self.strict_result = result
            self.strict_incumbent_updates += 1
            self.last_certified_screened_objective = (
                screened_objective
            )
            return True

        if self.last_certified_screened_objective is None:
            self.last_certified_screened_objective = (
                screened_objective
            )
        else:
            self.last_certified_screened_objective = min(
                self.last_certified_screened_objective,
                screened_objective,
            )
        return False

    def _certify(
        self,
        solution: DiscreteSolution,
        *,
        screened_objective: float,
    ) -> tuple[ResourceSolveResult, float, bool]:
        started = perf_counter()
        result = self.oracle.solve(
            self.instance,
            solution,
        )
        runtime_s = perf_counter() - started
        self.certification_runtime_s += runtime_s
        self.certification_samples_s.append(runtime_s)
        updated = self._update_strict_incumbent(
            solution,
            result,
            screened_objective=screened_objective,
        )
        return result, runtime_s, updated

    def _inject_solution(
        self,
        best: UavMecState,
        current: UavMecState,
        solution: DiscreteSolution,
    ) -> None:
        best.solution = deepcopy(solution)
        best.removed_tasks = []
        best.invalidate()

        if current is not best:
            current.solution = deepcopy(solution)
            current.removed_tasks = []
            current.invalidate()

    def _attempt_elite(
        self,
        best: UavMecState,
        current: UavMecState,
        now: float,
    ) -> None:
        if self.elite_triggers >= self.policy.max_elite_triggers:
            return

        remaining_pool = self.elite_pool_s - (
            self.elite_runtime_s
            + self.certification_runtime_s
        )
        remaining_search = self.search_deadline_at - now
        if remaining_pool <= 0.0 or remaining_search <= 0.0:
            return

        baseline_proxy = float(best.objective())
        baseline_result, cert_runtime_s, archive_updated = (
            self._certify(
                best.solution,
                screened_objective=baseline_proxy,
            )
        )

        self.elite_triggers += 1
        self._last_elite_at = perf_counter()

        event: dict[str, Any] = {
            "trigger": self.elite_triggers,
            "elapsed_s": now - self.started_at,
            "baseline_screened_objective": baseline_proxy,
            "baseline_stage1_status": _stage1_status(
                baseline_result
            ),
            "baseline_cert_runtime_s": cert_runtime_s,
            "archive_updated_before_elite": archive_updated,
            "intensifier": getattr(
                self.elite_intensifier,
                "__name__",
                type(self.elite_intensifier).__name__,
            ),
            "strict_improved": False,
            "injected": False,
        }

        if not _strict(baseline_result):
            event["skip_reason"] = "baseline_not_strict"
            self.events.append(event)
            return

        after_cert = perf_counter()
        remaining_pool = self.elite_pool_s - (
            self.elite_runtime_s
            + self.certification_runtime_s
        )
        remaining_search = self.search_deadline_at - after_cert
        elite_budget_s = min(
            self.elite_burst_s,
            max(0.0, remaining_pool),
            max(0.0, remaining_search),
        )
        if elite_budget_s <= 0.0:
            event["skip_reason"] = "elite_budget_exhausted"
            self.events.append(event)
            return

        state = UavMecState(
            self.instance,
            deepcopy(best.solution),
            self.evaluator,
        )
        elite_started = perf_counter()
        intensified, elite_stats = self.elite_intensifier(
            state,
            config=self.problem_config,
            objective=self.oracle,
            max_rounds=self.policy.elite_rounds_per_trigger,
            max_runtime_s=elite_budget_s,
        )
        elite_runtime_s = perf_counter() - elite_started
        self.elite_runtime_s += elite_runtime_s

        result_started = perf_counter()
        elite_result = self.oracle.solve(
            self.instance,
            intensified.solution,
        )
        result_runtime_s = perf_counter() - result_started
        self.certification_runtime_s += result_runtime_s
        self.certification_samples_s.append(result_runtime_s)

        strict_improved = False
        injected = False
        candidate_proxy: float | None = None

        if _strict(elite_result):
            base_energy = float(baseline_result.energy_stage1_j)
            elite_energy = float(elite_result.energy_stage1_j)
            energy_tol = (
                self.policy.strict_energy_tolerance_rel
                * max(1.0, abs(base_energy))
            )
            strict_improved = (
                elite_energy < base_energy - energy_tol
            )

            self._update_strict_incumbent(
                intensified.solution,
                elite_result,
                screened_objective=baseline_proxy,
            )

            if strict_improved:
                self.elite_strict_improvements += 1
                candidate_state = UavMecState(
                    self.instance,
                    deepcopy(intensified.solution),
                    self.evaluator,
                )
                candidate_proxy = float(
                    candidate_state.objective()
                )
                proxy_limit = (
                    baseline_proxy
                    * (
                        1.0
                        + self.policy.proxy_injection_tolerance_rel
                    )
                )
                if candidate_proxy <= proxy_limit:
                    self._inject_solution(
                        best,
                        current,
                        intensified.solution,
                    )
                    self.elite_injections += 1
                    injected = True
                    self._last_best_objective = float(
                        best.objective()
                    )
                    self._last_improvement_at = perf_counter()

        event.update(
            {
                "elite_runtime_s": elite_runtime_s,
                "elite_result_runtime_s": result_runtime_s,
                "elite_stage1_status": _stage1_status(
                    elite_result
                ),
                "strict_improved": strict_improved,
                "injected": injected,
                "candidate_screened_objective": candidate_proxy,
                "elite_stats": elite_stats,
            }
        )
        self.events.append(event)

    def __call__(
        self,
        rng,
        best: UavMecState,
        current: UavMecState,
    ) -> bool:
        del rng
        now = perf_counter()
        self.elapsed_s = now - self.started_at

        best_objective = float(best.objective())
        if self._last_best_objective is None:
            self._last_best_objective = best_objective
            self._last_improvement_at = now
        elif best_objective < self._last_best_objective - 1e-12:
            self._last_best_objective = best_objective
            self._last_improvement_at = now

        self.last_improvement_elapsed_s = (
            self._last_improvement_at - self.started_at
        )

        if now >= self.search_deadline_at:
            self.stop_reason = "search_deadline"
            return True

        if self.elite_triggers >= self.policy.max_elite_triggers:
            return False

        if self.elapsed_s < self.min_exploration_s:
            return False

        if now - self._last_improvement_at < self.stagnation_s:
            return False

        if (
            self._last_elite_at is not None
            and now - self._last_elite_at < self.stagnation_s
        ):
            return False

        self._attempt_elite(best, current, now)
        return False


def run_uav_mec_continuous_esi_alns(
    instance: Instance,
    *,
    continuous: ContinuousESIConfig,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    elite_oracle: Stage1CVXObjectiveOracle | None = None,
) -> ContinuousESIResult:
    """Run one uninterrupted ALNS engine with in-place ESI events."""

    _validate_policy(continuous)
    base_cfg = config or UavMecALNSConfig()
    objective_evaluator = (
        evaluator or ScreenedProxyObjectiveEvaluator()
    )
    oracle = elite_oracle or Stage1CVXObjectiveOracle()

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
        continuous.total_runtime_s
        * (1.0 - continuous.final_cert_reserve_fraction)
    )
    search_deadline = started + search_budget_s

    initial_objective = float(
        objective_evaluator(
            instance,
            initial_solution,
        )
    )
    accept = _TimeScaledRecordToRecordTravel(
        initial_objective,
        base_cfg.rrt_start_gap,
        base_cfg.rrt_end_gap,
        search_budget_s,
        started_at=started,
    )
    controller = _ContinuousESIController(
        instance=instance,
        evaluator=objective_evaluator,
        problem_config=base_cfg.problem,
        oracle=oracle,
        policy=continuous,
        started_at=started,
        search_deadline_at=search_deadline,
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

    final_certification_performed = False
    final_best = exploration.best_solution
    final_best_objective = float(
        exploration.best_objective
    )

    should_certify_final = (
        controller.strict_result is None
        or controller.last_certified_screened_objective is None
    )
    if (
        not should_certify_final
        and controller.last_certified_screened_objective is not None
    ):
        reference = (
            controller.last_certified_screened_objective
        )
        material_gain = (
            reference - final_best_objective
        ) / max(1.0, abs(reference))
        should_certify_final = (
            material_gain
            >= continuous.final_cert_min_screened_gain_rel
        )

    if should_certify_final:
        final_certification_performed = True
        controller._certify(
            final_best,
            screened_objective=final_best_objective,
        )

    if (
        controller.strict_solution is not None
        and controller.strict_result is not None
    ):
        best_solution = deepcopy(controller.strict_solution)
        final_cvx = controller.strict_result
        strict_found = True
    else:
        best_solution = deepcopy(final_best)
        cert_started = perf_counter()
        final_cvx = oracle.solve(
            instance,
            best_solution,
        )
        controller.certification_runtime_s += (
            perf_counter() - cert_started
        )
        strict_found = _strict(final_cvx)

    validate_solution(instance, best_solution)
    return ContinuousESIResult(
        exploration=exploration,
        best_solution=best_solution,
        final_cvx=final_cvx,
        strict_incumbent_found=strict_found,
        strict_incumbent_updates=(
            controller.strict_incumbent_updates
        ),
        elite_triggers=controller.elite_triggers,
        elite_strict_improvements=(
            controller.elite_strict_improvements
        ),
        elite_injections=controller.elite_injections,
        elite_runtime_s=controller.elite_runtime_s,
        certification_runtime_s=(
            controller.certification_runtime_s
        ),
        final_certification_performed=(
            final_certification_performed
        ),
        search_runtime_s=search_runtime_s,
        total_runtime_s=perf_counter() - started,
        oracle_calls=oracle.calls,
        oracle_cache_hits=oracle.cache_hits,
        events=controller.events,
    )
