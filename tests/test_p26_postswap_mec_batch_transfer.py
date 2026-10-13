"""P26 batch transfer creates distinct, complete, original-hardware legal D."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from run_p26_postswap_mec_batch_transfer import (
    POLICIES,_bundles,generate_batch_moves,joint_read_only,rank,
)
from run_p24_postswap_offload_redistribution import _audit_candidate
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def test_preserved_original_model_and_legal_real_multiple_task_transfer():
    instance,source=build_small_instance()
    source_sha=content_hash(source)
    instance_sha=content_hash(instance)
    opts,skips=generate_batch_moves(instance,source)
    assert opts,skips
    assert any(len(o["task_bundle"])>=2 for o in opts)
    for cand in opts:
        validate_solution(instance,cand["D"])
        assert cand["candidate_SHA"]==content_hash(cand["D"])
        assert cand["old_station"]!=cand["new_station"]
        assert len(cand["task_bundle"])>=2
        audit=_audit_candidate(instance,cand["D"])
        joint=joint_read_only(instance,cand["D"],audit["queue"]["queue_necessary_pass"])
        rec={**cand,"audit":audit,"joint":joint}
        for p in POLICIES:
            if p!="random_rank":
                assert isinstance(rank(rec,p),tuple)
    assert content_hash(instance)==instance_sha
    assert content_hash(source)==source_sha


def test_task_bundle_selection_has_complete_and_diverse_batch_sizes():
    inst,_=build_small_instance()
    batches=_bundles(inst,["S1","S2","S3"])
    assert batches
    assert any(len(tasks)==3 for _,tasks in batches)
    assert all(len(set(tasks))==len(tasks) for _,tasks in batches)
