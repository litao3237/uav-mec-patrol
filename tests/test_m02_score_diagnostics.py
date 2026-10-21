"""M0.2 controlled search-score diagnostics and strict compatibility."""
from dataclasses import replace
import pytest

from uav_mec.algorithms.alns import (
    ScreenedProxyObjectiveEvaluator,UavMecALNSConfig,run_uav_mec_alns,
)
from uav_mec.evaluation.task_objective import task_scalar,scalar_for_instance
from uav_mec.instances import build_small_instance


def test_only_scalar_reference_changes():
    instance,_=build_small_instance()
    instance=replace(instance,qos_hard=False)
    kw=dict(physical_violations=0,on_time=4,normalized_lateness=0.,
            energy_j=120000.,distance_m=10000.)
    old=ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile="v26_scale")._soft_scalar(instance,**kw)
    new=ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile="m0")._soft_scalar(instance,**kw)
    assert old==pytest.approx(task_scalar(total_tasks=len(instance.tasks),**kw))
    assert new==pytest.approx(scalar_for_instance(instance,**kw))
    assert abs(new-old)>1.
    with pytest.raises(ValueError):
        ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile="invalid")._soft_scalar(instance,**kw)


def test_trace_is_observation_only_and_reproducible():
    instance,solution=build_small_instance()
    instance=replace(instance,qos_hard=False)
    cfg=UavMecALNSConfig(iterations=8,seed=100)
    quiet=run_uav_mec_alns(instance,initial_solution=solution,config=cfg,
                    evaluator=ScreenedProxyObjectiveEvaluator())
    traced=run_uav_mec_alns(instance,initial_solution=solution,
                    config=replace(cfg,diagnostic_trace=True),
                    evaluator=ScreenedProxyObjectiveEvaluator())
    assert quiet.best_solution==traced.best_solution
    assert quiet.operator_pair_counts==traced.operator_pair_counts
    assert quiet.best_objective==pytest.approx(traced.best_objective)
    assert quiet.search_trace==[]
    assert len(traced.search_trace)==8
    assert sorted(x["iteration"] for x in traced.search_trace)==list(range(1,9))
    assert all(x["candidate_distance_m"]>=0 for x in traced.search_trace)
    assert sum(sum(c) for c in traced.operator_pair_counts.values())==8


def test_frozen_selector_and_greedy_acceptance_are_valid():
    instance,solution=build_small_instance()
    instance=replace(instance,qos_hard=False)
    result=run_uav_mec_alns(
        instance,initial_solution=solution,
        config=UavMecALNSConfig(iterations=5,seed=101,operator_decay=1.,
                                rrt_start_gap=0.,rrt_end_gap=0.,diagnostic_trace=True),
        evaluator=ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile="v26_scale"),
    )
    assert len(result.search_trace)==5
    assert result.best_objective<=result.initial_objective+1e-6
