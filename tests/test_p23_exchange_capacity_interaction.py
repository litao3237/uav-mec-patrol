"""P23 only changes MEC resource numeric capacity, keeps task/contact geometry."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from run_p23_exchange_capacity_interaction import (
    CAPACITY,perturb_only_mec_capacity,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("key,factors",list(CAPACITY.items()))
def test_p23_cpu_bw_are_only_differences(key,factors):
    instance,discrete=build_small_instance()
    old_sha=content_hash(instance)
    old_D=content_hash(discrete)
    new=perturb_only_mec_capacity(instance,*factors)
    assert content_hash(instance)==old_sha
    assert content_hash(discrete)==old_D
    for name in ("tasks","uavs","contact_points","depot_xy",
                 "cycle_s","avg_delay_budget_s","max_contacts_per_uav"):
        assert content_hash(getattr(new,name))==content_hash(getattr(instance,name))
    for mid,mec in instance.mecs.items():
        assert new.mecs[mid].cpu_ghz==pytest.approx(mec.cpu_ghz*factors[0])
        assert new.mecs[mid].bandwidth_mhz==pytest.approx(
            mec.bandwidth_mhz*factors[1])
        assert new.mecs[mid].radius_m==mec.radius_m


def test_p23_disallows_less_capacity():
    instance,_=build_small_instance()
    with pytest.raises(ValueError):
        perturb_only_mec_capacity(instance,.5,1)
    with pytest.raises(ValueError):
        perturb_only_mec_capacity(instance,1,.5)
