"""P15 lightweight INSERTION prediction without any extra MEC reconstruction.

P12–P14 established that old rank1 can miss strict Stage1+Stage2 feasible
contact reuse, yet P14's 3x full build_mec_assisted_initial_solution
cuts ALNS iterations by ~45% under matched exploration wall clocks.

P15 tests a strictly cheaper proxy on the LAST inserted task ONLY.
For every original top3 position, complete the partial ALNS state by
LOCAL insertion (as the original repair would); evaluate the already
available FIFO/EDF *necessary* precheck. Then in TEMPORARY metadata
only, consider the same task OFFLOADED at each existing downstream
contact and run the same optimistic FIFO/EDF checker; RESTORE original
LOCAL TaskDecision afterward. No contact is added, removed, moved, or
rebuilt, and NO CVX/Stage2 is called in selection.

This is heuristic model-specific prediction, never a mathematical
feasibility certificate. The original _finish_repair runs exactly
ONCE after a cheap insertion rank is selected. Same original ALNS
destroy and repair names/count, ScreenedProxy evaluator, RRT/roulette
and original strictly-qualified Stage1+2 remain unchanged.

Policies:
- cheap_sham: evaluate exactly the same local/virtual-offload metrics
  and always return original rank1 (cost-only control).
- cheap_contact: prefer a route position with an existing reachable
  MEC upload contact and earlier visit (contact-only negative control).
- cheap_virtual: choose minimum virtual single-contact/local
  FIFO/EDF necessary time score.
- cheap_guarded: retain rank1 when original local all-task queue
  passes. Otherwise use cheap_virtual.
No empirical weight fitting, no posthoc new-scene tuning.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter

from p14_post_mec_preview_repair import (
    _insertion_task_and_best_option,
    _queue_rank,
)
from uav_mec.algorithms.alns import operators as ops
from uav_mec.domain import StopType,TaskDecision

POLICIES=(
    "cheap_sham",
    "cheap_contact",
    "cheap_virtual",
    "cheap_guarded",
)
TOP_K=3


@dataclass
class CheapCounters:
    policy:str
    repair_calls:Counter=field(default_factory=Counter)
    selected_ranks:Counter=field(default_factory=Counter)
    evaluated_positions:int=0
    virtual_offload_checked:int=0
    rerouted_to_virtual_mec:int=0
    selected_non_top1:int=0
    original_top1_guarded:int=0
    original_rank_selected:int=0
    all_cheap_prediction_wall_s:float=0.
    full_MEC_finishes:int=0
    examples:list[dict]=field(default_factory=list)

    def snapshot(self):
        return {
            "policy":self.policy,
            "repair_calls":dict(self.repair_calls),
            "selected_ranks":dict(self.selected_ranks),
            "evaluated_positions":self.evaluated_positions,
            "virtual_offload_checked":self.virtual_offload_checked,
            "selected_non_top1":self.selected_non_top1,
            "original_top1_guarded":self.original_top1_guarded,
            "original_rank_selected":self.original_rank_selected,
            "all_cheap_prediction_wall_s":self.all_cheap_prediction_wall_s,
            "full_MEC_finishes":self.full_MEC_finishes,
            "examples":self.examples[:8],
        }


def cheap_score_for_option(state,task_id,option,*,rank,counters:CheapCounters):
    """On a SINGLE full-but-route-only D: simulated contact reuse, never MEC build."""
    t0=perf_counter()
    copy=state.copy()
    ops._apply_local_insertion(copy,task_id,option)
    trial=copy.solution
    local_key=_queue_rank(copy.instance,trial)
    all_keys=[("LOCAL",local_key)]
    route=trial.routes[option.uav_id]
    for stop in route.stops[option.position+1:]:
        if stop.kind is not StopType.CONTACT:
            continue
        v=stop.ref_id
        original=trial.task_decisions[task_id]
        trial.task_decisions[task_id]=TaskDecision.offload(v)
        try:
            key=_queue_rank(copy.instance,trial)
            all_keys.append((v,key))
            counters.virtual_offload_checked+=1
        finally:
            trial.task_decisions[task_id]=original
    key=min((score for _,score in all_keys))
    best_mode=next(mode for mode,score in all_keys if score==key)
    counters.evaluated_positions+=1
    counters.all_cheap_prediction_wall_s+=perf_counter()-t0
    return {
        "rank":rank,"option":option,"state":copy,
        "local_key":local_key,
        "best_virtual_key":key,
        "best_virtual_mode":best_mode,
        "reachable_old_contacts":len(all_keys)-1,
        "first_reachable_contact_position":next((
            i for i,stop in enumerate(route.stops[option.position+1:],
                                     start=option.position+1)
            if stop.kind is StopType.CONTACT),None),
    }


def _selection_key(record,policy):
    if policy=="cheap_contact":
        # Deliberately no queue information; test whether contact
        # reachability alone explains gains or removes valid paths.
        first=record["first_reachable_contact_position"]
        return (
            record["reachable_old_contacts"]==0,
            first if first is not None else 10**6,
            record["rank"],
        )
    return (record["best_virtual_key"],record["rank"])


def make_cheap_repair(kind,policy,counters:CheapCounters):
    if kind not in ("cheapest","regret2") or policy not in POLICIES:
        raise ValueError("Unknown registered P15 operator or policy")
    original=(ops.cheapest_insertion_repair if kind=="cheapest"
              else ops.regret2_insertion_repair)

    @wraps(original)
    def wrapper(destroyed,rng):
        counters.repair_calls[kind]+=1
        state=destroyed.copy()
        # Exactly match the ORIGINAL task order and original top-1
        # placements until the last removed task. No random draw added.
        while len(state.removed_tasks)>1:
            tid,choice=_insertion_task_and_best_option(state,kind)
            ops._apply_local_insertion(state,tid,choice)
        if not state.removed_tasks:
            result=ops._finish_repair(state)
            counters.full_MEC_finishes+=1
            return result
        task_id=state.removed_tasks[0]
        options=ops._options_for_task(state,task_id)
        if not options:raise RuntimeError("Original repair produced no final insertion")
        proposed=[]
        for rank,option in enumerate(options[:TOP_K],start=1):
            proposed.append(
                cheap_score_for_option(
                    state,task_id,option,rank=rank,counters=counters))
        if policy=="cheap_guarded" and not proposed[0]["local_key"][0]:
            winner=proposed[0]
            counters.original_top1_guarded+=1
        elif policy=="cheap_sham":
            winner=proposed[0]
        else:
            winner=min(proposed,key=lambda x:_selection_key(x,policy))
        counters.selected_ranks[winner["rank"]]+=1
        counters.selected_non_top1+=int(winner["rank"]>1)
        counters.original_rank_selected+=int(winner["rank"]==1)
        if len(counters.examples)<8:
            counters.examples.append({
                "kind":kind,
                "last_inserted_task":task_id,
                "chosen_original_rank":winner["rank"],
                "old_top1_local_queue_pass":not proposed[0]["local_key"][0],
                "best_virtual_mode":winner["best_virtual_mode"],
                "top3_virtual_pass":sum(
                    not x["best_virtual_key"][0] for x in proposed),
                "original_downstream_contacts":[
                    x["reachable_old_contacts"] for x in proposed],
            })
        # Must return the candidate's ORIGINAL local insertion to the
        # unchanged MEC builder, NEVER apply virtual diagnostics as
        # real accepted TaskDecision. Exactly ONE full MEC build.
        result=ops._finish_repair(winner["state"])
        counters.full_MEC_finishes+=1
        return result

    return wrapper


def build_cheap_repair_list(policy,counters:CheapCounters):
    result=[]
    orig=ops.make_repair_operators()
    for name,_ in orig:
        if name=="cheapest_insertion_mec_repair":
            result.append((name,make_cheap_repair("cheapest",policy,counters)))
        elif name=="regret2_insertion_mec_repair":
            result.append((name,make_cheap_repair("regret2",policy,counters)))
        else:
            raise RuntimeError("Unexpected original repair slot "+name)
    if len(result)!=len(orig):
        raise RuntimeError("Changed original ALNS repair operator count")
    return result
