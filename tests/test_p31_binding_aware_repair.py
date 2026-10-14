"""P31 invariants: one old MEC builder, legal complete D and SHA identity sham."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from p31_binding_aware_repair import (
    P31Limits,P31Counters,POLICIES,_diagnose,
    binding_targets,legal_cross_uav,rank_key,refine_one,make_repair_list,
)
from uav_mec.algorithms.alns import UavMecState,operators as ops
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance

SMALL=P31Limits(
    targets=2,destination_uavs=2,insertion_ranks_per_uav=1,
    alternate_contacts_per_position=1,total_candidates=5,joint_bw_cpu_bins=8,
)


def test_candidate_moves_are_original_physical_complete_with_no_added_contacts():
    inst,source=build_small_instance()
    physical=content_hash(inst)
    original=content_hash(source)
    counters=P31Counters("joint_cpu_bw")
    proposals=legal_cross_uav(inst,source,["S1"],SMALL,counters)
    assert proposals
    assert len(proposals)<=SMALL.total_candidates
    for move in proposals:
        validate_solution(inst,move["solution"])
        assert move["old_UAV"]!=move["new_UAV"]
        assert set(move["solution"].contact_visits).issubset(set(source.contact_visits))
        assert len(move["solution"].task_decisions)==len(source.task_decisions)
    assert content_hash(source)==original
    assert content_hash(inst)==physical


def test_all_policies_differ_only_in_frozen_readonly_ranking():
    inst,source=build_small_instance()
    d=_diagnose(inst,source,bins=8)
    focus=binding_targets(inst,d,limit=2)
    assert isinstance(focus,list)
    assert len(focus)<=2
    for p in POLICIES:
        assert isinstance(rank_key(d,p),tuple)


@pytest.mark.parametrize("policy",POLICIES)
def test_genuine_operator_one_exact_original_builder_preserves_original_source(policy):
    inst,source=build_small_instance()
    source_sha=content_hash(source)
    base=UavMecState(
        inst,deepcopy(source),ScreenedProxyObjectiveEvaluator()
    )
    destroyed=ops._destroy_tasks(base,["S1","S2"])
    originals=ops.make_repair_operators()
    wrapped_counter=P31Counters(policy)
    replacements=make_repair_list(policy,wrapped_counter,SMALL)
    assert [x[0] for x in originals]==[x[0] for x in replacements]
    for (_,old_fn),(_,new_fn) in zip(originals,replacements):
        original_repaired=old_fn(
            destroyed,np.random.default_rng(42)
        )
        new_repaired=new_fn(
            destroyed,np.random.default_rng(42)
        )
        validate_solution(inst,new_repaired.solution)
        assert not new_repaired.removed_tasks
        if policy=="sham":
            assert content_hash(new_repaired.solution)==content_hash(
                original_repaired.solution
            )
    assert wrapped_counter.legacy_full_builder_calls==len(originals)
    assert wrapped_counter.calls==len(originals)
    assert content_hash(source)==source_sha


def test_sham_postrepair_always_preserves_complete_discrete_solution():
    inst,source=build_small_instance()
    state=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    sha=content_hash(state.solution)
    counters=P31Counters("sham")
    updated=refine_one(state,"sham",counters,SMALL)
    assert content_hash(updated.solution)==sha
    assert content_hash(state.solution)==sha
    assert counters.chosen_other_D==0
