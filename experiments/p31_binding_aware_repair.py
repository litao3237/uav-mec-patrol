"""P31 bounded ALNS repair: binding-pair-aware cross-UAV, cross-MEC relocation.

EXPERIMENT-ONLY hook, not a change to develop. Keep original destroy,
cheapest/regret2, greedy MEC builder exactly once per repair, roulette/RRT,
ScreenedProxy and ORIGINAL independent Stage1/Stage2 completely unchanged.

After the legacy full MEC repair, optionally relocate a binding task to
another UAV, executing it locally or reusing an already-existing downstream
contact with another MEC. Same generated physical candidates and diagnostic
work for sham, queue, cpu and joint arms. No candidate CVX before selection.
Full original scalar objective and ALNS acceptance remain responsible for
the resulting search path. Necessary filters are never labeled strict.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter

from uav_mec.algorithms.alns import operators as ops
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.domain import ExecutionMode, StopType, TaskDecision
from uav_mec.evaluation import build_event_info, visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

POLICIES=("sham","queue_only","cpu_only","joint_cpu_bw")


@dataclass(frozen=True)
class P31Limits:
    targets:int=2
    destination_uavs:int=3
    insertion_ranks_per_uav:int=2
    alternate_contacts_per_position:int=2
    total_candidates:int=24
    joint_bw_cpu_bins:int=16


@dataclass
class P31Counters:
    policy:str
    calls:int=0
    legacy_full_builder_calls:int=0
    generated_candidates:int=0
    evaluated_candidates:int=0
    joint_bound_calls:int=0
    no_target:int=0
    no_better:int=0
    chosen_other_D:int=0
    already_necessary_passing:int=0
    total_diagnostic_wall_s:float=0.
    examples:list=field(default_factory=list)
    discarded:Counter=field(default_factory=Counter)

    def snapshot(self):
        return {
            "policy":self.policy,"calls":self.calls,
            "legacy_full_builder_calls":self.legacy_full_builder_calls,
            "generated_candidates":self.generated_candidates,
            "evaluated_candidates":self.evaluated_candidates,
            "joint_bound_calls":self.joint_bound_calls,
            "no_target":self.no_target,"no_better":self.no_better,
            "chosen_other_D":self.chosen_other_D,
            "already_necessary_passing":self.already_necessary_passing,
            "total_diagnostic_wall_s":self.total_diagnostic_wall_s,
            "examples":self.examples[:8],"discarded":dict(self.discarded),
        }


def _diagnose(instance,solution,*,bins:int,counters=None):
    info=build_event_info(instance,solution)
    q=queue_aware_feasibility_precheck(instance,solution,info)
    cpu=station_cpu_share_necessary_bound(
        instance,solution,info=info,queue=q)
    norm=sum(
        max(0.,q.task_completion_lb_s[tid]-task.release_s-task.deadline_s)/
        max(1.,task.deadline_s)
        for tid,task in instance.tasks.items())
    norm+=max(0.,q.avg_delay_lb_s-instance.avg_delay_budget_s)/max(
        1.,instance.avg_delay_budget_s)
    norm+=sum(
        max(0.,ret-instance.cycle_s)/max(1.,instance.cycle_s)
        for ret in q.return_time_lb_s.values())
    cpu_excess=sum(
        (stat["excess_cpu_ghz_lb"] or 0.)/
        max(1.,instance.mecs[mid].cpu_ghz)
        for mid,stat in cpu["stations"].items())
    pressure=max((
        stat["min_cpu_pressure_ratio"] or 0.
        for stat in cpu["stations"].values()
    ),default=0.)
    cpu_bad=bool(cpu["certified_cpu_share_failure"])
    joint_pass=False
    joint_excess=float("inf")
    if q.feasible and not cpu_bad:
        j=joint_station_bw_cpu_necessary_bound(
            instance,solution,info=info,queue=q,n_bins=bins)
        if counters is not None:counters.joint_bound_calls+=1
        joint_pass=bool(j["passes_joint_necessary_test"])
        joint_excess=sum(
            (st["oversubscription_cpu_ghz"] or 0.)/
            max(1.,instance.mecs[mid].cpu_ghz)
            for mid,st in j["stations"].items())
    return {
        "queue_pass":bool(q.feasible),
        "queue_reason_count":len(q.reasons),
        "queue_normalized_excess":norm,
        "cpu_bad":cpu_bad,"cpu_excess_ratio":cpu_excess,
        "cpu_pressure_ratio":pressure,
        "joint_pass":joint_pass,"joint_excess_ratio":joint_excess,
        "route_m":sum(info.route_distance_m.values()),
        "cpu_bound":cpu,"queue":q,"info":info,"solution":solution,
    }


def binding_targets(instance,diagnosis,limit:int=2):
    info=diagnosis["info"]
    bound=diagnosis["cpu_bound"]
    sol=diagnosis["solution"]
    pairs=[]
    for name,row in bound["pair_demands"].items():
        binding=row.get("deadline_binding")
        if binding is None:continue
        pressure=bound["stations"][row["station_id"]]["min_cpu_pressure_ratio"]
        need=row["needed_cpu_ghz_lb"]
        key=(-(pressure if pressure is not None else 1e6),
             -(need if need is not None else 1e6),name)
        pairs.append((key,row,binding))
    pairs.sort(key=lambda item:item[0])
    focus=[]
    for _,pair,binding in pairs:
        uav,mec=pair["pair"]
        prefix=[]
        for visit in info.contact_order[uav]:
            if visit_mec_id(instance,sol,visit)!=mec:
                continue
            prefix.extend(info.batch_edf_order[visit])
            if visit==binding["visit_id"]:break
        task=binding["task_id"]
        optional=sorted(
            (t for t in prefix if t!=task),
            key=lambda t:(-instance.tasks[t].workload_gcycles,t),
        )[:1]
        for tid in (task,*optional):
            if tid not in focus:focus.append(tid)
            if len(focus)>=limit:return focus
    return focus


def legal_cross_uav(instance,solution,targets,limits,counters):
    """Every returned candidate is a complete original-hardware legal D."""
    from uav_mec.algorithms.alns import UavMecState
    seen={solution_signature(solution)}
    generated=[]
    for tid in targets:
        old_uav=next(u for u,r in solution.routes.items() if tid in r.task_ids())
        dec=solution.task_decisions[tid]
        old_mec=(
            visit_mec_id(instance,solution,dec.contact_visit_id)
            if dec.mode is ExecutionMode.OFFLOAD else None)
        state=UavMecState(instance,deepcopy(solution),lambda inst,s:0.)
        broken=ops._destroy_tasks(state,[tid])
        dests={}
        for option in ops._options_for_task(broken,tid):
            if option.uav_id!=old_uav:
                dests.setdefault(option.uav_id,[]).append(option)
        for dest,valid in sorted(dests.items())[:limits.destination_uavs]:
            chosen=valid[:limits.insertion_ranks_per_uav]
            earliest=min(valid,key=lambda x:(x.position,x.key))
            if earliest not in chosen:chosen=[*chosen,earliest]
            for option in chosen:
                step=broken.copy()
                ops._apply_local_insertion(step,tid,option)
                complete=step.solution
                tid_position=next(
                    i for i,x in enumerate(complete.routes[dest].stops)
                    if x.kind is StopType.TASK and x.ref_id==tid)
                modes=[("local",None)]
                for i,stop in enumerate(complete.routes[dest].stops):
                    if stop.kind is not StopType.CONTACT or i<=tid_position:continue
                    if old_mec is None or visit_mec_id(
                        instance,complete,stop.ref_id)!=old_mec:
                        modes.append(("reuse_alt_station",stop.ref_id))
                modes=modes[:1+limits.alternate_contacts_per_position]
                for mode,visit_id in modes:
                    changed=deepcopy(complete)
                    if visit_id:
                        changed.task_decisions[tid]=TaskDecision.offload(visit_id)
                    try:
                        validate_solution(instance,changed)
                    except (ValueError,KeyError):
                        counters.discarded["invalid_D"]+=1
                        continue
                    signature=solution_signature(changed)
                    if signature in seen:
                        counters.discarded["duplicate"]+=1
                        continue
                    seen.add(signature)
                    generated.append({
                        "task":tid,"old_UAV":old_uav,"new_UAV":dest,
                        "mode":mode,"contact":visit_id,
                        "position":option.position,"solution":changed,
                    })
                    if len(generated)>=limits.total_candidates:
                        return generated
    return generated


def rank_key(a,policy):
    head=(not a["queue_pass"],a["queue_reason_count"])
    if policy in ("sham","joint_cpu_bw"):
        return head+(
            not a["joint_pass"],a["cpu_bad"],a["joint_excess_ratio"],
            a["cpu_excess_ratio"],a["queue_normalized_excess"],a["route_m"])
    if policy=="cpu_only":
        return head+(a["cpu_bad"],a["cpu_excess_ratio"],
                     a["queue_normalized_excess"],a["route_m"])
    if policy=="queue_only":
        return head+(a["queue_normalized_excess"],a["route_m"])
    raise ValueError(policy)


def refine_one(complete,policy,counters:P31Counters,limits:P31Limits=None):
    if policy not in POLICIES:raise ValueError(policy)
    limits=limits or P31Limits()
    start=perf_counter()
    counters.calls+=1
    instance=complete.instance
    old=complete.solution
    baseline=_diagnose(
        instance,old,bins=limits.joint_bw_cpu_bins,counters=counters)
    if baseline["joint_pass"]:
        counters.already_necessary_passing+=1
        counters.total_diagnostic_wall_s+=perf_counter()-start
        return complete
    targets=binding_targets(instance,baseline,limit=limits.targets)
    if not targets:
        counters.no_target+=1
        counters.total_diagnostic_wall_s+=perf_counter()-start
        return complete
    candidates=legal_cross_uav(instance,old,targets,limits,counters)
    counters.generated_candidates+=len(candidates)
    original_key=rank_key(baseline,policy)
    best_key=original_key
    best=None
    for row in candidates:
        d=_diagnose(
            instance,row["solution"],
            bins=limits.joint_bw_cpu_bins,counters=counters)
        counters.evaluated_candidates+=1
        key=rank_key(d,policy)
        if key<best_key:
            best_key=key
            best={**row,"diagnostic":d}
    if best is None:counters.no_better+=1
    if best is not None and len(counters.examples)<8:
        counters.examples.append({
            "task":best["task"],"new_UAV":best["new_UAV"],
            "mode":best["mode"],"contact":best["contact"],
            "old_queue":baseline["queue_pass"],
            "new_queue":best["diagnostic"]["queue_pass"],
            "old_cpu_bad":baseline["cpu_bad"],
            "new_cpu_bad":best["diagnostic"]["cpu_bad"],
            "new_joint_pass":best["diagnostic"]["joint_pass"],
        })
    counters.total_diagnostic_wall_s+=perf_counter()-start
    if policy=="sham" or best is None:
        return complete
    changed=complete.copy()
    changed.solution=best["solution"]
    changed.invalidate()
    validate_solution(instance,changed.solution)
    counters.chosen_other_D+=1
    return changed


def make_repair_list(policy,counters:P31Counters,limits:P31Limits=None):
    if policy not in POLICIES:raise ValueError(policy)
    result=[]
    for name,old_fn in ops.make_repair_operators():
        @wraps(old_fn)
        def wrapped(destroyed,rng,old_fn=old_fn):
            state=old_fn(destroyed,rng)
            counters.legacy_full_builder_calls+=1
            return refine_one(state,policy,counters,limits)
        result.append((name,wrapped))
    if [n for n,_ in result]!=[n for n,_ in ops.make_repair_operators()]:
        raise RuntimeError("Legacy ALNS repair operator names changed")
    return result
