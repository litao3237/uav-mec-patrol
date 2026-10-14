"""P33 first-use exact unchanged P32 CPU guard replication, two nested seeds.

All per-arm energy and strict feasibility comparisons are matched within
scene, scale, profile, algorithm seed; independent spatial sample size
is FOUR (not 72 nested observations or 216 ALNS runs).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

SCENES=(143,144,145,146)
SCALES=(30,50,80)
PROFILES=("baseline","compute_x1p5","deadline_x0p9")
SEEDS=(191,193)
ARMS=("original","cpu_sham","cpu_guard")


def summarize(collected:Path,output:Path):
    files=sorted(collected.rglob("p33-replication-K*_S*.json"))
    seen={}
    rows=[]
    errors=[]
    for file in files:
        d=json.loads(file.read_text(encoding="utf-8"))
        p=d["protocol"]
        key=(int(p["independent_spatial_scene"]),int(p["paper_task_scale"]))
        if key in seen:
            errors.append(f"Repeated S/K original input: {key}")
        seen[key]=file.name
        if not d.get("complete") or d.get("errors"):
            errors.append(f"Incomplete original Stage1+Stage2 S/K block: {key}")
        for name,expected in [
            ("all_new_spatial_scenes",SCENES),
            ("all_task_scales",SCALES),
            ("all_physical_profiles",PROFILES),
            ("nested_ALNS_algorithm_seeds",SEEDS),
            ("arms",ARMS),
        ]:
            if tuple(p.get(name,()))!=expected:
                errors.append(f"Changed registered protocol {key} {name}")
        if (p.get("B_exploration_clock_s")!=6. or
            p.get("elite_clock_s")!=2.):
            errors.append(f"Modified P33 real original ALNS clock {key}")
        if not p.get("P32_cpu_guard_algorithm_imported_exactly_unchanged"):
            errors.append("P32 frozen CPU mechanism changed")
        if not p.get("original_MEC_CPU_BW_UAV_tasks_frozen"):
            errors.append("Physical original resource capacity altered")
        for row in d["rows"]:
            if (row["scene"],row["scale"])!=key:
                errors.append("Wrong profile source for block")
            if any("ESI" not in row["arms"].get(a,{}) for a in ARMS):
                errors.append("Missing original strict numerical result")
            if row["arms"].get("cpu_sham",{}).get(
                "postrepair",{}).get("chosen_other_D")!=0:
                errors.append("Diagnostic-only CPU sham altered physical D")
            rows.append(row)
    expected={(s,k) for s in SCENES for k in SCALES}
    if set(seen)!=expected:
        errors.append(f"Missing blocks: {expected^set(seen)}")
    if len(rows)!=len(SCENES)*len(SCALES)*len(PROFILES)*len(SEEDS):
        errors.append(f"Expected 72 profiles/nested-seeds got {len(rows)}")
    row_keys=[
        (r["scene"],r["scale"],r["profile"],r["seed"]) for r in rows
    ]
    if len(row_keys)!=len(set(row_keys)):
        errors.append("Duplicate physical/profile/seed matched group")
    def stats(sample,arm):
        valid=[r["arms"][arm] for r in sample if "ESI" in r["arms"].get(arm,{})]
        return {
            "runs":len(valid),
            "B_strict_both":sum(x["B"]["strict_both"] for x in valid),
            "ESI_strict_both":sum(x["ESI"]["strict_both"] for x in valid),
            "B_iterations_total":sum(x["B_iterations"] for x in valid),
            "B_iterations_mean":mean(x["B_iterations"] for x in valid)
                                if valid else None,
            "mean_true_complete_wall_s":mean(
                x["true_complete_with_initialization_s"] for x in valid
            ) if valid else None,
            "mean_search_only_wall_s":mean(x["search_wall_s"] for x in valid)
                                        if valid else None,
            "original_repair_operator_calls":sum(
                (x["postrepair"] or {}).get("calls",0) for x in valid
            ),
            "actual_changed_repair_D":sum(
                (x["postrepair"] or {}).get("chosen_other_D",0) for x in valid
            ),
            "sham_hypothetical_changed_D":sum(
                (x["postrepair"] or {}).get("hypothetical_selected_D",0)
                for x in valid
            ),
            "queued_CPU_eligible_candidate_counts":sum(
                (x["postrepair"] or {}).get("queue_cpu_eligible_candidates",0)
                for x in valid
            ),
        }
    def key(r):
        return {
            "scene":r["scene"],"scale":r["scale"],
            "profile":r["profile"],"seed":r["seed"],
        }
    def compare(a,b):
        gain=[];loss=[];paired_energy=[];same_D=[]
        for r in rows:
            old=r["arms"][a]["ESI"]
            new=r["arms"][b]["ESI"]
            if new["strict_both"] and not old["strict_both"]:
                gain.append(key(r))
            if old["strict_both"] and not new["strict_both"]:
                loss.append(key(r))
            if new["strict_both"] and old["strict_both"]:
                paired_energy.append({
                    **key(r),
                    f"{a}_minus_{b}_energy_j":
                        old["energy_j"]-new["energy_j"],
                })
            if old["sha256"]==new["sha256"]:
                same_D.append(key(r))
        return {
            "strict_gain_cases":gain,
            "strict_loss_cases":loss,
            "strict_gain_n":len(gain),
            "strict_loss_n":len(loss),
            "both_strict_paired_energy":paired_energy,
            "both_strict_n":len(paired_energy),
            "mean_both_strict_matched_energy_delta_j":mean(
                list(item.values())[-1] for item in paired_energy
            ) if paired_energy else None,
            "identical_ESI_discrete_D_SHA_n":len(same_D),
        }
    changes={
        "cpu_sham_vs_original":compare("original","cpu_sham"),
        "cpu_guard_vs_original":compare("original","cpu_guard"),
        "cpu_guard_vs_cpu_sham":compare("cpu_sham","cpu_guard"),
    }
    cpu=changes["cpu_guard_vs_original"]
    cpu_scenes={r["scene"] for r in cpu["strict_gain_cases"]}
    cpu_scales={r["scale"] for r in cpu["strict_gain_cases"]}
    sham_delta=changes["cpu_guard_vs_cpu_sham"]
    gate={
        "predeclared_primary_method":"exact_P32_cpu_guard_no_retuning",
        "gains_on_at_least_two_new_independent_spatial_scenes":len(cpu_scenes)>=2,
        "gains_on_at_least_two_task_scales":len(cpu_scales)>=2,
        "no_lost_original_strict_feasible_case":cpu["strict_loss_n"]==0,
        "strict_net_advantage_over_equal_diagnostic_cpu_sham":(
            sham_delta["strict_gain_n"]>sham_delta["strict_loss_n"]
        ),
        "nested_seed_replications_are_NOT_spatially_independent":True,
        "not_publication_grade_statistical_significance":True,
    }
    gate["all_four_exploratory_requirements_passed"]=all(
        gate[name] for name in (
            "gains_on_at_least_two_new_independent_spatial_scenes",
            "gains_on_at_least_two_task_scales",
            "no_lost_original_strict_feasible_case",
            "strict_net_advantage_over_equal_diagnostic_cpu_sham",
        )
    )
    report={
        "preregistered_protocol":"P33_exact_P32_CPU_guard_two_seed_firstuse_v1",
        "independent_spatial_layouts":len(SCENES),
        "scene_K_source_blocks":len(seen),
        "matched_profile_nested_algorithm_seed_cases":len(rows),
        "full_original_ESI_ALNS_runs":len(rows)*len(ARMS),
        "original_original_model_unchanged":True,
        "matched_6plus2_soft_clock_not_hard_full_runtime":True,
        "independence_unit_spatial_scene_not_algo_seed_profile_scale":True,
        "P31_P32_used_for_hypothesis_not_reused_as_firstuse":True,
        "methods":{a:stats(rows,a) for a in ARMS},
        "by_scale":{str(k):{a:stats([r for r in rows if r["scale"]==k],a)
                            for a in ARMS} for k in SCALES},
        "by_scene":{str(s):{a:stats([r for r in rows if r["scene"]==s],a)
                            for a in ARMS} for s in SCENES},
        "by_nested_seed":{str(seed):{
            a:stats([r for r in rows if r["seed"]==seed],a)
            for a in ARMS} for seed in SEEDS},
        "paired_strict_vs_baselines":changes,
        "preregistered_primary_gate":gate,
        "errors":errors,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P33_CPU_REPLICATION_AGGREGATE="+json.dumps({
        "independent_layouts":len(SCENES),
        "nested_matched_cases":len(rows),
        "total_full_ALNS_runs":len(rows)*len(ARMS),
        "methods":report["methods"],
        "by_scale_strict":{
            scale:{arm:a["ESI_strict_both"] for arm,a in v.items()}
            for scale,v in report["by_scale"].items()
        },
        "by_nested_seed_strict":{
            seed:{arm:a["ESI_strict_both"] for arm,a in v.items()}
            for seed,v in report["by_nested_seed"].items()
        },
        "paired":{
            arm:{k:v for k,v in entries.items() if k not in (
                "both_strict_paired_energy",)}
            for arm,entries in changes.items()
        },
        "gate":gate,
        "errors":errors,
    },ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("P33 full immutable strict dataset incomplete: "+str(errors[:4]))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    summarize(a.collected,a.output)
