"""P26 full-MEC-batch transfer original-capacity paired strict comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCENES=(91,93)
POLICIES=("joint_bw_cpu_rank","cpu_lb_rank","queue_rank","random_rank")


def summarize(collected:Path,output:Path):
    docs=[json.loads(f.read_text(encoding="utf-8"))
          for f in sorted(collected.rglob("p26-batch-S*.json"))]
    errors=[]
    if sorted(d["protocol"]["scene"] for d in docs)!=list(SCENES):
        errors.append("Need both previously seen P26 S91/S93 blocks")
    rows=[r for d in docs for r in d["rows"]]
    if len(rows)!=3:
        errors.append("Expected 3 original profile/seed cases")
    for d in docs:
        if not d.get("complete") or d.get("errors"):
            errors.append("Missing complete P26 original physical source data")
    agg={
        "independent_spatial_scenes":len(set(d["protocol"]["scene"] for d in docs)),
        "already_inspected_development_source_cases":len(rows),
        "original_physical_cpu_bandwidth_not_increased":True,
        "full_ALNS_matched_wall_time_benchmark":False,
        "strict_CVX_posthoc_only":True,
        "same_exact_legal_candidates_for_all_rankers":True,
        "original_P22_strict":sum(
            r["P22_original_strict"]["Stage1_and_Stage2_strict"] for r in rows
        ),
        "policies":{},
        "paired":[],
        "errors":errors,
    }
    for p in POLICIES:
        agg["policies"][p]={
            "attempts":len(rows),
            "selected_full_stage1_stage2_checks":sum(
                r["policies"][p]["strict_selected_n"] for r in rows
            ),
            "source_cases_with_strict":sum(
                r["policies"][p]["any_strict"] for r in rows
            ),
            "strict_positive_candidates":[
                {
                    "scene":r["scene"],"profile":r["profile"],"seed":r["seed"],
                    "label":a["label"],"candidate_sha":a["candidate_SHA"],
                    "new_station":a["new_station"],
                    "offload_bundle":a["batch"],
                    "energy_j":a["strict"]["strict_energy_j"],
                }
                for r in rows for a in r["policies"][p]["checked"]
                if a["strict_both"]
            ],
            "new_strict_vs_frozen_swap":[
                {"scene":r["scene"],"profile":r["profile"],"seed":r["seed"]}
                for r in rows if r["policies"][p]["any_strict"]
                and not r["P22_original_strict"]["Stage1_and_Stage2_strict"]
            ],
            "selected_joint_necessary_pass":sum(
                a["joint_necessary_pass"] for r in rows
                for a in r["policies"][p]["checked"]
            ),
        }
    for r in rows:
        pools=[set(r["policies"][p]["same_full_pool_candidate_SHA"]) for p in POLICIES]
        if len(set(map(frozenset,pools)))!=1:
            errors.append(f"Not exactly the same candidate pool S{r['scene']}")
        quotas=[r["policies"][p]["strict_selected_n"] for p in POLICIES]
        if len(set(quotas))!=1:
            errors.append(f"Mismatched expensive CVX quotas S{r['scene']}")
        all_d=r["complete_candidate_pool"]
        agg["paired"].append({
            "scene":r["scene"],"profile":r["profile"],"seed":r["seed"],
            "original_swap_strict":r["P22_original_strict"]["Stage1_and_Stage2_strict"],
            "legal_batch_candidate_D":len(all_d),
            "original_swap_queue_pass":r["P22_queue_CPU_baseline"]["queue"]["queue_necessary_pass"],
            "queue_passing_candidates":sum(x["audit"]["queue"]["queue_necessary_pass"] for x in all_d),
            "joint_BW_CPU_passing_candidates":sum(
                x["joint"]["passes_joint_necessary_test"] for x in all_d
            ),
            "strict_after_6_by_arm":{
                p:r["policies"][p]["strict_pass_n"]
                for p in POLICIES
            },
        })
    agg["errors"]=errors
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(agg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P26_BATCH_AGGREGATE="+json.dumps(agg,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("P26 incomplete or unmatched controls: "+str(errors[:3]))
    return agg


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    summarize(args.collected,args.output)
