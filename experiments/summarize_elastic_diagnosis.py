"""Aggregate elastic resource diagnostic evidence without mixing scenarios/seeds.

All source results are immutable from GitHub Actions 38043248604. This does
NOT provide labels of global infeasibility. A numerically positive weighted
slack after relaxing only deadline/avg delay/cycle/battery is a conflict
indicator for that exact fixed route/contact/mode decision; nonoptimal elastic
status is inconclusive. Report controls and solver failures explicitly.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from run_model_sensitivity import METHODS, PROFILES
from uav_mec.optimization.resource.elastic_diagnosis import PROTOCOLS


def aggregate(blocks, *, expected=((50,61),(80,61),(80,62),(80,63),(80,64))):
    received={}
    for p in blocks:
        block=(int(p["protocol"]["tasks"]),int(p["protocol"]["independent_scenario_seed"]))
        if block in received:
            raise ValueError(f"Duplicate experimental block {block}")
        received[block]=p
    missing=sorted(set(expected)-set(received))
    flat=[
        r for b in received.values() for r in b.get("rows",[])
    ]
    summary=[]
    for K in sorted({k for k,_ in expected}):
        for profile in PROFILES:
            for method in METHODS:
                sample=[r for r in flat
                        if r.get("tasks")==K and r.get("profile")==profile
                        and r.get("method")==method]
                for mode in PROTOCOLS:
                    valid=[r for r in sample
                           if r.get("diagnoses",{}).get(mode,{}).get("numerically_credible")]
                    positive=[r for r in valid
                              if r["diagnoses"][mode]["normalized_total_elastic_slack"]>.002]
                    controls=[r for r in sample if r.get("original_stage1_qualified")]
                    conflicts=Counter()
                    for r in positive:
                        for f,v in r["diagnoses"][mode]["slack_sum_by_family"].items():
                            conflicts[f]+=v
                    top_constraints=Counter()
                    for r in positive:
                        for item in r["diagnoses"][mode].get("top_constraints",[])[:1]:
                            top_constraints[item["family"]]+=1

                    # Comparable paired mode effect on SAME fixed D. One
                    # method profile per archived original ALNS result.
                    reductions=defaultdict(list)
                    cpu_bw_relaxed=defaultdict(list)
                    if mode=="qos_plus_mec_capacity":
                        for r in valid:
                            q=r["diagnoses"].get("qos_only",{})
                            both=r["diagnoses"].get(mode,{})
                            if not q.get("numerically_credible"):
                                continue
                            S=r["scenario"]
                            reductions[S].append(
                                q["normalized_total_elastic_slack"]-
                                both["normalized_total_elastic_slack"]
                            )
                            caps=both.get("slack_sum_by_family",{})
                            cpu_bw_relaxed[S].append(
                                caps.get("mec_cpu_cap",0.)+caps.get("bandwidth_cap",0.)
                            )
                    summarize_scene=lambda x: (
                        mean(mean(v) for s,v in sorted(x.items()))
                        if x else None
                    )
                    summary.append({
                        "tasks":K,
                        "profile":profile,
                        "method":method,
                        "mode":mode,
                        "attempted":len(sample),
                        "independent_scenarios":len({r["scenario"] for r in sample}),
                        "previous_stage1_strict_qualified":len(controls),
                        "previous_stage2_strict_qualified":sum(
                            r.get("original_stage2_qualified",False) for r in sample
                        ),
                        "old_precheck_failed":sum(
                            not r.get("old_passed",False) for r in sample
                        ),
                        "queue_precheck_failed":sum(
                            not r.get("queue_passed",False) for r in sample
                        ),
                        "source_stage1_status":dict(Counter(
                            r.get("original_stage1_status","missing")
                            for r in sample
                        )),
                        "elastic_numerically_credible":len(valid),
                        "elastic_positive_relaxation":len(positive),
                        "elastic_inconclusive":len(sample)-len(valid),
                        "credible_control_violations":sum(
                            r["diagnoses"][mode]["normalized_total_elastic_slack"]>.002
                            for r in controls if r["diagnoses"][mode]["numerically_credible"]
                        ),
                        "normalized_conflict_by_family":dict(conflicts),
                        "dominant_conflict_count":dict(top_constraints),
                        "mean_normalized_total_slack_credible":(
                            mean(r["diagnoses"][mode]["normalized_total_elastic_slack"]
                                 for r in valid) if valid else None
                        ),
                        "mean_diagnostic_wall_s":(
                            mean(r["diagnoses"][mode]["diagnostic_build_and_solve_s"]
                                 for r in sample if r["diagnoses"].get(mode)
                                 and r["diagnoses"][mode].get("diagnostic_build_and_solve_s") is not None)
                            if any(r["diagnoses"].get(mode)
                                   and r["diagnoses"][mode].get("diagnostic_build_and_solve_s") is not None
                                   for r in sample) else None
                        ),
                        "paired_qos_to_plus_capacity_objective_reduction":summarize_scene(reductions),
                        "paired_normalized_capacity_relaxation":summarize_scene(cpu_bw_relaxed),
                    })

    return {
        "protocol":"elastic_fixed_D_resource_conflict_summary_v1",
        "expected_blocks":[list(k) for k in expected],
        "received_blocks":[list(k) for k in sorted(received)],
        "missing_blocks":[list(k) for k in missing],
        "incomplete_blocks":[list(k) for k,p in received.items() if not p.get("complete")],
        "unexpected_exceptions":[{
            "block":list(k),
            "errors":p.get("unhandled_program_errors",[]),
        } for k,p in received.items() if p.get("unhandled_program_errors")],
        "total_source_records":len(flat),
        "strict_source_valid":sum(r.get("original_stage1_qualified",False) for r in flat),
        "control_false_conflict_reports":sum(len(r.get("control_warning",[])) for r in flat),
        "summary":summary,
    }


def markdown(d):
    lines=[
        "# Elastic resource-conflict diagnosis — frozen original B/ESI structures",
        "",
        f"Received scenario blocks {len(d['received_blocks'])}/{len(d['expected_blocks'])}, "
        f"source structures {d['total_source_records']}; missing {d['missing_blocks']}.",
        "",
        "Every outcome preserves source solver status, rigorous old and",
        "queue-aware necessary bound, an independent scaled elastic conic",
        "model (QoS-only) and a hypothetical hardware-capacity-relaxation",
        "counterfactual. Fixed UAV paths, contacts and task decisions",
        "never change; the original P1-R algorithm and Stage-2 acceptance",
        "are NOT modified.",
        "",
        "| K | Profile | Method | Elastic mode | Credible | Positive slack | Original Stage1 valid | Inconclusive | Dominant normalized family |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for r in d["summary"]:
        tops=sorted(r["dominant_conflict_count"].items(),
                    key=lambda x:(-x[1],x[0]))
        dominant=",".join(f"{k}:{v}" for k,v in tops[:3]) or "—"
        lines.append(
            f"| {r['tasks']} | {r['profile']} | {r['method']} | {r['mode']} | "
            f"{r['elastic_numerically_credible']}/{r['attempted']} | "
            f"{r['elastic_positive_relaxation']} | "
            f"{r['previous_stage1_strict_qualified']} | "
            f"{r['elastic_inconclusive']} | {dominant} |"
        )
    lines += [
        "",
        "## Strict interpretation",
        "",
        "This is a **diagnostic** and not a globally certified minimal",
        "infeasible subsystem. A positive normalized elastic optimum",
        "suggests how much fixed-D constraints conflict only when",
        "a conic solver returned optimal with acceptable hard/soft",
        "residuals. Solver-error or optimal_inaccurate rows are inconclusive.",
        "",
        "The QoS-only mode relaxes task deadline, mean delay, UAV patrol",
        "cycle and UAV battery, keeping shared MEC bandwidth/CPU hard;",
        "the second mode additionally permits hypothetical extra",
        "aggregate MEC bandwidth/CPU (still preserving FIFO/EDF).",
        "Units are recovered from the positive scaling factors in",
        "the original numerical_scaling=True P1-R formulation.",
        "",
        "The weighted sum of per-constraint normalized slacks is not",
        "a causal blame score: many optimum relaxations can trade off",
        "against each other and changing the weights changes attributions.",
        "Saved local/MEC predecessors attached to the most violated",
        "deadlines are dependency *candidates*, not formal minimal cores.",
        "",
        "Strict Stage-1 controls should yield near-zero slack. All",
        "controls, failures, solver warnings and anomalous results",
        "are preserved; do not report energy on elastic-only solutions.",
        "",
        "Next: only after inspecting conflict evidence, compare targeted",
        "structural repairs under matched strict Stage-1/Stage-2 and",
        "end-to-end time budgets on new independent scenarios.",
    ]
    return "\n".join(lines)+"\n"


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--input-dir",type=Path,required=True)
    a.add_argument("--output-dir",type=Path,required=True)
    args=a.parse_args()
    paths=sorted(args.input_dir.rglob("elastic-K*_S*.json"))
    if not paths:
        raise FileNotFoundError("No elastic diagnostic JSON artifacts")
    data=aggregate([
        json.loads(p.read_text(encoding="utf-8")) for p in paths
    ])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",
    )
    (args.output_dir/"report.md").write_text(markdown(data),encoding="utf-8")
    fields=list(data["summary"][0])
    with (args.output_dir/"summary.csv").open(
        "w",encoding="utf-8",newline="",
    ) as out:
        writer=csv.DictWriter(out,fieldnames=fields)
        writer.writeheader()
        for row in data["summary"]:
            writer.writerow({
                k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                for k,v in row.items()
            })
    q=[r for r in data["summary"] if r["mode"]=="qos_only"]
    print("ELASTIC_AGGREGATE="+json.dumps({
        "blocks":len(data["received_blocks"]),
        "source_records":data["total_source_records"],
        "controls_with_positive_slack":data["control_false_conflict_reports"],
        "profiles":[{
            k:r[k] for k in (
                "tasks","profile","method","mode","attempted",
                "previous_stage1_strict_qualified",
                "elastic_numerically_credible",
                "elastic_positive_relaxation","elastic_inconclusive",
                "dominant_conflict_count"
            )
        } for r in q],
    },ensure_ascii=False),flush=True)
    if (data["missing_blocks"] or data["incomplete_blocks"]
            or data["unexpected_exceptions"]):
        raise RuntimeError("Missing or errored elastic diagnostic block; partial report preserved")


if __name__=="__main__":
    main()
