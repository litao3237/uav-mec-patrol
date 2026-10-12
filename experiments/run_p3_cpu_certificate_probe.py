"""P3 conditional frozen-source pilot: CPU certificate -> targeted MEC moves.

Four paired arms on exactly the SAME source D, same structural constraints
and exact Stage1 quota (<=3), same per-arm 4s *soft* generation cap.
- old_atomic_cpu_guard: old P1 atomic candidate pool + existing P2 safe gate
- cert_plain: add CPU-certificate-targeted legal repair moves
- cert_bridge: same new moves + reserve one proven CPU-pressure-progress beam
- heavy_bridge: identical move families/beam strategy but globally heavy
  offloaded tasks instead of constraint-binding prefix target tasks

This is a DEVELOPMENT diagnostic on already-inspected S85-S88, not
independent holdout nor complete equal-end-to-end ALNS. No official
result or originally frozen strict acceptance criterion changes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
from time import perf_counter

from atomic_batch_moves import atomic_batch_moves
from atomic_batch_search import atomic_search
from cpu_certificate_repair_moves import cpu_conflict_moves
from experiment_common import provenance, current_source_hashes
from progressive_bridge_core import PROFILES, _metric, _legacy_global_key
from run_queue_guided_repair import new_move_candidates, queue_gap
from run_seven_methods import finalize
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)

ARMS=("old_atomic_cpu_guard","cert_plain","cert_bridge","heavy_bridge")


def _root_task_ids(instance,source):
    root=queue_gap(instance,source)
    offenders=[r["task_id"] for r in root["task_offenders"][:3]]
    if offenders:return offenders
    from uav_mec.evaluation import build_event_info
    from uav_mec.optimization.resource.queue_aware_precheck import (
        queue_aware_feasibility_precheck,
    )
    q=queue_aware_feasibility_precheck(instance,source,
                                      build_event_info(instance,source))
    return sorted(instance.tasks,key=lambda t:(
        q.task_completion_lb_s[t]-instance.tasks[t].deadline_s
    ),reverse=True)[:3]


def _cpu_gap(lb):
    total=0.
    for station in lb["stations"].values():
        ratio=station["min_cpu_pressure_ratio"]
        if ratio is None:return math.inf
        total+=max(0.,ratio-1.)
    return total


def _choose_cpu_screened(instance,ordered,limit=3):
    """Select CVX shortlist; CPU necessity is a safe *negative* gate."""
    selected=[]
    screened=0
    passed=0
    t0=perf_counter()
    preview=[]
    for row in ordered:
        if len(selected)>=limit:break
        tested=station_cpu_share_necessary_bound(instance,row["sol"])
        screened+=1
        status=bool(tested["certified_cpu_share_failure"])
        if status:
            preview.append({"label":row["label"],"rejected":True})
            continue
        selected.append(row)
        passed+=1
        preview.append({"label":row["label"],"rejected":False})
    return selected,{
        "cpu_gate_checked":screened,
        "cpu_gate_rejected":screened-passed,
        "cpu_gate_wall_s":perf_counter()-t0,
        "first_candidate_screen_events":preview[:8],
    }


def _new_search(instance,source,*,policy,protect,
                generation_cap_s=4.,depth=4,beam_width=2):
    if policy not in ("certificate","workload"):
        raise ValueError(policy)
    if generation_cap_s<=0 or depth<=0 or beam_width<2:
        raise ValueError("Invalid fixed search budget")
    t0=perf_counter()
    ids=_root_task_ids(instance,source)
    root_metric=_metric(instance,source,root_task_ids=ids)
    root_cpu=_cpu_gap(station_cpu_share_necessary_bound(instance,source))
    beam=[{"label":"root","sol":deepcopy(source),
           "metric":root_metric,"cpu_gap":root_cpu,
           "has_target_move":False}]
    visited={solution_signature(source)}
    viable={}
    stats=Counter()
    trace=[]
    timed_out=False
    target_examples=[]
    for depth_now in range(1,depth+1):
        if perf_counter()-t0>=generation_cap_s:
            timed_out=True
            break
        layer=[]
        for parent in beam:
            if perf_counter()-t0>=generation_cap_s:
                timed_out=True
                break
            proposals=list(new_move_candidates(
                instance,parent["sol"],mode="queue_dependency_joint",offenders=3,
            ))
            stats["old_proposals"]+=len(proposals)
            if perf_counter()-t0<generation_cap_s:
                atomic,meta=atomic_batch_moves(
                    instance,parent["sol"],include_cross_uav=True,
                )
                proposals+=atomic
                stats["atomic_proposals"]+=len(atomic)
            if perf_counter()-t0<generation_cap_s:
                extra,explanation=cpu_conflict_moves(
                    instance,parent["sol"],policy=policy,task_limit=3,
                )
                proposals+=extra
                stats["cpu_extra_proposals"]+=len(extra)
                if len(target_examples)<3:
                    target_examples.append({
                        "depth":depth_now,
                        "parent":parent["label"],
                        "policy":policy,
                        "focus":explanation["focus_explanation"][:3],
                        "actual_targets":explanation["actual_targets"],
                        "source_cpu_capacity_violation":explanation[
                            "source_cpu_capacity_violation"],
                        "family_counts":explanation["move_family_counts"],
                    })
            for label,candidate in proposals:
                if perf_counter()-t0>=generation_cap_s:
                    timed_out=True
                    break
                sig=solution_signature(candidate)
                if sig in visited:
                    stats["duplicates"]+=1
                    continue
                visited.add(sig)
                metric=_metric(instance,candidate,root_task_ids=ids)
                stats["generated_unique"]+=1
                row={
                    "label":label,"sig":sig,"sol":candidate,"metric":metric,
                    "depth":depth_now,"family":label.split("::")[0],
                    "parent":parent["label"],
                    "has_target_move":(
                        parent["has_target_move"] or label.startswith("cpu_target_")),
                }
                if metric["passed"]:
                    viable[sig]=row
                if protect and label.startswith("cpu_target_"):
                    row["cpu_gap"]=_cpu_gap(
                        station_cpu_share_necessary_bound(instance,candidate))
                    row["cpu_progress"]=(
                        row["cpu_gap"]<parent["cpu_gap"]-1e-7)
                layer.append(row)
            if timed_out:break
        if not layer:break
        layer.sort(key=lambda x:_legacy_global_key(x["metric"],x["label"]))
        chosen=layer[:beam_width]
        protected=False
        if protect:
            # Keep best legacy-score state AND one lower-station-CPU-gap
            # candidate, when it exists within a conservative queue-gap
            # growth window. This is not a feasibility acceptance rule.
            top=layer[0]
            current_queue=float(root_metric["total_excess_s"])
            allowed_queue_gap=max(12.,current_queue*1.5+8.)
            improving=[
                row for row in layer
                if row.get("cpu_progress") and row["sig"]!=top["sig"]
                and row["metric"]["total_excess_s"]<=allowed_queue_gap
            ]
            improving.sort(key=lambda r:(
                r["cpu_gap"],*_legacy_global_key(r["metric"],r["label"])))
            if improving:
                chosen=[top,improving[0]]
                protected=True
        beam=[{
            "label":r["label"],"sol":r["sol"],"metric":r["metric"],
            "cpu_gap":r.get("cpu_gap",math.inf),
            "has_target_move":r["has_target_move"],
        } for r in chosen]
        trace.append({
            "depth":depth_now,
            "layer_unique":len(layer),
            "queue_pass":sum(x["metric"]["passed"] for x in layer),
            "selected_labels":[r["label"] for r in chosen],
            "selected_has_cpu_target":[r["has_target_move"] for r in chosen],
            "protected_cpu_progress":protected,
            "best_optimistic_excess_s":layer[0]["metric"]["total_excess_s"],
        })
        stats["depth_reached"]=depth_now
        if timed_out:break
    ordered=sorted(viable.values(),
                   key=lambda r:_legacy_global_key(r["metric"],r["label"]))
    return ordered,{
        "policy":policy,"protect_cpu_progress":protect,
        "old_source_queue_gap_s":root_metric["total_excess_s"],
        "old_source_cpu_gap":root_cpu,
        "unique_queue_admitted":len(ordered),
        "generated_unique":stats["generated_unique"],
        "old_raw":stats["old_proposals"],
        "atomic_raw":stats["atomic_proposals"],
        "cpu_target_raw":stats["cpu_extra_proposals"],
        "depth_reached":stats["depth_reached"],
        "soft_generation_timeout":timed_out,
        "generation_wall_s":perf_counter()-t0,
        "beam_trace":trace,
        "focus_examples":target_examples,
    }


def _strict_check(instance,shortlist,*,arm):
    oracle=Stage1CVXObjectiveOracle()
    begin=perf_counter()
    qualified=[]
    cand=[]
    for r in shortlist:
        res=oracle.solve(instance,r["sol"])
        ok=bool(stage1_is_qualified(res))
        cand.append({
            "label":r["label"],
            "family":r["label"].split("::")[0],
            "stage1_qualified":ok,
            "solver_status":res.diagnostics.get("stage1_status"),
            "energy_j":float(res.energy_stage1_j) if ok else None,
            "has_cpu_target_ancestor":r.get("has_target_move",False),
        })
        if ok:qualified.append((float(res.energy_stage1_j),r))
    strict=False
    energy=None
    selected=None
    final=None
    if qualified:
        _,best=min(qualified,key=lambda x:x[0])
        full=finalize(
            instance,best["sol"],method=arm,seed=None,
            initialization_s=0.,search_s=0.,
            diagnostics={"source":"P3_conditional_only","last_move":best["label"]},
        )
        strict=bool(full["stage1"]["qualified"] and full["stage2"]["qualified"])
        final={
            "stage1_qualified":bool(full["stage1"]["qualified"]),
            "stage2_qualified":bool(full["stage2"]["qualified"]),
        }
        selected=best["label"]
        if strict:energy=float(full["resources"].energy_stage1_j)
    return {
        "strict_both_recovered":strict,
        "strict_energy_j":energy,
        "last_move":selected,
        "final_stage_qualifications":final,
        "oracle_calls":oracle.calls,
        "stage1_pass_candidates":len(qualified),
        "candidate_results":cand,
        "strict_eval_wall_s":perf_counter()-begin,
    }


def _arm(instance,source,arm):
    start=perf_counter()
    if arm=="old_atomic_cpu_guard":
        ordered,stats=atomic_search(
            instance,source,include_atomic=True,include_cross_uav=True,
            beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.,
        )
        gen_s=float(stats["generation_wall_s"])
        info={
            "policy":"legacy_original",
            "protect_cpu_progress":False,
            "generated_unique":stats["unique_generated"],
            "unique_queue_admitted":stats["queue_passed"],
            "soft_generation_timeout":stats["soft_generation_overrun"],
            "depth_reached":stats["beam_depth_reached"],
            "generation_wall_s":gen_s,
        }
    else:
        policy=("workload" if arm=="heavy_bridge" else "certificate")
        ordered,info=_new_search(
            instance,source,policy=policy,
            protect=arm in ("cert_bridge","heavy_bridge"),
            generation_cap_s=4.,depth=4,beam_width=2,
        )
    shortlisted,gate=_choose_cpu_screened(instance,ordered,limit=3)
    final=_strict_check(instance,shortlisted,arm=arm)
    if final["oracle_calls"]>3:raise RuntimeError("Strict Stage1 budget exceeded")
    return {
        "arm":arm,
        "shortlist_labels":[x["label"] for x in shortlisted],
        "search":info,"cpu_gate":gate,**final,
        "total_wall_s":perf_counter()-start,
    }


def run(source_file:Path,old_file:Path,output:Path):
    if output.exists():raise FileExistsError(output)
    raw=json.loads(source_file.read_text(encoding="utf-8"))
    old=json.loads(old_file.read_text(encoding="utf-8"))
    if not raw.get("complete") or not old.get("complete"):
        raise ValueError("Source archives must be complete")
    scene=int(raw["protocol"]["independent_scenario_seed"])
    if scene not in (85,86,87,88) or old["protocol"]["scenario"]!=scene:
        raise ValueError("Frozen development source mismatch")
    original={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    old_idx={(r["profile"],int(r["seed"])):r for r in old["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"p3_static_cpu_certificate_targeted_joint_repair_development_v1",
            "scenario":scene,
            "original_source_sha256":content_hash(raw),
            "frozen_p1_sha256":content_hash(old),
            "current_provenance":provenance(),
            "source_hashes":current_source_hashes(Path(__file__)),
            "source_development_only_S85_S88":True,
            "same_source_D_and_strict_stage1_stage2_acceptance":True,
            "same_CVX_quota_3_per_arm":True,
            "same_beam_width_2_and_depth_4":True,
            "same_soft_generation_cap_s":4.,
            "time_includes_candidate_generation_cpu_gate_and_strict_validation":True,
            "not_equal_time_end_to_end_full_ALNS":True,
            "arms":list(ARMS),
        },
        "rows":[],"errors":[],
    }
    write_json(output,payload)
    for profile in PROFILES:
        snap=raw["profiles"][profile]
        inst=restore_instance(snap["instance"])
        if content_hash(inst)!=snap["instance_sha256"]:
            raise RuntimeError("Frozen physical instance mismatch")
        for seed in (125,126):
            oldrow=old_idx[profile,seed]
            if not oldrow["eligible"]:continue
            src=original[profile,seed,"B-ALNS"]
            sol=restore_solution(src["solution"])
            h=content_hash(sol)
            if h!=oldrow["source_solution_sha256"]:
                raise RuntimeError("Frozen source discrete scheme mismatch")
            row={
                "scenario":scene,"profile":profile,"seed":seed,
                "original_sha256":h,
                "old_p1_strict":bool(oldrow["arms"][
                    "atomic_offload_and_cross_uav_depth4"]["strict_both_recovered"]),
                "arms":{},
            }
            payload["rows"].append(row)
            write_json(output,payload)
            for arm in ARMS:
                try:
                    res=_arm(inst,sol,arm)
                    if content_hash(sol)!=h:
                        raise RuntimeError("Source D mutated")
                    row["arms"][arm]=res
                    print("P3_CPU_CERT_CASE="+json.dumps({
                        "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                        "strict":res["strict_both_recovered"],
                        "calls":res["oracle_calls"],
                        "queue_pass":res["search"]["unique_queue_admitted"],
                        "cpu_target_raw":res["search"].get("cpu_target_raw",0),
                        "sec":round(res["total_wall_s"],4),
                    },ensure_ascii=False),flush=True)
                except Exception as exc:
                    error={"scenario":scene,"profile":profile,"seed":seed,
                           "arm":arm,"type":type(exc).__name__,
                           "message":str(exc)}
                    row["arms"][arm]={"error":error,"strict_both_recovered":False}
                    payload["errors"].append(error)
                    print("P3_CPU_CERT_ERROR="+json.dumps(error),flush=True)
                write_json(output,payload)
    payload["complete"]=True
    payload["summary"]={
        "source_failures":len(payload["rows"]),
        "strict":{a:sum(r["arms"].get(a,{}).get("strict_both_recovered",False)
                        for r in payload["rows"]) for a in ARMS},
        "calls":{a:sum(r["arms"].get(a,{}).get("oracle_calls",0)
                       for r in payload["rows"]) for a in ARMS},
        "mean_wall_s":{a:(
            sum(r["arms"][a]["total_wall_s"] for r in payload["rows"])/len(payload["rows"])
            if payload["rows"] and all("total_wall_s" in r["arms"].get(a,{})
                                       for r in payload["rows"]) else None
        ) for a in ARMS},
        "unexpected_errors":len(payload["errors"]),
    }
    write_json(output,payload)
    print("P3_CPU_CERT_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"],
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"Unexpected P3 error: {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--previous",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    run(args.source,args.previous,args.output)
