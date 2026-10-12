"""P4 numerical attribution extensions must preserve old solver semantics."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.optimization.resource.elastic_diagnosis import (
    PROTOCOLS,SINGLE_CAPACITY_DIAGNOSTIC_MODES,
    diagnose_elastic_resources,
)
from run_p4_postbound_attribution import COUNTERFACTUALS


def test_new_counterfactuals_do_not_mutate_original_model():
    instance,sol=build_small_instance()
    initial=content_hash(sol)
    assert PROTOCOLS==("qos_only","qos_plus_mec_capacity","mec_capacity_only")
    assert SINGLE_CAPACITY_DIAGNOSTIC_MODES==(
        "cpu_capacity_only","bandwidth_capacity_only")
    for mode,expected in (
        ("cpu_capacity_only","mec_cpu_cap"),
        ("bandwidth_capacity_only","bandwidth_cap"),
    ):
        diag=diagnose_elastic_resources(instance,sol,mode=mode)
        assert diag["numerically_credible"],diag
        assert diag["normalized_total_elastic_slack"]<0.002,diag
        assert set(diag["slack_sum_by_family"])=={expected}
        assert "counterfactual hardware expansion" in diag[
            "capacity_relaxation_interpretation"]
    assert content_hash(sol)==initial


def test_previous_elastic_modes_retained():
    instance,sol=build_small_instance()
    for mode in PROTOCOLS:
        res=diagnose_elastic_resources(instance,sol,mode=mode)
        assert res["numerically_credible"],(mode,res)
    assert COUNTERFACTUALS==(
        "qos_only","mec_capacity_only",
        "cpu_capacity_only","bandwidth_capacity_only",
    )


@pytest.mark.parametrize("mode",["both_capacity_and_time","cpu_plus_airtime",""])
def test_unlisted_counterfactuals_disallowed(mode):
    instance,sol=build_small_instance()
    with pytest.raises(ValueError):
        diagnose_elastic_resources(instance,sol,mode=mode)
