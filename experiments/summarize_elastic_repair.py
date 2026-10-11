"""Aggregate per-structure strict feasibility recovery from elastic-guided trials."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from statistics import mean

from elastic_repair_core import ARM_NAMES

STRESS_PROFILES=("compute_x1p5","compute_x2p0","deadline_x0p9","deadline_x0p8")

def aggregate(blocks,*,expected=(61,62,63,64)):
    indexed={}
    for payload in blocks:
        s=int(payload["protocol"]["scenario"])
        if s in indexed:raise ValueError(f"Duplicate source scenario {s}")
        indexed[s]=payload
    flat=[r for _,p in sorted(indexed.items()) for r in p.get("rows",[])]
    table=[]
    for profile in STRESS_PROFILES:
        attempted=[r for r in flat if r["profile"]==profile]
        eligible=[r for r in attempted if r["eligible"]]
        for arm in ARM_NAMES:
            answers=[r["arms"][arm] for r in eligible if arm in r["arms"]]
            valid=[r for r in answers if r.get("strict_both_recovered")]
            def mean_available(key):
                vals=[r[key] for r in answers if r.get(key) is not None]
                return mean(vals) if vals else None
            table.append({
                "profile":profile,"arm":arm,
                "source_attempts":len(attempted),
                "source_precheck_failure":len(eligible),
                "independent_scenarios_source_failed":len({
                    r["scenario"] for r in eligible
                }),
                "arm_attempts":len(answers),
                "optimistic_pass_any":sum(
                    bool(r.get("precheck_passed_candidates")) for r in answers
                ),
                "strict_stage1_stage2_recovered":len(valid),
                "mean_stage1_cvx_calls":mean_available("strict_cvx_calls"),
                "mean_generated_structural_candidates":mean_available("generated_unique"),
                "mean_runtime_s_including_elastic_diagnosis":mean_available(
                    "total_s_including_diagnostic"
                ),
                "errors":sum(bool(r.get("error_type")) for r in answers),
            })
    return {
        "id":"elastic_slack_guided_joint_repair_summary_v1",
        "expected_scenarios":list(expected),
        "received_scenarios":sorted(indexed),
        "missing_scenarios":sorted(set(expected)-set(indexed)),
        "incomplete_scenarios":[s for s,p in indexed.items() if not p.get("complete")],
        "unexpected_errors":[{
            "scenario":s,"error":p.get("unexpected_errors",[])
        } for s,p in indexed.items() if p.get("unexpected_errors")],
        "source_state_records":len(flat),
        "original_lb_infeasible_states":sum(r.get("eligible",False) for r in flat),
        "summary":table,
    }

def markdown(d):
    lines=[
        "# Elastic-resource-guided feasibility repair on archived failed structures",
        "",
        f"Blocks {len(d['received_scenarios'])}/{len(d['expected_scenarios'])}; "
        f"old optimistic precheck failures {d['original_lb_infeasible_states']}.",
        "",
        "Every comparison arm starts at the same failed D, and only",
        "unchanged Stage-1 + Stage-2 + two physical residual timelines",
        "count as strict repair success. This trial is NOT equal wall time.",
        "",
        "| Stress | Arm | Eligible | Optimistic admission | Both stages recovered | Mean Stage-1 CVX | Mean seconds including diagnosis |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in d["summary"]:
        cvx=r["mean_stage1_cvx_calls"]
        tm=r["mean_runtime_s_including_elastic_diagnosis"]
        lines.append(
            f"| {r['profile']} | {r['arm']} | "
            f"{r['source_precheck_failure']} | "
            f"{r['optimistic_pass_any']} | "
            f"{r['strict_stage1_stage2_recovered']} | "
            f"{cvx:.2f} | {tm:.3f} |"
            if cvx is not None and tm is not None else
            f"| {r['profile']} | {r['arm']} | "
            f"{r['source_precheck_failure']} | "
            f"{r['optimistic_pass_any']} | "
            f"{r['strict_stage1_stage2_recovered']} | — | — |"
        )
    lines.extend([
        "",
        "### Interpretation",
        "",
        "- Old S61–S64 failures were used to design this mechanism;",
        "  they are not an independent holdout.",
        "- Equal depth/beam/CVX candidate limits do not mean equal wall time.",
        "  Elastic arms are explicitly charged their full source-D solve.",
        "- Optimistic passing rates across different necessary bounds are",
        "  not comparable measures of strict Stage-1/Stage-2 recovery.",
        "- A numeric optimal_inaccurate status is never considered a",
        "  mathematical proof of global infeasibility.",
        "- A new independent scene and algorithm seed holdout is required",
        "  before proposing an algorithmic improvement for the paper.",
    ])
    return "\n".join(lines)+"\n"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    files=sorted(args.input_dir.rglob("elastic-repair-K80_S*.json"))
    if not files:raise FileNotFoundError("No per-scenario elastic repair JSON")
    d=aggregate([json.loads(f.read_text(encoding="utf-8")) for f in files])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    (args.output_dir/"report.md").write_text(markdown(d),encoding="utf-8")
    keys=list(d["summary"][0])
    with (args.output_dir/"summary.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(d["summary"])
    totals=[
        {"arm":arm,
         "strict_recovered":sum(r["strict_stage1_stage2_recovered"]
                                for r in d["summary"] if r["arm"]==arm),
         "eligible":d["original_lb_infeasible_states"]}
        for arm in ARM_NAMES
    ]
    print("ELASTIC_REPAIR_AGGREGATE="+json.dumps({
        "source_states":d["source_state_records"],
        "eligible":d["original_lb_infeasible_states"],
        "totals":totals,
        "missing":d["missing_scenarios"],
        "unexpected_errors":d["unexpected_errors"],
    },ensure_ascii=False),flush=True)
    if d["missing_scenarios"] or d["incomplete_scenarios"] or d["unexpected_errors"]:
        raise RuntimeError("Incomplete elastic-guided repair matrix; partial report saved")

if __name__=="__main__":
    main()
