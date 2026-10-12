"""P12 verify exact original ALNS option and final MEC repair semantics."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from run_p12_insertion_finish_audit import (
    _ranks,queue_metrics,material_queue_improvement,
    _task_counterfactual,_actual_multi_task_original_repair,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances.small import build_small_instance
from uav_mec.evaluation.validator import validate_solution


@pytest.mark.parametrize("size,cap",[(2,10),(15,12),(80,12),(80,7),(7,7)])
def test_counterfactual_rank_sampling_includes_actual_original_top_one(size,cap):
    selected=_ranks(size,cap)
    assert selected[0]==1
    assert selected[-1]==size if size>cap else selected[-1]==size
    assert len(selected)<=cap
    assert selected==sorted(set(selected))
    assert all(1<=r<=size for r in selected)


def test_full_one_task_rebuild_matches_unchanged_actual_cheapest_repair():
    inst,source=build_small_instance()
    initial_sha=content_hash(source)
    state=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(state,["S1"])
    original_options=ops._options_for_task(destroyed,"S1")
    expected=destroyed.copy()
    ops._apply_local_insertion(expected,"S1",original_options[0])
    validate_solution(inst,expected.solution)
    original_before_sha=content_hash(expected.solution)
    finished=ops._finish_repair(expected)
    validate_solution(inst,finished.solution)
    actual_cheapest=ops.cheapest_insertion_repair(
        destroyed,np.random.default_rng(17))
    assert content_hash(actual_cheapest.solution)==content_hash(finished.solution)
    assert content_hash(source)==initial_sha
    assert original_before_sha!=content_hash(destroyed.solution)


def test_original_top1_vs_sampled_finish_counterfactual_never_edits_input():
    inst,source=build_small_instance()
    frozen=content_hash(source)
    result=_task_counterfactual(
        inst,source,"S1",sample_max=5,include_strict=False)
    assert result["original_solution_sha256"]==frozen
    assert 1 in result["sampled_original_ranks"]
    assert result["original_first_rank_after_MEC"][
        "queue_necessary_pass"] in (True,False)
    assert result["queue_best_sampled_original_rank"] in result[
        "sampled_original_ranks"]
    assert len(result["sampled_positions"])<=5
    assert content_hash(source)==frozen


def test_original_multi_task_cheapest_and_regret2_are_captured_nonmutating():
    inst,source=build_small_instance()
    before=content_hash(source)
    traces=_actual_multi_task_original_repair(inst,source,808)
    assert len(traces)==2
    for label,detail in traces.items():
        assert detail["actual_removed_task_count"]>=2
        assert detail["before_MEC_rebuild"]["queue_reason_count"]>=0
        assert detail["after_MEC_rebuild"]["queue_reason_count"]>=0
        assert detail["finished_exact_original_repair_sha256"]
    assert content_hash(source)==before


def test_material_improvement_does_not_count_tiny_float_noise_or_worse_constraints():
    base={"queue_necessary_pass":False,"queue_reason_count":2,
          "total_normalized_all_constraint_excess":0.100}
    minor={**base,"total_normalized_all_constraint_excess":0.099999}
    assert not material_queue_improvement(minor,base)
    better={**base,"queue_reason_count":1}
    assert material_queue_improvement(better,base)
    feasible={**base,"queue_necessary_pass":True,"queue_reason_count":0}
    assert material_queue_improvement(feasible,base)
