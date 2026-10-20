from __future__ import annotations

import math

from uav_mec.domain import DiscreteSolution, Instance, RouteStop, StopType


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def stop_xy(instance: Instance, solution: DiscreteSolution, stop: RouteStop) -> tuple[float, float]:
    if stop.kind is StopType.DEPOT:
        return instance.depot_xy
    if stop.kind is StopType.TASK:
        task = instance.tasks[stop.ref_id]
        return task.x, task.y
    if stop.kind is StopType.CONTACT:
        visit = solution.contact_visits[stop.ref_id]
        point = instance.contact_points[visit.point_id]
        return point.x, point.y
    raise ValueError(f"Unsupported stop type: {stop.kind}")
