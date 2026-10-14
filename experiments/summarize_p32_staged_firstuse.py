"""P32 four wholly disjoint first-use spatial layouts × 3 task scales.

Pair ESI physical stage1+stage2 feasibility first. Never compute average
energy over different subsets of strictly feasible solutions; only matched
both-strict pairs. Original exploration 6 seconds plus elite 2 seconds are
SOFT independent phase budgets, not full-run 8 seconds hard budgets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

SCENES=(139,140,141,142)
SCALES=(30,50,80)
PROFILES=("baseline","compute_x1p5","deadline_x0p9")
SEEDS=(191,)
ARMS=("original","p31_queue_only","sham_joint",
      "queue_guard","cpu_guard","joint_gate")


def summarize(collected:Path,output:Path):
    files=sorted(collected.rglob("p32-firstuse-K*_S*.json"))
    errors=[]
    observed={}
    rows=[]
    for file in files:
        report=json.loads(file.read_text(encoding="utf-8"))
        p=report["protocol"]
        key=(int(p["independent_spatial_scene"]),int(p["task_scale"]))
        if key in observed:
            errors.append("Duplicate scene-scale first-use block "+str(key))
        observed[key]=file.name
        if not report.get("complete") or report.get("errors"):
            errors.append("Incomplete first-use numerical block "+str(key))
        for name,expected in [
            ("all_new_spatial_scenes",SCENES),
            ("all_task_scales",SCALES),
            ("physical_profiles",PROFILES),
            ("algorithm_seeds_nested",SEEDS),
            ("arms",ARMS),
        ]:
            if tuple(p.get(name,()))!=tuple(expected):
                errors.append(f"Frozen protocol altered {key}:{name}")
        if (p.get("B_exploration_clock_s")!=6.
            or p.get("ESI_elite_clock_s")!=2.):
            errors.append("Original ALNS clock changed "+str(key))
        if not p.get("original_MEC_hardware_physical_model_and_strict_residuals"):
            errors.append("Original physical model not verified "+str(key))
        for row in report["rows"]:
            if (row["scene"],row["scale"])!=key:
                errors.append("Wrong paired physical source "+str(row))
            if any("ESI" not in row["arms"].get(a,{}) for a in ARMS):
                errors.append("Missing strict arm "+str(key))
            rows.append(row)
    needed={(s,k) for s in SCENES for k in SCALES}
    if set(observed)!=needed:
        errors.append("Missing 12 first-use scene/scale blocks "+str(needed^set(observed)))
    if len(rows)!=len(SCENES)*len(SCALES)*len(PROFILES)*len(SEEDS):
        errors.append(f"Expected 36 paired physical profiles, saw {len(rows)}")
    source_ids=[
        (row["scene"],row["scale"],row["profile"],row["seed"])
        for row in rows
    ]
    if len(source_ids)!=len(set(source_ids)):
        errors.append("Repeated physical scene/profile/seed input")
    def overview(sample,arm):
        valid=[r["arms"][arm] for r in sample if "ESI" in r["arms"].get(arm,{})]
        return {
            "n":len(valid),
            "B_strict_both":sum(x["B"]["strict_both"] for x in valid),
            "ESI_strict_both":sum(x["ESI"]["strict_both"] for x in valid),
            "B_iterations":sum(x["B_iterations"] for x in valid),
            "mean_B_iterations":mean(x["B_iterations"] for x in valid) if valid else None,
            "mean_true_complete_wall_s":mean(
                x["true_complete_with_initialization_s"] for x in valid
            ) if valid else None,
            "mean_exploration_elite_search_wall_s":mean(
                x["search_wall_s"] for x in valid
            ) if valid else None,
            "operator_calls":sum((x["postrepair"] or {}).get("calls",0)
                                 for x in valid),
            "changed_repair_D_count":sum(
                (x["postrepair"] or {}).get("chosen_other_D",0)
                for x in valid
            ),
            "joint_bound_calls":sum(
                (x["postrepair"] or {}).get("joint_bound_calls",0)
                for x in valid
            ),
            "cheap_eligible_candidates":sum(
                (x["postrepair"] or {}).get("queue_cpu_eligible_candidates",0)
                for x in valid
            ),
            "queue_CPU_preservation_calls":sum(
                (x["postrepair"] or {}).get("base_queue_and_cpu_pass_preserved",0)
                for x in valid
            ),
        }
    methods={a:overview(rows,a) for a in ARMS}
    by_scale={
        str(k):{a:overview([r for r in rows if r["scale"]==k],a)
                for a in ARMS}
        for k in SCALES
    }
    by_scene={
        str(s):{a:overview([r for r in rows if r["scene"]==s],a)
                for a in ARMS}
        for s in SCENES
    }
    by_profile={
        p:{a:overview([r for r in rows if r["profile"]==p],a)
           for a in ARMS}
        for p in PROFILES
    }
    paired={}
    for arm in ARMS[1:]:
        gains=[]
        lost=[]
        matched_energy=[]
        equal_sha=[]
        for r in rows:
            b=r["arms"]["original"]["ESI"]
            c=r["arms"][arm]["ESI"]
            key={
                "scene":r["scene"],"scale":r["scale"],
                "profile":r["profile"],"seed":r["seed"],
            }
            if c["strict_both"] and not b["strict_both"]:
                gains.append(key)
            if b["strict_both"] and not c["strict_both"]:
                lost.append(key)
            if b["strict_both"] and c["strict_both"]:
                matched_energy.append({
                    **key,"original_minus_new_energy_j":
                    b["energy_j"]-c["energy_j"],
                })
            if b["sha256"]==c["sha256"]:
                equal_sha.append(key)
        paired[arm]={
            "new_strict":gains,
            "lost_original_strict":lost,
            "both_strict_paired_energy":matched_energy,
            "both_strict_energy_pairs":len(matched_energy),
            "mean_paired_original_minus_arm_energy_j":(
                mean(v["original_minus_new_energy_j"] for v in matched_energy)
                if matched_energy else None
            ),
            "original_same_final_D_SHA":equal_sha,
        }
    primary=paired["queue_guard"]
    success_scenes={r["scene"] for r in primary["new_strict"]}
    success_scales={r["scale"] for r in primary["new_strict"]}
    primary_gate={
        "preregistered_primary_arm":"queue_guard",
        "strict_new_cases_at_least_two_independent_scenes":len(success_scenes)>=2,
        "strict_gains_at_least_two_task_scales":len(success_scales)>=2,
        "no_original_strict_losses":not primary["lost_original_strict"],
        "strict_gain_vs_diagnostic_sham":(
            methods["queue_guard"]["ESI_strict_both"]-
            methods["sham_joint"]["ESI_strict_both"]
        ),
        "nontrivial_overhead_actually_measured":True,
        "does_not_imply_publication_grade_statistical_significance":True,
    }
    primary_gate["cleared_exploratory_all_three_criteria"]=all(
        primary_gate[k] for k in (
            "strict_new_cases_at_least_two_independent_scenes",
            "strict_gains_at_least_two_task_scales",
            "no_original_strict_losses",
        )
    )
    report={
        "protocol":"P32_staged_queue_CPU_joint_mec_gate_firstuse_v1",
        "independent_spatial_layouts":len(SCENES),
        "scene_task_scale_blocks":len(observed),
        "paired_nested_physical_profile_algorithm_seed_cases":len(rows),
        "only_four_independent_spatial_layouts":True,
        "original_6s_plus_2s_soft_ALNS_clock_not_hard_total_runtime":True,
        "no_original_MEC_hardware_or_Stage1_Stage2_solver_changes":True,
        "S135_S138_P31_used_for_design_not_reused_as_firstuse":True,
        "methods":methods,
        "by_scale":by_scale,
        "by_scene":by_scene,
        "by_profile":by_profile,
        "paired_vs_original":paired,
        "preregistered_queue_guard_gate":primary_gate,
        "errors":errors,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print("P32_STAGED_AGGREGATE="+json.dumps({
        "sample":{k:report[k] for k in (
            "independent_spatial_layouts","scene_task_scale_blocks",
            "paired_nested_physical_profile_algorithm_seed_cases",
        )},
        "methods":methods,
        "by_scale_strict":{
            k:{a:x["ESI_strict_both"] for a,x in group.items()}
            for k,group in by_scale.items()
        },
        "paired_summary":{
            a:{
                "gains":len(v["new_strict"]),
                "losses":len(v["lost_original_strict"]),
                "new_cases":v["new_strict"],
                "lost_cases":v["lost_original_strict"],
                "both_strict_energy_n":v["both_strict_energy_pairs"],
                "paired_original_minus_arm_energy_j":
                    v["mean_paired_original_minus_arm_energy_j"],
                "original_same_D_count":len(v["original_same_final_D_SHA"]),
            }
            for a,v in paired.items()
        },
        "research_gate":primary_gate,
        "errors":errors,
    },ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("P32 first-use dataset invalid: "+str(errors[:5]))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    summarize(a.collected,a.output)
