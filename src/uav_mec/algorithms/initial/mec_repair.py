from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable

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
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.geometry import distance, stop_xy
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.reduced import (
    ReducedResourceEvaluation,
    evaluate_reduced_resources,
)

from .greedy import build_greedy_initial_solution


@dataclass(frozen=True)
class GreedyMECRepairConfig:
    """Restricted-candidate greedy repair for the initial discrete solution."""

    max_steps: int = 24
    critical_task_limit: int = 8
    new_contact_candidate_limit: int = 8
    improvement_tolerance: float = 1e-12


@dataclass(frozen=True)
class ProxyScore:
    violated_constraints: int
    max_normalized_violation: float
    sum_normalized_violation: float
    total_energy_j: float
    total_distance_m: float

    @property
    def key(self) -> tuple[float, float, float, float, float]:
        return (
            float(self.violated_constraints),
            self.max_normalized_violation,
            self.sum_normalized_violation,
            self.total_energy_j,
            self.total_distance_m,
        )


@dataclass(frozen=True)
class ProxyEvaluation:
    reduced: ReducedResourceEvaluation
    score: ProxyScore


def _proxy_resource_allocation(
    instance: Instance,
    solution: DiscreteSolution,
):
    """Fast deterministic capacity-feasible allocation for candidate ranking."""

    info = build_event_info(instance, solution)

    local_cpu = {
        task_id: instance.uavs[uav_id].local_cpu_ghz
        for uav_id, order in info.local_order.items()
        for task_id in order
    }

    bandwidth: dict[tuple[str, str], float] = {}
    mec_cpu: dict[tuple[str, str], float] = {}
    for mec_id, mec in instance.mecs.items():
        pairs = [
            pair
            for pair in info.active_uav_mec_pairs
            if pair[1] == mec_id
        ]
        if not pairs:
            continue
        bw_share = mec.bandwidth_mhz / len(pairs)
        cpu_share = mec.cpu_ghz / len(pairs)
        for pair in pairs:
            bandwidth[pair] = bw_share
            mec_cpu[pair] = cpu_share

    reduced = evaluate_reduced_resources(
        instance,
        solution,
        info,
        bandwidth_mhz=bandwidth,
        mec_cpu_ghz=mec_cpu,
        local_cpu_ghz=local_cpu,
    )
    return info, reduced


def _normalized_violations(
    instance: Instance,
    reduced: ReducedResourceEvaluation,
) -> list[float]:
    values: list[float] = []

    for task_id, task in instance.tasks.items():
        violation = max(0.0, reduced.deadline_violation_s[task_id])
        values.append(violation / max(1.0, task.deadline_s))

    avg_violation = max(
        0.0,
        reduced.avg_delay_s - instance.avg_delay_budget_s,
    )
    values.append(
        avg_violation / max(1.0, instance.avg_delay_budget_s)
    )

    for uav_id, uav in instance.uavs.items():
        cycle_violation = max(
            0.0,
            reduced.cycle_violation_s[uav_id],
        )
        values.append(
            cycle_violation / max(1.0, instance.cycle_s)
        )

        battery_violation = max(
            0.0,
            reduced.battery_violation_j[uav_id],
        )
        values.append(
            battery_violation / max(1.0, uav.energy_budget_j)
        )

    return values


def evaluate_initial_proxy(
    instance: Instance,
    solution: DiscreteSolution,
) -> ProxyEvaluation:
    """Evaluate a candidate with a cheap capacity-feasible latency proxy."""

    info, reduced = _proxy_resource_allocation(instance, solution)
    normalized = _normalized_violations(instance, reduced)
    score = ProxyScore(
        violated_constraints=sum(value > 1e-12 for value in normalized),
        max_normalized_violation=max(normalized, default=0.0),
        sum_normalized_violation=sum(normalized),
        total_energy_j=reduced.total_energy_j,
        total_distance_m=sum(info.route_distance_m.values()),
    )
    return ProxyEvaluation(reduced=reduced, score=score)


def _critical_local_tasks(
    instance: Instance,
    solution: DiscreteSolution,
    proxy: ProxyEvaluation,
    *,
    limit: int,
) -> list[str]:
    info = build_event_info(instance, solution)
    ranked: list[tuple[tuple[float, float, float, float, str], str]] = []

    for uav_id, order in info.local_order.items():
        for idx, task_id in enumerate(order):
            task = instance.tasks[task_id]
            completion = proxy.reduced.task_completion_s[task_id]
            lateness = max(
                0.0,
                proxy.reduced.deadline_violation_s[task_id],
            )
            lateness_norm = lateness / max(1.0, task.deadline_s)
            completion_ratio = (
                completion - task.release_s
            ) / max(1.0, task.deadline_s)
            downstream = len(order) - idx - 1
            queue_pressure = (
                task.workload_gcycles
                * (1.0 + downstream)
                / max(1.0, task.deadline_s)
            )
            rank = (
                1.0 if lateness > 0.0 else 0.0,
                lateness_norm,
                completion_ratio,
                queue_pressure,
                task_id,
            )
            ranked.append((rank, task_id))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [task_id for _, task_id in ranked[:limit]]


def _positions(
    route: Route,
) -> tuple[dict[str, int], dict[str, int]]:
    task_pos: dict[str, int] = {}
    contact_pos: dict[str, int] = {}
    for idx, stop in enumerate(route.stops):
        if stop.kind is StopType.TASK:
            task_pos[stop.ref_id] = idx
        elif stop.kind is StopType.CONTACT:
            contact_pos[stop.ref_id] = idx
    return task_pos, contact_pos


def _next_visit_id(
    solution: DiscreteSolution,
    uav_id: str,
) -> str:
    prefix = f"G_{uav_id}_"
    used = {
        visit_id
        for visit_id in solution.contact_visits
        if visit_id.startswith(prefix)
    }
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"


def _task_owner(solution: DiscreteSolution, task_id: str) -> str:
    return next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )


def _insert_contact_candidate(
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


def _reuse_contact_candidate(
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


def _best_new_contact_locations(
    instance: Instance,
    solution: DiscreteSolution,
    task_id: str,
    *,
    limit: int,
) -> list[tuple[float, str, int]]:
    owner = _task_owner(solution, task_id)
    route = solution.routes[owner]
    task_pos, _ = _positions(route)
    task_idx = task_pos[task_id]

    candidates: list[tuple[float, str, int]] = []
    for point_id, point in instance.contact_points.items():
        point_xy = (point.x, point.y)
        best: tuple[float, int] | None = None

        for insert_pos in range(task_idx + 1, len(route.stops)):
            prev_stop = route.stops[insert_pos - 1]
            next_stop = route.stops[insert_pos]
            prev_xy = stop_xy(instance, solution, prev_stop)
            next_xy = stop_xy(instance, solution, next_stop)
            detour = (
                distance(prev_xy, point_xy)
                + distance(point_xy, next_xy)
                - distance(prev_xy, next_xy)
            )
            if best is None or detour < best[0]:
                best = (detour, insert_pos)

        if best is not None:
            candidates.append((best[0], point_id, best[1]))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[:limit]


def _existing_contacts_after_task(
    solution: DiscreteSolution,
    task_id: str,
) -> Iterable[str]:
    owner = _task_owner(solution, task_id)
    route = solution.routes[owner]
    task_pos, contact_pos = _positions(route)
    return [
        visit_id
        for visit_id, pos in sorted(
            contact_pos.items(),
            key=lambda item: item[1],
        )
        if pos > task_pos[task_id]
    ]


def _strictly_better(
    candidate: ProxyScore,
    incumbent: ProxyScore,
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


def build_mec_assisted_initial_solution(
    instance: Instance,
    *,
    base_solution: DiscreteSolution | None = None,
    config: GreedyMECRepairConfig | None = None,
) -> DiscreteSolution:
    """Repair the route-only seed with greedy MEC contacts and batch reuse."""

    cfg = config or GreedyMECRepairConfig()
    current = (
        deepcopy(base_solution)
        if base_solution is not None
        else build_greedy_initial_solution(instance)
    )
    validate_solution(instance, current)
    current_proxy = evaluate_initial_proxy(instance, current)

    initial_score = current_proxy.score.key
    accepted_moves: list[dict[str, object]] = []

    for step in range(1, cfg.max_steps + 1):
        if current_proxy.score.violated_constraints == 0:
            break

        critical = _critical_local_tasks(
            instance,
            current,
            current_proxy,
            limit=cfg.critical_task_limit,
        )

        best_solution: DiscreteSolution | None = None
        best_proxy: ProxyEvaluation | None = None
        best_move: dict[str, object] | None = None

        for task_id in critical:
            for visit_id in _existing_contacts_after_task(current, task_id):
                candidate = _reuse_contact_candidate(
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
                if best_proxy is None or proxy.score.key < best_proxy.score.key:
                    best_solution = candidate
                    best_proxy = proxy
                    best_move = {
                        "type": "reuse_contact",
                        "task_id": task_id,
                        "visit_id": visit_id,
                    }

            owner = _task_owner(current, task_id)
            if (
                len(current.routes[owner].contact_visit_ids())
                >= instance.max_contacts_per_uav
            ):
                continue

            for detour_m, point_id, insert_pos in _best_new_contact_locations(
                instance,
                current,
                task_id,
                limit=cfg.new_contact_candidate_limit,
            ):
                candidate = _insert_contact_candidate(
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
                if best_proxy is None or proxy.score.key < best_proxy.score.key:
                    best_solution = candidate
                    best_proxy = proxy
                    best_move = {
                        "type": "insert_contact",
                        "task_id": task_id,
                        "point_id": point_id,
                        "insert_pos": insert_pos,
                        "detour_m": detour_m,
                    }

        if best_solution is None or best_proxy is None or best_move is None:
            break

        current = best_solution
        current_proxy = best_proxy
        accepted_moves.append({"step": step, **best_move})

    final_offloaded = sum(
        decision.mode is ExecutionMode.OFFLOAD
        for decision in current.task_decisions.values()
    )
    current.metadata.update(
        {
            "builder": "parallel_greedy_insertion_2opt_mec_repair",
            "phase": "mec_assisted_initial_solution",
            "mec_repair_steps": len(accepted_moves),
            "mec_repair_moves": accepted_moves,
            "proxy_initial_score": initial_score,
            "proxy_final_score": current_proxy.score.key,
            "proxy_feasible": current_proxy.score.violated_constraints == 0,
            "offloaded_tasks": final_offloaded,
            "contact_visits": len(current.contact_visits),
        }
    )
    validate_solution(instance, current)
    return current
