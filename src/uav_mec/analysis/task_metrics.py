"""Cohort-complete, task-level experiment statistics for the soft QoS protocol."""
from __future__ import annotations

from statistics import mean
import math
import numpy as np

from uav_mec.domain import Instance
from uav_mec.evaluation.task_objective import ON_TIME_TOL_S


REQUIRED_TASK_QOS_FIELDS = (
    "physical_feasible", "served_tasks", "success_rate",
    "mean_delay_all", "mean_delay_success", "p95_delay_all",
    "deadline_violation_rate", "stage1_energy", "stage2_energy",
    "route_distance", "mec_cpu_utilization", "runtime",
    "strict_all_tasks_success",
)


def summarize_task_qos(original: Instance, *,
                       served_ids: set[str], delays_s: dict[str, float],
                       unserved_reasons: dict[str, str], energy_stage1: float,
                       energy_stage2: float | None, total_energy: float,
                       route_distance_m: float, cpu_utilization: float,
                       runtime_s: float, energy_source: str) -> dict:
    total = len(original.tasks)
    if total == 0:
        raise ValueError("Task-level rates require a nonempty planned instance")
    if served_ids != set(delays_s):
        raise ValueError("Served tasks must have measured completion delays")
    if served_ids | set(unserved_reasons) != set(original.tasks):
        raise ValueError("Every planned task must be served or explicitly rejected")
    if served_ids & set(unserved_reasons):
        raise ValueError("Task cannot be both served and rejected")
    for value in [*delays_s.values(), energy_stage1, total_energy,
                  route_distance_m, cpu_utilization, runtime_s]:
        if not math.isfinite(value) or value < -1e-8:
            raise ValueError("Metrics require finite nonnegative physical measurements")
    if energy_stage2 is not None and not math.isfinite(energy_stage2):
        raise ValueError("Stage-2 energy must be finite when available")

    on_time = {t for t, delay in delays_s.items()
               if delay <= original.tasks[t].deadline_s + ON_TIME_TOL_S}
    late = served_ids - on_time
    successes = len(on_time)
    # Unserved tasks have no completion time. Cycle-end is an explicit
    # right-censoring/surrogate convention for all-task plots, not a measurement.
    all_delay = [delays_s.get(t, original.cycle_s) for t in sorted(original.tasks)]
    successful_delays = [delays_s[t] for t in sorted(on_time)]
    outcomes = {}
    for t in sorted(original.tasks):
        task = original.tasks[t]
        if t not in served_ids:
            outcomes[t] = {"status": "unserved", "delay_s": None, "deadline_s": task.deadline_s,
                           "tardiness_s": None, "reason": unserved_reasons[t]}
        else:
            delay = delays_s[t]
            outcomes[t] = {"status": "on_time" if t in on_time else "late",
                           "delay_s": float(delay), "deadline_s": task.deadline_s,
                           "tardiness_s": max(0., delay - task.deadline_s),
                           "reason": None if t in on_time else "deadline_missed"}
    return {
        "physical_feasible": True,
        "planned_tasks": total,
        "served_tasks": len(served_ids),
        "on_time_tasks": successes,
        "late_tasks": len(late),
        "unserved_tasks": total - len(served_ids),
        "success_rate": successes / total,
        "mean_delay_all": float(mean(all_delay)),
        "mean_delay_success": float(mean(successful_delays)) if successful_delays else None,
        "mean_delay_success_status": "defined" if successful_delays else "undefined_no_success",
        "p95_delay_all": float(np.quantile(all_delay, .95)),
        "deadline_violation_rate": len(late) / total,
        "unserved_rate": (total - len(served_ids)) / total,
        "failure_rate": 1.0 - successes / total,
        "stage1_energy": float(energy_stage1),
        "stage2_energy": float(energy_stage2) if energy_stage2 is not None else None,
        "total_energy": float(total_energy),
        "energy_per_successful_task": total_energy / successes if successes else None,
        "energy_per_success_status": "defined" if successes else "undefined_no_success",
        "energy_source": energy_source,
        "route_distance": float(route_distance_m),
        "mec_cpu_utilization": float(cpu_utilization),
        "runtime": float(runtime_s),
        "strict_all_tasks_success": successes == total and not unserved_reasons,
        "task_outcomes": outcomes,
        "all_task_delay_policy": "served_measured_unserved_right_censored_at_cycle_s",
    }
