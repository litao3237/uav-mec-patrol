"""Contract and actual cached/live search invariants for queue-aware evaluator."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_online_queue_budget import (
    METHODS, PROFILES, TIME_BUDGET_S, split_budget, summarize,
)
from uav_mec.algorithms.alns.evaluator import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns.queue_evaluator import QueueAwareScreenedProxyObjectiveEvaluator
from uav_mec.instances.small import build_small_instance
from uav_mec.optimization.resource.precheck import fast_feasibility_precheck
from uav_mec.evaluation import build_event_info


def test_original_screen_unchanged_and_queue_screen_matches_small_feasible():
    instance, solution = build_small_instance()
    base = ScreenedProxyObjectiveEvaluator()
    proposed = QueueAwareScreenedProxyObjectiveEvaluator()
    a = base(instance, solution)
    b = proposed(instance, solution)
    assert a == pytest.approx(b, abs=1e-4)
    assert proposed.stats.calls == 1
    assert proposed.queue_stats.queue_precheck_calls <= 1
    assert proposed.queue_stats.additional_rejections == 0
    assert proposed.queue_stats.avoided_exact_cvx_calls == 0
    assert proposed(instance, solution) == b
    assert proposed.stats.cache_hits == 1


def test_new_certificate_preempts_expensive_cvx_only_for_ambiguous_proxy(monkeypatch):
    import uav_mec.algorithms.alns.queue_evaluator as qe
    instance, solution = build_small_instance()
    pre = fast_feasibility_precheck(instance, solution, build_event_info(instance, solution))
    assert pre.feasible

    # A deliberately artificial queue witness verifies branch selection.
    # The physical validity of real queue proofs is separately tested.
    monkeypatch.setattr(qe, "queue_aware_feasibility_precheck", lambda *a, **kw:
        SimpleNamespace(feasible=False, reasons=("task S2: forced unit certificate",),
                        task_completion_lb_s={t: 30.0 for t in instance.tasks}))
    monkeypatch.setattr(qe, "evaluate_initial_proxy", lambda *a, **kw:
        SimpleNamespace(score=SimpleNamespace(
            violated_constraints=1,
            max_normalized_violation=0.2,
            sum_normalized_violation=0.4,
            total_energy_j=100.0)))
    proposed = QueueAwareScreenedProxyObjectiveEvaluator(cvx_solver=Mock())
    result = proposed(instance, solution)
    assert result > 1e9
    assert proposed.queue_stats.additional_rejections == 1
    assert proposed.queue_stats.avoided_exact_cvx_calls == 1
    assert proposed.stats.cvx_refinements == 0
    proposed.cvx_solver.solve.assert_not_called()


def test_old_precheck_failure_skips_extra_queue_work(monkeypatch):
    import uav_mec.algorithms.alns.queue_evaluator as qe
    instance, solution = build_small_instance()
    monkeypatch.setattr(qe, "fast_feasibility_precheck", lambda *a, **kw:
        SimpleNamespace(feasible=False, reasons=("forced_old_lb",)))
    monkeypatch.setattr(qe, "queue_aware_feasibility_precheck", lambda *a, **kw:
        (_ for _ in ()).throw(AssertionError("queue check should not run")))
    proposed = QueueAwareScreenedProxyObjectiveEvaluator()
    assert proposed(instance, solution) > 1e9
    assert proposed.queue_stats.old_precheck_rejected == 1
    assert proposed.queue_stats.queue_precheck_calls == 0


def test_time_allocations_equal_and_count_initialization():
    assert METHODS == ("B-ALNS-legacy","B-ALNS-queue",
                       "ESI-ALNS-legacy","ESI-ALNS-queue")
    assert set(PROFILES) == {"baseline","compute_x1p5","deadline_x0p9"}
    for budget in TIME_BUDGET_S.values():
        for method in METHODS:
            s = split_budget(budget, 0.7, method)
            assert s["alns_s"] + s["elite_s"] + s["reserved_final_s"] + 0.7 == pytest.approx(budget)
            assert s["elite_s"] == pytest.approx(
                .2 * budget if method.startswith("ESI-") else 0.0
            )


def test_method_summary_requires_strict_paired_validity():
    def row(m,energy,valid,within,queue):
        return {
            "tasks":50,"scenario":69,"seed":115,
            "profile":"baseline","method":m,
            "status":"ok","both_qualified":valid,
            "stage1_qualified":valid,"within_budget":within,
            "total_s":14.0,"energy_stage1_j":energy if valid else None,
            "queue_stats": queue,"evaluator_stats":{"calls":10,"cache_hits":2,"cvx_refinements":3}
        }
    rows=[
        row("B-ALNS-legacy",100,True,True,None),
        row("B-ALNS-queue",90,True,True,asdict(QueueAwareScreenedProxyObjectiveEvaluator().queue_stats)),
        row("ESI-ALNS-legacy",80,True,True,None),
        row("ESI-ALNS-queue",None,False,False,asdict(QueueAwareScreenedProxyObjectiveEvaluator().queue_stats)),
    ]
    s=summarize(rows)
    b=next(x for x in s if x["method"]=="B-ALNS-queue" and x["profile"]=="baseline")
    assert b["paired_vs_legacy"]==1
    assert b["paired_saving_vs_legacy_j"]==pytest.approx(10.0)
    e=next(x for x in s if x["method"]=="ESI-ALNS-queue" and x["profile"]=="baseline")
    assert e["paired_vs_legacy"]==0
    assert e["paired_saving_vs_legacy_j"] is None
    assert e["both_qualified"]==0
