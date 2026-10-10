"""Invariants for certificate-guided feasibility *diagnostic*, not acceptance."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from run_highload_rescue_probe import (
    ARMS,STRESS_PROFILES,precheck_score,candidate_moves,
    select_candidates,strict_recovery,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def force_deadline_failure(instance):
    broken=deepcopy(instance)
    broken.tasks={
        tid:replace(task,deadline_s=5.0)
        for tid,task in broken.tasks.items()
    }
    return broken


def test_exact_precheck_failure_summary_tracks_local_vs_offload():
    instance,sol=build_small_instance()
    stressed=force_deadline_failure(instance)
    p=precheck_score(stressed,sol)
    assert not p["passed"]
    assert p["n_reasons"]>=1
    assert p["max_task_excess_s"]>0
    assert sum(p["offenders_by_execution_mode"].values())==len(p["task_offenders"])
    assert all(x["excess_s"]>0 for x in p["task_offenders"])


@pytest.mark.parametrize("families",[("reorder",),("contact_mode",),
                                    ("reorder","contact_mode")])
def test_structurally_legal_guided_moves_do_not_mutate_source(families):
    instance,sol=build_small_instance()
    stressed=force_deadline_failure(instance)
    original=content_hash(sol)
    moves=candidate_moves(
        stressed,sol,families=families,limit_offenders=3,
    )
    assert content_hash(sol)==original
    for label,c in moves:
        validate_solution(stressed,c)
        assert content_hash(c)!=original
        assert sorted(c.iter_task_ids())==sorted(sol.iter_task_ids())
        assert label
    assert len({content_hash(c) for _,c in moves})==len(moves)


def test_bounded_beam_keeps_unqualified_candidates_without_making_up_energy():
    instance,sol=build_small_instance()
    stressed=force_deadline_failure(instance)
    shortlist,stats=select_candidates(
        stressed,sol,"guided_joint",
        beam_width=2,max_depth=2,per_arm_eval_limit=3,
    )
    assert len(shortlist)<=3
    assert stats["generated_unique"]>=0
    assert len(stats["depth"])<=2
    for key,label,c,metric,depth in shortlist:
        assert metric["passed"]
        assert 1<=depth<=2
        validate_solution(stressed,c)


def test_original_greedy_is_a_distinct_comparator():
    instance,sol=build_small_instance()
    stressed=force_deadline_failure(instance)
    result=strict_recovery(
        stressed,sol,"greedy_mec",
        beam_width=1,max_depth=1,exact_limit=1,
    )
    assert result["arm"]=="greedy_mec"
    assert "stage1_status" in result
    assert result["both_qualified"] is False
    assert result["strict_energy_stage1_j"] is None


def test_only_two_high_load_pressure_axes_are_probed():
    assert STRESS_PROFILES==(
        "compute_x1p5","compute_x2p0","deadline_x0p9","deadline_x0p8",
    )
    assert ARMS==(
        "greedy_mec","guided_reorder","guided_contact_mode","guided_joint",
    )
