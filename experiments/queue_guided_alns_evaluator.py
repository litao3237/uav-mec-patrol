"""P8 experimental queue-aware ALNS scalar objective, opt-in only.

P7 read-only audit established that the original ALNS generated ~595
different states in six inspected stressed K80 cases but just TWO
passed the *necessary* FIFO/EDF queue timing check.

This module intervenes INSIDE original ALNS exploration, NOT on a
failed endpoint. It changes neither neighborhood operators nor the
underlying physical model, and never interprets a necessary pass as
proof of true continuous resource feasibility.

On a queue-NECESSARY-failing state, return a smooth large penalty that
responds to the amount of optimistic task/deadline, average-delay and
cycle violation, rather than only to the original proxy's violation
counts. On a queue-necessary-PASSING state, call the unchanged original
ScreenedProxyObjectiveEvaluator (including its CVX refinement logic).

Two pre-registered variants:
- queue_sum: sum of normalized optimistic lower-bound shortfalls and
  the worst shortfall.
- queue_max: emphasize the single worst shortfall, with a smaller sum.

Prioritize queue-necessary-passing states as a search HEURISTIC only:
even states that pass the necessary queue test can violate static CPU,
bandwidth, real upload scheduling, battery and Stage1/Stage2. Use a
finite 1e9..5e9 penalty for queue-pass but original-proxy infeasible;
queue-failure penalty starts at 1e10. Full feasible original scalar
energy is NEVER altered.

The ranking is deliberately not asserted mathematically equivalent to
original ESI/ALNS. Compare rigorously under matched time budgets.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import isfinite

from uav_mec.algorithms.alns.evaluator import (
    ScreenedProxyObjectiveEvaluator, solution_signature,
)
from uav_mec.algorithms.initial import evaluate_initial_proxy
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


POLICIES=("queue_sum","queue_max")
INFEASIBLE_BASE_J=1e10
QUEUE_PASS_PROXY_CAP_J=5e9
STRICT_FEASIBLE_ENERGY_CUTOFF_J=1e8


def normalized_queue_violation(instance,queue) -> dict:
    """Read-only lower-bound violation indicators; NO feasibility oracle."""
    task_ratios=[]
    raw_deadline_excess=[]
    for tid,task in instance.tasks.items():
        excess=max(0.0,float(queue.task_completion_lb_s[tid]) -
                   (task.release_s + task.deadline_s))
        raw_deadline_excess.append(excess)
        task_ratios.append(excess/max(1.0,task.deadline_s))
    average_excess=max(
        0.0,float(queue.avg_delay_lb_s)-instance.avg_delay_budget_s)
    average_ratio=average_excess/max(1.0,instance.avg_delay_budget_s)
    cycle_ratios=[
        max(0.0,float(t)-instance.cycle_s)/max(1.0,instance.cycle_s)
        for t in queue.return_time_lb_s.values()
    ]
    ratios=task_ratios+[average_ratio]+cycle_ratios
    return {
        "total_normalized_excess":float(sum(ratios)),
        "maximum_normalized_excess":float(max(ratios,default=0.0)),
        "mean_task_normalized_excess":float(sum(task_ratios)/max(1,len(task_ratios))),
        "violated_task_deadlines":sum(v>1e-4 for v in raw_deadline_excess),
        "worst_task_deadline_excess_s":float(max(raw_deadline_excess,default=0.0)),
        "average_delay_excess_s":average_excess,
        "max_cycle_excess_s":max(
            0.0,*[float(t)-instance.cycle_s for t in queue.return_time_lb_s.values()]),
        "reasons":len(queue.reasons),
    }


@dataclass
class QueueGuidedObjectiveEvaluator:
    """Synchronous Stage1-safe ALNS objective with a queue-LB gradient.

    The internal original evaluator is invoked only where queue passes.
    P8 evaluation counts include the real evaluation cost of computing
    the optimistic queue certificate. No extra CVX calls are hidden.
    """

    policy: str = "queue_sum"
    original: ScreenedProxyObjectiveEvaluator = field(
        default_factory=ScreenedProxyObjectiveEvaluator)
    cache: dict[tuple,float] = field(default_factory=dict,init=False)
    stats: Counter = field(default_factory=Counter,init=False)

    def __post_init__(self):
        if self.policy not in POLICIES:
            raise ValueError("Unknown queue-guided objective")

    def __call__(self,instance,solution)->float:
        self.stats["calls"]+=1
        key=solution_signature(solution)
        if key in self.cache:
            self.stats["cache_hits"]+=1
            return self.cache[key]
        info=build_event_info(instance,solution)
        queue=queue_aware_feasibility_precheck(instance,solution,info)
        if queue.feasible:
            self.stats["queue_necessary_pass"]+=1
            original_value=float(self.original(instance,solution))
            if original_value < STRICT_FEASIBLE_ENERGY_CUTOFF_J:
                # Preserve original physical energy ranking exactly.
                value=original_value
                self.stats["original_finite_energy_zone"]+=1
            else:
                # Priority to queue-necessary passing structures is a
                # *search heuristic*, never a strict feasibility claim.
                value=1e9*(1.0+min(4.0,original_value/1e9))
                self.stats["queue_pass_but_original_proxy_penalty"]+=1
        else:
            self.stats["queue_necessary_fail"]+=1
            measures=normalized_queue_violation(instance,queue)
            original_proxy=evaluate_initial_proxy(instance,solution)
            # Remove the original proxy 1e9-level infeasible penalties:
            # proxy total energy is flight + MEC/local constructive energy,
            # at UAV's physical kJ scale, below the hard 1e10 tier.
            energy=float(original_proxy.score.total_energy_j)
            if not isfinite(energy):
                raise ValueError("Nonfinite proxy energy in P8")
            if self.policy=="queue_sum":
                grade=(
                    measures["total_normalized_excess"]+
                    measures["maximum_normalized_excess"])
            else:
                grade=(
                    measures["maximum_normalized_excess"]+
                    .1*measures["total_normalized_excess"])
            value=(
                INFEASIBLE_BASE_J+1e9*grade+energy)
            self.stats["queue_failure_gradation_sum"]+=int(
                1000*measures["total_normalized_excess"])
            self.stats["queue_failure_gradation_max"]+=int(
                1000*measures["maximum_normalized_excess"])
            self.stats["queue_failure_bad_task_count"]+=measures[
                "violated_task_deadlines"]
        if not isfinite(value):
            raise ValueError("Nonfinite P8 ALNS objective")
        self.cache[key]=float(value)
        return self.cache[key]

    def summarize(self):
        return {
            "policy":self.policy,
            "stats":dict(self.stats),
            "original_internal_solver_stats":{
                k:getattr(self.original.stats,k) for k in (
                    "calls","cache_hits","feasible_calls","infeasible_calls",
                    "precheck_rejects","ambiguous_proxy_calls","cvx_refinements")
            },
            "numerical_solver_statuses":dict(
                self.original.stats.resource_status_counts),
        }
