from __future__ import annotations

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import solve_kkt_resource_problem, verify_kkt


def test_kkt_solver_baseline_is_feasible_and_stationary() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    result = solve_kkt_resource_problem(instance, solution, info)

    assert result.feasible, result.diagnostics
    assert result.status == "optimal_approx"
    assert abs(result.energy_stage1_j - 35440.746287) < 5e-3
    assert result.diagnostics["avg_delay_final_s"] <= instance.avg_delay_budget_s + 2e-3

    report = verify_kkt(instance, solution, info, result)
    assert report["status"] == "ok"
    assert report["max_abs_stationarity_residual"] < 1e-8


def test_kkt_solver_uses_full_active_bandwidth() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    result = solve_kkt_resource_problem(instance, solution, info)
    assert result.feasible

    values = result.stage1_values["bandwidth_mhz"]
    used = sum(value for key, value in values.items() if "'E1'" in key)
    assert abs(used - instance.mecs["E1"].bandwidth_mhz) < 1e-8
