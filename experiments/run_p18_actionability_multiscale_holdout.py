"""P18 SECOND independent multiscale holdout for unchanged P17 algorithm.

No new mechanism, score, thresholds, repair operators or resource
constraints. This is the EXACT P17 proxy_actionable algorithm from
S121-S124 first-use, untouched, now tested on NEW spatial scenes
S125-S130 and two official paper task scales K50 and K80.

Same original B/ESI fixed search clock (6 seconds) and ESI elite
clock (2 seconds) at BOTH K50 and K80. 3 paired physical profiles:
baseline, compute_x1p5, deadline_x0p9. Two NESTED stochastic seeds
173/174. Four arms: original, exact-cost proxy_sham,
critical-pool-only proxy_critical, proxy_actionable. These are
pre-registered BEFORE viewing S125-S130 outcomes.

6 independent spatial scene seeds; K50 vs K80 in a given scene seed
share randomness and should be treated as correlated groups; algorithm
seeds are nested and NOT 6*2*3*2 independent spatial layouts.

Post-search Stage1/Stage2 independent resource qualification may run
beyond exploration clock, so record actual end-to-end wall time and
don't mistake nominal 6+2 seconds for absolute complete hard timeout.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from run_p17_actual_alns_pilot import (
    ARMS as ORIGINAL_P17_ARMS,run_arm,
)
from run_model_sensitivity import (
    PROFILES,make_profile,shared_task_geometry_hash,describe_instance,
)
from uav_mec.algorithms import (
    build_greedy_initial_solution,build_mec_assisted_initial_solution,
)
from uav_mec.analysis.experiment_snapshot import content_hash,write_json
from uav_mec.instances import (
    build_paper_scale_instance,load_paper_scale_config,
)

FROZEN_SCENES=(125,126,127,128,129,130)
SCALES=(50,80)
ALGORITHM_SEEDS=(173,174)
PROFILES_TO_RUN=("baseline","compute_x1p5","deadline_x0p9")
ARMS=("original","proxy_sham","proxy_critical","proxy_actionable")
assert set(ARMS).issubset(set(ORIGINAL_P17_ARMS))
SOURCE_CONFIG=Path("configs/baseline.yaml")
EXPLORATION_CLOCK_S=6.0
ELITE_CLOCK_S=2.0


def run(scene:int,tasks:int,output_dir:Path):
    if scene not in FROZEN_SCENES or tasks not in SCALES:
        raise ValueError("Only preregistered 6 S125-S130 scenes and K50/K80")
    if output_dir.exists() and list(output_dir.iterdir()):
        raise FileExistsError("Original scientific experiment evidence must not be overwritten")
    output_dir.mkdir(parents=True,exist_ok=True)
    output=output_dir/f"p18-multiscale-K{tasks}_S{scene}.json"

    cfg=load_paper_scale_config(SOURCE_CONFIG)
    base=build_paper_scale_instance(
        cfg,num_tasks=tasks,num_uavs=5,num_mecs=2,
        scenario_seed=scene,
    )
    frozen_base=content_hash(base)
    frozen_geometry=shared_task_geometry_hash(base)
    result={
        "complete":False,
        "protocol":{
            "id":"P18_P17_unmodified_MEC_actionability_second_new_multiscale_holdout_v1",
            "scene":scene,"tasks":tasks,
            "independent_spatial_scenes":list(FROZEN_SCENES),
            "paired_paper_task_scales":list(SCALES),
            "physical_stress_profiles":list(PROFILES_TO_RUN),
            "nested_algorithm_seeds":list(ALGORITHM_SEEDS),
            "arms":list(ARMS),
            "original_P17_proxy_actionable_code_unmodified":True,
            "same_original_ALNS_destroy_repair_RRT_and_reward":True,
            "original_ScreenedProxy_objective_and_P1R_unchanged":True,
            "same_initial_source_state_and_nested_seed":True,
            "original_B_exploration_max_runtime_s":EXPLORATION_CLOCK_S,
            "original_ESI_elite_max_runtime_s":ELITE_CLOCK_S,
            "original_Stage1_Stage2_full_residual_acceptance":True,
            "real_search_and_uninterruptible_solver_overruns_recorded":True,
            "not_strict_total_8second_hard_wall_budget":True,
            "nested_seeds_and_task_scales_not_independent_scene_replicates":True,
            "original_base_SHA256":frozen_base,
            "original_geometry_SHA256":frozen_geometry,
            "config_SHA256":sha256(SOURCE_CONFIG.read_bytes()).hexdigest(),
        },
        "profiles":{},"rows":[],"errors":[],
    }
    write_json(output,result)
    for profile in PROFILES_TO_RUN:
        inst=make_profile(base,profile)
        if content_hash(base)!=frozen_base:
            raise RuntimeError("Original paper-scale physical scene mutated")
        if shared_task_geometry_hash(inst)!=frozen_geometry:
            raise RuntimeError("Paired original physical geometry differs by method")
        result["profiles"][profile]={
            "instance_sha256":content_hash(inst),
            "geometry_sha256":frozen_geometry,
            "factor":PROFILES[profile][0],
            "multiplier":PROFILES[profile][1],
            "original_instance_summary":describe_instance(
                inst,configured_fastest_cpu=max(
                    mec.cpu_ghz for mec in cfg.mec_sites)),
        }
        write_json(output,result)
        for seed in ALGORITHM_SEEDS:
            initialized=perf_counter()
            initial=build_mec_assisted_initial_solution(
                inst,base_solution=build_greedy_initial_solution(inst))
            initialization_s=perf_counter()-initialized
            source_sha=content_hash(initial)
            row={
                "scene":scene,"tasks":tasks,"profile":profile,"seed":seed,
                "initial_solution_sha256":source_sha,
                "shared_initialization_wall_s":initialization_s,
                "arms":{},
            }
            result["rows"].append(row)
            write_json(output,result)
            for arm in ARMS:
                try:
                    found=run_arm(
                        inst,initial,seed,arm,
                        clock_budget_s=EXPLORATION_CLOCK_S)
                    if content_hash(initial)!=source_sha:
                        raise RuntimeError("Frozen shared initial D mutated by P18")
                    found["true_end_to_end_wall_s"]=(
                        initialization_s+found["complete_run_wall_s"])
                    found["shared_initialization_wall_s"]=initialization_s
                    row["arms"][arm]=found
                    print("P18_MULTISCALE_CASE="+json.dumps({
                        "scene":scene,"tasks":tasks,"profile":profile,
                        "seed":seed,"arm":arm,
                        "strict_B":found["B"]["strict_both"],
                        "strict_ESI":found["ESI"]["strict_both"],
                        "energy_J":found["ESI"]["energy_j"],
                        "iterations":found["B_search_iterations"],
                        "queue_pass":found["read_only_funnel"]["counters"].get(
                            "queue_necessary_pass",0),
                        "joint_pass":found["read_only_funnel"]["counters"].get(
                            "joint_bw_cpu_necessary_pass",0),
                        "original_builder_count":(
                            found["preview"]["original_builder_count"]
                            if found["preview"] else None),
                        "true_wall_s":round(found["true_end_to_end_wall_s"],4),
                    },ensure_ascii=False),flush=True)
                except Exception as e:
                    issue={
                        "scene":scene,"tasks":tasks,"profile":profile,
                        "seed":seed,"arm":arm,"type":type(e).__name__,
                        "message":str(e),
                    }
                    result["errors"].append(issue)
                    row["arms"][arm]={"error":issue}
                    print("P18_MULTISCALE_ERROR="+json.dumps(issue),flush=True)
                write_json(output,result)
    result["complete"]=True
    result["summary"]={
        "matched_rows":len(result["rows"]),
        "ESI_Strict_per_arm":{
            arm:sum(bool(r["arms"].get(arm,{}).get(
                "ESI",{}).get("strict_both"))
                for r in result["rows"])
            for arm in ARMS},
        "errors":len(result["errors"]),
    }
    write_json(output,result)
    print("P18_MULTISCALE_BLOCK="+json.dumps({
        "scene":scene,"tasks":tasks,**result["summary"],
    },ensure_ascii=False),flush=True)
    if result["errors"]:
        raise RuntimeError(f"Unresolved original-scene P18 error: {result['errors'][:2]}")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene",required=True,type=int)
    p.add_argument("--tasks",required=True,type=int)
    p.add_argument("--output-dir",required=True,type=Path)
    args=p.parse_args()
    run(args.scene,args.tasks,args.output_dir)
