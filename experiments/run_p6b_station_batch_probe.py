"""P6b post-joint-MEC contact-batch relocation, controlled ablation.

The P6 negative result identified an action-granularity mismatch:
joint resource certificates bind (UAV,MEC) virtual QUEUES, while
selecting a binding TASK can entirely miss a contact whose WHOLE BATCH
should migrate to the other MEC. P6b tests only a single common action:
repoint one physical contact visit, moving its entire task upload batch.

Same frozen B-ALNS source D, same original atomic beam, same joint
48-bin necessary filter, SAME <=3 original strict CVX Stage1 calls and
same Stage1+Stage2 finalization. All S89-S95 are already inspected
development data, not independent holdout or whole-ALNS comparison.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from atomic_batch_search import atomic_search
from progressive_bridge_core import PROFILES,_metric,_legacy_global_key
from run_p3_cpu_certificate_probe import _strict_check,_root_task_ids
from run_p5_joint_screening_probe import choose
from run_p6_postbound_probe import _eval_safe_bound
from station_batch_sweep_moves import POLICIES,station_batch_moves
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

ARMS=("P5_joint48_baseline",)+POLICIES
DEV_SCENES=(89,90,91,92,93,94,95)


def _batch_repair(
    instance,source,ordered,prior_selected,*,policy,
    seed_limit=4,action_limit=100,soft_wall_cap_s=3.0):
    if policy not in POLICIES:raise ValueError(policy)
    start=perf_counter()
    root_ids=_root_task_ids(instance,source)
    seen={solution_signature(c["sol"]) for c in ordered}
    extras={}
    counters=Counter()
    details=[]
    for seed in ordered:
        if counters["seed_examined"]>=seed_limit:break
        if perf_counter()-start>=soft_wall_cap_s:
            counters["soft_cap_hit"]+=1;break
        label,existing=_eval_safe_bound(instance,seed["sol"])
        counters["seed_examined"]+=1
        if label not in ("static_cpu_rejected","joint_rejected"):
            continue
        joint=(existing if existing is not None else
               joint_station_bw_cpu_necessary_bound(
                   instance,seed["sol"],n_bins=48))
        if not joint["joint_necessary_reject"]:continue
        counters["violating_seed_examined"]+=1
        family,meta=station_batch_moves(
            instance,seed["sol"],joint,policy=policy,
            alternative_points_per_visit=2,max_selected_visits=12)
        counters["structurally_generated"]+=len(family)
        if len(details)<4:
            details.append({
                "parent":seed["label"],
                "policy":policy,
                "target_station":meta.get("target_station"),
                "station_CPU_excess":meta.get("violation_CPU_ghz"),
                "selected_visits":meta.get("selected_visits"),
                "valid_moves":len(family),
            })
        for move,sol,why in family:
            if perf_counter()-start>=soft_wall_cap_s:
                counters["soft_cap_hit"]+=1;break
            if counters["unique_evaluated"]>=action_limit:
                counters["action_cap_hit"]+=1;break
            signature=solution_signature(sol)
            if signature in seen:continue
            seen.add(signature)
            counters["unique_evaluated"]+=1
            gate,_=_eval_safe_bound(instance,sol)
            counters[gate]+=1
            if gate=="joint_necessary_pass":
                metric=_metric(instance,sol,root_task_ids=root_ids)
                if not metric["passed"]:
                    raise RuntimeError("P6b admitted a forbidden queue-infeasible D")
                extras[signature]={
                    "label":move,"sol":sol,"metric":metric,
                    "family":move.split("::")[0],
                    "batch_origin":why,
                }
        if counters["soft_cap_hit"] or counters["action_cap_hit"]:
            break
    best=sorted(
        extras.values(),key=lambda x:_legacy_global_key(x["metric"],x["label"]))
    selected=list(prior_selected)
    if len(selected)<3:selected.extend(best[:3-len(selected)])
    return selected,{
        "policy":policy,
        "postbound_wall_s":perf_counter()-start,
        "extra_joint_passing":len(extras),
        "top_new_labels":[r["label"] for r in best[:6]],
        "origin_details":details,
        "counters":dict(counters),
    }


def evaluate(instance,source):
    before=content_hash(source)
    t0=perf_counter()
    queue,diagnostics=atomic_search(
        instance,source,include_atomic=True,include_cross_uav=True,
        beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.)
    common_generation_wall_s=perf_counter()-t0
    base,gate=choose(instance,queue,arm="joint_bw_cpu_48")
    old_gate_wall_s=gate["gate_wall_s"]
    arms={}
    for arm in ARMS:
        if arm=="P5_joint48_baseline":
            chosen=list(base)
            extra={
                "policy":"baseline","postbound_wall_s":0.,
                "extra_joint_passing":0,"top_new_labels":[],
            }
        else:
            chosen,extra=_batch_repair(
                instance,source,queue,base,policy=arm,
                seed_limit=4,action_limit=100,soft_wall_cap_s=3.,
            )
        strict=_strict_check(instance,chosen,arm="P6b_"+arm)
        if strict["oracle_calls"]>3:
            raise RuntimeError("Stage1 exact oracle quota exceeded")
        arms[arm]={
            "selection_labels":[c["label"] for c in chosen],
            "raw_queue_admitted":len(queue),
            "common_original_atomic_generation_s":common_generation_wall_s,
            "common_original_joint_gate_wall_s":old_gate_wall_s,
            "postbound":extra,**strict,
            "complete_conditional_repair_wall_s":(
                common_generation_wall_s+old_gate_wall_s+
                extra["postbound_wall_s"]+strict["strict_eval_wall_s"]),
        }
    if content_hash(source)!=before:
        raise RuntimeError("Original B discrete structure was mutated")
    return arms


def run(source_path:Path,output:Path):
    if output.exists():raise FileExistsError(output)
    original=json.loads(source_path.read_text(encoding="utf-8"))
    p=original["protocol"]
    if (not original.get("complete") or
        p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1"
        or int(p["task_scale"])!=80):
        raise ValueError("Unrecognized original B/ESI physical source")
    scene=int(p["independent_scenario_seed"])
    if scene not in DEV_SCENES:
        raise ValueError("P6b accepts ONLY previously inspected S89-S95")
    by_src={(r["profile"],int(r["seed"]),r["method"]):r
            for r in original["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"P6b_critically_station_batch_repoint_development_v1",
            "scene":scene,
            "source_sha256":content_hash(original),
            "same_frozen_atomic_search_and_joint48_screen":True,
            "original_B_source_search_prepaid":True,
            "maximum_Stage1_CVX_per_method":3,
            "same_original_Stage1_Stage2_residuals":True,
            "same_common_batch_repoint_move_family":True,
            "all_S89_S95_inspected_previously":True,
            "not_new_independent_holdout_or_end_to_end_equal_time_ALNS":True,
            "arms":list(ARMS),
        },
        "rows":[],"errors":[],
    }
    write_json(output,payload)
    for profile in PROFILES:
        snap=original["profiles"][profile]
        instance=restore_instance(snap["instance"])
        if content_hash(instance)!=snap["instance_sha256"]:
            raise RuntimeError("Physical stress instance identity changed")
        for seed in p["algorithm_seeds"]:
            source=by_src[profile,int(seed),"B-ALNS"]
            status=(
                ((source.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status"))
            row={
                "scene":scene,"profile":profile,"seed":int(seed),
                "source_stage1_status":status,
                "source_sha256":source.get("solution_sha256"),
                "eligible":status=="infeasible_precheck",
                "arms":{},
            }
            payload["rows"].append(row)
            write_json(output,payload)
            if not row["eligible"]:continue
            try:
                sol=restore_solution(source["solution"])
                if content_hash(sol)!=row["source_sha256"]:
                    raise RuntimeError("Frozen original source SHA mismatch")
                row["arms"]=evaluate(instance,sol)
                print("P6B_BATCH_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":int(seed),
                    "strict":{k:v["strict_both_recovered"] for k,v in row["arms"].items()},
                    "new_joint":{k:v["postbound"]["extra_joint_passing"]
                                 for k,v in row["arms"].items()},
                    "CVX":{k:v["oracle_calls"] for k,v in row["arms"].items()},
                },ensure_ascii=False),flush=True)
            except Exception as exc:
                error={"scene":scene,"profile":profile,"seed":int(seed),
                       "type":type(exc).__name__,"message":str(exc)}
                row["error"]=error
                payload["errors"].append(error)
                print("P6B_BATCH_ERROR="+json.dumps(error),flush=True)
            write_json(output,payload)
    payload["complete"]=True
    eligible=[r for r in payload["rows"] if r["eligible"]]
    payload["summary"]={
        "original_sources":len(payload["rows"]),
        "eligible_failed_D":len(eligible),
        "strict":{a:sum(r["arms"].get(a,{}).get("strict_both_recovered",False)
                        for r in eligible) for a in ARMS},
        "stage1_calls":{a:sum(r["arms"].get(a,{}).get("oracle_calls",0)
                              for r in eligible) for a in ARMS},
        "extra_joint_pass":{a:sum(r["arms"].get(a,{}).get("postbound",{}).get(
            "extra_joint_passing",0) for r in eligible) for a in ARMS},
        "errors":len(payload["errors"]),
    }
    write_json(output,payload)
    print("P6B_BATCH_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"],
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"P6b unexpected errors: {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.output)
