"""Numerical and causal-scope guards for the independent elastic P1-R diagnosis."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.stage1_acceptance import qualify_stage1_result, stage1_is_qualified
from uav_mec.optimization.resource.cvx_solver import solve_resource_problem
from uav_mec.optimization.resource.elastic_diagnosis import (
    PROTOCOLS, CAPACITY_GROUPS, QOS_GROUPS, constraint_family,
    relaxation_scale, diagnose_elastic_resources,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from summarize_elastic_diagnosis import aggregate


def test_explicit_groups_and_recovered_original_constraint_units():
    instance,sol=build_small_instance()
    assert PROTOCOLS == ("qos_only", "qos_plus_mec_capacity", "mec_capacity_only")
    assert QOS_GROUPS == {"deadline","avg_delay","cycle","battery"}
    assert CAPACITY_GROUPS == {"bandwidth_cap","mec_cpu_cap"}
    assert constraint_family("deadline::S1")=="deadline"
    assert constraint_family("avg_delay")=="avg_delay"
    assert constraint_family("cycle::U1")=="cycle"
    assert constraint_family("battery::U1")=="battery"
    assert constraint_family("bandwidth_cap::E1")=="bandwidth_cap"
    assert constraint_family("mec_cpu_cap::E1")=="mec_cpu_cap"
    assert constraint_family("local_fifo::S1") is None
    assert constraint_family("mec_task_complete::V11::1::S1") is None
    assert relaxation_scale(instance,"deadline::S1")==(instance.cycle_s,"s")
    assert relaxation_scale(instance,"avg_delay")==(instance.cycle_s,"s")
    assert relaxation_scale(instance,"battery::U1")==(
        instance.uavs["U1"].energy_budget_j,"J",
    )
    assert relaxation_scale(instance,"bandwidth_cap::E1")==(
        instance.mecs["E1"].bandwidth_mhz,"MHz",
    )
    assert relaxation_scale(instance,"mec_cpu_cap::E1")==(
        instance.mecs["E1"].cpu_ghz,"GHz",
    )


def test_strictly_valid_original_structure_has_nearly_zero_elastic_conflict():
    instance,sol=build_small_instance()
    baseline=solve_resource_problem(instance,sol,run_stage2=False)
    baseline=qualify_stage1_result(instance,sol,baseline)
    assert stage1_is_qualified(baseline),baseline.diagnostics
    source_hash=content_hash(sol)
    for mode in PROTOCOLS:
        diagnosis=diagnose_elastic_resources(instance,sol,mode=mode)
        assert diagnosis["numerically_credible"],diagnosis
        assert diagnosis["normalized_total_elastic_slack"] < 0.002, diagnosis
        assert diagnosis["max_hard_normalized_residual"]<.0002
        assert diagnosis["max_elastic_normalized_residual"]<.0002
    assert content_hash(sol)==source_hash


def test_incompatible_task_deadline_detected_without_relaxing_fifo_or_cpu_hardware():
    instance,sol=build_small_instance()
    changed=deepcopy(instance)
    changed.tasks={
        t:replace(task,deadline_s=1.0 if t=="S1" else task.deadline_s)
        for t,task in instance.tasks.items()
    }
    source_hash=content_hash(sol)
    diag=diagnose_elastic_resources(changed,sol,mode="qos_only")
    assert diag["numerically_credible"],diag
    assert diag["normalized_total_elastic_slack"]>0.005,diag
    assert diag["slack_sum_by_family"]["deadline"]>0
    assert any(
        c["constraint"]=="deadline::S1" and c["physical_slack"]>0
        for c in diag["top_constraints"]
    )
    assert diag["top_dependency_context"]
    assert diag["top_dependency_context"][0]["task_id"]=="S1"
    assert content_hash(sol)==source_hash


def test_no_mec_hardware_cap_softening_unless_explicitly_requested():
    instance,sol=build_small_instance()
    q=diagnose_elastic_resources(instance,sol,mode="qos_only")
    full=diagnose_elastic_resources(
        instance,sol,mode="qos_plus_mec_capacity",
    )
    assert q["numerically_credible"] and full["numerically_credible"]
    assert "mec_cpu_cap" not in q["slack_sum_by_family"]
    assert "bandwidth_cap" not in q["slack_sum_by_family"]
    assert "mec_cpu_cap" in full["slack_sum_by_family"]
    assert "bandwidth_cap" in full["slack_sum_by_family"]
    assert full["normalized_total_elastic_slack"]<=(
        q["normalized_total_elastic_slack"]+.003
    )


def test_missing_blocks_remain_visible_in_reporting():
    scenario={
        "protocol":{"tasks":80,"independent_scenario_seed":61},
        "complete":False,
        "rows":[],
        "unhandled_program_errors":[],
    }
    data=aggregate(
        [scenario],expected=((80,61),(80,62)),
    )
    assert data["missing_blocks"]==[[80,62]]
    assert data["incomplete_blocks"]==[[80,61]]


@pytest.mark.parametrize("invalid",[
    "qos_and_invalid_hardware","all_slack","",
])
def test_invalid_counterfactual_mode_rejected(invalid):
    instance,sol=build_small_instance()
    with pytest.raises(ValueError):
        diagnose_elastic_resources(instance,sol,mode=invalid)
