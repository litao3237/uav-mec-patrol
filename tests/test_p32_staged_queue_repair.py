"""P32 invariants: original complete builder, strict-source-protective cheap gate."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from p32_staged_queue_repair import (
    POLICIES,P32Counters,light_audit,eligible,cheap_key,
    joint_selection_shortlist,make_repair_list,refine_one,
)
from p31_binding_aware_repair import P31Limits
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState,operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance

SMALL=P31Limits(
    targets=2,destination_uavs=2,
    insertion_ranks_per_uav=1,alternate_contacts_per_position=1,
    total_candidates=5,joint_bw_cpu_bins=8,
)


def test_original_safe_queue_cpu_screen_no_pseudostrict_feasibility_claims():
    inst,solution=build_small_instance()
    instance_sha=content_hash(inst)
    sol_sha=content_hash(solution)
    record=light_audit(inst,solution)
    assert isinstance(record["queue_pass"],bool)
    assert isinstance(record["cpu_bad"],bool)
    assert eligible(record)==(
        record["queue_pass"] and not record["cpu_bad"]
    )
    assert record["cpu_bound"]["is_sufficient_for_feasibility"] is False
    assert content_hash(inst)==instance_sha
    assert content_hash(solution)==sol_sha


def test_identical_candidate_generation_ranking_then_max_8_joint_tests():
    synthetic=[]
    for n in range(23):
        record={
            "queue_pass":True,
            "cpu_bad":False,
            "queue_normalized_excess":float(n%7),
            "route_m":float(n),
            "cpu_pressure_ratio":float((n*3)%11),
            "cpu_excess_ratio":0.,
        }
        assert isinstance(cheap_key(record,"queue"),tuple)
        assert isinstance(cheap_key(record,"cpu"),tuple)
        synthetic.append({
            "label":f"T{n:03d}",
            "audit":record,"solution":None,
        })
    x=joint_selection_shortlist(synthetic)
    y=joint_selection_shortlist(synthetic)
    assert x==y
    assert len(x)<=8
    assert len(set(v["label"] for v in x))==len(x)
    assert {v["label"] for v in x}.issubset(
        {v["label"] for v in synthetic}
    )


@pytest.mark.parametrize("policy",POLICIES)
def test_original_builder_called_once_and_returns_legal_original_capacity(policy):
    inst,source=build_small_instance()
    original_sha=content_hash(source)
    instance_sha=content_hash(inst)
    state=UavMecState(
        inst,deepcopy(source),ScreenedProxyObjectiveEvaluator()
    )
    destroyed=ops._destroy_tasks(state,["S1","S2"])
    old=ops.make_repair_operators()
    counters=P32Counters(policy)
    new=make_repair_list(policy,counters,SMALL)
    assert [name for name,_ in old]==[name for name,_ in new]
    for (_,old_fn),(_,new_fn) in zip(old,new):
        r1=old_fn(destroyed,np.random.default_rng(42))
        r2=new_fn(destroyed,np.random.default_rng(42))
        validate_solution(inst,r2.solution)
        assert not r2.removed_tasks
        assert set(r2.solution.contact_visits).issubset(
            set(r1.solution.contact_visits)
        )
        if policy=="sham_joint":
            assert content_hash(r2.solution)==content_hash(r1.solution)
    assert counters.legacy_full_builder_calls==len(old)
    assert counters.calls==len(old)
    assert content_hash(source)==original_sha
    assert content_hash(inst)==instance_sha


def test_sham_direct_postrepair_does_not_change_any_discrete_decision():
    inst,source=build_small_instance()
    frozen_sha=content_hash(source)
    state=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    counters=P32Counters("sham_joint")
    result=refine_one(state,"sham_joint",counters,SMALL)
    assert content_hash(result.solution)==frozen_sha
    assert content_hash(state.solution)==frozen_sha
    assert counters.chosen_other_D==0
