"""Invariant tests for one-factor UAV-MEC parameter sensitivity."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_model_sensitivity import (
    METHODS,
    PROFILES,
    describe_instance,
    make_profile,
    physical_metrics,
    shared_task_geometry_hash,
    summarize,
)
from run_seven_methods import finalize
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config
from uav_mec.instances.small import build_small_instance


def small_paper_scale():
    config = load_paper_scale_config()
    return config, build_paper_scale_instance(
        config,
        num_tasks=12,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=61,
    )


def test_all_profiles_preserve_shared_geometry_contact_locations_and_task_data():
    config, base = small_paper_scale()
    original_hash = content_hash(base)
    common_hash = shared_task_geometry_hash(base)
    for name in PROFILES:
        changed = make_profile(base, name)
        assert changed is not base
        assert shared_task_geometry_hash(changed) == common_hash
        assert set(changed.tasks) == set(base.tasks)
        assert set(changed.mecs) == set(base.mecs)
        assert changed.contact_points == base.contact_points
        assert changed.uavs == base.uavs
        assert changed.cycle_s == base.cycle_s
        assert changed.avg_delay_budget_s == base.avg_delay_budget_s
        assert all(changed.tasks[t].release_s == 0 for t in base.tasks)
    assert content_hash(base) == original_hash
    assert content_hash(make_profile(base, "baseline")) == original_hash


@pytest.mark.parametrize("level", ["compute_x1p5", "compute_x2p0"])
def test_compute_multiplier_changes_only_compute_density(level):
    _, base = small_paper_scale()
    other = make_profile(base, level)
    factor = PROFILES[level][1]
    assert other.mecs == base.mecs
    for task_id, before in base.tasks.items():
        after = other.tasks[task_id]
        assert after.cycles_per_bit == pytest.approx(before.cycles_per_bit * factor)
        assert after.workload_gcycles == pytest.approx(before.workload_gcycles * factor)
        assert after.deadline_s == before.deadline_s
        assert after.data_mb == before.data_mb


@pytest.mark.parametrize("level", ["deadline_x0p9", "deadline_x0p8"])
def test_realized_deadline_scale_is_exact_and_not_regenerated(level):
    _, base = small_paper_scale()
    other = make_profile(base, level)
    factor = PROFILES[level][1]
    assert other.mecs == base.mecs
    for task_id, before in base.tasks.items():
        after = other.tasks[task_id]
        assert after.deadline_s == pytest.approx(before.deadline_s * factor)
        assert after.cycles_per_bit == before.cycles_per_bit


@pytest.mark.parametrize("level", ["bandwidth_x0p5", "bandwidth_x1p5"])
def test_bandwidth_scale_preserves_mec_coverage_cpu_and_uav(level):
    _, base = small_paper_scale()
    other = make_profile(base, level)
    factor = PROFILES[level][1]
    assert other.tasks == base.tasks
    assert other.contact_points == base.contact_points
    for mec_id, before in base.mecs.items():
        after = other.mecs[mec_id]
        assert after.bandwidth_mhz == pytest.approx(before.bandwidth_mhz * factor)
        assert after.cpu_ghz == before.cpu_ghz
        assert after.radius_m == before.radius_m


def test_individual_optimistic_feasibility_is_explicit():
    cfg, base = small_paper_scale()
    cpus = max(x.cpu_ghz for x in cfg.mec_sites)
    baseline = describe_instance(base, configured_fastest_cpu=cpus)
    doubled = describe_instance(
        make_profile(base, "compute_x2p0"),
        configured_fastest_cpu=cpus,
    )
    tight = describe_instance(
        make_profile(base, "deadline_x0p8"),
        configured_fastest_cpu=cpus,
    )
    assert doubled["total_workload_gcycles"] == pytest.approx(
        baseline["total_workload_gcycles"] * 2
    )
    assert tight["mean_deadline_s"] == pytest.approx(
        baseline["mean_deadline_s"] * .8
    )
    assert (
        doubled["n_individual_optimistic_deadline_impossible"]
        >= baseline["n_individual_optimistic_deadline_impossible"]
    )
    assert (
        tight["n_individual_optimistic_deadline_impossible"]
        >= baseline["n_individual_optimistic_deadline_impossible"]
    )


def test_summarize_never_imputes_failed_energy_or_masks_missing_pairs():
    physical = {
        "energy_components_j": {
            "flight_j": 800.0, "collection_j": 50.0,
            "upload_hover_j": 30.0, "transmit_j": 0.1,
            "local_compute_j": 4.0,
        },
        "offload_ratio": .2, "contact_visits": 2,
        "flight_collection_share_pct": 95.0,
        "upload_energy_share_pct": 3.0,
        "local_compute_energy_share_pct": 2.0,
        "max_mec_bandwidth_occupation": .8,
        "max_mec_cpu_occupation": .6,
        "mean_deadline_slack_s": 35.0,
        "total_route_distance_m": 100.0,
    }
    rows = [
        {
            "profile": "baseline", "seed": 111, "method": "B-ALNS",
            "status": "ok", "stage1_qualified": True,
            "both_qualified": True,
            "energy_stage1_j": 1000.0, "physical": physical,
            "timing": {"total_with_audit_s": 5.0},
        },
        {
            "profile": "compute_x1p5", "seed": 111, "method": "B-ALNS",
            "status": "ok", "stage1_qualified": True,
            "both_qualified": True,
            "energy_stage1_j": 1100.0, "physical": physical,
            "timing": {"total_with_audit_s": 6.0},
        },
        {
            "profile": "compute_x1p5", "seed": 112, "method": "B-ALNS",
            "status": "ok", "stage1_qualified": False,
            "both_qualified": False,
            "physical": None,
            "failure_stage": "stage1",
            "timing": {"total_with_audit_s": 6.0},
        },
    ]
    summary = summarize(rows)
    row = next(
        x for x in summary
        if x["profile"] == "compute_x1p5" and x["method"] == "B-ALNS"
    )
    assert row["attempts"] == 2
    assert row["both_qualified"] == 1
    assert row["paired_with_baseline_both_qualified"] == 1
    assert row["mean_delta_energy_vs_baseline_j_paired"] == pytest.approx(100.0)
    assert row["failure_stages"] == {"stage1": 1}


def test_stage2_metric_extraction_only_after_two_qualified_stages():
    instance, solution = build_small_instance()
    audited = finalize(
        instance, deepcopy(solution),
        method="unit", seed=111,
        initialization_s=0, search_s=0,
        diagnostics={},
    )
    if audited["stage1"]["qualified"] and audited["stage2"]["qualified"]:
        observed = physical_metrics(instance, solution, audited)
        assert observed is not None
        assert observed["stage2_physical_energy_j"] > 0
        assert observed["offload_ratio"] >= 0
        assert observed["flight_collection_share_pct"] > 0
        assert observed["max_mec_bandwidth_occupation"] <= 1.001
        assert observed["max_mec_cpu_occupation"] <= 1.001
    else:
        assert physical_metrics(instance, solution, audited) is None


def test_protocol_uses_only_original_methods():
    assert METHODS == ("B-ALNS", "ESI-ALNS")
    assert len(PROFILES) == 7
