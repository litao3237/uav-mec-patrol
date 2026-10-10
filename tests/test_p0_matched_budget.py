"""Budget protocol sanity checks for time-fair P0 experiments."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_p0_matched_budget import METHODS, BUDGET_S, slices, wall_clock_alns_config
from run_p0_contact_diagnostics import profile_config
from uav_mec.algorithms.alns.problem_operators import ProblemOperatorConfig


def test_budget_splits_charge_initialization_and_reserve_finalization():
    for K, total in BUDGET_S.items():
        alloc = slices(total, 0.7)
        assert alloc["base_search_s"] + 0.7 + alloc["reserved_finalization_s"] == pytest.approx(total)
        assert (alloc["esi_exploration_s"] + alloc["esi_total_s"]
                + alloc["reserved_finalization_s"] + 0.7) == pytest.approx(total)
        assert alloc["base_search_s"] > alloc["esi_exploration_s"]


def test_long_initialization_cannot_create_negative_search_budget():
    a = slices(15.0, 20.0)
    assert a["base_search_s"] == 0
    assert a["esi_exploration_s"] == 0
    with pytest.raises(ValueError):
        slices(-1, 0)


def test_time_scaled_acceptance_enabled_only_when_budget_positive():
    a = wall_clock_alns_config(105, 0.0)
    assert a.max_runtime_s == 0.0
    assert not a.time_scaled_rrt
    b = wall_clock_alns_config(105, 3.5)
    assert b.max_runtime_s == 3.5
    assert b.time_scaled_rrt


def test_esi_variants_share_same_search_capacity_and_preserve_contact_deletion():
    base = ProblemOperatorConfig()
    assert set(METHODS) == {
        "B-ALNS", "original_esi", "retain_remove_swap",
        "retain_remove_two_opt_star", "retain_remove_combined",
    }
    for method in METHODS[1:]:
        cfg = profile_config(base, method, geometric_pool=10)
        assert cfg.elite_shortlist_limit == base.elite_shortlist_limit
        assert cfg.elite_family_quota == base.elite_family_quota
        assert cfg.elite_enable_contact_remove
    assert profile_config(base, "original_esi", 10) == base
