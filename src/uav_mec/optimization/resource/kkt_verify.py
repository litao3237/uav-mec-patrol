from __future__ import annotations

import math
from typing import Any

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance
from uav_mec.evaluation import EventInfo, gamma_mhz, visit_mec_id

from .reduced import evaluate_reduced_resources
from .result import ResourceSolveResult


_MIN_BANDWIDTH_MHZ = 1e-3
_MIN_CPU_GHZ = 1e-4


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


def _upload_time(data_mbit: float, b_mhz: float, gamma_mhz_value: float) -> float:
    return data_mbit / rate_mbps(b_mhz, gamma_mhz_value)


def _stage1_resource_maps(
    info: EventInfo,
    vals: dict[str, dict[str, float]],
) -> tuple[
    dict[tuple[str, str], float],
    dict[tuple[str, str], float],
    dict[str, float],
]:
    bandwidth = {
        pair: _value(vals["bandwidth_mhz"], pair)
        for pair in info.active_uav_mec_pairs
    }
    mec_cpu = {
        pair: _value(vals["mec_cpu_ghz"], pair)
        for pair in info.active_uav_mec_pairs
    }
    local_cpu = {
        task_id: _value(vals["local_cpu_ghz"], task_id)
        for order in info.local_order.values()
        for task_id in order
    }
    return bandwidth, mec_cpu, local_cpu


def _record_complementarity(
    report: dict[str, Any],
    *,
    name: str,
    dual: float,
    slack: float,
) -> None:
    product = dual * slack
    report["complementarity"][name] = {
        "dual": dual,
        "slack": slack,
        "dual_times_slack": product,
    }


def verify_kkt(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    result: ResourceSolveResult,
) -> dict[str, Any]:
    """Verify the complete KKT picture for a Stage-1 resource solution.

    Earlier versions focused on stationarity only. That is necessary but not
    sufficient: a dual iterate can satisfy stationarity while still violating
    complementarity (for example, a positive deadline price on a slack task).
    This verifier therefore reports four blocks:

    1. primal feasibility,
    2. dual feasibility,
    3. complementarity,
    4. stationarity.

    The residuals have different physical units, so they should not be merged
    into a single mathematical norm. They are exposed separately for diagnosis.
    """

    if not result.stage1_values:
        return {"status": "skipped", "reason": "No stage-1 optimum available"}

    vals = result.stage1_values
    bandwidth, mec_cpu, local_cpu = _stage1_resource_maps(info, vals)
    reduced = evaluate_reduced_resources(
        instance,
        solution,
        info,
        bandwidth_mhz=bandwidth,
        mec_cpu_ghz=mec_cpu,
        local_cpu_ghz=local_cpu,
    )

    report: dict[str, Any] = {
        "local_cpu_stationarity": {},
        "bandwidth_stationarity": {},
        "mec_cpu_stationarity": {},
        "primal_feasibility": {},
        "dual_feasibility": {},
        "complementarity": {},
        "capacity_complementarity": {},
    }

    # ------------------------------------------------------------------
    # Primal feasibility + complementarity for task/QoS constraints.
    # ------------------------------------------------------------------
    completion = {
        task_id: _value(vals["task_completion_s"], task_id)
        for task_id in instance.tasks
    }

    for task_id, task in instance.tasks.items():
        delay = completion[task_id] - task.release_s
        slack = task.deadline_s - delay
        dual = _dual(result, f"deadline::{task_id}")
        report["primal_feasibility"][f"deadline::{task_id}"] = {
            "slack": slack,
            "violation": max(0.0, -slack),
        }
        _record_complementarity(
            report,
            name=f"deadline::{task_id}",
            dual=dual,
            slack=slack,
        )

    avg_delay = sum(
        completion[t] - instance.tasks[t].release_s
        for t in instance.tasks
    ) / len(instance.tasks)
    avg_slack = instance.avg_delay_budget_s - avg_delay
    avg_dual = _dual(result, "avg_delay")
    report["primal_feasibility"]["avg_delay"] = {
        "slack": avg_slack,
        "violation": max(0.0, -avg_slack),
    }
    _record_complementarity(
        report,
        name="avg_delay",
        dual=avg_dual,
        slack=avg_slack,
    )

    for uav_id, uav in instance.uavs.items():
        cycle_slack = instance.cycle_s - reduced.return_time_s[uav_id]
        cycle_dual = _dual(result, f"cycle::{uav_id}")
        report["primal_feasibility"][f"cycle::{uav_id}"] = {
            "slack": cycle_slack,
            "violation": max(0.0, -cycle_slack),
        }
        _record_complementarity(
            report,
            name=f"cycle::{uav_id}",
            dual=cycle_dual,
            slack=cycle_slack,
        )

        battery_slack = uav.energy_budget_j - reduced.energy_by_uav_j[uav_id]
        battery_dual = _dual(result, f"battery::{uav_id}")
        report["primal_feasibility"][f"battery::{uav_id}"] = {
            "slack": battery_slack,
            "violation": max(0.0, -battery_slack),
        }
        _record_complementarity(
            report,
            name=f"battery::{uav_id}",
            dual=battery_dual,
            slack=battery_slack,
        )

    # ------------------------------------------------------------------
    # Local FIFO constraints.
    # ------------------------------------------------------------------
    for uav_id, order in info.local_order.items():
        uav = instance.uavs[uav_id]
        for idx, task_id in enumerate(order):
            f = _value(vals["local_cpu_ghz"], task_id)
            start = _value(vals["local_start_s"], task_id)
            task = instance.tasks[task_id]

            release_slack = start - reduced.task_collect_s[task_id]
            release_dual = _dual(result, f"local_release::{task_id}")
            report["primal_feasibility"][f"local_release::{task_id}"] = {
                "slack": release_slack,
                "violation": max(0.0, -release_slack),
            }
            _record_complementarity(
                report,
                name=f"local_release::{task_id}",
                dual=release_dual,
                slack=release_slack,
            )

            if idx > 0:
                prev = order[idx - 1]
                fifo_slack = start - completion[prev]
                fifo_dual = _dual(result, f"local_fifo::{task_id}")
                report["primal_feasibility"][f"local_fifo::{task_id}"] = {
                    "slack": fifo_slack,
                    "violation": max(0.0, -fifo_slack),
                }
                _record_complementarity(
                    report,
                    name=f"local_fifo::{task_id}",
                    dual=fifo_dual,
                    slack=fifo_slack,
                )

            complete_slack = completion[task_id] - start - task.workload_gcycles / f
            complete_dual = _dual(result, f"local_complete::{task_id}")
            report["primal_feasibility"][f"local_complete::{task_id}"] = {
                "slack": complete_slack,
                "violation": max(0.0, -complete_slack),
            }
            _record_complementarity(
                report,
                name=f"local_complete::{task_id}",
                dual=complete_dual,
                slack=complete_slack,
            )

            upper_slack = uav.local_cpu_ghz - f
            upper_dual = _dual(result, f"local_upper::{task_id}")
            _record_complementarity(
                report,
                name=f"local_upper::{task_id}",
                dual=upper_dual,
                slack=upper_slack,
            )
            lower_slack = f - _MIN_CPU_GHZ
            lower_dual = _dual(result, f"local_lower::{task_id}")
            _record_complementarity(
                report,
                name=f"local_lower::{task_id}",
                dual=lower_dual,
                slack=lower_slack,
            )

    # ------------------------------------------------------------------
    # Upload epigraphs and MEC FIFO/EDF constraints.
    # ------------------------------------------------------------------
    for visit_id, edf_tasks in info.batch_edf_order.items():
        visit = solution.contact_visits[visit_id]
        mec_id = visit_mec_id(instance, solution, visit_id)
        pair = (visit.uav_id, mec_id)
        b = bandwidth[pair]
        F = mec_cpu[pair]
        tau = _value(vals["tau_s"], visit_id)
        data_mbit = sum(instance.tasks[t].data_mbit for t in info.batch_tasks[visit_id])
        upload_required = _upload_time(
            data_mbit,
            b,
            gamma_mhz(instance, solution, visit_id),
        )
        upload_slack = tau - upload_required
        upload_dual = _dual(result, f"upload_epi::{visit_id}")
        report["primal_feasibility"][f"upload_epi::{visit_id}"] = {
            "slack": upload_slack,
            "violation": max(0.0, -upload_slack),
        }
        _record_complementarity(
            report,
            name=f"upload_epi::{visit_id}",
            dual=upload_dual,
            slack=upload_slack,
        )

        batch_start = _value(vals["batch_start_s"], visit_id)
        batch_finish = _value(vals["batch_finish_s"], visit_id)

        arrival_slack = batch_start - reduced.mec_arrival_s[visit_id]
        arrival_dual = _dual(result, f"batch_arrival::{visit_id}")
        report["primal_feasibility"][f"batch_arrival::{visit_id}"] = {
            "slack": arrival_slack,
            "violation": max(0.0, -arrival_slack),
        }
        _record_complementarity(
            report,
            name=f"batch_arrival::{visit_id}",
            dual=arrival_dual,
            slack=arrival_slack,
        )

        pred = info.contact_predecessor_same_mec[visit_id]
        if pred is not None:
            pred_finish = _value(vals["batch_finish_s"], pred)
            fifo_slack = batch_start - pred_finish
            fifo_dual = _dual(result, f"batch_fifo::{visit_id}")
            report["primal_feasibility"][f"batch_fifo::{visit_id}"] = {
                "slack": fifo_slack,
                "violation": max(0.0, -fifo_slack),
            }
            _record_complementarity(
                report,
                name=f"batch_fifo::{visit_id}",
                dual=fifo_dual,
                slack=fifo_slack,
            )

        prefix = 0.0
        for m, task_id in enumerate(edf_tasks, start=1):
            prefix += instance.tasks[task_id].workload_gcycles
            task_slack = completion[task_id] - batch_start - prefix / F
            task_dual = _dual(
                result,
                f"mec_task_complete::{visit_id}::{m}::{task_id}",
            )
            report["primal_feasibility"][
                f"mec_task_complete::{visit_id}::{m}::{task_id}"
            ] = {
                "slack": task_slack,
                "violation": max(0.0, -task_slack),
            }
            _record_complementarity(
                report,
                name=f"mec_task_complete::{visit_id}::{m}::{task_id}",
                dual=task_dual,
                slack=task_slack,
            )

        total_work = prefix
        batch_complete_slack = batch_finish - batch_start - total_work / F
        batch_complete_dual = _dual(result, f"batch_complete::{visit_id}")
        report["primal_feasibility"][f"batch_complete::{visit_id}"] = {
            "slack": batch_complete_slack,
            "violation": max(0.0, -batch_complete_slack),
        }
        _record_complementarity(
            report,
            name=f"batch_complete::{visit_id}",
            dual=batch_complete_dual,
            slack=batch_complete_slack,
        )

    # ------------------------------------------------------------------
    # Capacity/lower-bound complementarity.
    # ------------------------------------------------------------------
    for mec_id, mec in instance.mecs.items():
        pairs = [p for p in info.active_uav_mec_pairs if p[1] == mec_id]
        if not pairs:
            continue

        b_sum = sum(bandwidth[p] for p in pairs)
        F_sum = sum(mec_cpu[p] for p in pairs)
        b_slack = mec.bandwidth_mhz - b_sum
        F_slack = mec.cpu_ghz - F_sum
        lb = _dual(result, f"bandwidth_cap::{mec_id}")
        lf = _dual(result, f"mec_cpu_cap::{mec_id}")

        report["primal_feasibility"][f"bandwidth_cap::{mec_id}"] = {
            "slack": b_slack,
            "violation": max(0.0, -b_slack),
        }
        report["primal_feasibility"][f"mec_cpu_cap::{mec_id}"] = {
            "slack": F_slack,
            "violation": max(0.0, -F_slack),
        }
        _record_complementarity(
            report,
            name=f"bandwidth_cap::{mec_id}",
            dual=lb,
            slack=b_slack,
        )
        _record_complementarity(
            report,
            name=f"mec_cpu_cap::{mec_id}",
            dual=lf,
            slack=F_slack,
        )
        report["capacity_complementarity"][mec_id] = {
            "bandwidth_slack_mhz": b_slack,
            "lambda_bandwidth": lb,
            "lambda_times_slack_bandwidth": lb * b_slack,
            "cpu_slack_ghz": F_slack,
            "lambda_cpu": lf,
            "lambda_times_slack_cpu": lf * F_slack,
        }

        for pair in pairs:
            uav_id, _ = pair
            b_lower_slack = bandwidth[pair] - _MIN_BANDWIDTH_MHZ
            b_lower_dual = _dual(result, f"b_lower::{uav_id}::{mec_id}")
            _record_complementarity(
                report,
                name=f"b_lower::{uav_id}::{mec_id}",
                dual=b_lower_dual,
                slack=b_lower_slack,
            )

            F_lower_slack = mec_cpu[pair] - _MIN_CPU_GHZ
            F_lower_dual = _dual(result, f"F_lower::{uav_id}::{mec_id}")
            _record_complementarity(
                report,
                name=f"F_lower::{uav_id}::{mec_id}",
                dual=F_lower_dual,
                slack=F_lower_slack,
            )

    # ------------------------------------------------------------------
    # Dual feasibility.
    # ------------------------------------------------------------------
    for name, dual in result.stage1_duals.items():
        dual_value = float(dual or 0.0)
        report["dual_feasibility"][name] = {
            "dual": dual_value,
            "violation": max(0.0, -dual_value),
        }

    # ------------------------------------------------------------------
    # Stationarity: retain the original targeted equations.
    # ------------------------------------------------------------------
    for task_id, decision in solution.task_decisions.items():
        if decision.mode is not ExecutionMode.LOCAL:
            continue
        uav_id = info.task_owner[task_id]
        uav = instance.uavs[uav_id]
        task = instance.tasks[task_id]
        f = local_cpu[task_id]
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

    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        b = bandwidth[pair]
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

    for pair in info.active_uav_mec_pairs:
        uav_id, mec_id = pair
        F = mec_cpu[pair]
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
                    {
                        "visit": visit_id,
                        "task": task_id,
                        "gamma": gamma_dual,
                        "prefix_gcycles": prefix,
                    }
                )
            total = sum(
                instance.tasks[t].workload_gcycles
                for t in info.batch_edf_order[visit_id]
            )
            zeta = _dual(result, f"batch_complete::{visit_id}")
            Xi += zeta * total
            terms.append(
                {
                    "visit": visit_id,
                    "batch_zeta": zeta,
                    "total_gcycles": total,
                }
            )
        residual = lam - Xi / (F * F) - lower
        report["mec_cpu_stationarity"][str(pair)] = {
            "F_cvx_ghz": F,
            "lambda_mec_cpu": lam,
            "lower_dual": lower,
            "Xi": Xi,
            "stationarity_residual": residual,
            "terms": terms,
        }

    stationarity_residuals: list[float] = []
    for section in (
        "local_cpu_stationarity",
        "bandwidth_stationarity",
        "mec_cpu_stationarity",
    ):
        for item in report[section].values():
            stationarity_residuals.append(
                abs(float(item["stationarity_residual"]))
            )

    primal_violations = [
        float(item["violation"])
        for item in report["primal_feasibility"].values()
    ]
    dual_violations = [
        float(item["violation"])
        for item in report["dual_feasibility"].values()
    ]
    complementarity = [
        abs(float(item["dual_times_slack"]))
        for item in report["complementarity"].values()
    ]

    report["max_abs_stationarity_residual"] = (
        max(stationarity_residuals) if stationarity_residuals else 0.0
    )
    report["max_primal_violation"] = max(primal_violations) if primal_violations else 0.0
    report["max_dual_violation"] = max(dual_violations) if dual_violations else 0.0
    report["max_abs_complementarity"] = max(complementarity) if complementarity else 0.0

    top = sorted(
        (
            {
                "name": name,
                "dual": float(item["dual"]),
                "slack": float(item["slack"]),
                "dual_times_slack": float(item["dual_times_slack"]),
            }
            for name, item in report["complementarity"].items()
        ),
        key=lambda item: abs(item["dual_times_slack"]),
        reverse=True,
    )
    report["top_complementarity"] = top[:10]
    report["status"] = "ok"
    return report
