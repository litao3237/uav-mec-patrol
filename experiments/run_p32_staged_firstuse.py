"""P32 preregistered first-use real ESI-ALNS stage-gated repair S139-S142.

All P31 S135-S138 are already analyzed and EXCLUDED from all first-use
claims. P32 uses exactly four new physical spatial scene seeds, three
paper K scales, three nested compute/deadline profiles and one paired
algorithm seed; six complete original ALNS arm runs per physical block.

Original ALNS, greedy 1x MEC builder, 6-second B exploration / 2-second
ESI elite clocks, screened proxy, RRT roulette, Stage1 and independent
Stage2 acceptance unchanged. P31 queue-only is rerun as an ablation on
the same scene/seed, not copied from the different prior holdout.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from p32_staged_queue_repair import (
    POLICIES,P32Counters,LIMITS,make_repair_list,
)
from run_model_sensitivity import (
    PROFILES,make_profile,shared_task_geometry_hash,describe_instance,
)
from run_p31_binding_alns_holdout import run_arm as p31_run_arm
from run_p7_alns_shadow_archive import ShadowPrecheckArchive
from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
    UavMecALNSConfig,build_greedy_initial_solution,
    build_mec_assisted_initial_solution,run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns import runner as alns_runner
from uav_mec.analysis.experiment_snapshot import content_hash,write_json
from uav_mec.instances import (
    build_paper_scale_instance,load_paper_scale_config,
)

ARMS=("original","p31_queue_only")+POLICIES
SCENES=(139,140,141,142)
SCALES=(30,50,80)
PHYSICAL_PROFILES=("baseline","compute_x1p5","deadline_x0p9")
SEEDS=(191,)
B_EXPLORATION_S=6.0
ESI_ELITE_S=2.0
CONFIG_PATH=Path("configs/baseline.yaml")


def run_one(inst,initial,seed,arm):
    if arm=="original":
        ans=p31_run_arm(inst,initial,seed,"original")
        ans["arm"]="original"
        return ans
    if arm=="p31_queue_only":
        ans=p31_run_arm(inst,initial,seed,"queue_only")
        ans["arm"]="p31_queue_only"
        ans["reference_operator"]="unmodified P31 queue_only"
        return ans
    if arm not in POLICIES:raise ValueError(arm)
    init_sha=content_hash(initial)
    counter=P32Counters(arm)
    observer=ShadowPrecheckArchive(
        ScreenedProxyObjectiveEvaluator(),max_saved=3
    )
    oracle=Stage1CVXObjectiveOracle()
    cfg=UavMecALNSConfig(
        iterations=100000,
        seed=seed,
        enable_problem_operators=False,
        max_runtime_s=B_EXPLORATION_S,
        time_scaled_rrt=True,
    )
    repair_list=make_repair_list(arm,counter,LIMITS)
    tic=perf_counter()
    with patch.object(
        alns_runner,"make_repair_operators",return_value=repair_list
    ):
        result=run_uav_mec_hybrid_alns(
            inst,
            initial_solution=deepcopy(initial),
            config=cfg,
            evaluator=observer,
            elite_rounds=2,
            elite_oracle=oracle,
            exploration_max_runtime_s=B_EXPLORATION_S,
            elite_max_runtime_s=ESI_ELITE_S,
        )
    elapsed=perf_counter()-tic
    if content_hash(initial)!=init_sha:
        raise RuntimeError("P32 modified common original initial D")
    strict={}
    audittime=0.
    for name,solution in (
        ("B",result.exploration.best_solution),
        ("ESI",result.best_solution),
    ):
        done=finalize(
            inst,solution,method=f"P32_{arm}_{name}",
            seed=seed,initialization_s=0.,search_s=elapsed,
            diagnostics={"source":"unchanged original P1R strict stage1+stage2"},
        )
        accepted=bool(
            done["stage1"]["qualified"] and done["stage2"]["qualified"]
        )
        elapsed_audit=float(
            done["timing"]["resource_recompute_s"]+
            done["timing"]["independent_audit_s"]
        )
        audittime+=elapsed_audit
        strict[name]={
            "sha256":content_hash(solution),
            "strict_both":accepted,
            "stage1_strict":bool(done["stage1"]["qualified"]),
            "stage2_strict":bool(done["stage2"]["qualified"]),
            "stage1_status":done["resources"].diagnostics.get("stage1_status"),
            "energy_j":(
                float(done["resources"].energy_stage1_j) if accepted else None
            ),
            "original_full_resource_audit_wall_s":elapsed_audit,
        }
    st=getattr(result.exploration.raw_result.statistics,"objectives",[])
    return {
        "arm":arm,**strict,
        "B_iterations":max(0,len(st)-1),
        "B_unique_D":observer.summary()["counters"].get("unique_generated",0),
        "read_only_funnel":observer.summary(),
        "postrepair":counter.snapshot(),
        "B_exploration_wall_s":result.exploration_runtime_s,
        "ESI_elite_wall_s":result.elite_phase_runtime_s,
        "search_wall_s":elapsed,
        "strict_audit_wall_s":audittime,
        "complete_run_wall_s":elapsed+audittime,
        "elite_CVX_calls":oracle.calls,
        "elite_skipped":result.elite_stats.get("skipped"),
        "budget_matched_exploration":True,
    }


def run_block(scene:int,scale:int,output:Path):
    if scene not in SCENES or scale not in SCALES:
        raise ValueError("P32 only sealed S139-S142 K30/K50/K80 first-use")
    if output.exists():
        raise FileExistsError("Never overwrite scientific P32 source evidence")
    cfg=load_paper_scale_config(CONFIG_PATH)
    base=build_paper_scale_instance(
        cfg,num_tasks=scale,num_uavs=5,num_mecs=2,scenario_seed=scene
    )
    original_base_sha=content_hash(base)
    geometry=shared_task_geometry_hash(base)
    data={
        "complete":False,
        "protocol":{
            "id":"P32_staged_queue_CPU_joint_mec_gate_firstuse_v1",
            "independent_spatial_scene":scene,
            "task_scale":scale,
            "all_new_spatial_scenes":list(SCENES),
            "all_task_scales":list(SCALES),
            "physical_profiles":list(PHYSICAL_PROFILES),
            "algorithm_seeds_nested":list(SEEDS),
            "arms":list(ARMS),
            "P32_limits":LIMITS.__dict__,
            "joint_screen_max":8,
            "only_after_queue_cpu_positive":True,
            "sham_joint_exact_staged_screen_but_no_D_change":True,
            "P31_queue_only_reference_unmodified":True,
            "preexisting_P31_S135_S138_not_firstuse":True,
            "original_full_MEC_greedy_builder_once_per_ALNS_repair":True,
            "original_ALNS_destroy_roulette_RRT_proxy_and_elite":True,
            "same_shared_original_initial_D_and_seed":True,
            "original_MEC_hardware_physical_model_and_strict_residuals":True,
            "B_exploration_clock_s":B_EXPLORATION_S,
            "ESI_elite_clock_s":ESI_ELITE_S,
            "total_complete_wall_hard_8_second_limit":False,
            "algorithm_results_not_independent_per_profile":True,
            "realistic_independent_sample_size_spatial_scenes":len(SCENES),
            "original_physical_SHA":original_base_sha,
            "common_task_geometry_SHA":geometry,
            "baseline_config_sha":sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        },
        "profiles":{},"rows":[],"errors":[],
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    write_json(output,data)
    for profile in PHYSICAL_PROFILES:
        inst=make_profile(base,profile)
        if (
            content_hash(base)!=original_base_sha
            or shared_task_geometry_hash(inst)!=geometry
        ):
            raise RuntimeError("P32 changed fixed physical source geometry")
        data["profiles"][profile]={
            "instance_sha":content_hash(inst),
            "geometry_sha":geometry,
            "factor":PROFILES[profile][0],
            "multiplier":PROFILES[profile][1],
            "description":describe_instance(
                inst,configured_fastest_cpu=max(
                    mec.cpu_ghz for mec in cfg.mec_sites
                ),
            ),
        }
        write_json(output,data)
        for seed in SEEDS:
            t0=perf_counter()
            initial=build_mec_assisted_initial_solution(
                inst,base_solution=build_greedy_initial_solution(inst)
            )
            initialization_wall=perf_counter()-t0
            init_sha=content_hash(initial)
            row={
                "scene":scene,"scale":scale,"profile":profile,"seed":seed,
                "shared_initial_SHA":init_sha,
                "shared_initial_wall_s":initialization_wall,
                "arms":{},
            }
            data["rows"].append(row)
            write_json(output,data)
            for arm in ARMS:
                try:
                    results=run_one(inst,initial,seed,arm)
                    if content_hash(initial)!=init_sha:
                        raise RuntimeError("ALNS mutated original matched seed D")
                    results["true_complete_with_initialization_s"]=(
                        results["complete_run_wall_s"]+initialization_wall
                    )
                    row["arms"][arm]=results
                    print("P32_STAGED_CASE="+json.dumps({
                        "scene":scene,"scale":scale,"profile":profile,
                        "seed":seed,"arm":arm,
                        "B_strict":results["B"]["strict_both"],
                        "ESI_strict":results["ESI"]["strict_both"],
                        "ESI_energy_j":results["ESI"]["energy_j"],
                        "B_iterations":results["B_iterations"],
                        "chosen_cross_UAV":(
                            (results["postrepair"] or {}).get("chosen_other_D",0)
                        ),
                        "joint_BW_CPU_cheap_checks":(
                            (results["postrepair"] or {}).get("joint_bound_calls",0)
                        ),
                        "true_complete_wall_s":round(
                            results["true_complete_with_initialization_s"],3
                        ),
                    },ensure_ascii=False),flush=True)
                except Exception as exc:
                    error={
                        "scene":scene,"scale":scale,"profile":profile,
                        "seed":seed,"arm":arm,
                        "type":type(exc).__name__,"message":str(exc),
                    }
                    data["errors"].append(error)
                    row["arms"][arm]={"error":error}
                    print("P32_STAGED_ERROR="+json.dumps(error),flush=True)
                write_json(output,data)
    data["complete"]=True
    data["summary"]={
        "scene":scene,"scale":scale,
        "paired_profiles":len(data["rows"]),
        "full_Stage1_Stage2_strict":{
            arm:sum(bool(r["arms"].get(arm,{}).get(
                "ESI",{}).get("strict_both",False))
            for r in data["rows"])
            for arm in ARMS
        },
        "errors":len(data["errors"]),
    }
    write_json(output,data)
    print("P32_STAGED_BLOCK="+json.dumps(data["summary"]),flush=True)
    if data["errors"]:
        raise RuntimeError("P32 incomplete original physics source: "+str(data["errors"][:3]))
    return data


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scene",type=int,required=True)
    cli.add_argument("--scale",type=int,required=True)
    cli.add_argument("--output",type=Path,required=True)
    a=cli.parse_args()
    run_block(a.scene,a.scale,a.output)
