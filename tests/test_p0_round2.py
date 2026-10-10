"""P0 round-2 inter-route neighborhoods: feasibility and non-regression."""
from __future__ import annotations

from collections import Counter

import pytest

from uav_mec.algorithms.alns.elite_route_neighborhoods import (
    CrossRouteConfig, FAMILIES, _build_candidate, _proposals,
    _task_only_length, run_cross_route_refinement,
)
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("family", FAMILIES)
def test_p0r2_proposals_change_two_uavs_and_preserve_tasks(family):
    instance, solution = build_small_instance()
    proposals = _proposals(instance, solution, family)
    assert proposals
    expected = Counter(solution.iter_task_ids())
    for proposal in proposals[: min(8, len(proposals))]:
        assert proposal.family == family
        assert len(proposal.new_orders) == 2
        changed = Counter(
            t for uav, route in proposal.new_orders.items() for t in route
        )
        old = Counter(
            t for uav in proposal.new_orders
            for t in solution.routes[uav].task_ids()
        )
        assert changed == old
        rebuilt = _build_candidate(instance, solution, proposal)
        validate_solution(instance, rebuilt)
        assert Counter(rebuilt.iter_task_ids()) == expected
        assert len(rebuilt.routes) == len(instance.uavs)


def test_p0r2_route_contacts_remain_valid_after_unbalanced_two_opt_star():
    instance, solution = build_small_instance()
    proposals = _proposals(instance, solution, "two_opt_star")
    unequal = [
        p for p in proposals
        if any(
            len(order) != len(solution.routes[uav].task_ids())
            for uav, order in p.new_orders.items()
        )
    ]
    assert unequal
    for proposal in unequal[:5]:
        rebuilt = _build_candidate(instance, solution, proposal)
        validate_solution(instance, rebuilt)
        assert all(
            len(route.contact_visit_ids()) <= instance.max_contacts_per_uav
            for route in rebuilt.routes.values()
        )


def test_p0r2_true_block_relocation_moves_two_tasks_across_uavs():
    instance, solution = build_small_instance()
    proposals = _proposals(instance, solution, "block_relocate")
    assert proposals
    for p in proposals[:12]:
        orders = p.new_orders
        source_counts = [len(solution.routes[u].task_ids()) for u in orders]
        new_counts = [len(v) for v in orders.values()]
        assert sorted(abs(a - b) for a, b in zip(source_counts, new_counts)) == [2, 2]


def test_p0r2_additional_refinement_monotone_with_surrogate_energy():
    instance, solution = build_small_instance()

    # This is a deterministic synthetic evaluator testing acceptance logic,
    # not a claimed physical CVXPY or feasibility result.
    def objective(instance, solution):
        return sum(
            _task_only_length(instance, tuple(route.task_ids()))
            for route in solution.routes.values()
        ) * 18.0

    initial_energy = objective(instance, solution)
    final, stats = run_cross_route_refinement(
        instance, solution,
        objective=objective,
        families=FAMILIES,
        config=CrossRouteConfig(
            geometric_pool_per_family=4,
            cvx_per_round=3,
            max_rounds=1,
        ),
    )
    validate_solution(instance, final)
    assert objective(instance, final) <= initial_energy + 1e-9
    assert 0 <= stats["cvx_candidates_evaluated"] <= 3
    assert stats["rounds"] == 1
    assert len(stats["selection_traces"]) == 1


def test_p0r2_invalid_families_or_budget_are_rejected():
    instance, solution = build_small_instance()
    def oracle(instance, solution):
        return 10.0

    with pytest.raises(ValueError):
        run_cross_route_refinement(
            instance, solution, objective=oracle,
            families=("swap", "swap"),
        )
    with pytest.raises(ValueError):
        run_cross_route_refinement(
            instance, solution, objective=oracle,
            families=("not_a_family",),
        )
    with pytest.raises(ValueError):
        run_cross_route_refinement(
            instance, solution, objective=oracle,
            config=CrossRouteConfig(cvx_per_round=0),
        )
