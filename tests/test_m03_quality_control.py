"""M0.3 quality-control regression: real Joules, counts, unit credit, legacy gate."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from uav_mec.algorithms.alns import (
    UavMecALNSConfig, ScreenedProxyObjectiveEvaluator, run_uav_mec_alns,
)
from uav_mec.algorithms.alns.quality_control import (
    TaskQoSRecordToRecord, UnitCreditBandit,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.instances import build_small_instance


class _StubOracle:
    """Deliberately contradictory scalar; control decisions must ignore it."""
    def quality_key(self, instance, solution):
        return solution.metadata["quality"]


class _StubState:
    def __init__(self, quality, scalar):
        self.instance = SimpleNamespace()
        self.solution = SimpleNamespace(metadata={"quality": quality})
        self.evaluator = _StubOracle()
        self.score = scalar

    def objective(self):
        return self.score


def test_unit_acceptance_scales_in_joules_not_bounded_score():
    best = _StubState((0., -50., 0., 100_000., 9500.), 4.5e9)
    good_excursion = _StubState((0., -50., 0., 105_000., 9700.), -1e12)
    bad_excursion = _StubState((0., -50., 0., 112_000., 9100.), -1e13)
    lower_success = _StubState((0., -49., 0., 1., 1.), -1e14)
    nonphysical = _StubState((1., -50., 0., 1., 1.), -1e15)
    more_success = _StubState((0., -51., 10., 1e9, 1e9), 1e15)
    gate = TaskQoSRecordToRecord(iterations=100, start_energy_rel=.08)
    assert gate(None, best, best, good_excursion)
    assert not gate(None, best, best, bad_excursion)
    assert not gate(None, best, best, lower_success)
    assert not gate(None, best, best, nonphysical)
    assert gate(None, best, best, more_success)
    assert gate.decisions[0]["energy_allowance_rel"] == pytest.approx(.08)
    assert gate.decisions[-1]["reason"] == "more_on_time_tasks"


def test_unit_acceptance_has_lateness_guard_and_cools():
    best = _StubState((0., -50., .005, 100_000., 9_000.), 100.0)
    slightly_late = _StubState((0., -50., .012, 98_000., 9_000.), 1e10)
    extreme_late = _StubState((0., -50., .5, 1., 1.), -1e10)
    gate = TaskQoSRecordToRecord(
        iterations=2, start_energy_rel=.10, start_lateness=.01,
    )
    assert gate(None, best, best, slightly_late)
    assert not gate(None, best, best, extreme_late)
    assert not gate(None, best, best, slightly_late)
    assert gate.decisions[-1]["lateness_allowance"] == pytest.approx(0.)


def test_quality_cache_does_not_trigger_extra_solve():
    instance, solution = build_small_instance()
    instance = replace(instance, qos_hard=False)
    evaluator = ScreenedProxyObjectiveEvaluator()
    scalar = evaluator(instance, solution)
    calls_before = evaluator.stats.calls
    key = evaluator.quality_key(instance, solution)
    assert evaluator.stats.calls == calls_before
    assert isinstance(scalar, float) and len(key) == 5
    assert key[0] in (0.0, 1.0)
    with pytest.raises(ValueError):
        evaluator.quality_key(replace(instance, qos_hard=True), solution)


def test_unit_credit_selects_all_pairs_and_rewards_improvements():
    instance, solution = build_small_instance()
    instance = replace(instance, qos_hard=False)
    state = UavMecState(instance, solution, ScreenedProxyObjectiveEvaluator())
    selector = UnitCreditBandit(
        num_destroy=2, num_repair=2,
        op_coupling=[[True, True], [False, True]],
        destroy_names=["d1", "d2"], repair_names=["r1", "r2"],
    )
    assert selector.num_destroy == 2 and selector.num_repair == 2
    assert len(selector.pairs) == 3
    rng = np.random.default_rng(10)
    picked = []
    for _ in range(3):
        d,r = selector(rng, state, state)
        picked.append((d,r))
        selector.update(state,d,r,2)
    assert set(picked) == set(selector.pairs)
    assert len(selector.credit_history) == 3
    assert all(0 <= e["credit"] <= 1 for e in selector.credit_history)
    assert sum(sum(v) for v in selector.pair_counts.values()) == 3


@pytest.mark.parametrize("acceptance,selector", [
    ("qos_physical_rrt", "roulette"),
    ("scalar_rrt", "unit_credit_ucb"),
    ("qos_physical_rrt", "unit_credit_ucb"),
])
def test_combined_alns_smoke(acceptance,selector):
    instance, solution = build_small_instance()
    instance = replace(instance, qos_hard=False)
    result = run_uav_mec_alns(
        instance, initial_solution=solution,
        config=UavMecALNSConfig(
            iterations=7,seed=100,acceptance_mode=acceptance,
            selection_mode=selector,diagnostic_trace=True,
        ),
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    assert len(result.search_trace) == 7
    assert sum(sum(v) for v in result.operator_pair_counts.values()) == 7
    if selector == "unit_credit_ucb":
        assert len(result.credit_history) == 7
    else:
        assert not result.credit_history
    if acceptance == "qos_physical_rrt":
        assert len(result.acceptance_trace) <= 7
    else:
        assert not result.acceptance_trace


def test_strict_legacy_defaults_and_quality_controls_guarded():
    inst,sol = build_small_instance()
    baseline = UavMecALNSConfig(iterations=5)
    assert baseline.acceptance_mode == "scalar_rrt"
    assert baseline.selection_mode == "roulette"
    assert run_uav_mec_alns(inst,initial_solution=sol,config=baseline).best_solution
    with pytest.raises(ValueError):
        run_uav_mec_alns(inst,initial_solution=sol,
            config=replace(baseline,acceptance_mode="qos_physical_rrt"))
    with pytest.raises(ValueError):
        run_uav_mec_alns(inst,initial_solution=sol,
            config=replace(baseline,selection_mode="unit_credit_ucb"))
