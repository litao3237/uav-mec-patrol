"""Infeasible-bridge unit tests: isolate search depth vs structurally diverse beam."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from progressive_bridge_core import (
    ARMS, _bridge_beam, _legacy_global_key,
    search_progressive, run_progressive_arm,
)
from run_queue_guided_repair import new_move_candidates
from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution


def test_bridge_can_keep_temporarily_worse_total_if_root_deadline_improves():
    def row(label, total, root, family):
        return {
            "sig":label, "label":label,
            "family":family,
            "metric":{
                "passed":False, "n_reasons":1,
                "total_excess_s":total,
                "root_excess_s":root,
                "worst_task_excess_s":total,
                "route_distance_m":100.0,
            },
        }
    improved_global = row("early_task::A",6.0,5.0,"early_task")
    root_bridge = row("cross_uav_fifo_relocation::B",9.0,2.0,"cross_uav")
    diverse,trace = _bridge_beam(
        [root_bridge,improved_global],beam_width=2,
        initial_root_excess_s=8.0,
    )
    assert [r["label"] for r in diverse] == [
        "early_task::A","cross_uav_fifo_relocation::B",
    ]
    assert diverse[1]["metric"]["total_excess_s"] > diverse[0]["metric"]["total_excess_s"]
    assert diverse[1]["metric"]["root_excess_s"] < diverse[0]["metric"]["root_excess_s"]
    assert trace["explicit_root_bridge_selections"] == 1


def test_a_bridge_not_bounded_by_root_improvement_is_discarded():
    row=lambda label,total,root:{
        "sig":label,"label":label,"metric":{
            "passed":False,"n_reasons":1,
            "total_excess_s":total,
            "root_excess_s":root,
            "worst_task_excess_s":total,
            "route_distance_m":100.,
        },
    }
    layer=[
        row("early_task::A",6.,6.),
        row("cross_uav_fifo_relocation::B",200.,2.),
    ]
    result,trace=_bridge_beam(layer,beam_width=2,initial_root_excess_s=8.)
    assert trace["explicit_root_bridge_selections"]==0
    assert result[0]["label"]=="early_task::A"


def failed_small():
    instance,sol=build_small_instance()
    stressed=deepcopy(instance)
    stressed.tasks={
        task_id:replace(task,deadline_s=1.0)
        for task_id,task in instance.tasks.items()
    }
    return stressed,sol


@pytest.mark.parametrize("policy",("plain_depth","bridge_depth"))
def test_progressive_search_preserves_all_input_and_strict_shortlist(policy):
    instance,solution=failed_small()
    old_hash=content_hash(solution)
    candidates,diagnostic=search_progressive(
        instance,solution,policy=policy,
        beam_width=2,depth=3,exact_limit=3,
        generation_cap_s=3.0,
    )
    assert content_hash(solution)==old_hash
    assert len(candidates)<=3
    assert diagnostic["actual_depth"]<=3
    assert diagnostic["precheck_passing"]>=len(candidates)
    assert diagnostic["original_queue"]["passed"] is False
    assert len(diagnostic["root_task_ids"])>=1
    for candidate in candidates:
        validate_solution(instance,candidate["sol"])
        assert candidate["metric"]["passed"]
        assert 1<=candidate["depth"]<=3


def test_the_depth_only_arm_calls_exact_same_candidate_generator_as_old_queue():
    instance,solution=failed_small()
    old=[s for s,_ in new_move_candidates(
        instance,solution,mode="queue_dependency_joint",offenders=3,
    )]
    search,diags=search_progressive(
        instance,solution,policy="plain_depth",
        beam_width=2,depth=1,exact_limit=3,
        generation_cap_s=5.0,
    )
    assert diags["unique_candidates"]<=len(old)
    assert diags["actual_depth"]<=1


def test_generation_timer_does_not_claim_hard_CVX_preemption():
    instance,solution=failed_small()
    candidates,diag=search_progressive(
        instance,solution,policy="bridge_depth",
        beam_width=2,depth=4,exact_limit=3,
        generation_cap_s=.00001,
    )
    assert diag["generation_soft_overrun"] or diag["actual_depth"]<=4
    assert len(candidates)<=3


def test_new_deep_search_does_not_increase_the_strict_CVX_candidate_quota():
    instance,solution=failed_small()
    result=run_progressive_arm(
        instance,solution,
        arm="queue_bridge_depth4",
        beam_width=2,depth=2,exact_limit=1,
        generation_cap_s=2.,
    )
    assert result["strict_stage1_oracle_calls"]<=1
    assert result["strict_candidate_limit"]==1
    assert result["strict_energy_j"] is None
    assert not result["strict_both_recovered"]


def test_armlist_freezes_operator_family_and_paired_ablation():
    assert ARMS==(
        "queue_original_depth2",
        "queue_plain_depth4",
        "queue_bridge_depth4",
    )
