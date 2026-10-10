"""Statistical/coverage tests for paired sensitivity aggregation."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from summarize_model_sensitivity import aggregate, report_markdown
from run_model_sensitivity import METHODS


def _metrics(energy: float, offload: float):
    return {
        "energy_stage1_j": energy,
        "physical": {
            "offload_ratio": offload,
            "flight_collection_share_pct": 98.5,
            "upload_energy_share_pct": 1.4,
            "local_compute_energy_share_pct": 0.1,
            "total_route_distance_m": 2000.0,
            "contact_visits": 2,
            "mean_deadline_slack_s": 12.0,
            "max_mec_bandwidth_occupation": 0.90,
            "max_mec_cpu_occupation": 0.75,
        },
    }


def _profile_block(scenario, factor_multiplier=1.5):
    def row(profile, seed, method, *, energy, valid=True):
        observed = _metrics(energy, .2) if valid else {
            "physical": None, "energy_stage1_j": None,
        }
        return {
            "profile": profile, "seed": seed, "method": method,
            "stage1_qualified": valid, "both_qualified": valid,
            "failure_stage": None if valid else "stage1",
            "status": "ok",
            **observed,
        }

    rows = []
    for algo_seed in (111, 112):
        for method in METHODS:
            rows.append(row("baseline", algo_seed, method,
                            energy=1000 + algo_seed))
            rows.append(row("compute_x1p5", algo_seed, method,
                            energy=1100 + algo_seed,
                            valid=not (
                                scenario == 63 and algo_seed == 112
                            )))
    inst = {
        "total_workload_gcycles": 200.0 * factor_multiplier,
        "mean_deadline_s": 180.0,
        "n_individual_optimistic_deadline_impossible": 0,
    }
    return {
        "complete": True,
        "protocol": {
            "task_scale": 50, "independent_scenario_seed": scenario,
        },
        "profiles": {
            "baseline": {"instance_summary": inst},
            "compute_x1p5": {"instance_summary": inst},
        },
        "rows": rows,
        "error_count": 0,
    }


def test_aggregate_pairs_strictly_by_seed_and_scenario():
    result = aggregate(
        [_profile_block(x) for x in (61, 62, 63, 64)],
        expected_tasks=[50],
        expected_scenarios=[61, 62, 63, 64],
    )
    row = next(
        x for x in result["rows"]
        if x["tasks"] == 50 and x["profile"] == "compute_x1p5"
        and x["method"] == "B-ALNS"
    )
    assert result["received_blocks"] == 4
    assert row["attempted"] == 8
    assert row["both_qualified"] == 7
    assert row["paired_with_baseline_valid"] == 7
    assert row["paired_with_baseline_scenarios"] == 4
    assert row["paired_delta_energy_stage1_j"] == pytest.approx(100.0)
    assert row["paired_delta_energy_boot95_scenario"] == pytest.approx([100, 100])
    assert row["failures_by_stage"] == {"stage1": 1}
    report = report_markdown(result)
    assert "compute_x1p5" in report
    assert "7/8" in report


def test_missing_scenario_and_incomplete_workflow_are_reported():
    partial = _profile_block(61)
    partial["complete"] = False
    data = aggregate(
        [partial], expected_tasks=[50], expected_scenarios=[61, 62],
    )
    assert data["missing_blocks"] == [[50, 62]]
    assert data["incomplete_blocks"] == [[50, 61]]


def test_duplicate_workflow_jobs_are_rejected_not_double_counted():
    first = _profile_block(61)
    second = _profile_block(61)
    with pytest.raises(ValueError, match="Duplicate"):
        aggregate(
            [first, second], expected_tasks=[50],
            expected_scenarios=[61],
        )
