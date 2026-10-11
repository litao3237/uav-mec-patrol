"""Strict paired repair after the source B-ALNS necessary-precheck failure.

Use identical frozen failed D for the depth-2 queue control, depth-4 same
candidate selection, and depth-4 diverse temporary-infeasible bridge.
Algorithm seed is nested in the scenario; stage1+stage2 residual qualification
is mandatory, so queue-passing states never count as strict success.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from experiment_common import current_source_hashes, provenance
from atomic_batch_search import (ARMS, run_atomic_arm, run_control_arm)
from progressive_bridge_core import PROFILES
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)


def summarize(rows):
    results=[]
    for profile in PROFILES:
        subset=[r for r in rows if r["profile"]==profile]
        eligible=[r for r in subset if r["eligible"]]
        for arm in ARMS:
            group=[r["arms"][arm] for r in eligible if arm in r["arms"]]
            valid=[r for r in group if r.get("strict_both_recovered")]
            def avg(field):
                vals=[v[field] for v in group if v.get(field) is not None]
                return mean(vals) if vals else None
            results.append({
                "profile":profile,"arm":arm,
                "attempted_source_states":len(subset),
                "eligible_failed_structures":len(eligible),
                "arm_attempts":len(group),
                "strict_stage1_stage2_recovered":len(valid),
                "mean_total_wall_s":avg("total_wall_s"),
                "mean_stage1_oracle_calls":avg("strict_stage1_oracle_calls"),
                "mean_stage_reached":(
                    mean(v["search_diagnostics"].get("actual_depth",0)
                         for v in group) if group and arm!=ARMS[0] else None
                ),
                "precheck_admitted_count":sum(
                    bool(v.get("search_diagnostics",{}).get(
                        "precheck_passing",v.get("search_diagnostics",{}).get(
                            "queue_pass_candidates",0,
                        ),
                    )) for v in group
                ),
                "soft_generation_time_overrun_count":sum(
                    bool(v.get("search_diagnostics",{}).get(
                        "generation_soft_overrun",False,
                    )) for v in group
                ),
                "exceptions":sum("error_type" in v for v in group),
            })
    return results


def run(args):
    if args.output.exists():raise FileExistsError(args.output)
    archived=json.loads(args.input.read_text(encoding="utf-8"))
    proto=archived["protocol"]
    if not archived.get("complete") or proto["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Expected complete frozen original model sensitivity archive")
    K,S=int(proto["task_scale"]),int(proto["independent_scenario_seed"])
    if K!=80:raise ValueError("Only K80 original failed states in this diagnostic")
    profiles=[x.strip() for x in args.profiles.split(",") if x.strip()]
    if not profiles or len(set(profiles))!=len(profiles) or any(p not in PROFILES for p in profiles):
        raise ValueError("Invalid or duplicate stress profiles")
    seeds=[int(x) for x in args.seeds.split(",") if x.strip()] if args.seeds else list(proto["algorithm_seeds"])
    index={(r["profile"],int(r["seed"]),r["method"]):r for r in archived["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"p1_atomic_coupled_MEC_dependency_repair_v1",
            "tasks":K,"scenario":S,
            "algorithm_seeds":seeds,
            "profiles":profiles,"arms":ARMS,
            "immutable_source_archive_sha256":content_hash(archived),
            "frozen_develop_sha":"0bdf3a26d4c042e13f96f84977261ffdd33cfc89",
            "same_exact_original_B_ALNS_failed_D_all_arms":True,
            "original_queue_depth2_width2":True,
            "new_arms_width":args.beam_width,
            "new_arms_depth":args.depth,
            "same_score_depth_width_and_generation_caps_for_all_depth4_methods":True,
            "only_one_best_CVX_candidate_is_strictly_finalized_per_arm":True,
            "max_candidate_stage1_checks_per_arm":args.exact_limit,
            "generation_soft_cap_s":args.generation_cap_s,
            "all_infeasible_intermediate_states_excluded_from_CVX":True,
            "strict_stage1_stage2_saved_reconstructed_audit":True,
            "not_full_matched_end_to_end_algorithm_comparison":True,
            "provenance":provenance(),
            "source_hashes":current_source_hashes(Path(__file__)),
        },
        "rows":[],
    }
    write_json(args.output,payload)
    unexpected=[]
    for profile in profiles:
        entry=archived["profiles"][profile]
        instance=restore_instance(entry["instance"])
        if content_hash(instance)!=entry["instance_sha256"]:
            raise RuntimeError("Archived physical instance hash mismatch")
        for seed in seeds:
            src=index[(profile,seed,"B-ALNS")]
            diag=(src.get("resources") or {}).get("diagnostics") or {}
            status=str(diag.get("stage1_status","unknown"))
            row={
                "tasks":K,"scenario":S,"profile":profile,
                "seed":seed,
                "source_stage1_status":status,
                "source_both_qualified":bool(src.get("both_qualified")),
                "eligible":status=="infeasible_precheck",
                "source_solution_sha256":src.get("solution_sha256"),
                "arms":{},
            }
            if row["eligible"]:
                sol=restore_solution(src["solution"])
                hash_before=content_hash(sol)
                if hash_before!=row["source_solution_sha256"]:
                    raise RuntimeError("Frozen source discrete solution checksum mismatch")
                for arm in ARMS:
                    try:
                        if arm in ARMS[:2]:
                            result=run_control_arm(
                                instance,sol,arm=arm,
                                beam_width=args.beam_width,
                                depth=args.depth,
                                exact_limit=args.exact_limit,
                                generation_cap_s=args.generation_cap_s,
                            )
                        else:
                            result=run_atomic_arm(
                                instance,sol,arm=arm,
                                beam_width=args.beam_width,
                                depth=args.depth,
                                exact_limit=args.exact_limit,
                                generation_cap_s=args.generation_cap_s,
                            )
                        if content_hash(sol)!=hash_before:
                            raise RuntimeError("Experiment mutated original failed D")
                        row["arms"][arm]=result
                        print(
                            f"ATOMIC K{K} S{S} A{seed} {profile} {arm}: "
                            f"strict={result['strict_both_recovered']} "
                            f"cvx={result['strict_stage1_oracle_calls']} "
                            f"time={result['total_wall_s']:.3f}s",
                            flush=True,
                        )
                    except Exception as exc:
                        unexpected.append({
                            "profile":profile,"seed":seed,"arm":arm,
                            "type":type(exc).__name__,"message":str(exc),
                        })
                        row["arms"][arm]={
                            "error_type":type(exc).__name__,
                            "error_message":str(exc),
                            "strict_both_recovered":False,
                        }
            payload["rows"].append(row)
            write_json(args.output,payload)
    payload["complete"]=True
    payload["unexpected_errors"]=unexpected
    payload["summary"]=summarize(payload["rows"])
    write_json(args.output,payload)
    print("ATOMIC_SUMMARY="+json.dumps({
        "tasks":K,"scenario":S,
        "source_attempts":len(payload["rows"]),
        "eligible":sum(r["eligible"] for r in payload["rows"]),
        "unexpected_errors":len(unexpected),
        "strict_recovery":{
            arm:sum(r["arms"].get(arm,{}).get("strict_both_recovered",False)
                    for r in payload["rows"])
            for arm in ARMS
        },
    },ensure_ascii=False),flush=True)
    if unexpected:
        raise RuntimeError(f"Unexpected repair failures recorded: {unexpected[:2]}")
    return payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--profiles",default=",".join(PROFILES))
    p.add_argument("--seeds",default="")
    p.add_argument("--beam-width",type=int,default=2)
    p.add_argument("--depth",type=int,default=4)
    p.add_argument("--exact-limit",type=int,default=3)
    p.add_argument("--generation-cap-s",type=float,default=4.)
    a=p.parse_args()
    if min(a.beam_width,a.depth,a.exact_limit)<=0 or a.generation_cap_s<=0:
        raise ValueError("Invalid search budget")
    run(a)


if __name__=="__main__":
    main()
