"""P32 fast staged gate: protect queue/CPU-possible repaired D, avoid blanket DP.

This is an EXPERIMENT BRANCH only. Source ALNS cheapest/regret2/full
MEC builder executes exactly once per repair; original destroy/roulette/RRT/
screened proxy/elite CVX and final physical Stage1+Stage2 stay unchanged.

P31 first-use S135-S138 showed 1 new and 1 lost strict result for joint,
and its queue ablation had one new, zero lost. P32 was designed after those
observations and MUST be evaluated on disjoint first-use S139-S142 only.
Do not reinterpret S135-S138 as unseen if using those cases diagnostically.

Specific frozen change:
- If repaired D passes queue and station CPU necessary checks, return that
  D untouched. Passing those two necessary checks DOES NOT prove strict.
  This preservation gate cannot guarantee that a whole ALNS trajectory
  dominates a separately run original ALNS search.
- Otherwise select up to two P31 binding tasks and generate up to 24
  same legal UAV/alternate contact candidates with the original operator,
  no extra MEC greedy builder and no conic solves during candidate ranking.
- Screen all generated D with OPTIMISTIC queue and static CPU lower bounds.
  Only candidates PASSING BOTH may replace the repaired D.
- 'queue_guard' chooses shortest queue excess and route; 'cpu_guard'
  chooses lowest static CPU pressure with queue tie-break; 'joint_gate'
  runs the already-existing 16-bin optimistic joint BW/CPU bound for
  at most eight q+CPU-passing candidates drawn from cheap rank shortlists.
  Select only an actually joint-necessary-passing result. These are not
  strict Stage1 feasibility claims.
- 'sham_joint' performs the exact same joint candidates/diagnostics as
  joint_gate but returns the preexisting repair unchanged.
- 3 new non-sham enabled policies share a frozen generated physical D pool
  and identical cheap queue/CPU screening; intentionally different
  additional joint solver work is measured rather than called equal cost.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass,field
from functools import wraps
from time import perf_counter

from p31_binding_aware_repair import (
    P31Limits,binding_targets,legal_cross_uav,
)
from uav_mec.algorithms.alns import operators as ops
from uav_mec.evaluation import build_event_info
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

POLICIES=("sham_joint","queue_guard","cpu_guard","joint_gate")
LIMITS=P31Limits()
MAX_JOINT_SCREEN=8
MAX_PER_CHEAP_RANK=4


@dataclass
class P32Counters:
    policy:str
    calls:int=0
    legacy_full_builder_calls:int=0
    base_queue_and_cpu_pass_preserved:int=0
    eligible_interventions:int=0
    no_target:int=0
    no_cheap_eligible_candidate:int=0
    no_joint_eligible_candidate:int=0
    generated_candidates:int=0
    evaluated_candidates:int=0
    queue_cpu_eligible_candidates:int=0
    joint_bound_calls:int=0
    joint_pass_candidates:int=0
    chosen_other_D:int=0
    total_diagnostic_wall_s:float=0.
    examples:list=field(default_factory=list)
    discarded:Counter=field(default_factory=Counter)

    def snapshot(self):
        return {
            "policy":self.policy,
            "calls":self.calls,
            "legacy_full_builder_calls":self.legacy_full_builder_calls,
            "base_queue_and_cpu_pass_preserved":self.base_queue_and_cpu_pass_preserved,
            "eligible_interventions":self.eligible_interventions,
            "no_target":self.no_target,
            "no_cheap_eligible_candidate":self.no_cheap_eligible_candidate,
            "no_joint_eligible_candidate":self.no_joint_eligible_candidate,
            "generated_candidates":self.generated_candidates,
            "evaluated_candidates":self.evaluated_candidates,
            "queue_cpu_eligible_candidates":self.queue_cpu_eligible_candidates,
            "joint_bound_calls":self.joint_bound_calls,
            "joint_pass_candidates":self.joint_pass_candidates,
            "chosen_other_D":self.chosen_other_D,
            "total_diagnostic_wall_s":self.total_diagnostic_wall_s,
            "examples":self.examples[:8],
            "discarded":dict(self.discarded),
        }


def light_audit(instance,solution):
    """Original safe FIFO/EDF and static CPU necessary inequalities only."""
    info=build_event_info(instance,solution)
    queue=queue_aware_feasibility_precheck(instance,solution,info)
    bound=station_cpu_share_necessary_bound(
        instance,solution,info=info,queue=queue
    )
    excess=sum(
        max(0.,queue.task_completion_lb_s[tid]
            -task.release_s-task.deadline_s)/max(1.,task.deadline_s)
        for tid,task in instance.tasks.items()
    )
    excess+=max(0.,queue.avg_delay_lb_s-instance.avg_delay_budget_s)/max(
        1.,instance.avg_delay_budget_s
    )
    excess+=sum(
        max(0.,r-instance.cycle_s)/max(1.,instance.cycle_s)
        for r in queue.return_time_lb_s.values()
    )
    cpu_excess=sum(
        (a["excess_cpu_ghz_lb"] or 0.)/max(1.,instance.mecs[mid].cpu_ghz)
        for mid,a in bound["stations"].items()
    )
    pressure=max((
        a["min_cpu_pressure_ratio"] or 0.
        for a in bound["stations"].values()
    ),default=0.)
    return {
        "queue_pass":bool(queue.feasible),
        "queue_reason_count":len(queue.reasons),
        "queue_normalized_excess":excess,
        "cpu_bad":bool(bound["certified_cpu_share_failure"]),
        "cpu_excess_ratio":cpu_excess,
        "cpu_pressure_ratio":pressure,
        "route_m":sum(info.route_distance_m.values()),
        "info":info,
        "queue":queue,
        "cpu_bound":bound,
        "solution":solution,
    }


def eligible(row):
    return row["queue_pass"] and not row["cpu_bad"]


def cheap_key(a,policy):
    if policy=="queue":
        return (
            a["queue_normalized_excess"],
            a["route_m"],
            a["cpu_pressure_ratio"],
        )
    if policy=="cpu":
        return (
            a["cpu_pressure_ratio"],
            a["cpu_excess_ratio"],
            a["queue_normalized_excess"],
            a["route_m"],
        )
    raise ValueError(policy)


def joint_selection_shortlist(eligible_pool):
    """Deterministic union from identical cheap-screened D, <=8."""
    selected={}
    for rule in ("queue","cpu"):
        for row in sorted(eligible_pool,key=lambda v:(
            cheap_key(v["audit"],rule),v["label"]
        ))[:MAX_PER_CHEAP_RANK]:
            selected.setdefault(row["label"],row)
    return list(selected.values())[:MAX_JOINT_SCREEN]


def _joint(instance,row,counters,*,bins):
    q=row["audit"]["queue"]
    j=joint_station_bw_cpu_necessary_bound(
        instance,row["solution"],
        info=row["audit"]["info"],queue=q,n_bins=bins,
    )
    counters.joint_bound_calls+=1
    passed=bool(j["passes_joint_necessary_test"])
    if passed:counters.joint_pass_candidates+=1
    row["joint_necessary_pass"]=passed
    row["joint_static_cpu_excess_ratio"]=sum(
        (stat["oversubscription_cpu_ghz"] or 0.)/
        max(1.,instance.mecs[mid].cpu_ghz)
        for mid,stat in j["stations"].items()
    )
    return row


def refine_one(complete,policy,counters:P32Counters,limits=None):
    if policy not in POLICIES:raise ValueError(policy)
    limits=limits or LIMITS
    started=perf_counter()
    counters.calls+=1
    instance=complete.instance
    original=complete.solution
    base=light_audit(instance,original)

    # Conservative screen: any truly strict solution necessarily passes
    # both, so preserve this discrete D before side effects. This does NOT
    # guard strict feasible solutions on other ALNS trajectories.
    if eligible(base):
        counters.base_queue_and_cpu_pass_preserved+=1
        counters.total_diagnostic_wall_s+=perf_counter()-started
        return complete

    counters.eligible_interventions+=1
    targets=binding_targets(instance,base,limit=limits.targets)
    if not targets:
        counters.no_target+=1
        counters.total_diagnostic_wall_s+=perf_counter()-started
        return complete
    moves=legal_cross_uav(instance,original,targets,limits,counters)
    counters.generated_candidates+=len(moves)
    pool=[]
    for i,move in enumerate(moves):
        audit=light_audit(instance,move["solution"])
        counters.evaluated_candidates+=1
        if not eligible(audit):
            continue
        counters.queue_cpu_eligible_candidates+=1
        pool.append({
            "label":f'{i:04d}::{move["task"]}::{move["new_UAV"]}'
                    f'::{move["mode"]}::{move["position"]}::{move["contact"]}',
            "solution":move["solution"],
            "audit":audit,
            "task":move["task"],
            "new_UAV":move["new_UAV"],
            "mode":move["mode"],
        })
    if not pool:
        counters.no_cheap_eligible_candidate+=1
        counters.total_diagnostic_wall_s+=perf_counter()-started
        return complete

    if policy in ("joint_gate","sham_joint"):
        shortlist=joint_selection_shortlist(pool)
        qualified=[
            r for r in (
                _joint(instance,row,counters,bins=limits.joint_bw_cpu_bins)
                for row in shortlist
            ) if r["joint_necessary_pass"]
        ]
        if not qualified:
            counters.no_joint_eligible_candidate+=1
            counters.total_diagnostic_wall_s+=perf_counter()-started
            return complete
        chosen=min(qualified,key=lambda r:(
            r["joint_static_cpu_excess_ratio"],
            cheap_key(r["audit"],"queue"),
            r["label"],
        ))
    else:
        rank="queue" if policy=="queue_guard" else "cpu"
        chosen=min(pool,key=lambda r:(cheap_key(r["audit"],rank),r["label"]))

    if len(counters.examples)<8:
        counters.examples.append({
            "task":chosen["task"],
            "new_UAV":chosen["new_UAV"],
            "mode":chosen["mode"],
            "new_queue_pass":chosen["audit"]["queue_pass"],
            "new_cpu_certified_failure":chosen["audit"]["cpu_bad"],
            "joint_tested":policy in ("joint_gate","sham_joint"),
            "candidate_pool":len(moves),
            "cheap_eligible_pool":len(pool),
        })
    counters.total_diagnostic_wall_s+=perf_counter()-started
    if policy=="sham_joint":
        return complete
    repaired=complete.copy()
    repaired.solution=deepcopy(chosen["solution"])
    repaired.invalidate()
    validate_solution(instance,repaired.solution)
    counters.chosen_other_D+=1
    return repaired


def make_repair_list(policy,counters:P32Counters,limits=None):
    if policy not in POLICIES:raise ValueError(policy)
    result=[]
    existing=ops.make_repair_operators()
    for name,old_fn in existing:
        @wraps(old_fn)
        def wrapped(destroyed,rng,old_fn=old_fn):
            fully_repaired=old_fn(destroyed,rng)
            counters.legacy_full_builder_calls+=1
            return refine_one(fully_repaired,policy,counters,limits)
        result.append((name,wrapped))
    if [x[0] for x in result]!=[x[0] for x in existing]:
        raise RuntimeError("P32 changed original operator names")
    return result
