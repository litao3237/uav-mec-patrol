"""P4: numerical attribution AFTER both safe feasibility bounds passed.

Replay FROZEN P3 S89-S92 heldout candidates. This data was inspected
during P3, hence P4 is a post-holdout diagnostic, NOT a new independent
holdout or a new improved ALNS algorithm.

Every original Stage1-examined D must be reproduced from its frozen
original source and shortlisted operator label. The new elastic modes
relax CPU capacity ONLY or bandwidth capacity ONLY, leaving true task
deadlines, all FIFO/EDF order, UAV batteries and the other capacity hard.
They are NOT feasible solutions under original physical resources.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from atomic_batch_search import atomic_search
from experiment_common import provenance, current_source_hashes
from run_p3_cpu_certificate_probe import (
    ARMS, _choose_cpu_screened, _new_search,
)
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.elastic_diagnosis import (
    diagnose_elastic_resources,
)
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)


COUNTERFACTUALS=(
    "qos_only",
    "mec_capacity_only",
    "cpu_capacity_only",
    "bandwidth_capacity_only",
)


def _shortlist(instance, source, arm):
    if arm=="old_atomic_cpu_guard":
        ordered,_=atomic_search(
            instance,source,include_atomic=True,include_cross_uav=True,
            beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.,
        )
    else:
        ordered,_=_new_search(
            instance,source,
            policy="workload" if arm=="heavy_bridge" else "certificate",
            protect=arm in ("cert_bridge","heavy_bridge"),
            beam_width=2,depth=4,generation_cap_s=4.,
        )
    selected,_=_choose_cpu_screened(instance,ordered,limit=3)
    return selected


def _structure_info(instance, sol):
    event=build_event_info(instance,sol)
    queue=queue_aware_feasibility_precheck(instance,sol,event)
    cpu=station_cpu_share_necessary_bound(instance,sol,info=event,queue=queue)
    bw_by_mec={}
    for (uav,mid) in event.active_uav_mec_pairs:
        bw_by_mec.setdefault(mid,{"active_pairs":[],"total_data_mbit":0.})
        bw_by_mec[mid]["active_pairs"].append(uav)
    for v,tasks in event.batch_tasks.items():
        from uav_mec.evaluation import visit_mec_id
        mid=visit_mec_id(instance,sol,v)
        bw_by_mec.setdefault(mid,{"active_pairs":[],"total_data_mbit":0.})
        bw_by_mec[mid]["total_data_mbit"]+=sum(
            instance.tasks[t].data_mbit for t in tasks)
    return {
        "queue_passes":bool(queue.feasible),
        "cpu_share_passes":not cpu["certified_cpu_share_failure"],
        "station_required_cpu_ratio":{
            mid:v["min_cpu_pressure_ratio"]
            for mid,v in cpu["stations"].items() if v["pairs"]
        },
        "active_uav_mec_pairs":len(event.active_uav_mec_pairs),
        "contacts":len(event.batch_tasks),
        "offload_tasks":sum(len(x) for x in event.batch_tasks.values()),
        "mec_batch_data":bw_by_mec,
    }


def _compact_elastic(x):
    return {
        k:x.get(k) for k in (
            "mode","status","solver","numerically_credible",
            "normalized_total_elastic_slack",
            "max_hard_normalized_residual",
            "max_elastic_normalized_residual",
            "diagnostic_build_and_solve_s",
            "capacity_relaxation_interpretation",
        )
    } | {
        "soft_families":x.get("slack_sum_by_family"),
        "top_constraints":(x.get("top_constraints") or [])[:8],
        "top_dependency_context":(x.get("top_dependency_context") or [])[:4],
        "attempts":(x.get("attempts") or [])[-2:],
    }


def run(source_path:Path,prior_path:Path,output_path:Path):
    if output_path.exists():
        raise FileExistsError("Never overwrite original diagnostic snapshot")
    raw=json.loads(source_path.read_text(encoding="utf-8"))
    prior=json.loads(prior_path.read_text(encoding="utf-8"))
    sp=raw["protocol"]
    scene=int(sp["independent_scenario_seed"])
    if (scene not in (89,90,91,92)
        or not raw.get("complete") or not prior.get("complete")
        or prior["protocol"]["scenario"]!=scene
        or prior["protocol"]["id"]!="P3_CPU_certificate_independent_conditional_repair_v1"):
        raise ValueError("Expected completed P3 S89-S92 frozen source/repair pair")
    sources={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    profile_instances={}
    for profile,snapshot in raw["profiles"].items():
        inst=restore_instance(snapshot["instance"])
        if content_hash(inst)!=snapshot["instance_sha256"]:
            raise RuntimeError("Original physical scenario mutated")
        profile_instances[profile]=inst
    payload={
        "complete":False,
        "protocol":{
            "id":"P4_postbound_strict_resource_attribution_v1",
            "source_p3_actions_run":38202029324,
            "scenario":scene,"task_scale":80,
            "source_sha256":content_hash(raw),
            "original_repair_result_sha256":content_hash(prior),
            "post_holdout_development_diagnostic_only":True,
            "no_change_to_official_P1R_or_stage1_acceptance":True,
            "no_ALNS_full_equal_time_comparison":True,
            "physical_capacity_relaxation_never_counts_as_repaired":True,
            "frozen_elastic_modes":list(COUNTERFACTUALS),
            "source_hashes":current_source_hashes(Path(__file__)),
            "provenance":provenance(),
        },
        "source_funnel":[],
        "candidate_dossiers":[],
        "positive_control":None,
        "errors":[],
    }
    write_json(output_path,payload)
    try:
        cache={}
        # Each of 4 baseline physical pressure profiles has two stochastic
        # algorithms seeds. Retain all 8 source statuses per scene.
        for row in prior["rows"]:
            profile,seed=row["profile"],int(row["seed"])
            src=sources[profile,seed,"B-ALNS"]
            if (row["source_solution_sha256"]!=src["solution_sha256"]):
                raise RuntimeError("Original P3 source D hash mismatch")
            record={
                "scenario":scene,"profile":profile,"seed":seed,
                "original_source_stage1_status":row["source_stage1_status"],
                "original_source_eligible":row["eligible_for_fixed_D_repair"],
                "methods":{},
            }
            payload["source_funnel"].append(record)
            if not row["eligible_for_fixed_D_repair"]:
                continue
            instance=profile_instances[profile]
            source=restore_solution(src["solution"])
            old_hash=content_hash(source)
            for arm in ARMS:
                old_arm=row["arms"].get(arm,{})
                if "error" in old_arm:raise RuntimeError("Unresolved prior P3 experiment error")
                old_results=old_arm.get("candidate_results",[])
                record["methods"][arm]={
                    "queue_admitted":old_arm["search"]["unique_queue_admitted"],
                    "cpu_gate_checked":old_arm["cpu_gate"]["cpu_gate_checked"],
                    "cpu_gate_rejected":old_arm["cpu_gate"]["cpu_gate_rejected"],
                    "stage1_calls":len(old_results),
                    "strict_recovered":bool(old_arm["strict_both_recovered"]),
                    "solver_status_counts":dict(Counter(
                        r.get("solver_status") or "unknown" for r in old_results)),
                }
                if not old_results:continue
                candidates=_shortlist(instance,source,arm)
                labels=[x["label"] for x in candidates]
                if labels!=old_arm["shortlist_labels"]:
                    raise RuntimeError(
                        f"Frozen candidates were not reproducible: S{scene} "
                        f"{profile} A{seed} {arm}: {labels} versus "
                        f"{old_arm['shortlist_labels']}")
                if len(candidates)!=len(old_results):
                    raise RuntimeError("Frozen shortlisted oracle quota changed")
                for rank,(chosen,previous) in enumerate(zip(candidates,old_results),1):
                    if previous["label"]!=chosen["label"]:
                        raise RuntimeError("Frozen candidate label alignment failed")
                    h=content_hash(chosen["sol"])
                    key=(profile,h)
                    if key in cache:
                        cache[key]["occurrences"].append({
                            "source_seed":seed,"arm":arm,"rank":rank,
                            "previous_solver_status":previous["solver_status"],
                        })
                        continue
                    item={
                        "scenario":scene,"profile":profile,"source_seed":seed,
                        "candidate_sha256":h,
                        "candidate_family":previous["family"],
                        "candidate_label":previous["label"],
                        "occurrences":[{
                            "source_seed":seed,"arm":arm,"rank":rank,
                            "previous_solver_status":previous["solver_status"],
                        }],
                        "old_model":_structure_info(instance,chosen["sol"]),
                        "original_stage1_qualified":previous["stage1_qualified"],
                        "original_stage1_status":previous["solver_status"],
                        "verified_exact_stage1":None,
                        "elastic_modes":{},
                    }
                    if not item["old_model"]["queue_passes"] or not item["old_model"]["cpu_share_passes"]:
                        raise RuntimeError("Original P3 admitted a rejected candidate")
                    cache[key]=item
                    payload["candidate_dossiers"].append(item)
                    write_json(output_path,payload)
                    # Verify solver identity independently before numerical
                    # attribution, without counting this as algorithm budget.
                    oracle=Stage1CVXObjectiveOracle()
                    solved=oracle.solve(instance,chosen["sol"])
                    verified=bool(stage1_is_qualified(solved))
                    item["verified_exact_stage1"]={
                        "qualified":verified,
                        "status":solved.diagnostics.get("stage1_status"),
                        "calls":oracle.calls,
                    }
                    if verified!=bool(previous["stage1_qualified"]):
                        item["solver_replay_mismatch"]=True
                    write_json(output_path,payload)
                    for mode in COUNTERFACTUALS:
                        start=perf_counter()
                        elastic=diagnose_elastic_resources(
                            instance,chosen["sol"],mode=mode,
                        )
                        item["elastic_modes"][mode]=_compact_elastic(elastic)
                        item["elastic_modes"][mode]["measured_wall_s"]=perf_counter()-start
                        write_json(output_path,payload)
                    print("P4_ATTRIBUTION_CASE="+json.dumps({
                        "scene":scene,"profile":profile,"seed":seed,
                        "candidate":h[:12],"family":item["candidate_family"],
                        "stage1_old":item["original_stage1_status"],
                        "stage1_replay":item["verified_exact_stage1"],
                        "counterfactual_modes":{
                            mode:{"status":d["status"],
                                  "credible":d["numerically_credible"],
                                  "positive_slack":d["normalized_total_elastic_slack"]}
                            for mode,d in item["elastic_modes"].items()
                        },
                    },ensure_ascii=False),flush=True)
            if content_hash(source)!=old_hash:
                raise RuntimeError("One of the replayed repairs mutated original D")

        # A positive control from a strictly qualified original solution:
        # all capacity-only counterfactuals should have near-zero slacks.
        ok_source=next((
            r for r in raw["rows"] if r["method"]=="B-ALNS"
            and r["profile"] in ("baseline","compute_x1p5",
                                "compute_x2p0","deadline_x0p9","deadline_x0p8")
            and r["stage1_qualified"]
        ),None)
        if ok_source is None:raise RuntimeError("No strict original control available")
        inst=profile_instances[ok_source["profile"]]
        sol=restore_solution(ok_source["solution"])
        control={
            "profile":ok_source["profile"],"seed":int(ok_source["seed"]),
            "source_sha256":content_hash(sol),
            "stage1_qualified":True,
            "modes":{},
        }
        payload["positive_control"]=control
        for mode in COUNTERFACTUALS:
            control["modes"][mode]=_compact_elastic(
                diagnose_elastic_resources(inst,sol,mode=mode))
            write_json(output_path,payload)
        if content_hash(sol)!=ok_source["solution_sha256"]:
            raise RuntimeError("Control source changed")
    except Exception as exc:
        payload["errors"].append({"type":type(exc).__name__,"message":str(exc)})
        write_json(output_path,payload)
        raise
    payload["complete"]=True
    payload["summary"]={
        "sources":len(payload["source_funnel"]),
        "failing_precheck_sources":sum(r["original_source_eligible"]
                                       for r in payload["source_funnel"]),
        "unique_Stage1_explored_candidates":len(payload["candidate_dossiers"]),
        "candidate_occurrences":sum(len(r["occurrences"]) for r
                                    in payload["candidate_dossiers"]),
        "stage1_replay_mismatches":sum(bool(r.get("solver_replay_mismatch"))
                                       for r in payload["candidate_dossiers"]),
        "positive_control_credible":{
            m:bool(v.get("numerically_credible"))
            for m,v in payload["positive_control"]["modes"].items()
        },
        "program_errors":len(payload["errors"]),
    }
    write_json(output_path,payload)
    print("P4_ATTRIBUTION_SUMMARY="+json.dumps({
        "scenario":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError("Unexpected diagnostic errors")
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--prior",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    run(a.source,a.prior,a.output)
