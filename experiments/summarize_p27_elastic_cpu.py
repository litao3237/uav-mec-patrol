"""P27 frozen original resource credibility and top capacity slack results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED={(91,"compute_x1p5",128),(93,"baseline",129)}
MODES=("cpu_capacity_only","bandwidth_capacity_only",
       "mec_capacity_only","qos_only")


def aggregate(directory:Path,output:Path):
    files=sorted(directory.rglob("p27-elastic-S*.json"))
    sources=[json.loads(x.read_text(encoding="utf-8")) for x in files]
    errors=[]
    ids={(r["protocol"]["scene"],r["protocol"]["profile"],r["protocol"]["seed"])
         for r in sources}
    if ids!=EXPECTED or len(sources)!=2:
        errors.append("Missing preregistered S91 or S93 original source/seed")
    for s in sources:
        if not s.get("complete") or s.get("errors"):
            errors.append(f"Incomplete elastic original source {s['protocol']['scene']}")
    results={
        "original_P1R_CPU_bandwidth_physical_model_never_changed":True,
        "relaxed_numerical_solution_is_NOT_original_strict_feasible":True,
        "already_seen_mechanism_development_only":True,
        "source_cases":len(sources),
        "original_stage1_stage2_strict":{},
        "per_source":[],
        "errors":errors,
    }
    for r in sources:
        entry={
            "scene":r["protocol"]["scene"],
            "profile":r["protocol"]["profile"],
            "seed":r["protocol"]["seed"],
            "variants":{},
        }
        for name,x in r["candidates"].items():
            measures={}
            for m in MODES:
                d=x["elastic_diagnoses"][m]
                credible=bool(d["numerically_credible"])
                physical={}
                if credible:
                    for v in d["top_constraints"]:
                        if v["family"]=="mec_cpu_cap":
                            physical[v["constraint"]]=v["physical_slack"]
                measures[m]={
                    "credible":credible,
                    "status":d["status"],
                    "normalized_total_slack":d["normalized_total_elastic_slack"],
                    "slack_sum_by_family":d["slack_sum_by_family"],
                    "largest_relevant_constraints":d["top_constraints"][:6],
                    "cpu_cap_physical_GHz_slack_for_top_constraints":physical,
                }
            entry["variants"][name]={
                "strict":x["original_strict_Stage1_Stage2"]["Stage1_and_Stage2_strict"],
                "strict_stage1_solver_status":x["original_strict_Stage1_Stage2"]["Stage1_solver_status"],
                "queue_necessary_pass":x["queue"]["queue_necessary_pass"],
                "cpu_static_necessary_fail":x["cpu_share_bound"]["certified_failure"],
                "joint_necessary_fail":x["joint_bw_cpu_necessary"]["joint_necessary_reject"],
                "elastic_modes":measures,
            }
        results["per_source"].append(entry)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P27_ELASTIC_AGGREGATE="+json.dumps(results,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("P27 diagnostic data missing: "+str(errors[:3]))
    return results


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    aggregate(a.collected,a.output)
