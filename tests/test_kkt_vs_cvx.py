from __future__ import annotations

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import solve_kkt_resource_problem, solve_resource_problem


def test_kkt_stage1_matches_cvx_reference_on_baseline() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    cvx = solve_resource_problem(instance, solution, info, verbose=False)
    kkt = solve_kkt_resource_problem(instance, solution, info)

    assert cvx.feasible, cvx.diagnostics
    assert kkt.feasible, kkt.diagnostics
    relative_gap = abs(kkt.energy_stage1_j - cvx.energy_stage1_j) / cvx.energy_stage1_j
    assert relative_gap < 1e-6
