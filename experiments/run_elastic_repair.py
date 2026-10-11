"""Paired source-D Stage-1/Stage-2 rescue trial using archived elastic conflicts.

The source original B-ALNS checkpoint and all parameter values come from the
immutable GitHub run 38043248604. The QoS-only elastic diagnosis is read from
independent GitHub run 38050123790. Original MEC greedy, old-LB joint, queue
dependency joint, elastic-ranked SAME moves, and elastic-targeted joint are
evaluated on exactly the same failed structure, each independently.

No original ESI/postprocessing stage is run before any arm. Results on
S61-S64 were used to develop mechanisms, so they are PILOT, not a holdout.
The separate new S71+ holdout is performed by another independent workflow.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from elastic_repair_core import ARM_NAMES, run_elastic_arm, old_queue_arm
from experiment_common import current_source_hashes, provenance
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)


STRESS_PROFILES = (
    "compute_x1p5", "compute_x2p0", "deadline_x0p9", "deadline_x0p8",
)


def summarize(rows):
    return [{
        "profile":p,
        "arm":arm,
        "eligible_source_states":sum(
            r["eligible"] for r in rows if r["profile"]==p
        ),
        "attempted":sum(
            arm in r["arms"] for r in rows
            if r["profile"]==p and r["eligible"]
        ),
        "strict_stage1_stage2_recovered":sum(
            bool(r["arms"].get(arm,{}).get("strict_both_recovered"))
            for r in rows if r["profile"]==p
        ),
        "precheck_passing_cases":sum(
            bool(r["arms"].get(arm,{}).get("precheck_passed_candidates"))
            for r in rows if r["profile"]==p
        ),
        "mean_total_s_including_diagnostic":(
            mean(r["arms"][arm]["total_s_including_diagnostic"]
                 for r in rows if r["profile"]==p and arm in r["arms"]
                 and r["arms"][arm].get("total_s_including_diagnostic") is not None)
            if any(r["profile"]==p and arm in r["arms"]
                   and r["arms"][arm].get("total_s_including_diagnostic") is not None
                   for r in rows) else None
        ),
        "mean_strict_cvx_calls":(
            mean(r["arms"][arm]["strict_cvx_calls"]
                 for r in rows if r["profile"]==p and arm in r["arms"]
                 and r["arms"][arm].get("strict_cvx_calls") is not None)
            if any(r["profile"]==p and arm in r["arms"]
                   and r["arms"][arm].get("strict_cvx_calls") is not None
                   for r in rows) else None
        ),
        "unexpected_arm_errors":sum(
            bool(r["arms"].get(arm,{}).get("error_type"))
            for r in rows if r["profile"]==p
        ),
    } for p in STRESS_PROFILES for arm in ARM_NAMES]


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    original=json.loads(args.source.read_text(encoding="utf-8"))
    previous=json.loads(args.elastic.read_text(encoding="utf-8"))
    p=original["protocol"]
    if not original.get("complete") or not previous.get("complete"):
        raise ValueError("Only completed, frozen source artifacts are allowed")
    if p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Wrong source experiment")
    K,S=int(p["task_scale"]),int(p["independent_scenario_seed"])
    if K!=80:
        raise ValueError("The historical source-D rescue probe is K80")
    assert previous["protocol"]["tasks"]==K
    assert previous["protocol"]["independent_scenario_seed"]==S
    profiles=[x.strip() for x in args.profiles.split(",") if x.strip()]
    if any(x not in STRESS_PROFILES for x in profiles):
        raise ValueError("Unsupported stress profile")
    seeds=(
        [int(x) for x in args.seeds.split(",")]
        if args.seeds else p["algorithm_seeds"]
    )
    by_source={(r["profile"],int(r["seed"]),r["method"]):r
               for r in original["rows"]}
    by_elastic={(r["profile"],int(r["seed"]),r["method"]):r
                for r in previous["rows"] if r.get("status")=="ok"}
    payload={
        "complete":False,
        "protocol":{
            "id":"elastic_slack_guided_same_failed_D_rescue_v1",
            "cohort":"historical_hypothesis_development_not_holdout",
            "tasks":K,"scenario":S,"seeds":seeds,"profiles":profiles,
            "source_original_run":38043248604,
            "source_elastic_diagnosis_run":38050123790,
            "arms":ARM_NAMES,
            "max_depth":args.depth,"beam_width":args.beam_width,
            "strict_candidate_CVX_calls_cap":args.exact_limit,
            "all_arm_actions_begin_from_exact_same_original_failed_D":True,
            "diagnostic_time_charged_only_to_elastic_arms":True,
            "stage2_and_physical_audits_never_relaxed":True,
            "not_equal_end_to_end_budget":True,
            "source_hashes":current_source_hashes(Path(__file__)),
            "provenance":provenance(),
        },
        "rows":[],
    }
    write_json(args.output,payload)
    errors=[]
    for profile in profiles:
        src=original["profiles"][profile]
        instance=restore_instance(src["instance"])
        if content_hash(instance)!=src["instance_sha256"]:
            raise RuntimeError("Original physical instance checksum mismatch")
        for seed in seeds:
            source=by_source[(profile,seed,"B-ALNS")]
            prior=by_elastic.get((profile,seed,"B-ALNS"))
            diag_result=(source.get("resources") or {}).get("diagnostics") or {}
            source_status=str(diag_result.get("stage1_status","unknown"))
            row={
                "scenario":S,"tasks":K,"profile":profile,"seed":seed,
                "original_stage1_status":source_status,
                "original_both_qualified":source.get("both_qualified",False),
                "eligible":source_status=="infeasible_precheck",
                "source_solution_sha256":source.get("solution_sha256"),
                "source_stage1_precheck_reasons":diag_result.get("precheck_reasons",[]),
                "arms":{},
            }
            if row["eligible"]:
                frozen=restore_solution(source["solution"])
                if content_hash(frozen)!=source["solution_sha256"]:
                    raise RuntimeError("Original failed structure SHA mismatch")
                if prior is None or prior["solution_sha256"]!=row["source_solution_sha256"]:
                    raise RuntimeError("Elastic diagnosis does not match original fixed structure")
                diag=prior["diagnoses"]["qos_only"]
                row["source_elastic_status"]=diag["status"]
                row["source_elastic_credible"]=diag["numerically_credible"]
                row["source_elastic_slack"]=diag.get("normalized_total_elastic_slack")
                diag_s=float(diag.get("diagnostic_build_and_solve_s") or 0.0)
                row["source_diagnostic_wall_s"]=diag_s
                for arm in ARM_NAMES:
                    try:
                        if arm.startswith("elastic_"):
                            result=run_elastic_arm(
                                instance,frozen,diag=diag,arm=arm,
                                beam_width=args.beam_width,depth=args.depth,
                                exact_limit=args.exact_limit,
                                diagnostic_runtime_s=diag_s,
                            )
                        else:
                            result=old_queue_arm(
                                instance,frozen,arm,
                                beam_width=args.beam_width,depth=args.depth,
                                exact_limit=args.exact_limit,
                            )
                        if content_hash(frozen)!=row["source_solution_sha256"]:
                            raise RuntimeError("An arm mutated the shared failed D!")
                        row["arms"][arm]=result
                        print(
                            f"ELASTIC_REPAIR K{K} S{S} A{seed} {profile} {arm}: "
                            f"qualified={result['strict_both_recovered']} "
                            f"queued={result['precheck_passed_candidates']} "
                            f"cvx={result['strict_cvx_calls']} "
                            f"elapsed={result['total_s_including_diagnostic']:.3f}",
                            flush=True,
                        )
                    except Exception as exc:
                        row["arms"][arm]={
                            "error_type":type(exc).__name__,
                            "error_message":str(exc),
                            "strict_both_recovered":False,
                        }
                        errors.append({
                            "profile":profile,"seed":seed,"arm":arm,
                            "type":type(exc).__name__,"message":str(exc),
                        })
            payload["rows"].append(row)
            write_json(args.output,payload)
    payload["summary"]=summarize(payload["rows"])
    payload["unexpected_errors"]=errors
    payload["complete"]=True
    write_json(args.output,payload)
    total=sum(r["eligible"] for r in payload["rows"])
    print("ELASTIC_REPAIR_SUMMARY="+json.dumps({
        "K":K,"S":S,"eligible":total,"skipped":len(payload["rows"])-total,
        "errors":len(errors),
        "arms":[{
            "arm":a,
            "recovered":sum(
                r["arms"].get(a,{}).get("strict_both_recovered",False)
                for r in payload["rows"]
            ),
            "precheck_passing":sum(
                bool(r["arms"].get(a,{}).get("precheck_passed_candidates"))
                for r in payload["rows"]
            ),
        } for a in ARM_NAMES],
    },ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError(f"Unexpected rescue errors preserved: {errors[:3]}")
    return payload


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--source",type=Path,required=True)
    a.add_argument("--elastic",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--profiles",default=",".join(STRESS_PROFILES))
    a.add_argument("--seeds",default="")
    a.add_argument("--depth",type=int,default=2)
    a.add_argument("--beam-width",type=int,default=2)
    a.add_argument("--exact-limit",type=int,default=3)
    args=a.parse_args()
    if min(args.depth,args.beam_width,args.exact_limit)<=0:
        raise ValueError("Rescue search/evaluation caps must be positive")
    run(args)


if __name__=="__main__":
    main()
