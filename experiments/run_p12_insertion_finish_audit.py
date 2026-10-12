"""P12 structural ranking attribution for ORIGINAL _insertion_option/_finish_repair.

This is a paired, offline COUNTERFACTUAL on already-inspected S89-S96
physical scenarios and SHA-256 frozen original B-ALNS endpoint solutions.

Part A fixes an ORIGINAL discrete D and removes exactly ONE task.
The SAME destroyed state and task are used to replay the entire
unchanged _options_for_task() ranking. For up to 12 preregistered
positions (always including original rank1), apply the ORIGINAL
_apply_local_insertion(), measure the true FIFO/EDF necessary timing
lower bound on the restored all-local D, then run the EXACT ORIGINAL
_finish_repair(), and repeat timing. No new sorting policy is used
to change the decisions of the actual old code in this experiment.

Part B uses the ORIGINAL critical destroy q≈15% of tasks and the
original cheapest/regret2 insertion repair. A read-only spy on
_finish_repair captures the COMPLETE route-only state just before
the same unchanged MEC rebuild, and the finished full solution.
This represents real 12-task ALNS repair, not only a 1-task corner.

A ≤3-candidate EXTRA post-hoc Stage1+Stage2 numerical audit per
chosen single-task source contrasts original top1 pre/post versus
best among the PRE-REGISTERED sampled positions. This diagnostic
CVX is not equal-budget ALNS nor evidence of algorithm improvement.
Necessary feasibility passes are NEVER called strictly feasible.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np

from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
)
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as alns_ops
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)

# These scenes and stochastic seeds were ALL exposed in earlier P3/P5/P7.
# They are selected mechanistic examples and are NOT an unseen holdout.
CASES={
    89:(("deadline_x0p9",128),),
    91:(("compute_x1p5",128),),
    93:(("compute_x1p5",130),("baseline",129)),
    95:(("compute_x2p0",130),),
    96:(("deadline_x0p9",130),),
}
MAX_TASKS_PER_SOURCE=2
MAX_OPTIONS_PER_TASK=12
MAX_CVX_STAGE1_EXTRA_PER_TASK=3


def queue_metrics(instance,solution):
    ev=build_event_info(instance,solution)  # calls ORIGINAL full validator
    q=queue_aware_feasibility_precheck(instance,solution,ev)
    deadline_excess=[
        max(0.,float(q.task_completion_lb_s[tid])-
            (task.release_s+task.deadline_s))
        for tid,task in instance.tasks.items()
    ]
    ratios=[
        e/max(1.,task.deadline_s)
        for e,task in zip(deadline_excess,instance.tasks.values())
    ]
    average_excess=max(0.,q.avg_delay_lb_s-instance.avg_delay_budget_s)
    period_excess=[
        max(0.,t-instance.cycle_s) for t in q.return_time_lb_s.values()
    ]
    norm=sum(ratios)+average_excess/max(1.,instance.avg_delay_budget_s)
    norm+=sum(x/max(1.,instance.cycle_s) for x in period_excess)
    return {
        "queue_necessary_pass":bool(q.feasible),
        "queue_reason_count":len(q.reasons),
        "late_task_count":sum(x>1e-4 for x in deadline_excess),
        "total_task_deadline_excess_s":sum(deadline_excess),
        "worst_task_deadline_excess_s":max(deadline_excess,default=0.),
        "total_normalized_all_constraint_excess":norm,
        "max_task_normalized_excess":max(ratios,default=0.),
        "average_delay_lb_excess_s":average_excess,
        "max_cycle_lb_excess_s":max(period_excess,default=0.),
        "route_total_distance_m":sum(ev.route_distance_m.values()),
        "MEC_offloaded_count":sum(len(x) for x in ev.batch_tasks.values()),
        "MEC_contact_count":len(ev.batch_tasks),
    }


def queue_rank(metric):
    # Ranking for DIAGNOSIS ONLY, never passed into ALNS.
    return (
        not metric["queue_necessary_pass"],
        metric["queue_reason_count"],
        metric["total_normalized_all_constraint_excess"],
        metric["worst_task_deadline_excess_s"],
        metric["route_total_distance_m"],
    )


def material_queue_improvement(challenger,original):
    if challenger["queue_necessary_pass"] and not original["queue_necessary_pass"]:
        return True
    if challenger["queue_reason_count"]<original["queue_reason_count"]:
        return True
    if challenger["queue_reason_count"]==original["queue_reason_count"]:
        return (
            challenger["total_normalized_all_constraint_excess"]<
            original["total_normalized_all_constraint_excess"]-1e-4)
    return False


def _ranks(total,max_options):
    if total<=max_options:return list(range(1,total+1))
    # Cover true original top1 (and top6), not just other nearby ties.
    top=list(range(1,min(6,total)+1))
    extra_n=max_options-len(top)
    if extra_n<=0:return top[:max_options]
    tail=[
        7+round(i*(total-7)/max(1,extra_n-1))
        for i in range(extra_n)
    ]
    order=sorted({*top,*tail,total})
    if len(order)>max_options:
        # Highest original rank, top rank and evenly distributed tail.
        order=[*top,*order[len(top)+1:]]
        order=sorted(set(order))
        while len(order)>max_options:
            order.pop(-2)
    return order


def _task_candidates(instance,source,max_tasks=MAX_TASKS_PER_SOURCE):
    ev=build_event_info(instance,source)
    q=queue_aware_feasibility_precheck(instance,source,ev)
    priority=sorted(instance.tasks,key=lambda tid:(
        -max(0.,q.task_completion_lb_s[tid]-
             (instance.tasks[tid].release_s+instance.tasks[tid].deadline_s))/
              max(1.,instance.tasks[tid].deadline_s),
        -instance.tasks[tid].workload_gcycles,tid))
    if not priority:return []
    result=[priority[0]]
    original_mode=source.task_decisions[priority[0]].mode
    for tid in priority[1:]:
        if source.task_decisions[tid].mode != original_mode:
            result.append(tid)
            break
    for tid in priority:
        if len(result)>=max_tasks:break
        if tid not in result:result.append(tid)
    return result[:max_tasks]


def _structural_changes(before,after):
    keys=set(before.task_decisions)|set(after.task_decisions)
    decision_changes=sum(
        before.task_decisions.get(t)!=after.task_decisions.get(t)
        for t in keys)
    contacts_added=len(set(after.contact_visits)-set(before.contact_visits))
    contacts_removed=len(set(before.contact_visits)-set(after.contact_visits))
    contact_changed=sum(
        before.contact_visits[v]!=after.contact_visits[v]
        for v in set(before.contact_visits)&set(after.contact_visits))
    return {
        "real_discrete_decisions_changed":int(decision_changes),
        "contact_visits_added":contacts_added,
        "contact_visits_removed":contacts_removed,
        "contact_visits_retargeted":contact_changed,
        "physical_signature_changed":(
            solution_signature(before)!=solution_signature(after)),
        "MEC_repair_recorded_steps":int(after.metadata.get("mec_repair_steps",0)),
        "MEC_repair_move_trace":after.metadata.get("mec_repair_moves",[])[:8],
    }


def _strict_numerical_check(instance,solution):
    start=perf_counter()
    oracle=Stage1CVXObjectiveOracle()
    check=oracle.solve(instance,solution)
    first=bool(stage1_is_qualified(check))
    result={
        "candidate_sha256":content_hash(solution),
        "Stage1_solver_status":check.diagnostics.get("stage1_status"),
        "Stage1_strict_qualified":first,
        "Stage1_CVX_calls":oracle.calls,
        "Stage2_strict_qualified":None,
        "Stage1_and_Stage2_strict":False,
        "strict_energy_j":None,
    }
    if first:
        evaluated=finalize(
            instance,solution,method="P12_posthoc_insertion_rank_audit",
            seed=None,initialization_s=0.,search_s=0.,
            diagnostics={"P12":"extra_posthoc_oracle_not_part_of_ALNS"},
        )
        second=bool(evaluated["stage2"]["qualified"])
        result["Stage2_strict_qualified"]=second
        result["Stage1_and_Stage2_strict"]=bool(
            evaluated["stage1"]["qualified"] and second)
        if result["Stage1_and_Stage2_strict"]:
            result["strict_energy_j"]=float(
                evaluated["resources"].energy_stage1_j)
    result["strict_posthoc_wall_s"]=perf_counter()-start
    return result


def _task_counterfactual(instance,source,task_id,*,sample_max=MAX_OPTIONS_PER_TASK,
                         include_strict=True):
    original_h=content_hash(source)
    frozen=UavMecState(
        instance,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=alns_ops._destroy_tasks(frozen,[task_id])
    options=alns_ops._options_for_task(destroyed,task_id)
    sample=_ranks(len(options),sample_max)
    evaluated=[]
    kept={}
    for rank in sample:
        option=options[rank-1]
        state=destroyed.copy()
        alns_ops._apply_local_insertion(state,task_id,option)
        if state.removed_tasks:raise RuntimeError("Single task remains partially removed")
        local=deepcopy(state.solution)
        validate_solution(instance,local)
        before=queue_metrics(instance,local)
        ts=perf_counter()
        fixed=alns_ops._finish_repair(state)  # UNCHANGED PRODUCTION FUNCTION
        repair_wall_s=perf_counter()-ts
        final=deepcopy(fixed.solution)
        after=queue_metrics(instance,final)
        change=_structural_changes(local,final)
        entry={
            "original_insertion_rank":rank,
            "original_insertion_key":list(option.key),
            "destination_UAV":option.uav_id,
            "position":option.position,
            "before_MEC_rebuild":before,
            "after_MEC_rebuild":after,
            "structural_effect":change,
            "original_MEC_builder_wall_s":repair_wall_s,
            "local_structure_sha256":content_hash(local),
            "repaired_structure_sha256":content_hash(final),
        }
        kept[rank]={"before":local,"after":final}
        evaluated.append(entry)
    if 1 not in kept:raise RuntimeError("P12 omitted the actual original top-ranked insertion")
    ordered=sorted(evaluated,key=lambda v:(
        queue_rank(v["after_MEC_rebuild"]),v["original_insertion_rank"]))
    best=ordered[0]
    top=next(r for r in evaluated if r["original_insertion_rank"]==1)
    later=[r for r in evaluated if r["original_insertion_rank"]!=1
           and material_queue_improvement(
               r["after_MEC_rebuild"],top["after_MEC_rebuild"])]
    # Compare exact same original-task physical source and removed set:
    # original top1 vs queue-best among sampled legal alternatives.
    positive=(
        any(r["after_MEC_rebuild"]["queue_necessary_pass"] and
            not top["after_MEC_rebuild"]["queue_necessary_pass"]
            for r in later))
    record={
        "task_id":task_id,
        "original_offloading_mode":source.task_decisions[task_id].mode.value,
        "original_solution_sha256":original_h,
        "destroyed_structural_sha256":content_hash(destroyed.solution),
        "all_original_legal_positions":len(options),
        "sampled_original_ranks":sample,
        "sampled_positions":evaluated,
        "original_first_rank_after_MEC":top["after_MEC_rebuild"],
        "queue_best_sampled_original_rank":best["original_insertion_rank"],
        "queue_best_sampled_after_MEC":best["after_MEC_rebuild"],
        "sampled_strictly_better_queue_alternatives":len(later),
        "any_alternative_becomes_queue_necessary_passing":bool(positive),
        "original_top1_before_to_after_queue_reason_delta":(
            top["after_MEC_rebuild"]["queue_reason_count"]-
            top["before_MEC_rebuild"]["queue_reason_count"]),
        "original_top1_MEC_rebuild_physical_signature_changed":(
            top["structural_effect"]["physical_signature_changed"]),
        "strict_posthoc":{"checked":False},
    }
    if include_strict:
        subjects={
            "original_top1_before_rebuild":kept[1]["before"],
            "original_top1_after_rebuild":kept[1]["after"],
            "best_sampled_after_rebuild":kept[best["original_insertion_rank"]]["after"],
        }
        results={}
        outcomes_cache={}
        for label,sol in subjects.items():
            physical_key=solution_signature(sol)
            if physical_key in outcomes_cache:
                results[label]={
                    **outcomes_cache[physical_key],
                    "reused_identical_physical_structure":True}
            else:
                if len(outcomes_cache)>=MAX_CVX_STAGE1_EXTRA_PER_TASK:
                    raise RuntimeError("Extra diagnostic Stage1 quota unexpectedly exceeded")
                result=_strict_numerical_check(instance,sol)
                outcomes_cache[physical_key]=result
                results[label]=result
        record["strict_posthoc"]={
            "checked":True,
            "distinct_extra_Stage1_candidates":len(outcomes_cache),
            "extra_Stage1_oracle_calls":sum(
                x["Stage1_CVX_calls"] for x in outcomes_cache.values()),
            "candidates":results,
        }
    if content_hash(source)!=original_h:
        raise RuntimeError("Counterfactual changed the frozen original source D")
    return record


def _actual_multi_task_original_repair(instance,source,seed):
    base=UavMecState(
        instance,deepcopy(source),ScreenedProxyObjectiveEvaluator())
    destroyed=alns_ops.critical_task_removal(
        base,np.random.default_rng(seed),
        config=alns_ops.DestroyConfig())
    removed=list(destroyed.removed_tasks)
    if not removed:raise RuntimeError("Original ALNS critical destroy empty")
    outcomes={}
    original_finish=alns_ops._finish_repair

    def finish_spy(state):
        local=deepcopy(state.solution)
        pre=queue_metrics(instance,local)
        result=original_finish(state)
        post=queue_metrics(instance,result.solution)
        record={
            "before_MEC_rebuild":pre,
            "after_MEC_rebuild":post,
            "structural_effect":_structural_changes(local,result.solution),
            "before_structure_sha256":content_hash(local),
            "after_structure_sha256":content_hash(result.solution),
        }
        captured.append(record)
        return result

    for label,repair in (
        ("original_cheapest_insertion_mec_repair",
         alns_ops.cheapest_insertion_repair),
        ("original_regret2_insertion_mec_repair",
         alns_ops.regret2_insertion_repair),
    ):
        captured=[]
        start=perf_counter()
        with patch.object(alns_ops,"_finish_repair",side_effect=finish_spy):
            completed=repair(destroyed,np.random.default_rng(seed+1))
        if len(captured)!=1:
            raise RuntimeError("Original repair did not call exactly one finish")
        outcomes[label]={
            "actual_removed_task_count":len(removed),
            "actual_removed_tasks":removed,
            "finished_exact_original_repair_sha256":content_hash(completed.solution),
            "posthoc_instrumented_repair_wall_s":perf_counter()-start,
            **captured[0],
        }
    return outcomes


def run(source_path:Path,output_path:Path,*,requested):
    if output_path.exists():raise FileExistsError("Never overwrite original fixed-source audit")
    frozen=json.loads(source_path.read_text(encoding="utf-8"))
    p=frozen["protocol"]
    scene=int(p["independent_scenario_seed"])
    if (not frozen.get("complete") or
        p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1"
        or scene not in CASES):
        raise ValueError("Expect frozen original B/ESI source on preregistered development scene")
    cases=[(profile,int(seed)) for profile,seed in requested]
    if not cases or any((pr,seed) not in CASES[scene] for pr,seed in cases):
        raise ValueError("P12 only allowed preregistered previously seen cases")
    records={
        (r["profile"],int(r["seed"]),r["method"]):r for r in frozen["rows"]
    }
    payload={
        "complete":False,
        "protocol":{
            "id":"P12_ALNS_Insertion_Position_To_Final_MEC_Rebuild_Attribution_v1",
            "scene":scene,
            "original_source_archive_sha256":content_hash(frozen),
            "previously_inspected_development_cases_only":True,
            "original_ALNS_insertion_key_and_finish_repair_untouched":True,
            "different_original_legal_insert_positions_same_destroyed_D":True,
            "sampled_option_count_per_task":MAX_OPTIONS_PER_TASK,
            "top1_original_insertion_always_included":True,
            "one_task_counterfactual_two_distinct_origin_tasks_max":True,
            "actual_full_12_task_original_cheapest_and_regret_repair":True,
            "posthoc_extra_CVX_not_matched_search_budget":True,
            "strict_stage1_stage2_original_unchanged":True,
            "original_Stage1_oracle_extra_limit_per_source":3,
            "all_metrics_FIF O_EDF".replace(" ",""): "necessary_not_strict_feasibility",
        },
        "rows":[],"errors":[],
    }
    write_json(output_path,payload)
    for profile,seed in cases:
        src=records[profile,seed,"B-ALNS"]
        frozen_sha=src["solution_sha256"]
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "source_B_stage1_status":(
                ((src.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status")),
            "source_B_Stage1_strict":bool(src["stage1_qualified"]),
            "original_B_sha256":frozen_sha,
            "single_task_counterfactuals":[],
            "real_multi_task_repair":{},
        }
        payload["rows"].append(row)
        write_json(output_path,payload)
        try:
            ins=frozen["profiles"][profile]
            instance=restore_instance(ins["instance"])
            if content_hash(instance)!=ins["instance_sha256"]:
                raise RuntimeError("Physical source instance SHA changed")
            solution=restore_solution(src["solution"])
            if content_hash(solution)!=frozen_sha:
                raise RuntimeError("Original B discrete source SHA changed")
            row["original_B_queue_necessary"]=queue_metrics(instance,solution)
            picked=_task_candidates(instance,solution)
            row["chosen_tasks_pre_registered_rule"]=picked
            for index,tid in enumerate(picked):
                detail=_task_counterfactual(
                    instance,solution,tid,include_strict=index==0)
                row["single_task_counterfactuals"].append(detail)
                write_json(output_path,payload)
                print("P12_INSERTION_TASK="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,
                    "task":tid,"mode":detail["original_offloading_mode"],
                    "all_positions":detail["all_original_legal_positions"],
                    "sampled":len(detail["sampled_positions"]),
                    "best_original_rank":detail["queue_best_sampled_original_rank"],
                    "better_alt":detail["sampled_strictly_better_queue_alternatives"],
                    "top1_queue_pass":detail["original_first_rank_after_MEC"]["queue_necessary_pass"],
                    "best_queue_pass":detail["queue_best_sampled_after_MEC"]["queue_necessary_pass"],
                    "extra_Stage1_CVX":detail["strict_posthoc"].get("extra_Stage1_oracle_calls",0),
                },ensure_ascii=False),flush=True)
            row["real_multi_task_repair"]=_actual_multi_task_original_repair(
                instance,solution,seed+4356)
            if content_hash(solution)!=frozen_sha:
                raise RuntimeError("Frozen original B state mutated")
            write_json(output_path,payload)
            print("P12_REAL_REPAIR="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "methods":{
                    name:{
                        "removed":v["actual_removed_task_count"],
                        "before_necessary":v["before_MEC_rebuild"]["queue_necessary_pass"],
                        "after_necessary":v["after_MEC_rebuild"]["queue_necessary_pass"],
                        "before_reasons":v["before_MEC_rebuild"]["queue_reason_count"],
                        "after_reasons":v["after_MEC_rebuild"]["queue_reason_count"],
                        "reassigns":v["structural_effect"]["real_discrete_decisions_changed"],
                    } for name,v in row["real_multi_task_repair"].items()
                },
            },ensure_ascii=False),flush=True)
        except Exception as exc:
            problem={
                "scene":scene,"profile":profile,"seed":seed,
                "type":type(exc).__name__,"message":str(exc),
            }
            row["error"]=problem
            payload["errors"].append(problem)
            print("P12_ERROR="+json.dumps(problem),flush=True)
        write_json(output_path,payload)
    payload["complete"]=True
    pairs=[t for r in payload["rows"]
           for t in r["single_task_counterfactuals"]]
    multi=[(name,snapshot) for r in payload["rows"]
           for name,snapshot in r["real_multi_task_repair"].items()]
    payload["summary"]={
        "cases":len(payload["rows"]),
        "single_task_tests":len(pairs),
        "sampled_counterfactual_positions":sum(len(t["sampled_positions"])
                                               for t in pairs),
        "old_top1_outperformed_by_at_least_one_sampled_later_position":sum(
            t["sampled_strictly_better_queue_alternatives"]>0 for t in pairs),
        "old_top1_failed_but_later_position_passed_queue_neccessary":sum(
            t["any_alternative_becomes_queue_necessary_passing"] for t in pairs),
        "original_top1_MEC_rebuild_physically_changed":sum(
            t["original_top1_MEC_rebuild_physical_signature_changed"]
            for t in pairs),
        "original_real_multi_task_repairs":len(multi),
        "real_original_MEC_builder_increased_queue_reason_count":sum(
            x["after_MEC_rebuild"]["queue_reason_count"]>
            x["before_MEC_rebuild"]["queue_reason_count"] for _,x in multi),
        "real_original_MEC_builder_decreased_queue_reason_count":sum(
            x["after_MEC_rebuild"]["queue_reason_count"]<
            x["before_MEC_rebuild"]["queue_reason_count"] for _,x in multi),
        "program_errors":len(payload["errors"]),
    }
    write_json(output_path,payload)
    print("P12_INSERTION_FINISH_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"Incomplete original-function P12 trace {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--cases",required=True,
                   help="comma-separated profile:algorithmseed")
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    run(args.source,args.output,
        requested=[(token.split(":")[0],int(token.split(":")[1]))
                   for token in args.cases.split(",")])
