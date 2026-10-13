"""P23 cross-UAV structural repair × MEC CPU/BW interaction aggregation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

SCENES=(89,91,93,95,96)
ARMS=("deadline_critical_pairs","random_cross_uav_pairs")
FACTORS=("unchanged","CPU_x2","BW_x2","CPU_BW_x2","CPU_BW_x4")


def summarize(collected:Path,output:Path):
    docs=[]
    errors=[]
    for f in sorted(collected.rglob("p23-interaction-S*.json")):
        d=json.loads(f.read_text(encoding="utf-8"))
        if not d.get("complete") or d.get("errors"):
            errors.append(f"incomplete source {f.name}")
        docs.append(d)
    if sorted(d["protocol"]["source_scene"] for d in docs)!=list(SCENES):
        errors.append("Expected five complete previously inspected physical scenes")
    rows=[r for d in docs for r in d["rows"]]
    if len(rows)!=6:
        errors.append("Expected six complete physical source/seed/profile combinations")
    result={
        "scenes":len(docs),
        "frozen_K80_B_sources":len(rows),
        "nested_controls_not_independent_spatial_scenes":True,
        "fixed_P22_winner_D_exact_SHA_reused":True,
        "new_full_ALNS_algorithm":False,
        "by_arm":{},
        "paired":[],
        "errors":errors,
    }
    for arm in ARMS:
        samples=[r["arms"][arm] for r in rows]
        summary={}
        for f in FACTORS:
            summary[f]={
                "n":len(samples),
                "queue_necessary_pass":sum(bool(x["capacity"][f]["queue"]["queue_necessary_pass"])
                                           for x in samples),
                "stage1_strict":sum(bool(x["capacity"][f]["strict"]["Stage1_strict_qualified"])
                                    for x in samples),
                "full_Stage1_Stage2_strict":sum(bool(x["capacity"][f]["Stage1_and_Stage2_strict"])
                                             for x in samples),
                "gain_vs_unchanged":sum(bool(x["capacity"][f]["Stage1_and_Stage2_strict"]) and
                                         not x["capacity"]["unchanged"]["Stage1_and_Stage2_strict"]
                                         for x in samples),
                "loss_vs_unchanged":sum(bool(x["capacity"]["unchanged"]["Stage1_and_Stage2_strict"]) and
                                         not x["capacity"][f]["Stage1_and_Stage2_strict"]
                                         for x in samples),
            }
        result["by_arm"][arm]=summary
    for r in rows:
        line={"scene":r["scene"],"profile":r["profile"],"seed":r["seed"],
              "original_B_strict":r["P22_source_initial_strict"]}
        for arm in ARMS:
            x=r["arms"][arm]
            line[arm]={
                "task_pair":x["P22_best_pair"],
                "queue_pass":{f:x["capacity"][f]["queue"]["queue_necessary_pass"]
                              for f in FACTORS},
                "strict":{f:x["capacity"][f]["Stage1_and_Stage2_strict"] for f in FACTORS},
                "stage1_status":{f:x["capacity"][f]["strict"]["Stage1_solver_status"]
                                 for f in FACTORS},
            }
        result["paired"].append(line)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P23_INTERACTION_AGGREGATE="+json.dumps(result,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("Missing P23 independent source data: "+str(errors[:3]))
    return result


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--collected",type=Path,required=True)
    cli.add_argument("--output",type=Path,required=True)
    a=cli.parse_args()
    summarize(a.collected,a.output)
