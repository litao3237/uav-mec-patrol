"""验证等价速率模型、实际高负载故障恢复以及残差失败时的安全回退。"""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import restore_instance, restore_solution
from uav_mec.evaluation import build_event_info, gamma_mhz, visit_mec_id
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource.cvx_solver import solve_resource_problem, solve_stage2_realization
from uav_mec.optimization.resource.problem import build_resource_model


def assign_physical(expression, value):
    """测试中向内部无量纲变量赋值，再通过物理表达式检查约束方向。"""
    internal = expression.variables()[0]
    internal.value = 1.0
    scale = float(expression.value)
    internal.value = value / scale


def test_scaled_upload_constraint_preserves_exact_shannon_boundary():
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    model = build_resource_model(instance, solution, info, numerical_scaling=True)
    for visit, tasks in info.batch_tasks.items():
        u = solution.contact_visits[visit].uav_id
        e = visit_mec_id(instance, solution, visit)
        for fraction in (.001, .1, .5, 1.0):
            bandwidth = fraction * instance.mecs[e].bandwidth_mhz
            rate = bandwidth * math.log1p(gamma_mhz(instance, solution, visit) / bandwidth) / math.log(2)
            tau = sum(instance.tasks[t].data_mbit for t in tasks) / rate
            assign_physical(model.variables["bandwidth_mhz"][u, e], bandwidth)
            for factor in (.9, 1.0, 1.1):
                assign_physical(model.variables["tau_s"][visit], factor * tau)
                residual = float(model.named_constraints[f"upload_epi::{visit}"].expr.value)
                if factor == 1.0:
                    assert abs(residual) < 1e-12
                else:
                    assert np.sign(residual) == np.sign(1 - factor)


def test_archived_high_load_failure_recovers_without_relaxing_energy_guard():
    data = json.loads((Path(__file__).parent / "fixtures/stage2_high_load_regression.json").read_text(encoding="utf-8"))
    instance, solution = restore_instance(data["instance"]), restore_solution(data["solution"])
    assert data["old_stage2_qualified"] is False
    result = solve_stage2_realization(instance, solution, build_event_info(instance, solution),
                                     energy_star_j=data["energy_star_j"],
                                     energy_tolerance_j=data["energy_tolerance_j"])
    assert result["accepted"] and result["status"] == "optimal", result["attempts"]
    limit = data["energy_star_j"] + data["energy_tolerance_j"]
    audit = audit_both_timelines(instance, solution, result["raw_values"], energy_limit_j=limit)
    assert all(v["passed"] for v in audit.values())
    assert result["energy_j"] <= limit + 1e-3
    first = audit_both_timelines(instance, solution, data["stage1_values"])
    assert audit["saved"]["metrics"]["normalized_mec_cpu"] <= first["saved"]["metrics"]["normalized_mec_cpu"] + 1e-6


def test_optimal_status_with_invalid_residual_never_replaces_stage1(monkeypatch):
    instance, solution = build_small_instance()
    monkeypatch.setattr("uav_mec.optimization.resource.cvx_solver._solver_candidates", lambda _: ["CLARABEL"])
    monkeypatch.setattr("uav_mec.analysis.constraint_audit.audit_both_timelines",
                        lambda *a, **kw: {"saved": {"passed": False}, "reconstructed": {"passed": False}})
    result = solve_resource_problem(instance, solution, capture_stage2_raw_values=True)
    assert result.diagnostics["stage2_accepted"] is False
    assert result.diagnostics["stage2_status"] != "optimal"
    assert result.final_values == result.stage1_values
    assert result.energy_final_j == result.energy_stage1_j
    expected_delay = sum(result.final_values["task_completion_s"][t] - instance.tasks[t].release_s
                         for t in instance.tasks) / len(instance.tasks)
    assert result.diagnostics["avg_delay_final_s"] == pytest.approx(expected_delay)


def test_stage1_oracle_does_not_invoke_stage2_recovery(monkeypatch):
    instance, solution = build_small_instance()
    def unexpected(*a, **kw):
        raise AssertionError("搜索的Stage-1评价不应触发Stage-2")
    monkeypatch.setattr("uav_mec.optimization.resource.cvx_solver.solve_stage2_realization", unexpected)
    result = solve_resource_problem(instance, solution, run_stage2=False)
    assert result.feasible and result.diagnostics["stage2_status"] == "skipped"
