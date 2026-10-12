"""P9 task-destroy targeting tests: original behavior default unchanged."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from uav_mec.algorithms import (
    UavMecALNSConfig,ScreenedProxyObjectiveEvaluator,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns.queue_operators import (
    QUEUE_DESTROY_POLICIES,queue_guided_task_rank,
    queue_critical_task_removal,create_queue_destroy_operator,
    _critical_queue_chains,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.algorithms.alns.operators import (
    DestroyConfig,critical_task_removal,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation import build_event_info
from uav_mec.instances.small import build_small_instance
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


def test_chain_includes_local_FIFO_ancestors_of_violating_task():
    inst,source=build_small_instance()
    changed=deepcopy(inst)
    changed.tasks={
        t:replace(task,deadline_s=1.0 if t=="S1" else task.deadline_s)
        for t,task in inst.tasks.items()
    }
    info=build_event_info(changed,source)
    queue=queue_aware_feasibility_precheck(changed,source,info)
    assert not queue.feasible
    graph=_critical_queue_chains(changed,source,info,queue)
    assert "S1" in graph and "S1" in graph["S1"]


@pytest.mark.parametrize("policy",QUEUE_DESTROY_POLICIES)
def test_operator_removes_exact_q_tasks_without_mutating_source(policy):
    inst,source=build_small_instance()
    old=content_hash(source)
    state=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    rng=np.random.default_rng(38)
    cfg=DestroyConfig(fraction=.5,min_remove=2,max_remove=3)
    tasks,details=queue_guided_task_rank(inst,source,policy=policy)
    assert len(tasks)==len(inst.tasks)
    assert len(set(tasks))==len(tasks)
    assert details["task_count"]==len(inst.tasks)
    destroyed=queue_critical_task_removal(state,rng,config=cfg,policy=policy)
    assert len(destroyed.removed_tasks)==cfg.count(len(inst.tasks))
    assert len(set(destroyed.removed_tasks))==len(destroyed.removed_tasks)
    assert content_hash(source)==old
    assert content_hash(state.solution)==old


def test_default_ALNS_is_identical_with_experiment_policy_explicitly_none():
    inst,sol=build_small_instance()
    common=dict(iterations=3,seed=192,enable_problem_operators=False)
    ctrl=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),
        config=UavMecALNSConfig(**common),
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    explicit=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),
        config=UavMecALNSConfig(**common,queue_destroy_policy=None),
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    assert content_hash(ctrl.best_solution)==content_hash(explicit.best_solution)
    assert ctrl.best_objective==explicit.best_objective


@pytest.mark.parametrize("policy",QUEUE_DESTROY_POLICIES)
def test_experimental_policy_preserves_route_task_structural_legality(policy):
    inst,sol=build_small_instance()
    res=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),
        config=UavMecALNSConfig(
            iterations=3,seed=192,enable_problem_operators=False,
            queue_destroy_policy=policy),
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    from uav_mec.evaluation.validator import validate_solution
    validate_solution(inst,res.best_solution)


def test_invalid_queue_destroy_policy_rejected():
    inst,sol=build_small_instance()
    with pytest.raises(ValueError):
        run_uav_mec_alns(
            inst,initial_solution=sol,
            config=UavMecALNSConfig(
                iterations=2,queue_destroy_policy="invalid"),
        )
