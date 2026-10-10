"""Numerical soundness and strict queue-model invariants for FIFO/EDF LB."""
from copy import deepcopy
from dataclasses import replace

import pytest

from uav_mec.analysis.stage1_acceptance import qualify_stage1_result, stage1_is_qualified
from uav_mec.domain import (
    ContactVisit, Route, RouteStop, StopType, TaskDecision,
)
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance
from uav_mec.optimization.resource import fast_feasibility_precheck
from uav_mec.optimization.resource.cvx_solver import solve_resource_problem
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


def test_queue_lb_does_not_exceed_strict_audited_stage1_solution():
    instance,solution=build_small_instance()
    info=build_event_info(instance,solution)
    solved=solve_resource_problem(instance,solution,info,run_stage2=False)
    accepted=qualify_stage1_result(instance,solution,solved)
    assert stage1_is_qualified(accepted), accepted.diagnostics
    lb=queue_aware_feasibility_precheck(instance,solution,info)
    old=fast_feasibility_precheck(instance,solution,info)
    assert lb.feasible, lb.reasons
    for task_id in instance.tasks:
        assert lb.task_completion_lb_s[task_id] >= old.task_completion_lb_s[task_id]-1e-6
        observed=float(accepted.stage1_values["task_completion_s"][task_id])
        assert lb.task_completion_lb_s[task_id] <= observed + .01


def test_queue_lb_sees_unavoidable_local_fifo_lateness_ignored_by_old_check():
    instance,solution=build_small_instance()
    from uav_mec.domain import TaskDecision
    instance=deepcopy(instance)
    solution=deepcopy(solution)
    solution.contact_visits={}
    for u,route in list(solution.routes.items()):
        solution.routes[u]=Route(u,tuple(
            stop for stop in route.stops if stop.kind is not StopType.CONTACT
        ))
    solution.task_decisions={t:TaskDecision.local() for t in instance.tasks}
    instance.tasks={
        t:replace(task,
                  cycles_per_bit=6000.0 if t=="S1" else task.cycles_per_bit,
                  deadline_s=500.0)
        for t,task in instance.tasks.items()
    }
    instance.avg_delay_budget_s=2000.0
    instance.cycle_s=2000.0
    validate_solution(instance,solution)
    info=build_event_info(instance,solution)
    old=fast_feasibility_precheck(instance,solution,info)
    new=queue_aware_feasibility_precheck(instance,solution,info)
    assert new.task_completion_lb_s["S2"] > old.task_completion_lb_s["S2"] + 1.0
    mid=.5*(new.task_completion_lb_s["S2"]+old.task_completion_lb_s["S2"])
    instance.tasks["S2"]=replace(instance.tasks["S2"],deadline_s=mid)
    info=build_event_info(instance,solution)
    assert fast_feasibility_precheck(instance,solution,info).feasible
    more=queue_aware_feasibility_precheck(instance,solution,info)
    assert not more.feasible
    assert any(x.startswith("task S2:") for x in more.reasons)


def test_mec_same_uav_two_batch_fifo_affects_optimistic_second_start():
    instance,solution=build_small_instance()
    solution=deepcopy(solution)
    route=solution.routes["U1"]
    stops=list(route.stops)
    stops.insert(-1,RouteStop.contact("V12"))
    solution.routes["U1"]=Route("U1",tuple(stops))
    solution.contact_visits["V12"]=ContactVisit("V12","U1","E1_P2")
    solution.task_decisions["S3"]=TaskDecision.offload("V12")
    validate_solution(instance,solution)
    info=build_event_info(instance,solution)
    assert info.contact_predecessor_same_mec["V12"]=="V11"
    lb=queue_aware_feasibility_precheck(instance,solution,info)
    assert lb.earliest_batch_start_lb_s["V12"]+1e-9 >= lb.mec_batch_earliest_finish_s["V11"]


def test_large_upload_from_prior_contact_affects_later_local_task_arrival():
    instance,solution=build_small_instance()
    info=build_event_info(instance,solution)
    old=fast_feasibility_precheck(instance,solution,info)
    new=queue_aware_feasibility_precheck(instance,solution,info)
    assert new.task_completion_lb_s["S3"] >= old.task_completion_lb_s["S3"]
    assert new.min_upload_s_by_visit["V11"] > 0


def test_release_times_not_silently_accepted_outside_frozen_model():
    instance,solution=build_small_instance()
    instance=deepcopy(instance)
    instance.tasks["S1"]=replace(instance.tasks["S1"],release_s=5.0)
    with pytest.raises(ValueError,match="release_s=0"):
        queue_aware_feasibility_precheck(instance,solution,build_event_info(instance,solution))
