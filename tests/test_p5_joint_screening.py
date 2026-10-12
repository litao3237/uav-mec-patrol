"""P5 paired screening tests: frozen no extra strict CVX budget."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from run_p5_joint_screening_probe import ARMS,choose
from uav_mec.instances.small import build_small_instance
from uav_mec.analysis.experiment_snapshot import content_hash


@pytest.mark.parametrize("arm",ARMS)
def test_all_arms_keep_known_original_feasible_structure_in_shortlist(arm):
    inst,sol=build_small_instance()
    original=content_hash(sol)
    pool=[{"label":"original_small","sol":sol}]
    selected,counters=choose(inst,pool,arm=arm,max_exact_checks=3)
    assert len(selected)==1
    assert selected[0]["label"]=="original_small"
    assert counters["gate_wall_s"]>=0
    assert content_hash(sol)==original


def test_joint_fully_respects_hard_three_oracle_candidate_limit():
    inst,sol=build_small_instance()
    pool=[{"label":str(i),"sol":sol} for i in range(8)]
    for arm in ARMS:
        selected,stats=choose(inst,pool,arm=arm,max_exact_checks=3)
        assert len(selected)==3
        assert stats["gate_wall_s"]>=0


def test_invalid_screen_configuration_fails_closed():
    inst,sol=build_small_instance()
    with pytest.raises(ValueError):
        choose(inst,[{"label":"src","sol":sol}],arm="invention")
    with pytest.raises(ValueError):
        choose(inst,[{"label":"src","sol":sol}],arm="joint_bw_cpu_48",max_exact_checks=0)
