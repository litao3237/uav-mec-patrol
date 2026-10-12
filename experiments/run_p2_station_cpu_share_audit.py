"""Audit physically necessary static MEC CPU-share bound on frozen P1 archives.

Runs NO new Stage1/Stage2 CVX solves. Replays search ONLY to recover
candidate structures; all strict feasible labels are taken from unchanged
previously archived P1 resource-audit records and matched by SHA-256.
The previous S85-S88 set is development data, never an unseen holdout.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from atomic_batch_search import atomic_search
from progressive_bridge_core import PROFILES
from uav_mec.analysis.experiment_snapshot import (
    restore_instance, restore_solution, content_hash, write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)


def _audit(inst, sol):
    ev=build_event_info(inst,sol)
    q=queue_aware_feasibility_precheck(inst,sol,ev)
    new=station_cpu_share_necessary_bound(inst,sol,info=ev,queue=q)
    return {
        "queue_necessary_pass":bool(q.feasible),
        "static_station_cpu_necessary_pass":bool(
            new["passes_necessary_cpu_share_test"]),
        "station_cpu_reject":bool(new["certified_cpu_share_failure"]),
        "min_station_cpu_pressure":new["stations"],
    }


def run(source_path, old_path, resource_path, output_path):
    if output_path.exists():raise FileExistsError(output_path)
    source=json.loads(source_path.read_text(encoding="utf-8"))
    old=json.loads(old_path.read_text(encoding="utf-8"))
    audit=json.loads(resource_path.read_text(encoding="utf-8"))
    if not source.get("complete") or not old.get("complete") or not audit.get("complete"):
        raise ValueError("Incomplete frozen sources")
    scene=source["protocol"]["independent_scenario_seed"]
    if (scene not in (85,86,87,88) or old["protocol"]["scenario"]!=scene
        or audit["protocol"]["scenario"]!=scene):
        raise ValueError("Mismatched source identity")
    source_by={(r["profile"],int(r["seed"]),r["method"]):r for r in source["rows"]}
    audit_by={(r["profile"],int(r["seed"])):r for r in audit["rows"]}
    old_by={(r["profile"],int(r["seed"])):r for r in old["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"p2_station_cpu_share_necessary_bound_development_audit_v1",
            "scenario":scene,
            "source_sha256":content_hash(source),
            "old_p1_sha256":content_hash(old),
            "resource_audit_sha256":content_hash(audit),
            "inspected_S85_S88_not_independent":True,
            "no_stage1_or_stage2_resolve":True,
            "no_changes_to_original_model_or_acceptance":True,
            "cpu_allocation_static_by_uav_mec_pair":True,
            "candidate_truth_only_from_original_sha256_matched_resource_audit":True,
        },
        "source_results":[],
        "candidate_results":[],
        "errors":[],
    }
    write_json(output_path,payload)
    try:
        for profile in ("baseline",)+PROFILES:
            snap=source["profiles"][profile]
            inst=restore_instance(snap["instance"])
            if content_hash(inst)!=snap["instance_sha256"]:
                raise RuntimeError("Physical instance hash changed")
            for seed in (125,126):
                for method in ("B-ALNS","ESI-ALNS"):
                    src=source_by[profile,seed,method]
                    sol=restore_solution(src["solution"])
                    if content_hash(sol)!=src["solution_sha256"]:
                        raise RuntimeError("Frozen source solution hash changed")
                    out=_audit(inst,sol)
                    payload["source_results"].append({
                        "scenario":scene,"profile":profile,"seed":seed,
                        "method":method,"solution_sha256":src["solution_sha256"],
                        "strict_stage1_qualified":bool(src["stage1_qualified"]),
                        "strict_stage2_qualified":bool(src["stage2_qualified"]),
                        "source_stage1_status":((src.get("resources") or {}).get("diagnostics") or {}).get("stage1_status"),
                        **out,
                    })
                    if src["stage1_qualified"] and out["station_cpu_reject"]:
                        raise RuntimeError("CPU necessary bound rejected strict positive control")
        # Candidate-level test on exact previously CVX-evaluated top8 archives.
        for profile in PROFILES:
            snap=source["profiles"][profile]
            inst=restore_instance(snap["instance"])
            for seed in (125,126):
                old_row=old_by[profile,seed]
                if not old_row["eligible"]:
                    continue
                r=audit_by[profile,seed]
                if not r.get("diagnosis_complete"):
                    raise RuntimeError("Incomplete resource candidate audit")
                archived=r["candidate_results"]
                src=source_by[profile,seed,"B-ALNS"]
                sol=restore_solution(src["solution"])
                shortlist,stats=atomic_search(
                    inst,sol,include_atomic=True,include_cross_uav=True,
                    beam_width=2,depth=4,exact_limit=8,generation_cap_s=4.,
                )
                if len(shortlist)!=len(archived):
                    raise RuntimeError(
                        f"Candidate count drift {scene} {profile} A{seed}: "
                        f"{len(shortlist)} vs {len(archived)}")
                if [c["label"] for c in shortlist[:3]]!=r["replay_top3_labels"]:
                    raise RuntimeError("Frozen top3 candidate names drift")
                for rank,(c,history) in enumerate(zip(shortlist,archived),1):
                    identity=content_hash(c["sol"])
                    if identity!=history["node_hash"]:
                        raise RuntimeError(f"Candidate fingerprint drift at rank {rank}")
                    out=_audit(inst,c["sol"])
                    if not out["queue_necessary_pass"]:
                        raise RuntimeError("A previous top8 admitted candidate fails old queue certificate")
                    if history["stage1_qualified"] and out["station_cpu_reject"]:
                        raise RuntimeError("CPU necessary test rejected strict Stage1 feasible candidate")
                    payload["candidate_results"].append({
                        "scenario":scene,"profile":profile,"seed":seed,
                        "rank":rank,"candidate_sha256":identity,
                        "candidate_family":history["family"],
                        "candidate_label":history["label"],
                        "strict_stage1_qualified":bool(history["stage1_qualified"]),
                        "strict_stage1_status":history["stage1_solver_status"],
                        "strict_extra_stage2_both":(
                            (history.get("stage2_complete_audit") or {}).get("strict_both_qualified")
                        ),
                        "original_top3":rank<=3,
                        **out,
                    })
                write_json(output_path,payload)
    except Exception as e:
        payload["errors"].append({"type":type(e).__name__,"message":str(e)})
        write_json(output_path,payload)
        raise
    payload["complete"]=True
    src=payload["source_results"]
    c=payload["candidate_results"]
    payload["summary"]={
        "source_count":len(src),
        "source_strict_stage1":sum(r["strict_stage1_qualified"] for r in src),
        "source_queue_rejected":sum(not r["queue_necessary_pass"] for r in src),
        "source_cpu_rejected":sum(r["station_cpu_reject"] for r in src),
        "source_new_only_rejected":sum(r["queue_necessary_pass"] and r["station_cpu_reject"] for r in src),
        "source_false_positive_rejected":sum(r["strict_stage1_qualified"] and r["station_cpu_reject"] for r in src),
        "candidate_count":len(c),
        "candidate_stage1_qualified":sum(r["strict_stage1_qualified"] for r in c),
        "candidate_new_cpu_rejected":sum(r["station_cpu_reject"] for r in c),
        "candidate_failed_CVX_cpu_rejected":sum(not r["strict_stage1_qualified"] and r["station_cpu_reject"] for r in c),
        "candidate_strict_CVX_cpu_rejected":sum(r["strict_stage1_qualified"] and r["station_cpu_reject"] for r in c),
        "top3_cpu_rejections":sum(r["original_top3"] and r["station_cpu_reject"] for r in c),
        "by_candidate_final_family":dict(Counter(r["candidate_family"] for r in c)),
    }
    write_json(output_path,payload)
    print("P2_STATION_SHARE_RESULT="+json.dumps({
        "scenario":scene,**payload["summary"],"errors":payload["errors"],
    },ensure_ascii=False),flush=True)
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--previous",required=True,type=Path)
    p.add_argument("--resource-audit",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    run(a.source,a.previous,a.resource_audit,a.output)
