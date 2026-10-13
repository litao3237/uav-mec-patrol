"""P20 unit controls: only MEC CPU/bandwidth changes, frozen source unchanged."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from run_p20_frozen_capacity_factorial import FACTORS, perturb_resources
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("label,scale", list(FACTORS.items()))
def test_only_requested_cpu_and_bandwidth_change(label, scale):
    inst, original_D = build_small_instance()
    source_sha = content_hash(inst)
    D_sha = content_hash(original_D)
    copy = deepcopy(inst)
    cpu, bw = scale
    trial = perturb_resources(inst, cpu, bw)
    assert content_hash(inst) == source_sha
    assert content_hash(original_D) == D_sha
    assert content_hash(trial.tasks) == content_hash(copy.tasks)
    assert content_hash(trial.uavs) == content_hash(copy.uavs)
    assert content_hash(trial.contact_points) == content_hash(copy.contact_points)
    assert set(trial.mecs) == set(inst.mecs)
    for mid, site in inst.mecs.items():
        assert trial.mecs[mid].cpu_ghz == pytest.approx(site.cpu_ghz * cpu)
        assert trial.mecs[mid].bandwidth_mhz == pytest.approx(
            site.bandwidth_mhz * bw
        )
        assert trial.mecs[mid].radius_m == site.radius_m
        assert trial.mecs[mid].x == site.x
        assert trial.mecs[mid].y == site.y


def test_reject_downward_capacity_change():
    inst, _ = build_small_instance()
    with pytest.raises(ValueError):
        perturb_resources(inst, 0.5, 1.0)
    with pytest.raises(ValueError):
        perturb_resources(inst, 1.0, 0.5)
