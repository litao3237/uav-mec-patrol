"""P25 same-shortlist two-offload original-MEC-CVX retrospective aggregate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

SCENES=(91,93)
POLICIES=("joint_bw_cpu_rank","cpu_lb_rank","queue_rank")


def summarize(collected:Path,output:Path):
    files=sorted(collected.rglob("p25-two-step-S*.json"))
    docs=[json.loads(f.read_text(encoding="utf-8")) for f in files]
    errors=[]
    if sorted(d["protocol"]["scene"] for d in docs)!=list(SCENES):
        errors.append("Missing P25 S91/S93 complete independent development source blocks")
    for d in docs:
        if not d.get("complete") or d.get("errors"):
            errors.append(f"Incomplete data S{d['protocol']['scene']}")
    rows=[r for d in docs for r in d["rows"]]
    if len(rows)!=3:
        errors.append(f"Expected S91 one, S93 two physical/seed profiles: got {len(rows)}")

    results={
        "different_original_spatial_scenes":len(SCENES),
        "previously_inspected_development_physical_cases":len(rows),
        "equal_common_second_step_candidate_pool":True,
        "fixed_original_MEC_resources":True,
        "diagnostic_only_not_matched_ALNS_wall":True,
        "P22_original_swap_strict_count":sum(
            bool(r["P22_swap_strict"]["Stage1_and_Stage2_strict"])
            for r in rows
        ),
        "policies":{},
        "paired":[],
        "errors":errors,
    }
    for policy in POLICIES:
        selected=[r["policies"][policy] for r in rows]
        results["policies"][policy]={
            "source_n":len(selected),
            "total_expensive_posthoc_strict_checks":sum(len(a["checked"]) for a in selected),
            "source_with_strict_solution":sum(bool(a["any_strict"]) for a in selected),
            "new_strict_vs_frozen_P22": [
                {"scene":r["scene"],"profile":r["profile"],"seed":r["seed"]}
                for r in rows
                if r["policies"][policy]["any_strict"]
                and not r["P22_swap_strict"]["Stage1_and_Stage2_strict"]
            ],
            "strict_success_candidates":[
                {"scene":r["scene"],"profile":r["profile"],"seed":r["seed"],
                 "label":v["label"],"candidate_sha":v["candidate_sha"],
                 "strict_energy_j":v["strict"]["strict_energy_j"]}
                for r in rows for v in r["policies"][policy]["checked"]
                if v["strict_both"]
            ],
            "selected_queue_passing_n":sum(
                z["queue_pass"] for x in selected for z in x["checked"]
            ),
            "selected_joint_necessary_passing_n":sum(
                z["joint_necessary_pass"] for x in selected for z in x["checked"]
            ),
        }
    for r in rows:
        sets=[set(r["policies"][p]["common_candidate_sha_set"]) for p in POLICIES]
        if len(set(map(frozenset,sets)))!=1:
            errors.append(f"Different final candidate pool used by rankings S{r['scene']}")
        counts=[len(r["policies"][p]["checked"]) for p in POLICIES]
        if len(set(counts))!=1:
            errors.append(f"Unequal numerical check quota S{r['scene']}")
        results["paired"].append({
            "scene":r["scene"],"profile":r["profile"],"seed":r["seed"],
            "root_moves_generated":r["first_full_generated"],
            "root_parent_states":r["first_parent_states"],
            "two_step_moves_generated":r["second_full_generated"],
            "common_shortlist":r["common_final_pool_size"],
            "parent_strict":r["P22_swap_strict"]["Stage1_and_Stage2_strict"],
            "strategies":{
                p:{
                    "any_strict":r["policies"][p]["any_strict"],
                    "strict_count":r["policies"][p]["strict_count"],
                    "posthoc_calls":len(r["policies"][p]["checked"]),
                    "passing_joint_gate":sum(
                        v["joint_necessary_pass"] for v in r["policies"][p]["checked"]),
                }
                for p in POLICIES
            },
        })
    results["errors"]=errors
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("P25_TWO_STEP_AGGREGATE="+json.dumps(results,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("Incomplete or mismatched P25 experimental sample: "+str(errors[:3]))
    return results


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--collected",type=Path,required=True)
    cli.add_argument("--output",type=Path,required=True)
    x=cli.parse_args()
    summarize(x.collected,x.output)
