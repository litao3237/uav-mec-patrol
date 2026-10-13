"""P14 exact original repair equivalence, preview quota, and fallback."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from p14_post_mec_preview_repair import (
    POLICIES,PREVIEW_K,PreviewCounters,make_preview_repair,
    build_repair_operator_list,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances.small import build_small_instance
from uav_mec.evaluation.validator import validate_solution


@pytest.mark.parametrize("kind",("cheapest","regret2"))
@pytest.mark.parametrize("removed",(["S1"],["S1","S2"],["S2","S3"]))
def test_sham_returns_identical_structure_as_production_original(kind,removed):
    inst,source=build_small_instance()
    sha=content_hash(source)
    state=UavMecState(
        inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    broken=ops._destroy_tasks(state,removed)
    func=(ops.cheapest_insertion_repair if kind=="cheapest" else
          ops.regret2_insertion_repair)
    old=func(broken,np.random.default_rng(77))
    stats=PreviewCounters("preview_sham")
    new=make_preview_repair(kind,"preview_sham",stats)(
        broken,np.random.default_rng(77))
    assert content_hash(old.solution)==content_hash(new.solution)
    assert old.removed_tasks==new.removed_tasks==[]
    assert content_hash(source)==sha
    assert 1<=stats.candidates_previewed<=PREVIEW_K
    assert stats.chosen_rank_above_one==0
    assert stats.operator_calls[kind]==1


@pytest.mark.parametrize("policy",POLICIES)
def test_all_policies_return_valid_complete_solution_with_at_most_three_previews(policy):
    inst,sol=build_small_instance()
    frozen=content_hash(sol)
    s=UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(s,["S1","S2"])
    counters=PreviewCounters(policy)
    op=make_preview_repair("cheapest",policy,counters)
    finished=op(destroyed,np.random.default_rng(888))
    validate_solution(inst,finished.solution)
    assert finished.removed_tasks==[]
    assert 1<=counters.candidates_previewed<=3
    assert counters.total_extra_mechanism_wall_s>=0.
    assert content_hash(sol)==frozen


def test_guarded_policy_skips_extra_previews_when_original_full_queue_passes():
    inst,sol=build_small_instance()
    state=UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(state,["S1"])
    old=ops.cheapest_insertion_repair(destroyed,np.random.default_rng(8))
    stats=PreviewCounters("preview_guarded")
    ours=make_preview_repair("cheapest","preview_guarded",stats)(
        destroyed,np.random.default_rng(8))
    assert content_hash(ours.solution)==content_hash(old.solution)
    assert stats.candidates_previewed==1
    assert stats.fallback_on_queue_pass==1


@pytest.mark.parametrize("policy",POLICIES)
def test_exactly_two_original_repair_slots_remain_with_same_names(policy):
    ops_list=build_repair_operator_list(
        policy,PreviewCounters(policy))
    assert [name for name,_ in ops_list]==[
        name for name,_ in ops.make_repair_operators()]
    assert all(callable(fn) for _,fn in ops_list)


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        make_preview_repair("cheapest","unknown",PreviewCounters("unknown"))
