"""P18 FIRST-USE S125–S128 K30/K50/K80 MEC actionability robustness with matched ALNS 6s+2s clocks.

Frozen arms: original, proxy_sham, proxy_contact, proxy_critical,
proxy_actionable. One original MEC builder per repair, without extra CVX for scoring. Freeze ALL policies, physical profiles and seeds BEFORE
seeing any S125–S128 result. Previous S89–S124 already inspected.

Every arm receives an identical initial discrete source, original
destroy/repair operator COUNT, original ScreenedProxy objective,
roulette/RRT, original P1-R CVX/Stage1/Stage2 and an identical read-only
feasibility observer. Preview changes only final task positioning in
the two original repair operators. Each B-ALNS exploration has a 6s
clock budget and ESI elite phase at most 2s. These are NOT hard
end-to-end 8s deadlines: conic solves and final independent Stage1+2
validation can overrun, so record real total wall time and quality.

Samples: four independent physical spatial scenarios; five single
factor pressure settings each; algorithm seeds are NESTED repeats.
Do not call 40 paired rows independent physical cases.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from run_p17_actual_alns_pilot import ARMS,run_arm
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

NEW_SCENES=(125,126,127,128)
NESTED_ALGORITHM_SEEDS=(173,174)
PROFILES_TO_RUN=("baseline","compute_x1p5","deadline_x0p9")
SCALES=(30,50,80)
P18_ARMS=("original","proxy_sham","proxy_actionable")
SOURCE_CONFIG=Path("configs/baseline.yaml")
EXPLORATION_BUDGET_S=6.0
ELITE_BUDGET_S=2.0


def run(scene,scale:int,output_dir:Path):
    if scene not in NEW_SCENES or scale not in SCALES:
        raise ValueError("Only frozen first-use S125-S128 and K30/K50/K80 physical scenarios")
    if output_dir.exists() and list(output_dir.iterdir()):
        raise FileExistsError("Never overwrite first-use P17 source outcomes")
    output_dir.mkdir(parents=True,exist_ok=True)
    output=output_dir/f"p18-firstuse-K{scale}_S{scene}.json"

    cfg=load_paper_scale_config(SOURCE_CONFIG)
    base=build_paper_scale_instance(
        cfg,num_tasks=scale,num_uavs=5,num_mecs=2,scenario_seed=scene)
    base_sha=content_hash(base)
    geometry_sha=shared_task_geometry_hash(base)
    results={
        "complete":False,
        "protocol":{
            "id":"P18_multiscale_firstuse_original_MEC_actionability_K30_K50_K80_S125_S128_v1",
            "scenario":scene,
            "scale":scale,
            "scale_tasks":scale,
            "preregistered_independent_scene_ids":list(NEW_SCENES),
            "nested_algorithm_seeds":list(NESTED_ALGORITHM_SEEDS),
            "physical_stress_profiles":list(PROFILES_TO_RUN),
            "all_frozen_scales":list(SCALES),
            "only_three_predeclared_methods":True,
            "methods":list(P18_ARMS),
            "identical_initial_solution_per_physical_seed":True,
            "original_operator_names_number_RRT_destroy_unchanged":True,
            "original_ScreenedProxy_CVX_Physics_unchanged":True,
            "top3_final_insertion_preview_capped":True,
            "original_MEC_critical8_and_strict_ProxyScore_improvement_only":True,
            "full_original_MEC_build_once_per_original_repair":True,
            "original_proxy_only_no_extra_CVX_for_candidate_ranking":True,
            "original_B_exploration_clock_s":EXPLORATION_BUDGET_S,
            "original_ESI_elite_clock_s":ELITE_BUDGET_S,
            "original_Stage1_Stage2_strict_reaudit":True,
            "same_readonly_necessary_funnel_all_arms":True,
            "actual_complete_wall_s_includes_independent_final_CVX":True,
            "strict_hard_8second_end_to_end":False,
            "nested_seeds_not_independent_physical_scenarios":True,
            "physical_source_sha256":base_sha,
            "physical_geometry_sha256":geometry_sha,
            "config_sha256":sha256(SOURCE_CONFIG.read_bytes()).hexdigest(),
        },
        "profiles":{},"rows":[],"errors":[],
    }
    write_json(output,results)
    for profile in PROFILES_TO_RUN:
        inst=make_profile(base,profile)
        if content_hash(base)!=base_sha:
            raise RuntimeError("Original physical source instance mutated")
        if shared_task_geometry_hash(inst)!=geometry_sha:
            raise RuntimeError("Paired task geometry drift")
        results["profiles"][profile]={
            "instance_sha256":content_hash(inst),
            "geometry_sha256":geometry_sha,
            "factor":PROFILES[profile][0],
            "multiplier":PROFILES[profile][1],
            "description":describe_instance(
                inst,configured_fastest_cpu=max(
                    x.cpu_ghz for x in cfg.mec_sites)),
        }
        write_json(output,results)
        for seed in NESTED_ALGORITHM_SEEDS:
            init_start=perf_counter()
            initial=build_mec_assisted_initial_solution(
                inst,base_solution=build_greedy_initial_solution(inst))
            initialization_s=perf_counter()-init_start
            source_sha=content_hash(initial)
            row={
                "scene":scene,"scale":scale,"profile":profile,"seed":seed,
                "original_initial_sha256":source_sha,
                "shared_initialization_wall_s":initialization_s,
                "arms":{},
            }
            results["rows"].append(row)
            write_json(output,results)
            for arm in P18_ARMS:
                try:
                    evaluation=run_arm(
                        inst,initial,seed,arm,
                        clock_budget_s=EXPLORATION_BUDGET_S)
                    if content_hash(initial)!=source_sha:
                        raise RuntimeError("Modified paired initial discrete source")
                    evaluation["original_shared_initialization_wall_s"]=initialization_s
                    evaluation["true_end_to_end_wall_s"]=(
                        initialization_s+evaluation["complete_run_wall_s"])
                    row["arms"][arm]=evaluation
                    print("P18_FIRSTUSE_CASE="+json.dumps({
                        "scene":scene,"scale":scale,"profile":profile,"seed":seed,
                        "arm":arm,
                        "B_Strict":evaluation["B"]["strict_both"],
                        "ESI_Strict":evaluation["ESI"]["strict_both"],
                        "ESI_Energy_J":evaluation["ESI"]["energy_j"],
                        "B_Iterations":evaluation["B_search_iterations"],
                        "Queue_Passing_D":evaluation["read_only_funnel"]["counters"].get(
                            "queue_necessary_pass",0),
                        "Joint_Passing_D":evaluation["read_only_funnel"]["counters"].get(
                            "joint_bw_cpu_necessary_pass",0),
                        "Preview_Count":(
                            evaluation["preview"]["cheap_previews"]
                            if evaluation["preview"] else 0),
                        "Preview_Changed_Rank1":(
                            evaluation["preview"]["selected_non_top1"]
                            if evaluation["preview"] else 0),
                        "Actual_Whole_Wall_S":round(
                            evaluation["true_end_to_end_wall_s"],3),
                    },ensure_ascii=False),flush=True)
                except Exception as err:
                    warning={
                        "scene":scene,"scale":scale,"profile":profile,"seed":seed,"arm":arm,
                        "type":type(err).__name__,"message":str(err),
                    }
                    results["errors"].append(warning)
                    row["arms"][arm]={"error":warning}
                    print("P18_FIRSTUSE_ERROR="+json.dumps(warning),flush=True)
                write_json(output,results)
    results["complete"]=True
    results["summary"]={
        "paired_rows":len(results["rows"]),
        "ESI_Stage1_Stage2_qualified":{
            arm:sum(bool(
                row["arms"].get(arm,{}).get("ESI",{}).get("strict_both"))
                for row in results["rows"])
            for arm in P18_ARMS},
        "unexpected_errors":len(results["errors"]),
    }
    write_json(output,results)
    print("P18_FIRSTUSE_SUMMARY="+json.dumps({
        "scene":scene,**results["summary"]},ensure_ascii=False),flush=True)
    if results["errors"]:
        raise RuntimeError(f"Incomplete P18 independent test: {results['errors'][:2]}")
    return results


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scenario",type=int,required=True)
    cli.add_argument("--scale",type=int,required=True,choices=SCALES)
    cli.add_argument("--output-dir",type=Path,required=True)
    options=cli.parse_args()
    run(options.scenario,options.scale,options.output_dir)
