"""P17 original greedy MEC action eligibility must be cheaper than full rebuild."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from p17_actionable_insertion_repair import (
    POLICIES,TOP_K,ActionabilityCounters,
    make_actionable_repair,make_actionable_repair_list,
    preview_actionable_reuse,choose_actionable,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState,operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("kind",["cheapest","regret2"])
@pytest.mark.parametrize("removed",[["S1"],["S1","S2"],["S2","S3"]])
def test_original_100percent_repaired_D_identity_for_cost_sham(kind,removed):
    inst,sol=build_small_instance()
    old_sha=content_hash(sol)
    broken=ops._destroy_tasks(
        UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator()),
        removed)
    original=(ops.cheapest_insertion_repair if kind=="cheapest"
              else ops.regret2_insertion_repair)
    a=original(broken,np.random.default_rng(67))
    stats=ActionabilityCounters("proxy_sham")
    b=make_actionable_repair(kind,"proxy_sham",stats)(
        broken,np.random.default_rng(67))
    assert content_hash(a.solution)==content_hash(b.solution)
    assert b.removed_tasks==[]
    assert stats.original_builder_count==1
    assert stats.cheap_previews<=TOP_K
    assert stats.selected_non_top1==0
    assert content_hash(sol)==old_sha


@pytest.mark.parametrize("policy",POLICIES)
def test_one_original_MEC_builder_called_and_no_invalid_virtual_decision(policy):
    inst,sol=build_small_instance()
    state=UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
    broken=ops._destroy_tasks(state,["S1","S2"])
    builder=ops._finish_repair
    stats=ActionabilityCounters(policy)
    with patch.object(ops,"_finish_repair",wraps=builder) as spy:
        finished=make_actionable_repair("cheapest",policy,stats)(
            broken,np.random.default_rng(87))
        assert spy.call_count==1
    validate_solution(inst,finished.solution)
    assert not finished.removed_tasks
    assert stats.original_builder_count==1
    assert stats.cheap_previews<=TOP_K
    assert stats.cheap_scoring_wall_s>=0.0


def test_no_real_MEC_repair_or_exact_stage1_for_single_proxy_candidate():
    inst,sol=build_small_instance()
    state=UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
    broken=ops._destroy_tasks(state,["S1"])
    opt=ops._options_for_task(broken,"S1")[0]
    old=content_hash(broken.solution)
    stats=ActionabilityCounters("proxy_actionable")
    with patch.object(ops,"_finish_repair",side_effect=RuntimeError("NO full MEC builder")):
        result=preview_actionable_reuse(broken,"S1",opt,1,stats)
    assert stats.cheap_local_proxy_calls==1
    assert result["rank"]==1
    assert result["state"].solution.task_decisions["S1"].mode.value=="local"
    assert content_hash(broken.solution)==old


def test_accepted_proxy_reuse_selector_handles_no_actions_and_valid_critical_candidate():
    sample=[
        {"rank":1,"base_proxy":(1,0.3,0.4,900,400),
         "best_accepted_reuse":None,"original_critical":True,"reachable_contacts":1},
        {"rank":2,"base_proxy":(1,0.4,0.5,700,420),
         "best_accepted_reuse":((0,0.,0.,920.,410.),"G_U1_1"),
         "original_critical":True,"reachable_contacts":2},
        {"rank":3,"base_proxy":(1,0.4,0.5,720,440),
         "best_accepted_reuse":None,"original_critical":False,"reachable_contacts":2},
    ]
    selected,reason=choose_actionable(sample,"proxy_actionable")
    assert selected["rank"]==2 and reason=="best_accepted_original_greedy_reuse"
    ok=[dict(x) for x in sample]
    ok[0]["base_proxy"]=(0,0.,0.,850.,400.)
    selected,reason=choose_actionable(ok,"proxy_actionable")
    assert selected["rank"]==1 and reason=="old_rank1_zero_proxy_violation"


@pytest.mark.parametrize("policy",POLICIES)
def test_two_original_repair_slot_names_and_count_preserved(policy):
    original=[name for name,_ in ops.make_repair_operators()]
    current=[name for name,_ in make_actionable_repair_list(
        policy,ActionabilityCounters(policy))]
    assert original==current


def test_unknown_policy_fails_closed():
    with pytest.raises(ValueError):
        make_actionable_repair("regret2","unknown",ActionabilityCounters("unknown"))
