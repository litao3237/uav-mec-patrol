"""P15 cheap virtual contact predictions cannot change original physics."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from p15_cheap_virtual_contact_repair import (
    POLICIES,TOP_K,CheapCounters,make_cheap_repair,
    build_cheap_repair_list,cheap_score_for_option,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("kind",["cheapest","regret2"])
@pytest.mark.parametrize("tasks",[["S1"],["S1","S2"],["S2","S3"]])
def test_cheap_sham_exactly_reproduces_original_build_and_rng(kind,tasks):
    inst,source=build_small_instance()
    original_sha=content_hash(source)
    start=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(start,tasks)
    control=(ops.cheapest_insertion_repair if kind=="cheapest"
             else ops.regret2_insertion_repair)(
        destroyed,np.random.default_rng(317))
    stat=CheapCounters("cheap_sham")
    sham=make_cheap_repair(kind,"cheap_sham",stat)(
        destroyed,np.random.default_rng(317))
    assert content_hash(sham.solution)==content_hash(control.solution)
    assert control.removed_tasks==sham.removed_tasks==[]
    assert stat.full_MEC_finishes==1
    assert stat.selected_non_top1==0
    assert stat.evaluated_positions<=TOP_K
    assert stat.virtual_offload_checked>=0
    assert content_hash(source)==original_sha


@pytest.mark.parametrize("policy",POLICIES)
def test_registered_proxy_returns_complete_legal_original_D_and_one_MEC_build(policy):
    inst,original=build_small_instance()
    sha=content_hash(original)
    state=UavMecState(inst,deepcopy(original),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(state,["S1","S2"])
    stats=CheapCounters(policy)
    production=ops._finish_repair
    with patch.object(ops,"_finish_repair",wraps=production) as spy:
        out=make_cheap_repair("cheapest",policy,stats)(
            destroyed,np.random.default_rng(4))
        assert spy.call_count==1
    validate_solution(inst,out.solution)
    assert stats.full_MEC_finishes==1
    assert stats.evaluated_positions<=TOP_K
    assert stats.all_cheap_prediction_wall_s>=0
    assert content_hash(original)==sha


def test_virtual_offload_does_not_commit_hypothetical_task_mode():
    inst,source=build_small_instance()
    start=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    broken=ops._destroy_tasks(start,["S1"])
    option=ops._options_for_task(broken,"S1")[0]
    snapshot=content_hash(broken.solution)
    stats=CheapCounters("cheap_virtual")
    measure=cheap_score_for_option(
        broken,"S1",option,rank=1,counters=stats)
    assert measure["state"].solution.task_decisions["S1"].mode.value=="local"
    assert content_hash(broken.solution)==snapshot
    assert stats.evaluated_positions==1
    assert measure["best_virtual_key"]<=measure["local_key"]


def test_guarded_returns_same_as_original_when_original_local_queue_passes():
    inst,source=build_small_instance()
    broken=ops._destroy_tasks(
        UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator()),
        ["S1"])
    orig=ops.cheapest_insertion_repair(broken,np.random.default_rng(7))
    stats=CheapCounters("cheap_guarded")
    updated=make_cheap_repair("cheapest","cheap_guarded",stats)(
        broken,np.random.default_rng(7))
    assert content_hash(orig.solution)==content_hash(updated.solution)
    assert stats.original_top1_guarded==1
    assert stats.selected_non_top1==0


@pytest.mark.parametrize("policy",POLICIES)
def test_two_original_repair_operator_slots_retained(policy):
    from uav_mec.algorithms.alns import operators as op
    old=[name for name,_ in op.make_repair_operators()]
    new=[name for name,_ in build_cheap_repair_list(
        policy,CheapCounters(policy))]
    assert old==new


def test_invalid_cheap_policy_is_rejected():
    with pytest.raises(ValueError):
        make_cheap_repair("cheapest","cheapest",
                          CheapCounters("cheapest"))
