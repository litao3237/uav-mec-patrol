"""P16 full original-builder acceptance prediction audit on 6 frozen B states.

Reconstruct exactly the first 2 pre-registered P12 removed tasks from
each originally failed/feasible B-ALNS D (S89/S91/S93/S95/S96), and
the top3 ORIGINAL insertion options. Measure:
 - original MEC reduced proxy's feasibility score on LOCAL complete D,
 - whether inserted task is in old greedy repair's critical top8,
 - whether an old existing contact reuse would be strictly accepted
   by original GreedyMECRepairConfig::_strictly_better,
 - the very first move taken by real _finish_repair (as control),
 - true after-original-builder FIFO/EDF necessary status and CPU time.
 No new Stage1/Stage2 oracle calls, no new ALNS, no changed original D.
 This is a DEVELOPMENT diagnostic on already-observed S89-S96 only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from run_p12_insertion_finish_audit import (
    CASES,_task_candidates,queue_metrics,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.algorithms.initial.mec_repair import (
    GreedyMECRepairConfig,_critical_local_tasks,
    _existing_contacts_after_task,_reuse_contact_candidate,
    _strictly_better,evaluate_initial_proxy,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)


def probe_task(inst,source,tid):
    state=UavMecState(
        inst,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(state,[tid])
    options=ops._options_for_task(destroyed,tid)
    model=GreedyMECRepairConfig()
    entries=[]
    for rank,option in enumerate(options[:3],start=1):
        trial=destroyed.copy()
        ops._apply_local_insertion(trial,tid,option)
        start=perf_counter()
        base=evaluate_initial_proxy(inst,trial.solution)
        eligible=(
            _critical_local_tasks(
                inst,trial.solution,base,limit=model.critical_task_limit)
            if base.score.violated_constraints else [])
        allowed=[]
        for vid in _existing_contacts_after_task(trial.solution,tid):
            cand=_reuse_contact_candidate(
                inst,trial.solution,task_id=tid,visit_id=vid)
            scored=evaluate_initial_proxy(inst,cand)
            if tid in eligible and _strictly_better(
                scored.score,base.score,tolerance=model.improvement_tolerance):
                allowed.append({
                    "contact_visit_id":vid,
                    "accepted_score_key":list(scored.score.key),
                })
        predictor_s=perf_counter()-start
        begin=perf_counter()
        finished=ops._finish_repair(trial.copy())
        builder_s=perf_counter()-begin
        moves=finished.solution.metadata.get("mec_repair_moves",[])
        first=moves[0] if moves else None
        checked=queue_metrics(inst,finished.solution)
        entries.append({
            "rank":rank,
            "original_uav":option.uav_id,
            "original_position":option.position,
            "original_delta_flight_m":option.delta_distance_m,
            "original_MEC_baseline_proxy_key":list(base.score.key),
            "inserted_task_is_original_critical_top8":tid in eligible,
            "candidate_actionable_reuse":allowed,
            "first_real_greedy_MEC_action":first,
            "real_original_greedy_actions":moves[:4],
            "old_MEC_reconstruction_queue_pass":checked["queue_necessary_pass"],
            "old_MEC_reconstruction_queue_reasons":checked["queue_reason_count"],
            "old_MEC_reconstruction_normalized_excess":checked[
                "total_normalized_all_constraint_excess"],
            "new_D_hash":content_hash(finished.solution),
            "prediction_wall_s":predictor_s,
            "actual_original_MEC_builder_wall_s":builder_s,
        })
    first=entries[0]
    actionable=[
        (tuple(move["accepted_score_key"]),e["rank"])
        for e in entries for move in e["candidate_actionable_reuse"]]
    if first["original_MEC_baseline_proxy_key"][0]==0:
        chosen=1
        rationale="rank1_original_proxy_already_zero_violations"
    elif actionable:
        chosen=min(actionable)[1]
        rationale="best_accepted_old_MEC_one_step_reuse"
    else:
        chosen=1
        rationale="no_accepted_inserted_task_reuse"
    predicted=entries[chosen-1]
    return {
        "removed_task":tid,
        "old_source_frozen_SHA":content_hash(source),
        "original_total_legal_options":len(options),
        "top3_original_positions":entries,
        "reconstructed_heuristic_policy":{
            "chosen_rank":chosen,
            "rationale":rationale,
            "old_rank1_queue_pass":first["old_MEC_reconstruction_queue_pass"],
            "chosen_queue_pass":predicted["old_MEC_reconstruction_queue_pass"],
            "old_rank1_queue_reason_count":first["old_MEC_reconstruction_queue_reasons"],
            "chosen_queue_reason_count":predicted[
                "old_MEC_reconstruction_queue_reasons"],
            "changed_original_rank":chosen!=1,
        },
    }


def run(file:Path,out:Path,cases):
    if out.exists():raise FileExistsError(out)
    raw=json.loads(file.read_text(encoding="utf-8"))
    scene=int(raw["protocol"]["independent_scenario_seed"])
    selected=[(p,int(seed)) for p,seed in cases]
    if scene not in CASES or not raw.get("complete") or any(
        item not in CASES[scene] for item in selected):
        raise ValueError("P16 only uses the P12 frozen development scenario set")
    idx={(r["profile"],int(r["seed"]),r["method"]):r
         for r in raw["rows"]}
    report={
        "complete":False,
        "protocol":{
            "id":"P16_original_MEC_critical_pool_reuse_actionability_broad_development_v1",
            "scene":scene,"source_file_SHA":content_hash(raw),
            "all_previously_seen_cases":True,
            "only_existing_critical_task_MEC_proxy_and_single_contact_reuse":True,
            "no_CVX_or_numerical_oracle_in_ranking_or_attribution":True,
            "P15_firstuse_results_not_used_to_tune_any_P16_params":True,
            "original_ALNS_and_Physics_unchanged":True,
        },
        "rows":[],"errors":[],
    }
    write_json(out,report)
    for profile,seed in selected:
        original=idx[profile,seed,"B-ALNS"]
        instance=restore_instance(raw["profiles"][profile]["instance"])
        if content_hash(instance)!=raw["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Frozen physical instance mismatch")
        solution=restore_solution(original["solution"])
        old_sha=content_hash(solution)
        if old_sha!=original["solution_sha256"]:
            raise RuntimeError("Original B checkpoint changed")
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "source_B_strict_stage1":original["stage1_qualified"],
            "source_sha":old_sha,"tested_task_cases":[],
        }
        report["rows"].append(row)
        write_json(out,report)
        try:
            for tid in _task_candidates(instance,solution):
                case=probe_task(instance,solution,tid)
                row["tested_task_cases"].append(case)
                write_json(out,report)
                summary=case["reconstructed_heuristic_policy"]
                print("P16_GENERAL_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,"task":tid,
                    "old_queue_pass":summary["old_rank1_queue_pass"],
                    "chosen_queue_pass":summary["chosen_queue_pass"],
                    "ranks":[e["rank"] for e in case["top3_original_positions"]
                             if e["candidate_actionable_reuse"]],
                    "choice":summary["chosen_rank"],
                    "original_MEC_actually_offloaded_inserted_task":[
                        e["rank"] for e in case["top3_original_positions"]
                        if any(m.get("task_id")==tid and
                               m.get("type")=="reuse_contact"
                               for m in e["real_original_greedy_actions"])
                    ],
                },ensure_ascii=False),flush=True)
            if content_hash(solution)!=old_sha:
                raise RuntimeError("Changed original B physical D")
        except Exception as exc:
            error={"scene":scene,"profile":profile,"seed":seed,
                   "type":type(exc).__name__,"message":str(exc)}
            row["error"]=error
            report["errors"].append(error)
        write_json(out,report)
    report["complete"]=True
    cases=[x for r in report["rows"] for x in r["tested_task_cases"]]
    all_rows=[e for c in cases for e in c["top3_original_positions"]]
    report["summary"]={
        "frozen_sources":len(report["rows"]),
        "removed_task_counterfactuals":len(cases),
        "frozen_top3_full_D":len(all_rows),
        "real_first_MEC_move_is_reuse_of_newly_inserted_task":sum(
            bool(e["first_real_greedy_MEC_action"] and
                 e["first_real_greedy_MEC_action"].get("type")=="reuse_contact"
                 and e["first_real_greedy_MEC_action"].get("task_id")==c["removed_task"])
            for c in cases for e in c["top3_original_positions"]),
        "original_top1_was_changed_by_actionability":sum(
            c["reconstructed_heuristic_policy"]["changed_original_rank"]
            for c in cases),
        "changed_rank_advanced_necessary_queue_feasibility":sum(
            (not c["reconstructed_heuristic_policy"]["old_rank1_queue_pass"]
             and c["reconstructed_heuristic_policy"]["chosen_queue_pass"])
            for c in cases),
        "changed_rank_lost_old_queue_passing":sum(
            c["reconstructed_heuristic_policy"]["old_rank1_queue_pass"]
            and not c["reconstructed_heuristic_policy"]["chosen_queue_pass"]
            for c in cases),
        "total_prediction_wall_s":sum(
            e["prediction_wall_s"] for e in all_rows),
        "total_full_original_MEC_builder_wall_s":sum(
            e["actual_original_MEC_builder_wall_s"] for e in all_rows),
        "unexpected_errors":len(report["errors"]),
    }
    write_json(out,report)
    print("P16_GENERAL_SUMMARY="+json.dumps({
        "scene":scene,**report["summary"]},ensure_ascii=False),flush=True)
    if report["errors"]:
        raise RuntimeError("Unexpected P16 audit error "+str(report["errors"][:2]))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--cases",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.source,args.output,[x.split(":") for x in args.cases.split(",")])
