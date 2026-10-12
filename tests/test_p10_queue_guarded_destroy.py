"""P10 one-slot ALNS control: fallback exact when no deadline violations."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from uav_mec.algorithms.alns.queue_operators import (
    GATED_POLICIES,queue_critical_task_removal,queue_guided_task_rank,
)
from uav_mec.algorithms.alns.operators import (
    DestroyConfig,critical_task_removal,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,UavMecALNSConfig,run_uav_mec_alns,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances.small import build_small_instance
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


@pytest.mark.parametrize("policy",sorted(GATED_POLICIES))
@pytest.mark.parametrize("seed",[7,91,703])
def test_guarded_is_exact_original_when_queue_task_deadlines_satisfied(policy,seed):
    inst,sol=build_small_instance()
    q=queue_aware_feasibility_precheck(inst,sol,build_event_info(inst,sol))
    assert q.feasible
    init=content_hash(sol)
    state=UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
    cfg=DestroyConfig()
    original=critical_task_removal(state,np.random.default_rng(seed),config=cfg)
    gated=queue_critical_task_removal(
        state,np.random.default_rng(seed),config=cfg,policy=policy)
    assert original.removed_tasks==gated.removed_tasks
    assert content_hash(original.solution)==content_hash(gated.solution)
    assert content_hash(sol)==init


@pytest.mark.parametrize("policy",sorted(GATED_POLICIES))
def test_guarded_still_targets_true_FIFO_EDF_task_deadline_failure(policy):
    inst,source=build_small_instance()
    inst=deepcopy(inst)
    inst.tasks={t:replace(v,deadline_s=1.0 if t=="S1" else v.deadline_s)
                for t,v in inst.tasks.items()}
    rank,why=queue_guided_task_rank(inst,source,policy=policy)
    assert not why["queue_pass"]
    assert why["deadline_violators"]>0
    assert len(rank)==len(inst.tasks)
    state=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    result=queue_critical_task_removal(
        state,np.random.default_rng(83),config=DestroyConfig(),policy=policy)
    assert len(result.removed_tasks)==DestroyConfig().count(len(inst.tasks))


def test_ungated_and_gated_predecessor_rankings_agree_on_failed_D():
    inst,sol=build_small_instance()
    inst=deepcopy(inst)
    inst.tasks={tid:replace(task,deadline_s=.5 if tid=="S1" else task.deadline_s)
                for tid,task in inst.tasks.items()}
    for gated,base in GATED_POLICIES.items():
        r1,d1=queue_guided_task_rank(inst,sol,policy=gated)
        r2,d2=queue_guided_task_rank(inst,sol,policy=base)
        assert r1==r2
        assert d1["deadline_violators"]==d2["deadline_violators"]


def test_default_original_critical_destroy_still_unmodified_after_hook():
    inst,sol=build_small_instance()
    cfg=dict(iterations=3,seed=514,enable_problem_operators=False)
    old=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),
        config=UavMecALNSConfig(**cfg),
        evaluator=ScreenedProxyObjectiveEvaluator())
    explicit=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),
        config=UavMecALNSConfig(**cfg,queue_destroy_policy=None),
        evaluator=ScreenedProxyObjectiveEvaluator())
    assert content_hash(old.best_solution)==content_hash(explicit.best_solution)
    assert old.best_objective==explicit.best_objective


@pytest.mark.parametrize("policy",sorted(GATED_POLICIES))
def test_ALNS_runner_executes_gated_operators_without_new_repair_ops(policy):
    inst,sol=build_small_instance()
    run=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),
        config=UavMecALNSConfig(
            iterations=4,seed=515,queue_destroy_policy=policy,
            enable_problem_operators=False),
        evaluator=ScreenedProxyObjectiveEvaluator())
    from uav_mec.evaluation.validator import validate_solution
    validate_solution(inst,run.best_solution)
