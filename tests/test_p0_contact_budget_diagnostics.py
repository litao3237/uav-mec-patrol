"""Contract tests for the fixed-structure UAV energy lower bound and P0 profile."""
from copy import deepcopy
from dataclasses import replace

import pytest

from uav_mec.algorithms.initial import evaluate_initial_proxy
from uav_mec.algorithms.alns.problem_operators import (
    ProblemOperatorConfig,
    _structural_elite_candidates,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.algorithms.alns.evaluator import ProxyObjectiveEvaluator
from uav_mec.instances.small import build_small_instance
from uav_mec.optimization.resource import solve_resource_problem
from uav_mec.optimization.resource.energy_lower_bound import (
    fixed_structure_energy_lower_bound,
    can_certify_no_meaningful_improvement,
)
from experiments.run_p0_contact_diagnostics import profile_config


def test_energy_lower_bound_cannot_exceed_reduced_feasible_proxy():
    instance, solution = build_small_instance()
    lb = fixed_structure_energy_lower_bound(instance, solution)
    proxy = evaluate_initial_proxy(instance, solution).reduced.total_energy_j
    assert lb > 0.0
    assert lb <= proxy + 1e-5


def test_energy_lower_bound_leq_strict_cvx_optimum():
    instance, solution = build_small_instance()
    exact = solve_resource_problem(
        instance, solution, run_stage2=False,
    )
    assert exact.feasible, exact.diagnostics
    lower = fixed_structure_energy_lower_bound(instance, solution)
    assert lower <= exact.energy_stage1_j + 0.05


def test_no_contact_bound_matches_flight_plus_optimistic_local_cpu():
    instance, solution = build_small_instance()
    from uav_mec.domain import Route, RouteStop, TaskDecision
    simple = deepcopy(solution)
    simple.contact_visits = {}
    simple.routes = {
        uav_id: Route(
            uav_id,
            tuple([stop for stop in route.stops if stop.kind.value != "contact"]),
        )
        for uav_id, route in simple.routes.items()
    }
    simple.task_decisions = {t: TaskDecision.local() for t in instance.tasks}
    from uav_mec.evaluation import build_event_info
    info = build_event_info(instance, simple)
    fixed_energy = sum(info.fixed_flight_energy_j.values()) + sum(
        info.fixed_collection_energy_j.values()
    )
    assert fixed_structure_energy_lower_bound(instance, simple) >= fixed_energy


def test_bound_guard_only_excludes_unbeatable_candidates():
    assert not can_certify_no_meaningful_improvement(800.0, 1000.0)
    assert can_certify_no_meaningful_improvement(999.5, 1000.0)
    assert not can_certify_no_meaningful_improvement(float("nan"), 1000.0)
    assert not can_certify_no_meaningful_improvement(float("inf"), 1000.0)


def test_operator_profile_preserves_contact_deletion():
    base = ProblemOperatorConfig()
    for profile in ("retain_remove_swap", "retain_remove_two_opt_star",
                    "retain_remove_block_relocate", "retain_remove_combined",
                    "retain_contact_remove_only"):
        cfg = profile_config(base, profile, geometric_pool=6)
        assert cfg.elite_enable_contact_remove
        assert not cfg.elite_enable_contact_relocate
        assert not cfg.elite_enable_contact_point_replace
        assert cfg.elite_shortlist_limit == base.elite_shortlist_limit
        assert cfg.elite_family_quota == base.elite_family_quota


@pytest.mark.parametrize("profile,disabled", (
    ("no_contact_remove", "elite_enable_contact_remove"),
    ("no_contact_relocate", "elite_enable_contact_relocate"),
    ("no_contact_point_replace", "elite_enable_contact_point_replace"),
))
def test_diagnostic_ablation_disables_only_one_contact_operation(profile, disabled):
    base = ProblemOperatorConfig()
    cfg = profile_config(base, profile, geometric_pool=6)
    for field in ("elite_enable_contact_remove", "elite_enable_contact_relocate",
                  "elite_enable_contact_point_replace"):
        assert getattr(cfg, field) is (field != disabled)


def test_trace_is_observational_no_shortlist_change():
    instance, solution = build_small_instance()
    state = UavMecState(instance, solution, ProxyObjectiveEvaluator())
    config = ProblemOperatorConfig()
    observed = _structural_elite_candidates(state, config=config)
    trace = {}
    repeated = _structural_elite_candidates(state, config=config, trace=trace)
    assert [label for label,_ in repeated] == [label for label,_ in observed]
    assert trace["shortlisted_total"] == len(repeated)
    assert sum(trace["selected_by_family"].values()) == len(repeated)
    assert trace["unique_ranked_total"] >= len(repeated)
