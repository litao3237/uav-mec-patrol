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
from uav_mec.optimization.resource import (
    KKTResourceSolverConfig,
    solve_kkt_resource_problem,
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


def test_kkt_never_discards_a_constructive_feasible_seed() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        scenario_seed=42,
    )
    base = build_greedy_initial_solution(instance)
    repaired = build_mec_assisted_initial_solution(
        instance,
        base_solution=base,
    )

    proxy = evaluate_initial_proxy(instance, repaired)
    assert proxy.score.violated_constraints == 0

    # One iteration is deliberately too short for dual convergence. The KKT
    # solver must still preserve the already verified feasible primal seed
    # instead of incorrectly reporting that no feasible iterate exists.
    result = solve_kkt_resource_problem(
        instance,
        repaired,
        config=KKTResourceSolverConfig(
            max_iterations=1,
            min_iterations=1,
            convergence_patience=1,
        ),
    )

    assert result.feasible
    assert result.diagnostics.get("initial_seed_feasible") is True
