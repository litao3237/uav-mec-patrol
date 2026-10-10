"""用已知可行解及有意违约例检查独立核验，避免只测试求解器状态。"""
from copy import deepcopy
from dataclasses import replace
import math

import pytest

from uav_mec.algorithms import ProxyObjectiveEvaluator, UavMecALNSConfig, run_uav_mec_alns
from uav_mec.analysis.constraint_audit import audit_resources, audit_both_timelines
from uav_mec.analysis.experiment_snapshot import json_ready, restore_instance, restore_solution, content_hash
from uav_mec.domain import ContactVisit, Route, RouteStop, TaskDecision
from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import CVXResourceSolver
from uav_mec.optimization.resource.problem import build_resource_model
from uav_mec.optimization.resource.reduced import evaluate_reduced_resources


@pytest.fixture(scope="module")
def solved():
    instance, solution = build_small_instance()
    result = CVXResourceSolver(capture_stage2_raw_values=True).solve(instance, solution)
    assert result.stage1_values
    return instance, solution, result


def test_snapshot_roundtrip_and_missing_values(solved):
    instance, solution, _ = solved
    assert content_hash(restore_instance(json_ready(instance))) == content_hash(instance)
    assert content_hash(restore_solution(json_ready(solution))) == content_hash(solution)
    assert json_ready({"a": math.inf, "b": math.nan}) == {"a": None, "b": None}


def test_independent_residuals_match_all_model_constraints(solved):
    instance, solution, result = solved
    values = result.stage1_values
    audit = audit_resources(instance, solution, values)
    assert audit["complete"] and audit["passed"], audit.get("worst_constraint")
    model = build_resource_model(instance, solution, build_event_info(instance, solution))
    for group, mapping in model.variables.items():
        for key, var in mapping.items():
            var.save_value(values[group][str(key)])
    actual = {c["id"]: c["signed_residual"] for c in audit["constraints"]}
    assert set(model.named_constraints) <= set(actual)
    for name, constraint in model.named_constraints.items():
        assert actual[name] == pytest.approx(float(constraint.expr.value), abs=1e-7), name
    assert audit["metrics"]["energy_j"] == pytest.approx(result.energy_stage1_j, abs=1e-5)
    assert sum(audit["metrics"]["energy_components_j"].values()) == pytest.approx(result.energy_stage1_j, abs=1e-5)


@pytest.mark.parametrize("group,change,family", [
    ("bandwidth_mhz", lambda x: x + 100, "bandwidth_cap"),
    ("mec_cpu_ghz", lambda x: x + 100, "mec_cpu_cap"),
    ("local_cpu_ghz", lambda x: x + 100, "local_upper"),
    ("tau_s", lambda x: 0.0, "upload_epi"),
    ("local_start_s", lambda x: 0.0, "local_release"),
    ("task_completion_s", lambda x: x + 10000, "deadline"),
    ("batch_start_s", lambda x: 0.0, "batch_arrival"),
    ("batch_finish_s", lambda x: 0.0, "batch_complete"),
])
def test_intentional_primal_violations_are_detected(solved, group, change, family):
    instance, solution, result = solved
    values = deepcopy(result.stage1_values)
    key = next(iter(values[group]))
    values[group][key] = change(values[group][key])
    audit = audit_resources(instance, solution, values)
    assert not audit["passed"]
    assert any(c["id"].startswith(family) and c["normalized_violation"] > 1 for c in audit["constraints"])


def test_missing_nonfinite_and_energy_guard_fail(solved):
    instance, solution, result = solved
    values = deepcopy(result.stage1_values)
    values["local_cpu_ghz"].clear()
    assert not audit_resources(instance, solution, values)["complete"]
    values = deepcopy(result.stage1_values)
    values["tau_s"][next(iter(values["tau_s"]))] = None
    assert not audit_resources(instance, solution, values)["complete"]
    audit = audit_resources(instance, solution, result.stage1_values, energy_limit_j=result.energy_stage1_j - 100)
    assert not audit["passed"]
    assert audit["worst_constraint"] == "stage2_energy_guard"


def test_stage2_and_reconstructed_timeline_have_distinct_audits(solved):
    instance, solution, result = solved
    raw = result.diagnostics["stage2_raw_values"]
    assert raw is not None
    audit = audit_both_timelines(instance, solution, raw,
                                 energy_limit_j=result.energy_stage1_j + result.diagnostics["energy_tolerance_j"])
    assert all(a["complete"] for a in audit.values())
    bad = deepcopy(raw)
    key = next(iter(bad["batch_start_s"]))
    bad["batch_start_s"][key] = -10.0
    audit = audit_both_timelines(instance, solution, bad)
    assert not audit["saved"]["passed"]
    assert audit["reconstructed"]["passed"]






@pytest.mark.parametrize("family", ["avg_delay", "cycle", "battery"])
def test_system_budget_violations_are_detected(solved, family):
    instance, solution, result = solved
    changed = deepcopy(instance)
    if family == "avg_delay":
        changed.avg_delay_budget_s = 1.0
    elif family == "cycle":
        changed.cycle_s = 1.0
    else:
        changed.uavs = {u: replace(v, energy_budget_j=1.0) for u, v in changed.uavs.items()}
    audit = audit_resources(changed, solution, result.stage1_values)
    assert not audit["passed"]
    assert any(c["id"].startswith(family) and c["normalized_violation"] > 1 for c in audit["constraints"])


def test_local_and_same_mec_batch_predecessors_are_enforced():
    instance, solution = build_small_instance()
    instance.cycle_s = instance.avg_delay_budget_s = 1000.0
    instance.tasks = {t: replace(v, deadline_s=1000.0) for t, v in instance.tasks.items()}
    instance.uavs = {u: replace(v, energy_budget_j=1e8) for u, v in instance.uavs.items()}
    solution.contact_visits["V12"] = ContactVisit("V12", "U1", "E1_P1")
    solution.routes["U1"] = Route("U1", solution.routes["U1"].stops[:-1] +
                                  (RouteStop.contact("V12"), RouteStop.depot()))
    solution.task_decisions["S3"] = TaskDecision.offload("V12")
    solution.task_decisions["S5"] = TaskDecision.local()
    del solution.contact_visits["V21"]
    solution.routes["U2"] = Route("U2", tuple(s for s in solution.routes["U2"].stops if s.ref_id != "V21"))
    info = build_event_info(instance, solution)
    resources = {"bandwidth_mhz": {str(("U1", "E1")): 3.0},
                 "mec_cpu_ghz": {str(("U1", "E1")): 4.0},
                 "local_cpu_ghz": {"S4": 1.0, "S5": 1.0}}
    reduced = evaluate_reduced_resources(instance, solution, info,
                                          bandwidth_mhz={("U1", "E1"): 3.0},
                                          mec_cpu_ghz={("U1", "E1"): 4.0},
                                          local_cpu_ghz=resources["local_cpu_ghz"])
    values = dict(resources, tau_s=reduced.upload_time_s, local_start_s=reduced.local_start_s,
                  task_completion_s=reduced.task_completion_s, batch_start_s=reduced.batch_start_s,
                  batch_finish_s=reduced.batch_finish_s)
    assert audit_resources(instance, solution, values)["passed"]
    for group, key, expected in (("batch_finish_s", "V11", "batch_fifo::V12"),
                                  ("task_completion_s", "S4", "local_fifo::S5")):
        bad = deepcopy(values)
        bad[group][key] = 999.0
        audit = audit_resources(instance, solution, bad)
        assert any(c["id"] == expected and c["normalized_violation"] > 1 for c in audit["constraints"])
