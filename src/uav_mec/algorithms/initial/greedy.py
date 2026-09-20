from __future__ import annotations

from dataclasses import dataclass

from uav_mec.domain import (
    DiscreteSolution,
    Instance,
    Route,
    RouteStop,
    TaskDecision,
)
from uav_mec.evaluation.geometry import distance
from uav_mec.evaluation.validator import validate_solution


@dataclass(frozen=True)
class GreedyInitialConfig:
    """Configuration for the task-only greedy seed.

    The construction follows a mature VRP pattern: parallel insertion followed
    by route-local 2-opt. The scoring is problem-aware but does not solve the
    contact/offloading subproblem yet.
    """

    max_two_opt_passes: int = 30
    deadline_tie_tolerance_s: float = 1e-9


@dataclass(frozen=True)
class _RouteProxy:
    distance_m: float
    base_return_s: float
    cycle_overflow_s: float
    max_deadline_lb_violation_s: float
    total_deadline_lb_violation_s: float

    @property
    def key(self) -> tuple[float, float, float, float]:
        return (
            self.cycle_overflow_s,
            self.max_deadline_lb_violation_s,
            self.total_deadline_lb_violation_s,
            self.distance_m,
        )


def _task_xy(instance: Instance, task_id: str) -> tuple[float, float]:
    task = instance.tasks[task_id]
    return task.x, task.y


def _optimistic_processing_time_s(instance: Instance, task_id: str) -> float:
    task = instance.tasks[task_id]
    fastest_cpu = max(
        [uav.local_cpu_ghz for uav in instance.uavs.values()]
        + [mec.cpu_ghz for mec in instance.mecs.values()]
    )
    return task.workload_gcycles / fastest_cpu


def _route_proxy(
    instance: Instance,
    uav_id: str,
    task_ids: list[str],
) -> _RouteProxy:
    """Return a cheap deterministic route-quality proxy."""

    uav = instance.uavs[uav_id]
    prev_xy = instance.depot_xy
    elapsed_s = 0.0
    distance_m = 0.0
    violations: list[float] = []

    for task_id in task_ids:
        task = instance.tasks[task_id]
        xy = _task_xy(instance, task_id)
        leg = distance(prev_xy, xy)
        distance_m += leg
        elapsed_s += leg / uav.speed_mps
        elapsed_s += task.collect_s

        optimistic_completion = elapsed_s + _optimistic_processing_time_s(
            instance,
            task_id,
        )
        deadline_abs = task.release_s + task.deadline_s
        violations.append(max(0.0, optimistic_completion - deadline_abs))
        prev_xy = xy

    return_leg = distance(prev_xy, instance.depot_xy)
    distance_m += return_leg
    elapsed_s += return_leg / uav.speed_mps

    return _RouteProxy(
        distance_m=distance_m,
        base_return_s=elapsed_s,
        cycle_overflow_s=max(0.0, elapsed_s - instance.cycle_s),
        max_deadline_lb_violation_s=max(violations, default=0.0),
        total_deadline_lb_violation_s=sum(violations),
    )


def _task_priority(instance: Instance, task_id: str) -> tuple[float, float, str]:
    """Earliest-deadline first, with far tasks breaking ties."""

    task = instance.tasks[task_id]
    depot_distance = distance(instance.depot_xy, (task.x, task.y))
    return task.release_s + task.deadline_s, -depot_distance, task_id


def _best_insertion(
    instance: Instance,
    routes: dict[str, list[str]],
    task_id: str,
) -> tuple[str, int]:
    best_key: tuple[float, float, float, float, float, int, str] | None = None
    best_move: tuple[str, int] | None = None

    for uav_id, route in routes.items():
        current_proxy = _route_proxy(instance, uav_id, route)
        for pos in range(len(route) + 1):
            candidate = route[:pos] + [task_id] + route[pos:]
            proxy = _route_proxy(instance, uav_id, candidate)
            incremental_distance = proxy.distance_m - current_proxy.distance_m

            key = (
                proxy.cycle_overflow_s,
                proxy.max_deadline_lb_violation_s,
                proxy.total_deadline_lb_violation_s,
                proxy.base_return_s,
                incremental_distance,
                len(route),
                uav_id,
            )
            if best_key is None or key < best_key:
                best_key = key
                best_move = (uav_id, pos)

    if best_move is None:
        raise RuntimeError(f"No insertion position found for task {task_id}")
    return best_move


def _two_opt_route(
    instance: Instance,
    uav_id: str,
    task_ids: list[str],
    *,
    max_passes: int,
) -> list[str]:
    """Route-local deterministic 2-opt using the same lexicographic proxy."""

    if len(task_ids) < 3:
        return list(task_ids)

    best = list(task_ids)
    best_proxy = _route_proxy(instance, uav_id, best)

    for _ in range(max_passes):
        improved = False
        candidate_best = best
        candidate_proxy = best_proxy

        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = (
                    best[:i]
                    + list(reversed(best[i : j + 1]))
                    + best[j + 1 :]
                )
                proxy = _route_proxy(instance, uav_id, candidate)
                if proxy.key < candidate_proxy.key:
                    candidate_best = candidate
                    candidate_proxy = proxy
                    improved = True

        if not improved:
            break
        best = candidate_best
        best_proxy = candidate_proxy

    return best


def build_greedy_initial_solution(
    instance: Instance,
    config: GreedyInitialConfig | None = None,
) -> DiscreteSolution:
    """Construct a valid all-local discrete seed for the coupled heuristic.

    Phase A implemented here:
      task-to-UAV assignment -> task visit order -> route-local 2-opt.

    Contacts and offloading are left for the next construction phase. Starting
    from a valid all-local seed gives a clean baseline for measuring exactly
    when contact insertion is necessary.
    """

    cfg = config or GreedyInitialConfig()
    routes: dict[str, list[str]] = {
        uav_id: [] for uav_id in sorted(instance.uavs)
    }

    for task_id in sorted(
        instance.tasks,
        key=lambda t: _task_priority(instance, t),
    ):
        uav_id, pos = _best_insertion(instance, routes, task_id)
        routes[uav_id].insert(pos, task_id)

    for uav_id in routes:
        routes[uav_id] = _two_opt_route(
            instance,
            uav_id,
            routes[uav_id],
            max_passes=cfg.max_two_opt_passes,
        )

    solution = DiscreteSolution(
        routes={
            uav_id: Route(
                uav_id,
                (
                    RouteStop.depot(),
                    *(RouteStop.task(task_id) for task_id in task_ids),
                    RouteStop.depot(),
                ),
            )
            for uav_id, task_ids in routes.items()
        },
        contact_visits={},
        task_decisions={
            task_id: TaskDecision.local()
            for task_id in instance.tasks
        },
        metadata={
            "builder": "parallel_greedy_insertion_2opt",
            "phase": "task_routing_all_local",
        },
    )
    validate_solution(instance, solution)
    return solution
