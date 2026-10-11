"""Diagnostic-only, elastic-QoS-directed UAV-MEC feasibility repair.

Two ablations isolate *diagnostic information* from *candidate search power*:
  - elastic_rank_same_moves: EXACT same queue dependency joint candidate
    generator as the frozen queue-only control, different deterministic score
    weighted toward elastic high-slack deadlines and predecessor dependencies.
  - elastic_targeted_joint: same queue candidate generator PLUS legitimate
    route/contact/offloading adjustments centered on top elastic deadlines
    and their FIFO/EDF blocking predecessors. Both use the same beam width,
    depth and at-most-three strict Stage-1 CVX candidate calls.

Elastic diagnosis is solved ONCE from the failed source D and its full time
is included in the treatment runtime. It is NOT used to label a modified D
as feasible, and is not recomputed on new D. All repairs must pass unchanged
original Stage-1/Stage-2 + two independent full-residual checks.

Only the original paper's frozen MEC resource, FIFO/EDF and UAV model apply.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from time import perf_counter

from _queue_repair_reference import (
    queue_gap, new_move_candidates, old_repair,
    strict_queue_repair,
)
from _legacy_rescue_reference import strict_recovery
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import ProxyObjectiveEvaluator, solution_signature
from uav_mec.algorithms.alns.operators import (
    _destroy_tasks, _options_for_task, _apply_local_insertion,
)
from uav_mec.algorithms.alns.problem_operators import (
    _apply_task_decision, _mode_candidates, _relocate_contact_candidates,
)
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations, _existing_contacts_after_task,
    _insert_contact_candidate, _reuse_contact_candidate,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.domain import ExecutionMode, Route, RouteStop, StopType
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution

from run_seven_methods import finalize


ARM_NAMES = (
    "greedy_mec",
    "old_lb_joint",
    "queue_joint",
    "elastic_rank_same_moves",
    "elastic_targeted_joint",
)


def elastic_conflict_targets(instance, solution, elastic, *, task_limit=3,
                             predecessor_limit=3):
    """A frozen source-D list of tasks and blocking predecessors.

    Deadline elastic primal slacks are not causal gradients. Dependencies
    are merely candidates to be evaluated under real fixed-resource CVX.
    """
    credible=bool(elastic and elastic.get("numerically_credible"))
    if not credible:
        return {
            "credible":False,"positive_source_slack":False,
            "source_slack":None,"targets":[],
            "predecessors":[],
            "task_weights":{},
            "basis":"no_credible_elastic",
        }
    pos=float(elastic["normalized_total_elastic_slack"])
    tasks=[]
    raw_weights={}
    for entry in elastic.get("top_constraints",[]):
        if entry["family"]!="deadline" or entry["normalized_slack"]<=1e-5:
            continue
        tid=entry["constraint"].split("::")[-1]
        if tid not in instance.tasks:
            continue
        if tid not in tasks:
            tasks.append(tid)
        raw_weights[tid]=float(entry["normalized_slack"])
        if len(tasks)>=task_limit:
            break
    predecessors=[]
    dependency_lookup={
        x["task_id"]:x.get("dependency_context",{})
        for x in elastic.get("top_dependency_context",[])
    }
    for task in tasks:
        context=dependency_lookup.get(task,{})
        prior=context.get("predecessors",context.get("within_batch_predecessors",[]))
        prevbatch=context.get("previous_batch_same_pair")
        if prevbatch is not None and prevbatch in solution.contact_visits:
            prior=list(prior)+[
                t for t,d in solution.task_decisions.items()
                if d.contact_visit_id==prevbatch
            ]
        prior=sorted(
            set(t for t in prior if t in instance.tasks and t!=task),
            key=lambda t:(-instance.tasks[t].workload_gcycles,t),
        )
        for t in prior[:predecessor_limit]:
            if t not in predecessors and t not in tasks:
                predecessors.append(t)
            raw_weights[t]=max(raw_weights.get(t,0.0),.35*raw_weights[task])
    return {
        "credible":True,
        "positive_source_slack":pos>.002,
        "source_slack":pos,
        "targets":tasks,
        "predecessors":predecessors,
        "task_weights":raw_weights,
        "basis":"positive_deadline_elastic_and_model_dependencies"
                if tasks else "no_positive_deadline_slack",
    }


def elastic_focus_moves(instance, original, focus, *, max_tasks=7):
    """Generate lawful local/MEC/offload/route actions from *source* conflicts."""
    priority=(focus["targets"]+focus["predecessors"])[:max_tasks]
    if not priority:
        return []
    state=UavMecState(instance,deepcopy(original),ProxyObjectiveEvaluator())
    info=build_event_info(instance,original)
    result=[]
    seen={solution_signature(original)}

    def add(label, candidate):
        try:
            validate_solution(instance,candidate)
        except (ValueError,KeyError):
            return
        sig=solution_signature(candidate)
        if sig in seen:return
        seen.add(sig)
        result.append((label,candidate))

    for task_id in priority:
        owner=info.task_owner[task_id]
        route=original.routes[owner]
        pos=next(i for i,s in enumerate(route.stops)
                 if s.kind is StopType.TASK and s.ref_id==task_id)

        # Early collection can shorten the critical successor chain.
        insert_points=sorted(set(
            (1,2,3,max(1,pos//2),max(1,pos-1))
        ))
        for insert in insert_points:
            if insert>=pos:continue
            c=deepcopy(original)
            stops=list(c.routes[owner].stops)
            move=stops.pop(pos)
            stops.insert(insert,move)
            c.routes[owner]=Route(owner,tuple(stops))
            add(f"elastic_early::{task_id}::{pos}->{insert}",c)

        # Reassign resource modes at old legally reachable MEC contacts.
        for new_decision in _mode_candidates(state,task_id):
            c=_apply_task_decision(state,task_id,new_decision)
            if c is not None:
                add(
                    f"elastic_mode::{task_id}:{new_decision.mode.value}:"
                    f"{new_decision.contact_visit_id}",c,
                )
        decision=original.task_decisions[task_id]
        if decision.mode is ExecutionMode.OFFLOAD:
            for label,c in _relocate_contact_candidates(
                state,decision.contact_visit_id,positions_limit=4,
            ):
                add(f"elastic_{label}",c)
        else:
            # An *upstream* local FIFO task can be offloaded even when that
            # task itself satisfies its own deadline. This is the new move.
            for visit_id in list(_existing_contacts_after_task(
                original,task_id,
            ))[:3]:
                try:
                    c=_reuse_contact_candidate(
                        instance,original,task_id=task_id,
                        visit_id=visit_id,
                    )
                    add(f"elastic_fifo_reuse::{task_id}->{visit_id}",c)
                except (ValueError,KeyError):
                    pass
            if len(route.contact_visit_ids()) < instance.max_contacts_per_uav:
                for _,point,insert in _best_new_contact_locations(
                    instance,original,task_id,limit=4,per_mec=1,
                )[:2]:
                    try:
                        c=_insert_contact_candidate(
                            instance,original,task_id=task_id,
                            point_id=point,insert_pos=insert,
                        )
                        add(
                            f"elastic_fifo_new_contact::{task_id}::{point}@{insert}",
                            c,
                        )
                    except (ValueError,KeyError):
                        pass

        # Cross UAV reassignment redistributes FIFO task loads and potential
        # MEC queue pressure. Select at most one good insert per recipient.
        destroyed=_destroy_tasks(state,[task_id])
        chosen_uavs=set()
        for opt in _options_for_task(destroyed,task_id):
            if opt.uav_id==owner or opt.uav_id in chosen_uavs:
                continue
            chosen_uavs.add(opt.uav_id)
            cstate=destroyed.copy()
            _apply_local_insertion(cstate,task_id,opt)
            add(
                f"elastic_cross_uav::{task_id}->{opt.uav_id}@{opt.position}",
                cstate.solution,
            )
    return result


def _frozen_priority_excess(instance, candidate, focus, *, queue_result):
    values=focus["task_weights"]
    if not values:
        return queue_result["total_optimistic_excess_s"]
    info=build_event_info(instance,candidate)
    from uav_mec.optimization.resource.queue_aware_precheck import (
        queue_aware_feasibility_precheck,
    )
    q=queue_aware_feasibility_precheck(instance,candidate,info)
    scale=sum(values.values())
    return sum(
        weight*max(0.0, q.task_completion_lb_s[tid]
                   -instance.tasks[tid].release_s
                   -instance.tasks[tid].deadline_s)
        for tid,weight in values.items()
    )/max(scale,1e-12)


def search_elastic(instance, source, *, elastic,
                   arm="elastic_targeted_joint",
                   beam_width=2,depth=2,exact_limit=3):
    if arm not in ("elastic_rank_same_moves","elastic_targeted_joint"):
        raise ValueError(arm)
    started=perf_counter()
    focus=elastic_conflict_targets(instance,source,elastic)
    old=queue_gap(instance,source)
    seen={solution_signature(source)}
    beam=[("start",deepcopy(source))]
    passing=[]
    generated=0
    history=[]
    for turn in range(1,depth+1):
        layer=[]
        for _,current in beam:
            # The SAME queue dependency pool exists for both variants.
            moves=list(new_move_candidates(
                instance,current,mode="queue_dependency_joint",offenders=3,
            ))
            if arm=="elastic_targeted_joint":
                moves+=elastic_focus_moves(instance,current,focus)
            for label,candidate in moves:
                sig=solution_signature(candidate)
                if sig in seen:continue
                seen.add(sig)
                generated+=1
                q=queue_gap(instance,candidate)
                focus_gap=_frozen_priority_excess(
                    instance,candidate,focus,queue_result=q,
                )
                # Always require optimistic queue pass for strict solver
                # selection. Within pass/fail classes, prioritize constraints
                # whose source elastic diagnosis reported the largest slack.
                key=(
                    not q["passed"],
                    q["n_reasons"],
                    focus_gap,
                    q["total_optimistic_excess_s"],
                    q["flight_distance_m"],
                    label,
                )
                layer.append((key,label,candidate,q,turn))
                if q["passed"]:
                    passing.append((key,label,candidate,q,turn))
        layer.sort(key=lambda x:x[0])
        history.append({
            "depth":turn,
            "evaluated_queue_candidates":len(layer),
            "queue_passed":sum(x[3]["passed"] for x in layer),
            "top_ranked_labels":[x[1] for x in layer[:3]],
            "best_queue_gap_s":(
                layer[0][3]["total_optimistic_excess_s"] if layer else None
            ),
        })
        if not layer:break
        beam=[(label,c) for _,label,c,_,_ in layer[:beam_width]]
    passing.sort(key=lambda x:x[0])
    return passing[:exact_limit],{
        "elastic_focus":focus,
        "original_queue_gap_s":old["total_optimistic_excess_s"],
        "generated_unique":generated,
        "queue_precheck_passing":len(passing),
        "queued_beam_search_s":perf_counter()-started,
        "history":history,
        "strict_shortlist_labels":[x[1] for x in passing[:exact_limit]],
    }


def run_elastic_arm(instance, source, *, diag, arm,
                    beam_width=2,depth=2,exact_limit=3,
                    diagnostic_runtime_s=0.0):
    start=perf_counter()
    shortlist,stats=search_elastic(
        instance,source,elastic=diag,arm=arm,
        beam_width=beam_width,depth=depth,exact_limit=exact_limit,
    )
    oracle=Stage1CVXObjectiveOracle()
    good=[]
    solves=[]
    for _,label,candidate,q,turn in shortlist:
        r=oracle.solve(instance,candidate)
        valid=stage1_is_qualified(r)
        solves.append({
            "label":label,"depth":turn,
            "stage1_status":r.diagnostics.get("stage1_status"),
            "qualified":valid,
            "energy_j":float(r.energy_stage1_j) if valid else None,
        })
        if valid:good.append((float(r.energy_stage1_j),label,candidate))
    accepted=None
    final_both=False
    final_energy=None
    final_status=None
    if good:
        energy,label,candidate=min(good,key=lambda x:x[0])
        result=finalize(
            instance,candidate,method=arm,seed=None,
            initialization_s=0.0,search_s=0.0,
            diagnostics={"source_elastic":diag,"chosen_label":label},
        )
        final_status=result["resources"].diagnostics.get("stage1_status")
        final_both=bool(
            result["stage1"]["qualified"] and result["stage2"]["qualified"]
        )
        if final_both:
            final_energy=float(result["resources"].energy_stage1_j)
            accepted=label
    return {
        "arm":arm,"strict_both_recovered":final_both,
        "strict_energy_j":final_energy,
        "stage1_candidate_qualified":len(good),
        "strict_cvx_calls":oracle.calls,
        "precheck_passed_candidates":stats["queue_precheck_passing"],
        "generated_unique":stats["generated_unique"],
        "accepted_label":accepted,"stage1_final_status":final_status,
        "source_elastic_credible":stats["elastic_focus"]["credible"],
        "source_elastic_positive":stats["elastic_focus"]["positive_source_slack"],
        "focus_tasks":stats["elastic_focus"]["targets"],
        "focus_predecessors":stats["elastic_focus"]["predecessors"],
        "trace":stats["history"],
        "candidate_results":solves,
        "search_and_solver_s":perf_counter()-start,
        "charged_diagnostic_s":diagnostic_runtime_s,
        "total_s_including_diagnostic":perf_counter()-start+diagnostic_runtime_s,
    }


def old_queue_arm(instance,solution,arm,*,beam_width,depth,exact_limit):
    if arm=="greedy_mec":
        r=old_repair(
            instance,solution,arm="greedy_mec",beam_width=beam_width,
            max_depth=depth,exact_limit=exact_limit,
        )
    elif arm=="old_lb_joint":
        r=old_repair(
            instance,solution,arm="guided_joint",beam_width=beam_width,
            max_depth=depth,exact_limit=exact_limit,
        )
    elif arm=="queue_joint":
        r=strict_queue_repair(
            instance,solution,mode="queue_dependency_joint",
            beam_width=beam_width,max_depth=depth,exact_limit=exact_limit,
        )
    else:
        raise ValueError(arm)
    return {
        "arm":arm,
        "strict_both_recovered":bool(r.get("strict_both_recovered",
                                       r.get("both_qualified",False))),
        "strict_energy_j":r.get(
            "recovery_energy_j",r.get("strict_energy_stage1_j"),
        ),
        "strict_cvx_calls":r.get(
            "strict_cvx_calls",r.get("n_stage1_CVX_calls"),
        ),
        "precheck_passed_candidates":r.get(
            "queue_precheck_passing",r.get("n_precheck_pass"),
        ),
        "generated_unique":r.get(
            "generated_unique",r.get("n_candidates_generated"),
        ),
        "accepted_label":r.get("accepted_move"),
        "search_and_solver_s":r["runtime_s"],
        "charged_diagnostic_s":0.0,
        "total_s_including_diagnostic":r["runtime_s"],
    }
