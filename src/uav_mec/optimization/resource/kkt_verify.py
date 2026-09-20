from __future__ import annotations

import math
from typing import Any

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id

from .result import ResourceSolveResult


def _dual(result: ResourceSolveResult, name: str) -> float:
    return float(result.stage1_duals.get(name, 0.0) or 0.0)


def _value(group: dict[str, float], key: Any) -> float:
    return float(group[str(key)])


def rate_mbps(b_mhz: float, gamma_mhz_value: float) -> float:
    return b_mhz * math.log2(1.0 + gamma_mhz_value / b_mhz)


def rate_prime(b_mhz: float, gamma_mhz_value: float) -> float:
    g = gamma_mhz_value
    b = b_mhz
    return (math.log(1.0 + g / b) - g / (b + g)) / math.log(2.0)


def psi_prime(data_mbit: float, b_mhz: float, gamma_mhz_value: float) -> float:
    r = rate_mbps(b_mhz, gamma_mhz_value)
    rp = rate_prime(b_mhz, gamma_mhz_value)
    return -data_mbit * rp / (r * r)


def verify_kkt(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    result: ResourceSolveResult,
) -> dict[str, Any]:
    if not result.stage1_values:
        return {"status": "skipped", "reason": "No stage-1 optimum available"}

    vals = result.stage1_values
    report: dict[str, Any] = {
        "local_cpu_stationarity": {},
        "bandwidth_stationarity": {},
        "mec_cpu_stationarity": {},
        "capacity_complementarity": {},
    }

    # Local CPU stationarity.
    for task_id, decision in solution.task_decisions.items():
        if decision.mode is not ExecutionMode.LOCAL:
            continue
        uav_id = info.task_owner[task_id]
        uav = instance.uavs[uav_id]
        task = instance.tasks[task_id]
        f = _value(vals["local_cpu_ghz"], task_id)
        gamma = _dual(result, f"local_complete::{task_id}")
        mu = _dual(result, f"battery::{uav_id}")
        nu_up = _dual(result, f"local_upper::{task_id}")
        nu_low = _dual(result, f"local_lower::{task_id}")
        kappa_scaled = uav.kappa * 1e27
        residual = (
            2.0 * (1.0 + mu) * kappa_scaled * task.workload_gcycles * f
            - gamma * task.workload_gcycles / (f * f)
            + nu_up
            - nu_low
        )
        closed_form = None
        if gamma > 0:
            closed_form = (gamma / (2.0 * (1.0 + mu) * kappa_scaled)) ** (1.0 / 3.0)
            closed_form = min(uav.local_cpu_ghz, closed_form)
        report["local_cpu_stationarity"][task_id] = {
            "f_cvx_ghz": f,
            "gamma_complete": gamma,
            "mu_battery": mu,
            "nu_upper": nu_up,
            "nu_lower": nu_low,
            "stationarity_residual": residual,
            "kkt_closed_form_ghz_if_interior": closed_form,
        }

    # Bandwidth stationarity per active (UAV, MEC) pair.
    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        b = _value(vals["bandwidth_mhz"], pair)
        lam = _dual(result, f"bandwidth_cap::{mec_id}")
        lower = _dual(result, f"b_lower::{uav_id}::{mec_id}")
        sum_term = 0.0
        details = []
        for visit_id in info.contact_order[uav_id]:
            if visit_mec_id(instance, solution, visit_id) != mec_id:
                continue
            phi = _dual(result, f"upload_epi::{visit_id}")
            data_mbit = sum(instance.tasks[t].data_mbit for t in info.batch_tasks[visit_id])
            g = gamma_mhz(instance, solution, visit_id)
            dp = psi_prime(data_mbit, b, g)
            sum_term += phi * dp
            details.append({"visit": visit_id, "phi": phi, "psi_prime": dp})
        residual = lam + sum_term - lower
        report["bandwidth_stationarity"][str(pair)] = {
            "b_cvx_mhz": b,
            "lambda_bandwidth": lam,
            "lower_dual": lower,
            "sum_phi_psi_prime": sum_term,
            "stationarity_residual": residual,
            "contact_terms": details,
        }

    # MEC CPU stationarity.
    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        F = _value(vals["mec_cpu_ghz"], pair)
        lam = _dual(result, f"mec_cpu_cap::{mec_id}")
        lower = _dual(result, f"F_lower::{uav_id}::{mec_id}")
        Xi = 0.0
        terms = []
        for visit_id in info.contact_order[uav_id]:
            if visit_mec_id(instance, solution, visit_id) != mec_id:
                continue
            prefix = 0.0
            for m, task_id in enumerate(info.batch_edf_order[visit_id], start=1):
                prefix += instance.tasks[task_id].workload_gcycles
                gamma_dual = _dual(result, f"mec_task_complete::{visit_id}::{m}::{task_id}")
                Xi += gamma_dual * prefix
                terms.append(
                    {"visit": visit_id, "task": task_id, "gamma": gamma_dual, "prefix_gcycles": prefix}
                )
            total = sum(instance.tasks[t].workload_gcycles for t in info.batch_edf_order[visit_id])
            zeta = _dual(result, f"batch_complete::{visit_id}")
            Xi += zeta * total
            terms.append({"visit": visit_id, "batch_zeta": zeta, "total_gcycles": total})
        residual = lam - Xi / (F * F) - lower
        report["mec_cpu_stationarity"][str(pair)] = {
            "F_cvx_ghz": F,
            "lambda_mec_cpu": lam,
            "lower_dual": lower,
            "Xi": Xi,
            "stationarity_residual": residual,
            "terms": terms,
        }

    for mec_id, mec in instance.mecs.items():
        pairs = [p for p in info.active_uav_mec_pairs if p[1] == mec_id]
        if not pairs:
            continue
        b_sum = sum(_value(vals["bandwidth_mhz"], p) for p in pairs)
        F_sum = sum(_value(vals["mec_cpu_ghz"], p) for p in pairs)
        lb = _dual(result, f"bandwidth_cap::{mec_id}")
        lf = _dual(result, f"mec_cpu_cap::{mec_id}")
        report["capacity_complementarity"][mec_id] = {
            "bandwidth_slack_mhz": mec.bandwidth_mhz - b_sum,
            "lambda_bandwidth": lb,
            "lambda_times_slack_bandwidth": lb * (mec.bandwidth_mhz - b_sum),
            "cpu_slack_ghz": mec.cpu_ghz - F_sum,
            "lambda_cpu": lf,
            "lambda_times_slack_cpu": lf * (mec.cpu_ghz - F_sum),
        }

    residuals: list[float] = []
    for section in ("local_cpu_stationarity", "bandwidth_stationarity", "mec_cpu_stationarity"):
        for item in report[section].values():
            residuals.append(abs(float(item["stationarity_residual"])))
    report["max_abs_stationarity_residual"] = max(residuals) if residuals else 0.0
    report["status"] = "ok"
    return report
