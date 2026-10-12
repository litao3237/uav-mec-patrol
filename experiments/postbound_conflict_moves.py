"""P6 structural post-bound repair: change ONE critical MEC contact or task.

Unlike P3 (which targeted the SOURCE D before the FIFO/EDF deadline
certificate was repaired), P6 first uses the original ALNS atomic beam
to produce *queue-necessary-passing* intermediate structures, and ONLY
THEN selects an overloaded MEC for coupled bandwidth-CPU repair.

This is a diagnostic hypothesis. P5's necessary bound is not used to
declare ANY candidate fully feasible; complete original Stage1/Stage2
is still the final arbiter. This file is not production ALNS.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import (
    ProxyObjectiveEvaluator,solution_signature,
)
from uav_mec.algorithms.alns.operators import (
    _cleanup_orphan_contacts,_destroy_tasks,
    _options_for_task,_apply_local_insertion,
)
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations,_existing_contacts_after_task,
    _insert_contact_candidate,
)
from uav_mec.domain import (
    ContactVisit,ExecutionMode,Route,RouteStop,StopType,TaskDecision,
)
from uav_mec.evaluation import build_event_info,visit_mec_id
from uav_mec.evaluation.geometry import distance,stop_xy
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)


def _station_targets(instance,source,bound,*,policy,limit=2):
    if policy not in ("certificate","workload"):
        raise ValueError("Unknown P6 target-selection control")
    if limit<=0:raise ValueError("Positive target limit required")
    info=build_event_info(instance,source)
    failing=[
        (mid,station) for mid,station in bound["stations"].items()
        if station["joint_necessary_violation"]
    ]
    if not failing:
        return [],{"policy":policy,"reason":"no_joint_resource_violation"}
    failing.sort(key=lambda x:(
        -(x[1]["oversubscription_cpu_ghz"] or float("inf")),
        x[0],
    ))
    mid,station=failing[0]
    all_tasks=[]
    for visit,tasks in info.batch_tasks.items():
        if visit_mec_id(instance,source,visit)==mid:
            all_tasks.extend(tasks)
    if not all_tasks:
        return [],{"policy":policy,"reason":"no_offloaded_tasks_in_failing_station"}
    selected=[]
    if policy=="certificate":
        allocation=station["best_optimistic_bin_allocation"]
        pairs=sorted(
            allocation.items(),
            key=lambda kv:(
                -(kv[1].get("needed_static_cpu_ghz_lb") or float("inf")),
                kv[0],
            ),
        )
        for pair,row in pairs:
            binding=row.get("limiting_deadline_task") or {}
            task=binding.get("task_id")
            if task in all_tasks and task not in selected:
                selected.append(task)
            # First try the task actually responsible for a binding
            # deadline, then its EDF/FIFO compulsory predecessors.
            if task in all_tasks:
                uid=pair.split("::")[0]
                order=[]
                for visit in info.contact_order[uid]:
                    if visit_mec_id(instance,source,visit)==mid:
                        order.extend(info.batch_edf_order[visit])
                if task in order:
                    for t in sorted(
                        order[:order.index(task)],
                        key=lambda x:(-instance.tasks[x].workload_gcycles,x)):
                        if t not in selected:selected.append(t)
            if len(selected)>=limit:break
    if policy=="workload":
        selected=sorted(
            all_tasks,key=lambda t:(-instance.tasks[t].workload_gcycles,t))
    # Always return SAME number of target tasks for paired controls, or
    # fewer if the station genuinely has fewer uploaded tasks.
    if len(selected)<limit:
        for t in sorted(all_tasks,
                        key=lambda x:(-instance.tasks[x].workload_gcycles,x)):
            if t not in selected:selected.append(t)
            if len(selected)>=limit:break
    selected=selected[:limit]
    return selected,{
        "policy":policy,"station":mid,
        "required_station_cpu_ghz":station["optimistic_min_total_cpu_ghz"],
        "station_cpu_ghz":station["physical_cpu_ghz"],
        "bound_oversubscription_cpu_ghz":station["oversubscription_cpu_ghz"],
        "selected_targets":selected,
    }


def postbound_conflict_moves(
    instance,source,*,policy="certificate",
    target_limit=2,point_variants=2,
    joint_bound=None,
):
    """Identical move families for model-critical and workload-only targets.

    Each legal candidate is a *single structural intervention*:
    task->LOCAL, existing contact alternate MEC, new alternate-MEC
    contact (possibly after releasing an orphan), full batch contact
    point relocation to other MEC, cross-UAV LOCAL move, or
    cross-UAV offload to an already-existing alternate-MEC contact.

    All move labels are informational only, not a feasibility ranking.
    """
    if policy not in ("certificate","workload"):
        raise ValueError(policy)
    if min(target_limit,point_variants)<=0:
        raise ValueError("Positive candidate limits required")
    source_hash=solution_signature(source)
    info=build_event_info(instance,source)
    bound=joint_bound or joint_station_bw_cpu_necessary_bound(
        instance,source,n_bins=48)
    targets,why=_station_targets(
        instance,source,bound,policy=policy,limit=target_limit)
    result=[];seen={source_hash};invalid=Counter()
    origin=UavMecState(
        instance,deepcopy(source),ProxyObjectiveEvaluator(),
    )

    def emit(label,candidate):
        try:
            _cleanup_orphan_contacts(candidate)
            validate_solution(instance,candidate)
        except (ValueError,KeyError) as exc:
            invalid[type(exc).__name__]+=1
            return
        signature=solution_signature(candidate)
        if signature in seen:return
        seen.add(signature)
        result.append((label,candidate))

    for tid in targets:
        d=source.task_decisions[tid]
        if d.mode is not ExecutionMode.OFFLOAD:
            continue
        visit=d.contact_visit_id
        uid=info.task_owner[tid]
        station=visit_mec_id(instance,source,visit)

        # 1. Move one task to local UAV FIFO, but do NOT claim this must
        # remove the original task deadline's queuing delay.
        cand=deepcopy(source)
        cand.task_decisions[tid]=TaskDecision.local()
        emit(f"p6_to_local::{tid}",cand)

        # 2. Use an existing contact from this same UAV to OTHER MEC.
        for alternative in _existing_contacts_after_task(source,tid):
            if visit_mec_id(instance,source,alternative)!=station:
                cand=deepcopy(source)
                cand.task_decisions[tid]=TaskDecision.offload(alternative)
                emit(f"p6_alt_existing::{tid}->{alternative}",cand)
                break

        # 3. Create one earliest legal alternate MEC contact.
        # First remove the previous contact IF this task was its last
        # uploader, so a full Hmax route can legitimately regain a slot.
        base=deepcopy(source)
        base.task_decisions[tid]=TaskDecision.local()
        _cleanup_orphan_contacts(base)
        if len(base.routes[uid].contact_visit_ids()) < instance.max_contacts_per_uav:
            choices=_best_new_contact_locations(
                instance,base,tid,
                limit=max(8,len(instance.contact_points)),
                per_mec=max(1,point_variants),
            )
            placed=0
            for _,point,position in choices:
                if instance.contact_points[point].mec_id==station:continue
                try:
                    newer=_insert_contact_candidate(
                        instance,base,task_id=tid,
                        point_id=point,insert_pos=position,
                    )
                except (ValueError,KeyError):
                    continue
                emit(f"p6_alt_new::{tid}->{point}@{position}",newer)
                placed+=1
                if placed>=point_variants:break

        # 4. Change the destination MEC for the WHOLE contact batch.
        # This is new relative to P3 task-to-LOCAL and models the shared
        # CPU demand of all tasks using the same physical MEC visit.
        route=source.routes[uid]
        idx=next(i for i,s in enumerate(route.stops)
                 if s.kind is StopType.CONTACT and s.ref_id==visit)
        if idx>0 and idx<len(route.stops)-1:
            prev=stop_xy(instance,source,route.stops[idx-1])
            nxt=stop_xy(instance,source,route.stops[idx+1])
            alternate_points=[
                (
                    distance(prev,(pt.x,pt.y))+
                    distance((pt.x,pt.y),nxt)-
                    distance(prev,nxt),
                    point_id,
                ) for point_id,pt in instance.contact_points.items()
                if pt.mec_id!=station
            ]
            for _,point in sorted(alternate_points)[:point_variants]:
                cand=deepcopy(source)
                cand.contact_visits[visit]=ContactVisit(
                    visit_id=visit,uav_id=uid,point_id=point)
                emit(f"p6_whole_batch_mec::{visit}->{point}",cand)

        # 5. Different UAV local schedule; moving the offloaded task
        # may unblock static station CPU but creates a local FIFO task.
        destroyed=_destroy_tasks(origin,[tid])
        found_uav=set()
        for opt in _options_for_task(destroyed,tid):
            if opt.uav_id==uid or opt.uav_id in found_uav:continue
            trial=destroyed.copy()
            _apply_local_insertion(trial,tid,opt)
            emit(f"p6_cross_local::{tid}->{opt.uav_id}@{opt.position}",
                 trial.solution)
            found_uav.add(opt.uav_id)
            if len(found_uav)>=1:break

        # 6. Move the task to a different UAV and its already existing
        # offload contact targeting another MEC. Preserve store-carry order.
        cross=[]
        point=(instance.tasks[tid].x,instance.tasks[tid].y)
        for other_uid,other_route in source.routes.items():
            if other_uid==uid:continue
            for other_v in other_route.contact_visit_ids():
                if visit_mec_id(instance,source,other_v)==station:continue
                ix=next(i for i,s in enumerate(other_route.stops)
                        if s.kind is StopType.CONTACT and s.ref_id==other_v)
                # Insert just before the existing contact, preserving
                # original contacts and all existing offloaded tasks.
                previous=stop_xy(instance,source,other_route.stops[ix-1])
                following=stop_xy(instance,source,other_route.stops[ix])
                added=(
                    distance(previous,point)+distance(point,following)-
                    distance(previous,following))
                cross.append((added,other_uid,other_v,ix))
        for _,other_uid,other_v,position in sorted(cross)[:1]:
            cand=deepcopy(source)
            cand.routes[uid]=Route(
                uid,tuple(s for s in cand.routes[uid].stops
                          if not (s.kind is StopType.TASK and s.ref_id==tid)))
            route2=cand.routes[other_uid]
            steps=list(route2.stops)
            steps.insert(position,RouteStop.task(tid))
            cand.routes[other_uid]=Route(other_uid,tuple(steps))
            cand.task_decisions[tid]=TaskDecision.offload(other_v)
            emit(
                f"p6_cross_offload::{tid}->{other_uid}/{other_v}@{position}",
                cand,
            )

    return result,{
        **why,
        "candidate_count":len(result),
        "families":dict(Counter(
            label.split("::")[0] for label,_ in result)),
        "structurally_invalid":dict(invalid),
        "original_signature_unmodified":solution_signature(source)==source_hash,
    }
