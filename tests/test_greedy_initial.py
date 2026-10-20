from __future__ import annotations

from uav_mec.algorithms import build_greedy_initial_solution
from uav_mec.evaluation import build_event_info, validate_solution
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def test_greedy_initial_solution_is_valid_and_complete() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        num_uavs=5,
        num_mecs=3,
        scenario_seed=17,
    )
    solution = build_greedy_initial_solution(instance)

    validate_solution(instance, solution)
    assigned = [
        task_id
        for route in solution.routes.values()
        for task_id in route.task_ids()
    ]
    assert len(assigned) == len(instance.tasks)
    assert set(assigned) == set(instance.tasks)
    assert len(set(assigned)) == len(assigned)
    assert not solution.contact_visits
    assert all(
        decision.contact_visit_id is None
        for decision in solution.task_decisions.values()
    )


def test_greedy_initial_solution_is_deterministic() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        scenario_seed=21,
    )
    a = build_greedy_initial_solution(instance)
    b = build_greedy_initial_solution(instance)

    assert {
        uav_id: route.labels()
        for uav_id, route in a.routes.items()
    } == {
        uav_id: route.labels()
        for uav_id, route in b.routes.items()
    }


def test_greedy_parallel_insertion_uses_multiple_uavs() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        num_uavs=5,
        scenario_seed=42,
    )
    solution = build_greedy_initial_solution(instance)
    info = build_event_info(instance, solution)

    nonempty = sum(
        1
        for route in solution.routes.values()
        if route.task_ids()
    )
    assert nonempty == len(instance.uavs)
    assert max(info.base_return_s.values()) < 2.0 * instance.cycle_s
