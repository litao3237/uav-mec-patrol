from __future__ import annotations

from collections import defaultdict

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance, StopType

from .geometry import distance


class SolutionValidationError(ValueError):
    pass


def validate_solution(instance: Instance, solution: DiscreteSolution) -> None:
    if set(solution.routes) != set(instance.uavs):
        missing = set(instance.uavs) - set(solution.routes)
        extra = set(solution.routes) - set(instance.uavs)
        raise SolutionValidationError(f"Route/UAV mismatch: missing={missing}, extra={extra}")

    seen_tasks: dict[str, str] = {}
    task_owner: dict[str, str] = {}
    visit_position: dict[str, tuple[str, int]] = {}
    task_position: dict[str, tuple[str, int]] = {}
    active_visits: set[str] = set()

    for uav_id, route in solution.routes.items():
        if route.uav_id != uav_id:
            raise SolutionValidationError(f"Route key {uav_id} does not match route.uav_id={route.uav_id}")
        if len(route.stops) < 2:
            raise SolutionValidationError(f"Route {uav_id} must contain at least two depot stops")
        if route.stops[0].kind is not StopType.DEPOT or route.stops[-1].kind is not StopType.DEPOT:
            raise SolutionValidationError(f"Route {uav_id} must start and end at depot")

        contact_count = 0
        for idx, stop in enumerate(route.stops[1:-1], start=1):
            if stop.kind is StopType.TASK:
                task_id = stop.ref_id
                if task_id not in instance.tasks:
                    raise SolutionValidationError(f"Unknown task {task_id}")
                if task_id in seen_tasks:
                    raise SolutionValidationError(
                        f"Task {task_id} appears in both {seen_tasks[task_id]} and {uav_id}"
                    )
                seen_tasks[task_id] = uav_id
                task_owner[task_id] = uav_id
                task_position[task_id] = (uav_id, idx)
            elif stop.kind is StopType.CONTACT:
                visit_id = stop.ref_id
                if visit_id not in solution.contact_visits:
                    raise SolutionValidationError(f"Unknown contact visit {visit_id}")
                visit = solution.contact_visits[visit_id]
                if visit.uav_id != uav_id:
                    raise SolutionValidationError(
                        f"Contact visit {visit_id} belongs to {visit.uav_id}, not {uav_id}"
                    )
                if visit.point_id not in instance.contact_points:
                    raise SolutionValidationError(f"Unknown contact point {visit.point_id}")
                point = instance.contact_points[visit.point_id]
                mec = instance.mecs[point.mec_id]
                if distance((point.x, point.y), (mec.x, mec.y)) > mec.radius_m + 1e-9:
                    raise SolutionValidationError(
                        f"Contact point {point.point_id} lies outside MEC {mec.mec_id} coverage"
                    )
                if visit_id in active_visits:
                    raise SolutionValidationError(f"Contact visit {visit_id} appears more than once")
                active_visits.add(visit_id)
                visit_position[visit_id] = (uav_id, idx)
                contact_count += 1
            else:
                raise SolutionValidationError("Depot is only allowed at route boundaries")

        if contact_count > instance.max_contacts_per_uav:
            raise SolutionValidationError(
                f"UAV {uav_id} has {contact_count} contacts, exceeding Hmax={instance.max_contacts_per_uav}"
            )

    if set(seen_tasks) != set(instance.tasks):
        missing = set(instance.tasks) - set(seen_tasks)
        extra = set(seen_tasks) - set(instance.tasks)
        raise SolutionValidationError(f"Tasks must appear exactly once: missing={missing}, extra={extra}")

    if set(solution.task_decisions) != set(instance.tasks):
        missing = set(instance.tasks) - set(solution.task_decisions)
        extra = set(solution.task_decisions) - set(instance.tasks)
        raise SolutionValidationError(f"Task decisions mismatch: missing={missing}, extra={extra}")

    if set(solution.contact_visits) != active_visits:
        inactive = set(solution.contact_visits) - active_visits
        missing = active_visits - set(solution.contact_visits)
        raise SolutionValidationError(f"Contact visit mismatch: inactive={inactive}, missing={missing}")

    batch_counts: defaultdict[str, int] = defaultdict(int)
    for task_id, decision in solution.task_decisions.items():
        if decision.mode is ExecutionMode.LOCAL:
            if decision.contact_visit_id is not None:
                raise SolutionValidationError(f"Local task {task_id} cannot reference a contact visit")
            continue

        if decision.mode is not ExecutionMode.OFFLOAD or not decision.contact_visit_id:
            raise SolutionValidationError(f"Invalid decision for task {task_id}: {decision}")

        visit_id = decision.contact_visit_id
        if visit_id not in active_visits:
            raise SolutionValidationError(f"Task {task_id} references inactive contact visit {visit_id}")

        owner = task_owner[task_id]
        visit_uav, visit_idx = visit_position[visit_id]
        task_uav, task_idx = task_position[task_id]
        if owner != visit_uav or task_uav != visit_uav:
            raise SolutionValidationError(
                f"Task {task_id} and contact {visit_id} must belong to the same UAV"
            )
        if task_idx >= visit_idx:
            raise SolutionValidationError(
                f"Store-carry-offload violated: task {task_id} must appear before contact {visit_id}"
            )
        batch_counts[visit_id] += 1

    for visit_id in active_visits:
        if batch_counts[visit_id] == 0:
            raise SolutionValidationError(f"Active contact visit {visit_id} serves no tasks")
