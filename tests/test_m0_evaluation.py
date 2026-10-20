"""M0 regressions: deadline semantics, true-unit elite gains, energy refinement."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import sys
from pathlib import Path

import pytest

from uav_mec.algorithms.alns import problem_operators as ops
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.evaluation.task_objective import (
    ON_TIME_TOL_S, LATENESS_TOL, better_task_key, measured_task_key,
    scalar_for_instance, task_key,
)
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource import CVXResourceSolver
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.stage1_acceptance import qualify_stage1_result
from uav_mec.analysis.task_metrics import summarize_task_qos


def test_energy_sensitivity_at_realistic_joule_scale():
    instance, _ = build_small_instance()
    a = scalar_for_instance(instance, physical_violations=0, on_time=5,
                            normalized_lateness=0, energy_j=118574., distance_m=1200.)
    b = scalar_for_instance(instance, physical_violations=0, on_time=5,
                            normalized_lateness=0, energy_j=118056., distance_m=1200.)
    assert a > b + .01, (a, b)
    assert better_task_key(task_key(physical_violations=0, on_time=5,
                                   normalized_lateness=0, energy_j=118056., distance_m=1200.),
                           task_key(physical_violations=0, on_time=5,
                                   normalized_lateness=0, energy_j=118574., distance_m=1200.),
                           min_energy_improvement_j=1.,
                           min_energy_improvement_rel=1e-4)


def test_success_and_lateness_outrank_any_energy():
    expensive_successful = task_key(physical_violations=0, on_time=3,
                                    normalized_lateness=.5, energy_j=1e6, distance_m=5e4)
    cheap_fewer_successes = task_key(physical_violations=0, on_time=2,
                                    normalized_lateness=0., energy_j=1., distance_m=1.)
    assert better_task_key(expensive_successful, cheap_fewer_successes)
    assert not better_task_key(cheap_fewer_successes, expensive_successful)
    low_lateness = task_key(physical_violations=0, on_time=3,
                            normalized_lateness=.01, energy_j=1e6, distance_m=1e4)
    high_lateness = task_key(physical_violations=0, on_time=3,
                             normalized_lateness=.02, energy_j=1., distance_m=1.)
    assert better_task_key(low_lateness, high_lateness)
    assert not better_task_key(cheap_fewer_successes, low_lateness)


def test_frozen_microsecond_qos_tolerance_matches_row_metrics():
    inst, _ = build_small_instance()
    first = sorted(inst.tasks)[0]
    delays = {t: inst.tasks[t].deadline_s / 2 for t in inst.tasks}
    delays[first] = inst.tasks[first].deadline_s + ON_TIME_TOL_S / 2
    key = measured_task_key(inst, delays, energy_j=100., distance_m=10.)
    row = summarize_task_qos(
        inst, served_ids=set(inst.tasks), delays_s=delays, unserved_reasons={},
        energy_stage1=100., energy_stage2=None, total_energy=100.,
        route_distance_m=10., cpu_utilization=0., runtime_s=1.,
        energy_source="unit_test",
    )
    assert -key[1] == row["on_time_tasks"] == len(inst.tasks)
    assert key[2] == 0.
    delays[first] = inst.tasks[first].deadline_s + 5 * ON_TIME_TOL_S
    key = measured_task_key(inst, delays, energy_j=100., distance_m=10.)
    row = summarize_task_qos(
        inst, served_ids=set(inst.tasks), delays_s=delays, unserved_reasons={},
        energy_stage1=100., energy_stage2=None, total_energy=100.,
        route_distance_m=10., cpu_utilization=0., runtime_s=1.,
        energy_source="unit_test",
    )
    assert -key[1] == row["on_time_tasks"] == len(inst.tasks)-1
    assert key[2] > 0


def test_elite_measured_joules_can_be_accepted_even_if_scalar_is_worse(monkeypatch):
    instance, original = build_small_instance()
    instance = replace(instance, qos_hard=False)
    candidate = deepcopy(original)
    candidate.metadata["m0_trial"] = "energy_saved"

    class Oracle:
        def quality_key(self, instance, solution):
            e = 118056. if solution.metadata.get("m0_trial") else 118574.
            return task_key(physical_violations=0, on_time=5,
                            normalized_lateness=0., energy_j=e, distance_m=1200.)
        def __call__(self, instance, solution):
            return 1000.2 if solution.metadata.get("m0_trial") else 1000.

    monkeypatch.setattr(ops, "_structural_elite_candidates",
                        lambda state, config: [("test_energy_move", candidate)])
    state = UavMecState(instance, original, Oracle())
    improved, stats = ops.contact_mode_intensification(
        state, objective=Oracle(),
        config=ops.ProblemOperatorConfig(elite_progressive_widening=False),
        max_rounds=1,
    )
    assert improved.solution.metadata.get("m0_trial") == "energy_saved"
    assert stats["improvements"] == 1
    assert stats["accepted_moves"][0]["improvement_j"] == pytest.approx(518.)
    assert stats["accepted_moves"][0]["success_count_gain"] == 0


def test_elite_must_reject_lower_success_even_if_energy_drops(monkeypatch):
    instance, original = build_small_instance()
    instance = replace(instance, qos_hard=False)
    candidate = deepcopy(original)
    candidate.metadata["m0_trial"] = "worse_success"

    class Oracle:
        def quality_key(self, instance, solution):
            return task_key(
                physical_violations=0,
                on_time=4 if solution.metadata.get("m0_trial") else 5,
                normalized_lateness=.02 if solution.metadata.get("m0_trial") else 0.,
                energy_j=100. if solution.metadata.get("m0_trial") else 118574.,
                distance_m=100.,
            )
        def __call__(self, instance, solution):
            return 0. if solution.metadata.get("m0_trial") else 1000.

    monkeypatch.setattr(ops, "_structural_elite_candidates",
                        lambda state, config: [("low_energy_low_success", candidate)])
    state = UavMecState(instance, original, Oracle())
    improved, stats = ops.contact_mode_intensification(
        state, objective=Oracle(),
        config=ops.ProblemOperatorConfig(elite_progressive_widening=False),
        max_rounds=1,
    )
    assert "m0_trial" not in improved.solution.metadata
    assert stats["improvements"] == 0


def test_soft_cvx_preserves_physical_audits_and_exposes_m0_policy():
    instance, solution = build_small_instance()
    instance = replace(instance, qos_hard=False)
    result = CVXResourceSolver(run_stage2=False).solve(instance, solution)
    assert result.feasible, result.diagnostics
    assert result.diagnostics["stage1_resource_policy"] == "m0_quality_guarded_energy_refinement"
    qualified = qualify_stage1_result(instance, solution, result)
    if qualified.diagnostics["stage1_qualified"]:
        audit = qualified.diagnostics["stage1_acceptance_audit"]
        assert all(x["complete"] and x["passed"] for x in audit.values())
    else:
        assert qualified.diagnostics["stage1_acceptance_reason"] is not None
    assert "m0_energy_refinement_status" in result.diagnostics
