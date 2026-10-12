"""P6 same-family model-targeted versus workload negative-control legal moves."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from postbound_conflict_moves import postbound_conflict_moves,_station_targets
from run_p6_postbound_probe import (
    ARMS,_eval_safe_bound,postbound_search,evaluate_source,
)
from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)


def _physical_station_stress():
    inst,sol=build_small_instance()
    x=deepcopy(inst)
    x.mecs["E1"]=replace(x.mecs["E1"],cpu_ghz=.12)
    return x,sol


@pytest.mark.parametrize("policy",("certificate","workload"))
def test_joint_resource_repair_builds_legal_alternate_mec_moves(policy):
    instance,source=_physical_station_stress()
    h=content_hash(source)
    bound=joint_station_bw_cpu_necessary_bound(instance,source,n_bins=12)
    assert bound["joint_necessary_reject"]
    tasks,metadata=_station_targets(
        instance,source,bound,policy=policy,limit=2)
    assert 1<=len(tasks)<=2,metadata
    moves,stats=postbound_conflict_moves(
        instance,source,policy=policy,
        target_limit=2,point_variants=2,
        joint_bound=bound)
    assert moves,stats
    assert stats["candidate_count"]==len(moves)
    assert stats["original_signature_unmodified"]
    assert any(label.startswith("p6_whole_batch_mec::")
               for label,_ in moves),stats
    seen=set()
    for label,candidate in moves:
        validate_solution(instance,candidate)
        cand_sha=content_hash(candidate)
        assert cand_sha!=h and cand_sha not in seen
        seen.add(cand_sha)
    assert content_hash(source)==h


def test_postbound_search_preserves_preselected_candidates_and_exact_cap():
    instance,source=build_small_instance()
    previous=content_hash(source)
    seed=[{"label":"small_original","sol":source,
           "metric":{"passed":True,"n_reasons":0,
                     "total_excess_s":0.,"route_distance_m":0.}}]
    for pol in ("workload","certificate"):
        shortlist,diag=postbound_search(
            instance,seed,policy=pol,
            include_whole_batch=pol=="certificate",
            source=source,original_selected=seed,
            postbound_soft_cap_s=2.,seed_limit=2,
            max_total_move_evals=5,
        )
        assert len(shortlist)<=3
        assert shortlist[0]["label"]=="small_original"
        assert diag["new_joint_necessary_passing"]==0
        assert diag["postbound_wall_s"]>=0
    assert content_hash(source)==previous


def test_original_Stage1_and_Stage2_do_not_receive_invalid_repair():
    instance,sol=build_small_instance()
    sha=content_hash(sol)
    label,diagnosis=_eval_safe_bound(instance,sol)
    assert label=="joint_necessary_pass",diagnosis
    assert ARMS==(
        "p5_joint48","postbound_workload",
        "postbound_certificate_no_batch","postbound_certificate_full",
    )
    assert content_hash(sol)==sha


@pytest.mark.parametrize("invalid",["nonsense","","random_no_model"])
def test_invalid_target_policy_is_rejected(invalid):
    instance,source=_physical_station_stress()
    with pytest.raises(ValueError):
        postbound_conflict_moves(instance,source,policy=invalid)
