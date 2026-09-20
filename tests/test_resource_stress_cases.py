from __future__ import annotations

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_resource_stress_cases
from uav_mec.optimization.resource import (
    solve_kkt_resource_problem,
    solve_resource_problem,
    verify_kkt,
)
from uav_mec.optimization.resource.problem import build_resource_model


def _case_map():
    return {name: (instance, solution) for name, instance, solution in build_resource_stress_cases()}


def test_stress_cases_build_valid_event_graphs() -> None:
    for name, instance, solution in build_resource_stress_cases():
        info = build_event_info(instance, solution)
        assert set(info.task_owner) == set(instance.tasks), name


def test_kkt_tight_bandwidth_and_cpu_cases_are_feasible() -> None:
    cases = _case_map()
    for name in ("tight_bandwidth", "tight_mec_cpu"):
        instance, solution = cases[name]
        result = solve_kkt_resource_problem(instance, solution, build_event_info(instance, solution))
        assert result.feasible, (name, result.diagnostics)


def test_tight_mec_cpu_activates_cpu_shadow_price() -> None:
    instance, solution = _case_map()["tight_mec_cpu"]
    result = solve_kkt_resource_problem(instance, solution, build_event_info(instance, solution))
    assert result.feasible
    assert result.stage1_duals["mec_cpu_cap::E1"] > 1e-4


def test_tight_average_delay_activates_beta() -> None:
    instance, solution = _case_map()["tight_avg_delay"]
    result = solve_kkt_resource_problem(instance, solution, build_event_info(instance, solution))
    assert result.feasible, result.diagnostics
    assert result.stage1_duals["avg_delay"] > 1e-4
    assert result.diagnostics["avg_delay_final_s"] <= instance.avg_delay_budget_s + 2.1e-3


def test_impossible_stress_case_is_rejected_without_crash() -> None:
    instance, solution = _case_map()["infeasible_deadline"]
    result = solve_kkt_resource_problem(instance, solution, build_event_info(instance, solution))
    assert not result.feasible
    assert result.status in {"infeasible_precheck", "kkt_no_feasible_iterate"}


def test_full_kkt_report_contains_all_four_condition_blocks() -> None:
    instance, solution = _case_map()["two_mec"]
    info = build_event_info(instance, solution)
    result = solve_kkt_resource_problem(instance, solution, info)
    assert result.feasible, result.diagnostics

    report = verify_kkt(instance, solution, info, result)
    assert report["status"] == "ok"
    assert "max_primal_violation" in report
    assert "max_dual_violation" in report
    assert "max_abs_complementarity" in report
    assert "max_abs_stationarity_residual" in report
    assert report["top_complementarity"]


def test_cvx_stress_models_register_only_cvx_constraints() -> None:
    """Regression for contactless/idle-UAV constant constraints.

    A UAV with no MEC contact has a constant patrol return time. That branch
    must still produce a CVXPY Constraint rather than Python bool so dual
    extraction is well-defined.
    """

    for name, instance, solution in build_resource_stress_cases():
        info = build_event_info(instance, solution)
        model = build_resource_model(instance, solution, info)
        bad = [
            (constraint_name, type(constraint).__name__)
            for constraint_name, constraint in model.named_constraints.items()
            if not hasattr(constraint, "dual_value")
        ]
        assert not bad, (name, bad)


def test_cvx_local_fifo_contactless_uav_case_solves_without_bool_constraint() -> None:
    instance, solution = _case_map()["local_fifo"]
    info = build_event_info(instance, solution)
    result = solve_resource_problem(instance, solution, info, verbose=False)
    assert result.feasible, result.diagnostics
    assert result.status in {"optimal", "optimal_inaccurate"}
