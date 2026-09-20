from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cvxpy as cp

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id


@dataclass
class CvxResourceModel:
    variables: dict[str, dict[Any, Any]]
    constraints: list[Any]
    named_constraints: dict[str, Any]
    total_energy: Any
    avg_delay_expr: Any
    return_time: dict[str, Any]
    normalized_mec_cpu: Any


def build_resource_model(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
) -> CvxResourceModel:
    """Build the convex P1-R model for a fixed discrete solution.

    Numerical units:
    - bandwidth: MHz
    - CPU: GHz
    - workload: Gcycles
    - data: Mbit
    - time: seconds
    - energy: joules
    """

    named: dict[str, Any] = {}
    constraints: list[Any] = []

    def cvx_sum(terms: list[Any] | tuple[Any, ...]) -> Any:
        """Return a scalar CVXPY expression even when *terms* is empty.

        Python/NumPy scalars are convenient in event construction, but a
        comparison between two plain scalars produces a Python ``bool`` rather
        than a CVXPY Constraint.  Keeping zero/constant branches as
        ``cp.Constant`` prevents contactless/idle UAV routes from leaking bools
        into ``model.constraints`` and ``named_constraints``.
        """

        expr: Any = cp.Constant(0.0)
        for term in terms:
            expr = expr + term
        return expr

    def add(name: str, con: Any) -> Any:
        # Defensive normalization.  The model builder should normally create
        # CVXPY constraints directly, but constant-only branches (for example a
        # UAV with no MEC contact) can otherwise evaluate ``float <= float`` in
        # Python and yield bool.  Preserve the exact feasibility meaning while
        # ensuring every registered item exposes ``dual_value``.
        if isinstance(con, bool):
            con = cp.Constant(0.0 if con else 1.0) <= 0.0
        if not hasattr(con, "dual_value"):
            raise TypeError(
                f"Named constraint {name!r} is not a CVXPY constraint: "
                f"{type(con).__name__}"
            )
        constraints.append(con)
        named[name] = con
        return con

    tau = {visit_id: cp.Variable(nonneg=True, name=f"tau_{visit_id}") for visit_id in info.batch_tasks}
    b = {
        pair: cp.Variable(nonneg=True, name=f"b_{pair[0]}_{pair[1]}")
        for pair in info.active_uav_mec_pairs
    }
    F = {
        pair: cp.Variable(nonneg=True, name=f"F_{pair[0]}_{pair[1]}")
        for pair in info.active_uav_mec_pairs
    }

    local_tasks = [
        task_id
        for task_id, decision in solution.task_decisions.items()
        if decision.mode is ExecutionMode.LOCAL
    ]
    f_local = {task_id: cp.Variable(nonneg=True, name=f"fU_{task_id}") for task_id in local_tasks}
    s_local = {task_id: cp.Variable(nonneg=True, name=f"sU_{task_id}") for task_id in local_tasks}
    c_task = {task_id: cp.Variable(nonneg=True, name=f"c_{task_id}") for task_id in instance.tasks}
    S_batch = {visit_id: cp.Variable(nonneg=True, name=f"SE_{visit_id}") for visit_id in info.batch_tasks}
    C_batch = {visit_id: cp.Variable(nonneg=True, name=f"CE_{visit_id}") for visit_id in info.batch_tasks}

    variables = {
        "tau_s": tau,
        "bandwidth_mhz": b,
        "mec_cpu_ghz": F,
        "local_cpu_ghz": f_local,
        "local_start_s": s_local,
        "task_completion_s": c_task,
        "batch_start_s": S_batch,
        "batch_finish_s": C_batch,
    }

    min_bw_mhz = 1e-3
    min_cpu_ghz = 1e-4
    ln2 = math.log(2.0)

    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        add(f"b_lower::{uav_id}::{mec_id}", min_bw_mhz - b[pair] <= 0)
        add(f"F_lower::{uav_id}::{mec_id}", min_cpu_ghz - F[pair] <= 0)

    # Upload-time epigraphs.
    for visit_id, batch in info.batch_tasks.items():
        visit = solution.contact_visits[visit_id]
        mec_id = visit_mec_id(instance, solution, visit_id)
        pair = (visit.uav_id, mec_id)
        gamma = gamma_mhz(instance, solution, visit_id)
        # -rel_entr(b, b+gamma) = b*ln(1+gamma/b).
        rate_mbps = -cp.rel_entr(b[pair], b[pair] + gamma) / ln2
        data_mbit = sum(instance.tasks[t].data_mbit for t in batch)
        upload_time = data_mbit * cp.inv_pos(rate_mbps)
        add(f"upload_epi::{visit_id}", upload_time - tau[visit_id] <= 0)

    # MEC capacities.
    for mec_id, mec in instance.mecs.items():
        active_pairs = [pair for pair in info.active_uav_mec_pairs if pair[1] == mec_id]
        if not active_pairs:
            continue
        add(
            f"bandwidth_cap::{mec_id}",
            cp.sum([b[pair] for pair in active_pairs]) - mec.bandwidth_mhz <= 0,
        )
        add(
            f"mec_cpu_cap::{mec_id}",
            cp.sum([F[pair] for pair in active_pairs]) - mec.cpu_ghz <= 0,
        )

    # Affine event times.
    t_collect: dict[str, Any] = {}
    theta_contact: dict[str, Any] = {}
    arrival_mec: dict[str, Any] = {}
    return_time: dict[str, Any] = {}

    for task_id in instance.tasks:
        uav_id = info.task_owner[task_id]
        prior = info.prior_contacts_before_task[(uav_id, task_id)]
        base = cp.Constant(float(info.base_collect_complete_s[(uav_id, task_id)]))
        t_collect[task_id] = base + cvx_sum([tau[v] for v in prior])

    for uav_id, visit_ids in info.contact_order.items():
        for visit_id in visit_ids:
            prior = info.prior_contacts_before_contact[(uav_id, visit_id)]
            base = cp.Constant(float(info.base_contact_arrival_s[(uav_id, visit_id)]))
            theta_contact[visit_id] = base + cvx_sum([tau[v] for v in prior])
            arrival_mec[visit_id] = theta_contact[visit_id] + tau[visit_id]
        return_time[uav_id] = cp.Constant(float(info.base_return_s[uav_id])) + cvx_sum(
            [tau[v] for v in visit_ids]
        )

    # Local FIFO queues.
    for uav_id, order in info.local_order.items():
        uav = instance.uavs[uav_id]
        for idx, task_id in enumerate(order):
            task = instance.tasks[task_id]
            add(f"local_release::{task_id}", t_collect[task_id] - s_local[task_id] <= 0)
            if idx > 0:
                prev = order[idx - 1]
                add(f"local_fifo::{task_id}", c_task[prev] - s_local[task_id] <= 0)
            add(
                f"local_complete::{task_id}",
                s_local[task_id]
                + task.workload_gcycles * cp.inv_pos(f_local[task_id])
                - c_task[task_id]
                <= 0,
            )
            add(f"local_upper::{task_id}", f_local[task_id] - uav.local_cpu_ghz <= 0)
            add(f"local_lower::{task_id}", 1e-4 - f_local[task_id] <= 0)

    # MEC virtual queues: FIFO across batches per (UAV,MEC), EDF within a batch.
    for visit_id, edf_tasks in info.batch_edf_order.items():
        visit = solution.contact_visits[visit_id]
        mec_id = visit_mec_id(instance, solution, visit_id)
        pair = (visit.uav_id, mec_id)
        add(f"batch_arrival::{visit_id}", arrival_mec[visit_id] - S_batch[visit_id] <= 0)
        pred = info.contact_predecessor_same_mec[visit_id]
        if pred is not None:
            add(f"batch_fifo::{visit_id}", C_batch[pred] - S_batch[visit_id] <= 0)

        prefix = 0.0
        for m, task_id in enumerate(edf_tasks, start=1):
            prefix += instance.tasks[task_id].workload_gcycles
            add(
                f"mec_task_complete::{visit_id}::{m}::{task_id}",
                S_batch[visit_id] + prefix * cp.inv_pos(F[pair]) - c_task[task_id] <= 0,
            )

        total_work = sum(instance.tasks[t].workload_gcycles for t in edf_tasks)
        add(
            f"batch_complete::{visit_id}",
            S_batch[visit_id] + total_work * cp.inv_pos(F[pair]) - C_batch[visit_id] <= 0,
        )

    # QoS.
    for task_id, task in instance.tasks.items():
        add(f"deadline::{task_id}", c_task[task_id] - task.release_s - task.deadline_s <= 0)

    avg_delay_expr = cvx_sum(
        [c_task[t] - instance.tasks[t].release_s for t in instance.tasks]
    ) / len(instance.tasks)
    add("avg_delay", avg_delay_expr - instance.avg_delay_budget_s <= 0)

    for uav_id in instance.uavs:
        add(f"cycle::{uav_id}", return_time[uav_id] - instance.cycle_s <= 0)

    # UAV energy.
    energy_by_uav: dict[str, Any] = {}
    for uav_id, uav in instance.uavs.items():
        fixed = info.fixed_flight_energy_j[uav_id] + info.fixed_collection_energy_j[uav_id]
        local_energy_terms = []
        for task_id in info.local_order[uav_id]:
            task = instance.tasks[task_id]
            kappa_scaled = uav.kappa * 1e27
            local_energy_terms.append(kappa_scaled * task.workload_gcycles * cp.square(f_local[task_id]))
        offload_terms = [
            (uav.hover_power_w + uav.tx_power_w) * tau[visit_id]
            for visit_id in info.contact_order[uav_id]
        ]
        energy_expr: Any = cp.Constant(float(fixed))
        energy_expr = energy_expr + cvx_sum(local_energy_terms) + cvx_sum(offload_terms)
        energy_by_uav[uav_id] = energy_expr
        add(f"battery::{uav_id}", energy_expr - uav.energy_budget_j <= 0)

    total_energy = cvx_sum([energy_by_uav[u] for u in instance.uavs])
    normalized_mec_cpu = cvx_sum(
        [F[pair] / instance.mecs[pair[1]].cpu_ghz for pair in info.active_uav_mec_pairs]
    )

    return CvxResourceModel(
        variables=variables,
        constraints=constraints,
        named_constraints=named,
        total_energy=total_energy,
        avg_delay_expr=avg_delay_expr,
        return_time=return_time,
        normalized_mec_cpu=normalized_mec_cpu,
    )
