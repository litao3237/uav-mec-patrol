from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import solve_resource_problem, verify_kkt
from uav_mec.optimization.resource.cvx_solver import _sanitize_positive_group


def _solve(instance, solution):
    info = build_event_info(instance, solution)
    return info, solve_resource_problem(instance, solution, info, verbose=False)


def test_baseline_and_kkt() -> None:
    instance, solution = build_small_instance()
    info, result = _solve(instance, solution)
    assert result.feasible, result.diagnostics
    assert result.is_dcp
    report = verify_kkt(instance, solution, info, result)
    assert report["status"] == "ok"
    assert report["max_abs_stationarity_residual"] < 5e-2


def test_more_bandwidth_does_not_increase_optimal_energy() -> None:
    instance, solution = build_small_instance()
    _, base = _solve(instance, solution)
    assert base.feasible

    more_bw = deepcopy(instance)
    more_bw.mecs = dict(instance.mecs)
    more_bw.mecs["E1"] = replace(instance.mecs["E1"], bandwidth_mhz=8.0)
    _, result = _solve(more_bw, solution)
    assert result.feasible
    assert result.energy_stage1_j <= base.energy_stage1_j + 1e-3


def test_tighter_delay_does_not_reduce_optimal_energy() -> None:
    instance, solution = build_small_instance()
    _, base = _solve(instance, solution)
    assert base.feasible

    tighter = deepcopy(instance)
    tighter.avg_delay_budget_s = 52.0
    _, result = _solve(tighter, solution)
    assert result.feasible
    assert result.energy_stage1_j + 1e-3 >= base.energy_stage1_j


def test_impossible_deadline_is_infeasible() -> None:
    instance, solution = build_small_instance()
    impossible = deepcopy(instance)
    impossible.tasks = dict(instance.tasks)
    impossible.tasks["S1"] = replace(instance.tasks["S1"], deadline_s=20.0)
    _, result = _solve(impossible, solution)
    assert not result.feasible



class _FakeVar:
    def __init__(self, value):
        self.value = value


def test_positive_resource_sanitizer_clips_tiny_violation() -> None:
    values, violations = _sanitize_positive_group(
        {
            "near": _FakeVar(0.0009995),
            "ok": _FakeVar(0.25),
        },
        minimum=1e-3,
    )

    assert not violations
    assert values["near"] == 1e-3
    assert values["ok"] == 0.25


def test_positive_resource_sanitizer_rejects_zero_and_nonfinite() -> None:
    values, violations = _sanitize_positive_group(
        {
            "zero": _FakeVar(0.0),
            "nan": _FakeVar(float("nan")),
        },
        minimum=1e-3,
    )

    assert not values
    assert len(violations) == 2
