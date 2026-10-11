"""UAV-MEC specific atomic *coupled* feasibility-repair neighborhoods.

A previously isolated bottleneck: K80 with high computation pressure often
needs multiple changes to a LOCAL FIFO chain or one MEC EDF/upload batch.
The original single-task move can temporarily worsen other deadlines. Here,
ONE structurally-valid candidate may change TWO causally related tasks and
the contact they upload to, or reassign the pair between UAV FIFO queues.

This is not an assertion of paper-level novelty: it is an experiment-only
hypothesis. The original ALNS/ESI and resource acceptance stay untouched.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations

from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import (
    ProxyObjectiveEvaluator, solution_signature,
)
from uav_mec.algorithms.alns.operators import (
    _destroy_tasks, _options_for_task, _apply_local_insertion,
    _cleanup_orphan_contacts,
)
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations, _existing_contacts_after_task,
    _insert_contact_candidate, _next_visit_id,
)
from uav_mec.domain import (
    ContactVisit, ExecutionMode, Route, RouteStop, StopType, TaskDecision,
)
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.geometry import distance, stop_xy
from uav_mec.evaluation.validator import validate_solution
from run_queue_guided_repair import queue_gap


def _task_stop_position(solution, uav_id, tid):
    return next(
        i for i,stop in enumerate(solution.routes[uav_id].stops)
        if stop.kind is StopType.TASK and stop.ref_id==tid
    )


def _best_split_locations(instance, source, owner, original_contact,
                          pair, *, per_pair_limit=2):
    route=source.routes[owner]
    old_i=next(
        i for i,stop in enumerate(route.stops)
        if stop.kind is StopType.CONTACT and stop.ref_id==original_contact
    )
    earliest=max(
        _task_stop_position(source,owner,t) for t in pair
    )+1
    # Insert a new MEC visit AFTER both tasks are sampled but BEFORE their
    # existing MEC batch, so the EDF/FIFO upload queue changes atomically.
    # Inserting immediately before the old visit is a valid early
    # upload of this pair (the old visit may remain for other tasks).
    if earliest>old_i:
        return []
    opportunities=[]
    for pos in range(earliest,old_i+1):
        prev=stop_xy(instance,source,route.stops[pos-1])
        nxt=stop_xy(instance,source,route.stops[pos])
        for ptid,point in instance.contact_points.items():
            xy=(point.x,point.y)
            extra=distance(prev,xy)+distance(xy,nxt)-distance(prev,nxt)
            opportunities.append((extra,ptid,pos))
    by_mec={}
    for extra,ptid,pos in sorted(opportunities):
        mec_id=instance.contact_points[ptid].mec_id
        if mec_id not in by_mec:
            by_mec[mec_id]=(extra,ptid,pos)
    return sorted(by_mec.values())[:per_pair_limit]


def atomic_batch_moves(instance, source, *, include_cross_uav=False,
                       offender_limit=3, max_pairs_per_offender=4):
    """Return unique validated candidates; all moves are *atomic*, no CVX.

    Per failing task, identify heavy predecessors in that task's LOCAL FIFO,
    or co-batched tasks in its MEC EDF queue. Construct double-offload,
    double-early-split, and optionally double-UAV-relocation candidates.
    """
    pressure=queue_gap(instance,source)
    info=build_event_info(instance,source)
    state=UavMecState(instance,deepcopy(source),ProxyObjectiveEvaluator())
    candidates=[]
    seen={solution_signature(source)}
    reject_counts={}

    def push(label,candidate):
        try:
            _cleanup_orphan_contacts(candidate)
            validate_solution(instance,candidate)
        except (KeyError,ValueError) as exc:
            reject_counts[type(exc).__name__]=reject_counts.get(
                type(exc).__name__,0
            )+1
            return
        sig=solution_signature(candidate)
        if sig in seen:
            return
        seen.add(sig)
        candidates.append((label,candidate))

    for entry in pressure["task_offenders"][:offender_limit]:
        delayed=entry["task_id"]
        owner=info.task_owner[delayed]
        decision=source.task_decisions[delayed]
        if decision.mode is ExecutionMode.LOCAL:
            seq=info.local_order[owner]
            if delayed not in seq:
                continue
            upstream=list(seq[:seq.index(delayed)])
            heavy=sorted(
                upstream,
                key=lambda t:(-instance.tasks[t].workload_gcycles,t),
            )[:3]
            pairs=list(combinations(heavy,2))
            pairs+=[(t,delayed) for t in heavy]
            # An atomic pair specifically targets the FIFO predecessor
            # dependency, not an arbitrary two-task route neighborhood.
            for pair in pairs[:max_pairs_per_offender]:
                t1,t2=pair
                later=max(pair,key=lambda t:_task_stop_position(source,owner,t))
                old_contacts=set(_existing_contacts_after_task(source,t1))
                for visit_id in list(_existing_contacts_after_task(
                    source,t2,
                )):
                    if visit_id not in old_contacts:
                        continue
                    proposal=deepcopy(source)
                    for task_id in pair:
                        proposal.task_decisions[task_id]=TaskDecision.offload(visit_id)
                    push(
                        f"bundle_reuse_contact::{t1}+{t2}->{visit_id}",
                        proposal,
                    )
                if len(source.routes[owner].contact_visit_ids())<instance.max_contacts_per_uav:
                    options=_best_new_contact_locations(
                        instance,source,later,limit=4,per_mec=1,
                    )
                    for _,point,insert in options[:2]:
                        try:
                            proposal=_insert_contact_candidate(
                                instance,source,task_id=later,
                                point_id=point,insert_pos=insert,
                            )
                            new_visits=set(proposal.contact_visits)-set(source.contact_visits)
                            if len(new_visits)!=1:
                                raise RuntimeError("Unexpected MEC visit creation")
                            visit_id=next(iter(new_visits))
                            for task_id in pair:
                                proposal.task_decisions[task_id]=TaskDecision.offload(visit_id)
                            push(
                                f"bundle_new_contact::{t1}+{t2}->{point}@{insert}",
                                proposal,
                            )
                        except (ValueError,KeyError):
                            pass

                if not include_cross_uav:
                    continue
                # Atomic pair relocation changes two UAV-local FIFO queues
                # at once. _destroy_tasks removes both local tasks, retaining
                # other offloaded tasks and their legally ordered contacts.
                destroyed=_destroy_tasks(state,pair)
                first,second=sorted(
                    pair,key=lambda t:_task_stop_position(source,owner,t)
                )
                destinations=set()
                for opt in _options_for_task(destroyed,first):
                    if opt.uav_id==owner or opt.uav_id in destinations:
                        continue
                    destinations.add(opt.uav_id)
                    one=destroyed.copy()
                    _apply_local_insertion(one,first,opt)
                    second_opts=[
                        x for x in _options_for_task(one,second)
                        if x.uav_id==opt.uav_id
                    ]
                    if not second_opts:
                        continue
                    two=one.copy()
                    _apply_local_insertion(two,second,second_opts[0])
                    push(
                        f"bundle_cross_uav::{first}+{second}->{opt.uav_id}"
                        f"@{opt.position}/{second_opts[0].position}",
                        two.solution,
                    )
                    if len(destinations)>=2:
                        break

        elif decision.mode is ExecutionMode.OFFLOAD:
            visit_id=decision.contact_visit_id
            if visit_id not in source.contact_visits:
                continue
            batch=[
                t for t,d in source.task_decisions.items()
                if d.contact_visit_id==visit_id and t!=delayed
            ]
            batch.sort(
                key=lambda t:(-instance.tasks[t].workload_gcycles,t),
            )
            if len(source.routes[owner].contact_visit_ids())>=instance.max_contacts_per_uav:
                continue
            for companion in batch[:max_pairs_per_offender]:
                pair=(delayed,companion)
                for _,point,pos in _best_split_locations(
                    instance,source,owner,visit_id,pair,
                ):
                    proposal=deepcopy(source)
                    new_visit=_next_visit_id(proposal,owner)
                    stops=list(proposal.routes[owner].stops)
                    stops.insert(pos,RouteStop.contact(new_visit))
                    proposal.routes[owner]=Route(owner,tuple(stops))
                    proposal.contact_visits[new_visit]=ContactVisit(
                        visit_id=new_visit,uav_id=owner,point_id=point,
                    )
                    for t in pair:
                        proposal.task_decisions[t]=TaskDecision.offload(new_visit)
                    push(
                        f"bundle_early_split::{delayed}+{companion}"
                        f"::{visit_id}->{point}@{pos}",
                        proposal,
                    )

    return candidates,{
        "unique_valid_candidates":len(candidates),
        "families":{
            name:sum(label.startswith(name) for label,_ in candidates)
            for name in (
                "bundle_reuse_contact","bundle_new_contact",
                "bundle_early_split","bundle_cross_uav",
            )
        },
        "structural_rejection_types":reject_counts,
        "root_queue_reasons":pressure.get("reasons",[])[:3],
    }
