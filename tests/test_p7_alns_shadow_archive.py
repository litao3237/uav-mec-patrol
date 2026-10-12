"""P7 shadow objective recorder must not influence the original ALNS run."""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from run_p7_alns_shadow_archive import ShadowPrecheckArchive
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,run_uav_mec_alns,UavMecALNSConfig,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.instances.small import build_small_instance


def test_shadow_returns_exact_same_objective_and_does_not_mutate_solution():
    inst,sol=build_small_instance()
    frozen=content_hash(sol)
    old=ScreenedProxyObjectiveEvaluator()
    new=ShadowPrecheckArchive(ScreenedProxyObjectiveEvaluator(),max_saved=3)
    a=old(inst,sol)
    b=new(inst,sol)
    assert a==b
    assert content_hash(sol)==frozen
    assert new.stats.calls==1
    assert new.counters["unique_generated"]==1
    assert new.counters["joint_bw_cpu_necessary_pass"]==1
    assert len(new.joint_archive)==1
    assert new(inst,sol)==a
    assert new.counters["unique_generated"]==1
    assert new.stats.calls==2


def test_identical_frozen_ALNS_trajectory_on_small_inst_with_shadow():
    inst,sol=build_small_instance()
    cfg=UavMecALNSConfig(
        iterations=3,seed=812,enable_problem_operators=False,
    )
    base=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),config=cfg,
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    wrapper=ShadowPrecheckArchive(
        ScreenedProxyObjectiveEvaluator(),max_saved=5)
    audited=run_uav_mec_alns(
        inst,initial_solution=deepcopy(sol),config=cfg,
        evaluator=wrapper,
    )
    assert content_hash(base.best_solution)==content_hash(audited.best_solution)
    assert base.best_objective==audited.best_objective
    assert wrapper.shadow_wall_s>=0
