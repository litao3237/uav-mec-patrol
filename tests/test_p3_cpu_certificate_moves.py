"""P3 model-targeted repair is diagnostic-only and source-immutable."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

import pytest
from cpu_certificate_repair_moves import (
    certificate_focus_tasks,heavy_task_control,cpu_conflict_moves,
)
from run_p3_cpu_certificate_probe import _new_search,_choose_cpu_screened
from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution


@pytest.mark.parametrize("policy",("certificate","workload"))
def test_certificate_targeted_moves_are_legal_and_nonmutating(policy):
    instance,source=build_small_instance()
    frozen=content_hash(source)
    targets,report=certificate_focus_tasks(instance,source,task_limit=3)
    assert targets and report["details"]
    assert len(set(targets))==len(targets)
    chosen=heavy_task_control(instance,source,task_limit=len(targets))
    assert len(chosen)==len(targets)
    moves,diag=cpu_conflict_moves(instance,source,policy=policy)
    assert diag["actual_targets"]
    assert moves
    assert diag["valid_unique_moves"]==len(moves)
    hashes=set()
    for label,candidate in moves:
        validate_solution(instance,candidate)
        assert label.startswith("cpu_target_")
        h=content_hash(candidate)
        assert h!=frozen and h not in hashes
        hashes.add(h)
    assert content_hash(source)==frozen


def test_lower_cpu_capacity_focus_is_attributed_to_actual_station_pair():
    instance,source=build_small_instance()
    scaled=deepcopy(instance)
    old=scaled.mecs["E1"]
    scaled.mecs["E1"]=replace(old,cpu_ghz=0.12)
    targets,report=certificate_focus_tasks(scaled,source,task_limit=2)
    assert report["bound"]["certified_cpu_share_failure"]
    assert targets
    assert all(item["station_id"]=="E1" for item in report["details"])


def test_same_numerical_precheck_is_required_before_strict_evaluation():
    instance,source=build_small_instance()
    frozen=content_hash(source)
    for policy in ("certificate","workload"):
        ordered,diag=_new_search(
            instance,source,policy=policy,protect=policy=="certificate",
            beam_width=2,depth=1,generation_cap_s=12.,
        )
        candidates,filter_meta=_choose_cpu_screened(instance,ordered,limit=3)
        assert len(candidates)<=3
        assert filter_meta["cpu_gate_checked"]>=len(candidates)
        assert all(x["metric"]["passed"] for x in candidates)
        assert diag["policy"]==policy
        assert diag["depth_reached"]<=1
    assert content_hash(source)==frozen
