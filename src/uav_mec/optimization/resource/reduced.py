from __future__ import annotations

from dataclasses import dataclass, field

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id

from .analytic import upload_time_s


@dataclass
class ReducedResourceEvaluation:
    total_energy_j: float
    energy_by_uav_j: dict[str, float]
    upload_time_s: dict[str, float]
    task_collect_s: dict[str, float]
    contact_arrival_s: dict[str, float]
    mec_arrival_s: dict[str, float]
    return_time_s: dict[str, float]
    local_start_s: dict[str, float]
    task_completion_s: dict[str, float]
    batch_start_s: dict[str, float]
    batch_finish_s: dict[str, float]
    avg_delay_s: float
    deadline_violation_s: dict[str, float] = field(default_factory=dict)
    cycle_violation_s: dict[str, float] = field(default_factory=dict)
    battery_violation_j: dict[str, float] = field(default_factory=dict)

    @property
    def max_qos_violation(self) -> float:
        values = list(self.deadline_violation_s.values()) + list(self.cycle_violation_s.values())
        return max([0.0, *values])


def evaluate_reduced_resources(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    *,
    bandwidth_mhz: dict[tuple[str, str], float],
    mec_cpu_ghz: dict[tuple[str, str], float],
    local_cpu_ghz: dict[str, float],
) -> ReducedResourceEvaluation:
    """Evaluate the fixed-discrete solution after eliminating epigraph time variables."""

    tau: dict[str, float] = {}
    for visit_id, batch in info.batch_tasks.items():
        visit = solution.contact_visits[visit_id]
        mec_id = visit_mec_id(instance, solution, visit_id)
        pair = (visit.uav_id, mec_id)
        data_mbit = sum(instance.tasks[t].data_mbit for t in batch)
        tau[visit_id] = upload_time_s(
            data_mbit,
            bandwidth_mhz[pair],
            gamma_mhz(instance, solution, visit_id),
        )

    t_collect: dict[str, float] = {}
    theta: dict[str, float] = {}
    mec_arrival: dict[str, float] = {}
    return_time: dict[str, float] = {}

    for task_id in instance.tasks:
        uav_id = info.task_owner[task_id]
        t_collect[task_id] = info.base_collect_complete_s[(uav_id, task_id)] + sum(
            tau[v] for v in info.prior_contacts_before_task[(uav_id, task_id)]
        )

    for uav_id, visits in info.contact_order.items():
        for visit_id in visits:
            theta[visit_id] = info.base_contact_arrival_s[(uav_id, visit_id)] + sum(
                tau[v] for v in info.prior_contacts_before_contact[(uav_id, visit_id)]
            )
            mec_arrival[visit_id] = theta[visit_id] + tau[visit_id]
        return_time[uav_id] = info.base_return_s[uav_id] + sum(tau[v] for v in visits)

    completion: dict[str, float] = {}
    local_start: dict[str, float] = {}
    for uav_id, order in info.local_order.items():
        prev_finish = 0.0
        for task_id in order:
            start = max(t_collect[task_id], prev_finish)
            local_start[task_id] = start
            finish = start + instance.tasks[task_id].workload_gcycles / local_cpu_ghz[task_id]
            completion[task_id] = finish
            prev_finish = finish

    batch_start: dict[str, float] = {}
    batch_finish: dict[str, float] = {}
    for uav_id, visits in info.contact_order.items():
        prev_finish_by_mec: dict[str, float] = {}
        for visit_id in visits:
            mec_id = visit_mec_id(instance, solution, visit_id)
            pair = (uav_id, mec_id)
            start = max(mec_arrival[visit_id], prev_finish_by_mec.get(mec_id, 0.0))
            batch_start[visit_id] = start
            prefix = 0.0
            for task_id in info.batch_edf_order[visit_id]:
                prefix += instance.tasks[task_id].workload_gcycles
                completion[task_id] = start + prefix / mec_cpu_ghz[pair]
            total = prefix
            finish = start + total / mec_cpu_ghz[pair]
            batch_finish[visit_id] = finish
            prev_finish_by_mec[mec_id] = finish

    energy_by_uav: dict[str, float] = {}
    for uav_id, uav in instance.uavs.items():
        energy = info.fixed_flight_energy_j[uav_id] + info.fixed_collection_energy_j[uav_id]
        for task_id in info.local_order[uav_id]:
            kappa_scaled = uav.kappa * 1e27
            f = local_cpu_ghz[task_id]
            energy += kappa_scaled * instance.tasks[task_id].workload_gcycles * f * f
        energy += sum(
            (uav.hover_power_w + uav.tx_power_w) * tau[visit_id]
            for visit_id in info.contact_order[uav_id]
        )
        energy_by_uav[uav_id] = energy

    avg_delay = sum(
        completion[t] - instance.tasks[t].release_s for t in instance.tasks
    ) / len(instance.tasks)
    deadline_violation = {
        t: completion[t] - instance.tasks[t].release_s - instance.tasks[t].deadline_s
        for t in instance.tasks
    }
    cycle_violation = {u: return_time[u] - instance.cycle_s for u in instance.uavs}
    battery_violation = {
        u: energy_by_uav[u] - instance.uavs[u].energy_budget_j for u in instance.uavs
    }

    return ReducedResourceEvaluation(
        total_energy_j=sum(energy_by_uav.values()),
        energy_by_uav_j=energy_by_uav,
        upload_time_s=tau,
        task_collect_s=t_collect,
        contact_arrival_s=theta,
        mec_arrival_s=mec_arrival,
        return_time_s=return_time,
        local_start_s=local_start,
        task_completion_s=completion,
        batch_start_s=batch_start,
        batch_finish_s=batch_finish,
        avg_delay_s=avg_delay,
        deadline_violation_s=deadline_violation,
        cycle_violation_s=cycle_violation,
        battery_violation_j=battery_violation,
    )
