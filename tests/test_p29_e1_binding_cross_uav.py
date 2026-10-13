"""P29 frozen cross-UAV options: legal direct E2 reuse and equal candidate pools."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from run_p29_e1_binding_cross_uav import (
    TARGET_GROUPS, RANKS,task_groups,_candidate_records,_read_only,_rank,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def test_binding_priority_and_control_use_original_E1_tasks():
    instance,source=build_small_instance()
    sha=content_hash(source)
    instance_sha=content_hash(instance)
    groups,meta=task_groups(instance,source,31)
    assert set(groups)==set(TARGET_GROUPS)
    assert groups["binding_chain_E1"]
    assert len({len(v) for v in groups.values()})==1
    assert all(t in meta["E1_offload_tasks_all"] for vs in groups.values() for t in vs)
    assert content_hash(source)==sha
    assert content_hash(instance)==instance_sha


def test_physical_cross_uav_task_reassignment_and_candidate_rankings():
    instance,source=build_small_instance()
    sha=content_hash(source)
    candidates,skipped=_candidate_records(instance,source,["S1","S2"])
    assert candidates
    for row in candidates:
        solution=row["D"]
        validate_solution(instance,solution)
        assert row["physical_D_SHA"]==content_hash(solution)
        assert row["from_UAV"]!=row["to_UAV"]
        score=_read_only(instance,solution)
        sample={**row,"read_only":score}
        for policy in RANKS:
            assert isinstance(_rank(sample,policy),tuple)
    assert content_hash(source)==sha


def test_seeded_controls_have_frozen_same_task_set():
    instance,source=build_small_instance()
    a,_=task_groups(instance,source,31)
    b,_=task_groups(instance,source,31)
    assert a==b
