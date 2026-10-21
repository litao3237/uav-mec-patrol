from __future__ import annotations

from dataclasses import dataclass, field

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource import (
    CVXResourceSolver,
    KKTResourceSolver,
    ResourceSolver,
    fast_feasibility_precheck,
)

from uav_mec.algorithms.initial import evaluate_initial_proxy
from uav_mec.evaluation.task_objective import scalar_for_instance, measured_task_key, task_scalar


def solution_signature(solution: DiscreteSolution) -> tuple:
    """Stable hashable signature for objective caching."""

    routes = tuple(
        (uav_id, tuple(route.labels()))
        for uav_id, route in sorted(solution.routes.items())
    )
    contacts = tuple(
        (visit_id, visit.uav_id, visit.point_id)
        for visit_id, visit in sorted(solution.contact_visits.items())
    )
    decisions = tuple(
        (
            task_id,
            decision.mode.value,
            decision.contact_visit_id or "",
        )
        for task_id, decision in sorted(solution.task_decisions.items())
    )
    return routes, contacts, decisions


@dataclass
class EvaluatorStats:
    calls: int = 0
    cache_hits: int = 0
    feasible_calls: int = 0
    infeasible_calls: int = 0
    resource_status_counts: dict[str, int] = field(default_factory=dict)
    precheck_rejects: int = 0
    ambiguous_proxy_calls: int = 0
    cvx_refinements: int = 0


@dataclass
class ProxyObjectiveEvaluator:
    """Fast scalar objective used for ALNS structural smoke tests."""

    infeasible_penalty_j: float = 1e9
    _cache: dict[tuple, float] = field(default_factory=dict, init=False)
    stats: EvaluatorStats = field(default_factory=EvaluatorStats, init=False)

    def __call__(
        self,
        instance: Instance,
        solution: DiscreteSolution,
    ) -> float:
        self.stats.calls += 1
        key = solution_signature(solution)
        if key in self._cache:
            self.stats.cache_hits += 1
            return self._cache[key]

        proxy = evaluate_initial_proxy(instance, solution)
        score = proxy.score
        if score.qos_soft:
            value = scalar_for_instance(instance,
                                physical_violations=score.violated_constraints,
                                on_time=score.on_time_tasks,
                                normalized_lateness=score.normalized_lateness,
                                energy_j=score.total_energy_j, distance_m=score.total_distance_m)
            self.stats.feasible_calls += int(score.violated_constraints == 0)
            self.stats.infeasible_calls += int(score.violated_constraints != 0)
        elif score.violated_constraints == 0:
            value = score.total_energy_j
            self.stats.feasible_calls += 1
        else:
            value = (
                score.total_energy_j
                + self.infeasible_penalty_j
                * (
                    1.0
                    + score.violated_constraints
                    + score.max_normalized_violation
                    + score.sum_normalized_violation
                )
            )
            self.stats.infeasible_calls += 1

        self._cache[key] = float(value)
        return float(value)


@dataclass
class ScreenedProxyObjectiveEvaluator:
    """Three-zone outer-search evaluator.

    1. Optimistic precheck failure is a hard infeasibility certificate for the
       fixed discrete state and receives a large finite penalty.
    2. Proxy-feasible states use the fast constructive resource energy.
    3. Precheck-feasible but proxy-infeasible states are ambiguous: the proxy is
       only one conservative resource allocation. These states are refined by a
       Stage-1-only CVXPY solve instead of being falsely rejected.

    This keeps the common path cheap while avoiding the false-negative pattern
    observed at high load (proxy violation > 0 but optimized P1-R feasible).
    """

    cvx_solver: ResourceSolver = field(
        default_factory=lambda: CVXResourceSolver(run_stage2=False)
    )
    infeasible_penalty_j: float = 1e9
    soft_qos_scalar_profile: str = "m0"
    _cache: dict[tuple, float] = field(default_factory=dict, init=False)
    stats: EvaluatorStats = field(default_factory=EvaluatorStats, init=False)
    _quality_cache: dict[tuple, tuple[float, ...]] = field(
        default_factory=dict, init=False, repr=False,
    )

    def _soft_scalar(self, instance: Instance, *, physical_violations: int,
                     on_time: int, normalized_lateness: float, energy_j: float,
                     distance_m: float) -> float:
        # Research-only controlled factor. Both arms share M0's physical model,
        # CVX recourse, admissibility, proxy/ambiguous-state handling and seed.
        options = dict(physical_violations=physical_violations, on_time=on_time,
                       normalized_lateness=normalized_lateness, energy_j=energy_j,
                       distance_m=distance_m)
        if self.soft_qos_scalar_profile == "m0":
            return scalar_for_instance(instance, **options)
        if self.soft_qos_scalar_profile == "v26_scale":
            return task_scalar(total_tasks=len(instance.tasks), **options)
        raise ValueError(
            f"Unknown soft_qos_scalar_profile={self.soft_qos_scalar_profile!r}"
        )

    def quality_key(self, instance: Instance, solution: DiscreteSolution) -> tuple[float, ...]:
        """Return already-computed proxy/CVX quality without an extra solver call.

        M0.3 accepts/rewards in task successes, lateness and physical Joules.
        This lookup shares the scalar evaluator's cache and has no new RNG.
        """
        if instance.qos_hard:
            raise ValueError("Quality-based search is only for task-level QoS")
        key = solution_signature(solution)
        if key not in self._quality_cache:
            self(instance, solution)
        return self._quality_cache[key]

    def __call__(
        self,
        instance: Instance,
        solution: DiscreteSolution,
    ) -> float:
        self.stats.calls += 1
        key = solution_signature(solution)
        if key in self._cache:
            self.stats.cache_hits += 1
            return self._cache[key]

        info = build_event_info(instance, solution)
        precheck = fast_feasibility_precheck(instance, solution, info)
        proxy = evaluate_initial_proxy(instance, solution)
        score = proxy.score

        if score.qos_soft:
            # CVX can rescue a conservative equal-share proxy, but only with
            # the same independently audited physical certificate as the
            # finalizer. Do not label solver "feasible" without a residual check.
            physical_failure = not precheck.feasible
            evaluated_key = None
            if score.violated_constraints and not physical_failure:
                from uav_mec.analysis.stage1_acceptance import qualify_stage1_result

                self.stats.cvx_refinements += 1
                self.stats.ambiguous_proxy_calls += 1
                result = qualify_stage1_result(
                    instance, solution, self.cvx_solver.solve(instance, solution, info)
                )
                self.stats.resource_status_counts[result.status] = (
                    self.stats.resource_status_counts.get(result.status, 0) + 1
                )
                physical_failure = not result.diagnostics.get("stage1_qualified", False)
                if not physical_failure:
                    audit = result.diagnostics["stage1_acceptance_audit"]["reconstructed"]
                    evaluated_key = measured_task_key(
                        instance, audit["timeline"]["task_delay_s"],
                        energy_j=audit["metrics"]["energy_j"],
                        distance_m=audit["metrics"]["total_distance_m"],
                    )
            self.stats.precheck_rejects += int(not precheck.feasible)
            self.stats.feasible_calls += int(not physical_failure)
            self.stats.infeasible_calls += int(physical_failure)
            if evaluated_key is None:
                on_time, late, energy, distance = (
                    score.on_time_tasks, score.normalized_lateness,
                    score.total_energy_j, score.total_distance_m,
                )
            else:
                on_time, late, energy, distance = (
                    int(-evaluated_key[1]), evaluated_key[2],
                    evaluated_key[3], evaluated_key[4],
                )
            value = self._soft_scalar(
                instance, physical_violations=int(physical_failure),
                on_time=on_time, normalized_lateness=late,
                energy_j=energy, distance_m=distance,
            )
            self._quality_cache[key] = (
                float(int(physical_failure)), -float(on_time),
                float(late), float(energy), float(distance),
            )
        elif not precheck.feasible:
            self.stats.precheck_rejects += 1
            self.stats.infeasible_calls += 1
            value = (
                score.total_energy_j
                + self.infeasible_penalty_j
                * (
                    1.0
                    + len(precheck.reasons)
                    + score.max_normalized_violation
                    + score.sum_normalized_violation
                )
            )
        elif score.violated_constraints == 0:
            self.stats.feasible_calls += 1
            value = score.total_energy_j
        else:
            self.stats.ambiguous_proxy_calls += 1
            self.stats.cvx_refinements += 1
            result = self.cvx_solver.solve(instance, solution, info)
            self.stats.resource_status_counts[result.status] = (
                self.stats.resource_status_counts.get(result.status, 0) + 1
            )
            if result.feasible:
                self.stats.feasible_calls += 1
                value = float(result.energy_stage1_j)
            else:
                self.stats.infeasible_calls += 1
                value = (
                    score.total_energy_j
                    + self.infeasible_penalty_j
                    * (
                        1.0
                        + score.violated_constraints
                        + score.max_normalized_violation
                        + score.sum_normalized_violation
                    )
                )

        self._cache[key] = float(value)
        return float(value)


@dataclass
class KKTObjectiveEvaluator:
    """Analytical P1-R evaluator with a finite infeasible penalty.

    The KKT resource solver may return a converged/approximate KKT point or a
    verified constructive feasible_seed fallback. Therefore this evaluator is
    not an exact oracle: CVXPY remains the correctness oracle for resource
    optimality checks. Infeasible states receive a finite proxy-based penalty
    so ALNS can move through infeasible regions.
    """

    solver: ResourceSolver = field(default_factory=KKTResourceSolver)
    infeasible_penalty_j: float = 1e9
    _cache: dict[tuple, float] = field(default_factory=dict, init=False)
    stats: EvaluatorStats = field(default_factory=EvaluatorStats, init=False)

    def __call__(
        self,
        instance: Instance,
        solution: DiscreteSolution,
    ) -> float:
        self.stats.calls += 1
        key = solution_signature(solution)
        if key in self._cache:
            self.stats.cache_hits += 1
            return self._cache[key]

        result = self.solver.solve(instance, solution)
        self.stats.resource_status_counts[result.status] = (
            self.stats.resource_status_counts.get(result.status, 0) + 1
        )

        # Only the soft protocol needs a proxy key for every KKT outcome.
        # Keep strict-mode allocation and acceptance unchanged.
        score = evaluate_initial_proxy(instance, solution).score if not instance.qos_hard else None
        if score is not None and score.qos_soft:
            value = scalar_for_instance(instance,
                                physical_violations=int(not result.feasible),
                                on_time=score.on_time_tasks,
                                normalized_lateness=score.normalized_lateness,
                                energy_j=score.total_energy_j, distance_m=score.total_distance_m)
            self.stats.feasible_calls += int(result.feasible)
            self.stats.infeasible_calls += int(not result.feasible)
        elif result.feasible:
            value = float(result.energy_stage1_j)
            self.stats.feasible_calls += 1
        else:
            proxy = evaluate_initial_proxy(instance, solution)
            score = proxy.score
            value = (
                score.total_energy_j
                + self.infeasible_penalty_j
                * (
                    1.0
                    + score.violated_constraints
                    + score.max_normalized_violation
                    + score.sum_normalized_violation
                )
            )
            self.stats.infeasible_calls += 1

        self._cache[key] = float(value)
        return float(value)
