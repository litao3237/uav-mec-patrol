from __future__ import annotations

import numpy as np

from uav_mec.algorithms import (
    ProxyObjectiveEvaluator,
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import (
    DestroyConfig,
    UavMecState,
    cheapest_insertion_repair,
    make_destroy_operators,
    random_task_removal,
)
from uav_mec.evaluation import build_event_info, validate_solution
from uav_mec.optimization.resource import (
    ResourceSolveResult,
    fast_feasibility_precheck,
)
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def _small_instance():
    cfg = load_paper_scale_config()
    return build_paper_scale_instance(
        cfg,
        num_tasks=12,
        num_uavs=3,
        num_mecs=2,
        scenario_seed=7,
    )


def _initial_solution(instance):
    route_seed = build_greedy_initial_solution(instance)
    return build_mec_assisted_initial_solution(
        instance,
        base_solution=route_seed,
    )


def test_destroy_repair_round_trip_is_complete_and_valid() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)
    rng = np.random.default_rng(5)

    destroyed = random_task_removal(
        state,
        rng,
        config=DestroyConfig(
            fraction=0.2,
            min_remove=2,
            max_remove=2,
        ),
    )
    assert len(destroyed.removed_tasks) == 2

    repaired = cheapest_insertion_repair(destroyed, rng)
    assert not repaired.removed_tasks
    validate_solution(instance, repaired.solution)


def test_proxy_objective_cache_is_used() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()

    first = evaluator(instance, solution)
    second = evaluator(instance, solution)

    assert first == second
    assert evaluator.stats.calls == 2
    assert evaluator.stats.cache_hits == 1


def test_short_external_alns_run_returns_valid_best_state() -> None:
    instance = _small_instance()
    initial = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    config = UavMecALNSConfig(
        iterations=4,
        seed=11,
        destroy=DestroyConfig(
            fraction=0.15,
            min_remove=1,
            max_remove=2,
        ),
    )

    result = run_uav_mec_alns(
        instance,
        initial_solution=initial,
        config=config,
        evaluator=evaluator,
    )

    validate_solution(instance, result.best_solution)
    assert result.best_objective <= result.initial_objective + 1e-9


def test_destroy_operator_factories_preserve_function_names() -> None:
    operators = make_destroy_operators(
        DestroyConfig(
            fraction=0.2,
            min_remove=1,
            max_remove=2,
        )
    )

    assert operators
    for registered_name, operator in operators:
        assert hasattr(operator, "__name__")
        assert operator.__name__
        assert registered_name


class _FakeFeasibleResourceSolver:
    def __init__(self, energy_j: float = 123.0) -> None:
        self.energy_j = energy_j
        self.calls = 0

    def solve(self, instance, solution, info=None):
        self.calls += 1
        return ResourceSolveResult(
            status="optimal",
            solver="FAKE",
            is_dcp=True,
            energy_stage1_j=self.energy_j,
            energy_final_j=self.energy_j,
            stage1_values={"fake": {"x": 1.0}},
            final_values={"fake": {"x": 1.0}},
        )


def test_screened_proxy_refines_precheck_feasible_proxy_gray_zone() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=80,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=42,
    )
    route_seed = build_greedy_initial_solution(instance)
    solution = build_mec_assisted_initial_solution(
        instance,
        base_solution=route_seed,
    )

    proxy = ProxyObjectiveEvaluator()
    proxy_value = proxy(instance, solution)
    assert proxy_value > 1e9

    info = build_event_info(instance, solution)
    precheck = fast_feasibility_precheck(instance, solution, info)
    assert precheck.feasible

    fake = _FakeFeasibleResourceSolver(energy_j=321.0)
    evaluator = ScreenedProxyObjectiveEvaluator(cvx_solver=fake)
    value = evaluator(instance, solution)

    assert value == 321.0
    assert fake.calls == 1
    assert evaluator.stats.ambiguous_proxy_calls == 1
    assert evaluator.stats.cvx_refinements == 1
    assert evaluator.stats.feasible_calls == 1
    assert evaluator.stats.precheck_rejects == 0
