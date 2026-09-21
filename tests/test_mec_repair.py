from __future__ import annotations

from uav_mec.algorithms import (
    GARouteConfig,
    build_fixed_route_nearest_mec_solution,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    evaluate_initial_proxy,
    run_route_ga,
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


def test_fixed_route_nearest_mec_preserves_routes_and_uses_nearest_mec() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=30,
        num_mecs=2,
        scenario_seed=42,
    )
    base = build_greedy_initial_solution(instance)
    baseline_task_routes = {
        uav_id: route.task_ids()
        for uav_id, route in base.routes.items()
    }

    solution = build_fixed_route_nearest_mec_solution(
        instance,
        base_solution=base,
    )
    validate_solution(instance, solution)

    assert {
        uav_id: route.task_ids()
        for uav_id, route in solution.routes.items()
    } == baseline_task_routes

    offloaded = 0
    for task_id, decision in solution.task_decisions.items():
        if decision.mode is not ExecutionMode.OFFLOAD:
            continue
        offloaded += 1
        visit = solution.contact_visits[decision.contact_visit_id]
        assigned_mec = instance.contact_points[visit.point_id].mec_id
        task = instance.tasks[task_id]
        nearest_mec = min(
            instance.mecs,
            key=lambda mec_id: (
                (
                    (task.x - instance.mecs[mec_id].x) ** 2
                    + (task.y - instance.mecs[mec_id].y) ** 2
                ),
                mec_id,
            ),
        )
        assert assigned_mec == nearest_mec

    assert offloaded > 0


def test_route_ga_is_deterministic_and_not_worse_than_greedy_proxy() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=24,
        num_mecs=2,
        scenario_seed=42,
    )
    route_seed = build_greedy_initial_solution(instance)
    repaired = build_mec_assisted_initial_solution(
        instance,
        base_solution=route_seed,
    )
    baseline_proxy = evaluate_initial_proxy(instance, repaired)

    ga_cfg = GARouteConfig(
        population_size=8,
        generations=4,
        tournament_size=3,
        elite_count=2,
    )
    a = run_route_ga(
        instance,
        seed=100,
        config=ga_cfg,
    )
    b = run_route_ga(
        instance,
        seed=100,
        config=ga_cfg,
    )

    validate_solution(instance, a.best_solution)
    validate_solution(instance, b.best_solution)

    assert a.best_proxy.score.key <= baseline_proxy.score.key
    assert a.best_proxy.score.key == b.best_proxy.score.key
    assert {
        uav_id: route.task_ids()
        for uav_id, route in a.best_solution.routes.items()
    } == {
        uav_id: route.task_ids()
        for uav_id, route in b.best_solution.routes.items()
    }
    assert a.best_solution.task_decisions == b.best_solution.task_decisions
    assert a.best_solution.contact_visits == b.best_solution.contact_visits
