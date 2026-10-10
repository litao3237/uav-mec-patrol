"""P0 integrated neighborhood replaces ESI candidates, never adds a stage."""
from copy import deepcopy
from dataclasses import replace

import pytest

from uav_mec.algorithms.alns.problem_operators import (
    ProblemOperatorConfig,
    _structural_elite_candidates,
    contact_mode_intensification,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.algorithms.alns.evaluator import ProxyObjectiveEvaluator
from uav_mec.algorithms.alns.elite_route_neighborhoods import (
    FAMILIES, _build_candidate, _proposals, _task_only_length,
)
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("family", FAMILIES)
def test_integrated_cross_uav_moves_are_structurally_valid(family):
    instance, solution = build_small_instance()
    proposals = _proposals(instance, solution, family)
    assert proposals
    for proposal in proposals[:min(6,len(proposals))]:
        candidate = _build_candidate(instance, solution, proposal)
        validate_solution(instance, candidate)
        assert sorted(candidate.iter_task_ids()) == sorted(instance.tasks)


def test_off_by_default_keeps_frozen_Esi_profile():
    cfg = ProblemOperatorConfig()
    assert cfg.elite_interroute_families == ()
    assert cfg.elite_shortlist_limit == 6
    assert cfg.elite_route_options_per_task == 2
    assert cfg.elite_family_quota == 1
    assert cfg.elite_progressive_widening


@pytest.mark.parametrize("family", FAMILIES)
def test_replacement_candidates_compete_in_same_six_slot_shortlist(family):
    instance, solution = build_small_instance()
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)
    cfg = replace(
        ProblemOperatorConfig(),
        elite_interroute_families=(family,),
        elite_interroute_geometry_pool=6,
        elite_enable_contact_relocate=False,
        elite_enable_contact_point_replace=False,
        elite_enable_contact_remove=False,
        elite_enable_batch_merge=False,
        elite_enable_batch_split=False,
        elite_enable_mode_batch_reassign=False,
        elite_enable_route_compute_relocate=False,
    )
    shortlist = _structural_elite_candidates(state, config=cfg)
    assert 0 < len(shortlist) <= cfg.elite_shortlist_limit
    assert all(label.startswith(family+"::") for label,_ in shortlist)
    for _, candidate in shortlist:
        validate_solution(instance, candidate)


def test_original_esi_candidate_path_does_not_require_new_module(monkeypatch):
    from uav_mec.algorithms.alns import elite_route_neighborhoods as new
    instance, solution = build_small_instance()
    evaluator = ProxyObjectiveEvaluator()
    state = UavMecState(instance, solution, evaluator)
    baseline = _structural_elite_candidates(
        state, config=ProblemOperatorConfig()
    )
    monkeypatch.setattr(new, "_shortlist", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("default ESI unexpectedly used new neighborhoods")
    ))
    again = _structural_elite_candidates(
        state, config=ProblemOperatorConfig()
    )
    assert [label for label,_ in baseline] == [label for label,_ in again]


def test_integrated_esi_accepts_only_improved_candidate():
    instance, solution = build_small_instance()
    evaluator = ProxyObjectiveEvaluator()
    before = evaluator(instance, solution)
    state = UavMecState(instance, deepcopy(solution), evaluator)
    cfg = replace(
        ProblemOperatorConfig(),
        elite_interroute_families=("swap",),
        elite_interroute_geometry_pool=4,
        elite_enable_contact_relocate=False,
        elite_enable_contact_point_replace=False,
        elite_enable_contact_remove=False,
        elite_progressive_widening=False,
    )
    result, stats = contact_mode_intensification(
        state, config=cfg, objective=evaluator, max_rounds=1
    )
    validate_solution(instance, result.solution)
    after = evaluator(instance, result.solution)
    assert after <= before + 1e-9
    assert stats["rounds"] == 1
    assert stats["candidates_evaluated"] <= cfg.elite_shortlist_limit
