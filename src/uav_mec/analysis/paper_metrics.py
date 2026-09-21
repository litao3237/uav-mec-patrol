from __future__ import annotations

import ast
from statistics import mean
from typing import Any

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance
from uav_mec.evaluation import EventInfo, build_event_info, visit_mec_id
from uav_mec.optimization.resource.reduced import (
    evaluate_reduced_resources,
)
from uav_mec.optimization.resource.result import ResourceSolveResult


def _pair_group(
    values: dict[str, float],
) -> dict[tuple[str, str], float]:
    parsed: dict[tuple[str, str], float] = {}
    for raw_key, value in values.items():
        key = ast.literal_eval(raw_key)
        if not (
            isinstance(key, tuple)
            and len(key) == 2
            and all(isinstance(item, str) for item in key)
        ):
            raise ValueError(f"Expected pair resource key, got {raw_key!r}")
        parsed[(key[0], key[1])] = float(value)
    return parsed


def _task_group(values: dict[str, float]) -> dict[str, float]:
    return {str(key): float(value) for key, value in values.items()}


def build_paper_metrics(
    instance: Instance,
    solution: DiscreteSolution,
    result: ResourceSolveResult,
    *,
    info: EventInfo | None = None,
    reference_distance_m: float | None = None,
) -> dict[str, Any]:
    """Build one consistent paper-facing metric record.

    The supplied ResourceSolveResult should normally come from the lexicographic
    CVX solve (Stage 1: minimum UAV energy; Stage 2: minimum normalized MEC CPU
    under the Stage-1 energy guard). CPU utilization is therefore reproducible.
    Bandwidth utilization is descriptive for that CPU-minimizing realization,
    but is not a minimum-bandwidth certificate. Resource bottleneck claims
    should use the Stage-1 capacity shadow prices reported below.
    """

    if not result.feasible:
        raise ValueError("Paper metrics require a feasible resource solution")

    info = info or build_event_info(instance, solution)
    values = result.final_values
    required = {
        "bandwidth_mhz",
        "mec_cpu_ghz",
        "local_cpu_ghz",
    }
    missing = required.difference(values)
    if missing:
        raise ValueError(
            f"Resource result missing final value groups: {sorted(missing)}"
        )

    bandwidth = _pair_group(values["bandwidth_mhz"])
    mec_cpu = _pair_group(values["mec_cpu_ghz"])
    local_cpu = _task_group(values["local_cpu_ghz"])

    reduced = evaluate_reduced_resources(
        instance,
        solution,
        info,
        bandwidth_mhz=bandwidth,
        mec_cpu_ghz=mec_cpu,
        local_cpu_ghz=local_cpu,
    )

    deadline_slack_s = {
        task_id: (
            instance.tasks[task_id].release_s
            + instance.tasks[task_id].deadline_s
            - reduced.task_completion_s[task_id]
        )
        for task_id in instance.tasks
    }

    bandwidth_utilization_by_mec: dict[str, float] = {}
    cpu_utilization_by_mec: dict[str, float] = {}
    active_mecs: list[str] = []
    for mec_id, mec in instance.mecs.items():
        bw_used = sum(
            value
            for (uav_id, pair_mec_id), value in bandwidth.items()
            if pair_mec_id == mec_id
        )
        cpu_used = sum(
            value
            for (uav_id, pair_mec_id), value in mec_cpu.items()
            if pair_mec_id == mec_id
        )
        bandwidth_utilization_by_mec[mec_id] = (
            bw_used / mec.bandwidth_mhz
        )
        cpu_utilization_by_mec[mec_id] = cpu_used / mec.cpu_ghz
        if any(pair[1] == mec_id for pair in info.active_uav_mec_pairs):
            active_mecs.append(mec_id)

    offloaded_tasks_by_mec = {mec_id: 0 for mec_id in instance.mecs}
    contacts_by_mec = {mec_id: 0 for mec_id in instance.mecs}
    for visit_id in solution.contact_visits:
        contacts_by_mec[
            visit_mec_id(instance, solution, visit_id)
        ] += 1
    for task_id, decision in solution.task_decisions.items():
        if decision.mode is not ExecutionMode.OFFLOAD:
            continue
        if decision.contact_visit_id is None:
            raise ValueError(
                f"Offloaded task {task_id} has no contact visit"
            )
        offloaded_tasks_by_mec[
            visit_mec_id(
                instance,
                solution,
                decision.contact_visit_id,
            )
        ] += 1

    total_distance_m = sum(info.route_distance_m.values())
    fixed_energy_j = sum(
        info.fixed_flight_energy_j[uav_id]
        + info.fixed_collection_energy_j[uav_id]
        for uav_id in instance.uavs
    )
    communication_energy_j = sum(
        (
            instance.uavs[
                solution.contact_visits[visit_id].uav_id
            ].hover_power_w
            + instance.uavs[
                solution.contact_visits[visit_id].uav_id
            ].tx_power_w
        )
        * upload_time
        for visit_id, upload_time in reduced.upload_time_s.items()
    )
    local_compute_energy_j = (
        reduced.total_energy_j
        - fixed_energy_j
        - communication_energy_j
    )

    active_bw = [
        bandwidth_utilization_by_mec[mec_id]
        for mec_id in active_mecs
    ]
    active_cpu = [
        cpu_utilization_by_mec[mec_id]
        for mec_id in active_mecs
    ]

    bandwidth_shadow_price_by_mec = {
        mec_id: max(
            0.0,
            float(
                result.stage1_duals.get(
                    f"bandwidth_cap::{mec_id}",
                    0.0,
                )
            ),
        )
        for mec_id in instance.mecs
    }
    cpu_shadow_price_by_mec = {
        mec_id: max(
            0.0,
            float(
                result.stage1_duals.get(
                    f"mec_cpu_cap::{mec_id}",
                    0.0,
                )
            ),
        )
        for mec_id in instance.mecs
    }
    energy_scale = max(1e-12, float(result.energy_stage1_j))
    bandwidth_relative_shadow_by_mec = {
        mec_id: (
            bandwidth_shadow_price_by_mec[mec_id]
            * instance.mecs[mec_id].bandwidth_mhz
            / energy_scale
        )
        for mec_id in instance.mecs
    }
    cpu_relative_shadow_by_mec = {
        mec_id: (
            cpu_shadow_price_by_mec[mec_id]
            * instance.mecs[mec_id].cpu_ghz
            / energy_scale
        )
        for mec_id in instance.mecs
    }
    active_bw_shadow = [
        bandwidth_relative_shadow_by_mec[mec_id]
        for mec_id in active_mecs
    ]
    active_cpu_shadow = [
        cpu_relative_shadow_by_mec[mec_id]
        for mec_id in active_mecs
    ]

    offloaded = sum(offloaded_tasks_by_mec.values())
    route_detour_pct = None
    if reference_distance_m is not None:
        route_detour_pct = (
            100.0
            * (total_distance_m - reference_distance_m)
            / max(1.0, abs(reference_distance_m))
        )

    stage1_status = str(
        result.diagnostics.get("stage1_status", result.status)
    )
    stage2_status = str(
        result.diagnostics.get("stage2_status", "unknown")
    )

    return {
        "stage1_status": stage1_status,
        "stage2_status": stage2_status,
        "energy_stage1_j": float(result.energy_stage1_j),
        "energy_final_j": float(result.energy_final_j),
        "avg_delay_s": float(reduced.avg_delay_s),
        "avg_delay_budget_s": float(instance.avg_delay_budget_s),
        "avg_delay_utilization": (
            reduced.avg_delay_s / instance.avg_delay_budget_s
        ),
        "mean_deadline_slack_s": mean(deadline_slack_s.values()),
        "min_deadline_slack_s": min(deadline_slack_s.values()),
        "max_deadline_slack_s": max(deadline_slack_s.values()),
        "max_return_time_s": max(reduced.return_time_s.values()),
        "max_cycle_utilization": max(
            value / instance.cycle_s
            for value in reduced.return_time_s.values()
        ),
        "max_battery_utilization": max(
            reduced.energy_by_uav_j[uav_id]
            / instance.uavs[uav_id].energy_budget_j
            for uav_id in instance.uavs
        ),
        "total_distance_m": total_distance_m,
        "route_detour_pct_vs_reference": route_detour_pct,
        "offloaded_tasks": offloaded,
        "offload_ratio": offloaded / max(1, len(instance.tasks)),
        "contacts": len(solution.contact_visits),
        "contacts_per_uav": (
            len(solution.contact_visits) / max(1, len(instance.uavs))
        ),
        "active_uav_mec_pairs": len(info.active_uav_mec_pairs),
        "active_mecs": active_mecs,
        "offloaded_tasks_by_mec": offloaded_tasks_by_mec,
        "contacts_by_mec": contacts_by_mec,
        "bandwidth_utilization_by_mec": bandwidth_utilization_by_mec,
        "cpu_utilization_by_mec": cpu_utilization_by_mec,
        "mean_active_mec_bandwidth_utilization": (
            mean(active_bw) if active_bw else 0.0
        ),
        "max_active_mec_bandwidth_utilization": (
            max(active_bw) if active_bw else 0.0
        ),
        "mean_active_mec_cpu_utilization": (
            mean(active_cpu) if active_cpu else 0.0
        ),
        "max_active_mec_cpu_utilization": (
            max(active_cpu) if active_cpu else 0.0
        ),
        "bandwidth_utilization_is_minimal_certificate": False,
        "bandwidth_shadow_price_by_mec": bandwidth_shadow_price_by_mec,
        "cpu_shadow_price_by_mec": cpu_shadow_price_by_mec,
        "bandwidth_relative_shadow_by_mec": (
            bandwidth_relative_shadow_by_mec
        ),
        "cpu_relative_shadow_by_mec": cpu_relative_shadow_by_mec,
        "mean_active_mec_bandwidth_relative_shadow": (
            mean(active_bw_shadow) if active_bw_shadow else 0.0
        ),
        "max_active_mec_bandwidth_relative_shadow": (
            max(active_bw_shadow) if active_bw_shadow else 0.0
        ),
        "mean_active_mec_cpu_relative_shadow": (
            mean(active_cpu_shadow) if active_cpu_shadow else 0.0
        ),
        "max_active_mec_cpu_relative_shadow": (
            max(active_cpu_shadow) if active_cpu_shadow else 0.0
        ),
        "active_mec_bandwidth_shadow_count": sum(
            value > 1e-8 for value in active_bw_shadow
        ),
        "active_mec_cpu_shadow_count": sum(
            value > 1e-8 for value in active_cpu_shadow
        ),
        "fixed_energy_j": fixed_energy_j,
        "fixed_energy_ratio": (
            fixed_energy_j / max(1e-12, reduced.total_energy_j)
        ),
        "communication_energy_j": communication_energy_j,
        "communication_energy_ratio": (
            communication_energy_j
            / max(1e-12, reduced.total_energy_j)
        ),
        "local_compute_energy_j": local_compute_energy_j,
        "local_compute_energy_ratio": (
            local_compute_energy_j
            / max(1e-12, reduced.total_energy_j)
        ),
    }
