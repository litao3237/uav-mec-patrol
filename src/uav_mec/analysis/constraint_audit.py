"""独立数值残差核验：直接计算物理约束，不以求解器状态代替可行性。"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import math
from statistics import mean

import numpy as np

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import build_event_info, gamma_mhz, visit_mec_id
from uav_mec.evaluation.validator import SolutionValidationError
from uav_mec.optimization.resource.reduced import evaluate_reduced_resources


@dataclass(frozen=True)
class AuditTolerance:
    """按物理单位冻结容差；对所有方法/阶段使用相同规则，禁止按结果放宽。"""

    relative: float = 1e-6
    time_s: float = 1e-4
    energy_j: float = 1e-3
    bandwidth_mhz: float = 1e-6
    cpu_ghz: float = 1e-7


def _failure(reason: str) -> dict:
    return {"complete": False, "passed": False, "reason": reason,
            "max_normalized_violation": None, "constraints": []}


def audit_resources(instance: Instance, solution: DiscreteSolution, values: dict,
                    *, energy_limit_j: float | None = None,
                    tolerance: AuditTolerance | None = None) -> dict:
    """核验全部连续约束和变量适用集合，同时返回可复核的逐任务时序与能耗。

    values必须是一个阶段的完整变量快照。能耗保护只在Stage-2指定；
    已保存变量与最早可行时序分别核验，不能用重建值掩盖原始变量违约。
    """
    tol = tolerance or AuditTolerance()
    if any(t.release_s != 0 for t in instance.tasks.values()):
        return _failure("当前核验模型限定为r_i=0")
    try:
        info = build_event_info(instance, solution)
    except (SolutionValidationError, KeyError) as exc:
        return _failure(f"离散合法性失败：{exc}")
    expected = {
        "tau_s": set(info.batch_tasks),
        "bandwidth_mhz": {str(p) for p in info.active_uav_mec_pairs},
        "mec_cpu_ghz": {str(p) for p in info.active_uav_mec_pairs},
        "local_cpu_ghz": {t for ts in info.local_order.values() for t in ts},
        "local_start_s": {t for ts in info.local_order.values() for t in ts},
        "task_completion_s": set(instance.tasks),
        "batch_start_s": set(info.batch_tasks),
        "batch_finish_s": set(info.batch_tasks),
    }
    if set(values) != set(expected):
        return _failure("变量组缺失或多余")
    for group, keys in expected.items():
        if set(values[group]) != keys:
            return _failure(f"变量适用集合不一致：{group}")
        if any(v is None or not math.isfinite(float(v)) for v in values[group].values()):
            return _failure(f"变量不是有限数：{group}")
    b = {ast.literal_eval(k): float(v) for k, v in values["bandwidth_mhz"].items()}
    cpu = {ast.literal_eval(k): float(v) for k, v in values["mec_cpu_ghz"].items()}
    f = values["local_cpu_ghz"]
    if any(v <= 0 for group in (b, cpu, f) for v in group.values()):
        return _failure("通信/计算资源非正，无法计算倒数约束")
    tau, starts, completion = (values[g] for g in ("tau_s", "local_start_s", "task_completion_s"))
    batch_start, batch_finish = (values[g] for g in ("batch_start_s", "batch_finish_s"))
    constraints = []

    def add(name: str, signed: float, unit: str, scale: float) -> None:
        absolute = {"s": tol.time_s, "J": tol.energy_j,
                    "MHz": tol.bandwidth_mhz, "GHz": tol.cpu_ghz}[unit]
        denominator = absolute + tol.relative * abs(scale)
        constraints.append({"id": name, "unit": unit, "signed_residual": float(signed),
                            "violation": max(0.0, float(signed)), "scale": float(scale),
                            "tolerance": denominator,
                            "normalized_violation": max(0.0, float(signed)) / denominator})

    # CVXPY的非负属性不出现在named_constraints中，需要额外逐变量核验。
    for group, mapping in values.items():
        for key, value in mapping.items():
            if group in ("bandwidth_mhz", "mec_cpu_ghz"):
                mec = instance.mecs[ast.literal_eval(key)[1]]
                unit, scale = (("MHz", mec.bandwidth_mhz) if group == "bandwidth_mhz"
                               else ("GHz", mec.cpu_ghz))
            elif group == "local_cpu_ghz":
                unit, scale = "GHz", instance.uavs[info.task_owner[key]].local_cpu_ghz
            else:
                unit, scale = "s", instance.cycle_s
            add(f"nonnegative::{group}::{key}", -value, unit, scale)
    for u, e in info.active_uav_mec_pairs:
        add(f"b_lower::{u}::{e}", 1e-3 - b[u, e], "MHz", 1e-3)
        add(f"F_lower::{u}::{e}", 1e-4 - cpu[u, e], "GHz", 1e-4)
    for e, mec in instance.mecs.items():
        pairs = [p for p in info.active_uav_mec_pairs if p[1] == e]
        if pairs:
            add(f"bandwidth_cap::{e}", sum(b[p] for p in pairs) - mec.bandwidth_mhz,
                "MHz", mec.bandwidth_mhz)
            add(f"mec_cpu_cap::{e}", sum(cpu[p] for p in pairs) - mec.cpu_ghz, "GHz", mec.cpu_ghz)

    collect = {t: info.base_collect_complete_s[u, t] + sum(tau[v] for v in
               info.prior_contacts_before_task[u, t]) for t, u in info.task_owner.items()}
    contact_arrival = {v: info.base_contact_arrival_s[u, v] + sum(tau[p] for p in
                       info.prior_contacts_before_contact[u, v])
                       for u, visits in info.contact_order.items() for v in visits}
    returns = {u: info.base_return_s[u] + sum(tau[v] for v in visits)
               for u, visits in info.contact_order.items()}
    for v, tasks in info.batch_tasks.items():
        u, e = solution.contact_visits[v].uav_id, visit_mec_id(instance, solution, v)
        rate = b[u, e] * math.log1p(gamma_mhz(instance, solution, v) / b[u, e]) / math.log(2)
        needed = sum(instance.tasks[t].data_mbit for t in tasks) / rate
        add(f"upload_epi::{v}", needed - tau[v], "s", instance.cycle_s)
        add(f"batch_arrival::{v}", contact_arrival[v] + tau[v] - batch_start[v], "s", instance.cycle_s)
        pred = info.contact_predecessor_same_mec[v]
        if pred is not None:
            add(f"batch_fifo::{v}", batch_finish[pred] - batch_start[v], "s", instance.cycle_s)
        work = 0.0
        for index, t in enumerate(info.batch_edf_order[v], 1):
            work += instance.tasks[t].workload_gcycles
            add(f"mec_task_complete::{v}::{index}::{t}",
                batch_start[v] + work / cpu[u, e] - completion[t], "s", instance.cycle_s)
        add(f"batch_complete::{v}", batch_start[v] + work / cpu[u, e] - batch_finish[v],
            "s", instance.cycle_s)
    for u, tasks in info.local_order.items():
        for index, t in enumerate(tasks):
            add(f"local_release::{t}", collect[t] - starts[t], "s", instance.cycle_s)
            if index:
                add(f"local_fifo::{t}", completion[tasks[index - 1]] - starts[t], "s", instance.cycle_s)
            add(f"local_complete::{t}", starts[t] + instance.tasks[t].workload_gcycles / f[t]
                - completion[t], "s", instance.cycle_s)
            add(f"local_lower::{t}", 1e-4 - f[t], "GHz", 1e-4)
            add(f"local_upper::{t}", f[t] - instance.uavs[u].local_cpu_ghz,
                "GHz", instance.uavs[u].local_cpu_ghz)
    for t, task in instance.tasks.items():
        add(f"deadline::{t}", completion[t] - task.release_s - task.deadline_s, "s", task.deadline_s)
    delays = {t: completion[t] - instance.tasks[t].release_s for t in instance.tasks}
    add("avg_delay", mean(delays.values()) - instance.avg_delay_budget_s, "s", instance.avg_delay_budget_s)
    energy_by_uav = {}
    components = {"flight_j": sum(info.fixed_flight_energy_j.values()),
                  "collection_j": sum(info.fixed_collection_energy_j.values()),
                  "upload_hover_j": 0.0, "transmit_j": 0.0, "local_compute_j": 0.0}
    for u, uav in instance.uavs.items():
        hover = sum(uav.hover_power_w * tau[v] for v in info.contact_order[u])
        transmit = sum(uav.tx_power_w * tau[v] for v in info.contact_order[u])
        local = sum(uav.kappa * 1e27 * instance.tasks[t].workload_gcycles * f[t] ** 2
                    for t in info.local_order[u])
        energy_by_uav[u] = info.fixed_flight_energy_j[u] + info.fixed_collection_energy_j[u] + hover + transmit + local
        components["upload_hover_j"] += hover
        components["transmit_j"] += transmit
        components["local_compute_j"] += local
        add(f"cycle::{u}", returns[u] - instance.cycle_s, "s", instance.cycle_s)
        add(f"battery::{u}", energy_by_uav[u] - uav.energy_budget_j, "J", uav.energy_budget_j)
    energy = sum(energy_by_uav.values())
    if energy_limit_j is not None:
        if not math.isfinite(energy_limit_j):
            return _failure("Stage-2能耗保护上限非有限数")
        add("stage2_energy_guard", energy - energy_limit_j, "J", energy_limit_j)
    worst = max(constraints, key=lambda c: c["normalized_violation"])
    carrying = {t: contact_arrival[d.contact_visit_id] - collect[t]
                for t, d in solution.task_decisions.items() if d.contact_visit_id is not None}
    metrics = {
        "energy_j": energy, "energy_components_j": components, "energy_by_uav_j": energy_by_uav,
        "normalized_mec_cpu": sum(cpu[p] / instance.mecs[p[1]].cpu_ghz for p in cpu),
        "cpu_occupation_by_mec": {e: sum(cpu[p] for p in cpu if p[1] == e) / mec.cpu_ghz
                                  for e, mec in instance.mecs.items()},
        "active_mecs": sorted({p[1] for p in cpu}),
        "total_distance_m": sum(info.route_distance_m.values()), "contacts": len(tau),
        "offloaded_tasks": len(carrying), "offload_ratio": len(carrying) / len(instance.tasks),
        "mean_delay_s": mean(delays.values()), "p95_delay_s": float(np.quantile(list(delays.values()), .95)),
        "min_deadline_slack_s": min(instance.tasks[t].deadline_s - delays[t] for t in delays),
        "mean_carrying_wait_s": mean(carrying.values()) if carrying else None,
        "carrying_wait_status": "available" if carrying else "not_applicable_all_local",
    }
    return {"complete": True, "passed": worst["normalized_violation"] <= 1.0,
            "max_normalized_violation": worst["normalized_violation"], "worst_constraint": worst["id"],
            "tolerance": asdict(tol), "constraints": constraints, "metrics": metrics,
            "timeline": {"task_collect_s": collect, "contact_arrival_s": contact_arrival,
                         "return_time_s": returns, "task_delay_s": delays,
                         "carrying_wait_s": carrying, "batch_tasks": info.batch_tasks,
                         "batch_edf_order": info.batch_edf_order}}


def audit_both_timelines(instance: Instance, solution: DiscreteSolution, values: dict,
                         *, energy_limit_j: float | None = None) -> dict:
    """分别核验保存变量和从资源重建的最早时序；缺失/失败不可替换成成功阶段。"""
    saved = audit_resources(instance, solution, values, energy_limit_j=energy_limit_j)
    if not saved["complete"]:
        return {"saved": saved, "reconstructed": _failure("原始快照不完整，未重建")}
    info = build_event_info(instance, solution)
    reduced = evaluate_reduced_resources(
        instance, solution, info,
        bandwidth_mhz={ast.literal_eval(k): v for k, v in values["bandwidth_mhz"].items()},
        mec_cpu_ghz={ast.literal_eval(k): v for k, v in values["mec_cpu_ghz"].items()},
        local_cpu_ghz=values["local_cpu_ghz"],
    )
    rebuilt = dict(values, tau_s=reduced.upload_time_s, local_start_s=reduced.local_start_s,
                   task_completion_s=reduced.task_completion_s, batch_start_s=reduced.batch_start_s,
                   batch_finish_s=reduced.batch_finish_s)
    return {"saved": saved, "reconstructed": audit_resources(instance, solution, rebuilt,
                                                            energy_limit_j=energy_limit_j)}
