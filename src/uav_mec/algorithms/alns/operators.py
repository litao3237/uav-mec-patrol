from __future__ import annotations

from dataclasses import dataclass
from functools import partial, update_wrapper
from typing import Iterable

import numpy as np

from uav_mec.algorithms.initial import (
    build_mec_assisted_initial_solution,
    evaluate_initial_proxy,
)
from uav_mec.domain import (
    DiscreteSolution,
    ExecutionMode,
    Route,
    RouteStop,
    StopType,
    TaskDecision,
)
from uav_mec.evaluation.geometry import distance, stop_xy
from uav_mec.evaluation.validator import validate_solution

from .state import UavMecState


@dataclass(frozen=True)
class DestroyConfig:
    fraction: float = 0.15
    min_remove: int = 2
    max_remove: int = 12
    critical_pool_factor: int = 3

    def count(self, num_tasks: int) -> int:
        raw = max(self.min_remove, round(self.fraction * num_tasks))
        return max(1, min(self.max_remove, num_tasks, int(raw)))


@dataclass(frozen=True)
class _InsertionOption:
    uav_id: str
    position: int
    cycle_overflow_s: float
    deadline_lb_violation_s: float
    delta_distance_m: float
    route_task_count: int

    @property
    def key(self) -> tuple[float, float, float, int, str, int]:
        return (
            self.cycle_overflow_s,
            self.deadline_lb_violation_s,
            self.delta_distance_m,
            self.route_task_count,
            self.uav_id,
            self.position,
        )


def _cleanup_orphan_contacts(solution: DiscreteSolution) -> None:
    used = {
        decision.contact_visit_id
        for decision in solution.task_decisions.values()
        if (
            decision.mode is ExecutionMode.OFFLOAD
            and decision.contact_visit_id is not None
        )
    }

    for uav_id, route in list(solution.routes.items()):
        solution.routes[uav_id] = Route(
            uav_id,
            tuple(
                stop
                for stop in route.stops
                if (
                    stop.kind is not StopType.CONTACT
                    or stop.ref_id in used
                )
            ),
        )

    solution.contact_visits = {
        visit_id: visit
        for visit_id, visit in solution.contact_visits.items()
        if visit_id in used
    }


def _destroy_tasks(
    current: UavMecState,
    task_ids: Iterable[str],
) -> UavMecState:
    destroyed = current.copy()
    remove = set(task_ids)
    if not remove:
        return destroyed

    for uav_id, route in list(destroyed.solution.routes.items()):
        destroyed.solution.routes[uav_id] = Route(
            uav_id,
            tuple(
                stop
                for stop in route.stops
                if not (
                    stop.kind is StopType.TASK
                    and stop.ref_id in remove
                )
            ),
        )

    for task_id in remove:
        destroyed.solution.task_decisions.pop(task_id, None)

    _cleanup_orphan_contacts(destroyed.solution)
    destroyed.removed_tasks = sorted(
        set(destroyed.removed_tasks).union(remove)
    )
    destroyed.invalidate()
    return destroyed


def random_task_removal(
    current: UavMecState,
    rng: np.random.Generator,
    *,
    config: DestroyConfig,
) -> UavMecState:
    tasks = sorted(current.instance.tasks)
    q = config.count(len(tasks))
    chosen = rng.choice(tasks, size=q, replace=False).tolist()
    return _destroy_tasks(current, chosen)


def critical_task_removal(
    current: UavMecState,
    rng: np.random.Generator,
    *,
    config: DestroyConfig,
) -> UavMecState:
    proxy = evaluate_initial_proxy(
        current.instance,
        current.solution,
    )
    ranked: list[tuple[tuple[float, float, float, str], str]] = []

    for task_id, task in current.instance.tasks.items():
        completion = proxy.reduced.task_completion_s[task_id]
        violation = max(
            0.0,
            proxy.reduced.deadline_violation_s[task_id],
        )
        normalized_violation = violation / max(1.0, task.deadline_s)
        completion_ratio = (
            completion - task.release_s
        ) / max(1.0, task.deadline_s)
        workload_pressure = (
            task.workload_gcycles / max(1.0, task.deadline_s)
        )
        rank = (
            normalized_violation,
            completion_ratio,
            workload_pressure,
            task_id,
        )
        ranked.append((rank, task_id))

    ranked.sort(key=lambda item: item[0], reverse=True)
    q = config.count(len(ranked))
    pool_size = min(
        len(ranked),
        max(q, config.critical_pool_factor * q),
    )
    pool = [task_id for _, task_id in ranked[:pool_size]]
    chosen = rng.choice(pool, size=q, replace=False).tolist()
    return _destroy_tasks(current, chosen)


def route_segment_removal(
    current: UavMecState,
    rng: np.random.Generator,
    *,
    config: DestroyConfig,
) -> UavMecState:
    nonempty = [
        (uav_id, list(route.task_ids()))
        for uav_id, route in current.solution.routes.items()
        if route.task_ids()
    ]
    if not nonempty:
        return current.copy()

    route_idx = int(rng.integers(0, len(nonempty)))
    _, tasks = nonempty[route_idx]
    q = min(config.count(len(current.instance.tasks)), len(tasks))
    start = int(rng.integers(0, len(tasks) - q + 1))
    chosen = tasks[start : start + q]
    return _destroy_tasks(current, chosen)


def _route_distance(
    instance,
    solution,
    stops: list[RouteStop],
) -> float:
    total = 0.0
    for left, right in zip(stops, stops[1:]):
        total += distance(
            stop_xy(instance, solution, left),
            stop_xy(instance, solution, right),
        )
    return total


def _insertion_option(
    state: UavMecState,
    task_id: str,
    uav_id: str,
    position: int,
) -> _InsertionOption:
    instance = state.instance
    solution = state.solution
    route = solution.routes[uav_id]
    current_stops = list(route.stops)
    task_stop = RouteStop.task(task_id)

    prev_stop = current_stops[position - 1]
    next_stop = current_stops[position]
    task_xy = stop_xy(instance, solution, task_stop)
    prev_xy = stop_xy(instance, solution, prev_stop)
    next_xy = stop_xy(instance, solution, next_stop)
    delta_distance = (
        distance(prev_xy, task_xy)
        + distance(task_xy, next_xy)
        - distance(prev_xy, next_xy)
    )

    candidate_stops = list(current_stops)
    candidate_stops.insert(position, task_stop)
    route_distance = _route_distance(
        instance,
        solution,
        candidate_stops,
    )
    collect_service = sum(
        instance.tasks[stop.ref_id].collect_s
        for stop in candidate_stops
        if stop.kind is StopType.TASK
    )
    base_return = (
        route_distance / instance.uavs[uav_id].speed_mps
        + collect_service
    )
    cycle_overflow = max(0.0, base_return - instance.cycle_s)

    elapsed = 0.0
    prev = candidate_stops[0]
    collect_time = 0.0
    for stop in candidate_stops[1:]:
        elapsed += distance(
            stop_xy(instance, solution, prev),
            stop_xy(instance, solution, stop),
        ) / instance.uavs[uav_id].speed_mps
        if stop.kind is StopType.TASK:
            elapsed += instance.tasks[stop.ref_id].collect_s
        if stop.kind is StopType.TASK and stop.ref_id == task_id:
            collect_time = elapsed
            break
        prev = stop

    task = instance.tasks[task_id]
    fastest_cpu = max(
        [u.local_cpu_ghz for u in instance.uavs.values()]
        + [m.cpu_ghz for m in instance.mecs.values()]
    )
    optimistic_completion = (
        collect_time + task.workload_gcycles / fastest_cpu
    )
    deadline_lb_violation = max(
        0.0,
        optimistic_completion
        - task.release_s
        - task.deadline_s,
    )

    return _InsertionOption(
        uav_id=uav_id,
        position=position,
        cycle_overflow_s=cycle_overflow,
        deadline_lb_violation_s=deadline_lb_violation,
        delta_distance_m=delta_distance,
        route_task_count=len(route.task_ids()),
    )


def _options_for_task(
    state: UavMecState,
    task_id: str,
) -> list[_InsertionOption]:
    options: list[_InsertionOption] = []
    for uav_id, route in state.solution.routes.items():
        for position in range(1, len(route.stops)):
            options.append(
                _insertion_option(
                    state,
                    task_id,
                    uav_id,
                    position,
                )
            )
    options.sort(key=lambda option: option.key)
    return options


def _apply_local_insertion(
    state: UavMecState,
    task_id: str,
    option: _InsertionOption,
) -> None:
    route = state.solution.routes[option.uav_id]
    stops = list(route.stops)
    stops.insert(option.position, RouteStop.task(task_id))
    state.solution.routes[option.uav_id] = Route(
        option.uav_id,
        tuple(stops),
    )
    state.solution.task_decisions[task_id] = TaskDecision.local()
    state.removed_tasks.remove(task_id)
    state.invalidate()


def _finish_repair(
    state: UavMecState,
) -> UavMecState:
    if state.removed_tasks:
        raise RuntimeError(
            f"Repair left tasks unassigned: {state.removed_tasks}"
        )
    validate_solution(state.instance, state.solution)
    state.solution = build_mec_assisted_initial_solution(
        state.instance,
        base_solution=state.solution,
    )
    validate_solution(state.instance, state.solution)
    state.invalidate()
    return state


def cheapest_insertion_repair(
    destroyed: UavMecState,
    rng: np.random.Generator,
) -> UavMecState:
    """Global cheapest insertion followed by problem-specific MEC repair."""

    repaired = destroyed.copy()
    while repaired.removed_tasks:
        best: tuple[tuple, str, _InsertionOption] | None = None
        for task_id in list(repaired.removed_tasks):
            option = _options_for_task(repaired, task_id)[0]
            candidate = (option.key, task_id, option)
            if best is None or candidate[0:2] < best[0:2]:
                best = candidate

        if best is None:
            raise RuntimeError("No task insertion option available")
        _, task_id, option = best
        _apply_local_insertion(repaired, task_id, option)

    return _finish_repair(repaired)


def regret2_insertion_repair(
    destroyed: UavMecState,
    rng: np.random.Generator,
) -> UavMecState:
    """Regret-2 route repair followed by problem-specific MEC repair."""

    repaired = destroyed.copy()
    while repaired.removed_tasks:
        chosen: tuple[
            tuple[float, float, float],
            str,
            _InsertionOption,
        ] | None = None

        for task_id in list(repaired.removed_tasks):
            options = _options_for_task(repaired, task_id)
            best = options[0]
            second = options[1] if len(options) > 1 else best
            regret = (
                max(
                    0.0,
                    second.cycle_overflow_s
                    - best.cycle_overflow_s,
                ),
                max(
                    0.0,
                    second.deadline_lb_violation_s
                    - best.deadline_lb_violation_s,
                ),
                max(
                    0.0,
                    second.delta_distance_m
                    - best.delta_distance_m,
                ),
            )
            candidate = (regret, task_id, best)
            if chosen is None or candidate[0] > chosen[0]:
                chosen = candidate

        if chosen is None:
            raise RuntimeError("No regret insertion option available")
        _, task_id, option = chosen
        _apply_local_insertion(repaired, task_id, option)

    return _finish_repair(repaired)


def _configured_destroy_operator(func, config: DestroyConfig):
    """Bind destroy configuration while preserving operator metadata.

    ALNS v7 accesses the operator's __name__ during registration even when an
    explicit registration name is supplied. functools.partial has no __name__
    by default, so update_wrapper copies the wrapped function metadata.
    """

    operator = partial(func, config=config)
    update_wrapper(operator, func)
    return operator


def make_destroy_operators(
    config: DestroyConfig,
):
    return [
        (
            "random_task_removal",
            _configured_destroy_operator(
                random_task_removal,
                config,
            ),
        ),
        (
            "critical_task_removal",
            _configured_destroy_operator(
                critical_task_removal,
                config,
            ),
        ),
        (
            "route_segment_removal",
            _configured_destroy_operator(
                route_segment_removal,
                config,
            ),
        ),
    ]


def make_repair_operators():
    return [
        ("cheapest_insertion_mec_repair", cheapest_insertion_repair),
        ("regret2_insertion_mec_repair", regret2_insertion_repair),
    ]
