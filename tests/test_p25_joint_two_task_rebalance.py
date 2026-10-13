"""P25 2-task different-decision repair stays legal under ORIGINAL hardware."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from run_p25_joint_two_task_rebalance import (
    POLICIES, pick_parent_roots, expand_second_moves, common_shortlist,
    audit_joint, final_score,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def test_frozen_original_source_and_distinct_two_task_moves_and_common_pool():
    instance, source=build_small_instance()
    inst_sha=content_hash(instance)
    source_sha=content_hash(source)
    first,parents,skip=pick_parent_roots(instance,source,42)
    assert first and parents
    assert isinstance(skip,dict)
    assert content_hash(source)==source_sha
    assert content_hash(instance)==inst_sha
    second=expand_second_moves(instance,parents)
    assert second
    shortlist=common_shortlist(second,42)
    assert shortlist
    seen=set()
    for r,state in shortlist:
        validate_solution(instance,state)
        assert r["sha"]==content_hash(state)
        assert r["sha"] not in seen
        assert r["changed_task"]!=r["root"]["first_task"]
        seen.add(r["sha"])
        r["joint"]=audit_joint(instance,state,r)
        assert "passes_joint_necessary_test" in r["joint"]
    assert content_hash(source)==source_sha
    for policy in POLICIES:
        sorted_pool=sorted([r for r,_ in shortlist],key=lambda x:final_score(x,policy))
        assert len(sorted_pool)==len(shortlist)
        assert {r["sha"] for r in sorted_pool}==seen


def test_seeded_parent_choice_reproduces_identical_original_snapshot():
    instance,source=build_small_instance()
    _,parents1,_=pick_parent_roots(instance,source,42)
    _,parents2,_=pick_parent_roots(instance,source,42)
    assert [r["sha"] for r,_,_ in parents1]==[r["sha"] for r,_,_ in parents2]
