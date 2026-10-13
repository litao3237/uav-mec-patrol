"""P17 lightweight proxy-CONSISTENT MEC insertion-actionability selection.

This solves a concrete P15 diagnostic flaw without completing MEC 3x.
An optimistic virtual TaskDecision.offload can pass FIFO/EDF but never
be chosen by the ORIGINAL greedy MEC builder because the action is not
in original _critical_local_tasks(top8) or violates the exact original
ProxyScore lexical improvement rule. P16 directly reproduced these
conditions for S96/S23: old rank1/rank2 no accepted reuse, old rank3
S23->G_U5_2 accepted by original builder and strict Stage1+2.

Only on the FINAL of 12 reinstated tasks, evaluate original top3
LOCAL trial completions with old capacity-feasible cheap
evaluate_initial_proxy(). For each downstream ORIGINAL contact,
evaluate exactly one original _reuse_contact_candidate() proxy.
Record whether inserted task is in old greedy critical8 AND
_strictly_better(reuse_proxy,local_proxy). This mirrors a necessary
condition for one candidate to enter the next original greedy MEC
move shortlist, not a proof it will be chosen or Stage1 feasible.

ALNS's original task reinsertion order for first 11 tasks is
unchanged. The ORIGINAL _finish_repair is called ONCE on the chosen
LOCAL insertion. Original 3 destroy, 2 repair, RRT, roulette, oracle,
P1-R model and Stage1/Stage2 residual thresholds stay unchanged.

Arms use same proxy evaluations on the same original top3 set:
  proxy_sham: choose original rank1, computation-cost control.
  proxy_contact: prefer available old contact, negative control.
  proxy_critical: prefer a position where inserted task in old MEC
    critical8 and at least one downstream old contact, no exact score
    improvement test.
  proxy_actionable: keep rank1 if its old proxy already has 0
    violations; otherwise select among EXACT original greedy
    accepted candidate reuse scores, falling back to old rank1.
Do not apply to other original ALNS repair stages or production develop.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass,field
from functools import wraps
from time import perf_counter

from p14_post_mec_preview_repair import _insertion_task_and_best_option
from uav_mec.algorithms.alns import operators as ops
from uav_mec.algorithms.initial.mec_repair import (
    GreedyMECRepairConfig,
    _critical_local_tasks,
    _existing_contacts_after_task,
    _reuse_contact_candidate,
    _strictly_better,
    evaluate_initial_proxy,
)

POLICIES=("proxy_sham","proxy_contact","proxy_critical","proxy_actionable")
TOP_K=3


@dataclass
class ActionabilityCounters:
    policy:str
    repair_calls:Counter=field(default_factory=Counter)
    selected_ranks:Counter=field(default_factory=Counter)
    original_builder_count:int=0
    cheap_local_proxy_calls:int=0
    cheap_reuse_proxy_calls:int=0
    actual_reuse_actions_accepted:int=0
    selected_non_top1:int=0
    rank1_was_proxy_feasible:int=0
    fallback_no_eligible_reuse:int=0
    cheap_previews:int=0
    cheap_scoring_wall_s:float=0.0
    examples:list[dict]=field(default_factory=list)

    def snapshot(self):
        return {
            "policy":self.policy,
            "repair_calls":dict(self.repair_calls),
            "selected_ranks":dict(self.selected_ranks),
            "original_builder_count":self.original_builder_count,
            "cheap_local_proxy_calls":self.cheap_local_proxy_calls,
            "cheap_reuse_proxy_calls":self.cheap_reuse_proxy_calls,
            "actual_reuse_actions_accepted":self.actual_reuse_actions_accepted,
            "selected_non_top1":self.selected_non_top1,
            "rank1_was_proxy_feasible":self.rank1_was_proxy_feasible,
            "fallback_no_eligible_reuse":self.fallback_no_eligible_reuse,
            "cheap_previews":self.cheap_previews,
            "cheap_scoring_wall_s":self.cheap_scoring_wall_s,
            "examples":self.examples[:8],
        }


def preview_actionable_reuse(state,tid,option,rank,counters:ActionabilityCounters):
    t0=perf_counter()
    candidate=state.copy()
    ops._apply_local_insertion(candidate,tid,option)
    inst=candidate.instance
    local=candidate.solution
    builder=GreedyMECRepairConfig()
    before=evaluate_initial_proxy(inst,local)
    counters.cheap_local_proxy_calls+=1
    critical=(
        _critical_local_tasks(
            inst,local,before,limit=builder.critical_task_limit)
        if before.score.violated_constraints else [])
    contacts=list(_existing_contacts_after_task(local,tid))
    actionable=[]
    for vid in contacts:
        discrete=_reuse_contact_candidate(
            inst,local,task_id=tid,visit_id=vid)
        alt=evaluate_initial_proxy(inst,discrete)
        counters.cheap_reuse_proxy_calls+=1
        if tid in critical and _strictly_better(
            alt.score,before.score,
            tolerance=builder.improvement_tolerance):
            actionable.append((tuple(alt.score.key),vid))
            counters.actual_reuse_actions_accepted+=1
    best=min(actionable,default=None)
    counters.cheap_previews+=1
    counters.cheap_scoring_wall_s+=perf_counter()-t0
    return {
        "rank":rank,"state":candidate,
        "base_proxy":tuple(before.score.key),
        "original_critical":tid in critical,
        "reachable_contacts":len(contacts),
        "first_reachable_contact":contacts[0] if contacts else None,
        "best_accepted_reuse":best,
    }


def choose_actionable(previews,policy):
    if policy not in POLICIES:raise ValueError(policy)
    first=previews[0]
    if policy=="proxy_sham":
        return first,"same_budget_orig_rank1"
    if policy=="proxy_contact":
        return min(previews,key=lambda x:(
            x["reachable_contacts"]==0,
            -x["reachable_contacts"],x["rank"])),"old_contact_only"
    if policy=="proxy_critical":
        candidates=[x for x in previews
                    if x["original_critical"] and x["reachable_contacts"]]
        return (min(candidates,key=lambda x:x["rank"])
                if candidates else first),"critical_pool_and_contact_only"
    if not first["base_proxy"][0]:
        return first,"old_rank1_zero_proxy_violation"
    accepted=[x for x in previews if x["best_accepted_reuse"] is not None]
    if not accepted:
        return first,"no_eligible_original_greedy_reuse"
    return min(accepted,key=lambda x:(
        x["best_accepted_reuse"][0],x["rank"])),"best_accepted_original_greedy_reuse"


def make_actionable_repair(kind,policy,counters:ActionabilityCounters):
    if kind not in ("cheapest","regret2") or policy not in POLICIES:
        raise ValueError("Unknown original repair or P17 policy")
    original=(ops.cheapest_insertion_repair if kind=="cheapest"
              else ops.regret2_insertion_repair)

    @wraps(original)
    def wrapper(destroyed,rng):
        counters.repair_calls[kind]+=1
        state=destroyed.copy()
        while len(state.removed_tasks)>1:
            tid,option=_insertion_task_and_best_option(state,kind)
            ops._apply_local_insertion(state,tid,option)
        if not state.removed_tasks:
            finished=ops._finish_repair(state)
            counters.original_builder_count+=1
            return finished
        tid=state.removed_tasks[0]
        options=ops._options_for_task(state,tid)
        previews=[
            preview_actionable_reuse(state,tid,option,rank,counters)
            for rank,option in enumerate(options[:TOP_K],start=1)
        ]
        chosen,reason=choose_actionable(previews,policy)
        counters.selected_ranks[chosen["rank"]]+=1
        counters.selected_non_top1+=int(chosen["rank"]!=1)
        counters.rank1_was_proxy_feasible+=int(previews[0]["base_proxy"][0]==0)
        counters.fallback_no_eligible_reuse+=int(
            reason=="no_eligible_original_greedy_reuse")
        if len(counters.examples)<8:
            counters.examples.append({
                "kind":kind,"last_task":tid,
                "selected_rank":chosen["rank"],
                "reason":reason,
                "rank1_old_proxy_zero_violations":previews[0]["base_proxy"][0]==0,
                "original_eligible_actionable_ranks":[
                    x["rank"] for x in previews
                    if x["best_accepted_reuse"] is not None],
                "available_prior_contacts":[x["reachable_contacts"] for x in previews],
            })
        finished=ops._finish_repair(chosen["state"])
        counters.original_builder_count+=1
        return finished

    return wrapper


def make_actionable_repair_list(policy,counters:ActionabilityCounters):
    original=ops.make_repair_operators()
    result=[]
    for name,_ in original:
        if name=="cheapest_insertion_mec_repair":
            result.append((name,make_actionable_repair("cheapest",policy,counters)))
        elif name=="regret2_insertion_mec_repair":
            result.append((name,make_actionable_repair("regret2",policy,counters)))
        else:
            raise RuntimeError("Unrecognized original ALNS repair slot "+name)
    if len(result)!=len(original):
        raise RuntimeError("P17 modified ALNS operator counts")
    return result
