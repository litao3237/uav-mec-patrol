"""Frozen-source P1 counterfactual: isolate beam vs oracle-slot crowding.

This reruns S85-S88 AFTER inspecting holdout, hence is a development
diagnostic, NOT a new independent holdout and NOT equal-time ALNS proof.
All candidate acceptance uses unchanged Stage1/Stage2 audits.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from atomic_batch_search import run_atomic_arm, run_control_arm
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)

FROZEN_SOURCE="uav_mec_one_factor_coupling_sensitivity_v1"
ARMS={
    "plain4":None,
    "atomic_global":("global","global"),
    "atomic_pure_beam":("pure_legacy_only","global"),
    "atomic_protect_beam":("one_pure_legacy","global"),
    "atomic_protect_shortlist":("global","one_pure_legacy"),
    "atomic_protect_both":("one_pure_legacy","one_pure_legacy"),
}


def run(input_file:Path, archived_result:Path, output:Path):
    if output.exists():
        raise FileExistsError(f"Do not overwrite {output}")
    raw=json.loads(input_file.read_text(encoding="utf-8"))
    old=json.loads(archived_result.read_text(encoding="utf-8"))
    proto=raw["protocol"]
    if not raw.get("complete") or proto.get("id")!=FROZEN_SOURCE:
        raise ValueError("Wrong original B/ESI frozen source")
    if not old.get("complete") or old["protocol"]["id"]!="p1_atomic_coupled_MEC_dependency_repair_v1":
        raise ValueError("Wrong original P1 audit source")
    scenario=int(proto["independent_scenario_seed"])
    if scenario not in (85,86,87,88) or scenario!=old["protocol"]["scenario"]:
        raise ValueError("Only previously frozen S85-S88")
    index={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    old_index={(r["profile"],int(r["seed"])):r for r in old["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"p1_candidate_selection_counterfactual_v1",
            "scenario":scenario,
            "source_sha256":content_hash(raw),
            "old_p1_sha256":content_hash(old),
            "source_run_id":38134649545,
            "arms":list(ARMS),
            "max_stage1_exact_checks_per_arm":3,
            "beam_width":2,
            "depth":4,
            "generation_soft_cap_s":4.,
            "reuses_inspected_S85_S88_development_only":True,
            "not_an_equal_wall_time_full_algorithm_comparison":True,
        },
        "rows":[],
        "errors":[],
    }
    write_json(output,payload)
    for profile in ("compute_x1p5","compute_x2p0","deadline_x0p9","deadline_x0p8"):
        instance=restore_instance(raw["profiles"][profile]["instance"])
        if content_hash(instance)!=raw["profiles"][profile]["instance_sha256"]:
            raise ValueError("Frozen physical instance hash mismatch")
        for seed in (125,126):
            src=index[profile,seed,"B-ALNS"]
            previous=old_index[profile,seed]
            status=((src.get("resources") or {}).get("diagnostics") or {}).get("stage1_status")
            if (status=="infeasible_precheck")!=previous["eligible"]:
                raise ValueError("Eligibility mismatch with immutable previous experiment")
            row={
                "scenario":scenario,"profile":profile,"seed":seed,
                "eligible":bool(previous["eligible"]),
                "source_solution_sha256":previous["source_solution_sha256"],
                "arms":{},
            }
            if row["eligible"]:
                solution=restore_solution(src["solution"])
                before=content_hash(solution)
                if before!=row["source_solution_sha256"]:
                    raise ValueError("Source structure changed")
                for name,policies in ARMS.items():
                    try:
                        if policies is None:
                            result=run_control_arm(instance,solution,
                                                   arm="queue_plain_depth4",
                                                   beam_width=2,depth=4,
                                                   exact_limit=3,generation_cap_s=4.)
                        else:
                            result=run_atomic_arm(
                                instance,solution,
                                arm="atomic_offload_and_cross_uav_depth4",
                                beam_width=2,depth=4,exact_limit=3,
                                generation_cap_s=4.,
                                beam_policy=policies[0],
                                shortlist_policy=policies[1],
                            )
                        if content_hash(solution)!=before:
                            raise ValueError("Mutated source solution")
                        if result.get("strict_stage1_oracle_calls",0)>3:
                            raise ValueError("Exceeded strict oracle quota")
                        row["arms"][name]=result
                        print("P1_SELECTION "+json.dumps({
                            "scene":scenario,"profile":profile,"seed":seed,
                            "arm":name,
                            "strict":bool(result.get("strict_both_recovered")),
                            "cvx":result.get("strict_stage1_oracle_calls"),
                            "seconds":round(result.get("total_wall_s",0.),4),
                        }),flush=True)
                    except Exception as exc:
                        row["arms"][name]={
                            "error_type":type(exc).__name__,
                            "error_message":str(exc),
                            "strict_both_recovered":False,
                        }
                        payload["errors"].append({
                            "profile":profile,"seed":seed,"arm":name,
                            "error_type":type(exc).__name__,"message":str(exc)
                        })
                if (not payload["errors"]
                    and bool(row["arms"]["plain4"]["strict_both_recovered"])
                     !=bool(previous["arms"]["queue_plain_depth4"]["strict_both_recovered"])):
                    payload["errors"].append({
                        "profile":profile,"seed":seed,"arm":"plain4",
                        "error_type":"ReplayMismatch",
                        "message":"Old comparator strict outcome changed on unchanged structure",
                    })
            payload["rows"].append(row)
            write_json(output,payload)
    payload["complete"]=True
    payload["summary"]={
        a:{"strict":sum(bool(r["arms"].get(a,{}).get("strict_both_recovered"))
                        for r in payload["rows"]),
           "eligible":sum(r["eligible"] for r in payload["rows"])}
        for a in ARMS
    }
    write_json(output,payload)
    print("P1_SELECTION_SUMMARY="+json.dumps({
        "scenario":scenario,"summary":payload["summary"],
        "errors":payload["errors"],
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"Counterfactual failures {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--archived-p1",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.input,a.archived_p1,a.output)
