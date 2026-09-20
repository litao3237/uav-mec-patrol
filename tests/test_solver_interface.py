from __future__ import annotations

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import KKTResourceSolver


def test_kkt_resource_solver_class_interface() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    result = KKTResourceSolver().solve(instance, solution, info)
    assert result.feasible
    assert result.solver == "KKT-DUAL"
