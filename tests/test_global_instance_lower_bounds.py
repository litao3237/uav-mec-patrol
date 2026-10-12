"""P11 entire-instance necessary conditions must not reject strict controls."""
from copy import deepcopy
from dataclasses import replace

import pytest

from global_instance_lower_bounds import (
    global_physical_necessary_bounds,_euclidean_mst_length,
)
from uav_mec.instances.small import build_small_instance
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.analysis.experiment_snapshot import content_hash


def test_original_strict_Stage1_small_never_rejected_as_globally_impossible():
    inst,sol=build_small_instance()
    oracle=Stage1CVXObjectiveOracle()
    assert stage1_is_qualified(oracle.solve(inst,sol))
    before=content_hash(inst)
    result=global_physical_necessary_bounds(inst)
    assert not result["globally_infeasible_certified"],result
    assert result["single_task_necessary"]["impossible_count"]==0
    assert result["UAV_count"]==len(inst.uavs)
    assert result["optimistically_pooled_all_local_and_MEC_cpu_ghz"]>0
    assert content_hash(inst)==before


def test_trivially_impossible_deadline_is_globally_certified():
    inst,_=build_small_instance()
    changed=deepcopy(inst)
    changed.tasks={
        tid:replace(task,deadline_s=.01 if tid=="S1" else task.deadline_s)
        for tid,task in changed.tasks.items()
    }
    result=global_physical_necessary_bounds(changed)
    assert result["globally_infeasible_certified"],result
    assert "S1" in result["single_task_necessary"]["first_bad_tasks"]


def test_deadline_relaxation_never_increases_global_energetic_worst_case():
    inst,_=build_small_instance()
    original=global_physical_necessary_bounds(inst)
    larger=deepcopy(inst)
    larger.tasks={
        tid:replace(t,deadline_s=t.deadline_s+1000.)
        for tid,t in larger.tasks.items()
    }
    future=global_physical_necessary_bounds(larger)
    assert future["pooled_CPU_energetic_interval"]["demand_ratio"]<=(
        original["pooled_CPU_energetic_interval"]["demand_ratio"]+1e-8)
    assert future["UAV_collection_MST_deadline_prefix"]["demand_ratio"]<=(
        original["UAV_collection_MST_deadline_prefix"]["demand_ratio"]+1e-8)


def test_euclidean_mst_geometry_is_order_invariant_and_zero_for_single():
    points=[(0.,0.),(0.,3.),(4.,3.),(4.,0.)]
    a=_euclidean_mst_length(points)
    b=_euclidean_mst_length([points[2],points[0],points[3],points[1]])
    assert abs(a-9.)<1e-10
    assert abs(b-a)<1e-10
    assert _euclidean_mst_length([(1.,2.)])==0.


@pytest.mark.parametrize("tol",[-.01,float("nan"),float("inf")])
def test_unsafe_numeric_margins_are_rejected(tol):
    inst,_=build_small_instance()
    with pytest.raises(ValueError):
        global_physical_necessary_bounds(inst,tol_rel=tol)
