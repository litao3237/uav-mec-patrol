"""P22 exchange must preserve frozen D and really move two tasks across UAVs."""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_p22_deadline_cross_uav_exchange import (
    ARMS, choose_pair_arms, one_cross_uav_exchange, owner_map,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def test_same_pair_quota_for_deadline_and_random_controls():
    inst, old = build_small_instance()
    origin = owner_map(old)
    chosen, stress, critical = choose_pair_arms(inst, old, seed=12, max_pairs=3)
    assert set(chosen) == set(ARMS)
    assert len(chosen[ARMS[0]]) == len(chosen[ARMS[1]]) == 3
    assert len(critical) == 3
    assert set(stress) == set(inst.tasks)
    for pairs in chosen.values():
        for a, b in pairs:
            assert origin[a] != origin[b]


def test_actual_original_mec_rebuilder_after_two_task_cross_exchange():
    instance, solution = build_small_instance()
    sha = content_hash(solution)
    owners = owner_map(solution)
    outcome, completed = one_cross_uav_exchange(
        instance, solution, owners, ("S1", "S4")
    )
    validate_solution(instance, completed)
    assert outcome["finished_D_sha"] == content_hash(completed)
    assert content_hash(completed) != sha
    assert content_hash(solution) == sha
    now = owner_map(completed)
    assert now["S1"] == "U2"
    assert now["S4"] == "U1"
    assert set(now) == set(owners)
