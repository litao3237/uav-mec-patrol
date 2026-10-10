"""Aggregate the queue-aware optimistic certificate audit by independent scenario."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from run_model_sensitivity import METHODS, PROFILES


def aggregate(blocks):
    sources=("dynamically_reoptimized","baseline_structure_fixed")
    expected={(K,S) for K in (50,80) for S in (61,62,63,64)}
    found={}
    for p in blocks:
        key=(p["protocol"]["tasks"],p["protocol"]["scenario"])
        if key in found:
            raise ValueError(f"Duplicate queue-audit scenario {key}")
        found[key]=p
    rows=[
        {**r,"tasks":K,"scenario":S}
        for (K,S),payload in found.items()
        for r in payload.get("rows",[])
    ]
    result=[]
    for K in (50,80):
        for source in sources:
            for profile in PROFILES:
                for method in METHODS:
                    group=[
                        r for r in rows if r["tasks"]==K
                        and r["source"]==source
                        and r["profile"]==profile
                        and r["method"]==method
                    ]
                    reasons=Counter()
                    for r in group:
                        reasons.update(r["queue_reason_groups"])
                    result.append({
                        "tasks":K,
                        "source":source,
                        "profile":profile,
                        "method":method,
                        "attempted":len(group),
                        "previous_strict_stage1_qualified":sum(
                            r["prior_strict_stage1_qualified"] for r in group
                        ),
                        "old_precheck_rejected":sum(
                            not r["old_precheck_passed"] for r in group
                        ),
                        "new_queue_precheck_rejected":sum(
                            not r["new_queue_precheck_passed"] for r in group
                        ),
                        "extra_safe_rejections":sum(
                            r["extra_certified_infeasible"] for r in group
                        ),
                        "false_rejected_previously_strict":sum(
                            r["prior_strict_stage1_qualified"]
                            and not r["new_queue_precheck_passed"]
                            for r in group
                        ),
                        "extra_reason_groups":dict(reasons),
                        "previous_stage1_status_count":dict(Counter(
                            r["prior_solver_status"] for r in group
                        )),
                        "mean_queue_extension_s":(
                            mean(r["mean_task_queue_extension_s"] for r in group)
                            if group else None
                        ),
                        "max_queue_extension_s":(
                            max(r["max_task_queue_extension_s"] for r in group)
                            if group else None
                        ),
                        "scenarios_with_data":len({r["scenario"] for r in group}),
                    })
    return {
        "id":"queue_aware_precheck_audit_aggregate_v1",
        "expected_blocks":len(expected),
        "received_blocks":len(found),
        "missing_blocks":[list(k) for k in sorted(expected-set(found))],
        "incomplete_blocks":[list(k) for k,p in found.items() if not p.get("complete")],
        "total_samples":len(rows),
        "summary":result,
        "false_rejections":sum(
            r["false_rejected_previously_strict"] for r in result
        ),
    }


def markdown(data):
    lines=[
        "# Queue-aware optimistic FIFO/EDF feasibility certificate",
        "",
        "This is an **offline diagnostic** of the previously validated",
        "and failed fixed resource structures. Neither the old ALNS nor",
        "ESI is changed; no new CVXPY solver calls are required.",
        "",
        f"Archived samples checked: {data['total_samples']}; "
        f"scenario blocks {data['received_blocks']}/{data['expected_blocks']}; "
        f"false rejections of independently strict-validated Stage-1 "
        f"solutions: **{data['false_rejections']}**.",
        "",
        "| K | Source | Profile | Method | Audited | Old rejects | New rejects | Added sound certificates | Previously Strict Stage1 qualified |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in data["summary"]:
        lines.append(
            f"| {r['tasks']} | {r['source']} | {r['profile']} | "
            f"{r['method']} | {r['attempted']} | "
            f"{r['old_precheck_rejected']} | {r['new_queue_precheck_rejected']} | "
            f"{r['extra_safe_rejections']} | "
            f"{r['previous_strict_stage1_qualified']} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- Each removed structure is certified by an **optimistic timing**",
        "  bound that still gives each MEC UAV-pair the whole station",
        "  bandwidth/CPU but keeps local FIFO and same-pair MEC FIFO/EDF.",
        "- This is stronger than the old per-task bound, which ignores",
        "  local FIFO and preceding-batch queueing.",
        "- The method does **not** directly certify which overall original",
        "  optimization instance has no feasible route. It rejects",
        "  individual, already-fixed task/route/contact/offload assignments.",
        "- Previously strict-Stage1-validated reference snapshots are",
        "  treated as safety controls: none may be excluded by the new",
        "  optimistic bound or have saved completion times earlier than",
        "  these lower bounds beyond the numerical safety tolerance.",
        "- Passing this lower bound is not sufficient to prove full CVX",
        "  feasibility; it still ignores resource sharing across UAV pairs,",
        "  battery budgets and all other continuous constraints.",
        "- Aggregate attempted/strict qualification rates must be shown",
        "  beside any suggested faster evaluation; on its own this run",
        "  does not establish a new algorithm's equal-time improvement.",
    ])
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    paths=sorted(args.input_dir.rglob("queue-K*_S*.json"))
    if not paths:
        raise FileNotFoundError("No queue audit result JSON")
    d=aggregate([
        json.loads(p.read_text(encoding="utf-8")) for p in paths
    ])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    (args.output_dir/"report.md").write_text(markdown(d),encoding="utf-8")
    keys=list(d["summary"][0])
    with (args.output_dir/"summary.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader()
        for row in d["summary"]:
            w.writerow({
                k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                for k,v in row.items()
            })
    print("QUEUE_CERTIFICATE_AGGREGATE="+json.dumps({
        "total":d["total_samples"],
        "false_rejections":d["false_rejections"],
        "stronger":sum(x["extra_safe_rejections"] for x in d["summary"]),
        "by_scale_source":[
            {"tasks":K,"source":source,
             "old_rejections":sum(r["old_precheck_rejected"] for r in d["summary"]
                                 if r["tasks"]==K and r["source"]==source),
             "new_rejections":sum(r["new_queue_precheck_rejected"] for r in d["summary"]
                                 if r["tasks"]==K and r["source"]==source),
             "extra":sum(r["extra_safe_rejections"] for r in d["summary"]
                         if r["tasks"]==K and r["source"]==source)}
            for K in (50,80)
            for source in ("dynamically_reoptimized","baseline_structure_fixed")
        ],
    },ensure_ascii=False),flush=True)
    if d["missing_blocks"] or d["incomplete_blocks"] or d["false_rejections"]:
        raise RuntimeError("Missing/incomplete/unsound audit; partial summary saved")


if __name__=="__main__":
    main()
