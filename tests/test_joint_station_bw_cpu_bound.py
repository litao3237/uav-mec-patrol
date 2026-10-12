"""P5 rigorous joint bandwidth/CPU test: positive controls and safe monotonicity."""
from copy import deepcopy
from dataclasses import replace

import pytest

from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.analysis.stage1_acceptance import (
    qualify_stage1_result,stage1_is_qualified,
)
from uav_mec.optimization.resource.cvx_solver import solve_resource_problem
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)


@pytest.mark.parametrize("resolution",(4,12,24,48))
def test_strictly_feasible_original_small_model_never_falsely_pruned(resolution):
    inst,sol=build_small_instance()
    prev=content_hash(sol)
    stage1=qualify_stage1_result(
        inst,sol,solve_resource_problem(inst,sol,run_stage2=False))
    assert stage1_is_qualified(stage1),stage1.diagnostics
    res=joint_station_bw_cpu_necessary_bound(inst,sol,n_bins=resolution)
    assert res["passes_joint_necessary_test"],res
    assert not res["joint_necessary_reject"]
    assert res["numerical_solver_oracle_calls"]==0
    assert res["joint_test_wall_s"]>=0
    assert res["stations"]["E1"]["pair_count"]==2
    assert content_hash(sol)==prev


def test_reducing_shared_cpu_to_impossible_budget_is_certified_safely():
    inst,sol=build_small_instance()
    tiny=deepcopy(inst)
    tiny.mecs["E1"]=replace(tiny.mecs["E1"],cpu_ghz=1e-5)
    assert station_cpu_share_necessary_bound(tiny,sol)["certified_cpu_share_failure"]
    certificate=joint_station_bw_cpu_necessary_bound(tiny,sol,n_bins=12)
    assert certificate["joint_necessary_reject"]
    assert certificate["stations"]["E1"]["static_minimum_pair_capacity_impossible"]


def test_finer_nested_grid_cannot_lower_optimal_CPU_demand_significantly():
    inst,sol=build_small_instance()
    results=[
        joint_station_bw_cpu_necessary_bound(inst,sol,n_bins=n)
        for n in (6,12,24,48)
    ]
    needs=[x["stations"]["E1"]["optimistic_min_total_cpu_ghz"]
           for x in results]
    assert all(x is not None for x in needs)
    assert all(b>=a-1e-7 for a,b in zip(needs,needs[1:])),needs


@pytest.mark.parametrize("bad_bins",[0,1,-1,257,2.5,True])
def test_invalid_grid_resolution_fails_closed(bad_bins):
    inst,sol=build_small_instance()
    with pytest.raises(ValueError):
        joint_station_bw_cpu_necessary_bound(inst,sol,n_bins=bad_bins)


def test_does_not_modify_frozen_solution():
    inst,sol=build_small_instance()
    frozen=content_hash(sol)
    a=joint_station_bw_cpu_necessary_bound(inst,sol,n_bins=8)
    b=joint_station_bw_cpu_necessary_bound(inst,sol,n_bins=8)
    assert a["joint_necessary_reject"]==b["joint_necessary_reject"]
    assert a["stations"]["E1"]["optimistic_min_total_cpu_ghz"]==(
        b["stations"]["E1"]["optimistic_min_total_cpu_ghz"])
    assert content_hash(sol)==frozen
