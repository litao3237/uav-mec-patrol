"""P8 queue gradient is tied to real FIFO/EDF necessary time inequality."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from queue_guided_alns_evaluator import (
    QueueGuidedObjectiveEvaluator,normalized_queue_violation,
    INFEASIBLE_BASE_J,POLICIES,
)
from run_p8_queue_alns_pilot import P8ReadOnlyFunnel,ARMS
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation import build_event_info
from uav_mec.instances.small import build_small_instance
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


def make_true_necessary_queue_failure():
    inst,sol=build_small_instance()
    inst=deepcopy(inst)
    inst.tasks={
        tid:replace(t,deadline_s=1.0 if tid=="S1" else t.deadline_s)
        for tid,t in inst.tasks.items()
    }
    q=queue_aware_feasibility_precheck(inst,sol,build_event_info(inst,sol))
    assert not q.feasible
    assert normalized_queue_violation(inst,q)["violated_task_deadlines"]>=1
    return inst,sol


@pytest.mark.parametrize("policy",POLICIES)
def test_true_queue_certificate_failure_gets_continuous_large_penalty(policy):
    inst,sol=make_true_necessary_queue_failure()
    frozen=content_hash(sol)
    e=QueueGuidedObjectiveEvaluator(policy=policy)
    a=e(inst,sol)
    assert a>=INFEASIBLE_BASE_J
    assert e.stats["queue_necessary_fail"]==1
    assert e.original.stats.calls==0,"Do not waste original CVX on true necessary failure"
    assert e(inst,sol)==a
    assert e.stats["cache_hits"]==1
    assert content_hash(sol)==frozen


@pytest.mark.parametrize("policy",POLICIES)
def test_original_energy_unchanged_for_known_strict_feasible_state(policy):
    inst,sol=build_small_instance()
    original=ScreenedProxyObjectiveEvaluator()
    guided=QueueGuidedObjectiveEvaluator(policy=policy)
    cost_orig=original(inst,sol)
    cost_new=guided(inst,sol)
    assert cost_new==cost_orig,(policy,cost_new,cost_orig)
    assert cost_new<1e8
    assert guided.stats["queue_necessary_pass"]==1
    assert guided.stats["original_finite_energy_zone"]==1


def test_gradient_magnitude_tracks_deadline_violation():
    inst,sol=make_true_necessary_queue_failure()
    worse=deepcopy(inst)
    worse.tasks={
        tid:replace(task,deadline_s=.25 if tid=="S1" else task.deadline_s)
        for tid,task in inst.tasks.items()
    }
    for policy in POLICIES:
        a=QueueGuidedObjectiveEvaluator(policy=policy)(inst,sol)
        b=QueueGuidedObjectiveEvaluator(policy=policy)(worse,sol)
        assert b>a,(policy,a,b)


def test_p8_readonly_funnel_returns_original_scalar_identically():
    inst,sol=build_small_instance()
    underlying=ScreenedProxyObjectiveEvaluator()
    logger=P8ReadOnlyFunnel(underlying)
    control=ScreenedProxyObjectiveEvaluator()
    x=logger(inst,sol)
    assert x==control(inst,sol)
    assert logger(inst,sol)==x
    assert logger.counters["unique_visited"]==1
    assert logger.counters["joint_bw_cpu_necessary_pass"]==1
    assert logger.observer_wall_s>=0
    assert ARMS==("original","queue_sum","queue_max")


@pytest.mark.parametrize("invalid",["noop","queue_cpu","","queue_binary"])
def test_unknown_policy_fails_closed(invalid):
    with pytest.raises(ValueError):
        QueueGuidedObjectiveEvaluator(policy=invalid)
