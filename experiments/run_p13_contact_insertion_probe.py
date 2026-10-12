"""P13 fixed-budget contact-aware insertion counterfactual pilot.

Do not alter original ALNS, P1-R, Stage1/Stage2 or the production
insertion/finish functions. For the same one-task removal, compare:
 A: original rank1 -> original MEC finish.
 B: top3 original-ranked options, same 3 finish previews, choose the
    original key (extra-budget negative control).
 C: top3 original-ranked options, same 3 finish previews, choose by
    the *post*-MEC FIFO/EDF necessary violation score.
 D: top3 original-ranked options, same 3 finish previews, choose by
    contact reuse/offloading opportunities, BEFORE reading queue score.

The top3 set is deliberately a restrictive fixed candidate budget:
S96/S23 old rank3 is included. This is OFFLINE attribution, not a
full-ALNS matched-clock success claim; P13 cannot claim generalization
until actual original ALNS integration and new-scene holdout.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from run_p12_insertion_finish_audit import (
    CASES,_task_candidates,queue_metrics,_structural_changes,
    _strict_numerical_check,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,restore_solution,content_hash,write_json,
)
from uav_mec.algorithms.alns.evaluator import solution_signature

ARMS=("original_top1","same_budget_original_rank",
      "contact_opportunity","post_mec_queue")
TOP_K=3


def _queue_key(m):
    return (not m["queue_necessary_pass"],
            m["queue_reason_count"],
            m["total_normalized_all_constraint_excess"],
            m["worst_task_deadline_excess_s"])


def _contact_key(record):
    """No queue oracle in contact arm: offload and contact reuse only.

    Original _finish_repair reports physical contact count and task
    offloading count; prefer more offloaded tasks with fewer new
    contact visits, then original insertion rank.
    """
    changes=record["structural_effect"]
    return (
        -record["after"]["MEC_offloaded_count"],
        changes["contact_visits_added"],
        record["after"]["MEC_contact_count"],
        record["rank"],
    )


def preview_one(instance,source,tid):
    start=perf_counter()
    frozen_sha=content_hash(source)
    initial=UavMecState(
        instance,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(initial,[tid])
    options=ops._options_for_task(destroyed,tid)
    if not options:raise RuntimeError("No original legal insertion")
    choices=[]
    snapshots={}
    for rank in range(1,min(TOP_K,len(options))+1):
        state=destroyed.copy()
        option=options[rank-1]
        ops._apply_local_insertion(state,tid,option)
        before=deepcopy(state.solution)
        t=perf_counter()
        finished=ops._finish_repair(state)
        rebuild_wall=perf_counter()-t
        after=deepcopy(finished.solution)
        metric=queue_metrics(instance,after)
        item={
            "rank":rank,
            "original_option_key":list(option.key),
            "uav_id":option.uav_id,
            "position":option.position,
            "after":metric,
            "structural_effect":_structural_changes(before,after),
            "post_MEC_structure_sha256":content_hash(after),
            "MEC_preview_wall_s":rebuild_wall,
        }
        choices.append(item)
        snapshots[rank]=after
    winners={
        "original_top1":choices[0],
        "same_budget_original_rank":min(
            choices,key=lambda c:c["rank"]),
        "contact_opportunity":min(choices,key=_contact_key),
        "post_mec_queue":min(
            choices,key=lambda c:(_queue_key(c["after"]),c["rank"])),
    }
    result={
        "task_id":tid,
        "source_sha256":frozen_sha,
        "available_original_positions":len(options),
        "fixed_preview_budget":len(choices),
        "same_candidate_pool_every_arm":True,
        "candidates":choices,
        "winners":{
            arm:{
                "rank":item["rank"],
                "queue_necessary_pass":item["after"]["queue_necessary_pass"],
                "queue_reason_count":item["after"]["queue_reason_count"],
                "total_normalized_excess":item["after"]["total_normalized_all_constraint_excess"],
                "physical_sha256":item["post_MEC_structure_sha256"],
            } for arm,item in winners.items()
        },
        "extra_stage1_posthoc":{},
        "previews_total_wall_s":perf_counter()-start,
    }
    checked={}
    for arm,item in winners.items():
        sig=solution_signature(snapshots[item["rank"]])
        if sig not in checked:
            checked[sig]=_strict_numerical_check(
                instance,snapshots[item["rank"]])
        result["extra_stage1_posthoc"][arm]=checked[sig]
    result["distinct_extra_stage1_CVX_candidates"]=len(checked)
    result["original_D_unchanged"]=content_hash(source)==frozen_sha
    if not result["original_D_unchanged"]:
        raise RuntimeError("P13 source mutated")
    return result


def run(source_file:Path,output:Path,cases):
    if output.exists():raise FileExistsError(output)
    raw=json.loads(source_file.read_text(encoding="utf-8"))
    scene=int(raw["protocol"]["independent_scenario_seed"])
    if not raw.get("complete") or scene not in CASES:
        raise ValueError("Only previously inspected frozen P12 scenes")
    cases=[(a,int(b)) for a,b in cases]
    if not cases or any(x not in CASES[scene] for x in cases):
        raise ValueError("Only preregistered P12 development sources")
    idx={(r["profile"],int(r["seed"]),r["method"]):r
         for r in raw["rows"]}
    output_data={
        "complete":False,
        "protocol":{
            "id":"P13_OriginalTop3_MECContactVsPostQueue_Counterfactual_v1",
            "scene":scene,
            "source_sha256":content_hash(raw),
            "arms":list(ARMS),
            "top3_original_legal_positions":True,
            "identical_preview_candidates_per_arm":True,
            "original_insertion_and_finish_repair_unchanged":True,
            "CVX_stage1_and_stage2_postpaid_diagnostic_only":True,
            "all_scenes_previously_inspected_not_new_holdout":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,output_data)
    for profile,seed in cases:
        old=idx[profile,seed,"B-ALNS"]
        instance=restore_instance(raw["profiles"][profile]["instance"])
        source=restore_solution(old["solution"])
        if content_hash(instance)!=raw["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Instance physical hash drift")
        if content_hash(source)!=old["solution_sha256"]:
            raise RuntimeError("Source D SHA drift")
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "source_B_sha256":old["solution_sha256"],
            "source_B_Stage1_strict":bool(old["stage1_qualified"]),
            "tasks":[],
        }
        output_data["rows"].append(row)
        write_json(output,output_data)
        try:
            for tid in _task_candidates(instance,source):
                trial=preview_one(instance,source,tid)
                row["tasks"].append(trial)
                write_json(output,output_data)
                print("P13_CONTACT_PREVIEW="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,
                    "task":tid,
                    "winners":{arm:{
                        "rank":v["rank"],
                        "queue_pass":v["queue_necessary_pass"],
                        "strict":trial["extra_stage1_posthoc"][arm]["Stage1_and_Stage2_strict"],
                    } for arm,v in trial["winners"].items()},
                    "extra_CVX_candidates":trial["distinct_extra_stage1_CVX_candidates"],
                },ensure_ascii=False),flush=True)
        except Exception as exc:
            error={
                "scene":scene,"profile":profile,"seed":seed,
                "type":type(exc).__name__,"message":str(exc),
            }
            row["error"]=error
            output_data["errors"].append(error)
        write_json(output,output_data)
    output_data["complete"]=True
    trials=[t for r in output_data["rows"] for t in r["tasks"]]
    output_data["summary"]={
        "source_cases":len(output_data["rows"]),
        "task_position_trials":len(trials),
        "arm_strict_Stage1_and_Stage2":{
            a:sum(t["extra_stage1_posthoc"][a]["Stage1_and_Stage2_strict"]
                  for t in trials) for a in ARMS},
        "arm_queue_necessary_pass":{
            a:sum(t["winners"][a]["queue_necessary_pass"] for t in trials)
            for a in ARMS},
        "arm_non_original_rank":{
            a:sum(t["winners"][a]["rank"]!=1 for t in trials) for a in ARMS},
        "program_errors":len(output_data["errors"]),
    }
    write_json(output,output_data)
    print("P13_CONTACT_PREVIEW_SUMMARY="+json.dumps({
        "scene":scene,**output_data["summary"]},ensure_ascii=False),flush=True)
    if output_data["errors"]:
        raise RuntimeError("P13 diagnostic errors: "+str(output_data["errors"][:2]))
    return output_data


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--cases",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.output,[v.split(":") for v in a.cases.split(",")])
