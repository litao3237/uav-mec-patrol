"""Aggregate fresh S71-S74 elastic-guided repair without treating seeds as iid."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

import numpy as np

from elastic_repair_core import ARM_NAMES
from summarize_elastic_repair import aggregate as pilot_aggregate,markdown as pilot_markdown

EXPECTED=(71,72,73,74)


def summarize_holdout(inputs):
    outcomes=[]
    source_records=[]
    metas=[]
    for path in sorted(inputs.rglob("elastic-repair-K80_S*.json")):
        outcomes.append(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted(inputs.rglob("fresh-source-K80_S*.json")):
        source_records.append(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted(inputs.rglob("holdout-protocol-K80_S*.json")):
        metas.append(json.loads(path.read_text(encoding="utf-8")))
    data=pilot_aggregate(outcomes,expected=EXPECTED)
    actual={p["protocol"]["scenario"]:p for p in outcomes}
    missing_original=sorted(set(EXPECTED)-{
        p["protocol"]["independent_scenario_seed"] for p in source_records
    })
    missing_metadata=sorted(set(EXPECTED)-{m["scenario"] for m in metas})
    data["missing_original_scenario_outputs"]=missing_original
    data["missing_holdout_protocol"]=missing_metadata
    data["original_source_stage1_counts"]={
        f"{profile}/{method}":{
            "attempted":sum(
                r["profile"]==profile and r["method"]==method
                for source in source_records for r in source["rows"]
            ),
            "strict_stage1":sum(
                r["profile"]==profile and r["method"]==method
                and r.get("stage1_qualified",False)
                for source in source_records for r in source["rows"]
            ),
            "strict_stage2":sum(
                r["profile"]==profile and r["method"]==method
                and r.get("both_qualified",False)
                for source in source_records for r in source["rows"]
            ),
        }
        for profile in (
            "baseline","compute_x1p5","compute_x2p0",
            "deadline_x0p9","deadline_x0p8"
        )
        for method in ("B-ALNS","ESI-ALNS")
    }
    flattened=[
        r for p in outcomes for r in p["rows"] if r.get("eligible")
    ]
    rng=np.random.default_rng(20261011)
    methods={}
    for arm in ARM_NAMES:
        grouped=defaultdict(list)
        for r in flattened:
            grouped[r["scenario"]].append(
                int(bool(r["arms"].get(arm,{}).get("strict_both_recovered")))
            )
        means=[mean(v) for _,v in sorted(grouped.items())]
        if len(means)>=3:
            samples=rng.choice(
                means,size=(10000,len(means)),replace=True
            ).mean(axis=1)
            interval=list(np.quantile(samples,[.025,.975]))
        else:interval=None
        methods[arm]={
            "strict_recovered":sum(
                v for values in grouped.values() for v in values
            ),
            "paired_eligible_total":len(flattened),
            "independent_scenarios_with_failed_D":len(grouped),
            "per_scenario_recovery_fraction":{
                str(k):mean(v) for k,v in sorted(grouped.items())
            },
            "descriptive_scenario_bootstrap_interval":interval,
            "bootstrap_caveat":"only four independent scenes; not a significance claim",
        }
    data["holdout_method_results"]=methods
    data["holds_unseen_scene_metadata_verified"]=(
        not data["missing_scenarios"]
        and not missing_original
        and not missing_metadata
        and all(p.get("complete") for p in metas)
    )
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    data=summarize_holdout(args.input_dir)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"holdout-summary.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    additional=[
        "",
        "## Fresh-scene holdout (independent S71-S74, nested A117/A118)",
        "",
        "| Repair arm | Strictly recovered original failed D | Eligible source failures |",
        "| --- | ---: | ---: |",
    ]
    for arm,r in data["holdout_method_results"].items():
        additional.append(
            f"| {arm} | {r['strict_recovered']} | {r['paired_eligible_total']} |"
        )
    additional +=[
        "",
        "Original strict Stage-1+Stage-2 success (B-ALNS/ESI) is recorded",
        "separately. This is CONDITIONAL recovery after an already-run",
        "B-ALNS source, not a demonstrated equal-runtime full ALNS algorithm.",
        "",
    ]
    (args.output_dir/"holdout-report.md").write_text(
        pilot_markdown(data)+"\n".join(additional)+"\n",encoding="utf-8"
    )
    with (args.output_dir/"per-profile.csv").open(
        "w",newline="",encoding="utf-8"
    ) as f:
        keys=list(data["summary"][0])
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader()
        w.writerows(data["summary"])
    print("ELASTIC_HOLDOUT_AGGREGATE="+json.dumps({
        "total_archived_failed_starts":data["original_lb_infeasible_states"],
        "strict_recovery":data["holdout_method_results"],
        "source_stage1_counts":data["original_source_stage1_counts"],
        "missing":data["missing_scenarios"],
    },ensure_ascii=False),flush=True)
    if (data["missing_scenarios"] or data["incomplete_scenarios"]
            or data["unexpected_errors"] or not data["holds_unseen_scene_metadata_verified"]):
        raise RuntimeError("Unfinished fresh-scene validation; partial statistics preserved")


if __name__=="__main__":
    main()
