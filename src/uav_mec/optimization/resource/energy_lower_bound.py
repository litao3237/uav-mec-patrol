"""Cheap, mathematically valid UAV-energy bound for a fixed discrete structure.

This bound is intentionally *optimistic*: a batch may receive its entire
MEC's bandwidth, local CPU may run at the model's tiny lower bound, and all
time/resource competition is ignored. Therefore it cannot substitute for
a feasible continuous allocation or for CVXPY and residual validation.

The current P1-R model in optimization/resource/problem.py uses
f >= 1e-4 GHz, b_(u,e) <= B_e, local energy kappa*1e27*w*f**2,
and hover/transmit energy (P_hover+P_tx)*sum_v tau_v.
"""
from __future__ import annotations

import math

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo, build_event_info, gamma_mhz, visit_mec_id
from uav_mec.optimization.resource.analytic import rate_mbps


def fixed_structure_energy_lower_bound(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo | None = None,
    *,
    min_local_cpu_ghz: float = 1e-4,
) -> float:
    """Return L(D) <= V(D) for *feasible* fixed discrete structures D.

    The rate bound is generous because each batch is given the station's
    entire bandwidth, irrespective of reservations of other UAVs/batches.
    Use a numerical safety margin before pruning; this function does not
    certify a solver's actual numerical optimality or constraint residual.
    """
    if min_local_cpu_ghz <= 0.0:
        raise ValueError("The modeled local CPU lower bound is positive")
    info = info or build_event_info(instance, solution)
    energy = 0.0
    for uav_id, uav in instance.uavs.items():
        energy += (
            info.fixed_flight_energy_j[uav_id]
            + info.fixed_collection_energy_j[uav_id]
        )
        for task_id in info.local_order[uav_id]:
            energy += (
                (uav.kappa * 1e27)
                * instance.tasks[task_id].workload_gcycles
                * min_local_cpu_ghz ** 2
            )
    for visit_id, task_ids in info.batch_tasks.items():
        visit = solution.contact_visits[visit_id]
        mec = instance.mecs[visit_mec_id(instance, solution, visit_id)]
        uav = instance.uavs[visit.uav_id]
        data_mbit = sum(instance.tasks[tid].data_mbit for tid in task_ids)
        rate = rate_mbps(mec.bandwidth_mhz, gamma_mhz(instance, solution, visit_id))
        if rate <= 0.0:
            return float("inf")
        energy += (uav.hover_power_w + uav.tx_power_w) * data_mbit / rate
    return float(energy)


def can_certify_no_meaningful_improvement(
    lower_bound_j: float,
    incumbent_energy_j: float,
    *,
    minimum_gain_j: float = 1.0,
    minimum_gain_relative: float = 1e-4,
    safety_abs_j: float = 0.01,
    safety_rel: float = 1e-7,
) -> bool:
    """Conservative, *optional* candidate filter for later experiments.

    An incumbent is NOT replaced unless its improvement exceeds a threshold
    max(minimum_gain_j, minimum_gain_relative * max(E_current, E_candidate)).
    Since a candidate qualifying under this rule must save at least
    max(minimum_gain_j, minimum_gain_relative * E_current), it is safe to
    reject when even the *optimistic* energy bound cannot clear that
    necessary saving, after subtracting an explicit numerical margin.
    """
    if not (math.isfinite(lower_bound_j) and math.isfinite(incumbent_energy_j)):
        return False
    if lower_bound_j < 0 or incumbent_energy_j <= 0:
        return False
    minimum_saving_j = max(
        minimum_gain_j,
        minimum_gain_relative * max(1.0, incumbent_energy_j),
    )
    tolerance = max(
        safety_abs_j,
        safety_rel * max(1.0, incumbent_energy_j, lower_bound_j),
    )
    return lower_bound_j >= incumbent_energy_j - minimum_saving_j + tolerance
