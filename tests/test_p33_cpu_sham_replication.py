"""P33 exact P32 CPU guard and no-change sham same original physical D."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
from p33_cpu_sham_replication import CpuShamCounters,make_cpu_sham_list
from p32_staged_queue_repair import (
    P32Counters,refine_one as p32_original_refine_one,
)
from p31_binding_aware_repair import P31Limits
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState,operators as ops
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance

SMALL=P31Limits(
    targets=2,destination_uavs=2,insertion_ranks_per_uav=1,
    alternate_contacts_per_position=1,total_candidates=5,
    joint_bw_cpu_bins=8,
)


def test_sham_returns_exact_full_MEC_builder_physical_D_and_original_builder_once():
    inst,source=build_small_instance()
    sha=content_hash(source)
    instance_sha=content_hash(inst)
    state=UavMecState(
        inst,deepcopy(source),ScreenedProxyObjectiveEvaluator()
    )
    destroyed=ops._destroy_tasks(state,["S1","S2"])
    old=ops.make_repair_operators()
    counters=CpuShamCounters("cpu_sham")
    sham=make_cpu_sham_list(counters,SMALL)
    assert [n for n,_ in sham]==[n for n,_ in old]
    for (_,old_op),(_,sham_op) in zip(old,sham):
        old_D=old_op(destroyed,np.random.default_rng(42))
        new_D=sham_op(destroyed,np.random.default_rng(42))
        validate_solution(inst,new_D.solution)
        assert content_hash(new_D.solution)==content_hash(old_D.solution)
        assert counters.chosen_other_D==0
    assert counters.calls==len(old)
    assert counters.legacy_full_builder_calls==len(old)
    assert content_hash(inst)==instance_sha
    assert content_hash(source)==sha


def test_sham_drops_hypothetical_accepted_change_without_mutating_source(monkeypatch):
    import p33_cpu_sham_replication as module
    inst,source=build_small_instance()
    start=UavMecState(inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(start,["S1","S2"])
    counters=CpuShamCounters("cpu_sham")
    reference_old=ops.make_repair_operators()[0][1](
        destroyed,np.random.default_rng(27)
    )
    reference_sha=content_hash(reference_old.solution)
    def fake_refine(full,policy,counter,limits):
        assert policy=="cpu_guard"
        counter.calls+=1
        counter.chosen_other_D+=1
        returned=full.copy()
        return returned
    monkeypatch.setattr(module.p32,"refine_one",fake_refine)
    sham=make_cpu_sham_list(counters,SMALL)[0][1]
    result=sham(destroyed,np.random.default_rng(27))
    assert content_hash(result.solution)==reference_sha
    assert counters.hypothetical_selected_D==1
    assert counters.chosen_other_D==0
    assert counters.snapshot()["hypothetical_selected_D"]==1
    assert counters.snapshot()["return_unmodified_original_repair_D"]
