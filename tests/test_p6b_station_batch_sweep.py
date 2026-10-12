"""P6b station-wide versus task-specific contact reassignment guards."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from station_batch_sweep_moves import (
    POLICIES,station_batch_moves,_candidate_visits,
)
from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation import build_event_info,visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)


def stress():
    inst,solution=build_small_instance()
    inst=deepcopy(inst)
    inst.mecs["E1"]=replace(inst.mecs["E1"],cpu_ghz=.12)
    bound=joint_station_bw_cpu_necessary_bound(inst,solution,n_bins=12)
    assert bound["joint_necessary_reject"]
    return inst,solution,bound


@pytest.mark.parametrize("policy",POLICIES)
def test_whole_batch_changes_only_contact_destination_and_is_structurally_legal(policy):
    inst,source,certificate=stress()
    before=content_hash(source)
    moves,meta=station_batch_moves(
        inst,source,certificate,policy=policy)
    assert moves and meta["structurally_valid_moves"]==len(moves),meta
    originals=build_event_info(inst,source)
    assert meta["target_station"]=="E1"
    hashes=set()
    for label,changed,why in moves:
        assert label.startswith("p6b_move_batch::")
        validate_solution(inst,changed)
        assert changed.task_decisions==source.task_decisions
        assert changed.routes==source.routes
        assert len(changed.contact_visits)==len(source.contact_visits)
        only=[v for v in source.contact_visits
              if source.contact_visits[v].point_id!=changed.contact_visits[v].point_id]
        assert only==[why["source_visit"]]
        assert why["source_station"]=="E1"
        assert why["destination_station"]=="E2"
        assert why["batch_tasks"]==originals.batch_tasks[only[0]]
        assert visit_mec_id(inst,changed,only[0])=="E2"
        sha=content_hash(changed)
        assert sha not in hashes and sha!=before
        hashes.add(sha)
    assert content_hash(source)==before


def test_certificate_selected_pairs_and_all_station_visits_are_scope_limited():
    inst,source,certificate=stress()
    all_visits,all_data=_candidate_visits(
        inst,source,certificate,policy="station_all_contacts")
    assert len(all_visits)==2
    assert set(all_data["visits"])==set(all_visits)
    for policy in POLICIES[1:]:
        visits,record=_candidate_visits(inst,source,certificate,policy=policy)
        assert 1<=len(visits)<=2
        assert set(visits)<=set(all_visits)
        assert record["target_station"]=="E1"


@pytest.mark.parametrize("mode",["unknown","","unsafe"])
def test_unregistered_visit_selection_policy_is_rejected(mode):
    inst,source,certificate=stress()
    with pytest.raises(ValueError):
        station_batch_moves(inst,source,certificate,policy=mode)
