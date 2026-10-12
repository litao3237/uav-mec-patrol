"""P6b causal-granularity test: station -> whole contact batch -> new MEC.

P6's task-level certificate-targeted move selection failed, while a
heavy-task control happened to select a successful whole-batch MEC
reassignment in one already-inspected S93 case. This experiment tests
the HYPOTHESIS that a joint station-level infeasibility witness should
target entire CONTACT VISITS, rather than particular binding tasks.

All policies share the exact same operator:
    reassign ONE pre-existing contact visit to a physical point at a
    DIFFERENT MEC, which moves ALL offloaded tasks in that batch.
The operation is fully structurally validated and is NOT accepted
until unchanged original Stage1/Stage2 residual qualification.

The policies differ ONLY in which visits of the same violating MEC
to examine, not what move family is available. Their different
candidate counts and actual wall time are reported explicitly.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from copy import deepcopy

from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.domain import ContactVisit,StopType
from uav_mec.evaluation import build_event_info,visit_mec_id
from uav_mec.evaluation.geometry import distance,stop_xy
from uav_mec.evaluation.validator import validate_solution


POLICIES=(
    "station_all_contacts",
    "joint_binding_pairs_2",
    "heaviest_batches_2",
    "lexical_contacts_2",
)


def _candidate_visits(instance,source,joint,policy):
    if policy not in POLICIES:raise ValueError(policy)
    info=build_event_info(instance,source)
    bad=[
        (m,row) for m,row in joint["stations"].items()
        if row["joint_necessary_violation"] and row["active_pairs"]
    ]
    if not bad:
        return [],{"violating_stations":[],"reason":"no_joint_violation"}
    # Only the MOST overloaded station: test whether its assignment can be
    # repaired without pushing the conflict to another MEC.
    bad.sort(key=lambda x:(
        -(x[1]["oversubscription_cpu_ghz"]
          if x[1]["oversubscription_cpu_ghz"] is not None
          else float("inf")),
        x[0],
    ))
    mid,station=bad[0]
    visits=[v for uid,vs in info.contact_order.items()
            for v in vs if visit_mec_id(instance,source,v)==mid]
    if not visits:
        return [],{"violating_stations":[mid],"reason":"no_visits"}
    weighted_batch={
        v:sum(instance.tasks[t].workload_gcycles
              for t in info.batch_edf_order[v]) for v in visits}
    if policy=="station_all_contacts":
        chosen=sorted(visits,key=lambda v:(-weighted_batch[v],v))
    elif policy=="heaviest_batches_2":
        chosen=sorted(visits,key=lambda v:(-weighted_batch[v],v))[:2]
    elif policy=="lexical_contacts_2":
        chosen=sorted(visits)[:2]
    else:
        allocation=station["best_optimistic_bin_allocation"]
        by_pair=defaultdict(list)
        for v in visits:
            uid=source.contact_visits[v].uav_id
            by_pair[f"{uid}::{mid}"].append(v)
        rowpairs=sorted(allocation.items(),key=lambda item:(
            -(item[1]["needed_static_cpu_ghz_lb"] or float("inf")),
            item[0]))
        selected=[]
        for pair,model in rowpairs:
            cause=(model.get("limiting_deadline_task") or {})
            tid=cause.get("task_id")
            options=by_pair[pair]
            first=next((v for v in options if tid in info.batch_tasks[v]),None)
            if first is None and options:
                first=max(options,key=lambda v:(weighted_batch[v],v))
            if first is not None and first not in selected:
                selected.append(first)
            if len(selected)>=2:break
        if len(selected)<2:
            for v in sorted(visits,key=lambda v:(-weighted_batch[v],v)):
                if v not in selected:selected.append(v)
                if len(selected)>=2:break
        chosen=selected[:2]
    return chosen,{
        "target_station":mid,
        "violation_CPU_ghz":station["oversubscription_cpu_ghz"],
        "physical_CPU_ghz":station["physical_cpu_ghz"],
        "visits":visits,
        "selected_visits":chosen,
        "batch_work_gcycles":weighted_batch,
        "policy":policy,
    }


def station_batch_moves(instance,source,joint,*,policy,
                        alternative_points_per_visit=2,
                        max_selected_visits=12):
    if alternative_points_per_visit<1 or max_selected_visits<1:
        raise ValueError("Positive structural candidate limits")
    info=build_event_info(instance,source)
    candidates,context=_candidate_visits(
        instance,source,joint,policy)
    candidates=candidates[:max_selected_visits]
    seen={solution_signature(source)}
    raw=[]
    structural_rejected=Counter()
    for visit in candidates:
        cv=source.contact_visits[visit]
        old_mid=visit_mec_id(instance,source,visit)
        route=source.routes[cv.uav_id]
        stop_id=next(i for i,s in enumerate(route.stops)
                     if s.kind is StopType.CONTACT and s.ref_id==visit)
        prev=stop_xy(instance,source,route.stops[stop_id-1])
        nex=stop_xy(instance,source,route.stops[stop_id+1])
        alternate=[
            (
                distance(prev,(pt.x,pt.y))+
                distance((pt.x,pt.y),nex)-
                distance(prev,nex),
                point_id,
            )
            for point_id,pt in instance.contact_points.items()
            if pt.mec_id!=old_mid
        ]
        alt_mecs=set()
        chosen_points=[]
        for detour,point_id in sorted(alternate):
            target=instance.contact_points[point_id].mec_id
            if target in alt_mecs and len(chosen_points)>=alternative_points_per_visit:
                break
            chosen_points.append((detour,point_id))
            alt_mecs.add(target)
            if len(chosen_points)>=alternative_points_per_visit:break
        for detour,point_id in chosen_points:
            changed=deepcopy(source)
            changed.contact_visits[visit]=ContactVisit(
                visit_id=visit,uav_id=cv.uav_id,point_id=point_id)
            try:
                validate_solution(instance,changed)
            except (ValueError,KeyError) as exc:
                structural_rejected[type(exc).__name__]+=1
                continue
            signature=solution_signature(changed)
            if signature in seen:continue
            seen.add(signature)
            raw.append((
                f"p6b_move_batch::{visit}->{point_id}",
                changed,
                {"source_visit":visit,"source_station":old_mid,
                 "destination_station":instance.contact_points[point_id].mec_id,
                 "batch_tasks":list(info.batch_tasks[visit]),
                 "batch_work_gcycles":context["batch_work_gcycles"][visit],
                 "extra_detour_m":float(detour)},
            ))
    return raw,{
        **context,
        "selected_visits":candidates,
        "structurally_valid_moves":len(raw),
        "structural_rejected":dict(structural_rejected),
    }
