"""E1 rotor model compatibility, dimensional validation and physical replay."""
from dataclasses import replace
import math
import pytest

from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash, json_ready, restore_instance
from uav_mec.domain import UAV
from uav_mec.evaluation.events import build_event_info
from uav_mec.evaluation.propulsion import RotorParameters, rotor_power_w, flight_power_w, hover_power_w
from uav_mec.instances import build_small_instance, load_paper_scale_config, build_paper_scale_instance
from uav_mec.optimization.resource import CVXResourceSolver


def test_zeng_hover_and_forward_power():
    p = RotorParameters()
    assert rotor_power_w(0, p) == pytest.approx(168.49, abs=1e-9)
    assert 110 < rotor_power_w(10, p) < 150
    assert all(rotor_power_w(v, p)>0 for v in (0.,2.,5.,10.,15.,20.))
    with pytest.raises(ValueError):
        rotor_power_w(-1., p)
    with pytest.raises(ValueError):
        rotor_power_w(float("nan"), p)
    with pytest.raises(ValueError):
        RotorParameters(P0_w=-1.)


def test_legacy_uav_serialization_unchanged():
    instance, _ = build_small_instance()
    payload = json_ready(instance)
    assert all("propulsion_model" not in u and "rotor_params" not in u
               for u in payload["uavs"].values())
    assert content_hash(restore_instance(payload)) == content_hash(instance)
    u=next(iter(instance.uavs.values()))
    assert flight_power_w(u) == u.flight_power_w
    assert hover_power_w(u) == u.hover_power_w


def test_opt_in_rotor_config_without_changing_task_scenarios():
    base=load_paper_scale_config("configs/baseline.yaml")
    rotor=load_paper_scale_config("configs/rotor_e1.yaml")
    assert base.uav_propulsion_model=="constant"
    assert rotor.uav_propulsion_model=="rotor"
    assert rotor.uav_rotor_params is not None
    base_instance=build_paper_scale_instance(base,num_tasks=30,num_uavs=5,num_mecs=3,scenario_seed=45)
    rotor_instance=build_paper_scale_instance(rotor,num_tasks=30,num_uavs=5,num_mecs=3,scenario_seed=45)
    assert base_instance.tasks==rotor_instance.tasks
    assert base_instance.contact_points==rotor_instance.contact_points
    assert base_instance.mecs==rotor_instance.mecs
    assert all(u.propulsion_model=="rotor" for u in rotor_instance.uavs.values())
    assert all(flight_power_w(u)>0 and hover_power_w(u)>0 for u in rotor_instance.uavs.values())


def test_rotor_energy_consistency_and_physical_acceptance():
    instance,solution=build_small_instance()
    rotor_uavs={u: replace(data,propulsion_model="rotor") for u,data in instance.uavs.items()}
    rotor=replace(instance,uavs=rotor_uavs,qos_hard=False)
    constant=replace(instance,qos_hard=False)
    info=build_event_info(rotor,solution)
    base_info=build_event_info(constant,solution)
    for u in rotor.uavs:
        assert info.fixed_flight_energy_j[u]==pytest.approx(
            flight_power_w(rotor.uavs[u])*info.route_distance_m[u]/rotor.uavs[u].speed_mps
        )
        assert info.fixed_collection_energy_j[u] != base_info.fixed_collection_energy_j[u]
    result=CVXResourceSolver(run_stage2=False).solve(rotor,solution)
    assert result.stage1_values, result.diagnostics
    reports=audit_both_timelines(rotor,solution,result.stage1_values)
    assert all(item["complete"] and item["passed"] for item in reports.values())
    components=reports["reconstructed"]["metrics"]["energy_components_j"]
    assert sum(components.values()) == pytest.approx(
        reports["reconstructed"]["metrics"]["energy_j"],rel=1e-9
    )
