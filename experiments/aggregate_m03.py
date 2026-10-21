"""M0.3 fail-closed physical and factorial ablation aggregator."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from uav_mec.analysis.experiment_snapshot import write_json
from uav_mec.evaluation.task_objective import LATENESS_TOL, ENERGY_EQUALITY_TOL_J
from diagnose_m03 import CASES, ARMS

def _priority(a,b):
    # Return whether a is demonstrably lex better than b.
    if a["on_time"]!=b["on_time"]:
        return a["on_time"]>b["on_time"]
    if a["normalized_lateness"] < b["normalized_lateness"]-LATENESS_TOL:
        return True
    if a["normalized_lateness"] > b["normalized_lateness"]+LATENESS_TOL:
        return False
    if a["energy_j"] < b["energy_j"]-ENERGY_EQUALITY_TOL_J:
        return True
    if abs(a["energy_j"]-b["energy_j"])<=ENERGY_EQUALITY_TOL_J:
        return a["route_distance_m"]<b["route_distance_m"]-1e-6
    return False


def aggregate(root:Path,out:Path):
    wanted=set(CASES)
    all_found=set()
    flat,comparisons=[],[]
    for path in sorted(root.rglob("K*_S*_A*.json")):
        data=json.loads(path.read_text(encoding="utf-8"))
        key=(data["tasks"],data["scenario"],data["seed"])
        if key not in wanted or key in all_found:
            raise RuntimeError(f"Unregistered or duplicated case: {path}")
        all_found.add(key)
        if not data["complete"] or data["iterations"]!=100:
            raise RuntimeError(f"Incomplete experiment record: {path}")
        if len(data["arms"])!=len(ARMS) or data["registered_arms"] != [v[0] for v in ARMS]:
            raise RuntimeError(f"Wrong factorial arms: {path}")
        pairs={x["arm"]:x for x in data["arms"]}
        if set(pairs)!={x[0] for x in ARMS}:
            raise RuntimeError(f"Arms missing/duplicated: {path}")
        if key[1]==45 and key[2]==100 and pairs["baseline"]["replicates_m02_m0_reference_sha"] is not True:
            raise RuntimeError(f"Baseline M02 reference failed K={key[0]}")
        for name, arm in pairs.items():
            if arm["physical_feasible"] is not True:
                raise RuntimeError(f"Unverified physical candidate in {key}: {name}")
            if len(arm["operator_trace"])!=100:
                raise RuntimeError(f"Missing 100-iteration trace in {key}: {name}")
            if sum(arm["outcomes"].values())!=100:
                raise RuntimeError(f"Invalid ALNS outcome count in {key}: {name}")
            if arm["acceptance_mode"]=="qos_physical_rrt" and len(arm["acceptance_trace"])==0:
                raise RuntimeError(f"Missing quality RRT records at {key}: {name}")
            if arm["selection_mode"]=="unit_credit_ucb" and len(arm["credit_trace"])!=100:
                raise RuntimeError(f"Missing QoS-credit records at {key}: {name}")
            if arm["unserved"]<0 or arm["on_time"]>key[0] or arm["served"]>key[0]:
                raise RuntimeError(f"Impossible task statistics in {key}: {name}")
            if arm["stage2_energy_j"] is not None and abs(
                arm["stage2_energy_j"]-arm["energy_j"]
            ) > 1e-5:
                raise RuntimeError(f"Stage 2 must match final measured Joules {key}: {name}")
            flat.append({
                "tasks":key[0],"scenario":key[1],"seed":key[2],
                "arm":name,
                **{f:arm[f] for f in (
                    "on_time","success_rate","served","unserved","late","normalized_lateness",
                    "energy_j","route_distance_m","search_s","resource_s","total_time_s",
                    "contact_visits","offloaded_tasks","candidate_solution_sha256",
                    "final_signature","stage2_status","admission_source","energy_source",
                )},
                "accepted":arm["outcomes"]["accepted"],
                "rejected":arm["outcomes"]["rejected"],
                "new_bests":arm["outcomes"]["best"],
                "unique_candidate_structures":len({
                    t["candidate_structure_sha256"] for t in arm["operator_trace"]
                }),
            })
        base=pairs["baseline"]
        for name in ("unit_acceptance","unit_credit","combined"):
            new=pairs[name]
            comparisons.append({
                "tasks":key[0],"scenario":key[1],"seed":key[2],
                "contrast":name,
                "delta_success_vs_baseline":new["on_time"]-base["on_time"],
                "delta_lateness_vs_baseline":new["normalized_lateness"]-base["normalized_lateness"],
                "delta_energy_j_vs_baseline":new["energy_j"]-base["energy_j"],
                "delta_route_m_vs_baseline":new["route_distance_m"]-base["route_distance_m"],
                "delta_search_s_vs_baseline":new["search_s"]-base["search_s"],
                "delta_total_s_vs_baseline":new["total_time_s"]-base["total_time_s"],
                "lex_better_than_baseline":_priority(new,base),
                "lex_worse_than_baseline":_priority(base,new),
                "same_solution_structure":new["final_signature"]==base["final_signature"],
                "same_success_count":new["on_time"]==base["on_time"],
                "both_physical":new["physical_feasible"] and base["physical_feasible"],
            })
    if all_found!=wanted or len(flat)!=24 or len(comparisons)!=18:
        raise RuntimeError(
            f"Missing planned M03 entries {sorted(wanted-all_found)}, {len(flat)} arms"
        )
    grouped=defaultdict(list)
    for row in comparisons:
        grouped[(row["tasks"],row["scenario"],row["contrast"])].append(row)
    scene_averages=[
        {
            "tasks":k,"scenario":s,"contrast":c,"seed_replicates":len(rows),
            "mean_energy_delta_j":mean(x["delta_energy_j_vs_baseline"] for x in rows),
            "mean_success_count_delta":mean(x["delta_success_vs_baseline"] for x in rows),
            "mean_search_runtime_delta_s":mean(x["delta_search_s_vs_baseline"] for x in rows),
            "lex_better_seed_count":sum(x["lex_better_than_baseline"] for x in rows),
            "lex_worse_seed_count":sum(x["lex_worse_than_baseline"] for x in rows),
        }
        for (k,s,c),rows in sorted(grouped.items())
    ]
    out.mkdir(parents=True,exist_ok=True)
    write_json(out/"m03_ablation.json",{
        "schema":"m03_four_arm_qos_unit_credit_v1",
        "registered_cases":sorted(wanted),
        "note":"A diagnostic fixed-iteration ablation; K50 contains three scenes and two seeds on S45 only; not a statistical dominance claim.",
        "all_physical_verified":True,
        "planned_pair_contrasts":len(comparisons),
        "arm_level":flat,
        "paired_contrasts":comparisons,
        "scenario_averages":scene_averages,
    })
    for name,records in [
        ("m03_arms.csv",flat),("m03_paired.csv",comparisons),
        ("m03_scenarios.csv",scene_averages),
    ]:
        keys=sorted({key for row in records for key in row})
        with (out/name).open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=keys)
            writer.writeheader()
            writer.writerows(records)
    print("Verified 24 arms, 6 cases, 18 paired contrasts; physical gate passed.",flush=True)
    for c in comparisons:
        print(json.dumps({
            f:c[f] for f in (
                "tasks","scenario","seed","contrast","delta_success_vs_baseline",
                "delta_energy_j_vs_baseline","delta_search_s_vs_baseline",
                "lex_better_than_baseline","lex_worse_than_baseline",
            )
        }),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    aggregate(a.input,a.output)
