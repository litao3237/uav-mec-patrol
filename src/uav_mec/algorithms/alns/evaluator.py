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
        if score.violated_constraints == 0:
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

        info = build_event_info(instance, solution)
        precheck = fast_feasibility_precheck(instance, solution, info)
        proxy = evaluate_initial_proxy(instance, solution)
        score = proxy.score

        if not precheck.feasible:
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

        if result.feasible:
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
