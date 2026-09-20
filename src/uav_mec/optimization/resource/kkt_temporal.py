from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo, build_event_info, gamma_mhz, visit_mec_id

from .analytic import (
    allocate_bandwidth_by_kkt,
    allocate_mec_cpu_by_kkt,
    local_cpu_from_shadow_price,
    upload_time_prime,
)
from .precheck import fast_feasibility_precheck
from .reduced import ReducedResourceEvaluation, evaluate_reduced_resources
from .result import ResourceSolveResult


@dataclass(frozen=True)
class KKTResourceSolverConfig:
    max_iterations: int = 3000
    min_iterations: int = 10
    convergence_patience: int = 10
    feasibility_tol_s: float = 2e-3
    avg_delay_tol_s: float = 2e-3
    energy_tol_j: float = 2e-2
    normalized_complementarity_tol: float = 1e-4
    normalized_subgradient_clip: float = 1.0
    min_bandwidth_mhz: float = 1e-3
    min_cpu_ghz: float = 1e-4
    initial_task_price: float = 1e-3
    task_step: float = 0.018
    average_step: float = 0.018
    cycle_step: float = 20.0
    battery_step: float = 0.5
    step_decay_blocks: float = 30.0
    tie_tol_s: float = 1e-7


@dataclass
class _TemporalPrices:
    local_gamma: dict[str, float]
    local_release: dict[str, float]
    local_queue: dict[str, float]
    batch_delta: dict[str, float]
    batch_release: dict[str, float]
    batch_queue: dict[str, float]
    batch_zeta: dict[str, float]
    xi_by_pair: dict[tuple[str, str], float]
    phi_by_visit: dict[str, float]


def _branch_weights(release_time: float, queue_time: float, *, tol: float) -> tuple[float, float]:
    if release_time > queue_time + tol:
        return 1.0, 0.0
    if queue_time > release_time + tol:
        return 0.0, 1.0
    return 0.5, 0.5


def _temporal_prices(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    evaluation: ReducedResourceEvaluation,
    *,
    alpha: dict[str, float],
    beta: float,
    xi_cycle: dict[str, float],
    mu_battery: dict[str, float],
    tie_tol_s: float,
) -> _TemporalPrices:
    task_weight = {
        task_id: alpha[task_id] + beta / len(instance.tasks)
        for task_id in instance.tasks
    }

    local_gamma: dict[str, float] = {}
    local_release: dict[str, float] = {}
    local_queue: dict[str, float] = {}

    # For each local task, compute whether its start is release-limited or queue-limited.
    local_branch: dict[str, tuple[float, float]] = {}
    for uav_id, order in info.local_order.items():
        for idx, task_id in enumerate(order):
            if idx == 0:
                local_branch[task_id] = (1.0, 0.0)
            else:
                prev = order[idx - 1]
                local_branch[task_id] = _branch_weights(
                    evaluation.task_collect_s[task_id],
                    evaluation.task_completion_s[prev],
                    tol=tie_tol_s,
                )

        downstream = 0.0
        for idx in range(len(order) - 1, -1, -1):
            task_id = order[idx]
            if idx + 1 < len(order):
                next_task = order[idx + 1]
                _, queue_share_next = local_branch[next_task]
                downstream = queue_share_next * local_gamma[next_task]
            else:
                downstream = 0.0
            gamma = task_weight[task_id] + downstream
            release_share, queue_share = local_branch[task_id]
            local_gamma[task_id] = gamma
            local_release[task_id] = release_share * gamma
            local_queue[task_id] = queue_share * gamma

    batch_delta: dict[str, float] = {}
    batch_release: dict[str, float] = {}
    batch_queue: dict[str, float] = {}
    batch_zeta: dict[str, float] = {}
    xi_by_pair = {pair: 0.0 for pair in info.active_uav_mec_pairs}

    # Process one virtual FIFO queue per (UAV, MEC).
    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        visits = [
            v
            for v in info.contact_order[uav_id]
            if visit_mec_id(instance, solution, v) == mec_id
        ]
        branch: dict[str, tuple[float, float]] = {}
        for idx, visit_id in enumerate(visits):
            if idx == 0:
                branch[visit_id] = (1.0, 0.0)
            else:
                prev = visits[idx - 1]
                branch[visit_id] = _branch_weights(
                    evaluation.mec_arrival_s[visit_id],
                    evaluation.batch_finish_s[prev],
                    tol=tie_tol_s,
                )

        for idx in range(len(visits) - 1, -1, -1):
            visit_id = visits[idx]
            if idx + 1 < len(visits):
                next_visit = visits[idx + 1]
                _, queue_share_next = branch[next_visit]
                zeta = queue_share_next * batch_delta[next_visit]
            else:
                zeta = 0.0
            own = sum(task_weight[t] for t in info.batch_edf_order[visit_id])
            delta = own + zeta
            release_share, queue_share = branch[visit_id]
            batch_delta[visit_id] = delta
            batch_release[visit_id] = release_share * delta
            batch_queue[visit_id] = queue_share * delta
            batch_zeta[visit_id] = zeta

            prefix = 0.0
            xi_value = 0.0
            for task_id in info.batch_edf_order[visit_id]:
                prefix += instance.tasks[task_id].workload_gcycles
                xi_value += task_weight[task_id] * prefix
            total_work = prefix
            xi_value += zeta * total_work
            xi_by_pair[pair] += xi_value

    phi_by_visit: dict[str, float] = {}
    for uav_id, visits in info.contact_order.items():
        uav = instance.uavs[uav_id]
        direct = (1.0 + mu_battery[uav_id]) * (
            uav.hover_power_w + uav.tx_power_w
        )
        for idx, visit_id in enumerate(visits):
            phi = direct + xi_cycle[uav_id]
            # This upload stop delays later task collection times.
            for task_id in info.local_order[uav_id]:
                if visit_id in info.prior_contacts_before_task[(uav_id, task_id)]:
                    phi += local_release[task_id]
            # tau_h is included in the MEC arrival of contact h and every later contact.
            for later_visit in visits[idx:]:
                phi += batch_release[later_visit]
            phi_by_visit[visit_id] = phi

    return _TemporalPrices(
        local_gamma=local_gamma,
        local_release=local_release,
        local_queue=local_queue,
        batch_delta=batch_delta,
        batch_release=batch_release,
        batch_queue=batch_queue,
        batch_zeta=batch_zeta,
        xi_by_pair=xi_by_pair,
        phi_by_visit=phi_by_visit,
    )
