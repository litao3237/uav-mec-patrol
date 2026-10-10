"""Opt-in queue-certificate outer ALNS evaluator.

The original ScreenedProxyObjectiveEvaluator remains untouched. This subclass
changes ONLY the necessary-feasibility screen for candidates that pass the
original task-only optimistic screen, preserving all incumbent/proxy/CVX code
paths otherwise. It is an *actual in-search* test, not offline postprocessing.

A new certificate cannot declare a previous strictly feasible solution
infeasible under the frozen FIFO/EDF resource model. We retain compact
witnesses, timings, and the number of expensive CVX evaluations avoided.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource import fast_feasibility_precheck
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.algorithms.initial import evaluate_initial_proxy

from .evaluator import ScreenedProxyObjectiveEvaluator, solution_signature


@dataclass
class QueueScreenStats:
    old_precheck_passed: int = 0
    old_precheck_rejected: int = 0
    queue_precheck_calls: int = 0
    queue_precheck_rejected: int = 0
    additional_rejections: int = 0
    extra_reject_proxy_ambiguous: int = 0
    extra_reject_proxy_feasible: int = 0
    avoided_exact_cvx_calls: int = 0
    queue_precheck_time_s: float = 0.0
    total_evaluation_time_s: float = 0.0
    cvx_solver_time_s: float = 0.0
    cvx_refinements: int = 0
    rejection_reason_histogram: dict[str, int] = field(default_factory=dict)
    sampled_rejections: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class QueueAwareScreenedProxyObjectiveEvaluator(ScreenedProxyObjectiveEvaluator):
    """Screening alternative; not enabled by default in any original method."""

    queue_tol_s: float = 1e-4
    witness_limit: int = 8
    queue_stats: QueueScreenStats = field(
        default_factory=QueueScreenStats, init=False,
    )

    def __call__(
        self,
        instance: Instance,
        solution: DiscreteSolution,
    ) -> float:
        started = perf_counter()
        try:
            self.stats.calls += 1
            signature = solution_signature(solution)
            if signature in self._cache:
                self.stats.cache_hits += 1
                return self._cache[signature]

            info = build_event_info(instance, solution)
            old = fast_feasibility_precheck(instance, solution, info)
            # Keep original code's proxy allocation and penalty computation.
            proxy = evaluate_initial_proxy(instance, solution)
            score = proxy.score

            if not old.feasible:
                self.queue_stats.old_precheck_rejected += 1
                self.stats.precheck_rejects += 1
                self.stats.infeasible_calls += 1
                value = (
                    score.total_energy_j
                    + self.infeasible_penalty_j
                    * (
                        1.0 + len(old.reasons)
                        + score.max_normalized_violation
                        + score.sum_normalized_violation
                    )
                )
            else:
                self.queue_stats.old_precheck_passed += 1
                t0 = perf_counter()
                newer = queue_aware_feasibility_precheck(
                    instance, solution, info, tol_s=self.queue_tol_s,
                )
                self.queue_stats.queue_precheck_time_s += perf_counter() - t0
                self.queue_stats.queue_precheck_calls += 1
                if not newer.feasible:
                    self.queue_stats.queue_precheck_rejected += 1
                    self.queue_stats.additional_rejections += 1
                    self.stats.infeasible_calls += 1
                    if score.violated_constraints:
                        self.queue_stats.extra_reject_proxy_ambiguous += 1
                        self.queue_stats.avoided_exact_cvx_calls += 1
                    else:
                        self.queue_stats.extra_reject_proxy_feasible += 1
                    histogram = self.queue_stats.rejection_reason_histogram
                    for reason in newer.reasons:
                        if reason.startswith("task "):
                            task_id = reason.split(":", 1)[0].split()[1]
                            family = "task_" + solution.task_decisions[task_id].mode.value
                        elif reason.startswith("average delay:"):
                            family = "average_delay"
                        elif reason.startswith("UAV "):
                            family = "patrol_cycle"
                        else:
                            family = "other"
                        histogram[family] = histogram.get(family, 0) + 1
                    if len(self.queue_stats.sampled_rejections) < self.witness_limit:
                        self.queue_stats.sampled_rejections.append({
                            "reasons": list(newer.reasons[:5]),
                            "proxy_violated_constraints": score.violated_constraints,
                            "task_queue_extension_max_s": max(
                                newer.task_completion_lb_s[t]
                                for t in instance.tasks
                            ),
                            "route_lengths": {
                                u: len(route.task_ids())
                                for u, route in solution.routes.items()
                            },
                            "offloaded_tasks": sum(
                                x.mode.value == "offload"
                                for x in solution.task_decisions.values()
                            ),
                        })
                    value = (
                        score.total_energy_j
                        + self.infeasible_penalty_j
                        * (
                            1.0 + len(newer.reasons)
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
                    self.queue_stats.cvx_refinements += 1
                    t0 = perf_counter()
                    result = self.cvx_solver.solve(instance, solution, info)
                    self.queue_stats.cvx_solver_time_s += perf_counter() - t0
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
                                1.0 + score.violated_constraints
                                + score.max_normalized_violation
                                + score.sum_normalized_violation
                            )
                        )

            self._cache[signature] = float(value)
            return float(value)
        finally:
            self.queue_stats.total_evaluation_time_s += perf_counter() - started
