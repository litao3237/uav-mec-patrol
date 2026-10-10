"""P0 time-allocation sweep protocol tests."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_p0_allocation_sweep import METHOD_FRACTIONS, METHODS, fractions
from run_p0_matched_budget import BUDGET_S
from run_p0_contact_diagnostics import profile_config
from uav_mec.algorithms.alns.problem_operators import ProblemOperatorConfig


def test_all_sweep_arms_have_same_total_nominal_budget():
    assert len(METHODS) == 6
    for _, (explore, elite) in METHOD_FRACTIONS.items():
        for budget in BUDGET_S.values():
            init = 0.7
            data = fractions(budget, init, explore, elite)
            assert data["exploration_s"] + data["elite_plus_anchor_s"] + init + data["finalization_reserve_s"] == pytest.approx(budget)


def test_sweep_contains_original_esi_and_alns_controls():
    assert METHOD_FRACTIONS["B-ALNS"] == (.8, 0.)
    assert METHOD_FRACTIONS["original_60_20"] == (.6, .2)
    assert METHOD_FRACTIONS["twoopt_60_20"] == (.6, .2)
    for fraction in (65, 70, 75):
        method = f"twoopt_{fraction}_{80-fraction:02d}"
        assert METHOD_FRACTIONS[method] == (fraction/100, (80-fraction)/100)


def test_bad_budgets_rejected():
    with pytest.raises(ValueError):
        fractions(15, 1, .7, .2)
    with pytest.raises(ValueError):
        fractions(15, -1, .6, .2)
    with pytest.raises(ValueError):
        fractions(-15, 1, .6, .2)


def test_small_elite_slice_does_not_become_negative():
    frac = fractions(15, .7, .75, .05)
    assert frac["elite_plus_anchor_s"] == pytest.approx(.75)


def test_twoopt_operator_does_not_remove_contact_deletion_or_increase_elite_slots():
    base = ProblemOperatorConfig()
    changed = profile_config(base, "retain_remove_two_opt_star", geometric_pool=8)
    assert changed.elite_enable_contact_remove
    assert changed.elite_shortlist_limit == base.elite_shortlist_limit
    assert changed.elite_family_quota == base.elite_family_quota
    assert changed.elite_min_improvement_j == base.elite_min_improvement_j
