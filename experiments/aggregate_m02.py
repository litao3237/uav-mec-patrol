"""Aggregate M0.2 frozen paired score arms; do not compare scalar values across scales."""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from uav_mec.analysis.experiment_snapshot import write_json

EXPECTED = {(30,45,100), (80,45,100)} | {
    (50,scenario,seed) for scenario in (45,46,47) for seed in (100,101,102)
}
BASE="540e7b3193d28feb9bca57eb9998a8098c91c2a3"


def compare(a,b):
    trace_a,trace_b=a["trace"],b["trace"]
    if len(trace_a)!=len(trace_b):
        raise ValueError("Unequal ALNS iteration counts")
    def first_differ(field):
        return next((i+1 for i,(x,y) in enumerate(zip(trace_a,trace_b))
                     if x[field]!=y[field]),None)
    return {
        "tasks":a["_tasks"],"scenario":a["_scenario"],"seed":a["_seed"],
        "successes_legacy":a["successes"],"successes_m0":b["successes"],
        "success_delta_m0_minus_legacy":b["successes"]-a["successes"],
        "energy_j_legacy":a["total_energy_j"],"energy_j_m0":b["total_energy_j"],
        "energy_delta_j_m0_minus_legacy":b["total_energy_j"]-a["total_energy_j"],
        "distance_m_legacy":a["route_distance_m"],"distance_m_m0":b["route_distance_m"],
        "distance_delta_m":b["route_distance_m"]-a["route_distance_m"],
        "contacts_legacy":a["contact_visits_before_admission"],
        "contacts_m0":b["contact_visits_before_admission"],
        "search_s_legacy":a["search_s"],"search_s_m0":b["search_s"],
        "unique_structures_legacy":a["trace_summary"]["unique_candidate_structures"],
        "unique_structures_m0":b["trace_summary"]["unique_candidate_structures"],
        "rrt_absolute_start_gap_legacy":a["rrt_initial_absolute_gap"],
        "rrt_absolute_start_gap_m0":b["rrt_initial_absolute_gap"],
        "first_operator_pair_divergence_iteration":
            next((i+1 for i,(x,y) in enumerate(zip(trace_a,trace_b))
                  if (x["destroy"],x["repair"]) != (y["destroy"],y["repair"])),None),
        "first_candidate_structure_divergence_iteration": first_differ("candidate_structure_sha256"),
        "first_candidate_outcome_divergence_iteration": first_differ("outcome_index"),
        "same_final_structure":a["candidate_structure_sha256"]==b["candidate_structure_sha256"],
        "physical_pass_both":a["physical_feasible"] and b["physical_feasible"],
        "served_all_both":a["unserved"]==0 and b["unserved"]==0,
        "legacy_selector_counts":a["selector_counts"],
        "m0_selector_counts":b["selector_counts"],
    }


def aggregate(root:Path,output:Path):
    summaries=[]
    factorial_details=[]
    found=set()
    for file in sorted(root.rglob("K*_S*_A*.json")):
        d=json.loads(file.read_text(encoding="utf-8"))
        key=(d["tasks"],d["scenario"],d["seed"])
        if key not in EXPECTED or key in found:
            raise ValueError(f"Unexpected or duplicate M0.2 block {key}: {file}")
        found.add(key)
        if d["base_resource_commit"]!=BASE or d["iterations"]!=100 or not d["complete"]:
            raise ValueError(f"Bad provenance or incomplete block {file}")
        arms={a["arm"]:a for a in d["arms"]}
        needed={"legacy_adaptive_rrt","m0_adaptive_rrt"}
        if set(arms)!=needed | ({"legacy_frozen_rrt","m0_frozen_rrt",
                                  "legacy_adaptive_greedy","m0_adaptive_greedy"}
                                 if key==(50,45,100) else set()):
            raise ValueError(f"Missing/extra arms at {file}: {sorted(arms)}")
        if key[1]==45 and key[2]==100 and arms["m0_adaptive_rrt"]["reference_m0_search_sha_match"] is not True:
            raise RuntimeError(f"M0 replication mismatch at K={key[0]}: experimental validity fails")
        for a in arms.values():
            if a["iterations"]!=100 or not a["physical_feasible"]:
                raise ValueError(f"Unverified or wrong iteration count: {file}")
            if len(a["trace"])!=100 or a["trace_summary"]["iterations_recorded"]!=100:
                raise ValueError(f"Missing trace: {file}")
            if sum(a["trace_summary"][f"outcome_{label}"]
                   for label in ("best","better","accepted","rejected"))!=100:
                raise ValueError(f"Incorrect outcome accounting: {file}")
            a["_tasks"],a["_scenario"],a["_seed"]=key
        row=compare(arms["legacy_adaptive_rrt"],arms["m0_adaptive_rrt"])
        row["instance_sha256"]=d["instance_sha256"]
        row["initial_sha256"]=d["initial_sha256"]
        summaries.append(row)
        if key==(50,45,100):
            for selector,xa,xb in (
                ("frozen",arms["legacy_frozen_rrt"],arms["m0_frozen_rrt"]),
                ("greedy",arms["legacy_adaptive_greedy"],arms["m0_adaptive_greedy"]),
            ):
                extra=compare(xa,xb)
                extra["control"]=selector
                factorial_details.append(extra)
    if found!=EXPECTED:
        raise RuntimeError(f"Missing blocks: {sorted(EXPECTED-found)}")
    groups=defaultdict(list)
    for row in summaries:
        groups[(row["tasks"],row["scenario"])].append(row)
    # Seed replicates are nested in scenarios; do not pretend 9 runs are
    # independent scenarios in a significance test.
    scenario_rows=[
        {
            "tasks":k,"scenario":s,"algorithm_seed_repeats":len(rows),
            "mean_energy_delta_j_m0_minus_legacy":mean(x["energy_delta_j_m0_minus_legacy"] for x in rows),
            "mean_distance_delta_m":mean(x["distance_delta_m"] for x in rows),
            "mean_success_delta":mean(x["success_delta_m0_minus_legacy"] for x in rows),
            "m0_better_energy_seeds":sum(x["energy_delta_j_m0_minus_legacy"] < -1e-3 for x in rows),
            "legacy_better_energy_seeds":sum(x["energy_delta_j_m0_minus_legacy"] > 1e-3 for x in rows),
        } for (k,s),rows in sorted(groups.items())
    ]
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/"m02_diagnosis.json",{
        "protocol":"m02_score_only_same_m0_recourse",
        "fixed_solver_commit":BASE,
        "independent_scenarios_for_K50":3,
        "total_seed_level_pairs":len(summaries),
        "data_scoping":"only matched K,scenario,seed and identical M0 resource recourse",
        "primary_pairs":summaries,"factorial_controls":factorial_details,
        "scenario_nested_means":scenario_rows,
    })
    for fname,rows in [
        ("m02_primary_pairs.csv",summaries),
        ("m02_factorial_controls.csv",factorial_details),
        ("m02_scenario_means.csv",scenario_rows),
    ]:
        if not rows: continue
        fields=sorted({key for r in rows for key in r})
        with (output/fname).open("w",newline="",encoding="utf-8") as stream:
            w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
            w.writerows({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v)
                         for k,v in r.items()} for r in rows)
    print(json.dumps({"pairs":len(summaries),"scenario_nested_means":scenario_rows,
                      "factorial":factorial_details},ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    opts=p.parse_args()
    aggregate(opts.input,opts.out)
