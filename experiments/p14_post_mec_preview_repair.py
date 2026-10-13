"""P14: fixed Top-3 MEC-completion previews INSIDE original ALNS repair.

Every destroy operation, stochastic task insertion order for all but
the final removed task, roulette/RRT selection, original
ScreenedProxyObjectiveEvaluator, and original Stage1/Stage2 are
unchanged. Only final task placement in the two ORIGINAL repair
operators (cheapest, regret2) can be selected differently.

This is not a proof of model feasibility. The optimistic FIFO/EDF
post-MEC checks are used only for ranking. The full original CVX and
saved/reconstructed Stage1+Stage2 qualification remain the arbiter.

'preview_sham' computes the very same three previews and THEN returns
old rank1: it is the compute-cost negative control.
'preview_contact' uses only rebuilt MEC contact/offload metadata to
choose among exactly those three, reproducing P13's unsafe proxy.
'preview_queue' selects minimal full-D optimistic queue violations.
'preview_guarded' preserves rank1 whenever its complete rebuilt
queue necessarily passes; otherwise it evaluates the remaining two.
No additional standalone CVX solves are made for selection.

Monkeypatch the reference ONLY inside the experiments runner, never
edit the develop branch or underlying production repair functions.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter

from uav_mec.algorithms.alns import operators as ops
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)

POLICIES=(
    "preview_sham",
    "preview_contact",
    "preview_queue",
    "preview_guarded",
)
PREVIEW_K=3


def _insertion_task_and_best_option(state,kind):
    """Return EXACT original task-selection for cheapest/regret2."""
    if kind=="cheapest":
        best=None
        for tid in list(state.removed_tasks):
            option=ops._options_for_task(state,tid)[0]
            candidate=(option.key,tid,option)
            if best is None or candidate[:2]<best[:2]:
                best=candidate
        if best is None:raise RuntimeError("Original insertion has no task")
        return best[1],best[2]
    if kind=="regret2":
        chosen=None
        for tid in list(state.removed_tasks):
            options=ops._options_for_task(state,tid)
            best=options[0]
            second=options[1] if len(options)>1 else best
            regret=(
                max(0.0,second.cycle_overflow_s-best.cycle_overflow_s),
                max(0.0,second.deadline_lb_violation_s-
                    best.deadline_lb_violation_s),
                max(0.0,second.delta_distance_m-best.delta_distance_m),
            )
            candidate=(regret,tid,best)
            if chosen is None or candidate[0]>chosen[0]:
                chosen=candidate
        if chosen is None:raise RuntimeError("Original regret2 no task")
        return chosen[1],chosen[2]
    raise ValueError("Unknown original repair kind")


def _queue_rank(instance,solution):
    info=build_event_info(instance,solution)
    q=queue_aware_feasibility_precheck(instance,solution,info)
    total=0.0
    max_task_excess=0.0
    for tid,t in instance.tasks.items():
        gap=max(0.,float(q.task_completion_lb_s[tid])-
                (t.release_s+t.deadline_s))
        total+=gap/max(1.,t.deadline_s)
        max_task_excess=max(max_task_excess,gap)
    total+=max(0.,float(q.avg_delay_lb_s)-
               instance.avg_delay_budget_s)/max(1.,instance.avg_delay_budget_s)
    total+=sum(
        max(0.,float(value)-instance.cycle_s)/max(1.,instance.cycle_s)
        for value in q.return_time_lb_s.values())
    return (
        not bool(q.feasible),
        len(q.reasons),
        total,
        max_task_excess,
        sum(info.route_distance_m.values()),
    )


def _contact_rank(solution,before_solution,rank):
    # Same P13 concept: more tasks offloaded, fewer newly-added contacts,
    # fewer overall MEC contacts, old insertion position for ties.
    from uav_mec.domain import ExecutionMode
    n_offloaded=sum(
        d.mode is ExecutionMode.OFFLOAD
        for d in solution.task_decisions.values())
    new_contacts=len(
        set(solution.contact_visits)-set(before_solution.contact_visits))
    return (-n_offloaded,new_contacts,len(solution.contact_visits),rank)


@dataclass
class PreviewCounters:
    policy: str
    operator_calls: Counter=field(default_factory=Counter)
    selected_ranks: Counter=field(default_factory=Counter)
    queue_pass_wins: Counter=field(default_factory=Counter)
    candidates_previewed: int=0
    chosen_rank_above_one: int=0
    total_extra_mechanism_wall_s: float=0.0
    original_full_repair_returned:int=0
    fallback_on_queue_pass:int=0
    examples:list[dict]=field(default_factory=list)

    def snapshot(self):
        return {
            "policy":self.policy,
            "operator_calls":dict(self.operator_calls),
            "selected_ranks":dict(self.selected_ranks),
            "queue_pass_wins":dict(self.queue_pass_wins),
            "candidates_previewed":self.candidates_previewed,
            "chosen_rank_above_one":self.chosen_rank_above_one,
            "preview_and_ranking_wall_s":self.total_extra_mechanism_wall_s,
            "original_full_repair_returned":self.original_full_repair_returned,
            "fallback_on_queue_pass":self.fallback_on_queue_pass,
            "first_examples":self.examples[:8],
        }


def make_preview_repair(kind,policy,counters:PreviewCounters):
    if kind not in ("cheapest","regret2") or policy not in POLICIES:
        raise ValueError("Unregistered P14 repair operator or policy")
    original=(ops.cheapest_insertion_repair if kind=="cheapest"
              else ops.regret2_insertion_repair)

    @wraps(original)
    def patched(destroyed,rng):
        # The old cheap/regret task selection and insertion are
        # reproduced exactly until the LAST removed task.
        counters.operator_calls[kind]+=1
        state=destroyed.copy()
        while len(state.removed_tasks)>1:
            tid,option=_insertion_task_and_best_option(state,kind)
            ops._apply_local_insertion(state,tid,option)
        if not state.removed_tasks:
            return ops._finish_repair(state)

        tid=state.removed_tasks[0]
        options=ops._options_for_task(state,tid)
        if not options:raise RuntimeError("Original repair has no final insertion")
        started=perf_counter()
        previews=[]
        for ix,opt in enumerate(options[:PREVIEW_K],start=1):
            branch=state.copy()
            ops._apply_local_insertion(branch,tid,opt)
            before=branch.solution
            completed=ops._finish_repair(branch)
            score=_queue_rank(completed.instance,completed.solution)
            previews.append({
                "rank":ix,"state":completed,"queue_key":score,
                "contact_key":_contact_rank(
                    completed.solution,before,ix),
                "option_key":opt.key,
            })
            counters.candidates_previewed+=1
            if ix==1 and policy=="preview_guarded" and not score[0]:
                counters.fallback_on_queue_pass+=1
                break
        if policy=="preview_contact":
            picked=min(previews,key=lambda x:x["contact_key"])
        elif policy in ("preview_queue","preview_guarded"):
            picked=min(previews,key=lambda x:(
                x["queue_key"],x["rank"]))
        else:
            picked=previews[0]
        counters.selected_ranks[picked["rank"]]+=1
        if picked["rank"]>1:counters.chosen_rank_above_one+=1
        counters.original_full_repair_returned+=int(picked["rank"]==1)
        counters.queue_pass_wins[str(not picked["queue_key"][0])]+=1
        counters.total_extra_mechanism_wall_s+=perf_counter()-started
        if len(counters.examples)<8:
            counters.examples.append({
                "kind":kind,"last_task":tid,
                "available_options":len(options),
                "selected_rank":picked["rank"],
                "rank1_necessary_pass":not previews[0]["queue_key"][0],
                "winner_necessary_pass":not picked["queue_key"][0],
                "previewed":len(previews),
            })
        return picked["state"]

    return patched


def build_repair_operator_list(policy,counters:PreviewCounters):
    original=ops.make_repair_operators()
    result=[]
    for name,fn in original:
        if name=="cheapest_insertion_mec_repair":
            result.append((name,make_preview_repair(
                "cheapest",policy,counters)))
        elif name=="regret2_insertion_mec_repair":
            result.append((name,make_preview_repair(
                "regret2",policy,counters)))
        else:
            # Future original changes must not be silently hidden.
            raise RuntimeError("Unrecognized original ALNS repair slot "+name)
    assert len(result)==len(original)==2
    return result
