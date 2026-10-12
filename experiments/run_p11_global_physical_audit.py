"""Read previously frozen original physical problem (not failed D) globally.

P9 S105-S108 and P10 S109-S112 HAVE ALREADY BEEN INSPECTED. This
P11 run evaluates proof-based optimistic instance-level necessary
conditions without editing/sampling ANY old discrete or numerical
results; it does NOT generate a new holdout or certify existence when
a physical scenario passes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from global_instance_lower_bounds import global_physical_necessary_bounds
from run_model_sensitivity import make_profile,shared_task_geometry_hash
from uav_mec.analysis.experiment_snapshot import content_hash,write_json
from uav_mec.instances import build_paper_scale_instance,load_paper_scale_config


PROFILES=("baseline","compute_x1p5","compute_x2p0",
          "deadline_x0p9","deadline_x0p8")
SOURCE_CONFIG=Path("configs/baseline.yaml")
DEV_SCENES=tuple(range(105,113))


def run(earlier:Path,out_path:Path):
    if out_path.exists():raise FileExistsError("Never overwrite original certificate evidence")
    prior=json.loads(earlier.read_text(encoding="utf-8"))
    scene=int(prior["protocol"]["scenario"])
    if scene not in DEV_SCENES or not prior.get("complete") or prior.get("errors"):
        raise ValueError("Expected completed, already-seen S105-S112 firstuse ALNS data")
    if list(prior["protocol"]["independent_new_physical_scenarios"]) not in (
        [105,106,107,108],[109,110,111,112],
    ):
        raise ValueError("Not the original frozen new physical scene protocol")
    cfg=load_paper_scale_config(SOURCE_CONFIG)
    base=build_paper_scale_instance(
        cfg,num_tasks=80,num_uavs=5,num_mecs=2,scenario_seed=scene)
    hashes=prior["protocol"]
    if content_hash(base)!=hashes["physical_base_sha256"]:
        raise RuntimeError("Global proof test changed original generated instance")
    geo=shared_task_geometry_hash(base)
    if geo!=hashes["physical_geometry_sha256"]:
        raise RuntimeError("Physical geometry hash mismatch")
    rows_by_profile={p:[] for p in PROFILES}
    for r in prior["rows"]:
        rows_by_profile[r["profile"]].append(r)
    result={
        "complete":False,
        "protocol":{
            "id":"P11_Global_Whole_UAV_MEC_Instance_Necessary_Bounds_v1",
            "scene":scene,
            "physical_base_sha256":hashes["physical_base_sha256"],
            "original_paired_ALNS_results_sha256":content_hash(prior),
            "already_inspected_P9_P10_data":True,
            "no_modified_discrete_search_or_physical_resources":True,
            "no_CVX_solve_or_Stage2_in_this_diagnostic":True,
            "original_Stage1_Stage2_controls_preserved":True,
            "global_necessary_failure_not_fixed_discrete_D_only":True,
            "passing_not_sufficient_for_global_feasibility":True,
            "primary_sampling_unit":"physical scenario, nested algorithm seeds",
        },
        "rows":[],"errors":[],
    }
    write_json(out_path,result)
    for profile in PROFILES:
        instance=make_profile(base,profile)
        if content_hash(instance)!=prior["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Physical stress profile SHA mismatch")
        certificate=global_physical_necessary_bounds(instance)
        old=rows_by_profile[profile]
        if len(old)!=2:raise RuntimeError("Missing original nested algorithm seed")
        base_success=sum(
            bool(row["arms"]["original"]["ESI"]["strict_both"])
            for row in old)
        any_success=sum(
            any(bool(v["ESI"]["strict_both"])
                for v in row["arms"].values())
            for row in old)
        if certificate["globally_infeasible_certified"] and any_success:
            raise RuntimeError(
                "UNSOUND GLOBAL INSTANCE PROOF: rejects a strictly validated Stage1+Stage2 instance")
        record={
            "scene":scene,"profile":profile,
            "original_instance_sha256":content_hash(instance),
            "physical_geometry_sha256":geo,
            "nested_old_original_strict_ESI":base_success,
            "nested_any_experimental_strict_ESI":any_success,
            "strict_independent_numerical_model_unchanged":True,
            "global_certificate":certificate,
        }
        result["rows"].append(record)
        write_json(out_path,result)
        print("P11_GLOBAL_INSTANCE_CASE="+json.dumps({
            "scene":scene,"profile":profile,
            "proved_globally_impossible":certificate["globally_infeasible_certified"],
            "individually_impossible_tasks":certificate["single_task_necessary"]["impossible_count"],
            "worst_compute_interval_ratio":certificate["pooled_CPU_energetic_interval"]["demand_ratio"],
            "worst_collection_deadline_ratio":certificate["UAV_collection_MST_deadline_prefix"]["demand_ratio"],
            "MST_cycle_ratio":certificate["UAV_collection_MST_patrol_cycle"]["demand_ratio"],
            "original_ESI_strict_nested":base_success,
            "any_method_strict_nested":any_success,
        },ensure_ascii=False),flush=True)
    result["complete"]=True
    result["summary"]={
        "profiles":len(result["rows"]),
        "proven_global_impossible":sum(
            x["global_certificate"]["globally_infeasible_certified"]
            for x in result["rows"]),
        "strictly_feasible_original_source_controls":sum(
            x["nested_old_original_strict_ESI"]>0 for x in result["rows"]),
        "unsafe_false_global_exclusions":sum(
            x["global_certificate"]["globally_infeasible_certified"] and
            x["nested_any_experimental_strict_ESI"]>0
            for x in result["rows"]),
    }
    write_json(out_path,result)
    print("P11_GLOBAL_INSTANCE_SUMMARY="+json.dumps({
        "scene":scene,**result["summary"],
    },ensure_ascii=False),flush=True)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.output)
