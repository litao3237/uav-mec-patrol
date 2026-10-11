"""Queue-certificate-guided feasibility repair for archived K80 failures.

A *diagnostic* comparison against the frozen original:
    (1) Greedy MEC repair
    (2) old-LB-guided joint local/contact repairs
    (3) queue-LB scoring on the SAME legacy candidate generator
    (4) queue-aware *dependency repair*: consider FIFO-blocking predecessor
        tasks, contact reuse/insertion and cross-UAV task reassignment.

Only the last arm changes the neighborhood. Every arm starts from the exact
same previously failed B-ALNS structure; no original ESI is run beforehand.
Stage-1/2 strict constraints and residual audits are unchanged, and budgets
for beam depth, width and strict CVX candidate checks are fixed. This probe
is not yet a matched *end-to-end* metaheuristic benchmark.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import _legacy_rescue_reference as legacy

from experiment_common import current_source_hashes, provenance
from run_seven_methods import finalize
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import (
    ProxyObjectiveEvaluator, solution_signature,
)
from uav_mec.algorithms.alns.operators import (
    _destroy_tasks, _options_for_task, _apply_local_insertion,
)
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations,
    _existing_contacts_after_task,
    _insert_contact_candidate,
    _reuse_contact_candidate,
)
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,restore_solution,write_json,content_hash,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


ARMS=("original_greedy","legacy_joint","queue_rank_same_moves","queue_dependency_joint")
STRESS_PROFILES=("compute_x1p5","compute_x2p0","deadline_x0p9","deadline_x0p8")


def queue_gap(instance, solution):
    info=build_event_info(instance,solution)
    q=queue_aware_feasibility_precheck(instance,solution,info)
    per_task={
        tid:max(
            0.0,
            q.task_completion_lb_s[tid]
            -instance.tasks[tid].release_s
            -instance.tasks[tid].deadline_s,
        )
        for tid in instance.tasks
    }
    cycle_excess=sum(max(0.0,t-instance.cycle_s) for t in q.return_time_lb_s.values())
    delay_excess=max(0.0,q.avg_delay_lb_s-instance.avg_delay_budget_s)
    violators=sorted(
        [(v,tid,solution.task_decisions[tid].mode.value)
         for tid,v in per_task.items() if v>1e-8],reverse=True,
    )
    return {
        "passed":q.feasible,
        "n_reasons":len(q.reasons),
        "total_optimistic_excess_s":sum(per_task.values())+cycle_excess+delay_excess,
        "task_offenders":[
            {"task_id":tid,"mode":mode,"excess_s":v}
            for v,tid,mode in violators
        ],
        "offenders_by_execution_mode":dict(Counter(v[2] for v in violators)),
        "reasons":list(q.reasons),
        "max_excess_s":max(per_task.values(),default=0.0),
        "flight_distance_m":sum(info.route_distance_m.values()),
    }


def added_dependency_moves(instance, solution, *, limit=3, max_per_uav=1):
    """Enlarge only queue-driven repairs, with strict structural validation."""
    state=UavMecState(instance,deepcopy(solution),ProxyObjectiveEvaluator())
    p=queue_gap(instance,solution)
    info=build_event_info(instance,solution)
    candidates=[]
    seen={solution_signature(solution)}
    for item in p["task_offenders"][:limit]:
        task_id=item["task_id"]
        # For late LOCAL tasks, long-running PREDECESSOR tasks in the same
        # UAV FIFO queue can cause lateness; offloading the predecessor can
        # release all later local deadlines even if that predecessor meets its
        # own deadline. This dependency is missed by the old violation-only
        # scorer.
        if item["mode"]=="local":
            owner=info.task_owner[task_id]
            local_seq=info.local_order[owner]
            if task_id in local_seq:
                earlier=local_seq[:local_seq.index(task_id)]
                earlier=sorted(
                    earlier,
                    key=lambda t:instance.tasks[t].workload_gcycles,
                    reverse=True,
                )[:2]
                for prior_task in earlier:
                    for contact in list(_existing_contacts_after_task(
                        solution,prior_task,
                    )):
                        try:
                            c=_reuse_contact_candidate(
                                instance,solution,task_id=prior_task,visit_id=contact,
                            )
                            candidates.append((
                                f"fifo_predecessor_reuse::{prior_task}::{contact}",c,
                            ))
                        except ValueError:
                            pass
                    if len(solution.routes[owner].contact_visit_ids()) < instance.max_contacts_per_uav:
                        for _,point,pos in _best_new_contact_locations(
                            instance,solution,prior_task,
                            limit=4,per_mec=1,
                        )[:2]:
                            try:
                                c=_insert_contact_candidate(
                                    instance,solution,task_id=prior_task,
                                    point_id=point,insert_pos=pos,
                                )
                                candidates.append((
                                    f"fifo_predecessor_new_contact::{prior_task}::{point}@{pos}",c,
                                ))
                            except ValueError:
                                pass

        # Cross-UAV relocation changes route AND effective local FIFO queue.
        # Retained MEC batches cannot be broken: original offloaded tasks
        # keep their contacts except the moved task, which becomes LOCAL.
        destroyed=_destroy_tasks(state,[task_id])
        options=_options_for_task(destroyed,task_id)
        original_owner=info.task_owner[task_id]
        chosen=set()
        for opt in options:
            if opt.uav_id==original_owner or opt.uav_id in chosen:
                continue
            chosen.add(opt.uav_id)
            variant=destroyed.copy()
            _apply_local_insertion(variant,task_id,opt)
            try:
                validate_solution(instance,variant.solution)
            except (ValueError,KeyError):
                continue
            candidates.append((
                f"cross_uav_fifo_relocation::{task_id}->{opt.uav_id}@{opt.position}",
                variant.solution,
            ))
            if len(chosen)>=max_per_uav*max(1,len(instance.uavs)-1):
                break
    unique=[]
    for label,c in candidates:
        sig=solution_signature(c)
        if sig in seen:
            continue
        seen.add(sig)
        unique.append((label,c))
    return unique


def new_move_candidates(instance, solution, *, mode, offenders=3):
    # Shared base candidate set is *exactly* the previous diagnostic's
    # generator, so score-only and structural-neighborhood effects can be
    # separated. Queue dependency mode appends new repair actions.
    candidates=legacy.candidate_moves(
        instance,solution,
        families=("reorder","contact_mode"),
        limit_offenders=offenders,
    )
    if mode=="queue_dependency_joint":
        candidates.extend(
            added_dependency_moves(instance,solution,limit=offenders)
        )
    seen=set()
    result=[]
    for label,c in candidates:
        sig=solution_signature(c)
        if sig in seen or sig==solution_signature(solution):
            continue
        seen.add(sig)
        result.append((label,c))
    return result


def search_queue(instance, initial, *, mode, beam_width=2,
                 max_depth=2, exact_limit=3):
    assert mode in {"queue_rank_same_moves","queue_dependency_joint"}
    init=queue_gap(instance,initial)
    seen={solution_signature(initial)}
    beam=[("start",deepcopy(initial),init)]
    passing=[]
    generated=0
    trace=[]
    for depth in range(1,max_depth+1):
        layer=[]
        for _,current,_ in beam:
            for label,c in new_move_candidates(
                instance,current,mode=mode,
            ):
                sig=solution_signature(c)
                if sig in seen:continue
                seen.add(sig)
                generated+=1
                status=queue_gap(instance,c)
                rank=(
                    not status["passed"],
                    status["n_reasons"],
                    status["total_optimistic_excess_s"],
                    status["flight_distance_m"],
                    label,
                )
                layer.append((rank,label,c,status))
                if status["passed"]:
                    passing.append((rank,label,c,status,depth))
        layer.sort(key=lambda x:x[0])
        trace.append({
            "depth":depth,
            "generated":len(layer),
            "passing":sum(x[3]["passed"] for x in layer),
            "best_gap_s":layer[0][3]["total_optimistic_excess_s"]
                if layer else None,
        })
        if not layer:break
        beam=[(l,c,s) for _,l,c,s in layer[:beam_width]]
    passing.sort(key=lambda x:x[0])
    return passing[:exact_limit],{
        "original_queue_lb":init,
        "unique_generated":generated,
        "queue_pass_candidates":len(passing),
        "depth":trace,
    }


def strict_queue_repair(instance, source, *, mode,
                        beam_width=2,max_depth=2,exact_limit=3):
    t0=perf_counter()
    shortlist,stats=search_queue(
        instance,source,mode=mode,
        beam_width=beam_width,max_depth=max_depth,exact_limit=exact_limit,
    )
    oracle=Stage1CVXObjectiveOracle()
    eligible=[]
    exact_records=[]
    for _,label,c,pressure,depth in shortlist:
        solved=oracle.solve(instance,c)
        qualified=stage1_is_qualified(solved)
        exact_records.append({
            "move":label,"depth":depth,
            "stage1_status":solved.diagnostics.get("stage1_status"),
            "stage1_qualified":qualified,
            "stage1_energy_j":solved.energy_stage1_j if qualified else None,
        })
        if qualified:
            eligible.append((float(solved.energy_stage1_j),label,c))
    result={
        "arm":mode,
        "original_queue_lb":stats["original_queue_lb"],
        "generated_unique":stats["unique_generated"],
        "queue_precheck_passing":stats["queue_pass_candidates"],
        "strict_cvx_calls":oracle.calls,
        "strict_stage1_qualified_candidates":len(eligible),
        "strict_both_recovered":False,
        "recovery_energy_j":None,
        "accepted_move":None,
        "search_trace":stats["depth"],
        "cvx_records":exact_records,
    }
    if eligible:
        energy,label,c=min(eligible,key=lambda x:x[0])
        # Count recovery only after fresh, independent resource solves,
        # including full Stage-2 and original saved/reconstructed auditing.
        done=finalize(
            instance,c,method=mode,seed=None,
            initialization_s=0.0,search_s=0.0,
            diagnostics={"accepted_move":label,"precheck":stats},
        )
        result.update({
            "strict_both_recovered":bool(
                done["stage1"]["qualified"] and done["stage2"]["qualified"]
            ),
            "recovery_energy_j":(
                float(done["resources"].energy_stage1_j)
                if done["stage1"]["qualified"] and done["stage2"]["qualified"]
                else None
            ),
            "final_stage1_status":done["resources"].diagnostics.get("stage1_status"),
            "accepted_move":label,
            "repaired_solution_sha256":content_hash(c),
        })
    result["runtime_s"]=perf_counter()-t0
    return result


def old_repair(instance, source, *, arm, beam_width,max_depth,exact_limit):
    result=legacy.strict_recovery(
        instance,source,arm,
        exact_limit=exact_limit,beam_width=beam_width,max_depth=max_depth,
    )
    return {
        "arm":arm,
        "generated_unique":result.get("n_candidates_generated",0),
        "queue_precheck_passing":None,
        "old_precheck_passing":result.get("n_precheck_pass",0),
        "strict_cvx_calls":result.get("n_stage1_CVX_calls",0),
        "strict_stage1_qualified_candidates":int(
            result.get("stage1_qualified",False)
        ),
        "strict_both_recovered":result.get("both_qualified",False),
        "recovery_energy_j":result.get("strict_energy_stage1_j"),
        "accepted_move":result.get("accepted_move"),
        "runtime_s":result.get("runtime_s"),
        "legacy_details":result,
    }


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    raw=json.loads(args.input.read_text(encoding="utf-8"))
    if raw["protocol"]["id"]!="uav_mec_one_factor_coupling_sensitivity_v1" or not raw["complete"]:
        raise ValueError("Expected completed independent sensitivity source")
    K,S=raw["protocol"]["task_scale"],raw["protocol"]["independent_scenario_seed"]
    if K!=80:
        raise ValueError("Only K80 stress scenarios included")
    index={
        (r["profile"],r["seed"],r["method"]):r
        for r in raw["rows"]
    }
    output={
        "complete":False,
        "protocol":{
            "id":"queue_certificate_guided_repair_comparison_v1",
            "tasks":K,"scenario":S,
            "source_original_workflow_run":38043248604,
            "physical_profiles":list(STRESS_PROFILES),
            "arms":list(ARMS),
            "same_archived_failed_B_ALNS_structure":True,
            "max_beam_width":args.beam_width,
            "max_depth":args.depth,
            "max_exact_CVX_candidates_per_guided_arm":args.exact_limit,
            "original_develop_not_modified":True,
            "not_equal_wall_time":True,
            "source_hashes":current_source_hashes(Path(__file__)),
            "provenance":provenance(),
        },
        "rows":[],
    }
    write_json(args.output,output)
    failures=[]
    for profile in STRESS_PROFILES:
        instance=restore_instance(raw["profiles"][profile]["instance"])
        for seed in raw["protocol"]["algorithm_seeds"]:
            record=index[(profile,seed,"B-ALNS")]
            diag=record.get("resources",{}).get("diagnostics",{})
            qualified=record.get("both_qualified",False)
            status=diag.get("stage1_status","error")
            row={
                "profile":profile,"scenario":S,"seed":seed,
                "source_stage1_status":status,
                "eligible":status=="infeasible_precheck",
                "source_both_qualified":qualified,
                "source_solution_sha256":record.get("solution_sha256"),
                "arms":{},
            }
            if row["eligible"]:
                solution=restore_solution(record["solution"])
                row["old_lb"]=legacy.precheck_score(instance,solution)
                row["new_queue_lb"]=queue_gap(instance,solution)
                for arm in ARMS:
                    try:
                        if arm=="original_greedy":
                            result=old_repair(
                                instance,solution,arm="greedy_mec",
                                beam_width=args.beam_width,max_depth=args.depth,
                                exact_limit=args.exact_limit,
                            )
                        elif arm=="legacy_joint":
                            result=old_repair(
                                instance,solution,arm="guided_joint",
                                beam_width=args.beam_width,max_depth=args.depth,
                                exact_limit=args.exact_limit,
                            )
                        else:
                            result=strict_queue_repair(
                                instance,solution,mode=arm,
                                beam_width=args.beam_width,max_depth=args.depth,
                                exact_limit=args.exact_limit,
                            )
                        row["arms"][arm]=result
                        print(
                            f"QUEUE_RESCUE K{K} S{S} A{seed} {profile} {arm} "
                            f"n={result.get('generated_unique')} "
                            f"passed_queue={result.get('queue_precheck_passing')} "
                            f"strict_recovered={result.get('strict_both_recovered')} "
                            f"CVX={result.get('strict_cvx_calls')} "
                            f"seconds={result.get('runtime_s'):.3f}",
                            flush=True,
                        )
                    except Exception as exc:
                        row["arms"][arm]={
                            "error_type":type(exc).__name__,
                            "error_message":str(exc),
                            "strict_both_recovered":False,
                        }
                        failures.append({
                            "scenario":S,"seed":seed,
                            "profile":profile,"arm":arm,
                            "error":str(exc),
                        })
            output["rows"].append(row)
            write_json(args.output,output)
    output["complete"]=True
    output["unexpected_errors"]=failures
    output["summary"]={
        arm:{
            "eligible":sum(r["eligible"] for r in output["rows"]),
            "strict_both_recovered":sum(
                bool(r["arms"].get(arm,{}).get("strict_both_recovered"))
                for r in output["rows"]
            ),
            "queue_precheck_passing_cases":sum(
                r["arms"].get(arm,{}).get("queue_precheck_passing",0)>0
                for r in output["rows"] if r["eligible"]
            ) if arm.startswith("queue") else None,
        } for arm in ARMS
    }
    write_json(args.output,output)
    print("QUEUE_RESCUE_SUMMARY="+json.dumps(output["summary"],ensure_ascii=False),flush=True)
    if failures:
        raise RuntimeError(f"Unexpected queue repair exceptions, preserved: {failures[:3]}")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--beam-width",type=int,default=2)
    p.add_argument("--depth",type=int,default=2)
    p.add_argument("--exact-limit",type=int,default=3)
    args=p.parse_args()
    if min(args.beam_width,args.depth,args.exact_limit)<=0:
        raise ValueError("All budgets must be positive")
    run(args)


if __name__=="__main__":
    main()
