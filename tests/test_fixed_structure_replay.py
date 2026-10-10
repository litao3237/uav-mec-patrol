"""Tests for constant-discrete-structure UAV-MEC physical replay."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_fixed_structure_replay import classify_precheck, summarize
from summarize_fixed_structure_replay import aggregate, format_md
from run_model_sensitivity import make_profile, PROFILES
from uav_mec.analysis.experiment_snapshot import (
    content_hash,json_ready,restore_instance,restore_solution,
)
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def test_roundtrip_persisted_immutable_structure_and_param_variation():
    instance, solution = build_small_instance()
    source = content_hash(solution)
    restored = restore_solution(json_ready(solution))
    assert content_hash(restored) == source
    reconstructed_instance = restore_instance(json_ready(instance))
    assert content_hash(reconstructed_instance) == content_hash(instance)
    for profile in PROFILES:
        modified = make_profile(reconstructed_instance, profile)
        validate_solution(modified, restored)
        assert content_hash(restored) == source


def test_precheck_reason_task_local_or_offloaded_is_encoded():
    instance, solution = build_small_instance()
    descriptor = classify_precheck(instance, solution)
    assert isinstance(descriptor["reasons"], list)
    assert isinstance(descriptor["reason_families"], dict)
    for item in descriptor["offending_tasks"]:
        assert item["mode"] in {"local","offload"}
        assert item["optimistic_deadline_gap_s"] > 0
    assert descriptor["max_task_deadline_LB_excess_s"] >= 0


def test_precheck_detects_worsening_fixed_deadline_without_changing_routes():
    instance, solution = build_small_instance()
    stressed = deepcopy(instance)
    stressed.tasks = {
        t:replace(task,deadline_s=1.0)
        for t,task in instance.tasks.items()
    }
    d = classify_precheck(stressed,solution)
    assert not d["passed_necessary_precheck"]
    assert any(key.startswith("task_") for key in d["reason_families"])
    assert content_hash(solution)==content_hash(solution)


def synthetic_row(profile, *, seed=111, energy=100.0, valid=True,
                  dynamic_valid=True):
    return {
        "method":"B-ALNS", "profile":profile,"seed":seed,
        "precheck":{
            "passed_necessary_precheck":valid,
            "reason_families":{} if valid else {"task_local":1},
        },
        "stage1_status":"optimal" if valid else "infeasible_precheck",
        "stage1_qualified":valid,"both_qualified":valid,
        "energy_stage1_j":energy if valid else None,
        "physical":{
            "offload_ratio":.2, "flight_collection_share_pct":98.,
            "upload_energy_share_pct":1.,
        } if valid else None,
        "total_s":1.5,
        "earlier_dynamic":{
            "both_qualified":dynamic_valid,
            "energy_stage1_j":energy if dynamic_valid else None,
            "stage1_status":"optimal" if dynamic_valid else "infeasible_precheck",
        },
    }


def test_replay_summary_requires_both_stage_qualified_for_energy():
    data=[
        synthetic_row("baseline",energy=100),
        synthetic_row("compute_x1p5",energy=115),
        synthetic_row("compute_x2p0",valid=False,dynamic_valid=False),
    ]
    summary=summarize(data)
    a=next(x for x in summary if x["profile"]=="compute_x1p5" and x["method"]=="B-ALNS")
    assert a["paired_qualified"]==1
    assert a["mean_delta_fixed_energy_vs_baseline_j_paired"]==15
    b=next(x for x in summary if x["profile"]=="compute_x2p0" and x["method"]=="B-ALNS")
    assert b["paired_qualified"]==0
    assert b["mean_fixed_stage1_energy_j_qualified"] is None
    assert b["precheck_rejected"]==1


def test_aggregate_detects_missing_results_and_stricter_constraint_monotonicity():
    sample={
        "protocol":{"source_block":{"tasks":50,"scenario_seed":61}},
        "complete":True,
        "rows":[
            synthetic_row("baseline",energy=100.0),
            synthetic_row("compute_x1p5",energy=110.0),
            synthetic_row("bandwidth_x1p5",energy=95.0),
        ],
    }
    data=aggregate(
        [sample],expected_tasks=(50,),expected_scenarios=(61,62),
    )
    assert data["missing_blocks"]==[[50,62]]
    row=next(x for x in data["summary"]
             if x["profile"]=="compute_x1p5" and x["method"]=="B-ALNS")
    assert not row["monotonicity_violations"]
    assert row["mean_fixed_energy_change_vs_fixed_baseline_j"]==10
    assert "fixed" in format_md(data).lower()


def test_aggregate_records_large_nonmonotonic_numerical_anomaly_not_silently_ignored():
    base={
        "protocol":{"source_block":{"tasks":50,"scenario_seed":61}},
        "complete":True,
        "rows":[
            synthetic_row("baseline",energy=100.0),
            synthetic_row("compute_x1p5",energy=90.0),
        ],
    }
    data=aggregate([base],expected_tasks=(50,),expected_scenarios=(61,))
    row=next(x for x in data["summary"]
             if x["profile"]=="compute_x1p5" and x["method"]=="B-ALNS")
    assert len(row["monotonicity_violations"])==1
