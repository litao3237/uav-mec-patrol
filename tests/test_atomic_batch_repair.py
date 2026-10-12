"""Strict structural/selection tests for atomic UAV-MEC dependency bundles."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from atomic_batch_moves import atomic_batch_moves
from atomic_batch_search import (
    ARMS,atomic_search,run_atomic_arm,
)
from progressive_bridge_core import search_progressive
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.domain import Route,StopType,TaskDecision
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def fifo_stress_with_three_locals():
    instance,sol=build_small_instance()
    inst=deepcopy(instance)
    candidate=deepcopy(sol)
    candidate.routes["U1"]=Route(
        "U1",tuple(s for s in candidate.routes["U1"].stops
                   if s.kind is not StopType.CONTACT),
    )
    candidate.contact_visits.pop("V11")
    for t in ("S1","S2","S3"):
        candidate.task_decisions[t]=TaskDecision.local()
    inst.tasks["S3"]=replace(inst.tasks["S3"],deadline_s=1.)
    validate_solution(inst,candidate)
    return inst,candidate


def offload_batch_stress():
    instance,sol=build_small_instance()
    inst=deepcopy(instance)
    inst.tasks["S2"]=replace(inst.tasks["S2"],deadline_s=1.)
    return inst,sol


def test_double_local_offload_generates_real_contact_batch():
    instance,solution=fifo_stress_with_three_locals()
    before=content_hash(solution)
    out,meta=atomic_batch_moves(instance,solution,include_cross_uav=False)
    assert out,meta
    assert meta["families"]["bundle_new_contact"]>0
    for label,candidate in out:
        validate_solution(instance,candidate)
        assert sorted(candidate.iter_task_ids())==sorted(solution.iter_task_ids())
        assert content_hash(candidate)!=before
    assert content_hash(solution)==before


def test_atomic_pair_cross_uav_is_distinct_and_structurally_legal():
    instance,sol=fifo_stress_with_three_locals()
    moves,meta=atomic_batch_moves(instance,sol,include_cross_uav=True)
    assert meta["families"]["bundle_cross_uav"]>0,meta
    assert any(label.startswith("bundle_cross_uav") for label,_ in moves)
    for label,candidate in moves:
        validate_solution(instance,candidate)


def test_atomic_mec_edf_batch_split_shifts_two_offloaded_tasks_together():
    instance,sol=offload_batch_stress()
    initial=content_hash(sol)
    moves,meta=atomic_batch_moves(instance,sol)
    selected=[(label,c) for label,c in moves
              if label.startswith("bundle_early_split")]
    assert selected,meta
    for label,c in selected:
        validate_solution(instance,c)
        assert c.task_decisions["S2"].mode.value=="offload"
        assert c.task_decisions["S2"].contact_visit_id==(
            c.task_decisions["S1"].contact_visit_id
        )
        assert content_hash(c)!=initial
    assert content_hash(sol)==initial


def test_atom_disabled_matches_exact_plain4_comparator_when_no_timeout():
    instance,sol=fifo_stress_with_three_locals()
    expected,stats=search_progressive(
        instance,sol,policy="plain_depth",
        beam_width=2,depth=2,exact_limit=3,generation_cap_s=15.,
    )
    observed,meta=atomic_search(
        instance,sol,include_atomic=False,
        beam_width=2,depth=2,exact_limit=3,generation_cap_s=15.,
    )
    assert [x["label"] for x in observed]==[x["label"] for x in expected]
    assert meta["unique_generated"]==stats["unique_candidates"]
    assert meta["queue_passed"]==stats["precheck_passing"]


@pytest.mark.parametrize("arm",ARMS[2:])
def test_unchanged_strict_exact_candidate_limit_and_no_source_mutation(arm):
    instance,sol=fifo_stress_with_three_locals()
    before=content_hash(sol)
    result=run_atomic_arm(
        instance,sol,arm=arm,beam_width=2,depth=2,
        exact_limit=1,generation_cap_s=3.,
    )
    assert content_hash(sol)==before
    assert result["strict_stage1_oracle_calls"]<=1
    assert result["strict_candidate_limit"]==1
    assert result["strict_energy_j"] is None
    assert not result["strict_both_recovered"]


def test_locked_ablation_arms_are_not_called_original_paper_algorithms():
    assert ARMS==(
        "queue_original_depth2",
        "queue_plain_depth4",
        "atomic_offload_depth4",
        "atomic_offload_and_cross_uav_depth4",
    )


@pytest.mark.parametrize("policy",(
    "global","one_pure_legacy","pure_legacy_only",
))
def test_counterfactual_beam_policy_never_changes_strict_acceptance_rules(policy):
    instance,sol=fifo_stress_with_three_locals()
    before=content_hash(sol)
    shortlisted,diag=atomic_search(
        instance,sol,include_atomic=True,include_cross_uav=True,
        beam_policy=policy,shortlist_policy="one_pure_legacy",
        depth=2,beam_width=2,exact_limit=2,generation_cap_s=15.,
    )
    assert len(shortlisted)<=2
    assert all(x["metric"]["passed"] for x in shortlisted)
    assert all("pure_legacy" in x for x in shortlisted)
    assert all(len(step["beam_labels"])<=2 for step in diag["trace"])
    assert content_hash(sol)==before


def test_counterfactual_invalid_policy_fails_closed():
    instance,sol=fifo_stress_with_three_locals()
    with pytest.raises(ValueError):
        atomic_search(instance,sol,include_atomic=True,
                      beam_policy="made_up")


def test_optin_atomic_diagnostic_ancestry_is_structurally_sound():
    instance,sol=fifo_stress_with_three_locals()
    original=content_hash(sol)
    shortlist,stats=atomic_search(
        instance,sol,include_atomic=True,include_cross_uav=True,
        beam_width=2,depth=3,exact_limit=8,
        generation_cap_s=15.,diagnostic_trace=True,
    )
    assert len(shortlist)==len(stats["diagnostic_shortlist"])
    for row,snapshot in zip(shortlist,stats["diagnostic_shortlist"]):
        assert snapshot["node_hash"]==content_hash(row["sol"])
        assert snapshot["parent_hash"] is not None
        assert snapshot["path"][-1]==row["label"]
        assert snapshot["depth"]==len(snapshot["path"])
    for layer in stats["trace"]:
        assert len(layer["beam_paths"])==len(layer["beam_labels"])
        assert len(layer["beam_hashes"])==len(layer["beam_labels"])
        assert all(x is not None for x in layer["beam_hashes"])
    assert content_hash(sol)==original


def test_source_queue_conflict_certificate_remains_necessary_only():
    from run_p1_resource_conflict_audit import certificate
    instance,sol=fifo_stress_with_three_locals()
    result=certificate(instance,sol)
    assert not result["passed"]
    assert result["deadline_count"]>=1
    assert result["deadline_by_mode"]["local"]>=1
