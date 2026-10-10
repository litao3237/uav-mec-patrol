"""Regression and adversarial tests for protected elite candidate selection."""
from dataclasses import replace
from time import perf_counter

import pytest

from uav_mec.algorithms.alns.elite_candidate_selection import (
    select_protected_elite_candidates,
)
from uav_mec.algorithms.alns.problem_operators import (
    ProblemOperatorConfig,
    _proxy_precheck_key,
    _structural_elite_candidates,
)
from uav_mec.algorithms.alns.elite_route_neighborhoods import (
    _shortlist, CrossRouteConfig,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.algorithms.alns.evaluator import ProxyObjectiveEvaluator
from uav_mec.instances.small import build_small_instance

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from run_p0_selector_budget import selection_profile, METHODS, BUDGET_S, slices


def _family(label):
    if label.startswith("route_"):
        return "route"
    if label.startswith("contact_remove"):
        return "contact_remove"
    if label.startswith("batch_merge"):
        return "batch_merge"
    if label.startswith(("contact_relocate", "contact_point_replace")):
        return "contact"
    if label.startswith("two_opt_star"):
        return "two_opt_star"
    if label.startswith("swap"):
        return "swap"
    return "mode_batch"


def _fake_ranked():
    # The first key entry 0 means the optimistic necessary precheck passed.
    return sorted([
        ((0,0,90.0), "two_opt_star::A", object()),
        ((0,0,95.0), "two_opt_star::B", object()),
        ((0,0,100.0), "contact_relocate::old", object()),
        ((0,0,105.0), "contact_remove::old", object()),
        ((0,0,106.0), "route_compute_relocate::old", object()),
        ((0,0,107.0), "batch_merge::old", object()),
        ((0,0,108.0), "swap::old", object()),
        ((0,0,110.0), "mode_batch::old", object()),
    ], key=lambda item: item[0])


def test_replace_only_contact_slot_and_preserve_route_and_delete():
    ranked = _fake_ranked()
    selected, trace = select_protected_elite_candidates(
        ranked, _family, limit=4, family_quota=1,
        policy="replace_contact_slot",
    )
    labels = [item[1] for item in selected]
    assert "route_compute_relocate::old" in labels
    assert "contact_remove::old" in labels
    assert "batch_merge::old" in labels
    assert "contact_relocate::old" not in labels
    assert "two_opt_star::A" in labels
    assert len(labels) == 4
    assert len(trace["replaced"]) == 1
    assert trace["replaced"][0]["old"] == "contact_relocate::old"


def test_replacement_keeps_original_when_cross_precheck_fails():
    ranked = [
        ((0,0,100.0), "contact_relocate::A", object()),
        ((0,0,101.0), "route_compute_relocate::B", object()),
        ((1,1,90.0), "two_opt_star::fails", object()),
    ]
    selected, _ = select_protected_elite_candidates(
        ranked, _family, limit=2, family_quota=1,
        policy="replace_contact_slot",
    )
    assert [entry[1] for entry in selected] == [
        "contact_relocate::A", "route_compute_relocate::B"
    ]


def test_protected_priority_reserves_orig_route_contact_delete_and_batch():
    selected, trace = select_protected_elite_candidates(
        _fake_ranked(), _family, limit=4, family_quota=1,
        policy="protected_priority",
    )
    labels = [item[1] for item in selected]
    assert "route_compute_relocate::old" in labels
    assert "contact_remove::old" in labels
    assert "batch_merge::old" in labels
    assert "two_opt_star::A" in labels
    assert len(labels) == 4
    assert len(trace["protected"]) == 4


@pytest.mark.parametrize("policy", [
    "replace_contact_slot", "protected_priority",
])
def test_protected_selector_does_not_expand_strict_cvx_slots(policy):
    selected, _ = select_protected_elite_candidates(
        _fake_ranked(), _family, limit=2, family_quota=1,
        policy=policy,
    )
    assert len(selected) <= 2


def test_selection_configuration_keeps_deletion_and_shared_esi_budget():
    base = ProblemOperatorConfig()
    assert base.elite_selection_policy == "legacy"
    assert not base.elite_reuse_cross_proxy_scores
    for method in METHODS[1:]:
        profile = selection_profile(base, method, geometric_pool=4)
        assert profile.elite_enable_contact_remove
        assert profile.elite_shortlist_limit == base.elite_shortlist_limit
        assert profile.elite_min_improvement_j == base.elite_min_improvement_j
    assert selection_profile(base, "original_esi", 4) == base
    assert selection_profile(
        base, "replace_contact_slot", 4
    ).elite_enable_contact_relocate
    assert selection_profile(
        base, "protected_two_opt_star", 4
    ).elite_selection_policy == "protected_priority"
    assert slices(BUDGET_S[50], 1)["esi_total_s"] == 3.0


def test_cross_route_precomputed_proxy_key_matches_outer_heuristic():
    instance, solution = build_small_instance()
    state = UavMecState(instance, solution, ProxyObjectiveEvaluator())
    short, trace = _shortlist(
        instance, solution,
        CrossRouteConfig(geometric_pool_per_family=4, cvx_per_round=3),
        ("two_opt_star",),
    )
    assert short, trace
    for key, label, candidate, passed, proxy_ok in short:
        assert tuple(key) == _proxy_precheck_key(state, candidate)


def test_time_guard_avoids_expensive_extra_cross_generation():
    instance, solution = build_small_instance()
    state = UavMecState(instance, solution, ProxyObjectiveEvaluator())
    cfg = selection_profile(
        ProblemOperatorConfig(),
        "protected_two_opt_star",
        geometric_pool=4,
    )
    trace = {}
    _structural_elite_candidates(
        state, config=cfg, trace=trace,
        deadline=perf_counter() - 1.0,
    )
    assert trace["cross_skipped_for_budget"]
    assert trace["cross_generation_s"] == 0.0
    assert trace["cross_proxy_cache_hits"] == 0


def test_cached_cross_score_reuses_without_changing_structural_ranking():
    instance, solution = build_small_instance()
    state = UavMecState(instance, solution, ProxyObjectiveEvaluator())
    cfg = selection_profile(
        ProblemOperatorConfig(),
        "protected_two_opt_star",
        geometric_pool=5,
    )
    cached = {}
    cs = _structural_elite_candidates(
        state, config=cfg, trace=cached,
    )
    plain = {}
    ps = _structural_elite_candidates(
        state,
        config=replace(cfg, elite_reuse_cross_proxy_scores=False),
        trace=plain,
    )
    assert [label for label, _ in cs] == [label for label, _ in ps]
    assert cached["cross_proxy_cache_hits"] >= 1
    assert plain["cross_proxy_cache_hits"] == 0
