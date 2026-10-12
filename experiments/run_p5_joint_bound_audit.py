"""Frozen P5 safe-bound audit on P1 and P4 archived strict outcomes.

Source corpus A: P1 S85-S88, original B/ESI + at most 8 Stage1 verified
candidates per selected failed D (via exact prior P1 hashes).
Source corpus B: P4 post-holdout S89-S92 (original P3 physical sources
and 6 postbound candidates, all CVX failed, prior model replay verified).

Both corpora have ALREADY BEEN INSPECTED. P5 is development evidence,
NOT a new holdout and NEVER a proof of entire route-instance infeasibility.
No original Stage1/Stage2 CVX solve is needed for this experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from atomic_batch_search import atomic_search
from run_p4_postbound_attribution import _shortlist as _p3_shortlist
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

BINS=(12,24,48)
P1_PROTO="p1_frozen_resource_conflict_attribution_v1"
P4_PROTO="P4_postbound_strict_resource_attribution_v1"


def metrics(instance,solution):
    info=build_event_info(instance,solution)
    queue=queue_aware_feasibility_precheck(instance,solution,info)
    old=station_cpu_share_necessary_bound(instance,solution,info=info,queue=queue)
    new={}
    for bins in BINS:
        result=joint_station_bw_cpu_necessary_bound(
            instance,solution,info=info,queue=queue,n_bins=bins)
        new[str(bins)]={
            "rejected":bool(result["joint_necessary_reject"]),
            "joint_wall_s":float(result["joint_test_wall_s"]),
            "stations":{
                mid:{
                    "physical_CPU_GHz":x["physical_cpu_ghz"],
                    "physical_BW_MHz":x["physical_bandwidth_mhz"],
                    "min_required_CPU_GHz":x["optimistic_min_total_cpu_ghz"],
                    "CPU_oversubscription_GHz":x["oversubscription_cpu_ghz"],
                    "rounded_bandwidth_budget_MHz":x["upper_rounded_bandwidth_budget_mhz"],
                    "joint_necessary_violation":x["joint_necessary_violation"],
                    "optimistic_min_pair_allocation":(
                        x["best_optimistic_bin_allocation"] if bins==48 else None),
                } for mid,x in result["stations"].items() if x["active_pairs"]
            },
        }
    return {
        "old_queue_pass":bool(queue.feasible),
        "old_CPU_share_pass":not old["certified_cpu_share_failure"],
        "joint":new,
    }


def run(source_path:Path,audit_path:Path,output_path:Path):
    if output_path.exists():raise FileExistsError("Immutable diagnostic output")
    raw=json.loads(source_path.read_text(encoding="utf-8"))
    archived=json.loads(audit_path.read_text(encoding="utf-8"))
    if not raw.get("complete") or not archived.get("complete"):
        raise ValueError("Incomplete original scientific archives")
    id=archived["protocol"]["id"]
    if id not in (P1_PROTO,P4_PROTO):raise ValueError("Unknown prior strict resource dossier")
    scene=int(raw["protocol"]["independent_scenario_seed"])
    if scene!=archived["protocol"]["scenario"]:
        raise ValueError("Scenario identity mismatch")
    if id==P1_PROTO and scene not in (85,86,87,88):raise ValueError("P1 cohort mismatch")
    if id==P4_PROTO and scene not in (89,90,91,92):raise ValueError("P4 cohort mismatch")
    cohort="P1" if id==P1_PROTO else "P4"
    sources={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    instances={}
    for profile,entry in raw["profiles"].items():
        instance=restore_instance(entry["instance"])
        if content_hash(instance)!=entry["instance_sha256"]:
            raise RuntimeError("Physical instance hash mismatch")
        instances[profile]=instance
    payload={
        "complete":False,
        "protocol":{
            "id":"P5_quantized_joint_BW_CPU_necessary_screen_audit_v1",
            "cohort":cohort,"scenario":scene,"resolutions":list(BINS),
            "original_source_sha256":content_hash(raw),
            "prior_strict_resource_dossier_sha256":content_hash(archived),
            "only_previous_strict_outcomes_no_new_CVX_solver_calls":True,
            "prior_P1_P4_already_inspected_development_only":True,
            "safe_monotonic_bin_upper_rounding":True,
            "original_model_and_ALNS_acceptance_unchanged":True,
        },
        "source_rows":[],"strict_candidate_rows":[],"errors":[],
    }
    write_json(output_path,payload)
    # All B/ESI source structures, whether original Stage1 feasible,
    # precheck infeasible, or numerically uncertain.
    for src in raw["rows"]:
        if src["method"] not in ("B-ALNS","ESI-ALNS"):continue
        if "solution" not in src:
            payload["source_rows"].append({
                "profile":src["profile"],"seed":src["seed"],
                "method":src["method"],"missing_original_solution":True})
            continue
        inst=instances[src["profile"]]
        sol=restore_solution(src["solution"])
        identity=content_hash(sol)
        if identity!=src["solution_sha256"]:
            raise RuntimeError("Original discrete solution fingerprint drift")
        result=metrics(inst,sol)
        if src.get("stage1_qualified") and any(
            x["rejected"] for x in result["joint"].values()):
            raise RuntimeError("UNSOUND necessary bound: rejected known strict positive control")
        payload["source_rows"].append({
            "profile":src["profile"],"seed":int(src["seed"]),
            "method":src["method"],"solution_sha256":identity,
            "strict_stage1_qualified":bool(src.get("stage1_qualified")),
            "original_stage1_status":(
                ((src.get("resources") or {}).get("diagnostics") or {}).get("stage1_status")),
            **result,
        })
    write_json(output_path,payload)

    # Reconstruct *only* previously exactly evaluated candidates, and
    # match each unchanged source/model with its archived SHA256.
    if id==P1_PROTO:
        for previous in archived["rows"]:
            profile,seed=previous["profile"],int(previous["seed"])
            if not previous.get("diagnosis_complete"):raise RuntimeError("Unfinished P1 dossier")
            sol=restore_solution(sources[profile,seed,"B-ALNS"]["solution"])
            inst=instances[profile]
            expected=previous["candidate_results"]
            shortlisted,diag=atomic_search(
                inst,sol,include_atomic=True,include_cross_uav=True,
                beam_width=2,depth=4,exact_limit=8,generation_cap_s=4.)
            if len(shortlisted)!=len(expected):
                raise RuntimeError("P1 shortlisted identity count differs")
            for rank,(cand,prior) in enumerate(zip(shortlisted,expected),1):
                h=content_hash(cand["sol"])
                if (h!=prior["node_hash"] or cand["label"]!=prior["label"]):
                    raise RuntimeError("P1 original Stage1 candidate SHA/label mismatch")
                result=metrics(inst,cand["sol"])
                if prior["stage1_qualified"] and any(
                    x["rejected"] for x in result["joint"].values()):
                    raise RuntimeError("P5 erroneously rejects previously qualified Stage1 candidate")
                payload["strict_candidate_rows"].append({
                    "profile":profile,"seed":seed,"rank":rank,
                    "candidate_sha256":h,"label":cand["label"],
                    "original_stage1_qualified":bool(prior["stage1_qualified"]),
                    "original_stage1_status":prior["stage1_solver_status"],
                    **result,
                })
            write_json(output_path,payload)
    else:
        for old in archived["candidate_dossiers"]:
            profile,seed=old["profile"],int(old["source_seed"])
            occurrence=old["occurrences"][0]
            inst=instances[profile]
            src=sources[profile,seed,"B-ALNS"]
            sol=restore_solution(src["solution"])
            selected=_p3_shortlist(inst,sol,occurrence["arm"])
            rank=occurrence["rank"]
            if rank>len(selected):raise RuntimeError("P4 selected shortlist lacks rank")
            cand=selected[rank-1]
            h=content_hash(cand["sol"])
            if h!=old["candidate_sha256"] or cand["label"]!=old["candidate_label"]:
                raise RuntimeError("P4 archived original Stage1 candidate SHA/label mismatch")
            result=metrics(inst,cand["sol"])
            payload["strict_candidate_rows"].append({
                "profile":profile,"seed":seed,"rank":rank,
                "candidate_sha256":h,"label":cand["label"],
                "original_stage1_qualified":bool(old["original_stage1_qualified"]),
                "original_stage1_status":old["original_stage1_status"],
                **result,
            })
            write_json(output_path,payload)
    payload["complete"]=True
    payload["summary"]={}
    for label,rows in (
        ("original_source_records",payload["source_rows"]),
        ("previously_exact_CVX_checked_candidates",payload["strict_candidate_rows"]),
    ):
        available=[r for r in rows if not r.get("missing_original_solution")]
        payload["summary"][label]={
            "records":len(rows),
            "available":len(available),
            "original_strict_stage1_positive":sum(
                r.get("strict_stage1_qualified",r.get("original_stage1_qualified",False))
                for r in available),
            "queue_rejected":sum(not r["old_queue_pass"] for r in available),
            "old_CPU_share_rejected":sum(not r["old_CPU_share_pass"] for r in available),
            "joint_rejected":{
                str(bins):sum(r["joint"][str(bins)]["rejected"] for r in available)
                for bins in BINS},
            "new_beyond_queue_plus_old_CPU":{
                str(bins):sum(
                    r["old_queue_pass"] and r["old_CPU_share_pass"] and
                    r["joint"][str(bins)]["rejected"]
                    for r in available)
                for bins in BINS},
            "wrongly_rejected_original_strict":{
                str(bins):sum(
                    r.get("strict_stage1_qualified",r.get("original_stage1_qualified",False))
                    and r["joint"][str(bins)]["rejected"]
                    for r in available)
                for bins in BINS},
            "mean_joint_wall_s":{
                str(bins):(mean(r["joint"][str(bins)]["joint_wall_s"]
                                for r in available) if available else None)
                for bins in BINS},
        }
    write_json(output_path,payload)
    print("P5_JOINT_AUDIT_SUMMARY="+json.dumps({
        "cohort":cohort,"scenario":scene,"summary":payload["summary"],
    },ensure_ascii=False),flush=True)
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--audit",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.audit,a.output)
