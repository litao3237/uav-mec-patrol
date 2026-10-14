"""P31 original-ESI ALNS matched clock and first-use paper-scale experiment.

The five preregistered arms use the same source instance/initial D and
original 3 destroy / 2 repair slots, RRT, screened proxy, exact original
Stage1+Stage2 and independent read-only trajectory observer.
When enabled, only the original repair results are optionally altered by
the bounded P31 after-repair local and alternate-existing-contact moves.
Sham executes IDENTICAL P31 diagnostic work and always returns original D.
B explore 6s + elite 2s are soft per-phase bounds, NOT an 8s complete cap.
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

from p31_binding_aware_repair import (
    P31Counters, P31Limits, POLICIES, make_repair_list,
)
from run_model_sensitivity import (
    PROFILES, make_profile, shared_task_geometry_hash, describe_instance,
)
from run_p7_alns_shadow_archive import ShadowPrecheckArchive
from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator, Stage1CVXObjectiveOracle,
    UavMecALNSConfig, build_greedy_initial_solution,
    build_mec_assisted_initial_solution, run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns import runner as alns_runner
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, write_json,
)
from uav_mec.instances import (
    build_paper_scale_instance, load_paper_scale_config,
)

ARMS=("original",)+POLICIES
SCENES=(135,136,137,138)
SCALES=(30,50,80)
PHYSICAL_PROFILES=("baseline","compute_x1p5","deadline_x0p9")
ALGORITHM_SEEDS=(191,)
EXPLORATION_S=6.0
ELITE_S=2.0
SOURCE_CONFIG=Path("configs/baseline.yaml")
LIMITS=P31Limits()


def run_arm(inst,init,seed,arm,*,exploration_s=EXPLORATION_S):
    if arm not in ARMS:raise ValueError(arm)
    frozen_initial=content_hash(init)
    counter=None if arm=="original" else P31Counters(arm)
    observer=ShadowPrecheckArchive(
        ScreenedProxyObjectiveEvaluator(),max_saved=3)
    oracle=Stage1CVXObjectiveOracle()
    scope=(
        nullcontext()
        if arm=="original"
        else patch.object(
            alns_runner,"make_repair_operators",
            return_value=make_repair_list(arm,counter,LIMITS),
        )
    )
    cfg=UavMecALNSConfig(
        iterations=100000 if exploration_s is not None else 100,
        seed=seed,enable_problem_operators=False,
        max_runtime_s=exploration_s,
        time_scaled_rrt=exploration_s is not None,
    )
    started=perf_counter()
    with scope:
        hybrid=run_uav_mec_hybrid_alns(
            inst,initial_solution=deepcopy(init),
            config=cfg,evaluator=observer,
            elite_rounds=2,elite_oracle=oracle,
            exploration_max_runtime_s=exploration_s,
            elite_max_runtime_s=ELITE_S if exploration_s is not None else None,
        )
    search_wall=perf_counter()-started
    if content_hash(init)!=frozen_initial:
        raise RuntimeError("P31 changed original shared initial D")
    strict={}
    audit_wall=0.
    for label,solution in (
        ("B",hybrid.exploration.best_solution),
        ("ESI",hybrid.best_solution),
    ):
        output=finalize(
            inst,solution,method=f"P31_{arm}_{label}",
            seed=seed,initialization_s=0.,search_s=search_wall,
            diagnostics={"source":"P31 frozen unchanged original Stage1+Stage2"},
        )
        accepted=bool(
            output["stage1"]["qualified"] and output["stage2"]["qualified"]
        )
        time=float(
            output["timing"]["resource_recompute_s"]+
            output["timing"]["independent_audit_s"]
        )
        audit_wall+=time
        strict[label]={
            "sha256":content_hash(solution),
            "strict_both":accepted,
            "stage1_strict":bool(output["stage1"]["qualified"]),
            "stage2_strict":bool(output["stage2"]["qualified"]),
            "stage1_status":output["resources"].diagnostics.get(
                "stage1_status"),
            "energy_j":(
                float(output["resources"].energy_stage1_j)
                if accepted else None
            ),
            "original_full_resource_audit_wall_s":time,
        }
    stats=getattr(
        hybrid.exploration.raw_result.statistics,"objectives",[])
    return {
        "arm":arm,**strict,
        "B_iterations":max(0,len(stats)-1),
        "B_unique_D":observer.summary()["counters"].get("unique_generated",0),
        "read_only_funnel":observer.summary(),
        "postrepair":counter.snapshot() if counter else None,
        "B_exploration_wall_s":hybrid.exploration_runtime_s,
        "ESI_elite_wall_s":hybrid.elite_phase_runtime_s,
        "search_wall_s":search_wall,
        "strict_audit_wall_s":audit_wall,
        "complete_run_wall_s":search_wall+audit_wall,
        "elite_CVX_calls":oracle.calls,
        "elite_skipped":hybrid.elite_stats.get("skipped"),
        "budget_matched_exploration":exploration_s is not None,
    }


def run_block(scene:int,scale:int,output:Path):
    if scene not in SCENES or scale not in SCALES:
        raise ValueError("Not preregistered independent P31 physical layout/scale")
    if output.exists():
        raise FileExistsError("Do not overwrite original scientific P31 archive")
    cfg=load_paper_scale_config(SOURCE_CONFIG)
    base=build_paper_scale_instance(
        cfg,num_tasks=scale,num_uavs=5,num_mecs=2,scenario_seed=scene)
    original_sha=content_hash(base)
    geometry=shared_task_geometry_hash(base)
    result={
        "complete":False,
        "protocol":{
            "id":"P31_original_ALNS_MEC_cross_UAV_binding_CPU_BW_firstuse_v1",
            "independent_spatial_scene":scene,
            "paper_task_scale":scale,
            "all_firstuse_scenes":list(SCENES),
            "all_paper_task_scales":list(SCALES),
            "profiles":list(PHYSICAL_PROFILES),
            "nested_algorithm_seeds":list(ALGORITHM_SEEDS),
            "arms":list(ARMS),
            "postrepair_limits":LIMITS.__dict__,
            "original_greedy_full_MEC_builder_per_repair":1,
            "unchanged_original_operators_roulette_RRT_and_objective":True,
            "identical_initial_D_and_nested_seed_each_arm":True,
            "P31_same_full_candidate_pool_and_readonly_diagnostics_each_ablation":True,
            "P31_no_extra_CVX_during_candidate_ranking":True,
            "original_P1R_strict_Stage1_Stage2_unchanged":True,
            "B_exploration_wall_budget_s":EXPLORATION_S,
            "ESI_elite_wall_budget_s":ELITE_S,
            "not_a_hard_complete_8second_wall_deadline":True,
            "scene_count_is_independent_seed_not_nested_rows":True,
            "not_claiming_statistical_significance_with_only_four_scenes":True,
            "original_base_sha":original_sha,
            "original_geometry_sha":geometry,
            "config_sha":sha256(SOURCE_CONFIG.read_bytes()).hexdigest(),
        },
        "profiles":{}, "rows":[], "errors":[],
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    write_json(output,result)
    for profile in PHYSICAL_PROFILES:
        inst=make_profile(base,profile)
        if content_hash(base)!=original_sha or (
            shared_task_geometry_hash(inst)!=geometry
        ):
            raise RuntimeError("P31 profile changed frozen base/spatial geometry")
        result["profiles"][profile]={
            "instance_sha":content_hash(inst),
            "geometry_sha":geometry,
            "factor":PROFILES[profile][0],
            "multiplier":PROFILES[profile][1],
            "description":describe_instance(
                inst,configured_fastest_cpu=max(
                    p.cpu_ghz for p in cfg.mec_sites
                )
            ),
        }
        write_json(output,result)
        for seed in ALGORITHM_SEEDS:
            init_t=perf_counter()
            initial=build_mec_assisted_initial_solution(
                inst,base_solution=build_greedy_initial_solution(inst)
            )
            initialization_s=perf_counter()-init_t
            frozen_initial=content_hash(initial)
            row={
                "scene":scene,"scale":scale,"profile":profile,
                "seed":seed,"shared_initial_SHA":frozen_initial,
                "shared_initial_wall_s":initialization_s,"arms":{},
            }
            result["rows"].append(row)
            write_json(output,result)
            for arm in ARMS:
                try:
                    observed=run_arm(inst,initial,seed,arm)
                    if content_hash(initial)!=frozen_initial:
                        raise RuntimeError("P31 arm modified original initial D")
                    observed["true_complete_with_initialization_s"]=(
                        observed["complete_run_wall_s"]+initialization_s
                    )
                    row["arms"][arm]=observed
                    print("P31_HOLDOUT_CASE="+json.dumps({
                        "scene":scene,"scale":scale,"profile":profile,
                        "seed":seed,"arm":arm,
                        "B_strict":observed["B"]["strict_both"],
                        "ESI_strict":observed["ESI"]["strict_both"],
                        "ESI_energy_J":observed["ESI"]["energy_j"],
                        "B_iterations":observed["B_iterations"],
                        "joint_gate_generated":observed["read_only_funnel"][
                            "counters"].get("joint_bw_cpu_necessary_pass",0),
                        "P31_chosen_moves":(
                            (observed["postrepair"] or {}).get("chosen_other_D",0)
                        ),
                        "true_whole_wall_s":round(
                            observed["true_complete_with_initialization_s"],3
                        ),
                    },ensure_ascii=False),flush=True)
                except Exception as exc:
                    error={
                        "scene":scene,"scale":scale,"profile":profile,
                        "seed":seed,"arm":arm,
                        "type":type(exc).__name__,"message":str(exc),
                    }
                    result["errors"].append(error)
                    row["arms"][arm]={"error":error}
                    print("P31_HOLDOUT_ERROR="+json.dumps(error),flush=True)
                write_json(output,result)
    result["complete"]=True
    result["summary"]={
        "physical_scene":scene,"scale":scale,
        "matched_rows":len(result["rows"]),
        "strict_ESI_by_arm":{
            arm:sum(bool(r["arms"].get(arm,{}).get(
                "ESI",{}).get("strict_both"))
                for r in result["rows"])
            for arm in ARMS
        },
        "errors":len(result["errors"]),
    }
    write_json(output,result)
    print("P31_HOLDOUT_BLOCK="+json.dumps(result["summary"]),flush=True)
    if result["errors"]:
        raise RuntimeError("P31 incomplete original holdout: "+str(result["errors"][:2]))
    return result


def replay_seen(source:Path,out:Path,cases):
    if out.exists():raise FileExistsError(out)
    raw=json.loads(source.read_text(encoding="utf-8"))
    scene=int(raw["protocol"]["independent_scenario_seed"])
    if scene not in (91,93) or not raw.get("complete"):
        raise ValueError("Frozen inspected P3/P5 source required")
    chosen=[(p,int(s)) for p,s in cases]
    rows={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    r={
        "complete":False,"scene":scene,
        "already_seen_development_only":True,
        "same_100_iterations_not_equal_wall":True,
        "rows":[],"errors":[],
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    write_json(out,r)
    for profile,seed in chosen:
        inst=restore_instance(raw["profiles"][profile]["instance"])
        if content_hash(inst)!=raw["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Frozen old physical case changed")
        initial=build_mec_assisted_initial_solution(
            inst,base_solution=build_greedy_initial_solution(inst))
        expected=rows[profile,seed,"B-ALNS"]["solution_sha256"]
        old={"profile":profile,"seed":seed,"expected_B_SHA":expected,"arms":{}}
        r["rows"].append(old)
        write_json(out,r)
        for arm in ARMS:
            obs=run_arm(inst,initial,seed,arm,exploration_s=None)
            old["arms"][arm]={
                "B_SHA":obs["B"]["sha256"],
                "B_strict":obs["B"]["strict_both"],
                "ESI_strict":obs["ESI"]["strict_both"],
                "B_steps":obs["B_iterations"],
                "postrepair":obs["postrepair"],
                "total_wall_s":obs["complete_run_wall_s"],
            }
            if arm in ("original","sham") and (
                obs["B"]["sha256"] != expected
            ):
                r["errors"].append({
                    "profile":profile,"seed":seed,"arm":arm,
                    "message":"Original/sham lost frozen original B endpoint SHA",
                })
            write_json(out,r)
            print("P31_DEVELOPMENT_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "arm":arm,"B_exact_old_SHA":obs["B"]["sha256"]==expected,
                "B_strict":obs["B"]["strict_both"],
                "ESI_strict":obs["ESI"]["strict_both"],
                "postrepair":(
                    (obs["postrepair"] or {}).get("chosen_other_D",0)
                ),
            },ensure_ascii=False),flush=True)
    r["complete"]=True
    write_json(out,r)
    if r["errors"]:
        raise RuntimeError("P31 old replay identity fail: "+str(r["errors"]))
    return r


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="action",required=True)
    hold=sub.add_parser("firstuse")
    hold.add_argument("--scene",type=int,required=True)
    hold.add_argument("--scale",type=int,required=True)
    hold.add_argument("--output",type=Path,required=True)
    dev=sub.add_parser("development")
    dev.add_argument("--source",type=Path,required=True)
    dev.add_argument("--cases",required=True)
    dev.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.action=="firstuse":run_block(a.scene,a.scale,a.output)
    else:replay_seen(a.source,a.output,[x.split(":") for x in a.cases.split(",")])
