"""P18 multiscale original-vs-actionable matched-clock strict aggregate.

Count physical scene-scale pairs as blocks and algorithm seeds as nested
repeats. No unpaired conditional energy comparisons.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import mean
import argparse

ARMS=("original","proxy_sham","proxy_actionable")
SCALES=(30,50,80)
SCENES=(125,126,127,128)
PROFILES=("baseline","compute_x1p5","deadline_x0p9")


def aggregate(directory:Path,out:Path):
    files=sorted(directory.rglob("p18-firstuse-K*_S*.json"))
    seen=set()
    rows=[]
    errors=[]
    for f in files:
        d=json.loads(f.read_text(encoding="utf-8"))
        p=d["protocol"]
        key=(int(p["scale_tasks"]),int(p["scenario"]))
        if key in seen:errors.append(f"duplicate {key}")
        seen.add(key)
        if not d.get("complete"):errors.append(f"incomplete {key}")
        errors.extend(d.get("errors",[]))
        for row in d.get("rows",[]):
            if row["scale"]!=key[0] or row["scene"]!=key[1]:
                errors.append(f"mismatched source {key}")
            if not all("ESI" in row["arms"].get(a,{}) for a in ARMS):
                errors.append(f"missing arm {key} {row['profile']} {row['seed']}")
            rows.append(row)
    expected={(k,s) for k in SCALES for s in SCENES}
    if seen!=expected or len(rows)!=72:
        errors.append(f"expected 12 scale-scene blocks/72 paired rows got {len(seen)}/{len(rows)}")
    result={
        "physical_scene_scale_blocks":len(seen),
        "distinct_spatial_scene_ids":len({s for _,s in seen}),
        "paired_profile_seed_rows":len(rows),
        "nested_seeds_are_not_independent_scenes":True,
        "same_B_search_clock_not_hard_end_to_end_clock":True,
        "methods":{},
        "by_scale":{},
        "by_profile":{},
        "paired_vs_original":{},
        "errors":errors,
    }
    def stats(sample,arm):
        xs=[r["arms"][arm] for r in sample if "ESI" in r["arms"].get(arm,{})]
        return {
            "n":len(xs),
            "strict_ESI_Stage1_Stage2":sum(x["ESI"]["strict_both"] for x in xs),
            "B_strict_Stage1":sum(x["B"]["strict_stage1"] for x in xs),
            "ALNS_iterations":sum(x["B_search_iterations"] for x in xs),
            "queue_necessary_D":sum(x["read_only_funnel"]["counters"].get("queue_necessary_pass",0) for x in xs),
            "joint_BW_CPU_necessary_D":sum(x["read_only_funnel"]["counters"].get("joint_bw_cpu_necessary_pass",0) for x in xs),
            "mean_complete_wall_s":mean(x["true_end_to_end_wall_s"] for x in xs) if xs else None,
            "mean_cheap_scoring_wall_s":mean((x["preview"] or {}).get("cheap_scoring_wall_s",0) for x in xs) if xs else None,
        }
    result["methods"]={a:stats(rows,a) for a in ARMS}
    result["by_scale"]={str(k):{a:stats([r for r in rows if r["scale"]==k],a) for a in ARMS} for k in SCALES}
    result["by_profile"]={p:{a:stats([r for r in rows if r["profile"]==p],a) for a in ARMS} for p in PROFILES}
    for a in ARMS[1:]:
        gains=[];losses=[];paired_energy=[]
        for r in rows:
            old=r["arms"].get("original",{}).get("ESI",{})
            new=r["arms"].get(a,{}).get("ESI",{})
            key={"scene":r["scene"],"scale":r["scale"],"profile":r["profile"],"seed":r["seed"]}
            if new.get("strict_both") and not old.get("strict_both"):gains.append(key)
            if old.get("strict_both") and not new.get("strict_both"):losses.append(key)
            if old.get("strict_both") and new.get("strict_both"):
                paired_energy.append({**key,"original_minus_new_energy_j":old["energy_j"]-new["energy_j"]})
        result["paired_vs_original"][a]={
            "new_strict":gains,
            "lost_original_strict":losses,
            "both_strict_energy_pairs":paired_energy,
            "mean_paired_energy_saving_j":mean(x["original_minus_new_energy_j"] for x in paired_energy) if paired_energy else None,
        }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P18_MULTISCALE_AGGREGATE="+json.dumps(result,ensure_ascii=False),flush=True)
    if errors:raise RuntimeError(f"Incomplete P18 multiscale: {errors[:4]}")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    aggregate(args.collected,args.output)
