"""Aggregate paired old-LB and queue-dependent feasibility repair diagnostics."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from statistics import mean

from run_queue_guided_repair import ARMS,STRESS_PROFILES


def aggregate(payloads):
    blocks={}
    for p in payloads:
        scenario=p["protocol"]["scenario"]
        if scenario in blocks:
            raise ValueError(f"Duplicate scenario {scenario}")
        blocks[scenario]=p
    result=[]
    for profile in STRESS_PROFILES:
        sample=[
            r for _,p in sorted(blocks.items())
            for r in p["rows"]
            if r["profile"]==profile
        ]
        eligible=[r for r in sample if r["eligible"]]
        for arm in ARMS:
            answers=[r["arms"][arm] for r in eligible if arm in r["arms"]]
            result.append({
                "profile":profile,"arm":arm,
                "total_attempts":len(sample),
                "original_fixed_precheck_failed":len(eligible),
                "n_scenarios_with_failed_states":len({
                    r["scenario"] for r in eligible
                }),
                "arm_attempts":len(answers),
                "precheck_passing":sum(
                    int(x.get("queue_precheck_passing",x.get("old_precheck_passing",0)) or 0)>0
                    for x in answers
                ),
                "strict_both_recovered":sum(x.get("strict_both_recovered",False) for x in answers),
                "mean_exact_calls":mean(x.get("strict_cvx_calls",0) for x in answers)
                    if answers else None,
                "mean_runtime_s":mean(x["runtime_s"] for x in answers
                                      if x.get("runtime_s") is not None)
                    if any(x.get("runtime_s") is not None for x in answers) else None,
                "unexpected_errors":sum("error_type" in x for x in answers),
            })
    return {
        "id":"queue_guided_feasibility_probe_aggregate_v1",
        "expected_scenarios":[61,62,63,64],
        "received_scenarios":sorted(blocks),
        "missing_scenarios":sorted({61,62,63,64}-set(blocks)),
        "incomplete":[s for s,p in blocks.items() if not p.get("complete")],
        "unexpected_errors":[{s:p.get("unexpected_errors")} for s,p in blocks.items()
                             if p.get("unexpected_errors")],
        "rows":result,
    }


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--input-dir",type=Path,required=True)
    a.add_argument("--output-dir",type=Path,required=True)
    args=a.parse_args()
    files=sorted(args.input_dir.rglob("queue-repair-K80_S*.json"))
    if not files:raise FileNotFoundError("No repair JSON artifacts")
    d=aggregate([json.loads(f.read_text(encoding="utf-8")) for f in files])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    keys=list(d["rows"][0])
    with (args.output_dir/"summary.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader()
        w.writerows(d["rows"])
    md=[
        "# Queue-aware feasibility repair: paired pre-registered probe",
        "",
        "On the same frozen K80 B-ALNS precheck-failing discrete solutions,",
        "compare original greedy, original optimistic-bound guided repair,",
        "queue-ranked identical neighborhood, and queue-guided predecessors/",
        "cross-UAV moves. Passing an optimistic check is NOT strict recovery.",
        "",
        "| Stress profile | Arm | Failed source states | Necessary precheck passed | Both strict stages recovered | Mean CVX | Mean CPU s |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in d["rows"]:
        md.append(
            f"| {r['profile']} | {r['arm']} | "
            f"{r['original_fixed_precheck_failed']} | "
            f"{r['precheck_passing']} | "
            f"{r['strict_both_recovered']} | "
            f"{r['mean_exact_calls'] if r['mean_exact_calls'] is not None else '—'} | "
            f"{r['mean_runtime_s']:.3f} |"
            if r["mean_runtime_s"] is not None else
            f"| {r['profile']} | {r['arm']} | "
            f"{r['original_fixed_precheck_failed']} | "
            f"{r['precheck_passing']} | "
            f"{r['strict_both_recovered']} | — | — |"
        )
    md +=[
        "",
        "These are selected failure-structure diagnoses (4 scenarios, nested",
        "algorithm seeds). No fair end-to-end optimizer advantage is claimed.",
        "All exact Stage-1/Stage-2 audit rules are inherited unchanged.",
        "Success/failure coverage and actual CPU cost are part of the result.",
    ]
    (args.output_dir/"report.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print("QUEUE_REPAIR_AGGREGATE="+json.dumps({
        "received":d["received_scenarios"],"rows":d["rows"],
        "errors":d["unexpected_errors"],
    },ensure_ascii=False),flush=True)
    if d["missing_scenarios"] or d["incomplete"] or d["unexpected_errors"]:
        raise RuntimeError("Incomplete repair matrix; partial results persisted")


if __name__=="__main__":main()
