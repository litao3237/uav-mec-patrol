"""Aggregate fixed-discrete UAV-MEC physical-response experiments by scenario."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from run_model_sensitivity import METHODS, PROFILES


def aggregate(payloads, *, expected_tasks=(50,80), expected_scenarios=(61,62,63,64)):
    indexed = {}
    missed = []
    for p in payloads:
        b = p["protocol"]["source_block"]
        key = (int(b["tasks"]), int(b["scenario_seed"]))
        if key in indexed:
            raise ValueError(f"Duplicate block {key}")
        indexed[key] = p
    for K in expected_tasks:
        for S in expected_scenarios:
            if (K,S) not in indexed:
                missed.append((K,S))
    allrows=[]
    for (K,S),payload in indexed.items():
        for row in payload.get("rows", []):
            allrows.append({**row,"tasks":K,"scenario_seed":S})

    results=[]
    for K in expected_tasks:
        for method in METHODS:
            for profile in PROFILES:
                rows=[r for r in allrows
                      if r["tasks"]==K and r["method"]==method
                      and r["profile"]==profile]
                base={(r["scenario_seed"],r["seed"]):r for r in allrows
                      if r["tasks"]==K and r["method"]==method
                      and r["profile"]=="baseline"}
                strict=[r for r in rows if r["both_qualified"]]
                energies=defaultdict(list)
                strict_precheck_true=defaultdict(list)
                offender=Counter()
                original_status=Counter()
                monotone_violations=[]
                paired=0
                for r in rows:
                    offender.update(r["precheck"]["reason_families"])
                    original_status[r["earlier_dynamic"]["stage1_status"]]+=1
                    baseline=base.get((r["scenario_seed"],r["seed"]))
                    if baseline and baseline["both_qualified"] and r["both_qualified"]:
                        delta=r["energy_stage1_j"]-baseline["energy_stage1_j"]
                        paired+=1
                        energies[r["scenario_seed"]].append(delta)
                        tol=max(1.0,1e-5*abs(baseline["energy_stage1_j"]))
                        # If constraints only tighten, an optimum cannot fall.
                        # If BW expands, an optimum cannot rise.
                        impossible=(
                            profile!="baseline"
                            and (
                                (profile=="bandwidth_x1p5" and delta>tol)
                                or (profile!="bandwidth_x1p5" and delta<-tol)
                            )
                        )
                        if impossible:
                            monotone_violations.append({
                                "scenario":r["scenario_seed"],
                                "seed":r["seed"],"delta_energy_j":delta,
                                "tolerance_j":tol,
                            })
                by_s=[mean(v) for s,v in sorted(energies.items())]
                def average_float(key):
                    vals=[float(r["physical"][key]) for r in strict
                          if r["physical"] is not None
                          and r["physical"].get(key) is not None]
                    return mean(vals) if vals else None
                results.append({
                    "tasks":K,"method":method,"profile":profile,
                    "n_attempt":len(rows),
                    "n_fixed_precheck_qualified":sum(
                        r["precheck"]["passed_necessary_precheck"] for r in rows
                    ),
                    "n_fixed_stage1_qualified":sum(r["stage1_qualified"] for r in rows),
                    "n_fixed_both_qualified":len(strict),
                    "n_earlier_reoptimized_both_qualified":sum(
                        r["earlier_dynamic"]["both_qualified"] for r in rows
                    ),
                    "fixed_precheck_reason_count":dict(offender),
                    "earlier_dynamic_stage1_status_count":dict(original_status),
                    "paired_both_qualified_fixed_vs_fixed_baseline":paired,
                    "n_paired_independent_scenarios":len(by_s),
                    "mean_fixed_energy_change_vs_fixed_baseline_j":(
                        mean(by_s) if by_s else None
                    ),
                    "monotonicity_violations":monotone_violations,
                    "conditional_mean_offload_ratio":average_float("offload_ratio"),
                    "conditional_mean_flight_collection_share_pct":average_float(
                        "flight_collection_share_pct"
                    ),
                    "conditional_mean_upload_energy_share_pct":average_float(
                        "upload_energy_share_pct"
                    ),
                    "mean_elapsed_s":mean(r["total_s"] for r in rows) if rows else None,
                })
    return {
        "protocol":"fixed_D_coupling_replay_aggregate_v1",
        "expected_blocks":len(expected_tasks)*len(expected_scenarios),
        "received_blocks":len(indexed),
        "missing_blocks":[list(x) for x in missed],
        "incomplete_blocks":[list(k) for k,p in indexed.items() if not p.get("complete")],
        "total_records":len(allrows),
        "summary":results,
    }


def format_md(data):
    lines=[
        "# Fixed discrete-structure physical replay",
        "",
        "The same baseline UAV routes, contacts and task offload modes are",
        "held **unchanged** while task compute density, realized deadlines or",
        "MEC bandwidth is changed. Stage-1/Stage-2 resources are resolved",
        "and independently audited. These results MUST NOT be conflated",
        "with reoptimized routes from the parameter sensitivity sweep.",
        "",
        f"Workload blocks: {data['received_blocks']}/{data['expected_blocks']}; "
        f"recorded outcomes: {data['total_records']}.",
        "",
        "| K | Structure origin | Factor | Necessary LB passed | Strict Stage1+Stage2 | Reoptimized previous study qualified | Paired ΔE (J) | Offload ratio |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    def fmt(x,d=1):
        return "—" if x is None else f"{x:.{d}f}"
    for r in data["summary"]:
        lines.append(
            f"| {r['tasks']} | {r['method']} | {r['profile']} | "
            f"{r['n_fixed_precheck_qualified']}/{r['n_attempt']} | "
            f"{r['n_fixed_both_qualified']}/{r['n_attempt']} | "
            f"{r['n_earlier_reoptimized_both_qualified']}/{r['n_attempt']} | "
            f"{fmt(r['mean_fixed_energy_change_vs_fixed_baseline_j'])} | "
            f"{fmt(r['conditional_mean_offload_ratio'],3)} |"
        )
    bad=[r for r in data["summary"] if r["monotonicity_violations"]]
    lines.extend([
        "",
        "### Scope and interpretation",
        "",
        "- Strict qualified fractions use both independent Stage-1/Stage-2",
        "  residual audits and exclude invalid solver statuses.",
        "- A fixed structure may become infeasible under tighter tasks;",
        "  this does not show that the entire problem instance is infeasible.",
        "- A fixed structure's optimized energy should be monotone with",
        "  feasible-set tightening/relaxation. Recorded exceptions to this",
        "  mathematical expectation can stem from approximate solver",
        "  solutions and are flagged for separate numerical review.",
        f"- Fixed-structure numerical monotonicity flags: "
        f"{sum(len(r['monotonicity_violations']) for r in bad)}.",
        "- Previous reoptimized search results use the SAME parameterized",
        "  physical instances, but can choose new discrete structures, so",
        "  their objective trajectories need not be monotone.",
        "- Four scenario seeds with two nested algorithm seeds do not",
        "  establish general population-level statistical significance.",
    ])
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    files=sorted(args.input_dir.rglob("fixed-K*_S*.json"))
    if not files:
        raise FileNotFoundError("No fixed replay results")
    data=aggregate([json.loads(f.read_text(encoding="utf-8")) for f in files])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    (args.output_dir/"report.md").write_text(format_md(data),encoding="utf-8")
    keys=list(data["summary"][0])
    with (args.output_dir/"summary.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader()
        for row in data["summary"]:
            w.writerow({
                k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                for k,v in row.items()
            })
    print("FIXED_AGGREGATE="+json.dumps({
        "blocks":data["received_blocks"],
        "records":data["total_records"],
        "rows":[{
            k:r[k] for k in (
                "tasks","method","profile","n_fixed_precheck_qualified",
                "n_fixed_both_qualified","n_earlier_reoptimized_both_qualified",
                "mean_fixed_energy_change_vs_fixed_baseline_j"
            )
        } for r in data["summary"]],
    },ensure_ascii=False),flush=True)
    if data["missing_blocks"] or data["incomplete_blocks"]:
        raise RuntimeError("Missing or incomplete results; partial summary retained")


if __name__=="__main__":
    main()
