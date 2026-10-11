"""Aggregate paired progressive infeasible bridge tests by independent scenario.

Original beam-depth2, deeper same score, deeper bridge-diverse all start from
the same frozen stage1-precheck-failing D. The output never treats the nested
algorithm RNG seeds as independent task-scenario replicates. Strict two-stage
qualification and actual total wall time are reported jointly.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import mean
import numpy as np

from atomic_batch_search import ARMS
from progressive_bridge_core import PROFILES


def aggregate(blocks,*,expected_scenarios):
    blockmap={}
    for b in blocks:
        scenario=int(b["protocol"]["scenario"])
        if scenario in blockmap:
            raise ValueError(f"Duplicate scenario archive {scenario}")
        blockmap[scenario]=b
    rows=[
        r for scenario,b in sorted(blockmap.items())
        for r in b.get("rows",[])
    ]
    eligible=[r for r in rows if r.get("eligible")]
    summary=[]
    for profile in PROFILES:
        obs=[r for r in rows if r["profile"]==profile]
        bad=[r for r in obs if r.get("eligible")]
        for arm in ARMS:
            measures=[r["arms"][arm] for r in bad if arm in r["arms"]]
            strictly=[r for r in measures if r.get("strict_both_recovered")]
            def avg(field):
                vals=[float(r[field]) for r in measures if r.get(field) is not None]
                return mean(vals) if vals else None
            summary.append({
                "profile":profile,"arm":arm,
                "attempts_all_original":len(obs),
                "original_precheck_infeasible_D":len(bad),
                "arm_attempts":len(measures),
                "strict_recovered":len(strictly),
                "paired_failure_scenarios":len({
                    r["scenario"] for r in bad
                }),
                "mean_total_wall_s":avg("total_wall_s"),
                "mean_stage1_oracle_calls":avg("strict_stage1_oracle_calls"),
                "mean_generated_unique":(
                    mean(r["search_diagnostics"].get(
                        "unique_candidates",
                        r["search_diagnostics"].get(
                            "unique_generated",0,
                        ),
                    ) for r in measures) if measures else None
                ),
                "mean_queue_precheck_passing":(
                    mean(r["search_diagnostics"].get(
                        "precheck_passing",
                        r["search_diagnostics"].get(
                            "queue_pass_candidates",0,
                        ),
                    ) for r in measures) if measures else None
                ),
                "soft_generation_overruns":sum(
                    r.get("search_diagnostics",{}).get(
                        "generation_soft_overrun",False,
                    ) for r in measures
                ),
                "unexpected_exceptions":sum(
                    bool(r.get("error_type")) for r in measures
                ),
            })
    method_summary={}
    for arm in ARMS:
        cases=defaultdict(list)
        for r in eligible:
            case=r["arms"].get(arm,{})
            if case.get("error_type"):
                continue
            cases[r["scenario"]].append(
                int(case.get("strict_both_recovered",False))
            )
        scenario_rates=[mean(v) for _,v in sorted(cases.items())]
        if len(scenario_rates)>=3:
            rng=np.random.default_rng(20261011)
            boot=rng.choice(
                scenario_rates,(10000,len(scenario_rates)),replace=True,
            ).mean(axis=1)
            interval=list(np.quantile(boot,[.025,.975]))
        else:
            interval=None
        method_summary[arm]={
            "strict_recovered":sum(
                bool(r["arms"].get(arm,{}).get("strict_both_recovered"))
                for r in eligible
            ),
            "eligible_failed_structures":len(eligible),
            "independent_scenarios_with_failed_structures":len(cases),
            "scenario_equal_mean_recovery_rate":(
                mean(scenario_rates) if scenario_rates else None
            ),
            "descriptive_scenario_bootstrap95":interval,
            "bootstrap_note":"only four independent scenarios, nested seeds are not iid replicates",
            "per_scenario_rates":{
                str(s):mean(v) for s,v in sorted(cases.items())
            },
            "mean_full_wall_s":(
                mean(r["arms"][arm]["total_wall_s"] for r in eligible
                     if r["arms"].get(arm,{}).get("total_wall_s") is not None)
                if any(r["arms"].get(arm,{}).get("total_wall_s") is not None
                       for r in eligible) else None
            ),
        }
    return {
        "protocol":"p1_atomic_MEC_coupled_repair_paired_summary_v1",
        "expected_scenarios":list(expected_scenarios),
        "received_scenarios":sorted(blockmap),
        "missing_scenarios":sorted(set(expected_scenarios)-set(blockmap)),
        "incomplete_scenarios":[s for s,b in blockmap.items()
                                if not b.get("complete")],
        "errors":[{"scenario":s,"errors":b.get("unexpected_errors")}
                  for s,b in blockmap.items() if b.get("unexpected_errors")],
        "original_source_states":len(rows),
        "eligible_failed_source_D":len(eligible),
        "by_profile":summary,
        "methods":method_summary,
    }


def markdown(data):
    lines=[
        "# Progressive infeasible-state bridge, paired Stage1/Stage2 strict repair",
        "",
        f"Scenarios {data['received_scenarios']}; "
        f"source states {data['original_source_states']}; "
        f"old necessary-precheck-infeasible D {data['eligible_failed_source_D']}.",
        "",
        "| Physical profile | Arm | Eligible | Strictly restored | Avg wall seconds | Mean Stage-1 oracle calls |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in data["by_profile"]:
        sec=row["mean_total_wall_s"]
        cvx=row["mean_stage1_oracle_calls"]
        lines.append(
            f"| {row['profile']} | {row['arm']} | "
            f"{row['original_precheck_infeasible_D']} | "
            f"{row['strict_recovered']} | "
            f"{sec:.3f} | {cvx:.2f} |"
            if sec is not None and cvx is not None else
            f"| {row['profile']} | {row['arm']} | "
            f"{row['original_precheck_infeasible_D']} | "
            f"{row['strict_recovered']} | — | — |"
        )
    lines +=[
        "",
        "## Interpretation",
        "",
        "- All arms use the exact same precheck-infeasible archived B-ALNS D.",
        "- Plain depth4 and bridge depth4 share operator generator, depth,",
        "  beam width, soft generation time cap and max Stage-1 oracle quota.",
        "- Bridge-only changes WHICH temporary infeasible intermediates",
        "  survive in the beam. Stage-1 is never called for queue-infeasible D.",
        "- Equal strict CVX quota is not equal end-to-end runtime; always",
        "  report actual wall time and numerical solver failures.",
        "- A temporarily infeasible intermediate is not counted as a",
        "  recovered structure unless final Stage1+Stage2 independently pass.",
        "- These results are exploratory if scenarios have informed prior",
        "  method design. Only unused scenes constitute a holdout.",
        "- A corrected algorithm integrated with an actual ALNS loop and",
        "  equal end-to-end time is required before claiming superiority.",
    ]
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--scenarios",default="61,62,63,64")
    args=p.parse_args()
    paths=sorted(args.input_dir.rglob("atomic-K80_S*.json"))
    if not paths:raise FileNotFoundError("No original or new bridge scenario results")
    data=aggregate(
        [json.loads(f.read_text(encoding="utf-8")) for f in paths],
        expected_scenarios=tuple(int(x) for x in args.scenarios.split(",") if x),
    )
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"summary.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",
    )
    (args.output_dir/"report.md").write_text(
        markdown(data),encoding="utf-8",
    )
    keys=list(data["by_profile"][0])
    with (args.output_dir/"summary.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=keys)
        writer.writeheader()
        for row in data["by_profile"]:
            writer.writerow(row)
    print("ATOMIC_AGGREGATE="+json.dumps({
        "eligible":data["eligible_failed_source_D"],
        "methods":data["methods"],
        "missing":data["missing_scenarios"],
        "errors":data["errors"],
    },ensure_ascii=False),flush=True)
    if data["missing_scenarios"] or data["incomplete_scenarios"] or data["errors"]:
        raise RuntimeError("Incomplete bridge matrix; partial results persisted")


if __name__=="__main__":
    main()
