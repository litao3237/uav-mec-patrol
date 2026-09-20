from __future__ import annotations

import math
from dataclasses import dataclass, field

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id


@dataclass(frozen=True)
class FeasibilityPrecheckResult:
    feasible: bool
    reasons: tuple[str, ...] = ()
    task_completion_lb_s: dict[str, float] = field(default_factory=dict)
    return_time_lb_s: dict[str, float] = field(default_factory=dict)


def _rate_mbps(bandwidth_mhz: float, gamma_mhz_value: float) -> float:
    if bandwidth_mhz <= 0.0:
        return 0.0
    return bandwidth_mhz * math.log2(1.0 + gamma_mhz_value / bandwidth_mhz)


def fast_feasibility_precheck(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    *,
    tol_s: float = 1e-9,
) -> FeasibilityPrecheckResult:
    """Cheap optimistic lower-bound checks before invoking a conic solver.

    The checks deliberately give every offloading batch the *entire* MEC bandwidth
    and CPU capacity, ignore queueing from other UAVs, and ignore prior upload
    stops when computing base arrivals. Therefore any violation found here is a
    genuine infeasibility certificate for the fixed discrete solution.
    """

    reasons: list[str] = []
    completion_lb: dict[str, float] = {}
    upload_lb_by_visit: dict[str, float] = {}

    # Optimistic upload lower bounds: one batch temporarily receives all MEC bandwidth.
    for visit_id, batch in info.batch_tasks.items():
        if not batch:
            continue
        mec_id = visit_mec_id(instance, solution, visit_id)
        mec = instance.mecs[mec_id]
        gamma = gamma_mhz(instance, solution, visit_id)
        rate = _rate_mbps(mec.bandwidth_mhz, gamma)
        data_mbit = sum(instance.tasks[t].data_mbit for t in batch)
        upload_lb_by_visit[visit_id] = data_mbit / rate if rate > 0.0 else float("inf")

    # Per-task optimistic completion lower bounds.
    for task_id, decision in solution.task_decisions.items():
        task = instance.tasks[task_id]
        uav_id = info.task_owner[task_id]

        if decision.mode is ExecutionMode.LOCAL:
            uav = instance.uavs[uav_id]
            # Ignore all local queueing and prior upload stops: optimistic by construction.
            lb = (
                info.base_collect_complete_s[(uav_id, task_id)]
                + task.workload_gcycles / uav.local_cpu_ghz
            )
        else:
            visit_id = decision.contact_visit_id
            assert visit_id is not None
            mec_id = visit_mec_id(instance, solution, visit_id)
            mec = instance.mecs[mec_id]
            edf_order = info.batch_edf_order[visit_id]
            prefix_work = 0.0
            for current in edf_order:
                prefix_work += instance.tasks[current].workload_gcycles
                if current == task_id:
                    break
            lb = (
                info.base_contact_arrival_s[(uav_id, visit_id)]
                + upload_lb_by_visit[visit_id]
                + prefix_work / mec.cpu_ghz
            )

        completion_lb[task_id] = lb
        deadline_abs = task.release_s + task.deadline_s
        if lb > deadline_abs + tol_s:
            reasons.append(
                f"task {task_id}: optimistic completion LB {lb:.6f}s exceeds "
                f"deadline {deadline_abs:.6f}s"
            )

    # Average-delay optimistic lower bound.
    if completion_lb:
        avg_lb = sum(
            completion_lb[t] - instance.tasks[t].release_s for t in instance.tasks
        ) / len(instance.tasks)
        if avg_lb > instance.avg_delay_budget_s + tol_s:
            reasons.append(
                f"average delay: optimistic LB {avg_lb:.6f}s exceeds "
                f"budget {instance.avg_delay_budget_s:.6f}s"
            )

    # Patrol-cycle optimistic lower bound.
    return_lb: dict[str, float] = {}
    for uav_id, visit_ids in info.contact_order.items():
        lb = info.base_return_s[uav_id] + sum(upload_lb_by_visit.get(v, 0.0) for v in visit_ids)
        return_lb[uav_id] = lb
        if lb > instance.cycle_s + tol_s:
            reasons.append(
                f"UAV {uav_id}: optimistic return LB {lb:.6f}s exceeds cycle "
                f"{instance.cycle_s:.6f}s"
            )

    return FeasibilityPrecheckResult(
        feasible=not reasons,
        reasons=tuple(reasons),
        task_completion_lb_s=completion_lb,
        return_time_lb_s=return_lb,
    )
