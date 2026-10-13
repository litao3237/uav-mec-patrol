"""P19 fixed-destroy causal order controls, original repair SHA identities."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from run_p19_repair_order_factorial import (
    KINDS,POLICIES,_original_task_order,replay,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState,operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


@pytest.mark.parametrize("kind",KINDS)
@pytest.mark.parametrize("removed",[["S1","S2"],["S1","S2","S3"]])
def test_original_order_full_D_exactly_matches_original_production_repair(kind,removed):
    inst,sol=build_small_instance()
    before=content_hash(sol)
    base=UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
    broken=ops._destroy_tasks(base,removed)
    order=_original_task_order(broken,kind)
    assert set(order)==set(removed)
    record,new=replay(broken,kind,"original_order",order)
    orig=(ops.cheapest_insertion_repair if kind=="cheapest"
          else ops.regret2_insertion_repair)(
        broken,np.random.default_rng(28))
    assert content_hash(new)==content_hash(orig.solution)
    assert record["finished_sha"]==content_hash(orig.solution)
    assert content_hash(sol)==before


@pytest.mark.parametrize("kind",KINDS)
def test_all_factorial_arms_share_removed_set_and_complete_valid_original_D(kind):
    inst,sol=build_small_instance()
    broken=ops._destroy_tasks(
        UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator()),
        ["S1","S2","S3"])
    frozen=content_hash(broken.solution)
    original_order=_original_task_order(broken,kind)
    for policy in POLICIES:
        record,completed=replay(broken,kind,policy,original_order)
        assert set(record["order"])==set(original_order)
        assert len(record["insertions"])==len(original_order)
        assert all(x["original_option_rank"]==1
                   for x in record["insertions"][:-1])
        validate_solution(inst,completed)
        assert content_hash(broken.solution)==frozen


@pytest.mark.parametrize("kind",KINDS)
def test_reverse_is_true_intervention_and_final_rank_is_only_last_position(kind):
    inst,sol=build_small_instance()
    broken=ops._destroy_tasks(
        UavMecState(inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator()),
        ["S1","S2","S3"])
    order=_original_task_order(broken,kind)
    a,_=replay(broken,kind,"reverse_order",order)
    b,_=replay(broken,kind,"original_order_last_rank3",order)
    assert a["order"]==list(reversed(order))
    assert b["order"]==order
    assert b["insertions"][-1]["original_option_rank"]==3
    assert all(x["original_option_rank"]==1 for x in b["insertions"][:-1])
