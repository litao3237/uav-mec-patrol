from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from uav_mec.domain import (
    ContactVisit,
    DiscreteSolution,
    ExecutionMode,
    Instance,
    Route,
    RouteStop,
    StopType,
    TaskDecision,
)
from uav_mec.evaluation.geometry import distance, stop_xy
from uav_mec.evaluation.validator import validate_solution

from .greedy import build_greedy_initial_solution
from .mec_repair import ProxyEvaluation, evaluate_initial_proxy


@dataclass(frozen=True)
class NearestMECFixedRouteConfig:
    """Fixed-route nearest-MEC offloading heuristic.

    The task-to-UAV assignment and task visit order are frozen. The heuristic
    may only reuse/insert MEC contacts and switch selected tasks from Local to
    MEC execution. For each task, MEC choice is purely geometric: the nearest
    MEC center is used, without heterogeneous CPU/bandwidth-aware selection.
    """

    max_steps: int = 24
    critical_task_limit: int = 12
    improvement_tolerance: float = 1e-12


def _task_owner(solution: DiscreteSolution, task_id: str) -> str:
    return next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )


def _positions(route: Route) -> tuple[dict[str, int], dict[str, int]]:
    task_pos: dict[str, int] = {}
    contact_pos: dict[str, int] = {}
    for idx, stop in enumerate(route.stops):
        if stop.kind is StopType.TASK:
            task_pos[stop.ref_id] = idx
        elif stop.kind is StopType.CONTACT:
            contact_pos[stop.ref_id] = idx
    return task_pos, contact_pos


def _next_visit_id(solution: DiscreteSolution, uav_id: str) -> str:
    prefix = f"N_{uav_id}_"
    used = {
        visit_id
        for visit_id in solution.contact_visits
        if visit_id.startswith(prefix)
    }
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"


def _nearest_mec_id(instance: Instance, task_id: str) -> str:
    task = instance.tasks[task_id]
    task_xy = (task.x, task.y)
    return min(
        instance.mecs,
        key=lambda mec_id: (
            distance(
                task_xy,
                (
                    instance.mecs[mec_id].x,
                    instance.mecs[mec_id].y,
                ),
            ),
            mec_id,
        ),
    )


def _critical_local_tasks(
    instance: Instance,
    solution: DiscreteSolution,
    proxy: ProxyEvaluation,
    *,
    limit: int,
) -> list[str]:
    ranked: list[tuple[tuple[float, float, float, str], str]] = []
    for task_id, decision in solution.task_decisions.items():
        if decision.mode is not ExecutionMode.LOCAL:
            continue
        task = instance.tasks[task_id]
        violation = max(
            0.0,
            proxy.reduced.deadline_violation_s[task_id],
        )
        completion = proxy.reduced.task_completion_s[task_id]
        completion_ratio = (
            completion - task.release_s
        ) / max(1.0, task.deadline_s)
        workload_pressure = (
            task.workload_gcycles / max(1.0, task.deadline_s)
        )
        ranked.append(
            (
                (
                    violation / max(1.0, task.deadline_s),
                    completion_ratio,
                    workload_pressure,
                    task_id,
                ),
                task_id,
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [task_id for _, task_id in ranked[:limit]]


def _strictly_better(
    candidate,
    incumbent,
    *,
    tolerance: float,
) -> bool:
    if candidate.violated_constraints != incumbent.violated_constraints:
        return candidate.violated_constraints < incumbent.violated_constraints

    for a, b in zip(candidate.key[1:], incumbent.key[1:]):
        scale = max(1.0, abs(a), abs(b))
        if a < b - tolerance * scale:
            return True
        if a > b + tolerance * scale:
            return False
    return False


def _existing_nearest_mec_contacts_after_task(
    instance: Instance,
    solution: DiscreteSolution,
    task_id: str,
    mec_id: str,
) -> list[str]:
    owner = _task_owner(solution, task_id)
    route = solution.routes[owner]
    task_pos, contact_pos = _positions(route)
    return [
        visit_id
        for visit_id, pos in sorted(
            contact_pos.items(),
            key=lambda item: item[1],
        )
        if (
            pos > task_pos[task_id]
            and instance.contact_points[
                solution.contact_visits[visit_id].point_id
            ].mec_id
            == mec_id
        )
    ]


def _reuse_contact(
    instance: Instance,
    solution: DiscreteSolution,
    *,
    task_id: str,
    visit_id: str,
) -> DiscreteSolution:
    candidate = deepcopy(solution)
    candidate.task_decisions[task_id] = TaskDecision.offload(visit_id)
    validate_solution(instance, candidate)
    return candidate


def _best_nearest_mec_contact_insertion(
    instance: Instance,
    solution: DiscreteSolution,
    *,
    task_id: str,
    mec_id: str,
) -> tuple[float, str, int] | None:
    owner = _task_owner(solution, task_id)
    route = solution.routes[owner]
    task_pos, _ = _positions(route)
    task_idx = task_pos[task_id]

    best: tuple[float, float, str, int] | None = None
    task = instance.tasks[task_id]
    task_xy = (task.x, task.y)

    for point_id, point in instance.contact_points.items():
        if point.mec_id != mec_id:
            continue

        point_xy = (point.x, point.y)
        task_to_point = distance(task_xy, point_xy)

        for insert_pos in range(task_idx + 1, len(route.stops)):
            prev_xy = stop_xy(
                instance,
                solution,
                route.stops[insert_pos - 1],
            )
            next_xy = stop_xy(
                instance,
                solution,
                route.stops[insert_pos],
            )
            detour = (
                distance(prev_xy, point_xy)
                + distance(point_xy, next_xy)
                - distance(prev_xy, next_xy)
            )
            key = (
                task_to_point,
                detour,
                point_id,
                insert_pos,
            )
            if best is None or key < best:
                best = key

    if best is None:
        return None
    _, detour, point_id, insert_pos = best
    return detour, point_id, insert_pos


def _insert_contact(
    instance: Instance,
    solution: DiscreteSolution,
    *,
    task_id: str,
    point_id: str,
    insert_pos: int,
) -> DiscreteSolution:
    candidate = deepcopy(solution)
    owner = _task_owner(candidate, task_id)
    visit_id = _next_visit_id(candidate, owner)
    route = candidate.routes[owner]
    stops = list(route.stops)
    stops.insert(insert_pos, RouteStop.contact(visit_id))
    candidate.routes[owner] = Route(owner, tuple(stops))
    candidate.contact_visits[visit_id] = ContactVisit(
        visit_id=visit_id,
        uav_id=owner,
        point_id=point_id,
    )
    candidate.task_decisions[task_id] = TaskDecision.offload(visit_id)
    validate_solution(instance, candidate)
    return candidate


def build_fixed_route_nearest_mec_solution(
    instance: Instance,
    *,
    base_solution: DiscreteSolution | None = None,
    config: NearestMECFixedRouteConfig | None = None,
) -> DiscreteSolution:
    """Build a fixed-route nearest-MEC heuristic solution.

    The heuristic freezes the greedy task routes. At each step it examines
    deadline/queue-critical local tasks. A task may only offload to its nearest
    MEC center. Existing later contacts at that MEC are preferred; otherwise
    one contact is inserted without changing task order. Candidate acceptance
    uses the same cheap feasibility-oriented proxy as initialization, but MEC
    selection itself is geometry-only.
    """

    cfg = config or NearestMECFixedRouteConfig()
    current = (
        deepcopy(base_solution)
        if base_solution is not None
        else build_greedy_initial_solution(instance)
    )
    validate_solution(instance, current)

    frozen_task_routes = {
        uav_id: route.task_ids()
        for uav_id, route in current.routes.items()
    }
    current_proxy = evaluate_initial_proxy(instance, current)
    initial_score = current_proxy.score.key
    accepted_moves: list[dict[str, object]] = []

    for step in range(1, cfg.max_steps + 1):
        if current_proxy.score.violated_constraints == 0:
            break

        best_solution: DiscreteSolution | None = None
        best_proxy: ProxyEvaluation | None = None
        best_move: dict[str, object] | None = None

        for task_id in _critical_local_tasks(
            instance,
            current,
            current_proxy,
            limit=cfg.critical_task_limit,
        ):
            mec_id = _nearest_mec_id(instance, task_id)

            for visit_id in _existing_nearest_mec_contacts_after_task(
                instance,
                current,
                task_id,
                mec_id,
            ):
                candidate = _reuse_contact(
                    instance,
                    current,
                    task_id=task_id,
                    visit_id=visit_id,
                )
                proxy = evaluate_initial_proxy(instance, candidate)
                if not _strictly_better(
                    proxy.score,
                    current_proxy.score,
                    tolerance=cfg.improvement_tolerance,
                ):
                    continue
                if (
                    best_proxy is None
                    or proxy.score.key < best_proxy.score.key
                ):
                    best_solution = candidate
                    best_proxy = proxy
                    best_move = {
                        "type": "reuse_nearest_mec_contact",
                        "task_id": task_id,
                        "mec_id": mec_id,
                        "visit_id": visit_id,
                    }

            owner = _task_owner(current, task_id)
            if (
                len(current.routes[owner].contact_visit_ids())
                >= instance.max_contacts_per_uav
            ):
                continue

            insertion = _best_nearest_mec_contact_insertion(
                instance,
                current,
                task_id=task_id,
                mec_id=mec_id,
            )
            if insertion is None:
                continue
            detour_m, point_id, insert_pos = insertion
            candidate = _insert_contact(
                instance,
                current,
                task_id=task_id,
                point_id=point_id,
                insert_pos=insert_pos,
            )
            proxy = evaluate_initial_proxy(instance, candidate)
            if not _strictly_better(
                proxy.score,
                current_proxy.score,
                tolerance=cfg.improvement_tolerance,
            ):
                continue
            if (
                best_proxy is None
                or proxy.score.key < best_proxy.score.key
            ):
                best_solution = candidate
                best_proxy = proxy
                best_move = {
                    "type": "insert_nearest_mec_contact",
                    "task_id": task_id,
                    "mec_id": mec_id,
                    "point_id": point_id,
                    "insert_pos": insert_pos,
                    "detour_m": detour_m,
                }

        if best_solution is None or best_proxy is None:
            break

        current = best_solution
        current_proxy = best_proxy
        accepted_moves.append(
            {
                "step": step,
                **(best_move or {}),
            }
        )

    for uav_id, route in current.routes.items():
        if route.task_ids() != frozen_task_routes[uav_id]:
            raise RuntimeError(
                "Fixed-route nearest-MEC heuristic changed task order"
            )

    current.metadata.update(
        {
            "builder": "fixed_route_nearest_mec",
            "phase": "geometry_only_mec_offloading",
            "nearest_mec_steps": len(accepted_moves),
            "nearest_mec_moves": accepted_moves,
            "proxy_initial_score": initial_score,
            "proxy_final_score": current_proxy.score.key,
            "proxy_feasible": (
                current_proxy.score.violated_constraints == 0
            ),
            "offloaded_tasks": sum(
                decision.mode is ExecutionMode.OFFLOAD
                for decision in current.task_decisions.values()
            ),
            "contact_visits": len(current.contact_visits),
        }
    )
    validate_solution(instance, current)
    return current
