"""P33 sealed exact P32 cpu_guard replication, disjoint S143–S146.

Do not tune/import any outcome from P32 S139-S142 as first-use.
Full 4 new spatial layouts × K30/K50/K80 × baseline/compute_x1p5/
deadline_x0p9 × two nested ALNS seeds (191, 193) × 3 matched arms =
216 original Stage1+independent Stage2 hybrid ALNS runs.

The actual P32 cpu_guard is imported and run unchanged. The new
cpu_sham executes exactly its cheap screening and hypothetical move
then returns original full-MEC repaired D, unlike P32's joint sham.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

from p33_cpu_sham_replication import run_cpu_sham
from run_p32_staged_firstuse import run_one as run_p32_one
from run_model_sensitivity import (
    PROFILES,make_profile,shared_task_geometry_hash,describe_instance,
)
from uav_mec.algorithms import (
    build_greedy_initial_solution,build_mec_assisted_initial_solution,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash,write_json,
)
from uav_mec.instances import (
    build_paper_scale_instance,load_paper_scale_config,
)

SCENES=(143,144,145,146)
SCALES=(30,50,80)
PHYSICAL_PROFILES=("baseline","compute_x1p5","deadline_x0p9")
ALGORITHM_SEEDS=(191,193)
ARMS=("original","cpu_sham","cpu_guard")
B_EXPLORATION_S=6.
ESI_ELITE_S=2.
CONFIG_PATH=Path("configs/baseline.yaml")


def run_block(scene:int,scale:int,output:Path):
    if scene not in SCENES or scale not in SCALES:
        raise ValueError("P33 accepts only preregistered S143-S146 K30 K50 K80")
    if output.exists():
        raise FileExistsError("Cannot overwrite original first-use output")
    cfg=load_paper_scale_config(CONFIG_PATH)
    physical=build_paper_scale_instance(
        cfg,num_tasks=scale,num_uavs=5,num_mecs=2,scenario_seed=scene
    )
    original_instance_sha=content_hash(physical)
    geometry_sha=shared_task_geometry_hash(physical)
    result={
        "complete":False,
        "protocol":{
            "id":"P33_exact_P32_CPU_guard_two_seed_firstuse_v1",
            "independent_spatial_scene":scene,
            "paper_task_scale":scale,
            "all_new_spatial_scenes":list(SCENES),
            "all_task_scales":list(SCALES),
            "all_physical_profiles":list(PHYSICAL_PROFILES),
            "nested_ALNS_algorithm_seeds":list(ALGORITHM_SEEDS),
            "arms":list(ARMS),
            "P32_cpu_guard_algorithm_imported_exactly_unchanged":True,
            "cpu_sham_same_queue_CPU_candidate_work_drops_only_move":True,
            "all_arm_original_builder_one_call_per_repair":True,
            "original_screened_proxy_destroy_roulette_RRT_elite":True,
            "full_original_Stage1_Stage2_saved_residual_audit":True,
            "original_MEC_CPU_BW_UAV_tasks_frozen":True,
            "S135_S142_previously_seen_and_excluded_as_firstuse":True,
            "B_exploration_clock_s":B_EXPLORATION_S,
            "elite_clock_s":ESI_ELITE_S,
            "hard_end_to_end_8s_time_limit":False,
            "nested_2_seeds_not_independent_spatial_scenes":True,
            "original_physical_sha":original_instance_sha,
            "shared_task_geometry_sha":geometry_sha,
            "config_sha":sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        },
        "profiles":{},
        "rows":[],
        "errors":[],
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    write_json(output,result)
    for profile in PHYSICAL_PROFILES:
        inst=make_profile(physical,profile)
        if (
            content_hash(physical)!=original_instance_sha
            or shared_task_geometry_hash(inst)!=geometry_sha
        ):
            raise RuntimeError("P33 physical geometry/hardware source drift")
        inst_sha=content_hash(inst)
        result["profiles"][profile]={
            "instance_sha":inst_sha,
            "geometry_sha":geometry_sha,
            "factor":PROFILES[profile][0],
            "multiplier":PROFILES[profile][1],
            "description":describe_instance(
                inst,configured_fastest_cpu=max(
                    mec.cpu_ghz for mec in cfg.mec_sites
                ),
            ),
        }
        write_json(output,result)
        for seed in ALGORITHM_SEEDS:
            start=perf_counter()
            initial=build_mec_assisted_initial_solution(
                inst,base_solution=build_greedy_initial_solution(inst)
            )
            initialization_time=perf_counter()-start
            init_sha=content_hash(initial)
            row={
                "scene":scene,"scale":scale,"profile":profile,
                "seed":seed,"shared_initial_SHA":init_sha,
                "original_source_physical_SHA":inst_sha,
                "initialization_wall_s":initialization_time,
                "arms":{},
            }
            result["rows"].append(row)
            write_json(output,result)
            for arm in ARMS:
                try:
                    if arm=="cpu_sham":
                        output_arm=run_cpu_sham(inst,initial,seed)
                    else:
                        output_arm=run_p32_one(inst,initial,seed,arm)
                    if content_hash(initial)!=init_sha:
                        raise RuntimeError("P33 modified shared original B start")
                    output_arm["true_complete_with_initialization_s"]=(
                        output_arm["complete_run_wall_s"]+
                        initialization_time
                    )
                    row["arms"][arm]=output_arm
                    print("P33_CPU_REPLICATION_CASE="+json.dumps({
                        "scene":scene,"scale":scale,"profile":profile,
                        "seed":seed,"arm":arm,
                        "B_strict":output_arm["B"]["strict_both"],
                        "ESI_strict":output_arm["ESI"]["strict_both"],
                        "strict_energy_j":output_arm["ESI"]["energy_j"],
                        "exploration_iterations":output_arm["B_iterations"],
                        "genuinely_changed_D":(
                            (output_arm["postrepair"] or {}).get("chosen_other_D",0)
                        ),
                        "hypothetical_cpu_sham_changes":(
                            (output_arm["postrepair"] or {}).get(
                                "hypothetical_selected_D",0)
                        ),
                        "full_run_wall_s":round(
                            output_arm["true_complete_with_initialization_s"],3
                        ),
                    },ensure_ascii=False),flush=True)
                except Exception as exc:
                    err={
                        "scene":scene,"scale":scale,"profile":profile,
                        "seed":seed,"arm":arm,
                        "type":type(exc).__name__,
                        "message":str(exc),
                    }
                    result["errors"].append(err)
                    row["arms"][arm]={"error":err}
                    print("P33_CPU_REPLICATION_ERROR="+json.dumps(err),flush=True)
                write_json(output,result)
    result["complete"]=True
    result["summary"]={
        "scene":scene,
        "scale":scale,
        "nested_physical_profile_algorithm_seed_n":len(result["rows"]),
        "strict_by_arm":{
            a:sum(bool(r["arms"].get(a,{}).get(
                "ESI",{}).get("strict_both"))
                for r in result["rows"])
            for a in ARMS
        },
        "errors":len(result["errors"]),
    }
    write_json(output,result)
    print("P33_CPU_REPLICATION_BLOCK="+json.dumps(
        result["summary"],ensure_ascii=False
    ),flush=True)
    if result["errors"]:
        raise RuntimeError("P33 incomplete ALNS execution: "+str(result["errors"][:3]))
    return result


if __name__=="__main__":
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--scene",type=int,required=True)
    arg.add_argument("--scale",type=int,required=True)
    arg.add_argument("--output",type=Path,required=True)
    a=arg.parse_args()
    run_block(a.scene,a.scale,a.output)
