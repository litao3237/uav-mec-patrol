"""Queue-aware optimistic feasibility certificate for fixed UAV-MEC structures.

This is a *necessary* (not sufficient) feasibility test. It strengthens the
current task-only fast_feasibility_precheck by preserving local UAV FIFO
execution and FIFO between visits of the same (UAV,MEC) virtual queue,
together with EDF task order within each MEC visit.

It remains optimistic:
  - every UAV-MEC pair gets the station's FULL bandwidth and FULL MEC CPU;
  - every UAV local task gets its MAX local CPU;
  - the minimum possible upload duration is used in flight/event timelines;
  - interference and competition among different UAV-MEC pairs are ignored;
  - no battery-energy constraints are needed to derive the time lower bound.

Therefore any deadline/avg-delay/patrol-cycle violation *certifies only
this fixed discrete structure is impossible* under the published resource
model. Passing all checks does NOT prove real CVXPY feasibility.
Do NOT enable as a production prune without a separate numerical audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id
from uav_mec.optimization.resource.analytic import rate_mbps


@dataclass(frozen=True)
class QueueAwarePrecheckResult:
    feasible: bool
    reasons: tuple[str, ...]
    task_completion_lb_s: dict[str, float]
    return_time_lb_s: dict[str, float]
    min_upload_s_by_visit: dict[str, float]
    earliest_batch_start_lb_s: dict[str, float]
    earliest_local_start_lb_s: dict[str, float]
    local_fifo_earliest_finish_s: dict[str, float]
    mec_batch_earliest_finish_s: dict[str, float]
    avg_delay_lb_s: float


def queue_aware_feasibility_precheck(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    *,
    tol_s: float = 1e-4,
) -> QueueAwarePrecheckResult:
    """Return sound optimistic time bounds with modeled FIFO/EDF order.

    All source paper workloads use release_s=0, as does its independent
    constraint audit. Do not silently generalize this bound to a new
    release-time model without also generalizing the resource constraints.
    """
    if any(task.release_s != 0.0 for task in instance.tasks.values()):
        raise ValueError("Current fixed-structure resource model assumes release_s=0")
    if tol_s < 0:
        raise ValueError("tol_s must be nonnegative")

    upload_lb = {}
    for v, batch in info.batch_tasks.items():
        mec = instance.mecs[visit_mec_id(instance, solution, v)]
        gamma = gamma_mhz(instance, solution, v)
        rate = rate_mbps(mec.bandwidth_mhz, gamma)
        data_mbit = sum(instance.tasks[t].data_mbit for t in batch)
        upload_lb[v] = data_mbit / rate

    def before_task_upload_s(uav_id, tid):
        return sum(
            upload_lb[v] for v in info.prior_contacts_before_task[uav_id, tid]
        )

    def before_contact_upload_s(uav_id, visit_id):
        return sum(
            upload_lb[v]
            for v in info.prior_contacts_before_contact[uav_id, visit_id]
        )

    completion_lb: dict[str, float] = {}
    earliest_local_start: dict[str, float] = {}
    local_finish: dict[str, float] = {}
    for uav_id, task_ids in info.local_order.items():
        cpu_ghz = instance.uavs[uav_id].local_cpu_ghz
        last_finished = 0.0
        for tid in task_ids:
            earliest_collect = (
                info.base_collect_complete_s[uav_id, tid]
                + before_task_upload_s(uav_id, tid)
            )
            earliest_start = max(earliest_collect, last_finished)
            finished = (
                earliest_start
                + instance.tasks[tid].workload_gcycles / cpu_ghz
            )
            earliest_local_start[tid] = earliest_start
            local_finish[tid] = finished
            completion_lb[tid] = finished
            last_finished = finished

    earliest_batch_start: dict[str, float] = {}
    mec_finish: dict[str, float] = {}
    for uav_id, visit_ids in info.contact_order.items():
        for v in visit_ids:
            mec = instance.mecs[visit_mec_id(instance, solution, v)]
            arrival_lb = (
                info.base_contact_arrival_s[uav_id, v]
                + before_contact_upload_s(uav_id, v)
                + upload_lb[v]
            )
            prev = info.contact_predecessor_same_mec[v]
            prior_finished = mec_finish[prev] if prev is not None else 0.0
            first_batch_start = max(arrival_lb, prior_finished)
            earliest_batch_start[v] = first_batch_start
            cum_work = 0.0
            for tid in info.batch_edf_order[v]:
                cum_work += instance.tasks[tid].workload_gcycles
                completion_lb[tid] = first_batch_start + cum_work / mec.cpu_ghz
            mec_finish[v] = first_batch_start + cum_work / mec.cpu_ghz

    if set(completion_lb) != set(instance.tasks):
        raise ValueError("Incomplete task completion bounds; invalid discrete structure")

    return_lb = {}
    for uav_id, visits in info.contact_order.items():
        return_lb[uav_id] = (
            info.base_return_s[uav_id]
            + sum(upload_lb[v] for v in visits)
        )

    reasons = []
    for tid, task in instance.tasks.items():
        deadline = task.release_s + task.deadline_s
        lb = completion_lb[tid]
        if lb > deadline + tol_s:
            reasons.append(
                f"task {tid}: queue-aware optimistic completion LB "
                f"{lb:.6f}s exceeds deadline {deadline:.6f}s"
            )

    avg_lb = mean(
        completion_lb[t] - instance.tasks[t].release_s
        for t in instance.tasks
    )
    if avg_lb > instance.avg_delay_budget_s + tol_s:
        reasons.append(
            f"average delay: queue-aware optimistic LB {avg_lb:.6f}s exceeds "
            f"budget {instance.avg_delay_budget_s:.6f}s"
        )
    for uav_id, lb in return_lb.items():
        if lb > instance.cycle_s + tol_s:
            reasons.append(
                f"UAV {uav_id}: optimistic return LB {lb:.6f}s "
                f"exceeds cycle {instance.cycle_s:.6f}s"
            )

    return QueueAwarePrecheckResult(
        feasible=not reasons,
        reasons=tuple(reasons),
        task_completion_lb_s=completion_lb,
        return_time_lb_s=return_lb,
        min_upload_s_by_visit=upload_lb,
        earliest_batch_start_lb_s=earliest_batch_start,
        earliest_local_start_lb_s=earliest_local_start,
        local_fifo_earliest_finish_s=local_finish,
        mec_batch_earliest_finish_s=mec_finish,
        avg_delay_lb_s=avg_lb,
    )
