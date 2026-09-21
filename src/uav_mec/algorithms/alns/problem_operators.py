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


def contact_mode_intensification(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
    objective,
    max_rounds: int = 2,
    tolerance: float = 1e-12,
) -> tuple[UavMecState, dict[str, int]]:
    """Exact-oracle elite intensification for contact and mode/batch moves.

    The main ALNS may use a fast screened evaluator. This routine is intended
    for elite/post-search states, where a small number of shortlisted
    contact/mode moves can afford a stronger objective oracle (for example,
    Stage-1 CVX). Every accepted move is therefore monotone with respect to
    that oracle.
    """

    current = state.copy()
    stats = {
        "rounds": 0,
        "contact_attempts": 0,
        "contact_improvements": 0,
        "mode_attempts": 0,
        "mode_improvements": 0,
    }

    def value(solution: DiscreteSolution) -> float:
        return float(objective(current.instance, solution))

    current_value = value(current.solution)

    for _ in range(max_rounds):
        improved = False
        stats["rounds"] += 1

        contact_candidate = _best_contact_opportunity_move(
            current,
            config=config,
        )
        if contact_candidate != current.solution:
            stats["contact_attempts"] += 1
            candidate_value = value(contact_candidate)
            scale = max(
                1.0,
                abs(current_value),
                abs(candidate_value),
            )
            if (
                candidate_value
                < current_value - tolerance * scale
            ):
                current.solution = contact_candidate
                current.invalidate()
                current_value = candidate_value
                stats["contact_improvements"] += 1
                improved = True

        mode_candidate = _best_mode_batch_move(
            current,
            config=config,
        )
        if mode_candidate != current.solution:
            stats["mode_attempts"] += 1
            candidate_value = value(mode_candidate)
            scale = max(
                1.0,
                abs(current_value),
                abs(candidate_value),
            )
            if (
                candidate_value
                < current_value - tolerance * scale
            ):
                current.solution = mode_candidate
                current.invalidate()
                current_value = candidate_value
                stats["mode_improvements"] += 1
                improved = True

        if not improved:
            break

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
