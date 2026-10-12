"""Safety and unit-model guards for the *diagnostic-only* CPU share bound."""
from copy import deepcopy
from dataclasses import replace

from uav_mec.instances.small import build_small_instance
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.analysis.experiment_snapshot import content_hash


def test_small_original_valid_model_not_rejected():
    inst,sol=build_small_instance()
    before=content_hash(sol)
    info=build_event_info(inst,sol)
    q=queue_aware_feasibility_precheck(inst,sol,info)
    a=station_cpu_share_necessary_bound(inst,sol,info=info,queue=q)
    b=station_cpu_share_necessary_bound(inst,sol)
    assert a==b
    assert a["passes_necessary_cpu_share_test"],a
    assert "U1::E1" in a["pair_demands"]
    assert "U2::E1" in a["pair_demands"]
    assert len(a["stations"]["E1"]["pairs"])==2
    assert content_hash(sol)==before


def test_isolate_shared_station_cpu_capacity_decrease_monotonic():
    inst,sol=build_small_instance()
    base=station_cpu_share_necessary_bound(inst,sol)
    needs=base["stations"]["E1"]["required_cpu_lb_ghz"]
    assert needs is not None and needs>0
    changed=deepcopy(inst)
    original=changed.mecs["E1"]
    changed.mecs["E1"]=replace(original,cpu_ghz=needs*0.35)
    stressed=station_cpu_share_necessary_bound(changed,sol)
    assert stressed["certified_cpu_share_failure"],stressed
    assert stressed["stations"]["E1"]["min_cpu_pressure_ratio"]>2.0
    assert not base["certified_cpu_share_failure"]


def test_raising_station_cpu_never_creates_share_violation():
    inst,sol=build_small_instance()
    base=station_cpu_share_necessary_bound(inst,sol)
    bigger=deepcopy(inst)
    current=bigger.mecs["E1"]
    bigger.mecs["E1"]=replace(current,cpu_ghz=current.cpu_ghz*2)
    larger=station_cpu_share_necessary_bound(bigger,sol)
    assert larger["stations"]["E1"]["min_cpu_pressure_ratio"]<=base["stations"]["E1"]["min_cpu_pressure_ratio"]
