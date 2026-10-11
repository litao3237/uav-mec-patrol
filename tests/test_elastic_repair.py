"""Contract tests for source-elastic-guided same-D joint repair experiment."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from elastic_repair_core import (
    ARM_NAMES, elastic_conflict_targets, elastic_focus_moves,
    search_elastic, old_queue_arm,
)
from _queue_repair_reference import new_move_candidates
from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution


def fake_elastic(instance):
    return {
        "numerically_credible":True,
        "normalized_total_elastic_slack":.15,
        "top_constraints":[{
            "constraint":"deadline::S2", "family":"deadline",
            "normalized_slack":.10, "physical_slack":12.0,
        }],
        "top_dependency_context":[{
            "task_id":"S2", "diagnostic_slack_s":12.,
            "dependency_context":{
                "execution":"local_fifo", "UAV":"U1",
                "predecessors":["S1"],
            },
        }],
    }


def too_tight():
    instance,solution=build_small_instance()
    instance=deepcopy(instance)
    instance.tasks={
        t:replace(task,deadline_s=1.0)
        for t,task in instance.tasks.items()
    }
    return instance,solution


def test_source_elastic_targets_include_blocking_predecessors():
    instance,sol=build_small_instance()
    focus=elastic_conflict_targets(instance,sol,fake_elastic(instance))
    assert focus["credible"]
    assert focus["positive_source_slack"]
    assert focus["targets"]==["S2"]
    assert focus["predecessors"]==["S1"]
    assert focus["task_weights"]["S2"]>focus["task_weights"]["S1"]


def test_missing_diagnostic_remains_inconclusive_not_fake_conflict():
    instance,sol=build_small_instance()
    focus=elastic_conflict_targets(instance,sol,{"numerically_credible":False})
    assert not focus["credible"]
    assert not focus["positive_source_slack"]
    assert focus["targets"]==[]
    assert focus["source_slack"] is None


def test_all_targeted_operators_preserve_original_D_and_candidate_structure():
    instance,sol=build_small_instance()
    start=content_hash(sol)
    moves=elastic_focus_moves(
        instance,sol,
        elastic_conflict_targets(instance,sol,fake_elastic(instance)),
    )
    assert moves
    assert content_hash(sol)==start
    keys=[]
    for label,proposal in moves:
        validate_solution(instance,proposal)
        assert content_hash(proposal)!=start
        assert sorted(proposal.iter_task_ids())==sorted(sol.iter_task_ids())
        keys.append(content_hash(proposal))
    assert len(keys)==len(set(keys))


def test_same_moves_policy_does_not_generate_new_candidate_families():
    instance,sol=too_tight()
    before=content_hash(sol)
    baseline=new_move_candidates(
        instance,sol,mode="queue_dependency_joint",
    )
    short,trace=search_elastic(
        instance,sol,elastic=fake_elastic(instance),
        arm="elastic_rank_same_moves",
        beam_width=1,depth=1,exact_limit=3,
    )
    assert trace["generated_unique"]==len(baseline)
    assert trace["elastic_focus"]["targets"]==["S2"]
    assert len(short)<=3
    assert content_hash(sol)==before


@pytest.mark.parametrize("arm",["elastic_rank_same_moves","elastic_targeted_joint"])
def test_elastic_candidate_budget_is_strict_and_only_queue_passing(arm):
    instance,sol=too_tight()
    shortlisted,stats=search_elastic(
        instance,sol,elastic=fake_elastic(instance),
        arm=arm,beam_width=2,depth=2,exact_limit=2,
    )
    assert len(shortlisted)<=2
    assert len(stats["history"])<=2
    assert stats["queue_precheck_passing"]>=len(shortlisted)
    for key,label,c,s,depth in shortlisted:
        assert s["passed"]
        validate_solution(instance,c)


def test_frozen_old_comparators_have_same_hard_cvx_limit():
    assert ARM_NAMES==(
        "greedy_mec","old_lb_joint","queue_joint",
        "elastic_rank_same_moves","elastic_targeted_joint",
    )
    instance,sol=too_tight()
    for arm in ("greedy_mec","old_lb_joint","queue_joint"):
        r=old_queue_arm(instance,sol,arm,
                        beam_width=1,depth=1,exact_limit=1)
        assert r["strict_cvx_calls"]<=1
        assert not r["strict_both_recovered"]
        assert r["charged_diagnostic_s"]==0
