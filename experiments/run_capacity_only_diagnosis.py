"""Isolate shared MEC capacity pressure from temporal/route feasibility.

Use the EXACT discrete structures previously diagnosed by independent elastic
QoS and QoS+capacity counterfactuals. Here, task deadlines, mean delay,
patrol cycle and UAV battery remain HARD; only the MEC station aggregate
bandwidth and CPU capacity limits may expand through nonnegative normalized
slacks, with all FIFO/EDF and processing constraints kept hard.

This is a diagnostic counterfactual, NOT permission to exceed real
MEC hardware or proof of global infeasibility. A supported original
feasible control must require approximately zero extra MEC capacity.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from statistics import mean

from experiment_common import current_source_hashes, provenance
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.optimization.resource.elastic_diagnosis import (
    diagnose_elastic_resources,
)


def summarize(rows):
    output=[]
    for K in sorted({r["tasks"] for r in rows}):
        profiles=sorted({r["profile"] for r in rows if r["tasks"]==K})
        for profile in profiles:
            for method in ("B-ALNS","ESI-ALNS"):
                sample=[r for r in rows if r["tasks"]==K
                        and r["profile"]==profile and r["method"]==method]
                f=[r for r in sample if r["capacity_only"]["numerically_credible"]]
                aq=[r for r in sample if r["qos_only_positive"]]
                positive=[r for r in f
                          if r["capacity_only"]["normalized_total_elastic_slack"]>.002]
                repaired_by_caps=[
                    r for r in aq if r["capacity_only"]["numerically_credible"]
                ]
                strict_control=[r for r in sample if r["original_stage1_qualified"]]
                output.append({
                    "tasks":K,"profile":profile,"method":method,
                    "attempts":len(sample),
                    "original_stage1_qualified":len(strict_control),
                    "qos_only_positive_conflict":len(aq),
                    "mec_capacity_only_strict_QoS_feasible":len(f),
                    "mec_capacity_only_requires_expand":len(positive),
                    "mec_capacity_only_status": {
                        status:sum(x["capacity_only"]["status"]==status for x in sample)
                        for status in sorted({x["capacity_only"]["status"] for x in sample})
                    },
                    "qos_conflicts_potentially_rescuable_by_capacity":len(repaired_by_caps),
                    "strict_controls_false_extra_capacity":sum(
                        x["capacity_only"]["normalized_total_elastic_slack"]>.002
                        for x in strict_control
                        if x["capacity_only"]["numerically_credible"]
                    ),
                    "mec_cap_credible_cpu_sum":sum(
                        x["capacity_only"]["slack_sum_by_family"].get("mec_cpu_cap",0.)
                        for x in f
                    ),
                    "mec_cap_credible_bw_sum":sum(
                        x["capacity_only"]["slack_sum_by_family"].get("bandwidth_cap",0.)
                        for x in f
                    ),
                    "mean_elastic_runtime_s":mean(
                        x["capacity_only"]["diagnostic_build_and_solve_s"]
                        for x in sample
                    ) if sample else None,
                })
    return output


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    original=json.loads(args.source.read_text(encoding="utf-8"))
    previous=json.loads(args.previous.read_text(encoding="utf-8"))
    p=original["protocol"]
    K,S=int(p["task_scale"]),int(p["independent_scenario_seed"])
    if not original["complete"] or not previous["complete"]:
        raise RuntimeError("A source artifact is incomplete")
    assert previous["protocol"]["tasks"]==K
    assert previous["protocol"]["independent_scenario_seed"]==S
    originals={(r["profile"],int(r["seed"]),r["method"]):r for r in original["rows"]}
    instances={}
    cache={}
    payload={
        "complete":False,
        "protocol":{
            "id":"mec_capacity_only_counterfactual_resource_diagnosis_v1",
            "tasks":K,"independent_scenario_seed":S,
            "prior_elastic_run":38050123790,
            "original_parameter_run":38043248604,
            "hard_QoS_deadline_avg_delay_cycle_battery":True,
            "soft_only_mec_station_cpu_and_bandwidth_capacity":True,
            "unchanged_original_route_contact_execution":True,
            "not_combinatorial_global_infeasibility_proof":True,
            "source_hashes":current_source_hashes(Path(__file__)),
            "provenance":provenance(),
        },
        "rows":[],
    }
    write_json(args.output,payload)
    failures=[]
    for prior in previous["rows"]:
        if prior.get("status")!="ok" or not prior.get("diagnoses"):
            continue
        profile,seed,method=prior["profile"],int(prior["seed"]),prior["method"]
        original_row=originals[(profile,seed,method)]
        if profile not in instances:
            x=original["profiles"][profile]
            instance=restore_instance(x["instance"])
            if content_hash(instance)!=x["instance_sha256"]:
                raise RuntimeError("Original instance changed")
            instances[profile]=instance
        instance=instances[profile]
        solution=restore_solution(original_row["solution"])
        signature=content_hash(solution)
        if signature!=prior["solution_sha256"]:
            raise RuntimeError("Prior elastic/source original solution SHA mismatch")
        key=(profile,signature)
        if key in cache:
            diag=deepcopy(cache[key])
            from_cache=True
        else:
            try:
                diag=diagnose_elastic_resources(
                    instance,solution,mode="mec_capacity_only"
                )
            except Exception as exc:
                failures.append({
                    "profile":profile,"seed":seed,
                    "method":method,"error":str(exc),
                })
                diag={
                    "status":"unexpected_exception",
                    "numerically_credible":False,
                    "error_type":type(exc).__name__,
                    "error_message":str(exc),
                }
            cache[key]=deepcopy(diag)
            from_cache=False
        prior_q=prior["diagnoses"]["qos_only"]
        row={
            "tasks":K,
            "scenario":S,
            "profile":profile,
            "seed":seed,
            "method":method,
            "original_stage1_status":prior["original_stage1_status"],
            "original_stage1_qualified":prior["original_stage1_qualified"],
            "old_precheck_passed":prior["old_passed"],
            "queue_precheck_passed":prior["queue_passed"],
            "qos_only_positive":bool(
                prior_q["numerically_credible"]
                and prior_q["normalized_total_elastic_slack"]>.002
            ),
            "qos_only_normalized_slack":prior_q.get("normalized_total_elastic_slack"),
            "qos_plus_capacity_normalized_slack":prior["diagnoses"][
                "qos_plus_mec_capacity"
            ].get("normalized_total_elastic_slack"),
            "solution_sha256":signature,
            "capacity_only":diag,
            "reused_solver_diagnostic":from_cache,
        }
        payload["rows"].append(row)
        write_json(args.output,payload)
        print(
            f"CAPACITY_ONLY K{K} S{S} A{seed} {profile} {method}: "
            f"original={prior['original_stage1_status']}, "
            f"qos_slack={row['qos_only_normalized_slack']}, "
            f"capacity_status={diag.get('status')}, "
            f"credible={diag.get('numerically_credible')} "
            f"extra_station_capacity={diag.get('normalized_total_elastic_slack')}",
            flush=True,
        )
    payload["summary"]=summarize(payload["rows"])
    payload["complete"]=True
    payload["unique_diagnostic_runs"]=len(cache)
    payload["unexpected_errors"]=failures
    write_json(args.output,payload)
    print("CAPACITY_ONLY_SUMMARY="+json.dumps({
        "K":K,"S":S,"rows":len(payload["rows"]),
        "unique":len(cache),"errors":len(failures),
        "summary":[{
            k:r[k] for k in (
                "profile","method","attempts","original_stage1_qualified",
                "qos_only_positive_conflict",
                "mec_capacity_only_strict_QoS_feasible",
                "qos_conflicts_potentially_rescuable_by_capacity",
                "mec_capacity_only_status"
            )
        } for r in payload["summary"]],
    },ensure_ascii=False),flush=True)
    if failures:
        raise RuntimeError(f"Unexpected counterfactual errors: {failures[:2]}")
    return payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--previous",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    run(p.parse_args())


if __name__=="__main__":
    main()
