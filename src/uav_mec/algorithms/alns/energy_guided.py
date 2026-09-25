from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import partial, update_wrapper
from time import perf_counter
from typing import Any

import numpy as np

from uav_mec.algorithms.initial import evaluate_initial_proxy
from uav_mec.domain import (
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
from uav_mec.optimization.resource import (
    ResourceSolveResult,
    fast_feasibility_precheck,
)

from .operators import (
    _apply_local_insertion,
    _cleanup_orphan_contacts,
    _destroy_tasks,
    _options_for_task,
)
from .problem_operators import (
    ProblemOperatorConfig,
    _apply_task_decision,
    _batch_merge_candidates,
    _best_new_contact_options,
    _contact_removal_candidates,
    _insert_new_contact_for_task,
    _mode_candidates,
    _structural_elite_candidates,
)
from .state import UavMecState


@dataclass(frozen=True)
class EnergyGuidedESIConfig:
    """Restricted energy-guided exact-intensification budget."""

    hotspot_task_limit: int = 6
    route_options_per_task: int = 5
    existing_contacts_per_route_option: int = 2
    new_contacts_per_mec: int = 1
    new_contact_options_per_route: int = 3
    contact_hotspot_limit: int = 2
    proxy_pool_limit: int = 10
    cvx_shortlist_limit: int = 3
    exploratory_fallback_limit: int = 1
    fallback_structural_limit: int = 2
    deadline_dual_weight: float = 0.10
    cycle_dual_weight: float = 0.05
    min_proxy_gain_j: float = 0.0


@dataclass
class _EnergyCandidate:
    label: str
    family: str
    solution: DiscreteSolution
    hotspot_j: float
    source_task: str | None = None
    source_contact: str | None = None
    route_delta_j: float | None = None


def _strict_stage1(result: ResourceSolveResult) -> bool:
    return bool(
        result.feasible
        and str(
            result.diagnostics.get(
                "stage1_status",
                result.status,
            )
        )
        == "optimal"
    )


def _task_owner(
    solution: DiscreteSolution,
    task_id: str,
) -> str:
    return next(
        uav_id
        for uav_id, route in solution.routes.items()
        if task_id in route.task_ids()
    )


def _task_route_removal_saving_m(
    state: UavMecState,
    task_id: str,
) -> float:
    owner = _task_owner(state.solution, task_id)
    route = state.solution.routes[owner]
    idx = next(
        idx
        for idx, stop in enumerate(route.stops)
        if (
            stop.kind is StopType.TASK
            and stop.ref_id == task_id
        )
    )
    prev_xy = stop_xy(
        state.instance,
        state.solution,
        route.stops[idx - 1],
    )
    task_xy = stop_xy(
        state.instance,
        state.solution,
        route.stops[idx],
    )
    next_xy = stop_xy(
        state.instance,
        state.solution,
        route.stops[idx + 1],
    )
    return max(
        0.0,
        distance(prev_xy, task_xy)
        + distance(task_xy, next_xy)
        - distance(prev_xy, next_xy),
    )


def _contact_detour_saving_m(
    state: UavMecState,
    visit_id: str,
) -> float:
    visit = state.solution.contact_visits[visit_id]
    route = state.solution.routes[visit.uav_id]
    idx = next(
        idx
        for idx, stop in enumerate(route.stops)
        if (
            stop.kind is StopType.CONTACT
            and stop.ref_id == visit_id
        )
    )
    prev_xy = stop_xy(
        state.instance,
        state.solution,
        route.stops[idx - 1],
    )
    contact_xy = stop_xy(
        state.instance,
        state.solution,
        route.stops[idx],
    )
    next_xy = stop_xy(
        state.instance,
        state.solution,
        route.stops[idx + 1],
    )
    return max(
        0.0,
        distance(prev_xy, contact_xy)
        + distance(contact_xy, next_xy)
        - distance(prev_xy, next_xy),
    )


def _normalized_dual(
    result: ResourceSolveResult,
    name: str,
    *,
    group_prefix: str,
) -> float:
    value = max(0.0, float(result.stage1_duals.get(name, 0.0)))
    group = [
        max(0.0, float(dual))
        for key, dual in result.stage1_duals.items()
        if key.startswith(group_prefix)
    ]
    scale = max(group, default=0.0)
    if scale <= 1e-12:
        return 0.0
    return min(1.0, value / scale)


def _task_energy_hotspots(
    state: UavMecState,
    result: ResourceSolveResult,
    *,
    guidance: EnergyGuidedESIConfig,
) -> list[dict[str, Any]]:
    """Attribute current exact Stage-1 UAV energy to task hotspots."""

    info = build_event_info(state.instance, state.solution)
    local_cpu = result.stage1_values.get("local_cpu_ghz", {})
    tau = result.stage1_values.get("tau_s", {})

    rows: list[dict[str, Any]] = []
    for task_id, task in state.instance.tasks.items():
        owner = info.task_owner[task_id]
        uav = state.instance.uavs[owner]
        route_saving_m = _task_route_removal_saving_m(
            state,
            task_id,
        )
        route_j = (
            route_saving_m
            / max(1e-12, uav.speed_mps)
            * uav.flight_power_w
        )

        decision = state.solution.task_decisions[task_id]
        compute_j = 0.0
        contact_j = 0.0

        if decision.mode is ExecutionMode.LOCAL:
            f_ghz = float(local_cpu.get(task_id, 0.0))
            if f_ghz > 0.0:
                compute_j = (
                    uav.kappa
                    * 1e27
                    * task.workload_gcycles
                    * f_ghz
                    * f_ghz
                )
        elif decision.contact_visit_id is not None:
            visit_id = decision.contact_visit_id
            visit_tau = max(0.0, float(tau.get(visit_id, 0.0)))
            batch = info.batch_tasks.get(visit_id, [])
            total_data = sum(
                state.instance.tasks[item].data_mbit
                for item in batch
            )
            share = (
                task.data_mbit / total_data
                if total_data > 1e-12
                else 0.0
            )
            contact_j = (
                uav.hover_power_w + uav.tx_power_w
            ) * visit_tau * share

        energy_j = route_j + compute_j + contact_j
        deadline_dual = _normalized_dual(
            result,
            f"deadline::{task_id}",
            group_prefix="deadline::",
        )
        cycle_dual = _normalized_dual(
            result,
            f"cycle::{owner}",
            group_prefix="cycle::",
        )
        priority_j = energy_j * (
            1.0
            + guidance.deadline_dual_weight * deadline_dual
            + guidance.cycle_dual_weight * cycle_dual
        )

        rows.append(
            {
                "task_id": task_id,
                "owner": owner,
                "mode": decision.mode.value,
                "energy_j": energy_j,
                "route_j": route_j,
                "compute_j": compute_j,
                "contact_j": contact_j,
                "deadline_dual_norm": deadline_dual,
                "cycle_dual_norm": cycle_dual,
                "priority_j": priority_j,
            }
        )

    rows.sort(
        key=lambda item: (
            float(item["priority_j"]),
            float(item["energy_j"]),
            str(item["task_id"]),
        ),
        reverse=True,
    )
    return rows


def _contact_energy_hotspots(
    state: UavMecState,
    result: ResourceSolveResult,
) -> list[dict[str, Any]]:
    info = build_event_info(state.instance, state.solution)
    tau = result.stage1_values.get("tau_s", {})
    rows: list[dict[str, Any]] = []

    for visit_id, visit in state.solution.contact_visits.items():
        batch = info.batch_tasks.get(visit_id, [])
        if not batch:
            continue
        uav = state.instance.uavs[visit.uav_id]
        upload_j = (
            uav.hover_power_w + uav.tx_power_w
        ) * max(0.0, float(tau.get(visit_id, 0.0)))
        detour_j = (
            _contact_detour_saving_m(state, visit_id)
            / max(1e-12, uav.speed_mps)
            * uav.flight_power_w
        )
        data_mbit = sum(
            state.instance.tasks[task_id].data_mbit
            for task_id in batch
        )
        total_j = upload_j + detour_j
        rows.append(
            {
                "visit_id": visit_id,
                "uav_id": visit.uav_id,
                "batch_size": len(batch),
                "data_mbit": data_mbit,
                "upload_j": upload_j,
                "detour_j": detour_j,
                "energy_j": total_j,
                "energy_per_mbit": (
                    total_j / max(1e-9, data_mbit)
                ),
            }
        )

    rows.sort(
        key=lambda item: (
            float(item["energy_per_mbit"]),
            float(item["energy_j"]),
            str(item["visit_id"]),
        ),
        reverse=True,
    )
    return rows


def _energy_aware_route_options(
    state: UavMecState,
    task_id: str,
    *,
    limit: int,
):
    source = _task_owner(state.solution, task_id)
    source_uav = state.instance.uavs[source]
    removal_j = (
        _task_route_removal_saving_m(state, task_id)
        / max(1e-12, source_uav.speed_mps)
        * source_uav.flight_power_w
    )

    destroyed = _destroy_tasks(state, [task_id])
    options = _options_for_task(destroyed, task_id)

    scored = []
    for option in options:
        target_uav = state.instance.uavs[option.uav_id]
        insertion_j = (
            max(0.0, option.delta_distance_m)
            / max(1e-12, target_uav.speed_mps)
            * target_uav.flight_power_w
        )
        route_delta_j = insertion_j - removal_j
        scored.append(
            (
                (
                    option.cycle_overflow_s,
                    option.deadline_lb_violation_s,
                    route_delta_j,
                    option.route_task_count,
                    option.uav_id,
                    option.position,
                ),
                route_delta_j,
                destroyed,
                option,
            )
        )

    # Preserve one best option from every UAV first, then fill globally. This
    # makes cross-UAV relocation explicit without reverting to family quotas.
    selected = []
    seen_uavs: set[str] = set()
    for item in sorted(scored, key=lambda row: row[0]):
        option = item[3]
        if option.uav_id in seen_uavs:
            continue
        selected.append(item)
        seen_uavs.add(option.uav_id)
        if len(selected) >= limit:
            return selected

    for item in sorted(scored, key=lambda row: row[0]):
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _coupled_task_candidates(
    state: UavMecState,
    hotspot: dict[str, Any],
    *,
    guidance: EnergyGuidedESIConfig,
) -> list[_EnergyCandidate]:
    task_id = str(hotspot["task_id"])
    candidates: list[_EnergyCandidate] = []

    for _, route_delta_j, destroyed, option in _energy_aware_route_options(
        state,
        task_id,
        limit=guidance.route_options_per_task,
    ):
        candidate_state = destroyed.copy()
        _apply_local_insertion(
            candidate_state,
            task_id,
            option,
        )
        validate_solution(
            candidate_state.instance,
            candidate_state.solution,
        )

        local_candidate = deepcopy(candidate_state.solution)
        if local_candidate != state.solution:
            candidates.append(
                _EnergyCandidate(
                    label=(
                        "energy_route_local::"
                        f"{task_id}->{option.uav_id}@{option.position}"
                    ),
                    family="route_local",
                    solution=local_candidate,
                    hotspot_j=float(hotspot["priority_j"]),
                    source_task=task_id,
                    route_delta_j=route_delta_j,
                )
            )

        existing = [
            decision
            for decision in _mode_candidates(
                candidate_state,
                task_id,
            )
            if decision.mode is ExecutionMode.OFFLOAD
        ]
        for decision in existing[
            : guidance.existing_contacts_per_route_option
        ]:
            coupled = _apply_task_decision(
                candidate_state,
                task_id,
                decision,
            )
            if coupled is None or coupled == state.solution:
                continue
            candidates.append(
                _EnergyCandidate(
                    label=(
                        "energy_route_offload_reuse::"
                        f"{task_id}->{option.uav_id}@{option.position}"
                        f"::{decision.contact_visit_id}"
                    ),
                    family="route_offload",
                    solution=coupled,
                    hotspot_j=float(hotspot["priority_j"]),
                    source_task=task_id,
                    route_delta_j=route_delta_j,
                )
            )

        new_options = _best_new_contact_options(
            candidate_state,
            task_id,
            per_mec=guidance.new_contacts_per_mec,
        )
        for _, point_id, insert_pos in new_options[
            : guidance.new_contact_options_per_route
        ]:
            coupled = _insert_new_contact_for_task(
                candidate_state,
                task_id,
                point_id,
                insert_pos,
            )
            if coupled is None or coupled == state.solution:
                continue
            candidates.append(
                _EnergyCandidate(
                    label=(
                        "energy_route_offload_new::"
                        f"{task_id}->{option.uav_id}@{option.position}"
                        f"::{point_id}@{insert_pos}"
                    ),
                    family="route_offload",
                    solution=coupled,
                    hotspot_j=float(hotspot["priority_j"]),
                    source_task=task_id,
                    route_delta_j=route_delta_j,
                )
            )

    return candidates


def _contact_hotspot_candidates(
    state: UavMecState,
    hotspots: list[dict[str, Any]],
    *,
    guidance: EnergyGuidedESIConfig,
) -> list[_EnergyCandidate]:
    candidates: list[_EnergyCandidate] = []
    focus = {
        str(row["visit_id"]): row
        for row in hotspots[: guidance.contact_hotspot_limit]
    }
    if not focus:
        return candidates

    for label, solution in _contact_removal_candidates(state):
        visit_id = label.split("::", 1)[1]
        if visit_id not in focus:
            continue
        candidates.append(
            _EnergyCandidate(
                label="energy_" + label,
                family="contact_remove",
                solution=solution,
                hotspot_j=float(focus[visit_id]["energy_j"]),
                source_contact=visit_id,
            )
        )

    for label, solution in _batch_merge_candidates(state):
        body = label.split("::", 1)[1]
        source = body.split("->", 1)[0]
        if source not in focus:
            continue
        candidates.append(
            _EnergyCandidate(
                label="energy_" + label,
                family="batch_merge",
                solution=solution,
                hotspot_j=float(focus[source]["energy_j"]),
                source_contact=source,
            )
        )

    return candidates


def _solution_signature(solution: DiscreteSolution) -> tuple[Any, ...]:
    return (
        tuple(
            (
                uav_id,
                tuple(solution.routes[uav_id].labels()),
            )
            for uav_id in sorted(solution.routes)
        ),
        tuple(
            sorted(
                (
                    visit_id,
                    visit.uav_id,
                    visit.point_id,
                )
                for visit_id, visit
                in solution.contact_visits.items()
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
                in solution.task_decisions.items()
            )
        ),
    )


def _cvx_cost_proxy(
    state: UavMecState,
    solution: DiscreteSolution,
) -> float:
    info = build_event_info(state.instance, solution)
    local_tasks = sum(
        decision.mode is ExecutionMode.LOCAL
        for decision in solution.task_decisions.values()
    )
    return (
        1.0
        + 0.20 * len(solution.contact_visits)
        + 0.35 * len(info.active_uav_mec_pairs)
        + 0.02 * local_tasks
    )


def _screen_candidates(
    state: UavMecState,
    candidates: list[_EnergyCandidate],
    *,
    guidance: EnergyGuidedESIConfig,
) -> tuple[list[_EnergyCandidate], list[dict[str, Any]]]:
    baseline_proxy = evaluate_initial_proxy(
        state.instance,
        state.solution,
    )
    baseline_energy = float(
        baseline_proxy.score.total_energy_j
    )

    seen: set[tuple[Any, ...]] = set()
    ranked: list[tuple[tuple[float, ...], _EnergyCandidate, dict[str, Any]]] = []

    for candidate in candidates:
        signature = _solution_signature(candidate.solution)
        if signature in seen:
            continue
        seen.add(signature)

        info = build_event_info(
            state.instance,
            candidate.solution,
        )
        precheck = fast_feasibility_precheck(
            state.instance,
            candidate.solution,
            info,
        )
        if not precheck.feasible:
            continue

        proxy = evaluate_initial_proxy(
            state.instance,
            candidate.solution,
        )
        proxy_gain_j = (
            baseline_energy
            - float(proxy.score.total_energy_j)
        )
        cost_proxy = _cvx_cost_proxy(
            state,
            candidate.solution,
        )
        efficiency = proxy_gain_j / max(1e-9, cost_proxy)

        meta = {
            "move": candidate.label,
            "family": candidate.family,
            "hotspot_j": candidate.hotspot_j,
            "proxy_gain_j": proxy_gain_j,
            "cvx_cost_proxy": cost_proxy,
            "proxy_gain_per_cost": efficiency,
            "proxy_violations": int(
                proxy.score.violated_constraints
            ),
            "route_delta_j": candidate.route_delta_j,
            "source_task": candidate.source_task,
            "source_contact": candidate.source_contact,
        }
        key = (
            efficiency,
            proxy_gain_j,
            candidate.hotspot_j,
            -float(proxy.score.violated_constraints),
            -float(proxy.score.max_normalized_violation),
        )
        ranked.append((key, candidate, meta))

    ranked.sort(key=lambda row: row[0], reverse=True)
    pool = ranked[: guidance.proxy_pool_limit]

    positive = [
        item
        for item in pool
        if float(item[2]["proxy_gain_j"])
        >= guidance.min_proxy_gain_j
    ]
    selected = positive[: guidance.cvx_shortlist_limit]

    # Proxy allocation can be conservative. When fewer than k positive-gain
    # candidates survive, fill remaining exact slots with high-hotspot,
    # precheck-feasible candidates instead of forcing a false negative.
    if (
        len(selected) < guidance.cvx_shortlist_limit
        and guidance.exploratory_fallback_limit > 0
    ):
        remaining = [
            item
            for item in pool
            if item not in selected
        ]
        remaining.sort(
            key=lambda row: (
                float(row[2]["hotspot_j"]),
                float(row[2]["proxy_gain_per_cost"]),
            ),
            reverse=True,
        )
        fill = min(
            guidance.exploratory_fallback_limit,
            guidance.cvx_shortlist_limit - len(selected),
        )
        selected.extend(remaining[:fill])

    return (
        [candidate for _, candidate, _ in selected],
        [meta for _, _, meta in ranked],
    )


def energy_guided_intensification(
    state: UavMecState,
    *,
    config: ProblemOperatorConfig,
    objective,
    guidance: EnergyGuidedESIConfig | None = None,
    max_rounds: int = 1,
    tolerance: float = 1e-12,
    max_runtime_s: float | None = None,
) -> tuple[UavMecState, dict[str, object]]:
    """Exact ESI driven by current Stage-1 energy hotspots.

    Candidate generation is deliberately different from generic B-ALNS:
    high-energy tasks are relocated jointly with local/offload/contact choices,
    then a cheap energy-opportunity screen spends exact CVX calls only on the
    best expected energy-per-cost candidates.
    """

    guide = guidance or EnergyGuidedESIConfig()
    if max_runtime_s is not None and max_runtime_s < 0:
        raise ValueError("max_runtime_s must be non-negative")

    started = perf_counter()
    deadline = (
        None
        if max_runtime_s is None
        else started + max_runtime_s
    )
    current = state.copy()

    stats: dict[str, object] = {
        "rounds": 0,
        "generated_candidates": 0,
        "proxy_ranked_candidates": 0,
        "candidates_evaluated": 0,
        "exact_cvx_calls": 0,
        "strict_candidates": 0,
        "improvements": 0,
        "accepted_moves": [],
        "evaluated_moves": [],
        "hotspot_tasks": [],
        "contact_hotspots": [],
        "budget_exhausted": False,
        "runtime_s": 0.0,
        "exact_runtime_s": 0.0,
        "exact_improvement_j": 0.0,
        "energy_gain_per_cvx_j": 0.0,
        "energy_gain_per_second_jps": 0.0,
    }

    def exhausted() -> bool:
        value = (
            deadline is not None
            and perf_counter() >= deadline
        )
        if value:
            stats["budget_exhausted"] = True
        return value

    for round_idx in range(max_rounds):
        if exhausted():
            break

        baseline_result = objective.solve(
            current.instance,
            current.solution,
        )
        if not _strict_stage1(baseline_result):
            break

        baseline_energy = float(
            baseline_result.energy_stage1_j
        )
        task_hotspots = _task_energy_hotspots(
            current,
            baseline_result,
            guidance=guide,
        )
        contact_hotspots = _contact_energy_hotspots(
            current,
            baseline_result,
        )
        stats["hotspot_tasks"] = task_hotspots[
            : guide.hotspot_task_limit
        ]
        stats["contact_hotspots"] = contact_hotspots[
            : guide.contact_hotspot_limit
        ]

        candidates: list[_EnergyCandidate] = []
        for hotspot in task_hotspots[
            : guide.hotspot_task_limit
        ]:
            candidates.extend(
                _coupled_task_candidates(
                    current,
                    hotspot,
                    guidance=guide,
                )
            )
        candidates.extend(
            _contact_hotspot_candidates(
                current,
                contact_hotspots,
                guidance=guide,
            )
        )

        # If the new energy-guided neighborhood is unexpectedly sparse, retain
        # a very small legacy structural fallback rather than wasting an elite
        # trigger.
        if len(candidates) < guide.cvx_shortlist_limit:
            for label, solution in _structural_elite_candidates(
                current,
                config=config,
            )[: guide.fallback_structural_limit]:
                candidates.append(
                    _EnergyCandidate(
                        label="fallback::" + label,
                        family="fallback",
                        solution=solution,
                        hotspot_j=0.0,
                    )
                )

        stats["generated_candidates"] = int(
            stats["generated_candidates"]
        ) + len(candidates)

        shortlist, ranking = _screen_candidates(
            current,
            candidates,
            guidance=guide,
        )
        stats["proxy_ranked_candidates"] = int(
            stats["proxy_ranked_candidates"]
        ) + len(ranking)

        if not shortlist:
            break

        best_solution: DiscreteSolution | None = None
        best_label: str | None = None
        best_value = baseline_energy
        evaluated = list(stats["evaluated_moves"])

        ranking_map = {
            str(row["move"]): row
            for row in ranking
        }

        for candidate in shortlist:
            if exhausted():
                break
            before_calls = int(getattr(objective, "calls", 0))
            before_runtime_count = len(
                getattr(objective, "solve_runtimes_s", [])
            )
            candidate_started = perf_counter()
            result = objective.solve(
                current.instance,
                candidate.solution,
            )
            wall_runtime_s = (
                perf_counter() - candidate_started
            )
            exact_runtimes = getattr(
                objective,
                "solve_runtimes_s",
                [],
            )
            if len(exact_runtimes) > before_runtime_count:
                exact_runtime_s = float(
                    exact_runtimes[-1]
                )
            else:
                exact_runtime_s = wall_runtime_s

            new_call = int(
                getattr(objective, "calls", 0)
            ) > before_calls
            stats["candidates_evaluated"] = int(
                stats["candidates_evaluated"]
            ) + 1
            if new_call:
                stats["exact_cvx_calls"] = int(
                    stats["exact_cvx_calls"]
                ) + 1
                stats["exact_runtime_s"] = float(
                    stats["exact_runtime_s"]
                ) + exact_runtime_s

            strict = _strict_stage1(result)
            if strict:
                stats["strict_candidates"] = int(
                    stats["strict_candidates"]
                ) + 1
            value = (
                float(result.energy_stage1_j)
                if strict
                else float("inf")
            )
            improvement_j = (
                baseline_energy - value
                if strict
                else None
            )

            row = dict(
                ranking_map.get(
                    candidate.label,
                    {"move": candidate.label},
                )
            )
            row.update(
                {
                    "round": round_idx + 1,
                    "strict": strict,
                    "objective_j": (
                        value if np.isfinite(value) else None
                    ),
                    "improvement_j": improvement_j,
                    "exact_runtime_s": exact_runtime_s,
                    "new_cvx_call": new_call,
                }
            )
            evaluated.append(row)

            scale = max(
                1.0,
                abs(best_value),
                abs(value),
            )
            acceptance_tol = max(
                tolerance * scale,
                config.elite_min_improvement_j,
                config.elite_min_improvement_rel * scale,
            )
            if (
                strict
                and value < best_value - acceptance_tol
            ):
                best_value = value
                best_label = candidate.label
                best_solution = candidate.solution

        stats["evaluated_moves"] = evaluated
        stats["rounds"] = int(stats["rounds"]) + 1

        if best_solution is None or best_label is None:
            break

        gain_j = baseline_energy - best_value
        current.solution = deepcopy(best_solution)
        current.invalidate()
        stats["improvements"] = int(
            stats["improvements"]
        ) + 1
        stats["exact_improvement_j"] = float(
            stats["exact_improvement_j"]
        ) + gain_j
        accepted = list(stats["accepted_moves"])
        accepted.append(
            {
                "move": best_label,
                "objective": best_value,
                "improvement_j": gain_j,
                "improvement_pct": (
                    100.0
                    * gain_j
                    / max(1.0, abs(baseline_energy))
                ),
            }
        )
        stats["accepted_moves"] = accepted

    stats["runtime_s"] = perf_counter() - started
    candidate_count = int(stats["candidates_evaluated"])
    cvx_count = int(stats["exact_cvx_calls"])
    total_gain = float(stats["exact_improvement_j"])
    exact_runtime = float(stats["exact_runtime_s"])
    stats["energy_gain_per_cvx_j"] = (
        total_gain / cvx_count
        if cvx_count > 0
        else 0.0
    )
    stats["energy_gain_per_second_jps"] = (
        total_gain / exact_runtime
        if exact_runtime > 1e-12
        else 0.0
    )
    stats["strict_hit_rate"] = (
        float(stats["strict_candidates"]) / candidate_count
        if candidate_count > 0
        else 0.0
    )
    stats["accepted_hit_rate"] = (
        float(stats["improvements"]) / candidate_count
        if candidate_count > 0
        else 0.0
    )

    validate_solution(
        current.instance,
        current.solution,
    )
    current.invalidate()
    return current, stats


def make_energy_guided_intensifier(
    guidance: EnergyGuidedESIConfig | None = None,
):
    operator = partial(
        energy_guided_intensification,
        guidance=guidance or EnergyGuidedESIConfig(),
    )
    update_wrapper(operator, energy_guided_intensification)
    return operator
