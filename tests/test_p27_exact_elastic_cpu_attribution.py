"""P27 predeclared physical source / elastic relaxation control tests."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from run_p27_exact_elastic_cpu_attribution import MODES,SAMPLES
from uav_mec.optimization.resource.elastic_diagnosis import (
    SINGLE_CAPACITY_DIAGNOSTIC_MODES,PROTOCOLS,
)


def test_preregistered_source_only_known_original_cases():
    assert set(SAMPLES)=={
        (91,"compute_x1p5",128),
        (93,"baseline",129),
    }
    assert all("single" in record and "batch" in record
               for record in SAMPLES.values())
    assert all(isinstance(s["single"],str) and isinstance(s["batch"],str)
               for s in SAMPLES.values())


def test_elastic_methods_are_existing_diagnostic_not_physics_replacement():
    assert set(MODES).issubset(
        set(SINGLE_CAPACITY_DIAGNOSTIC_MODES) | set(PROTOCOLS)
    )
    assert MODES==(
        "cpu_capacity_only",
        "bandwidth_capacity_only",
        "mec_capacity_only",
        "qos_only",
    )
