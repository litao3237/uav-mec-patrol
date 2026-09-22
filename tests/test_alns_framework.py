from __future__ import annotations

import numpy as np

from uav_mec.algorithms import (
    GARouteConfig,
    ProxyObjectiveEvaluator,
    ProblemOperatorConfig,
    ScreenedProxyObjectiveEvaluator,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_route_ga,
    run_uav_mec_alns,
    run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns import (
    DestroyConfig,
    UavMecState,
    cheapest_insertion_repair,
    make_destroy_operators,
    random_task_removal,
)
from uav_mec.algorithms.alns.problem_operators import (
    compute_aware_insertion_repair,
    contact_mode_intensification,
    contact_opportunity_repair,
    make_problem_destroy_operators,
    make_problem_repair_operators,
    mec_batch_pressure_removal,
    mode_batch_repair,
    shared_mec_pressure_removal,
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
    assert sum(
        sum(values)
        for values in result.operator_pair_counts.values()
    ) == config.iterations


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



def test_problem_specific_operator_factories_have_expected_families() -> None:
    destroy = make_problem_destroy_operators(
        DestroyConfig(
            fraction=0.2,
            min_remove=1,
            max_remove=3,
        ),
        ProblemOperatorConfig(),
    )
    repair = make_problem_repair_operators(
        ProblemOperatorConfig(),
    )

    assert [name for name, _ in destroy] == [
        "mec_batch_pressure_removal",
        "shared_mec_pressure_removal",
    ]
    assert [name for name, _ in repair] == [
        "contact_opportunity_repair",
        "mode_batch_repair",
        "compute_aware_insertion_repair",
    ]
    for _, operator in destroy + repair:
        assert hasattr(operator, "__name__")
        assert operator.__name__


def test_problem_specific_destroy_operators_return_partial_states() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)
    rng = np.random.default_rng(17)
    destroy_cfg = DestroyConfig(
        fraction=0.2,
        min_remove=1,
        max_remove=3,
    )
    problem_cfg = ProblemOperatorConfig()

    batch_destroyed = mec_batch_pressure_removal(
        state,
        rng,
        config=destroy_cfg,
        problem=problem_cfg,
    )
    assert batch_destroyed.removed_tasks

    shared_destroyed = shared_mec_pressure_removal(
        state,
        rng,
        config=destroy_cfg,
        problem=problem_cfg,
    )
    assert shared_destroyed.removed_tasks


def test_problem_specific_repairs_restore_complete_valid_solution() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)
    destroy_cfg = DestroyConfig(
        fraction=0.2,
        min_remove=2,
        max_remove=2,
    )
    problem_cfg = ProblemOperatorConfig(
        contact_points_per_mec=1,
        contact_target_pool=1,
        critical_task_limit=3,
        mode_candidate_limit=6,
        compute_option_limit=5,
    )

    repairs = (
        contact_opportunity_repair,
        mode_batch_repair,
        compute_aware_insertion_repair,
    )
    for idx, repair in enumerate(repairs, start=1):
        rng = np.random.default_rng(30 + idx)
        destroyed = random_task_removal(
            state,
            rng,
            config=destroy_cfg,
        )
        repaired = repair(
            destroyed,
            rng,
            config=problem_cfg,
        )
        assert not repaired.removed_tasks
        validate_solution(instance, repaired.solution)



def test_contact_mode_intensification_is_monotone_for_supplied_objective() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)
    before = evaluator(instance, solution)

    intensified, stats = contact_mode_intensification(
        state,
        config=ProblemOperatorConfig(
            contact_points_per_mec=1,
            contact_target_pool=1,
            critical_task_limit=3,
            mode_candidate_limit=6,
        ),
        objective=evaluator,
        max_rounds=1,
    )
    after = evaluator(instance, intensified.solution)

    validate_solution(instance, intensified.solution)
    assert after <= before + 1e-9
    assert stats["rounds"] == 1


class _ConstantEliteOracle:
    def __init__(
        self,
        energy_j: float = 123.0,
        *,
        stage1_status: str = "optimal",
    ) -> None:
        self.energy_j = energy_j
        self.stage1_status = stage1_status
        self.calls = 0
        self.cache_hits = 0

    def solve(self, instance, solution):
        self.calls += 1
        return ResourceSolveResult(
            status=self.stage1_status,
            solver="FAKE",
            is_dcp=True,
            energy_stage1_j=self.energy_j,
            energy_final_j=self.energy_j,
            stage1_values={"fake": {"x": 1.0}},
            final_values={"fake": {"x": 1.0}},
            diagnostics={
                "stage1_status": self.stage1_status,
            },
        )

    def __call__(self, instance, solution):
        return self.solve(
            instance,
            solution,
        ).energy_stage1_j


def test_hybrid_runner_uses_generic_exploration_and_nonworsening_elite() -> None:
    instance = _small_instance()
    initial = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    config = UavMecALNSConfig(
        iterations=2,
        seed=19,
        enable_problem_operators=True,
    )
    oracle = _ConstantEliteOracle(energy_j=321.0)

    result = run_uav_mec_hybrid_alns(
        instance,
        initial_solution=initial,
        config=config,
        evaluator=evaluator,
        elite_rounds=1,
        elite_oracle=oracle,
    )

    validate_solution(instance, result.best_solution)
    assert result.exploration_cvx_energy_j == 321.0
    assert result.final_cvx_energy_j == 321.0
    assert result.improvement_pct == 0.0
    assert result.exploration.operator_pair_counts




class _InaccurateStage1Solver:
    def solve(self, instance, solution, info=None):
        return ResourceSolveResult(
            status="optimal_inaccurate",
            solver="FAKE",
            is_dcp=True,
            energy_stage1_j=1.0,
            energy_final_j=1.0,
            stage1_values={"fake": {"x": 1.0}},
            final_values={"fake": {"x": 1.0}},
            diagnostics={
                "stage1_status": "optimal_inaccurate",
            },
        )


def test_stage1_elite_oracle_rejects_inaccurate_candidate_value() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    oracle = Stage1CVXObjectiveOracle()
    oracle.solver = _InaccurateStage1Solver()

    assert oracle(instance, solution) == float("inf")



def test_hybrid_skips_elite_refinement_without_strict_stage1_optimum() -> None:
    instance = _small_instance()
    initial = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    oracle = _ConstantEliteOracle(
        energy_j=321.0,
        stage1_status="optimal_inaccurate",
    )

    result = run_uav_mec_hybrid_alns(
        instance,
        initial_solution=initial,
        config=UavMecALNSConfig(
            iterations=1,
            seed=23,
        ),
        evaluator=evaluator,
        elite_rounds=2,
        elite_oracle=oracle,
    )

    assert result.best_solution == result.exploration.best_solution
    assert result.elite_stats["rounds"] == 0
    assert (
        result.elite_stats["skipped"]
        == "exploration_stage1_not_strict_optimal"
    )


def test_elite_route_family_can_be_disabled_for_ablation() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)

    _, stats = contact_mode_intensification(
        state,
        config=ProblemOperatorConfig(
            contact_points_per_mec=1,
            contact_target_pool=1,
            critical_task_limit=3,
            mode_candidate_limit=6,
            elite_shortlist_limit=12,
            elite_enable_route_compute_relocate=False,
        ),
        objective=evaluator,
        max_rounds=1,
    )

    assert all(
        not str(move["move"]).startswith(
            "route_compute_relocate::"
        )
        for move in stats["evaluated_moves"]
    )


def test_elite_contact_family_can_be_disabled_for_ablation() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)

    _, stats = contact_mode_intensification(
        state,
        config=ProblemOperatorConfig(
            contact_points_per_mec=1,
            contact_target_pool=1,
            critical_task_limit=3,
            mode_candidate_limit=6,
            elite_shortlist_limit=12,
            elite_enable_contact_relocate=False,
            elite_enable_contact_point_replace=False,
            elite_enable_contact_remove=False,
        ),
        objective=evaluator,
        max_rounds=1,
    )

    forbidden_prefixes = (
        "contact_relocate::",
        "contact_remove::",
    )
    assert all(
        not str(move["move"]).startswith(forbidden_prefixes)
        and str(move["move"]) != "contact_point_replace"
        for move in stats["evaluated_moves"]
    )


def test_elite_batch_family_can_be_disabled_for_ablation() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)

    _, stats = contact_mode_intensification(
        state,
        config=ProblemOperatorConfig(
            contact_points_per_mec=1,
            contact_target_pool=1,
            critical_task_limit=3,
            mode_candidate_limit=6,
            elite_shortlist_limit=12,
            elite_enable_batch_merge=False,
            elite_enable_batch_split=False,
        ),
        objective=evaluator,
        max_rounds=1,
    )

    forbidden_prefixes = (
        "batch_merge::",
        "batch_split_or_new_contact::",
    )
    assert all(
        not str(move["move"]).startswith(forbidden_prefixes)
        for move in stats["evaluated_moves"]
    )


def test_elite_progressive_widening_can_be_disabled_for_ablation() -> None:
    instance = _small_instance()
    solution = _initial_solution(instance)
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)

    _, stats = contact_mode_intensification(
        state,
        config=ProblemOperatorConfig(
            contact_points_per_mec=1,
            contact_target_pool=1,
            critical_task_limit=3,
            mode_candidate_limit=6,
            elite_shortlist_limit=6,
            elite_progressive_widening=False,
        ),
        objective=evaluator,
        max_rounds=1,
    )

    assert stats["widenings"] == 0
    assert stats["widened_candidates_evaluated"] == 0
    assert stats["widened_families"] == []



def test_alns_wall_clock_budget_can_stop_before_first_iteration() -> None:
    instance = _small_instance()
    initial = _initial_solution(instance)
    result = run_uav_mec_alns(
        instance,
        initial_solution=initial,
        config=UavMecALNSConfig(
            iterations=4,
            seed=31,
            max_runtime_s=0.0,
        ),
        evaluator=ProxyObjectiveEvaluator(),
    )

    validate_solution(instance, result.best_solution)
    assert sum(
        sum(values)
        for values in result.operator_pair_counts.values()
    ) == 0


def test_route_ga_wall_clock_budget_returns_initial_population_best() -> None:
    instance = _small_instance()
    result = run_route_ga(
        instance,
        seed=37,
        config=GARouteConfig(
            population_size=6,
            generations=10,
            max_runtime_s=0.0,
        ),
    )

    validate_solution(instance, result.best_solution)
    assert result.generations == 0
    assert result.evaluations > 0


def test_hybrid_zero_elite_budget_skips_structural_candidates() -> None:
    instance = _small_instance()
    initial = _initial_solution(instance)
    oracle = _ConstantEliteOracle(energy_j=321.0)

    result = run_uav_mec_hybrid_alns(
        instance,
        initial_solution=initial,
        config=UavMecALNSConfig(
            iterations=1,
            seed=41,
        ),
        evaluator=ProxyObjectiveEvaluator(),
        elite_rounds=2,
        elite_oracle=oracle,
        elite_max_runtime_s=0.0,
    )

    validate_solution(instance, result.best_solution)
    assert result.best_solution == result.exploration.best_solution
    assert result.elite_stats["candidates_evaluated"] == 0
    assert result.elite_stats["budget_exhausted"] is True
