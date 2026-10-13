"""P29 identical local/direct-E2 relocation policy compare on two old cases."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

SOURCES={(91,"compute_x1p5",128),(93,"baseline",129)}
GROUPS=("binding_chain_E1","heavy_E1","random_E1")
RANKS=("joint_bw_cpu","static_cpu","queue_only")


def aggregate(collected:Path,output:Path):
    docs=[json.loads(f.read_text(encoding="utf-8"))
          for f in sorted(collected.rglob("p29-transfer-S*.json"))]
    errors=[]
    if {(d["protocol"]["scene"],d["protocol"]["profile"],d["protocol"]["seed"])
        for d in docs}!=SOURCES or len(docs)!=2:
        errors.append("Missing preregistered two old physical scene/control results")
    for d in docs:
        if not d.get("complete") or d.get("errors"):
            errors.append(f"Incomplete P29 source {d['protocol']['scene']}")
    out={
        "original_physical_capacity_and_Stage1_Stage2_unchanged":True,
        "not_new_ALNS_or_unseen_holdout":True,
        "independent_spatial_scene_count":len(docs),
        "source_qualifier_cases":len(docs),
        "matched_candidate_generation_template_and_per_rank_checks":True,
        "by_group":{},"paired":[],"errors":errors,
    }
    for group in GROUPS:
        rows=[]
        for d in docs:
            r=d["results"][group]
            rows.append((d,r))
        out["by_group"][group]={
            "physical_cases":len(rows),
            "total_legal_cross_UAV_D":sum(r["legal_distinct_candidates"] for _,r in rows),
            "ranks":{},
        }
        for policy in RANKS:
            out["by_group"][group]["ranks"][policy]={
                "selected_strict_check_count":sum(
                    len(r["policy"][policy]["strict_checks"]) for _,r in rows
                ),
                "strict_new_over_P22_swap_cases":[
                    {
                        "scene":d["protocol"]["scene"],
                        "profile":d["protocol"]["profile"],
                        "seed":d["protocol"]["seed"],
                    } for d,r in rows
                    if r["policy"][policy]["any_strict"] and
                    not d["protocol"]["P22_original_strict"]
                ],
                "strict_positive_candidates":[
                    {
                        "scene":d["protocol"]["scene"],
                        "profile":d["protocol"]["profile"],
                        "seed":d["protocol"]["seed"],
                        "target":x["task"],"to_UAV":x["to_UAV"],
                        "execution":x["execution"],"contact":x["visit"],
                        "sha":x["SHA"],"strict_energy_j":x["strict_result"]["strict_energy_j"],
                    }
                    for d,r in rows for x in r["policy"][policy]["strict_checks"]
                    if x["strict_both"]
                ],
            }
    for d in docs:
        sample={"scene":d["protocol"]["scene"],
                "profile":d["protocol"]["profile"],
                "seed":d["protocol"]["seed"],"groups":{}}
        for group in GROUPS:
            r=d["results"][group]
            if len({frozenset(x["common_candidate_SHA"]) for x in r["policy"].values()})!=1:
                errors.append(f"Changed candidate pool between rankers S{sample['scene']}")
            if len({x["quota"] for x in r["policy"].values()})!=1:
                errors.append(f"Changed strict solver quota between rankers S{sample['scene']}")
            sample["groups"][group]={
                "target_tasks":r["targets"],
                "candidate_D":r["legal_distinct_candidates"],
                "queue_passing_D":sum(x["read_only"]["queue"]["queue_necessary_pass"]
                                      for x in r["candidate_pool"]),
                "joint_passing_D":sum(x["read_only"]["joint"]["passes_joint_necessary_test"]
                                      for x in r["candidate_pool"]),
                "strict_by_ranking":{p:r["policy"][p]["strict_sources"] for p in RANKS},
            }
        out["paired"].append(sample)
    out["errors"]=errors
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P29_E1_TRANSFER_AGGREGATE="+json.dumps(out,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("P29 dataset/control mismatch "+str(errors[:3]))
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    x=p.parse_args()
    aggregate(x.collected,x.output)
