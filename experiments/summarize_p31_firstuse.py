"""P31 aggregate preregistered first-use 4 physical layouts × 3 paper scales.

No unpaired feasible-only energy means. Physical scene seeds independent;
scale/profile are paired blocks and stochastic algorithm seeds nested.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean

SCENES=(135,136,137,138)
SCALES=(30,50,80)
PROFILES=("baseline","compute_x1p5","deadline_x0p9")
SEEDS=(191,)
ARMS=("original","sham","queue_only","cpu_only","joint_cpu_bw")


def summarize(collected:Path,output:Path):
    files=sorted(collected.rglob("p31-firstuse-K*_S*.json"))
    observed={}
    rows=[]
    errors=[]
    for file in files:
        d=json.loads(file.read_text(encoding="utf-8"))
        p=d["protocol"]
        source=(int(p["independent_spatial_scene"]),int(p["paper_task_scale"]))
        if source in observed:errors.append(f"Duplicated physical source {source}")
        observed[source]=file.name
        if not d.get("complete"):errors.append(f"Incomplete block {source}")
        errors.extend(d.get("errors",[]))
        if tuple(p.get("arms",()))!=ARMS:
            errors.append(f"Changed preregistered arms {source}")
        if tuple(p.get("nested_algorithm_seeds",()))!=SEEDS:
            errors.append(f"Changed seed/nesting {source}")
        if tuple(p.get("profiles",()))!=PROFILES:
            errors.append(f"Changed physical profiles {source}")
        if p.get("B_exploration_wall_budget_s")!=6. or p.get("ESI_elite_wall_budget_s")!=2.:
            errors.append(f"Changed budget {source}")
        for row in d["rows"]:
            if (row["scene"],row["scale"])!=source:
                errors.append(f"Wrong source row {row}")
            if not all("ESI" in row["arms"].get(arm,{}) for arm in ARMS):
                errors.append(f"Missing complete arms in {source}")
            rows.append(row)
    planned={(s,k) for s in SCENES for k in SCALES}
    if set(observed)!=planned:
        errors.append(f"Expected 12 frozen scene-scale blocks: {set(observed)^planned}")
    if len(rows)!=len(SCENES)*len(SCALES)*len(PROFILES)*len(SEEDS):
        errors.append(f"Expected 36 paired profile/seed rows, saw {len(rows)}")
    seen_pairs=set()
    for row in rows:
        key=(row["scene"],row["scale"],row["profile"],row["seed"])
        if key in seen_pairs:errors.append(f"Duplicate nested seed {key}")
        seen_pairs.add(key)
    report={
        "frozen_protocol":"P31_original_ALNS_MEC_cross_UAV_binding_CPU_BW_firstuse_v1",
        "independent_spatial_layouts":len({x[0] for x in observed}),
        "spatial_scene_scale_blocks":len(observed),
        "paired_profile_nested_seed_rows":len(rows),
        "independent_sample_unit":"physical_spatial_scene, not 36 independent layouts",
        "time_fairness":"matched B exploration 6s plus elite <=2s, NOT hard 8s end-to-end",
        "physical_model_and_original_stage1_stage2_unchanged":True,
        "methods":{},
        "by_scale":{},
        "by_profile":{},
        "paired_vs_original":{},
        "research_gate":{},
        "errors":errors,
    }
    def stats(sample,arm):
        good=[r["arms"][arm] for r in sample if "ESI" in r["arms"].get(arm,{})]
        return {
            "n":len(good),
            "B_Stage1_Stage2_strict":sum(bool(x["B"]["strict_both"]) for x in good),
            "ESI_Stage1_Stage2_strict":sum(bool(x["ESI"]["strict_both"]) for x in good),
            "B_iterations":sum(x["B_iterations"] for x in good),
            "mean_B_iterations":mean(x["B_iterations"] for x in good) if good else None,
            "mean_true_whole_wall_s":mean(
                x["true_complete_with_initialization_s"] for x in good
            ) if good else None,
            "mean_search_wall_s":mean(x["search_wall_s"] for x in good) if good else None,
            "operator_calls":sum(
                (x["postrepair"] or {}).get("calls",0) for x in good
            ),
            "P31_selected_cross_UAV_D":sum(
                (x["postrepair"] or {}).get("chosen_other_D",0)
                for x in good
            ),
            "P31_generated_candidates":sum(
                (x["postrepair"] or {}).get("generated_candidates",0)
                for x in good
            ),
        }
    report["methods"]={arm:stats(rows,arm) for arm in ARMS}
    report["by_scale"]={
        str(k):{arm:stats([r for r in rows if r["scale"]==k],arm)
                for arm in ARMS}
        for k in SCALES
    }
    report["by_profile"]={
        p:{arm:stats([r for r in rows if r["profile"]==p],arm)
           for arm in ARMS}
        for p in PROFILES
    }
    for arm in ARMS[1:]:
        gains=[]
        losses=[]
        paired_energy=[]
        for row in rows:
            orig=row["arms"].get("original",{}).get("ESI",{})
            new=row["arms"].get(arm,{}).get("ESI",{})
            key={
                "scene":row["scene"],"scale":row["scale"],
                "profile":row["profile"],"seed":row["seed"],
            }
            if new.get("strict_both") and not orig.get("strict_both"):
                gains.append(key)
            if orig.get("strict_both") and not new.get("strict_both"):
                losses.append(key)
            if orig.get("strict_both") and new.get("strict_both"):
                paired_energy.append({
                    **key,"original_minus_new_j":
                    orig["energy_j"]-new["energy_j"]
                })
        report["paired_vs_original"][arm]={
            "new_strict_solutions":gains,
            "lost_original_strict_solutions":losses,
            "both_strict_energy_pairs":paired_energy,
            "mean_both_strict_paired_saving_j":(
                mean(x["original_minus_new_j"] for x in paired_energy)
                if paired_energy else None
            ),
        }
    joint=report["paired_vs_original"]["joint_cpu_bw"]
    gain_scenes={r["scene"] for r in joint["new_strict_solutions"]}
    gain_scales={r["scale"] for r in joint["new_strict_solutions"]}
    report["research_gate"]={
        "predeclared_min_two_new_physical_scenes":len(gain_scenes)>=2,
        "predeclared_min_two_task_scales":len(gain_scales)>=2,
        "no_lost_baseline_strict_solutions":not joint["lost_original_strict_solutions"],
        "joint_vs_sham_strict_gain_n":(
            report["methods"]["joint_cpu_bw"]["ESI_Stage1_Stage2_strict"]-
            report["methods"]["sham"]["ESI_Stage1_Stage2_strict"]
        ),
        "statistical_significance_not_asserted":True,
    }
    report["research_gate"]["cleared_exploratory_thresholds"]=all(
        report["research_gate"][k] for k in (
            "predeclared_min_two_new_physical_scenes",
            "predeclared_min_two_task_scales",
            "no_lost_baseline_strict_solutions",
        )
    )
    report["errors"]=errors
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P31_HOLDOUT_AGGREGATE="+json.dumps({
        **{k:v for k,v in report.items() if k not in (
            "paired_vs_original","by_scale","by_profile")},
        "paired_summary":{
            a:{
                "new_strict":len(x["new_strict_solutions"]),
                "lost_strict":len(x["lost_original_strict_solutions"]),
                "paired_energy_cases":len(x["both_strict_energy_pairs"]),
                "mean_paired_energy_saving_j":
                    x["mean_both_strict_paired_saving_j"],
                "gain_cases":x["new_strict_solutions"],
                "loss_cases":x["lost_original_strict_solutions"],
            }
            for a,x in report["paired_vs_original"].items()
        },
        "by_scale_strict":{
            k:{a:v["ESI_Stage1_Stage2_strict"]
               for a,v in arms.items()}
            for k,arms in report["by_scale"].items()
        },
    },ensure_ascii=False),flush=True)
    if errors:raise RuntimeError("P31 new physical holdout incomplete "+str(errors[:3]))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collected",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    a=parser.parse_args()
    summarize(a.collected,a.output)
