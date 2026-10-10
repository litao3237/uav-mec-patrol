"""Aggregate QoS-hard MEC-capacity-only diagnosis across paired original instances."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from statistics import mean


def aggregate(payloads,expected=((50,61),(80,61),(80,62),(80,63),(80,64))):
    blocks={}
    for p in payloads:
        pair=(int(p["protocol"]["tasks"]),int(p["protocol"]["independent_scenario_seed"]))
        if pair in blocks:raise ValueError(f"Duplicate source block {pair}")
        blocks[pair]=p
    rows=[{**row,"tasks":K,"scenario":S}
          for (K,S),p in blocks.items() for row in p["rows"]]
    summary=[]
    for K in sorted({x[0] for x in expected}):
        for profile in sorted({r["profile"] for r in rows if r["tasks"]==K}):
            for method in ("B-ALNS","ESI-ALNS"):
                group=[r for r in rows
                       if r["tasks"]==K and r["profile"]==profile
                       and r["method"]==method]
                qos=[r for r in group if r["qos_only_positive"]]
                capacity_success=[r for r in qos
                                  if r["capacity_only"]["numerically_credible"]]
                cap_optimal=[r for r in group
                             if r["capacity_only"]["numerically_credible"]]
                summary.append({
                    "tasks":K,"profile":profile,"method":method,
                    "attempted":len(group),
                    "scenarios":len({r["scenario"] for r in group}),
                    "qos_conflict_positive":len(qos),
                    "original_stage1_valid":sum(
                        r["original_stage1_qualified"] for r in group
                    ),
                    "capacity_only_numerically_credible":len(cap_optimal),
                    "capacity_only_solver_infeasible":sum(
                        r["capacity_only"]["status"]=="infeasible" for r in group
                    ),
                    "capacity_only_unresolved":sum(
                        not r["capacity_only"]["numerically_credible"] and
                        r["capacity_only"]["status"] not in (
                            "infeasible","no_applicable_elastic_capacity_constraints"
                        ) for r in group
                    ),
                    "capacity_only_hard_QoS_restored_for_qos_conflicts":len(capacity_success),
                    "mean_extra_station_cpu_normalized_given_capacity_recovery":(
                        mean(r["capacity_only"]["slack_sum_by_family"].get(
                            "mec_cpu_cap",0.0) for r in capacity_success
                        ) if capacity_success else None
                    ),
                    "mean_extra_station_bw_normalized_given_capacity_recovery":(
                        mean(r["capacity_only"]["slack_sum_by_family"].get(
                            "bandwidth_cap",0.0) for r in capacity_success
                        ) if capacity_success else None
                    ),
                    "controls_false_extra_station_cap":sum(
                        r["original_stage1_qualified"] and
                        r["capacity_only"]["numerically_credible"] and
                        r["capacity_only"]["normalized_total_elastic_slack"]>.002
                        for r in group
                    ),
                    "all_statuses":dict(Counter(r["capacity_only"]["status"] for r in group)),
                })
    return {
        "protocol":"mec_capacity_only_diagnosis_summary_v1",
        "received":[list(pair) for pair in sorted(blocks)],
        "expected":[list(pair) for pair in expected],
        "missing":[list(pair) for pair in sorted(set(expected)-set(blocks))],
        "incomplete":[list(pair) for pair,p in blocks.items() if not p.get("complete")],
        "errors":[{"block":list(pair),"errors":p.get("unexpected_errors",[])}
                  for pair,p in blocks.items() if p.get("unexpected_errors")],
        "source_records":len(rows),
        "summary":summary,
    }


def markdown(d):
    lines=[
        "# MEC CPU/bandwidth capacity-only counterfactual diagnosis",
        "",
        "This is *not* a new UAV routing algorithm. Fix route/contact/mode,",
        "keep actual task deadlines, average task delay, UAV return cycle",
        "and battery as HARD constraints and permit only hypothetical",
        "MEC bandwidth/CPU station capacity increases. The original",
        "published resource allocation remains unchanged.",
        "",
        f"Blocks {len(d['received'])}/{len(d['expected'])}; source records {d['source_records']}.",
        "",
        "| K | Physical factor | Method | Source | Prior QoS conflict | MEC-upgrade-only yields an optimal slack solution | Solver says infeasible |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for r in d["summary"]:
        lines.append(
            f"| {r['tasks']} | {r['profile']} | {r['method']} | "
            f"{r['attempted']} | {r['qos_conflict_positive']} | "
            f"{r['capacity_only_hard_QoS_restored_for_qos_conflicts']} | "
            f"{r['capacity_only_solver_infeasible']} |"
        )
    lines.extend([
        "",
        "### Limitations",
        "",
        "A conic solver reporting infeasible for a fixed-D capacity-only",
        "counterfactual is *numerical evidence*, not a formal mathematical",
        "certificate for the entire UAV-MEC routing problem.",
        "",
        "If simply expanding MEC station bandwidth and CPU still cannot",
        "satisfy hard task deadlines, then repairing the **original route,",
        "contact sequence, local FIFO queue or task execution mode** is",
        "likely necessary for this fixed-D case. However, per-task local",
        "CPU and contact/flight timing also remain HARD; a positive",
        "counterfactual MEC slack would not itself be an admissible",
        "decision under the real hardware model.",
        "",
        "Do not interpret the normalized sum of capacity slack as a causal",
        "price of upgrading MEC resources. Optimal allocation under a",
        "different diagnostic penalty could select a different mix.",
        "No elastic-only point is counted as a real strictly feasible",
        "Stage-1 + Stage-2 result.",
    ])
    return "\n".join(lines)+"\n"


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--input-dir",type=Path,required=True)
    a.add_argument("--output-dir",type=Path,required=True)
    args=a.parse_args()
    files=sorted(args.input_dir.rglob("capacity-K*_S*.json"))
    if not files:raise FileNotFoundError("No capacity-only diagnostic data")
    d=aggregate([json.loads(p.read_text(encoding="utf-8")) for p in files])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.output_dir/"report.md").write_text(markdown(d),encoding="utf-8")
    fields=list(d["summary"][0])
    with (args.output_dir/"summary.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for r in d["summary"]:
            w.writerow({
                k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                for k,v in r.items()
            })
    print("CAPACITY_AGGREGATE="+json.dumps({
        "source_records":d["source_records"],
        "missing":d["missing"],
        "K80_profiles":[{
            k:r[k] for k in (
                "profile","method","attempted","qos_conflict_positive",
                "capacity_only_hard_QoS_restored_for_qos_conflicts",
                "capacity_only_solver_infeasible","capacity_only_unresolved",
                "controls_false_extra_station_cap"
            )
        } for r in d["summary"] if r["tasks"]==80],
    },ensure_ascii=False),flush=True)
    if d["missing"] or d["incomplete"] or d["errors"]:
        raise RuntimeError("Incomplete capacity-only matrix; partial evidence saved")


if __name__=="__main__":main()
