"""MEC capacity-only elastic diagnosis retains all QoS and FIFO/EDF constraints."""
from copy import deepcopy
from dataclasses import replace

import pytest

from uav_mec.domain import Route, TaskDecision, StopType
from uav_mec.instances.small import build_small_instance
from uav_mec.optimization.resource.elastic_diagnosis import (
    diagnose_elastic_resources,
)


def test_existing_strict_baseline_needs_no_hypothetical_mec_upgrade():
    instance,sol=build_small_instance()
    r=diagnose_elastic_resources(
        instance,sol,mode="mec_capacity_only",
    )
    assert r["numerically_credible"],r
    assert r["status"]=="optimal"
    assert r["normalized_total_elastic_slack"]<.002,r
    assert set(r["slack_sum_by_family"]).issubset({
        "bandwidth_cap","mec_cpu_cap"
    })
    assert all(x["family"] in ("bandwidth_cap","mec_cpu_cap")
               for x in r["top_constraints"])


def test_extremely_early_deadline_cannot_be_fixed_by_mec_expansion():
    instance,sol=build_small_instance()
    stressed=deepcopy(instance)
    stressed.tasks={
        t:replace(task,deadline_s=.1 if t=="S1" else task.deadline_s)
        for t,task in instance.tasks.items()
    }
    r=diagnose_elastic_resources(
        stressed,sol,mode="mec_capacity_only"
    )
    assert not r["numerically_credible"],r
    assert r["status"] in (
        "infeasible","infeasible_inaccurate","solver_error","unbounded_inaccurate"
    )


def test_without_any_contact_no_mec_capacity_slack_exists():
    instance,sol=build_small_instance()
    sol=deepcopy(sol)
    sol.routes={
        uid:Route(uid,tuple(s for s in route.stops
                            if s.kind is not StopType.CONTACT))
        for uid,route in sol.routes.items()
    }
    sol.contact_visits={}
    sol.task_decisions={tid:TaskDecision.local() for tid in instance.tasks}
    r=diagnose_elastic_resources(
        instance,sol,mode="mec_capacity_only"
    )
    assert r["status"]=="no_applicable_elastic_capacity_constraints"
    assert not r["numerically_credible"]


def test_capacity_and_qos_modes_have_different_soft_constraint_sets():
    instance,sol=build_small_instance()
    q=diagnose_elastic_resources(instance,sol,mode="qos_only")
    allsoft=diagnose_elastic_resources(instance,sol,mode="qos_plus_mec_capacity")
    cap=diagnose_elastic_resources(instance,sol,mode="mec_capacity_only")
    assert all(x["numerically_credible"] for x in (q,allsoft,cap))
    assert set(q["slack_sum_by_family"])=={"deadline","avg_delay","cycle","battery"}
    assert set(cap["slack_sum_by_family"])=={"bandwidth_cap","mec_cpu_cap"}
    assert set(allsoft["slack_sum_by_family"])==(
        set(q["slack_sum_by_family"])|set(cap["slack_sum_by_family"])
    )
