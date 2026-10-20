"""Protect v26 physics/QoS separation, cohort accounting, and deterministic admission."""
from dataclasses import replace

import pytest

from uav_mec.analysis.task_admission import admit_tasks, project_tasks, task_removal_order
from uav_mec.analysis.task_metrics import REQUIRED_TASK_QOS_FIELDS, summarize_task_qos
from uav_mec.algorithms.initial.mec_repair import evaluate_initial_proxy
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.task_objective import task_scalar, task_key
from uav_mec.instances import build_small_instance
from uav_mec.optimization.resource.precheck import fast_feasibility_precheck


def test_soft_qos_deadline_does_not_invalidate_physical_precheck():
    original, solution = build_small_instance()
    hard = replace(original, tasks={
        t: replace(task, deadline_s=0.001) for t, task in original.tasks.items()
    })
    soft = replace(hard, qos_hard=False)
    strict_check = fast_feasibility_precheck(hard, solution, build_event_info(hard, solution))
    soft_check = fast_feasibility_precheck(soft, solution, build_event_info(soft, solution))
    assert not strict_check.feasible
    assert any('deadline' in reason for reason in strict_check.reasons)
    assert all('deadline' not in reason and 'average delay' not in reason
               for reason in soft_check.reasons)
    soft_proxy = evaluate_initial_proxy(soft, solution)
    assert soft_proxy.score.qos_soft
    assert soft_proxy.score.on_time_tasks == 0


def test_discrete_rank_prioritizes_success_then_lateness_then_energy():
    a = task_key(physical_violations=0, on_time=2, normalized_lateness=200,
                 energy_j=200000, distance_m=10000)
    b = task_key(physical_violations=0, on_time=1, normalized_lateness=0,
                 energy_j=0, distance_m=0)
    assert a < b
    s1 = task_scalar(total_tasks=3, physical_violations=0, on_time=2,
                     normalized_lateness=200, energy_j=200000, distance_m=10000)
    s2 = task_scalar(total_tasks=3, physical_violations=0, on_time=1,
                     normalized_lateness=0, energy_j=0, distance_m=0)
    assert s1 < s2
    assert task_scalar(total_tasks=3, physical_violations=1, on_time=3,
                       normalized_lateness=0, energy_j=1, distance_m=1) > s1


def test_admission_projects_stops_without_dangling_visits():
    original, solution = build_small_instance()
    soft = replace(original, qos_hard=False)
    removed = sorted(soft.tasks)[0]
    subset, projected = project_tasks(soft, solution, set(soft.tasks)-{removed})
    assert removed not in projected.task_decisions
    assert set(subset.tasks) == set(projected.task_decisions)
    build_event_info(subset, projected)
    assert set(task_removal_order(soft, solution)) == set(soft.tasks)


def test_zero_task_idle_is_a_true_physical_fallback():
    original, solution = build_small_instance()
    impossible = replace(original, qos_hard=False, cycle_s=0.000001)
    result = admit_tasks(impossible, solution)
    assert result.source == "verified_idle"
    assert len(result.instance.tasks) == 0
    assert set(result.removed_reasons) == set(impossible.tasks)
    assert all(route.labels() == ["DEPOT", "DEPOT"]
               for route in result.solution.routes.values())
    assert result.resources is None


def test_task_metrics_never_fake_missing_stage2_or_unserved_delays():
    original, _ = build_small_instance()
    ids = sorted(original.tasks)
    delays = {ids[0]: original.tasks[ids[0]].deadline_s + 1,
              ids[1]: original.tasks[ids[1]].deadline_s / 2}
    removed = {t: "physical_admission_rejected" for t in ids[2:]}
    r = summarize_task_qos(original, served_ids=set(delays), delays_s=delays,
                           unserved_reasons=removed, energy_stage1=100,
                           energy_stage2=None, total_energy=100,
                           route_distance_m=80, cpu_utilization=.2,
                           runtime_s=1, energy_source="constructive_verified")
    assert set(REQUIRED_TASK_QOS_FIELDS) <= set(r)
    assert r["stage2_energy"] is None
    assert r["task_outcomes"][ids[-1]]["delay_s"] is None if len(ids) > 2 else True
    assert r["success_rate"] == pytest.approx(1 / len(original.tasks))
    assert r["deadline_violation_rate"] == pytest.approx(1 / len(original.tasks))
    assert r["strict_all_tasks_success"] is False
    assert r["energy_per_successful_task"] == pytest.approx(100)


def test_undefined_success_conditional_metrics_are_null_not_zero():
    original, _ = build_small_instance()
    values = summarize_task_qos(
        original, served_ids=set(), delays_s={},
        unserved_reasons={t: "unserved" for t in original.tasks},
        energy_stage1=0, energy_stage2=None, total_energy=0,
        route_distance_m=0, cpu_utilization=0, runtime_s=1,
        energy_source="verified_idle")
    assert values["mean_delay_success"] is None
    assert values["energy_per_successful_task"] is None
    assert values["mean_delay_all"] == original.cycle_s
    assert values["success_rate"] == 0


def test_strict_instance_json_is_backward_compatible_and_soft_is_explicit():
    from uav_mec.analysis.experiment_snapshot import json_ready, restore_instance
    inst, _ = build_small_instance()
    legacy = json_ready(inst)
    assert "qos_hard" not in legacy
    assert restore_instance(legacy).qos_hard is True
    v26 = json_ready(replace(inst, qos_hard=False))
    assert v26["qos_hard"] is False
    assert restore_instance(v26).qos_hard is False



def test_energy_metrics_are_independent_physical_measurements():
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
    from run_seven_methods import finalize
    inst, solution = build_small_instance()
    soft = replace(inst, qos_hard=False)
    row = finalize(soft, solution, method="TEST", seed=None,
                   initialization_s=0., search_s=0., diagnostics={})
    m = row["metrics"]
    assert m["physical_feasible"] is True
    assert m["stage1_energy"] >= 0.
    if m["stage2_energy"] is not None:
        assert m["stage2_energy"] == pytest.approx(m["total_energy"], rel=1e-8)
