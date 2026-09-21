from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import partial, update_wrapper

import numpy as np

from uav_mec.algorithms.initial import evaluate_initial_proxy
from uav_mec.domain import (
    ContactVisit,
    DiscreteSolution,
    ExecutionMode,
    Route,
    RouteStop,
    StopType,
    TaskDecision,
)
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.geometry import distance, stop_xy
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import fast_feasibility_precheck

from .operators import (
    DestroyConfig,
    _apply_local_insertion,
    _cleanup_orphan_contacts,
    _destroy_tasks,
    _finish_repair,
    _options_for_task,
    cheapest_insertion_repair,
    critical_task_removal,
    regret2_insertion_repair,
)
from .state import UavMecState


@dataclass(frozen=True)
class ProblemOperatorConfig:
    """Restricted candidate budget for problem-specific ALNS operators."""

    contact_points_per_mec: int = 2
    contact_target_pool: int = 3
    critical_task_limit: int = 6
    mode_candidate_limit: int = 24
    compute_option_limit: int = 12
    elite_shortlist_limit: int = 6
    elite_task_limit: int = 4
    elite_positions_per_contact: int = 2
    elite_points_per_mec: int = 1
    elite_route_options_per_task: int = 2
    elite_family_quota: int = 1
    elite_min_improvement_rel: float = 1e-4
    elite_min_improvement_j: float = 1.0


def _proxy_precheck_key(
    state: UavMecState,
    solution: DiscreteSolution,
) -> tuple[float, ...]:
    """Cheap shortlist key aligned with the screened outer evaluator.

    Optimistic-precheck failure remains a hard structural signal. Once a
    candidate passes that screen, proxy constraint violations are not ranked
    ahead of energy, because high-load experiments showed that a proxy
    violation can still be Stage-1 CVX feasible. The proxy is therefore used
    only to shortlist a promising local move; the selected move is checked
    against the injected outer evaluator before intensification accepts it.
    """

    info = build_event_info(state.instance, solution)
    precheck = fast_feasibility_precheck(
        state.instance,
        solution,
        info,
    )
    proxy = evaluate_initial_proxy(state.instance, solution)
    score = proxy.score
    return (
        0.0 if precheck.feasible else 1.0,
        float(len(precheck.reasons)),
        score.total_energy_j,
        float(score.violated_constraints),
        score.max_normalized_violation,
        score.sum_normalized_violation,
        score.total_distance_m,
    )


def _aligned_intensification_choice(
    state: UavMecState,
    baseline: DiscreteSolution,
    candidate: DiscreteSolution,
    *,
    tolerance: float = 1e-12,
) -> DiscreteSolution:
    """Keep an intensification move only when the outer evaluator agrees."""

    baseline_obj = float(
        state.evaluator(state.instance, baseline)
    )
    candidate_obj = float(
        state.evaluator(state.instance, candidate)
    )
    scale = max(
        1.0,
        abs(baseline_obj),
        abs(candidate_obj),
    )
    if candidate_obj < baseline_obj - tolerance * scale:
        return candidate
    return baseline

def _visit_pressure(
    state: UavMecState,
    visit_id: str,
    *,
    info=None,
    proxy=None,
) -> tuple[float, float, int, str]:
    info = info or build_event_info(state.instance, state.solution)
    proxy = proxy or evaluate_initial_proxy(
        state.instance,
        state.solution,
    )
    batch = info.batch_tasks.get(visit_id, [])
    if not batch:
        return (0.0, 0.0, 0, visit_id)

    max_ratio = max(
        (
            proxy.reduced.task_completion_s[task_id]
            - state.instance.tasks[task_id].release_s
        )
        / max(1.0, state.instance.tasks[task_id].deadline_s)
        for task_id in batch
    )
    upload_s = proxy.reduced.upload_time_s.get(visit_id, 0.0)
    point_id = state.solution.contact_visits[visit_id].point_id
    mec_id = state.instance.contact_points[point_id].mec_id
    pair_count = sum(
        pair_mec == mec_id
        for _, pair_mec in info.active_uav_mec_pairs
    )
    return (max_ratio, upload_s, pair_count, visit_id)


def mec_batch_pressure_removal(
    current: UavMecState,
    rng: np.random.Generator,
    *,
    config: DestroyConfig,
    problem: ProblemOperatorConfig,
) -> UavMecState:
    """Remove a high-pressure offloading batch to reopen contact/batch choices."""

    info = build_event_info(current.instance, current.solution)
    visits = [
        visit_id
        for visit_id, batch in info.batch_tasks.items()
        if batch
    ]
    if not visits:
        return critical_task_removal(
            current,
            rng,
            config=config,
        )

    proxy = evaluate_initial_proxy(current.instance, current.solution)
    ranked = sorted(
        visits,
        key=lambda visit_id: _visit_pressure(
            current,
            visit_id,
            info=info,
            proxy=proxy,
        ),
        reverse=True,
    )
    pool = ranked[: min(problem.contact_target_pool, len(ranked))]
    visit_id = str(rng.choice(pool))
    batch = list(info.batch_tasks[visit_id])

    batch.sort(
        key=lambda task_id: (
            proxy.reduced.deadline_violation_s[task_id]
            / max(1.0, current.instance.tasks[task_id].deadline_s),
            (
                proxy.reduced.task_completion_s[task_id]
                - current.instance.tasks[task_id].release_s
            )
            / max(1.0, current.instance.tasks[task_id].deadline_s),
            current.instance.tasks[task_id].workload_gcycles,
            task_id,
        ),
        reverse=True,
    )
    q = min(config.count(len(current.instance.tasks)), len(batch))
    return _destroy_tasks(current, batch[:q])


def shared_mec_pressure_removal(
    current: UavMecState,
    rng: np.random.Generator,
    *,
    config: DestroyConfig,
    problem: ProblemOperatorConfig,
) -> UavMecState:
    """Remove tasks from the most contended MEC to enable MEC reassignment."""

    info = build_event_info(current.instance, current.solution)
    pairs_per_mec: dict[str, int] = {}
    for _, mec_id in info.active_uav_mec_pairs:
        pairs_per_mec[mec_id] = pairs_per_mec.get(mec_id, 0) + 1

    shared = [
        (count, mec_id)
        for mec_id, count in pairs_per_mec.items()
        if count >= 2
    ]
    if not shared:
        return mec_batch_pressure_removal(
            current,
            rng,
            config=config,
            problem=problem,
        )

    max_count = max(count for count, _ in shared)
    target_mecs = sorted(
        mec_id for count, mec_id in shared if count == max_count
    )
    mec_id = str(rng.choice(target_mecs))

    tasks: list[str] = []
    for visit_id, batch in info.batch_tasks.items():
        point_id = current.solution.contact_visits[visit_id].point_id
        if current.instance.contact_points[point_id].mec_id == mec_id:
            tasks.extend(batch)

    if not tasks:
        return mec_batch_pressure_removal(
            current,
            rng,
            config=config,
            problem=problem,
        )

    proxy = evaluate_initial_proxy(current.instance, current.solution)
    tasks = sorted(
        set(tasks),
        key=lambda task_id: (
            proxy.reduced.deadline_violation_s[task_id]
            / max(1.0, current.instance.tasks[task_id].deadline_s),
            (
                proxy.reduced.task_completion_s[task_id]
                - current.instance.tasks[task_id].release_s
            )
            / max(1.0, current.instance.tasks[task_id].deadline_s),
            current.instance.tasks[task_id].workload_gcycles,
            task_id,
        ),
        reverse=True,
    )
    q = min(config.count(len(current.instance.tasks)), len(tasks))
    return _destroy_tasks(current, tasks[:q])


def _candidate_points_for_visit(
    state: UavMecState,
    visit_id: str,
    *,
    per_mec: int,
) -> list[str]:
    solution = state.solution
    visit = solution.contact_visits[visit_id]
    route = solution.routes[visit.uav_id]
    pos = next(
        idx
        for idx, stop in enumerate(route.stops)
        if stop.kind is StopType.CONTACT and stop.ref_id == visit_id
    )
    prev_stop = route.stops[pos - 1]
    next_stop = route.stops[pos + 1]
    prev_xy = stop_xy(state.instance, solution, prev_stop)
    next_xy = stop_xy(state.instance, solution, next_stop)

    by_mec: dict[str, list[tuple[float, float, str]]] = {}
    for point_id, point in state.instance.contact_points.items():
        detour = (
            distance(prev_xy, (point.x, point.y))
            + distance((point.x, point.y), next_xy)
            - distance(prev_xy, next_xy)
        )
        mec = state.instance.mecs[point.mec_id]
        center_ratio = distance(
            (point.x, point.y),
            (mec.x, mec.y),
        ) / max(1e-12, mec.radius_m)
        by_mec.setdefault(point.mec_id, []).append(
            (detour, center_ratio, point_id)
        )

    candidates: list[str] = []
    for mec_id in sorted(by_mec):
        ranked = sorted(by_mec[mec_id])
        candidates.extend(
            point_id for _, _, point_id in ranked[:per_mec]
        )
    return candidates


def _replace_contact_point(
    solution: DiscreteSolution,
    visit_id: str,
    point_id: str,
) -> DiscreteSolution:
    candidate = deepcopy(solution)
    visit = candidate.contact_visits[visit_id]
    candidate.contact_visits[visit_id] = ContactVisit(
        visit_id=visit.visit_id,
        uav_id=visit.uav_id,
        point_id=point_id,
    )
    return candidate


def _best_contact_opportunity_move(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
) -> DiscreteSolution:
    if not state.solution.contact_visits:
        return deepcopy(state.solution)

    info = build_event_info(state.instance, state.solution)
    proxy = evaluate_initial_proxy(state.instance, state.solution)
    ranked_visits = sorted(
        state.solution.contact_visits,
        key=lambda visit_id: _visit_pressure(
            state,
            visit_id,
            info=info,
            proxy=proxy,
        ),
        reverse=True,
    )
    ranked_visits = ranked_visits[: config.contact_target_pool]

    incumbent = deepcopy(state.solution)
    incumbent_key = _proxy_precheck_key(state, incumbent)

    for visit_id in ranked_visits:
        current_point = state.solution.contact_visits[visit_id].point_id
        for point_id in _candidate_points_for_visit(
            state,
            visit_id,
            per_mec=config.contact_points_per_mec,
        ):
            if point_id == current_point:
                continue
            candidate = _replace_contact_point(
                state.solution,
                visit_id,
                point_id,
            )
            validate_solution(state.instance, candidate)
            key = _proxy_precheck_key(state, candidate)
            if key < incumbent_key:
                incumbent = candidate
                incumbent_key = key

    return incumbent


def contact_opportunity_repair(
    destroyed: UavMecState,
    rng: np.random.Generator,
    *,
    config: ProblemOperatorConfig,
) -> UavMecState:
    """Route repair followed by contact-point/MEC replacement intensification."""

    repaired = cheapest_insertion_repair(destroyed, rng)
    baseline = deepcopy(repaired.solution)
    candidate = _best_contact_opportunity_move(
        repaired,
        config=config,
    )
    repaired.solution = _aligned_intensification_choice(
        repaired,
        baseline,
        candidate,
    )
    validate_solution(repaired.instance, repaired.solution)
    repaired.invalidate()
    return repaired


def _route_positions(route: Route) -> tuple[dict[str, int], dict[str, int]]:
    task_pos: dict[str, int] = {}
    visit_pos: dict[str, int] = {}
    for idx, stop in enumerate(route.stops):
        if stop.kind is StopType.TASK:
            task_pos[stop.ref_id] = idx
        elif stop.kind is StopType.CONTACT:
            visit_pos[stop.ref_id] = idx
    return task_pos, visit_pos


def _mode_candidates(
    state: UavMecState,
    task_id: str,
) -> list[TaskDecision]:
    solution = state.solution
    owner = next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )
    route = solution.routes[owner]
    task_pos, visit_pos = _route_positions(route)

    candidates = [TaskDecision.local()]
    for visit_id, pos in sorted(
        visit_pos.items(),
        key=lambda item: item[1],
    ):
        if pos > task_pos[task_id]:
            candidates.append(TaskDecision.offload(visit_id))
    return candidates


def _apply_task_decision(
    state: UavMecState,
    task_id: str,
    decision: TaskDecision,
) -> DiscreteSolution | None:
    current = state.solution.task_decisions[task_id]
    if current == decision:
        return None

    candidate = deepcopy(state.solution)
    candidate.task_decisions[task_id] = decision
    _cleanup_orphan_contacts(candidate)
    try:
        validate_solution(state.instance, candidate)
    except ValueError:
        return None
    return candidate


def _critical_tasks_for_mode_move(
    state: UavMecState,
    *,
    limit: int,
) -> list[str]:
    proxy = evaluate_initial_proxy(state.instance, state.solution)
    ranked = sorted(
        state.instance.tasks,
        key=lambda task_id: (
            proxy.reduced.deadline_violation_s[task_id]
            / max(1.0, state.instance.tasks[task_id].deadline_s),
            (
                proxy.reduced.task_completion_s[task_id]
                - state.instance.tasks[task_id].release_s
            )
            / max(1.0, state.instance.tasks[task_id].deadline_s),
            state.instance.tasks[task_id].workload_gcycles,
            task_id,
        ),
        reverse=True,
    )
    return ranked[:limit]


def _best_mode_batch_move(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
) -> DiscreteSolution:
    incumbent = deepcopy(state.solution)
    incumbent_key = _proxy_precheck_key(state, incumbent)
    checked = 0

    for task_id in _critical_tasks_for_mode_move(
        state,
        limit=config.critical_task_limit,
    ):
        for decision in _mode_candidates(state, task_id):
            candidate = _apply_task_decision(
                state,
                task_id,
                decision,
            )
            if candidate is None:
                continue

            checked += 1
            key = _proxy_precheck_key(state, candidate)
            if key < incumbent_key:
                incumbent = candidate
                incumbent_key = key

            if checked >= config.mode_candidate_limit:
                return incumbent

    return incumbent


def mode_batch_repair(
    destroyed: UavMecState,
    rng: np.random.Generator,
    *,
    config: ProblemOperatorConfig,
) -> UavMecState:
    """Regret route repair followed by Local/MEC and batch reassignment."""

    repaired = regret2_insertion_repair(destroyed, rng)
    baseline = deepcopy(repaired.solution)
    candidate = _best_mode_batch_move(
        repaired,
        config=config,
    )
    repaired.solution = _aligned_intensification_choice(
        repaired,
        baseline,
        candidate,
    )
    validate_solution(repaired.instance, repaired.solution)
    repaired.invalidate()
    return repaired


def _compute_pressure_for_option(
    state: UavMecState,
    task_id: str,
    option,
) -> tuple[float, float, float, float, int, str, int]:
    """Optimistic local-FIFO pressure for one route insertion option."""

    instance = state.instance
    solution = state.solution
    route = solution.routes[option.uav_id]
    stops = list(route.stops)
    stops.insert(option.position, RouteStop.task(task_id))

    elapsed = 0.0
    previous = stops[0]
    local_finish = 0.0
    max_violation = 0.0
    sum_violation = 0.0

    for stop in stops[1:]:
        elapsed += distance(
            stop_xy(instance, solution, previous),
            stop_xy(instance, solution, stop),
        ) / instance.uavs[option.uav_id].speed_mps

        if stop.kind is StopType.TASK:
            task = instance.tasks[stop.ref_id]
            elapsed += task.collect_s
            is_local = (
                stop.ref_id == task_id
                or solution.task_decisions.get(
                    stop.ref_id,
                    TaskDecision.local(),
                ).mode
                is ExecutionMode.LOCAL
            )
            if is_local:
                local_finish = (
                    max(elapsed, task.release_s, local_finish)
                    + task.workload_gcycles
                    / instance.uavs[option.uav_id].local_cpu_ghz
                )
                violation = max(
                    0.0,
                    local_finish
                    - task.release_s
                    - task.deadline_s,
                ) / max(1.0, task.deadline_s)
                max_violation = max(max_violation, violation)
                sum_violation += violation

        previous = stop

    return (
        option.cycle_overflow_s,
        max_violation,
        sum_violation,
        option.delta_distance_m,
        option.route_task_count,
        option.uav_id,
        option.position,
    )


def compute_aware_insertion_repair(
    destroyed: UavMecState,
    rng: np.random.Generator,
    *,
    config: ProblemOperatorConfig,
) -> UavMecState:
    """Deadline-aware cross-route insertion using optimistic local-FIFO pressure."""

    repaired = destroyed.copy()

    while repaired.removed_tasks:
        best: tuple[tuple, str, object] | None = None
        for task_id in list(repaired.removed_tasks):
            options = _options_for_task(repaired, task_id)
            for option in options[: config.compute_option_limit]:
                key = _compute_pressure_for_option(
                    repaired,
                    task_id,
                    option,
                )
                candidate = (key, task_id, option)
                if best is None or candidate[0:2] < best[0:2]:
                    best = candidate

        if best is None:
            raise RuntimeError("No compute-aware insertion option available")
        _, task_id, option = best
        _apply_local_insertion(repaired, task_id, option)

    repaired = _finish_repair(repaired)
    baseline = deepcopy(repaired.solution)
    candidate = _best_mode_batch_move(
        repaired,
        config=config,
    )
    repaired.solution = _aligned_intensification_choice(
        repaired,
        baseline,
        candidate,
    )
    validate_solution(repaired.instance, repaired.solution)
    repaired.invalidate()
    return repaired



def _next_elite_visit_id(
    solution: DiscreteSolution,
    uav_id: str,
) -> str:
    prefix = f"EL_{uav_id}_"
    idx = 1
    while f"{prefix}{idx}" in solution.contact_visits:
        idx += 1
    return f"{prefix}{idx}"


def _visit_batch_tasks(
    solution: DiscreteSolution,
    visit_id: str,
) -> list[str]:
    return [
        task_id
        for task_id, decision in solution.task_decisions.items()
        if (
            decision.mode is ExecutionMode.OFFLOAD
            and decision.contact_visit_id == visit_id
        )
    ]


def _relocate_contact_candidates(
    state: UavMecState,
    visit_id: str,
    *,
    positions_limit: int,
) -> list[tuple[str, DiscreteSolution]]:
    solution = state.solution
    visit = solution.contact_visits[visit_id]
    route = solution.routes[visit.uav_id]
    batch = _visit_batch_tasks(solution, visit_id)
    if not batch:
        return []

    without = [
        stop
        for stop in route.stops
        if not (
            stop.kind is StopType.CONTACT
            and stop.ref_id == visit_id
        )
    ]
    task_pos = {
        stop.ref_id: idx
        for idx, stop in enumerate(without)
        if stop.kind is StopType.TASK
    }
    earliest = max(task_pos[task_id] for task_id in batch) + 1

    point = state.instance.contact_points[visit.point_id]
    ranked: list[tuple[float, int]] = []
    for pos in range(earliest, len(without)):
        prev_xy = stop_xy(
            state.instance,
            solution,
            without[pos - 1],
        )
        next_xy = stop_xy(
            state.instance,
            solution,
            without[pos],
        )
        detour = (
            distance(prev_xy, (point.x, point.y))
            + distance((point.x, point.y), next_xy)
            - distance(prev_xy, next_xy)
        )
        ranked.append((detour, pos))

    # Keep the earliest feasible opportunity for latency plus the geometrically
    # best alternatives for flight energy.
    positions = [earliest]
    for _, pos in sorted(ranked):
        if pos not in positions:
            positions.append(pos)
        if len(positions) >= positions_limit:
            break

    candidates: list[tuple[str, DiscreteSolution]] = []
    for pos in positions:
        current_pos = next(
            idx
            for idx, stop in enumerate(route.stops)
            if (
                stop.kind is StopType.CONTACT
                and stop.ref_id == visit_id
            )
        )
        # Convert the insertion position in the contact-free route back to a
        # meaningful move; if the order is unchanged this is a no-op.
        candidate = deepcopy(solution)
        stops = [
            stop
            for stop in candidate.routes[visit.uav_id].stops
            if not (
                stop.kind is StopType.CONTACT
                and stop.ref_id == visit_id
            )
        ]
        stops.insert(pos, RouteStop.contact(visit_id))
        candidate.routes[visit.uav_id] = Route(
            visit.uav_id,
            tuple(stops),
        )
        if candidate.routes[visit.uav_id].stops == route.stops:
            continue
        validate_solution(state.instance, candidate)
        candidates.append(
            (f"contact_relocate::{visit_id}::{current_pos}->{pos}", candidate)
        )
    return candidates


def _best_new_contact_options(
    state: UavMecState,
    task_id: str,
    *,
    per_mec: int,
) -> list[tuple[float, str, int]]:
    solution = state.solution
    owner = next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )
    route = solution.routes[owner]
    task_pos, _ = _route_positions(route)
    task_idx = task_pos[task_id]

    by_mec: dict[str, list[tuple[float, str, int]]] = {}
    for point_id, point in state.instance.contact_points.items():
        best: tuple[float, int] | None = None
        for pos in range(task_idx + 1, len(route.stops)):
            prev_xy = stop_xy(
                state.instance,
                solution,
                route.stops[pos - 1],
            )
            next_xy = stop_xy(
                state.instance,
                solution,
                route.stops[pos],
            )
            detour = (
                distance(prev_xy, (point.x, point.y))
                + distance((point.x, point.y), next_xy)
                - distance(prev_xy, next_xy)
            )
            if best is None or detour < best[0]:
                best = (detour, pos)

        if best is not None:
            by_mec.setdefault(point.mec_id, []).append(
                (best[0], point_id, best[1])
            )

    options: list[tuple[float, str, int]] = []
    for mec_id in sorted(by_mec):
        options.extend(
            sorted(by_mec[mec_id])[:per_mec]
        )
    return sorted(options)


def _insert_new_contact_for_task(
    state: UavMecState,
    task_id: str,
    point_id: str,
    insert_pos: int,
) -> DiscreteSolution | None:
    solution = state.solution
    owner = next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )
    route = solution.routes[owner]

    current_contacts = len(route.contact_visit_ids())
    decision = solution.task_decisions[task_id]
    old_singleton = False
    if (
        decision.mode is ExecutionMode.OFFLOAD
        and decision.contact_visit_id is not None
    ):
        old_singleton = (
            len(
                _visit_batch_tasks(
                    solution,
                    decision.contact_visit_id,
                )
            )
            == 1
        )

    if (
        current_contacts >= state.instance.max_contacts_per_uav
        and not old_singleton
    ):
        return None

    candidate = deepcopy(solution)
    visit_id = _next_elite_visit_id(candidate, owner)
    stops = list(candidate.routes[owner].stops)
    stops.insert(insert_pos, RouteStop.contact(visit_id))
    candidate.routes[owner] = Route(owner, tuple(stops))
    candidate.contact_visits[visit_id] = ContactVisit(
        visit_id=visit_id,
        uav_id=owner,
        point_id=point_id,
    )
    candidate.task_decisions[task_id] = TaskDecision.offload(
        visit_id
    )
    _cleanup_orphan_contacts(candidate)
    try:
        validate_solution(state.instance, candidate)
    except ValueError:
        return None
    return candidate


def _batch_merge_candidates(
    state: UavMecState,
) -> list[tuple[str, DiscreteSolution]]:
    solution = state.solution
    candidates: list[tuple[str, DiscreteSolution]] = []

    for uav_id, route in solution.routes.items():
        task_pos, visit_pos = _route_positions(route)
        visits = sorted(
            route.contact_visit_ids(),
            key=lambda visit_id: visit_pos[visit_id],
        )
        for source in visits:
            batch = _visit_batch_tasks(solution, source)
            if not batch:
                continue
            for target in visits:
                if target == source:
                    continue
                target_pos = visit_pos[target]
                if any(
                    task_pos[task_id] >= target_pos
                    for task_id in batch
                ):
                    continue

                candidate = deepcopy(solution)
                for task_id in batch:
                    candidate.task_decisions[task_id] = (
                        TaskDecision.offload(target)
                    )
                _cleanup_orphan_contacts(candidate)
                try:
                    validate_solution(
                        state.instance,
                        candidate,
                    )
                except ValueError:
                    continue
                candidates.append(
                    (
                        f"batch_merge::{source}->{target}",
                        candidate,
                    )
                )
    return candidates


def _contact_removal_candidates(
    state: UavMecState,
) -> list[tuple[str, DiscreteSolution]]:
    candidates: list[tuple[str, DiscreteSolution]] = []
    for visit_id in state.solution.contact_visits:
        batch = _visit_batch_tasks(
            state.solution,
            visit_id,
        )
        if not batch:
            continue
        candidate = deepcopy(state.solution)
        for task_id in batch:
            candidate.task_decisions[task_id] = (
                TaskDecision.local()
            )
        _cleanup_orphan_contacts(candidate)
        try:
            validate_solution(state.instance, candidate)
        except ValueError:
            continue
        candidates.append(
            (f"contact_remove::{visit_id}", candidate)
        )
    return candidates


def _route_removal_saving(
    state: UavMecState,
    task_id: str,
) -> float:
    solution = state.solution
    owner = next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )
    route = solution.routes[owner]
    idx = next(
        idx
        for idx, stop in enumerate(route.stops)
        if stop.kind is StopType.TASK
        and stop.ref_id == task_id
    )
    prev_xy = stop_xy(
        state.instance,
        solution,
        route.stops[idx - 1],
    )
    task_xy = stop_xy(
        state.instance,
        solution,
        route.stops[idx],
    )
    next_xy = stop_xy(
        state.instance,
        solution,
        route.stops[idx + 1],
    )
    return (
        distance(prev_xy, task_xy)
        + distance(task_xy, next_xy)
        - distance(prev_xy, next_xy)
    )


def _elite_route_tasks(
    state: UavMecState,
    *,
    limit: int,
) -> list[str]:
    critical = _critical_tasks_for_mode_move(
        state,
        limit=limit,
    )
    distance_ranked = sorted(
        state.instance.tasks,
        key=lambda task_id: (
            _route_removal_saving(state, task_id),
            task_id,
        ),
        reverse=True,
    )[:limit]

    result: list[str] = []
    for task_id in critical + distance_ranked:
        if task_id not in result:
            result.append(task_id)
        if len(result) >= 2 * limit:
            break
    return result


def _route_compute_relocate_candidates(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
) -> list[tuple[str, DiscreteSolution]]:
    candidates: list[tuple[str, DiscreteSolution]] = []

    for task_id in _elite_route_tasks(
        state,
        limit=config.elite_task_limit,
    ):
        destroyed = _destroy_tasks(
            state,
            [task_id],
        )
        options = _options_for_task(
            destroyed,
            task_id,
        )
        for option in options[
            : config.elite_route_options_per_task
        ]:
            candidate_state = destroyed.copy()
            _apply_local_insertion(
                candidate_state,
                task_id,
                option,
            )
            try:
                candidate_state = _finish_repair(
                    candidate_state
                )
            except ValueError:
                continue

            if candidate_state.solution == state.solution:
                continue
            candidates.append(
                (
                    "route_compute_relocate::"
                    f"{task_id}->{option.uav_id}"
                    f"@{option.position}",
                    candidate_state.solution,
                )
            )

    return candidates


def _structural_elite_candidates(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
) -> list[tuple[str, DiscreteSolution]]:
    candidates: list[tuple[str, DiscreteSolution]] = []

    for visit_id in state.solution.contact_visits:
        candidates.extend(
            _relocate_contact_candidates(
                state,
                visit_id,
                positions_limit=(
                    config.elite_positions_per_contact
                ),
            )
        )

    candidates.extend(_batch_merge_candidates(state))
    candidates.extend(_contact_removal_candidates(state))
    candidates.extend(
        _route_compute_relocate_candidates(
            state,
            config=config,
        )
    )

    critical = _critical_tasks_for_mode_move(
        state,
        limit=config.elite_task_limit,
    )
    for task_id in critical:
        for _, point_id, insert_pos in _best_new_contact_options(
            state,
            task_id,
            per_mec=config.elite_points_per_mec,
        ):
            candidate = _insert_new_contact_for_task(
                state,
                task_id,
                point_id,
                insert_pos,
            )
            if candidate is None:
                continue
            candidates.append(
                (
                    f"batch_split_or_new_contact::{task_id}"
                    f"::{point_id}@{insert_pos}",
                    candidate,
                )
            )

    # Existing point replacement and task-level mode/batch moves remain useful
    # cheap generators, but they now compete with structural moves only in the
    # elite shortlist.
    point_candidate = _best_contact_opportunity_move(
        state,
        config=config,
    )
    if point_candidate != state.solution:
        candidates.append(
            ("contact_point_replace", point_candidate)
        )

    mode_candidate = _best_mode_batch_move(
        state,
        config=config,
    )
    if mode_candidate != state.solution:
        candidates.append(
            ("task_mode_or_batch_reassign", mode_candidate)
        )

    ranked: list[
        tuple[tuple[float, ...], str, DiscreteSolution]
    ] = []
    seen: set[str] = set()
    for label, candidate in candidates:
        signature = repr(
            (
                tuple(
                    (
                        uav_id,
                        candidate.routes[uav_id].labels(),
                    )
                    for uav_id in sorted(candidate.routes)
                ),
                tuple(
                    sorted(
                        (
                            visit_id,
                            visit.point_id,
                        )
                        for visit_id, visit
                        in candidate.contact_visits.items()
                    )
                ),
                tuple(
                    sorted(
                        (
                            task_id,
                            decision.mode.value,
                            decision.contact_visit_id,
                        )
                        for task_id, decision
                        in candidate.task_decisions.items()
                    )
                ),
            )
        )
        if signature in seen:
            continue
        seen.add(signature)
        ranked.append(
            (
                _proxy_precheck_key(state, candidate),
                label,
                candidate,
            )
        )

    ranked.sort(key=lambda item: item[0])

    def family(label: str) -> str:
        if label.startswith("route_compute_relocate::"):
            return "route"
        if (
            label.startswith("contact_relocate::")
            or label == "contact_point_replace"
        ):
            return "contact"
        if label.startswith("contact_remove::"):
            return "contact_remove"
        if label.startswith("batch_merge::"):
            return "batch_merge"
        if label.startswith("batch_split_or_new_contact::"):
            return "batch_split"
        if label == "task_mode_or_batch_reassign":
            return "mode_batch"
        return "other"

    # A global proxy top-k can starve an entire structural family even when
    # that family contains the exact-CVX improving move. Preserve one (or the
    # configured quota) from each family first, then fill the remaining budget
    # by the global proxy ranking.
    selected: list[
        tuple[tuple[float, ...], str, DiscreteSolution]
    ] = []
    selected_signatures: set[str] = set()
    per_family: dict[str, int] = {}

    for item in ranked:
        _, label, candidate = item
        fam = family(label)
        if per_family.get(fam, 0) >= config.elite_family_quota:
            continue
        signature = repr(
            (
                label,
                tuple(
                    (
                        uav_id,
                        candidate.routes[uav_id].labels(),
                    )
                    for uav_id in sorted(candidate.routes)
                ),
                tuple(
                    sorted(
                        (
                            task_id,
                            decision.mode.value,
                            decision.contact_visit_id,
                        )
                        for task_id, decision
                        in candidate.task_decisions.items()
                    )
                ),
            )
        )
        if signature in selected_signatures:
            continue
        selected.append(item)
        selected_signatures.add(signature)
        per_family[fam] = per_family.get(fam, 0) + 1
        if len(selected) >= config.elite_shortlist_limit:
            break

    if len(selected) < config.elite_shortlist_limit:
        for item in ranked:
            _, label, candidate = item
            signature = repr(
                (
                    label,
                    tuple(
                        (
                            uav_id,
                            candidate.routes[uav_id].labels(),
                        )
                        for uav_id in sorted(candidate.routes)
                    ),
                    tuple(
                        sorted(
                            (
                                task_id,
                                decision.mode.value,
                                decision.contact_visit_id,
                            )
                            for task_id, decision
                            in candidate.task_decisions.items()
                        )
                    ),
                )
            )
            if signature in selected_signatures:
                continue
            selected.append(item)
            selected_signatures.add(signature)
            if len(selected) >= config.elite_shortlist_limit:
                break

    selected.sort(key=lambda item: item[0])
    return [
        (label, candidate)
        for _, label, candidate in selected
    ]


def contact_mode_intensification(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
    objective,
    max_rounds: int = 2,
    tolerance: float = 1e-12,
) -> tuple[UavMecState, dict[str, object]]:
    """Exact-oracle elite intensification over structural MEC neighborhoods.

    The main ALNS keeps its generic exploration budget. Only the elite state is
    exposed to a small shortlist of contact relocation/insertion/removal,
    explicit batch merge/split, point replacement and task-level mode/batch
    reassignment candidates. Cheap proxy/precheck logic builds the shortlist;
    the supplied objective oracle decides every accepted move.
    """

    current = state.copy()
    stats: dict[str, object] = {
        "rounds": 0,
        "candidates_evaluated": 0,
        "improvements": 0,
        "accepted_moves": [],
        "evaluated_moves": [],
    }

    def value(solution: DiscreteSolution) -> float:
        return float(objective(current.instance, solution))

    current_value = value(current.solution)

    for _ in range(max_rounds):
        stats["rounds"] = int(stats["rounds"]) + 1
        shortlist = _structural_elite_candidates(
            current,
            config=config,
        )
        if not shortlist:
            break

        best_value = current_value
        best_label: str | None = None
        best_solution: DiscreteSolution | None = None

        round_base_value = current_value
        evaluated_moves = list(stats["evaluated_moves"])
        for label, candidate in shortlist:
            candidate_value = value(candidate)
            stats["candidates_evaluated"] = (
                int(stats["candidates_evaluated"]) + 1
            )
            finite_candidate = np.isfinite(candidate_value)
            improvement_pct = (
                100.0
                * (round_base_value - candidate_value)
                / max(1.0, abs(round_base_value))
                if finite_candidate
                else None
            )
            evaluated_moves.append(
                {
                    "round": int(stats["rounds"]),
                    "move": label,
                    "objective": (
                        candidate_value
                        if finite_candidate
                        else None
                    ),
                    "improvement_pct": improvement_pct,
                }
            )
            scale = max(
                1.0,
                abs(best_value),
                abs(candidate_value),
            )
            numerical_tol = tolerance * scale
            meaningful_tol = max(
                config.elite_min_improvement_j,
                config.elite_min_improvement_rel * scale,
            )
            acceptance_tol = max(
                numerical_tol,
                meaningful_tol,
            )
            if (
                candidate_value
                < best_value - acceptance_tol
            ):
                best_value = candidate_value
                best_label = label
                best_solution = candidate
        stats["evaluated_moves"] = evaluated_moves

        if best_solution is None or best_label is None:
            break

        current.solution = best_solution
        current.invalidate()
        current_value = best_value
        stats["improvements"] = int(
            stats["improvements"]
        ) + 1
        accepted_moves = list(stats["accepted_moves"])
        accepted_moves.append(
            {
                "move": best_label,
                "objective": best_value,
                "improvement_j": (
                    current_value - best_value
                ),
                "improvement_pct": (
                    100.0
                    * (current_value - best_value)
                    / max(1.0, abs(current_value))
                ),
            }
        )
        stats["accepted_moves"] = accepted_moves

    validate_solution(current.instance, current.solution)
    current.invalidate()
    return current, stats

def _configured(func, **kwargs):
    operator = partial(func, **kwargs)
    update_wrapper(operator, func)
    return operator


def make_problem_destroy_operators(
    destroy: DestroyConfig,
    problem: ProblemOperatorConfig,
):
    return [
        (
            "mec_batch_pressure_removal",
            _configured(
                mec_batch_pressure_removal,
                config=destroy,
                problem=problem,
            ),
        ),
        (
            "shared_mec_pressure_removal",
            _configured(
                shared_mec_pressure_removal,
                config=destroy,
                problem=problem,
            ),
        ),
    ]


def make_problem_repair_operators(
    problem: ProblemOperatorConfig,
):
    return [
        (
            "contact_opportunity_repair",
            _configured(
                contact_opportunity_repair,
                config=problem,
            ),
        ),
        (
            "mode_batch_repair",
            _configured(
                mode_batch_repair,
                config=problem,
            ),
        ),
        (
            "compute_aware_insertion_repair",
            _configured(
                compute_aware_insertion_repair,
                config=problem,
            ),
        ),
    ]
