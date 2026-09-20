from __future__ import annotations

import numpy as np

from uav_mec.algorithms import (
    ProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import (
    DestroyConfig,
    UavMecState,
    cheapest_insertion_repair,
    random_task_removal,
)
from uav_mec.evaluation import validate_solution
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
