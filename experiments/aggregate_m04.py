"""M0.4 independent 55-arm, 44-contrast physical and provenance verification."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from diagnose_m04 import ARMS, CASES, BASE_CVX_SHA, BASE_MODEL_SHA, CONFIG_SHA
from uav_mec.analysis.experiment_snapshot import write_json
from uav_mec.evaluation.task_objective import LATENESS_TOL, ENERGY_EQUALITY_TOL_J


def _better(candidate, base):
    if candidate["on_time"] != base["on_time"]:
        return candidate["on_time"] > base["on_time"]
    if candidate["normalized_lateness"] < base["normalized_lateness"] - LATENESS_TOL:
        return True
    if candidate["normalized_lateness"] > base["normalized_lateness"] + LATENESS_TOL:
        return False
    if candidate["energy_j"] < base["energy_j"] - ENERGY_EQUALITY_TOL_J:
        return True
    if abs(candidate["energy_j"] - base["energy_j"]) <= ENERGY_EQUALITY_TOL_J:
        return candidate["route_distance_m"] < base["route_distance_m"] - 1e-6
    return False


def aggregate(root: Path, output: Path):
    planned=set(CASES)
    got=set()
    flat=[]
    paired=[]
    for path in sorted(root.rglob("K*_S*_A*.json")):
        report=json.loads(path.read_text(encoding="utf-8"))
        case=(report["tasks"],report["scenario"],report["seed"])
        if case in got or case not in planned:
            raise ValueError(f"Unexpected or duplicated M0.4 case {path}")
        got.add(case)
        if not report["complete"] or report["iterations"]!=100:
            raise RuntimeError(f"Incomplete run {path}")
        if report["resource_source_hashes"] != {
            "cvx":BASE_CVX_SHA,"problem":BASE_MODEL_SHA,"config":CONFIG_SHA,
        }:
            raise RuntimeError(f"Unexpected M0 physics source {path}")
        arms=report["arms"]
        if [a["arm"] for a in arms]!=[x[0] for x in ARMS]:
            raise RuntimeError(f"Missing / out-of-order arms {path}")
        baseline=arms[0]
        if baseline["reproduced_m03_reference"] is False:
            raise RuntimeError(f"Baseline differs from frozen M0.3 source {case}")
        if report["holdout"] != (case[1] in (48,49,50)):
            raise RuntimeError(f"Holdout flag changed for {case}")
        for a in arms:
            if not a["physical_feasible"]:
                raise RuntimeError(f"Non-physical final candidate: {case} {a['arm']}")
            if len(a["operator_trace"])!=100 or len(a["credit_history"])!=100:
                raise RuntimeError(f"Missing ALNS operator/reward trace: {case} {a['arm']}")
            if a["selector"]=="domain_credit_ucb":
                if len(a["domain_history"])!=100:
                    raise RuntimeError(f"No M0.4 domain feedback: {case} {a['arm']}")
                if not all(0<=d["adjusted_credit"]<=1 for d in a["domain_history"]):
                    raise RuntimeError(f"Out-of-range reward: {case} {a['arm']}")
            elif a["domain_history"]:
                raise RuntimeError(f"Baseline unit-credit UCB contaminated: {case}")
            if a["on_time"]>case[0] or a["on_time"]+a["late"]+a["unserved"] != case[0]:
                raise RuntimeError(f"Incoherent task outcomes: {case} {a['arm']}")
            if a["stage2_energy_j"] is not None and abs(
                a["stage2_energy_j"]-a["energy_j"]
            )>1e-5:
                raise RuntimeError(f"Accepted Stage-2 energy mismatch: {case}")
            flat.append({
                "tasks":case[0],"scenario":case[1],"seed":case[2],
                "holdout":report["holdout"],"arm":a["arm"],
                **{k:a[k] for k in (
                    "on_time","served","late","unserved","normalized_lateness",
                    "energy_j","route_distance_m","search_s","resource_s","total_s",
                    "contact_visits","offloaded_tasks","stage2_status",
                    "admission_source","energy_source","structure_sha256",
                    "candidate_solution_sha256",
                )},
                "novel_structures":len({
                    t["candidate_structure_sha256"] for t in a["operator_trace"]
                }),
                "credit_average":mean(e["credit"] for e in a["credit_history"]),
                "accepted_count":sum(t["outcome_index"]==2 for t in a["operator_trace"]),
                "new_best_count":sum(t["outcome_index"]==0 for t in a["operator_trace"]),
            })
        for a in arms[1:]:
            paired.append({
                "tasks":case[0],"scenario":case[1],"seed":case[2],
                "holdout":report["holdout"],
                "mechanism":a["arm"],
                "delta_success":a["on_time"]-baseline["on_time"],
                "delta_lateness":a["normalized_lateness"]-baseline["normalized_lateness"],
                "delta_energy_j":a["energy_j"]-baseline["energy_j"],
                "delta_route_m":a["route_distance_m"]-baseline["route_distance_m"],
                "delta_search_s":a["search_s"]-baseline["search_s"],
                "delta_total_s":a["total_s"]-baseline["total_s"],
                "lex_better":_better(a,baseline),
                "lex_worse":_better(baseline,a),
                "identical_structure":a["structure_sha256"]==baseline["structure_sha256"],
                "both_physically_valid":a["physical_feasible"] and baseline["physical_feasible"],
            })
    if got!=planned or len(flat)!=len(CASES)*len(ARMS) or len(paired)!=len(CASES)*(len(ARMS)-1):
        raise RuntimeError(f"Wrong planned matrix: got {sorted(got)}, arms {len(flat)}, contrasts {len(paired)}")
    grouped=defaultdict(list)
    for p in paired:
        grouped[(p["tasks"],p["scenario"],p["mechanism"])].append(p)
    scene_rows=[
        {
            "tasks":k,"scenario":sc,"mechanism":method,"holdout":sc in (48,49,50),
            "seed_repeats":len(rows),
            "mean_delta_energy_j":mean(row["delta_energy_j"] for row in rows),
            "mean_delta_success":mean(row["delta_success"] for row in rows),
            "mean_delta_search_s":mean(row["delta_search_s"] for row in rows),
            "lex_wins":sum(row["lex_better"] for row in rows),
            "lex_losses":sum(row["lex_worse"] for row in rows),
        }
        for (k,sc,method),rows in sorted(grouped.items())
    ]
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/"m04_verification.json",{
        "schema":"M0.4-domain-aware-credit-frozen-physical-v1",
        "cases":list(CASES),"arm_names":[x[0] for x in ARMS],
        "physical_verified":True,"total_arms":len(flat),
        "contrasts":len(paired),"full_trace_available_in_raw_cases":True,
        "caveats":[
            "MEC contact benefit is a cheap causal-agnostic proxy, not measured marginal MEC value.",
            "Unserved tasks have null observed delays, not zero or fabricated completion times.",
            "100 iterations are matched; wall-clock search runtime is measured but not constrained.",
            "S48/S49/S50 are a limited hold-out; paired algorithm-seed repeats are nested within scenario.",
        ],
        "arms":flat,"paired":paired,"scenario_means":scene_rows,
    })
    for file,rows in (
        ("m04_arms.csv",flat),
        ("m04_paired.csv",paired),
        ("m04_scenarios.csv",scene_rows),
    ):
        keys=sorted({k for r in rows for k in r})
        with (output/file).open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
    print("M0.4 VERIFIED:",len(flat),"physical arms and",len(paired),"paired contrasts.",flush=True)
    for k in (30,50,80):
        rows=[p for p in paired if p["tasks"]==k]
        for mechanism in [x[0] for x in ARMS[1:]]:
            subset=[r for r in rows if r["mechanism"]==mechanism]
            if subset:
                print(json.dumps({
                    "K":k,"mechanism":mechanism,"n":len(subset),
                    "wins":sum(x["lex_better"] for x in subset),
                    "losses":sum(x["lex_worse"] for x in subset),
                    "mean_delta_energy_j":mean(x["delta_energy_j"] for x in subset),
                    "holdout_n":sum(x["holdout"] for x in subset),
                }),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    aggregate(args.input,args.output)
