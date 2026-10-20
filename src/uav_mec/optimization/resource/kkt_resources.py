from __future__ import annotations

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id

from .analytic import (
    allocate_bandwidth_by_kkt,
    allocate_mec_cpu_by_kkt,
    local_cpu_from_shadow_price,
    upload_time_prime,
)
from .kkt_temporal import _TemporalPrices
from .reduced import ReducedResourceEvaluation


def _allocate_resources(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    prices: _TemporalPrices,
    *,
    mu_battery: dict[str, float],
    min_bandwidth_mhz: float,
    min_cpu_ghz: float,
) -> tuple[
    dict[tuple[str, str], float],
    dict[tuple[str, str], float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
]:
    local_cpu: dict[str, float] = {}
    for uav_id, order in info.local_order.items():
        uav = instance.uavs[uav_id]
        kappa_scaled = uav.kappa * 1e27
        for task_id in order:
            local_cpu[task_id] = local_cpu_from_shadow_price(
                prices.local_gamma[task_id],
                kappa_scaled=kappa_scaled,
                battery_price=mu_battery[uav_id],
                max_cpu_ghz=uav.local_cpu_ghz,
                min_cpu_ghz=min_cpu_ghz,
            )

    bandwidth: dict[tuple[str, str], float] = {}
    lambda_b: dict[str, float] = {}
    for mec_id, mec in instance.mecs.items():
        pairs = [pair for pair in info.active_uav_mec_pairs if pair[1] == mec_id]
        if not pairs:
            continue
        terms_by_pair: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
        for pair in pairs:
            uav_id, _ = pair
            terms: list[tuple[float, float, float]] = []
            for visit_id in info.contact_order[uav_id]:
                if visit_mec_id(instance, solution, visit_id) != mec_id:
                    continue
                data_mbit = sum(instance.tasks[t].data_mbit for t in info.batch_tasks[visit_id])
                terms.append(
                    (prices.phi_by_visit[visit_id], data_mbit, gamma_mhz(instance, solution, visit_id))
                )
            terms_by_pair[pair] = terms
        alloc, price = allocate_bandwidth_by_kkt(
            mec.bandwidth_mhz,
            terms_by_pair,
            min_bandwidth_mhz=min_bandwidth_mhz,
        )
        bandwidth.update(alloc)
        lambda_b[mec_id] = price

    mec_cpu: dict[tuple[str, str], float] = {}
    lambda_f: dict[str, float] = {}
    for mec_id, mec in instance.mecs.items():
        pairs = [pair for pair in info.active_uav_mec_pairs if pair[1] == mec_id]
        if not pairs:
            continue
        weights = {pair: prices.xi_by_pair[pair] for pair in pairs}
        alloc, price = allocate_mec_cpu_by_kkt(
            mec.cpu_ghz,
            weights,
            min_cpu_ghz=min_cpu_ghz,
        )
        mec_cpu.update(alloc)
        lambda_f[mec_id] = price

    return bandwidth, mec_cpu, local_cpu, lambda_b, lambda_f


def _initial_resources(
    instance: Instance,
    info: EventInfo,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], dict[str, float]]:
    bandwidth: dict[tuple[str, str], float] = {}
    mec_cpu: dict[tuple[str, str], float] = {}
    for mec_id, mec in instance.mecs.items():
        pairs = [p for p in info.active_uav_mec_pairs if p[1] == mec_id]
        if pairs:
            for pair in pairs:
                bandwidth[pair] = mec.bandwidth_mhz / len(pairs)
                mec_cpu[pair] = mec.cpu_ghz / len(pairs)
    local_cpu = {
        task_id: instance.uavs[info.task_owner[task_id]].local_cpu_ghz
        for order in info.local_order.values()
        for task_id in order
    }
    return bandwidth, mec_cpu, local_cpu


def _is_feasible(
    instance: Instance,
    evaluation: ReducedResourceEvaluation,
    *,
    time_tol: float,
    avg_tol: float,
    energy_tol_j: float,
) -> bool:
    if any(v > time_tol for v in evaluation.deadline_violation_s.values()):
        return False
    if evaluation.avg_delay_s - instance.avg_delay_budget_s > avg_tol:
        return False
    if any(v > time_tol for v in evaluation.cycle_violation_s.values()):
        return False
    if any(v > energy_tol_j for v in evaluation.battery_violation_j.values()):
        return False
    return True


def _snapshot_values(
    evaluation: ReducedResourceEvaluation,
    *,
    bandwidth: dict[tuple[str, str], float],
    mec_cpu: dict[tuple[str, str], float],
    local_cpu: dict[str, float],
) -> dict[str, dict[str, float]]:
    return {
        "tau_s": {str(k): float(v) for k, v in evaluation.upload_time_s.items()},
        "bandwidth_mhz": {str(k): float(v) for k, v in bandwidth.items()},
        "mec_cpu_ghz": {str(k): float(v) for k, v in mec_cpu.items()},
        "local_cpu_ghz": {str(k): float(v) for k, v in local_cpu.items()},
        "local_start_s": {str(k): float(v) for k, v in evaluation.local_start_s.items()},
        "task_completion_s": {str(k): float(v) for k, v in evaluation.task_completion_s.items()},
        "batch_start_s": {str(k): float(v) for k, v in evaluation.batch_start_s.items()},
        "batch_finish_s": {str(k): float(v) for k, v in evaluation.batch_finish_s.items()},
    }


def _build_dual_snapshot(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    evaluation: ReducedResourceEvaluation,
    prices: _TemporalPrices,
    *,
    alpha: dict[str, float],
    beta: float,
    xi_cycle: dict[str, float],
    mu_battery: dict[str, float],
    bandwidth: dict[tuple[str, str], float],
    mec_cpu: dict[tuple[str, str], float],
    local_cpu: dict[str, float],
    lambda_b: dict[str, float],
    lambda_f: dict[str, float],
    min_bandwidth_mhz: float,
    min_cpu_ghz: float,
) -> dict[str, float]:
    duals: dict[str, float] = {}
    for task_id in instance.tasks:
        duals[f"deadline::{task_id}"] = alpha[task_id]
    duals["avg_delay"] = beta
    for uav_id in instance.uavs:
        duals[f"cycle::{uav_id}"] = xi_cycle[uav_id]
        duals[f"battery::{uav_id}"] = mu_battery[uav_id]
    for mec_id in instance.mecs:
        if mec_id in lambda_b:
            duals[f"bandwidth_cap::{mec_id}"] = lambda_b[mec_id]
        if mec_id in lambda_f:
            duals[f"mec_cpu_cap::{mec_id}"] = lambda_f[mec_id]

    for task_id, gamma in prices.local_gamma.items():
        duals[f"local_complete::{task_id}"] = gamma
        duals[f"local_release::{task_id}"] = prices.local_release[task_id]
        duals[f"local_fifo::{task_id}"] = prices.local_queue[task_id]
        uav_id = info.task_owner[task_id]
        uav = instance.uavs[uav_id]
        task = instance.tasks[task_id]
        f = local_cpu[task_id]
        kappa_scaled = uav.kappa * 1e27
        base = (
            2.0 * (1.0 + mu_battery[uav_id]) * kappa_scaled * task.workload_gcycles * f
            - gamma * task.workload_gcycles / (f * f)
        )
        upper = max(0.0, -base) if abs(f - uav.local_cpu_ghz) <= 1e-8 else 0.0
        lower = max(0.0, base) if abs(f - min_cpu_ghz) <= 1e-8 else 0.0
        duals[f"local_upper::{task_id}"] = upper
        duals[f"local_lower::{task_id}"] = lower

    for visit_id, phi in prices.phi_by_visit.items():
        duals[f"upload_epi::{visit_id}"] = phi
        duals[f"batch_arrival::{visit_id}"] = prices.batch_release[visit_id]
        duals[f"batch_fifo::{visit_id}"] = prices.batch_queue[visit_id]
        duals[f"batch_complete::{visit_id}"] = prices.batch_zeta[visit_id]
        for m, task_id in enumerate(info.batch_edf_order[visit_id], start=1):
            duals[f"mec_task_complete::{visit_id}::{m}::{task_id}"] = (
                alpha[task_id] + beta / len(instance.tasks)
            )

    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        b = bandwidth[pair]
        sum_term = 0.0
        for visit_id in info.contact_order[uav_id]:
            if visit_mec_id(instance, solution, visit_id) != mec_id:
                continue
            data = sum(instance.tasks[t].data_mbit for t in info.batch_tasks[visit_id])
            sum_term += prices.phi_by_visit[visit_id] * upload_time_prime(
                data, b, gamma_mhz(instance, solution, visit_id)
            )
        b_base = lambda_b[mec_id] + sum_term
        duals[f"b_lower::{uav_id}::{mec_id}"] = (
            max(0.0, b_base) if abs(b - min_bandwidth_mhz) <= 1e-8 else 0.0
        )

        F = mec_cpu[pair]
        f_base = lambda_f[mec_id] - prices.xi_by_pair[pair] / (F * F)
        duals[f"F_lower::{uav_id}::{mec_id}"] = (
            max(0.0, f_base) if abs(F - min_cpu_ghz) <= 1e-8 else 0.0
        )
    return duals
