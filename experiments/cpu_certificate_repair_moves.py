"""Experimental P3: certificate-targeted *structural* UAV-MEC repair.

Target tasks are identified from the binding static (UAV,MEC) CPU-share
necessary inequality, NOT from their raw workloads alone. Legal repair
families are held identical against a global-heavy-task target control.
None of these moves is accepted as feasible without unchanged full P1-R
and Stage-2 independent residual audit. This is NOT the paper algorithm.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import (
    ProxyObjectiveEvaluator, solution_signature,
)
from uav_mec.algorithms.alns.operators import (
    _cleanup_orphan_contacts, _destroy_tasks,
    _options_for_task, _apply_local_insertion,
)
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations, _existing_contacts_after_task,
    _insert_contact_candidate,
)
from uav_mec.domain import TaskDecision, ExecutionMode
from uav_mec.evaluation import build_event_info, visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)


def certificate_focus_tasks(instance, source, *, task_limit=3):
    """Return a causal *hypothesis*: binding deadlines and CPU-heavy prefix.

    The guaranteed necessary test identifies overloaded static virtual
    queues. Target identification is heuristic: a task's appearance in a
    binding prefix does NOT prove that changing it will restore feasibility.
    """
    if task_limit < 1:
        raise ValueError("task_limit must be positive")
    info=build_event_info(instance,source)
    bound=station_cpu_share_necessary_bound(instance,source,info=info)
    pair_rank=[]
    for key,row in bound["pair_demands"].items():
        mid=row["station_id"]
        station=bound["stations"][mid]
        station_pressure=station["min_cpu_pressure_ratio"]
        pair_need=row["needed_cpu_ghz_lb"]
        pair_rank.append((
            # Violating stations first, then model-predicted CPU pressure.
            not station["necessary_capacity_violation"],
            -float("inf") if station_pressure is None else -station_pressure,
            -float("inf") if pair_need is None else -pair_need,
            key,row,
        ))
    pair_rank.sort(key=lambda x:(x[0],x[1],x[2],x[3]))
    selected=[]; details=[]
    for _,_,_,key,row in pair_rank:
        if len(selected)>=task_limit:break
        binding=row.get("deadline_binding")
        if not binding:continue
        uid,mid=row["pair"]
        order=[]
        for v in info.contact_order[uid]:
            if visit_mec_id(instance,source,v)!=mid:
                continue
            order.extend(info.batch_edf_order[v])
        if not order:continue
        critical=binding["task_id"]
        if critical not in order:continue
        prefix=order[:order.index(critical)+1]
        ranks=[critical]+sorted(
            (t for t in prefix if t!=critical),
            key=lambda t:(-instance.tasks[t].workload_gcycles,t),
        )
        for tid in ranks:
            if tid in selected:continue
            selected.append(tid)
            details.append({
                "task_id":tid,
                "bottleneck_pair":key,
                "station_id":mid,
                "station_cpu_share_ratio_lb":(
                    bound["stations"][mid]["min_cpu_pressure_ratio"]),
                "is_binding_task":tid==critical,
                "task_workload_gcycles":instance.tasks[tid].workload_gcycles,
            })
            if len(selected)>=task_limit:break
    return selected,{"details":details,"bound":bound}


def heavy_task_control(instance,source,*,task_limit):
    """Negative control: same number of targets, global load only."""
    if task_limit<=0:return []
    tasks=[
        tid for tid,d in source.task_decisions.items()
        if d.mode is ExecutionMode.OFFLOAD
    ]
    return sorted(
        tasks,key=lambda tid:(-instance.tasks[tid].workload_gcycles,tid)
    )[:task_limit]


def cpu_conflict_moves(instance,source,*,policy="certificate",task_limit=3):
    """Generate IDENTICAL move families for certificate/workload control.

    Per-target: local execution, alternate existing MEC contact, alternate
    new MEC contact, or single-task transfer to another UAV's LOCAL FIFO.
    Structural legality, original maximum visits and provenance are checked.
    """
    if policy not in ("certificate","workload"):
        raise ValueError(policy)
    focus,metadata=certificate_focus_tasks(
        instance,source,task_limit=task_limit,
    )
    targets=(focus if policy=="certificate" else
             heavy_task_control(instance,source,task_limit=len(focus)))
    info=build_event_info(instance,source)
    state=UavMecState(instance,deepcopy(source),ProxyObjectiveEvaluator())
    unique={solution_signature(source)}
    moves=[]
    skipped=Counter()

    def add(label, candidate):
        try:
            _cleanup_orphan_contacts(candidate)
            validate_solution(instance,candidate)
        except (ValueError,KeyError) as exc:
            skipped[type(exc).__name__]+=1
            return
        signature=solution_signature(candidate)
        if signature in unique:return
        unique.add(signature)
        moves.append((label,candidate))

    for tid in targets:
        dec=source.task_decisions[tid]
        if dec.mode is not ExecutionMode.OFFLOAD:
            continue
        old_visit=dec.contact_visit_id
        old_mid=visit_mec_id(instance,source,old_visit)
        owner=info.task_owner[tid]

        # 1. Stop sharing MEC CPU; may trade conflict for local FIFO pressure.
        proposal=deepcopy(source)
        proposal.task_decisions[tid]=TaskDecision.local()
        add(f"cpu_target_local::{tid}",proposal)

        # 2. Reuse a legal existing contact to an ALTERNATIVE station.
        after=_existing_contacts_after_task(source,tid)
        for visit in after:
            if visit_mec_id(instance,source,visit)==old_mid:
                continue
            proposal=deepcopy(source)
            proposal.task_decisions[tid]=TaskDecision.offload(visit)
            add(f"cpu_target_alt_reuse::{tid}->{visit}",proposal)
            break

        # 3. Move this task to an alternative MEC with at most one new visit.
        if len(source.routes[owner].contact_visit_ids())<instance.max_contacts_per_uav:
            options=_best_new_contact_locations(
                instance,source,tid,limit=max(4,len(instance.contact_points)),
                per_mec=1,
            )
            for _,point,pos in options:
                if instance.contact_points[point].mec_id==old_mid:continue
                try:
                    proposal=_insert_contact_candidate(
                        instance,source,task_id=tid,
                        point_id=point,insert_pos=pos,
                    )
                except (ValueError,KeyError):
                    continue
                add(f"cpu_target_alt_new::{tid}->{point}@{pos}",proposal)
                break

        # 4. Relocate an offloaded task to a different UAV's local queue.
        destroyed=_destroy_tasks(state,[tid])
        options=_options_for_task(destroyed,tid)
        for opt in options:
            if opt.uav_id==owner:continue
            candidate=destroyed.copy()
            _apply_local_insertion(candidate,tid,opt)
            add(f"cpu_target_cross_local::{tid}->{opt.uav_id}@{opt.position}",
                candidate.solution)
            break

    return moves,{
        "policy":policy,
        "certificate_focus":focus,
        "actual_targets":targets,
        "source_cpu_capacity_violation":bool(
            metadata["bound"]["certified_cpu_share_failure"]
        ),
        "source_station_cpu_pressure":{
            mid:v["min_cpu_pressure_ratio"]
            for mid,v in metadata["bound"]["stations"].items()
        },
        "focus_explanation":metadata["details"],
        "valid_unique_moves":len(moves),
        "move_family_counts":dict(Counter(
            l.split("::")[0] for l,_ in moves)),
        "invalid_structural_move_counts":dict(skipped),
    }
