"""Algorithm-independent physical-feasibility admission for task-QoS experiments.

All seven methods use the same deterministic reduction, CPU/bandwidth model
and independent residual audits. Only a *verified* physical solution is emitted.
"""
from __future__ import annotations

from dataclasses import dataclass, replace, field
from time import perf_counter
import math

from uav_mec.algorithms.initial.mec_repair import evaluate_initial_proxy
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.stage1_acceptance import qualify_stage1_result
from uav_mec.domain import DiscreteSolution, Instance, Route, RouteStop, StopType
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import CVXResourceSolver
from uav_mec.optimization.resource.reduced import evaluate_reduced_resources
from uav_mec.optimization.resource.result import ResourceSolveResult


@dataclass
class AdmissionResult:
    instance: Instance
    solution: DiscreteSolution
    resources: ResourceSolveResult | None
    audit: dict | None
    source: str
    removed_reasons: dict[str, str] = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)
    runtime_s: float = 0.0


def project_tasks(instance: Instance, solution: DiscreteSolution,
                  keep: set[str]) -> tuple[Instance, DiscreteSolution]:
    """Drop omitted tasks and now-unused contacts; preserve order and depot legs."""
    if not keep.issubset(instance.tasks):
        raise ValueError("Task subset contains unknown ids")
    active_visits = {d.contact_visit_id for t, d in solution.task_decisions.items()
                     if t in keep and d.contact_visit_id is not None}
    routes = {
        u: Route(u, tuple(stop for stop in route.stops
                         if (stop.kind is StopType.DEPOT or
                             stop.kind is StopType.TASK and stop.ref_id in keep or
                             stop.kind is StopType.CONTACT and stop.ref_id in active_visits)))
        for u, route in solution.routes.items()
    }
    projected = DiscreteSolution(
        routes=routes,
        contact_visits={v: c for v, c in solution.contact_visits.items() if v in active_visits},
        task_decisions={t: d for t, d in solution.task_decisions.items() if t in keep},
        metadata=dict(solution.metadata, admission_tasks=sorted(keep)),
    )
    subset = replace(instance, tasks={t: instance.tasks[t] for t in sorted(keep)})
    validate_solution(subset, projected)
    return subset, projected


def task_removal_order(instance: Instance, solution: DiscreteSolution) -> list[str]:
    """Largest tardiness, delay ratio, marginal detour, MEC pressure, then ID."""
    info = build_event_info(instance, solution)
    proxy = evaluate_initial_proxy(instance, solution)
    delay = {t: proxy.reduced.task_completion_s[t] - instance.tasks[t].release_s
             for t in instance.tasks}
    detours = {}
    full_distance = sum(info.route_distance_m.values())
    for t in sorted(instance.tasks):
        trial_instance, trial_solution = project_tasks(
            instance, solution, set(instance.tasks) - {t})
        detours[t] = max(
            0., full_distance - sum(build_event_info(trial_instance, trial_solution).route_distance_m.values())
        )
    def priority(t: str) -> tuple:
        task = instance.tasks[t]
        normalized_delay = delay[t] / max(1., task.deadline_s)
        tardiness = max(0., normalized_delay - 1.)
        decision = solution.task_decisions[t]
        pressure = 0.
        if decision.contact_visit_id is not None:
            visit = solution.contact_visits[decision.contact_visit_id]
            mec = instance.mecs[instance.contact_points[visit.point_id].mec_id]
            pressure = (task.workload_gcycles / mec.cpu_ghz
                        + task.data_mbit / mec.bandwidth_mhz)
        return (-tardiness, -normalized_delay, -detours[t], -pressure, t)
    return sorted(instance.tasks, key=priority)


def constructive_certificate(instance: Instance, solution: DiscreteSolution
                             ) -> tuple[ResourceSolveResult, dict] | None:
    """Check deterministic equal-share resources; a feasible certificate is real data.

    Used if the conic solver failed numerically or if its Stage-1 residuals failed;
    this is not labeled as CVX optimum and Stage-2 remains unavailable.
    """
    info = build_event_info(instance, solution)
    bw = {}
    cpu = {}
    for e, mec in instance.mecs.items():
        pairs = [pair for pair in info.active_uav_mec_pairs if pair[1] == e]
        for pair in pairs:
            bw[pair] = mec.bandwidth_mhz / len(pairs)
            cpu[pair] = mec.cpu_ghz / len(pairs)
    local_cpu = {t: instance.uavs[u].local_cpu_ghz
                 for u, seq in info.local_order.items() for t in seq}
    reduced = evaluate_reduced_resources(
        instance, solution, info, bandwidth_mhz=bw, mec_cpu_ghz=cpu, local_cpu_ghz=local_cpu)
    values = {
        "tau_s": reduced.upload_time_s,
        "bandwidth_mhz": {str(k): v for k, v in bw.items()},
        "mec_cpu_ghz": {str(k): v for k, v in cpu.items()},
        "local_cpu_ghz": local_cpu,
        "local_start_s": reduced.local_start_s,
        "task_completion_s": reduced.task_completion_s,
        "batch_start_s": reduced.batch_start_s,
        "batch_finish_s": reduced.batch_finish_s,
    }
    audits = audit_both_timelines(instance, solution, values)
    if not all(a["complete"] and a["passed"] for a in audits.values()):
        return None
    energy = audits["reconstructed"]["metrics"]["energy_j"]
    result = ResourceSolveResult(
        status="feasible_constructive", solver="EQUAL_SHARE_CERTIFICATE", is_dcp=True,
        energy_stage1_j=energy, energy_final_j=energy,
        stage1_values=values, final_values=values,
        diagnostics={"stage1_status": "feasible_constructive", "stage1_qualified": False,
                     "stage2_status": "not_run", "stage2_accepted": False,
                     "physical_certificate": True},
    )
    return result, audits


def admit_tasks(instance: Instance, solution: DiscreteSolution, *,
                solver: CVXResourceSolver | None = None) -> AdmissionResult:
    """Return a verified feasible subset, including a legitimate zero-task route.

    A rejected task is never quietly counted as completed. Numerical failure is
    distinguishable from physical infeasibility in the removal trace.
    """
    if instance.qos_hard:
        raise ValueError("Task admission requires soft QoS instance")
    validate_solution(instance, solution)
    resource_solver = solver or CVXResourceSolver(run_stage2=False)
    remaining = set(instance.tasks)
    rejected: dict[str, str] = {}
    attempts: list[dict] = []
    started = perf_counter()
    while remaining:
        partial, reduced_solution = project_tasks(instance, solution, remaining)
        proxy = evaluate_initial_proxy(partial, reduced_solution)
        solved = qualify_stage1_result(
            partial, reduced_solution, resource_solver.solve(partial, reduced_solution))
        diag = solved.diagnostics
        accepted_cvx = bool(diag.get("stage1_qualified", False))
        accepted = None
        source = ""
        if accepted_cvx:
            audit = diag["stage1_acceptance_audit"]
            accepted = solved
            source = "cvx_verified"
        else:
            certified = constructive_certificate(partial, reduced_solution)
            if certified is not None:
                accepted, audit = certified
                source = "constructive_verified"
        attempts.append({
            "remaining_tasks": len(remaining), "stage1_status": diag.get("stage1_status", solved.status),
            "solver_status": solved.status, "source": source or "rejected",
            "physical_proxy_violations": proxy.score.violated_constraints,
            "precheck_reasons": solved.diagnostics.get("precheck_reasons", []),
        })
        if accepted is not None:
            return AdmissionResult(
                partial, reduced_solution, accepted, audit, source,
                rejected, attempts, perf_counter() - started)
        candidate = task_removal_order(partial, reduced_solution)[0]
        reason = str(diag.get("stage1_acceptance_reason") or solved.status)
        rejected[candidate] = f"admission_physical_or_numerical_failure:{reason}"
        remaining.remove(candidate)
    # A depot -> depot itinerary has no flight, task collection, upload or MEC work;
    # this is an explicit, independently structurally valid physical fallback.
    partial, reduced_solution = project_tasks(instance, solution, set())
    info = build_event_info(partial, reduced_solution)
    if any(value > 1e-9 for value in info.base_return_s.values()):
        raise RuntimeError("Idle route unexpectedly has nonzero travel")
    if any(value > 1e-9 for value in info.fixed_flight_energy_j.values()):
        raise RuntimeError("Idle route unexpectedly consumes flight energy")
    attempts.append({"remaining_tasks": 0, "source": "verified_idle", "stage1_status": "not_applicable"})
    return AdmissionResult(
        partial, reduced_solution, None, None, "verified_idle",
        rejected, attempts, perf_counter() - started)
