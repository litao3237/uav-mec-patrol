from __future__ import annotations

from uav_mec.algorithms import (
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    evaluate_initial_proxy,
)
from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import validate_solution
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def test_mec_repair_returns_valid_solution_and_never_worsens_proxy() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        scenario_seed=42,
    )
    base = build_greedy_initial_solution(instance)
    before = evaluate_initial_proxy(instance, base)

    repaired = build_mec_assisted_initial_solution(
        instance,
        base_solution=base,
    )
    validate_solution(instance, repaired)
    after = evaluate_initial_proxy(instance, repaired)

    assert after.score.key <= before.score.key
    assert len(repaired.contact_visits) <= (
        len(instance.uavs) * instance.max_contacts_per_uav
    )


def test_mec_repair_offloads_when_all_local_proxy_is_infeasible() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        scenario_seed=42,
    )
    base = build_greedy_initial_solution(instance)
    before = evaluate_initial_proxy(instance, base)
    assert before.score.violated_constraints > 0

    repaired = build_mec_assisted_initial_solution(
        instance,
        base_solution=base,
    )
    offloaded = sum(
        decision.mode is ExecutionMode.OFFLOAD
        for decision in repaired.task_decisions.values()
    )

    assert offloaded > 0
    assert repaired.contact_visits


def test_mec_repair_is_deterministic() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        scenario_seed=42,
    )
    base = build_greedy_initial_solution(instance)

    a = build_mec_assisted_initial_solution(
        instance,
        base_solution=base,
    )
    b = build_mec_assisted_initial_solution(
        instance,
        base_solution=base,
    )

    assert {
        uav_id: route.labels()
        for uav_id, route in a.routes.items()
    } == {
        uav_id: route.labels()
        for uav_id, route in b.routes.items()
    }
    assert a.task_decisions == b.task_decisions
    assert a.contact_visits == b.contact_visits
