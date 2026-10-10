"""Summarize certificate-targeted repair outcome and failure reasons."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from run_highload_rescue_probe import ARMS,STRESS_PROFILES


def aggregate(blocks):
    expected=[61,62,63,64]
    unique={}
    for payload in blocks:
        p=payload["protocol"]
        key=int(p["scenario"])
        if key in unique:
            raise ValueError(f"Duplicate rescued scenario {key}")
        unique[key]=payload
    missing=[s for s in expected if s not in unique]
    rows=[r for p in unique.values() for r in p.get("rows",[])]
    summary=[]
    for profile in STRESS_PROFILES:
        sample=[r for r in rows if r["profile"]==profile]
        failed=[r for r in sample if r["repair_eligible"]]
        orig_status=Counter(r["source_stage1_status"] for r in sample)
        offenders=Counter()
        for r in failed:
            offenders.update(r["original_score"]["offenders_by_execution_mode"])
        for arm in ARMS:
            eligible=[
                r["arms"][arm] for r in failed if arm in r["arms"]
            ]
            recovered=[r for r in eligible if r.get("both_qualified")]
            summary.append({
                "profile":profile,"arm":arm,
                "attempted_failed_precheck_structures":len(failed),
                "scenarios_with_eligible":len({
                    r["scenario"] for r in failed
                }),
                "original_stage1_status_counts":dict(orig_status),
                "original_task_offender_counts":dict(offenders),
                "eligible_arm_runs":len(eligible),
                "precheck_restored":sum(
                    r.get("n_precheck_pass",0)>0 for r in eligible
                ),
                "strict_stage1_recovered":sum(
                    r.get("stage1_qualified",False) for r in eligible
                ),
                "strict_both_recovered":len(recovered),
                "mean_repair_total_s":(
                    mean(r["runtime_s"] for r in eligible
                         if r.get("runtime_s") is not None)
                    if any(r.get("runtime_s") is not None for r in eligible)
                    else None
                ),
                "mean_unique_generated":(
                    mean(r.get("n_candidates_generated",0) for r in eligible)
                    if eligible else None
                ),
                "errors":sum("error_type" in r for r in eligible),
            })
    return {
        "protocol":"certificate_repair_probe_summary_v1",
        "received_scenarios":sorted(unique),
        "expected_scenarios":expected,
        "missing":missing,
        "incomplete":[s for s,p in unique.items() if not p.get("complete")],
        "total_scenario_arms":len(rows)*len(ARMS),
        "unexpected_errors":[{"scenario":s,"errors":p.get("errors",[])}
             for s,p in unique.items() if p.get("errors")],
        "rows":summary,
    }


def markdown(summary):
    lines=[
        "# High-load optimistic-bound-infeasible discrete-solution repair probe",
        "",
        "Source: previously recorded B-ALNS stress-condition solutions from",
        "coupling sensitivity experiment, **only** instances with strictly",
        "certified infeasible fixed structures under the optimistic time",
        "lower bound are eligible. `optimal_inaccurate` numerical failures",
        "are not treated as certified structural infeasibility.",
        "",
        f"Scenarios: {summary['received_scenarios']}; missing {summary['missing']}.",
        "",
        "| Stress profile | Arm | LB-infeasible cases | Necessary precheck rescued | Strict Stage1 + Stage2 rescued | Repair CPU seconds |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in summary["rows"]:
        t=r["mean_repair_total_s"]
        lines.append(
            f"| {r['profile']} | {r['arm']} | "
            f"{r['attempted_failed_precheck_structures']} | "
            f"{r['precheck_restored']} | "
            f"{r['strict_both_recovered']} | "
            f"{t:.2f}" if t is not None else
            f"| {r['profile']} | {r['arm']} | "
            f"{r['attempted_failed_precheck_structures']} | "
            f"{r['precheck_restored']} | "
            f"{r['strict_both_recovered']} | —"
        )
        lines[-1]+=" |"
    lines += [
        "",
        "All results are a **diagnostic probe**, not a matched-time algorithm",
        "comparison. Guided methods enumerate structural candidates and",
        "strictly validate a capped shortlist; CPU cost must be reported.",
        "A failing solution may still be globally reparable with more",
        "complex/multi-UAV moves; this test cannot certify global infeasibility.",
        "No numerical Stage-1/2 standard is relaxed in any arm.",
        "",
    ]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    files=sorted(args.input_dir.rglob("rescue-K80_S*.json"))
    if not files:
        raise FileNotFoundError("No rescue results found")
    data=aggregate([
        json.loads(path.read_text(encoding="utf-8"))
        for path in files
    ])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    (args.output_dir/"report.md").write_text(
        markdown(data),encoding="utf-8"
    )
    fields=list(data["rows"][0])
    with (args.output_dir/"summary.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for row in data["rows"]:
            w.writerow({
                k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                for k,v in row.items()
            })
    print("RESCUE_AGGREGATE="+json.dumps({
        "received":data["received_scenarios"],
        "errors":data["unexpected_errors"],
        "rows":[{
            k:r[k] for k in
            ("profile","arm","attempted_failed_precheck_structures",
             "precheck_restored","strict_both_recovered")
        } for r in data["rows"]],
    },ensure_ascii=False),flush=True)
    if data["missing"] or data["incomplete"] or data["unexpected_errors"]:
        raise RuntimeError("Missing/incomplete/erroneous repair results; partial summary saved")


if __name__=="__main__":
    main()
