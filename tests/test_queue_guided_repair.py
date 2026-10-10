"""Regression contracts: queue-targeted repair is disjoint from original comparator."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

import _legacy_rescue_reference as legacy
from run_queue_guided_repair import (
    ARMS,STRESS_PROFILES,queue_gap,added_dependency_moves,
    new_move_candidates,search_queue,
)
from uav_mec.instances.small import build_small_instance
from uav_mec.evaluation.validator import validate_solution
from uav_mec.analysis.experiment_snapshot import content_hash


def stressed():
    instance,solution=build_small_instance()
    instance=deepcopy(instance)
    instance.tasks={
        t:replace(task,deadline_s=5.0)
        for t,task in instance.tasks.items()
    }
    return instance,solution


def test_queue_gap_tracks_fifo_pressure_beyond_original_no_queue_gap():
    instance,solution=stressed()
    a=legacy.precheck_score(instance,solution)
    b=queue_gap(instance,solution)
    assert not a["passed"]
    assert not b["passed"]
    assert b["total_optimistic_excess_s"] >= a["total_optimistic_excess_s"] - 1e-6
    assert b["max_excess_s"] >= a["max_task_excess_s"] - 1e-6


def test_new_dependency_candidates_are_structurally_legal_and_source_immutable():
    instance,solution=stressed()
    before=content_hash(solution)
    moves=added_dependency_moves(instance,solution,limit=3)
    assert content_hash(solution)==before
    assert len(moves)==len({content_hash(c) for _,c in moves})
    for label,c in moves:
        validate_solution(instance,c)
        assert sorted(c.iter_task_ids()) == sorted(solution.iter_task_ids())
        assert label.startswith((
            "fifo_predecessor_reuse::",
            "fifo_predecessor_new_contact::",
            "cross_uav_fifo_relocation::",
        ))


def test_queue_rank_can_use_exact_legacy_candidate_generator():
    instance,solution=stressed()
    a=legacy.candidate_moves(
        instance,solution,families=("reorder","contact_mode"),limit_offenders=3
    )
    b=new_move_candidates(
        instance,solution,mode="queue_rank_same_moves",offenders=3,
    )
    # Both call the same frozen generator; duplicate structural signatures
    # are filtered deterministically by each path.
    assert [label for label,c in a] == [label for label,c in b]


@pytest.mark.parametrize("mode",["queue_rank_same_moves","queue_dependency_joint"])
def test_bounded_queue_search_preserves_all_strict_resource_validation(mode):
    instance,solution=stressed()
    shortlist,stats=search_queue(
        instance,solution,mode=mode,
        beam_width=2,max_depth=2,exact_limit=2,
    )
    assert len(shortlist)<=2
    assert stats["unique_generated"]>=0
    assert stats["queue_pass_candidates"]>=len(shortlist)
    assert len(stats["depth"])<=2
    for rank,label,c,score,depth in shortlist:
        assert score["passed"]
        assert 1<=depth<=2
        validate_solution(instance,c)


def test_declared_stress_and_arms_match_pre_registered_protocol():
    assert ARMS == (
        "original_greedy","legacy_joint",
        "queue_rank_same_moves","queue_dependency_joint",
    )
    assert STRESS_PROFILES == (
        "compute_x1p5","compute_x2p0","deadline_x0p9","deadline_x0p8",
    )
