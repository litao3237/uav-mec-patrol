"""防止实验矩阵伪重复、资源失败回填及不等场景样本造成的统计偏差。"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from aggregate_multiscale_metrics import row_metrics, scenario_summary, summarize, verify_archive
from run_multiscale_metrics import METHODS, execution_schedule, expected_keys


def test_matrix_does_not_duplicate_deterministic_methods():
    keys = expected_keys("formal")
    assert len(keys) == 528
    assert len(expected_keys("pilot")) == 15
    for method in METHODS:
        group = [k for k in keys if k[-1] == method]
        assert len(group) == (48 if method in METHODS[:2] else 144)
        assert all((k[2] is None) == (method in METHODS[:2]) for k in group)


def test_schedule_keeps_shared_exploration_paired():
    schedule = execution_schedule(80, 45, [100, 101, 102])
    assert schedule == execution_schedule(80, 45, [100, 101, 102])
    assert len(schedule) == len(set(schedule)) == 8
    assert {s for m, s in schedule if m == "B/ESI"} == {100, 101, 102}


def test_scenario_weighting_does_not_treat_repeats_as_independent():
    values = [{"scenario_seed": 45, "value": 10.0}] * 3
    values += [{"scenario_seed": 46, "value": 30.0}]
    result = scenario_summary(values)
    assert result["scenario_equal_mean"] == 20.0
    assert result["run_equal_mean"] == 15.0
    assert result["independent_scenarios"] == 2
    assert scenario_summary([])["scenario_equal_mean"] is None
    assert scenario_summary(values[:1])["descriptive_scenario_bootstrap_95"] is None
    with pytest.raises(ValueError):
        scenario_summary([{"scenario_seed": 45, "value": float("nan")}])


def test_stage2_failure_is_not_replaced_with_stage1_metrics():
    row = {"stage1": {"qualified": True, "audit": {"saved": {"metrics": {"energy_j": 10.0}}}},
           "stage2": {"qualified": False}, "timing": {"search_s": 2.0}}
    result = row_metrics(row)
    assert result["stage1_energy_j"] == 10.0
    assert result["both_stages_qualified_rate"] == 0.0
    assert "mean_delay_s" not in result and "normalized_mec_cpu" not in result


def test_common_subset_excludes_missing_baseline_without_imputation():
    rows = []
    for k, s, a, m in expected_keys("pilot"):
        rows.append({"tasks": k, "scenario_seed": s, "algorithm_seed": a, "method": m,
                     "stage1": {"qualified": True}, "stage2": {"qualified": True},
                     "metrics": {"energy": 10.0 if m == "ESI-ALNS" else 12.0}})
    next(r for r in rows if r["tasks"] == 80 and r["method"] == "FTR-NM")["metrics"] = {}
    result = summarize(deepcopy(rows), "pilot")
    common = [r for r in result["all_method_common_summaries"] if r["tasks"] == 80 and r["metric"] == "energy"]
    assert all(r["valid_observations"] == 0 for r in common)
    pair = next(r for r in result["paired_esi_differences"]
                if r["tasks"] == 80 and r["baseline"] == "B-ALNS" and r["metric"] == "energy")
    assert pair["scenario_equal_mean"] == -2.0
    assert pair["independent_scenarios"] == 1


def test_incomplete_archive_cannot_pass_gate(tmp_path):
    with pytest.raises(ValueError, match="矩阵不完整"):
        verify_archive(tmp_path, "formal")
