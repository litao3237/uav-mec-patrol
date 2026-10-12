"""P5 frozen conditional repair pilot: same discrete moves, different safe gates.

Experiment arms on the SAME original failed B-ALNS fixed D:
  queue_top3      original atomic/cross-UAV queue-only shortlist;
  static_cpu_top3 earlier P2 static MEC CPU certificate;
  joint_bw_cpu_12 P5 static CPU + rigorous 12-bin joint BW/CPU DP;
  joint_bw_cpu_48 P5 static CPU + rigorous 48-bin joint BW/CPU DP.

Identical candidate pool/beam/depth/4s soft candidate generation, 3-or
FEWER unchanged Stage1 oracle checks per arm, one Stage1+Stage2 full final
qualification. Source B search/preparation is prepaid; NOT a complete
equal-time ESI-ALNS comparison, nor a proof that generated candidates
satisfy the published physical constraints. Counters distinguish
safe gate rejections from solver failures. Source D remains immutable.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from atomic_batch_search import atomic_search
from progressive_bridge_core import PROFILES
from run_p3_cpu_certificate_probe import _strict_check
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,restore_solution,content_hash,write_json,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

ARMS=("queue_top3","static_cpu_top3","joint_bw_cpu_12","joint_bw_cpu_48")


def choose(instance,sorted_queue_pass,*,arm,max_exact_checks=3):
    if arm not in ARMS:raise ValueError(arm)
    if max_exact_checks<1:raise ValueError(max_exact_checks)
    start=perf_counter()
    chosen=[]
    checked=Counter()
    encountered=[]
    for candidate in sorted_queue_pass:
        if len(chosen)>=max_exact_checks:break
        if arm=="queue_top3":
            chosen.append(candidate)
            continue
        static=station_cpu_share_necessary_bound(instance,candidate["sol"])
        checked["static_checked"]+=1
        if static["certified_cpu_share_failure"]:
            checked["static_rejected"]+=1
            if len(encountered)<12:
                encountered.append({"label":candidate["label"],"reason":"static_cpu"})
            continue
        if arm.startswith("joint_"):
            resolution=12 if arm.endswith("_12") else 48
            bound=joint_station_bw_cpu_necessary_bound(
                instance,candidate["sol"],n_bins=resolution)
            checked["joint_checked"]+=1
            if bound["joint_necessary_reject"]:
                checked["joint_extra_rejected"]+=1
                if len(encountered)<12:
                    stations=[
                        m for m,row in bound["stations"].items()
                        if row["joint_necessary_violation"]
                    ]
                    encountered.append({
                        "label":candidate["label"],"reason":"joint_bw_cpu",
                        "station_ids":stations,
                    })
                continue
        chosen.append(candidate)
    return chosen,{
        **dict(checked),
        "gate_wall_s":perf_counter()-start,
        "scan_events":encountered,
    }


def evaluate_case(instance,source):
    started=perf_counter()
    seen_before=content_hash(source)
    ordered,raw=atomic_search(
        instance,source,include_atomic=True,include_cross_uav=True,
        beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.,
    )
    if len(ordered)!=raw["queue_passed"]:
        raise RuntimeError("Raw search shortlist omitted a queue-admissible state")
    common_gen_time=perf_counter()-started
    arms={}
    for arm in ARMS:
        selected,gate=choose(instance,ordered,arm=arm)
        strict=_strict_check(instance,selected,arm="P5_"+arm)
        if strict["oracle_calls"]>3:
            raise RuntimeError("Strict Stage1 CVX quota exceeded")
        arms[arm]={
            "arm":arm,
            "selection_labels":[r["label"] for r in selected],
            "candidate_generation_shared_wall_s":common_gen_time,
            "cpu_and_joint_gate":gate,
            **strict,
            "full_repair_wall_s":(
                common_gen_time+gate["gate_wall_s"]+strict["strict_eval_wall_s"]),
        }
    if content_hash(source)!=seen_before:
        raise RuntimeError("Frozen original source mutated")
    return {
        "original_discrete_source_sha256":seen_before,
        "original_queue_passing_unique_candidates":len(ordered),
        "raw_search_diagnostics":{
            "source_queue_excess_s":raw["source_queue_excess_s"],
            "unique_generated":raw["unique_generated"],
            "queue_passed":raw["queue_passed"],
            "beam_depth_reached":raw["beam_depth_reached"],
            "soft_generation_overrun":raw["soft_generation_overrun"],
        },
        "arms":arms,
    }


def run(input_file:Path,output:Path):
    if output.exists():raise FileExistsError("Do not overwrite experiment evidence")
    archived=json.loads(input_file.read_text(encoding="utf-8"))
    p=archived["protocol"]
    if (not archived.get("complete") or p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1"
        or int(p["task_scale"])!=80):
        raise ValueError("Expected original completed K80 source archives")
    scene=int(p["independent_scenario_seed"])
    seeds=list(p["algorithm_seeds"])
    rows={(r["profile"],int(r["seed"]),r["method"]):r for r in archived["rows"]}
    out={
        "complete":False,
        "protocol":{
            "id":"P5_matched_three_strict_oracle_joint_BW_CPU_screen_v1",
            "scenario":scene,"source_sha256":content_hash(archived),
            "nested_seeds":seeds,"arms":list(ARMS),
            "same_frozen_original_failed_B_ALNS_D":True,
            "same_generated_queue_candidates_all_arms":True,
            "same_beam_width_2_depth_4_soft_cap_s_4":True,
            "max_stage1_oracle_calls_3":True,
            "Stage1_Stage2_and_saved_reconstructed_audit_unmodified":True,
            "prepaid_source_search_not_full_equal_runtime_ALNS":True,
            "joint_n_bins_pre_registered":48,
            "no_official_algorithm_changes":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,out)
    for profile in PROFILES:
        instance=restore_instance(archived["profiles"][profile]["instance"])
        if content_hash(instance)!=archived["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Original instance SHA256 mismatch")
        for seed in seeds:
            old=rows[profile,seed,"B-ALNS"]
            src_status=((old.get("resources") or {}).get("diagnostics") or {}).get("stage1_status")
            row={
                "scenario":scene,"profile":profile,"seed":seed,
                "source_status":src_status,
                "eligible":src_status=="infeasible_precheck",
                "source_sha256":old.get("solution_sha256"),
                "arms":{},
            }
            out["rows"].append(row)
            write_json(output,out)
            if not row["eligible"]:continue
            try:
                sol=restore_solution(old["solution"])
                if content_hash(sol)!=old["solution_sha256"]:
                    raise RuntimeError("Original frozen B-ALNS solution changed")
                x=evaluate_case(instance,sol)
                if x["original_discrete_source_sha256"]!=old["solution_sha256"]:
                    raise RuntimeError("Frozen source replaced")
                row.update(x)
                print("P5_SCREEN_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,
                    "queue_admitted":x["original_queue_passing_unique_candidates"],
                    "outcomes":{
                        a:{"strict":v["strict_both_recovered"],
                           "CVX":v["oracle_calls"],
                           "wall":round(v["full_repair_wall_s"],4),
                           "static_rej":v["cpu_and_joint_gate"].get("static_rejected",0),
                           "joint_rej":v["cpu_and_joint_gate"].get("joint_extra_rejected",0)}
                        for a,v in x["arms"].items()
                    }
                },ensure_ascii=False),flush=True)
            except Exception as exc:
                issue={
                    "scene":scene,"profile":profile,"seed":seed,
                    "type":type(exc).__name__,"message":str(exc)}
                row["error"]=issue
                out["errors"].append(issue)
            write_json(output,out)
    out["complete"]=True
    elig=[r for r in out["rows"] if r["eligible"]]
    out["summary"]={
        "source_pressure_attempts":len(out["rows"]),
        "conditional_failed_D":len(elig),
        "strict":{a:sum(r["arms"].get(a,{}).get("strict_both_recovered",False)
                        for r in elig) for a in ARMS},
        "total_stage1_CVX":{a:sum(r["arms"].get(a,{}).get("oracle_calls",0)
                                   for r in elig) for a in ARMS},
        "exceptions":len(out["errors"]),
    }
    write_json(output,out)
    print("P5_SCREEN_SUMMARY="+json.dumps({
        "scene":scene,**out["summary"],"errors":out["errors"]
    },ensure_ascii=False),flush=True)
    if out["errors"]:
        raise RuntimeError(f"Unexpected paired P5 problem {out['errors'][:2]}")
    return out


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    a=ap.parse_args()
    run(a.source,a.output)
