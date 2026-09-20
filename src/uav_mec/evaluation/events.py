from __future__ import annotations

from dataclasses import dataclass, field

from uav_mec.domain import DiscreteSolution, ExecutionMode, Instance, StopType

from .geometry import distance, stop_xy
from .validator import validate_solution


@dataclass
class EventInfo:
    task_owner: dict[str, str] = field(default_factory=dict)
    base_collect_complete_s: dict[tuple[str, str], float] = field(default_factory=dict)
    base_contact_arrival_s: dict[tuple[str, str], float] = field(default_factory=dict)
    base_return_s: dict[str, float] = field(default_factory=dict)
    route_distance_m: dict[str, float] = field(default_factory=dict)
    fixed_flight_energy_j: dict[str, float] = field(default_factory=dict)
    fixed_collection_energy_j: dict[str, float] = field(default_factory=dict)
    contact_order: dict[str, list[str]] = field(default_factory=dict)
    prior_contacts_before_task: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    prior_contacts_before_contact: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    local_order: dict[str, list[str]] = field(default_factory=dict)
    batch_tasks: dict[str, list[str]] = field(default_factory=dict)
    batch_edf_order: dict[str, list[str]] = field(default_factory=dict)
    contact_predecessor_same_mec: dict[str, str | None] = field(default_factory=dict)
    active_uav_mec_pairs: list[tuple[str, str]] = field(default_factory=list)


def visit_mec_id(instance: Instance, solution: DiscreteSolution, visit_id: str) -> str:
    visit = solution.contact_visits[visit_id]
    return instance.contact_points[visit.point_id].mec_id


def build_event_info(instance: Instance, solution: DiscreteSolution) -> EventInfo:
    validate_solution(instance, solution)
    info = EventInfo()

    for uav_id, route in solution.routes.items():
        uav = instance.uavs[uav_id]
        base_t = 0.0
        total_dist = 0.0
        contacts_so_far: list[str] = []
        local_tasks: list[str] = []
        contact_order: list[str] = []
        prev_xy = stop_xy(instance, solution, route.stops[0])

        for stop in route.stops[1:]:
            xy = stop_xy(instance, solution, stop)
            dist = distance(prev_xy, xy)
            total_dist += dist
            base_t += dist / uav.speed_mps

            if stop.kind is StopType.TASK:
                task = instance.tasks[stop.ref_id]
                base_t += task.collect_s
                info.task_owner[stop.ref_id] = uav_id
                info.base_collect_complete_s[(uav_id, stop.ref_id)] = base_t
                info.prior_contacts_before_task[(uav_id, stop.ref_id)] = list(contacts_so_far)
                if solution.task_decisions[stop.ref_id].mode is ExecutionMode.LOCAL:
                    local_tasks.append(stop.ref_id)
            elif stop.kind is StopType.CONTACT:
                visit_id = stop.ref_id
                info.base_contact_arrival_s[(uav_id, visit_id)] = base_t
                info.prior_contacts_before_contact[(uav_id, visit_id)] = list(contacts_so_far)
                contacts_so_far.append(visit_id)
                contact_order.append(visit_id)

            prev_xy = xy

        info.base_return_s[uav_id] = base_t
        info.route_distance_m[uav_id] = total_dist
        info.fixed_flight_energy_j[uav_id] = uav.flight_power_w * (total_dist / uav.speed_mps)
        collection_time = sum(instance.tasks[t].collect_s for t in route.task_ids())
        info.fixed_collection_energy_j[uav_id] = uav.hover_power_w * collection_time
        info.contact_order[uav_id] = contact_order
        info.local_order[uav_id] = local_tasks

    for visit_id in solution.contact_visits:
        tasks = [
            task_id
            for task_id, decision in solution.task_decisions.items()
            if decision.mode is ExecutionMode.OFFLOAD and decision.contact_visit_id == visit_id
        ]
        info.batch_tasks[visit_id] = tasks
        info.batch_edf_order[visit_id] = sorted(tasks, key=lambda t: instance.tasks[t].deadline_s)

    active_pairs: set[tuple[str, str]] = set()
    for uav_id, visit_ids in info.contact_order.items():
        last_for_mec: dict[str, str] = {}
        for visit_id in visit_ids:
            mec_id = visit_mec_id(instance, solution, visit_id)
            active_pairs.add((uav_id, mec_id))
            info.contact_predecessor_same_mec[visit_id] = last_for_mec.get(mec_id)
            last_for_mec[mec_id] = visit_id

    info.active_uav_mec_pairs = sorted(active_pairs)
    return info


def format_event_summary(instance: Instance, solution: DiscreteSolution, info: EventInfo) -> str:
    lines = ["=== Fixed discrete solution / base event timeline ==="]
    for uav_id, route in solution.routes.items():
        labels = " -> ".join(route.labels())
        lines.append(f"{uav_id}: {labels}")
        fixed_energy = info.fixed_flight_energy_j[uav_id] + info.fixed_collection_energy_j[uav_id]
        lines.append(
            f"  distance={info.route_distance_m[uav_id]:.1f} m, "
            f"base_return={info.base_return_s[uav_id]:.2f} s, fixed_energy={fixed_energy:.2f} J"
        )
        for task_id in route.task_ids():
            decision = solution.task_decisions[task_id]
            mode = decision.mode.value if decision.contact_visit_id is None else decision.contact_visit_id
            lines.append(
                f"  {task_id}: base_collect={info.base_collect_complete_s[(uav_id, task_id)]:.2f} s, mode={mode}"
            )
        for visit_id in info.contact_order[uav_id]:
            point_id = solution.contact_visits[visit_id].point_id
            mec_id = instance.contact_points[point_id].mec_id
            lines.append(
                f"  {visit_id}: base_arrival={info.base_contact_arrival_s[(uav_id, visit_id)]:.2f} s, "
                f"point={point_id}, MEC={mec_id}, batch={info.batch_tasks[visit_id]}"
            )
    return "\n".join(lines)
