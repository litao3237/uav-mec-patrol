"""P0 round-2: conservative inter-UAV structural neighborhoods.

This experimental module never replaces the original ESI shortlist. A caller
first runs the unchanged ESI, then applies these additional CVX-validated moves
from that exact validated elite. Modes/contacts are repaired after changing
routes, and only strictly validated energy improvements are accepted.

Geometric pre-ranking uses task-only route length *only as a screening proxy*.
The actual objective is fixed-structure Stage-1 CVXPY via the injected oracle.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Callable

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
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.geometry import distance
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import fast_feasibility_precheck

from .evaluator import solution_signature
from .operators import _cleanup_orphan_contacts


FAMILIES = ("swap", "two_opt_star", "block_relocate")


@dataclass(frozen=True)
class CrossRouteConfig:
    geometric_pool_per_family: int = 18
    cvx_per_round: int = 6
    max_rounds: int = 2
    block_size: int = 2
    min_improvement_j: float = 1.0
    min_improvement_rel: float = 1e-4


@dataclass(frozen=True)
class _Proposal:
    family: str
    label: str
    new_orders: dict[str, tuple[str, ...]]
    geometric_delta_m: float


def _task_only_length(instance, task_order: tuple[str, ...]) -> float:
    points = [instance.depot_xy]
    points.extend((instance.tasks[t].x, instance.tasks[t].y) for t in task_order)
    points.append(instance.depot_xy)
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def _task_orders(solution: DiscreteSolution) -> dict[str, tuple[str, ...]]:
    return {
        u: tuple(route.task_ids())
        for u, route in solution.routes.items()
    }


def _proposals(instance, solution, family: str) -> list[_Proposal]:
    """Enumerate true cross-route moves, prioritizing geometric deltas."""
    if family not in FAMILIES:
        raise ValueError(family)
    orders = _task_orders(solution)
    uavs = sorted(orders)
    lengths = {u: _task_only_length(instance, orders[u]) for u in uavs}
    proposals = []
    for idx, u in enumerate(uavs):
        a = orders[u]
        if not a:
            continue
        destinations = uavs[idx + 1:] if family != "block_relocate" else [
            candidate for candidate in uavs if candidate != u
        ]
        for v in destinations:
            b = orders[v]
            if family == "swap":
                if not b:
                    continue
                changes = (
                    (
                        f"{a[i]}<->{b[j]}::{u}/{v}",
                        a[:i] + (b[j],) + a[i + 1:],
                        b[:j] + (a[i],) + b[j + 1:],
                    )
                    for i in range(len(a))
                    for j in range(len(b))
                )
            elif family == "two_opt_star":
                # Exchanging route suffixes is the inter-route 2-opt* move;
                # cuts exclude the empty/unchanged exchange and permit
                # a UAV to receive a different task count.
                changes = (
                    (
                        f"{u}@{i}<->{v}@{j}",
                        a[:i] + b[j:],
                        b[:j] + a[i:],
                    )
                    for i in range(1, len(a) + 1)
                    for j in range(1, len(b) + 1)
                    if i < len(a) or j < len(b)
                )
            else:
                if len(a) < 2:
                    continue
                # Block relocation moves contiguous tasks (not contacts)
                # to any insertion slot of a *different* UAV.
                size = 2
                changes = (
                    (
                        f"{u}[{i}:{i+size}]->{v}@{j}",
                        a[:i] + a[i + size:],
                        b[:j] + a[i:i + size] + b[j:],
                    )
                    for i in range(len(a) - size + 1)
                    for j in range(len(b) + 1)
                )
            for label, new_a, new_b in changes:
                if new_a == a and new_b == b:
                    continue
                new_orders = {u: new_a, v: new_b}
                delta = (
                    _task_only_length(instance, new_a)
                    + _task_only_length(instance, new_b)
                    - lengths[u] - lengths[v]
                )
                proposals.append(_Proposal(family, f"{family}::{label}", new_orders, delta))
    proposals.sort(key=lambda p: (p.geometric_delta_m, p.label))
    return proposals


def _rebuild_contacts_for_route(
    solution: DiscreteSolution,
    uav_id: str,
    original: Route,
    tasks: tuple[str, ...],
) -> Route:
    """Keep nonempty original contacts in order and after their live batches.

    Contact visit IDs/positions stay tied to their original UAV. Tasks that
    cross UAV boundaries become local first; unaffected offloaded tasks stay
    assigned to their original contacts. Reinsert contact at the original
    task ordinal or later when the batch's latest task has moved.
    """
    old_task_ordinal = 0
    contacts = []
    for stop in original.stops[1:-1]:
        if stop.kind is StopType.TASK:
            old_task_ordinal += 1
        elif stop.kind is StopType.CONTACT:
            batch = [
                task_id for task_id, decision in solution.task_decisions.items()
                if (
                    decision.mode is ExecutionMode.OFFLOAD
                    and decision.contact_visit_id == stop.ref_id
                    and task_id in tasks
                )
            ]
            if batch:
                required = 1 + max(tasks.index(t) for t in batch)
                slot = min(len(tasks), max(old_task_ordinal, required))
                contacts.append((slot, stop.ref_id))

    stops = [RouteStop.depot()]
    for index in range(len(tasks) + 1):
        if index > 0:
            stops.append(RouteStop.task(tasks[index - 1]))
        stops.extend(
            RouteStop.contact(visit_id)
            for slot, visit_id in contacts if slot == index
        )
    stops.append(RouteStop.depot())
    return Route(uav_id, tuple(stops))


def _build_candidate(instance, original: DiscreteSolution, proposal: _Proposal):
    """Produce a valid discrete candidate, then allow standard MEC repair."""
    candidate = deepcopy(original)
    changed = proposal.new_orders
    previous_owner = {
        t: u for u, order in _task_orders(original).items() for t in order
    }
    new_owner = {t: u for u, order in changed.items() for t in order}
    for task_id, uav_id in new_owner.items():
        if previous_owner[task_id] != uav_id:
            candidate.task_decisions[task_id] = TaskDecision.local()
    for uav_id, new_order in changed.items():
        candidate.routes[uav_id] = _rebuild_contacts_for_route(
            candidate, uav_id, original.routes[uav_id], new_order,
        )
    _cleanup_orphan_contacts(candidate)
    validate_solution(instance, candidate)
    candidate = build_mec_assisted_initial_solution(
        instance, base_solution=candidate,
    )
    validate_solution(instance, candidate)
    return candidate


def _ranking_key(instance, solution):
    info = build_event_info(instance, solution)
    precheck = fast_feasibility_precheck(instance, solution, info)
    proxy = evaluate_initial_proxy(instance, solution).score
    return (
        0 if precheck.feasible else 1,
        len(precheck.reasons),
        proxy.total_energy_j,
        proxy.violated_constraints,
        proxy.max_normalized_violation,
        proxy.sum_normalized_violation,
        proxy.total_distance_m,
    ), precheck.feasible, proxy.violated_constraints == 0


def _shortlist(instance, original, config: CrossRouteConfig, families):
    """Two-stage ranking: geometry to bound repair cost, then proxy/precheck."""
    per_family = {}
    generated = {}
    constructed = {}
    valid_precheck = {}
    entries = []
    seen_sigs = {solution_signature(original)}
    for family in families:
        proposals = _proposals(instance, original, family)
        generated[family] = len(proposals)
        constructed[family] = 0
        valid_precheck[family] = 0
        candidates = []
        for proposal in proposals[:config.geometric_pool_per_family]:
            try:
                candidate = _build_candidate(instance, original, proposal)
            except ValueError:
                continue
            signature = solution_signature(candidate)
            if signature in seen_sigs:
                continue
            seen_sigs.add(signature)
            constructed[family] += 1
            key, precheck_ok, proxy_ok = _ranking_key(instance, candidate)
            if precheck_ok:
                valid_precheck[family] += 1
            candidates.append((key, proposal.label, candidate, precheck_ok, proxy_ok))
        candidates.sort(key=lambda x: (x[0], x[1]))
        per_family[family] = candidates
    # Reserve representation for all active families; never occupy more than
    # the same six additional strict-CVX slots per round across variants.
    for family in families:
        if per_family[family] and len(entries) < config.cvx_per_round:
            entries.append(per_family[family].pop(0))
    extras = sorted(
        (item for group in per_family.values() for item in group),
        key=lambda x: (x[0], x[1]),
    )
    entries.extend(extras[:max(0, config.cvx_per_round - len(entries))])
    return entries[:config.cvx_per_round], {
        "raw_proposals": generated,
        "constructed_candidates": constructed,
        "precheck_passing": valid_precheck,
        "shortlisted_labels": [item[1] for item in entries[:config.cvx_per_round]],
    }


def run_cross_route_refinement(
    instance,
    initial: DiscreteSolution,
    *,
    objective: Callable,
    families: tuple[str, ...] = FAMILIES,
    config: CrossRouteConfig | None = None,
):
    """Strictly monotonic *additional* refinement on the original ESI elite."""
    cfg = config or CrossRouteConfig()
    if not families or any(family not in FAMILIES for family in families):
        raise ValueError(f"Invalid route families {families!r}")
    if len(set(families)) != len(families):
        raise ValueError("Duplicate route families")
    if cfg.geometric_pool_per_family <= 0 or cfg.cvx_per_round <= 0:
        raise ValueError("Nonpositive neighborhood budget")
    started = perf_counter()
    current = deepcopy(initial)
    current_energy = float(objective(instance, current))
    if not np.isfinite(current_energy):
        raise ValueError("Unqualified starting ESI energy")
    stats = {
        "families": list(families),
        "rounds": 0,
        "cvx_candidates_evaluated": 0,
        "improvements": 0,
        "accepted_moves": [],
        "evaluated_moves": [],
        "selection_traces": [],
    }
    for round_no in range(1, cfg.max_rounds + 1):
        shortlist, trace = _shortlist(instance, current, cfg, families)
        trace["round"] = round_no
        stats["selection_traces"].append(trace)
        stats["rounds"] += 1
        best_candidate = None
        best_energy = current_energy
        best_label = None
        for key, label, candidate, precheck_ok, proxy_ok in shortlist:
            energy = float(objective(instance, candidate))
            stats["cvx_candidates_evaluated"] += 1
            gain = current_energy - energy if np.isfinite(energy) else None
            stats["evaluated_moves"].append({
                "round": round_no,
                "move": label,
                "energy_j": energy if np.isfinite(energy) else None,
                "saving_j": gain,
                "precheck_passed": precheck_ok,
                "proxy_feasible": proxy_ok,
                "geometric_proxy_j": key[2],
            })
            threshold = max(
                cfg.min_improvement_j,
                cfg.min_improvement_rel * max(1.0, abs(energy), abs(best_energy)),
            )
            if np.isfinite(energy) and energy < best_energy - threshold:
                best_candidate = candidate
                best_energy = energy
                best_label = label
        if best_candidate is None:
            break
        gain_j = current_energy - best_energy
        current = best_candidate
        current_energy = best_energy
        stats["improvements"] += 1
        stats["accepted_moves"].append({
            "round": round_no,
            "move": best_label,
            "saving_j": gain_j,
            "energy_j": best_energy,
        })
    validate_solution(instance, current)
    stats["runtime_s"] = perf_counter() - started
    return current, stats
