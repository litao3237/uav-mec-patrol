from __future__ import annotations

from uav_mec.analysis import build_paper_metrics
from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import CVXResourceSolver


def test_paper_metrics_are_consistent_on_small_instance() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    result = CVXResourceSolver(run_stage2=True).solve(
        instance,
        solution,
        info,
    )
    assert result.feasible

    metrics = build_paper_metrics(
        instance,
        solution,
        result,
        info=info,
        reference_distance_m=sum(info.route_distance_m.values()),
    )

    assert metrics["stage1_status"] in {"optimal", "optimal_inaccurate"}
    assert metrics["stage2_status"] in {
        "optimal",
        "optimal_inaccurate",
        "skipped",
    }
    assert metrics["energy_stage1_j"] > 0.0
    assert metrics["avg_delay_s"] <= instance.avg_delay_budget_s + 1e-2
    assert metrics["min_deadline_slack_s"] >= -1e-2
    assert 0.0 <= metrics["offload_ratio"] <= 1.0
    assert metrics["contacts"] == len(solution.contact_visits)
    assert metrics["active_uav_mec_pairs"] == len(
        info.active_uav_mec_pairs
    )
    assert abs(metrics["route_detour_pct_vs_reference"]) < 1e-12
    assert 0.0 <= metrics["fixed_energy_ratio"] <= 1.0
    assert 0.0 <= metrics["communication_energy_ratio"] <= 1.0
    assert 0.0 <= metrics["local_compute_energy_ratio"] <= 1.0

    total_ratio = (
        metrics["fixed_energy_ratio"]
        + metrics["communication_energy_ratio"]
        + metrics["local_compute_energy_ratio"]
    )
    assert abs(total_ratio - 1.0) < 1e-6

    for value in metrics["bandwidth_utilization_by_mec"].values():
        assert value >= 0.0
        assert value <= 1.0 + 1e-5
    for value in metrics["cpu_utilization_by_mec"].values():
        assert value >= 0.0
        assert value <= 1.0 + 1e-5
