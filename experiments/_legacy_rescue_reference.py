"""Probe repair of high-load UAV-MEC *fixed-structure* infeasibility certificates.

Loads failed B-ALNS structures directly from the archived independent
sensitivity run 38043248604. Retains successful and non-precheck-failure
cases as coverage metadata. Tests original MEC greedy repair against
CERTIFICATE-GUIDED moves: (1) move late-collected task earlier, (2) revise
MEC contact/order and execution decision, (3) their combination.

The primary outcome is strict Stage-1 + Stage-2 recovery from an originally
precheck-infeasible discrete solution. This is a *diagnostic feasibility
probe*, not a full equal-runtime algorithm benchmark or proof that any
unrecovered MILP instance is globally infeasible.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from experiment_common import current_source_hashes, provenance
from run_seven_methods import finalize
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import ProxyObjectiveEvaluator, solution_signature
from uav_mec.algorithms.alns.problem_operators import (
    _apply_task_decision, _mode_candidates,
    _relocate_contact_candidates,
)
from uav_mec.algorithms.initial import (
    build_mec_assisted_initial_solution, evaluate_initial_proxy,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.domain import Route, RouteStop, StopType, ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import fast_feasibility_precheck


ARMS=("greedy_mec", "guided_reorder", "guided_contact_mode", "guided_joint")
STRESS_PROFILES=("compute_x1p5","compute_x2p0","deadline_x0p9","deadline_x0p8")


def precheck_score(instance, solution):
    info=build_event_info(instance,solution)
    p=fast_feasibility_precheck(instance,solution,info)
    deadline_excess={
        tid:max(0.,lb-instance.tasks[tid].release_s-instance.tasks[tid].deadline_s)
        for tid,lb in p.task_completion_lb_s.items()
    }
    avg_lb=sum(
        p.task_completion_lb_s[t]-instance.tasks[t].release_s
        for t in instance.tasks
    )/len(instance.tasks)
    gap_cycle=sum(max(0.,t-instance.cycle_s) for t in p.return_time_lb_s.values())
    gap_avg=max(0.,avg_lb-instance.avg_delay_budget_s)
    total=sum(deadline_excess.values())+gap_cycle+gap_avg
    # Record all task types; offloaded batch EDF tasks are a key diagnostic.
    violators=[
        (excess,tid,solution.task_decisions[tid].mode.value)
        for tid,excess in deadline_excess.items() if excess>1e-8
    ]
    violators.sort(reverse=True)
    classes=Counter(v[2] for v in violators)
    total_route=sum(info.route_distance_m.values())
    return {
        "passed":p.feasible,
        "reasons":list(p.reasons),
        "positive_task_excess_s":total-gap_cycle-gap_avg,
        "total_optimistic_excess_s":total,
        "n_reasons":len(p.reasons),
        "task_offenders":[
            {"task_id":tid,"mode":mode,"excess_s":v}
            for v,tid,mode in violators
        ],
        "offenders_by_execution_mode":dict(classes),
        "max_task_excess_s":violators[0][0] if violators else 0.,
        "flight_distance_m":total_route,
    }


def candidate_moves(instance, solution, *, families, limit_offenders=3):
    """Enumerate structurally legal moves directed at *certified* offenders."""
    score=precheck_score(instance,solution)
    offenders=[
        x["task_id"] for x in score["task_offenders"][:limit_offenders]
    ]
    state=UavMecState(instance,deepcopy(solution),ProxyObjectiveEvaluator())
    out=[]
    if "reorder" in families:
        for tid in offenders:
            owner=next(
                u for u,route in solution.routes.items() if tid in route.task_ids()
            )
            route=solution.routes[owner]
            pos=next(
                i for i,s in enumerate(route.stops)
                if s.kind is StopType.TASK and s.ref_id==tid
            )
            if pos<=1:
                continue
            # Earlier task collection is the direct response to an optimistic
            # completion-LB deadline certificate. Space/route validity checked.
            allowed=sorted(set(
                [1,2,3,max(1,pos//2),max(1,pos-1)]
            ))
            for insert in allowed:
                if insert>=pos:
                    continue
                c=deepcopy(solution)
                stops=list(c.routes[owner].stops)
                moved=stops.pop(pos)
                stops.insert(insert,moved)
                c.routes[owner]=Route(owner,tuple(stops))
                try:
                    validate_solution(instance,c)
                except (ValueError,KeyError):
                    continue
                out.append((f"early_task::{tid}::{owner}:{pos}->{insert}",c))
    if "contact_mode" in families:
        target_visits=set()
        for tid in offenders:
            decision=solution.task_decisions[tid]
            if decision.mode is ExecutionMode.OFFLOAD:
                target_visits.add(decision.contact_visit_id)
            for replacement in _mode_candidates(state,tid):
                c=_apply_task_decision(state,tid,replacement)
                if c is not None:
                    out.append((
                        f"task_mode::{tid}::{replacement.mode.value}:{replacement.contact_visit_id}",
                        c,
                    ))
        for visit_id in sorted(x for x in target_visits if x is not None):
            try:
                out.extend(_relocate_contact_candidates(
                    state,visit_id,positions_limit=4,
                ))
            except (ValueError,KeyError):
                continue
    unique={}
    own=solution_signature(solution)
    for label,c in out:
        sig=solution_signature(c)
        if sig==own or sig in unique:
            continue
        unique[sig]=(label,c)
    return list(unique.values())


def select_candidates(instance, original, arm, *, beam_width=2,
                      max_depth=2, per_arm_eval_limit=3):
    if arm=="guided_reorder":
        families=("reorder",)
    elif arm=="guided_contact_mode":
        families=("contact_mode",)
    elif arm=="guided_joint":
        families=("reorder","contact_mode")
    else:
        raise ValueError(arm)
    start=perf_counter()
    initial_score=precheck_score(instance,original)
    start_key=solution_signature(original)
    seen={start_key}
    beam=[("start",deepcopy(original),initial_score)]
    feasible=[]
    generated=0
    depth_records=[]
    best_optimistic=None
    best_any_gap=initial_score["total_optimistic_excess_s"]

    for depth in range(1,max_depth+1):
        layer=[]
        for _,current,_ in beam:
            for label,c in candidate_moves(
                instance,current,families=families,
            ):
                sig=solution_signature(c)
                if sig in seen:
                    continue
                seen.add(sig)
                generated+=1
                metric=precheck_score(instance,c)
                if metric["total_optimistic_excess_s"]<best_any_gap:
                    best_any_gap=metric["total_optimistic_excess_s"]
                    best_optimistic=label
                # Prefer a necessary precheck pass, then the number and size
                # of violated optimistic constraints, then route length.
                rank=(
                    not metric["passed"],
                    metric["n_reasons"],
                    metric["total_optimistic_excess_s"],
                    metric["flight_distance_m"],
                    label,
                )
                layer.append((rank,label,c,metric))
                if metric["passed"]:
                    feasible.append((rank,label,c,metric,depth))
        layer.sort(key=lambda item:item[0])
        depth_records.append({
            "depth":depth,
            "new_candidates":len(layer),
            "precheck_passing":sum(x[3]["passed"] for x in layer),
            "best_gap_s":layer[0][3]["total_optimistic_excess_s"]
                if layer else None,
        })
        if not layer:
            break
        beam=[(label,c,metric) for _,label,c,metric
              in layer[:beam_width]]
    feasible.sort(key=lambda item:item[0])
    shortlist=feasible[:per_arm_eval_limit]
    return shortlist,{
        "generated_unique":generated,
        "passed_necessary_precheck":len(feasible),
        "generation_s":perf_counter()-start,
        "depth":depth_records,
        "original_gap_s":initial_score["total_optimistic_excess_s"],
        "best_optimistic_gap_s":best_any_gap,
        "best_optimistic_move":best_optimistic,
        "shortlist_labels":[x[1] for x in shortlist],
    }


def strict_recovery(instance, source, arm, *, exact_limit, beam_width, max_depth):
    start=perf_counter()
    if arm=="greedy_mec":
        repaired=build_mec_assisted_initial_solution(
            instance,base_solution=deepcopy(source),
        )
        changed=solution_signature(repaired)!=solution_signature(source)
        score=precheck_score(instance,repaired)
        full=finalize(
            instance,repaired,method="original_MEC_repair",seed=None,
            initialization_s=0.0,search_s=0.0,diagnostics={
                "originalMECRepairSteps":repaired.metadata.get("mec_repair_steps"),
                "originalMECRepairMoves":repaired.metadata.get("mec_repair_moves"),
            },
        )
        both=bool(full["stage1"]["qualified"] and full["stage2"]["qualified"])
        return {
            "arm":arm,"changed":changed,"n_candidates_generated":1,
            "n_precheck_pass":int(score["passed"]),
            "n_stage1_CVX_calls":1,
            "stage1_status":full["resources"].diagnostics.get("stage1_status"),
            "stage1_qualified":bool(full["stage1"]["qualified"]),
            "both_qualified":both,
            "strict_energy_stage1_j": (
                float(full["resources"].energy_stage1_j) if both else None
            ),
            "repaired_solution_sha256":content_hash(repaired),
            "score_after":score,
            "accepted_move":None,
            "runtime_s":perf_counter()-start,
        }
    shortlist,stats=select_candidates(
        instance,source,arm,beam_width=beam_width,
        max_depth=max_depth,per_arm_eval_limit=exact_limit,
    )
    oracle=Stage1CVXObjectiveOracle()
    evaluations=[]
    valid=[]
    for rank,label,c,score,depth in shortlist:
        result=oracle.solve(instance,c)
        exact=stage1_is_qualified(result)
        evaluations.append({
            "move":label,"depth":depth,
            "stage1_solver_status":result.diagnostics.get("stage1_status"),
            "stage1_qualified":exact,
            "energy_stage1_j":float(result.energy_stage1_j) if exact else None,
        })
        if exact:
            valid.append((float(result.energy_stage1_j),label,c,score))
    result={
        "arm":arm,"changed":False,
        "n_candidates_generated":stats["generated_unique"],
        "n_precheck_pass":stats["passed_necessary_precheck"],
        "n_stage1_CVX_calls":oracle.calls,
        "stage1_evaluations":evaluations,
        "search_trace":stats,
        "stage1_qualified":bool(valid),
        "both_qualified":False,
        "strict_energy_stage1_j":None,
        "accepted_move":None,
        "runtime_s":None,
    }
    if valid:
        energy,label,c,score=min(valid,key=lambda x:x[0])
        # Independent final Stage-1 *recompute* plus Stage-2 verification.
        full=finalize(
            instance,c,method=arm,seed=None,
            initialization_s=0.,search_s=0.,
            diagnostics={"accepted_move":label,"search_trace":stats},
        )
        result.update({
            "changed":True,
            "final_stage1_status":full["resources"].diagnostics.get("stage1_status"),
            "stage1_qualified":bool(full["stage1"]["qualified"]),
            "both_qualified":bool(
                full["stage1"]["qualified"] and full["stage2"]["qualified"]
            ),
            "strict_energy_stage1_j": (
                float(full["resources"].energy_stage1_j)
                if full["stage1"]["qualified"] and full["stage2"]["qualified"]
                else None
            ),
            "repaired_solution_sha256":content_hash(c),
            "score_after":score,
            "accepted_move":label,
        })
    result["runtime_s"]=perf_counter()-start
    return result


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    source=json.loads(args.input.read_text(encoding="utf-8"))
    p=source["protocol"]
    if not source.get("complete") or p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Expected completed original sensitivity block")
    K,S=p["task_scale"],p["independent_scenario_seed"]
    if K!=80:
        raise ValueError("High-load feasibility rescue probe currently scoped to K80")
    payload={
        "complete":False,
        "protocol":{
            "id":"precheck_certificate_feasibility_rescue_probe_v1",
            "source_run_id":38043248604,
            "source_frozen_algorithm_sha":"0bdf3a26d4c042e13f96f84977261ffdd33cfc89",
            "tasks":K,"scenario":S,
            "profiles":list(STRESS_PROFILES),
            "method":"only archived failed B-ALNS structures (avoid pseudo-pairs)",
            "arms":list(ARMS),
            "max_depth":args.depth,"beam_width":args.beam_width,
            "exact_stage1_candidates_per_guided_arm":args.exact_limit,
            "meaning":"diagnose one/two-move feasibility recovery, NOT fair-time optimizer ranking",
            "provenance":provenance(),
            "source_hashes":current_source_hashes(Path(__file__)),
        },
        "rows":[],
    }
    write_json(args.output,payload)
    rows={
        (r["profile"],r["seed"],r["method"]):r
        for r in source["rows"]
    }
    errors=[]
    for profile in STRESS_PROFILES:
        instance=restore_instance(source["profiles"][profile]["instance"])
        for seed in p["algorithm_seeds"]:
            original=rows[(profile,seed,"B-ALNS")]
            diag=original.get("resources",{}).get("diagnostics",{})
            stage1=diag.get("stage1_status","exception")
            row={
                "tasks":K,"scenario":S,"seed":seed,"profile":profile,
                "source_stage1_status":stage1,
                "original_both_qualified":original.get("both_qualified",False),
                "source_solution_sha256":original.get("solution_sha256"),
                "source_precheck_reasons":diag.get("precheck_reasons",[]),
                "repair_eligible":stage1=="infeasible_precheck",
                "arms":{},
            }
            if row["repair_eligible"]:
                sol=restore_solution(original["solution"])
                row["original_score"]=precheck_score(instance,sol)
                try:
                    for arm in ARMS:
                        try:
                            row["arms"][arm]=strict_recovery(
                                instance,sol,arm,
                                exact_limit=args.exact_limit,
                                beam_width=args.beam_width,max_depth=args.depth,
                            )
                            found=row["arms"][arm]
                            print(
                                f"RESCUE K{K} S{S} A{seed} {profile} {arm}: "
                                f"candidate_pass={found['n_precheck_pass']} "
                                f"strict_both={found['both_qualified']} "
                                f"CVX={found['n_stage1_CVX_calls']} "
                                f"runtime={found['runtime_s']:.2f}s",
                                flush=True,
                            )
                        except Exception as exc:
                            row["arms"][arm]={
                                "error_type":type(exc).__name__,
                                "message":str(exc),
                                "both_qualified":False,
                            }
                            errors.append({
                                "profile":profile,"seed":seed,"arm":arm,
                                "error":str(exc),
                            })
                except Exception as exc:
                    errors.append({
                        "profile":profile,"seed":seed,"arm":"row",
                        "error":str(exc),
                    })
            payload["rows"].append(row)
            write_json(args.output,payload)
    payload["complete"]=True
    payload["errors"]=errors
    write_json(args.output,payload)
    total=sum(r["repair_eligible"] for r in payload["rows"])
    by_arm={
        arm:{
            "attempts":total,
            "recovered_both":sum(
                bool(r["arms"].get(arm,{}).get("both_qualified"))
                for r in payload["rows"]
            ),
            "precheck_pass_in_arm":sum(
                int(r["arms"].get(arm,{}).get("n_precheck_pass",0)>0)
                for r in payload["rows"]
            ),
        }
        for arm in ARMS
    }
    print(
        "RESCUE_SUMMARY="+json.dumps({
            "tasks":K,"scenario":S,"eligible":total,
            "skipped":len(payload["rows"])-total,
            "methods":by_arm,
            "errors":len(errors),
        },ensure_ascii=False),flush=True,
    )
    if errors:
        raise RuntimeError(f"Repair algorithm errors; see preserved results: {errors[:3]}")
    return payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--beam-width",type=int,default=2)
    p.add_argument("--depth",type=int,default=2)
    p.add_argument("--exact-limit",type=int,default=3)
    args=p.parse_args()
    if min(args.beam_width,args.depth,args.exact_limit)<1:
        raise ValueError("Budgets must be positive")
    run(args)


if __name__=="__main__":
    main()
