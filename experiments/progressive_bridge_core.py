"""Bounded multi-stage repair of temporarily infeasible UAV-MEC structures.

Unlike the original depth-2 queue repair, this pilot tests a *distinct*
mechanism: retain alternative infeasible intermediates which reduce the
root bottleneck deadline even when their total queue bound gets worse.
An ablation uses identical moves, same depth/width and identical CVX quota
but the original global violation ranking instead.

ALL candidate families and fixed-D FIFO/EDF feasibility constraints are
inherited from the frozen queue-guided-repair experiment. New code only
controls how infeasible intermediate states are retained. The official
develop branch's ALNS acceptance and resource validation are unchanged.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from time import perf_counter

from run_queue_guided_repair import (
    new_move_candidates,
    strict_queue_repair,
    queue_gap,
)

from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from run_seven_methods import finalize


PROFILES = (
    "compute_x1p5", "compute_x2p0", "deadline_x0p9", "deadline_x0p8",
)
ARMS = (
    "queue_original_depth2",
    "queue_plain_depth4",
    "queue_bridge_depth4",
)


def _metric(instance, solution, *, root_task_ids):
    """Compute a certificate *vector*, not a misleading CVX objective value."""
    info = build_event_info(instance, solution)
    q = queue_aware_feasibility_precheck(instance, solution, info)
    gap_by_task = {
        task_id:max(
            0.0,
            q.task_completion_lb_s[task_id]
            - instance.tasks[task_id].release_s
            - instance.tasks[task_id].deadline_s,
        )
        for task_id in instance.tasks
    }
    cycle_over = sum(
        max(0.0, earliest - instance.cycle_s)
        for earliest in q.return_time_lb_s.values()
    )
    delay_over = max(0.0, q.avg_delay_lb_s - instance.avg_delay_budget_s)
    return {
        "passed":q.feasible,
        "n_reasons":len(q.reasons),
        "violated_task_count":sum(v>1e-6 for v in gap_by_task.values()),
        "sum_deadline_excess_s":sum(gap_by_task.values()),
        "worst_task_excess_s":max(gap_by_task.values(),default=0.0),
        "root_excess_s":sum(gap_by_task.get(t,0.0) for t in root_task_ids),
        "total_excess_s":sum(gap_by_task.values()) + cycle_over + delay_over,
        "route_distance_m":sum(info.route_distance_m.values()),
        "reason_examples":list(q.reasons[:3]),
    }


def _legacy_global_key(metric, label):
    return (
        not metric["passed"],
        metric["n_reasons"],
        metric["total_excess_s"],
        metric["route_distance_m"],
        label,
    )


def _move_family(label: str) -> str:
    if label.startswith("fifo_predecessor_reuse"):
        return "fifo_predecessor_reuse"
    if label.startswith("fifo_predecessor_new_contact"):
        return "fifo_predecessor_new_contact"
    if label.startswith("cross_uav_fifo_relocation"):
        return "cross_uav"
    if label.startswith("contact_relocate"):
        return "contact_relocate"
    if label.startswith("early_task"):
        return "early_task"
    if label.startswith("task_mode"):
        return "task_mode"
    return label.split("::")[0]


def _bridge_beam(layer, *, beam_width, initial_root_excess_s):
    """Keep good global moves AND credible temporary-infeasible bridges.

    The second beam member (when available) prioritizes reducing the original
    offender's queue delay and a different move family, subject to a bound on
    new total optimistic violation. This is *not* a new proof of feasibility.
    """
    if not layer:return [],{}
    ordered = sorted(layer,key=lambda row:_legacy_global_key(row["metric"],row["label"]))
    chosen = [ordered[0]]
    bridge_choices = 0
    search_diversity = 0
    first_family=_move_family(chosen[0]["label"])
    # A new violation is temporarily allowed; the head source deadline MUST
    # make progress unless no such move exists. Do not allow arbitrary
    # blow-ups or silently turn the queue bound into a feasible acceptance.
    source_root_scale=max(1.0,initial_root_excess_s)
    candidates = [
        row for row in layer if row["sig"] not in {c["sig"] for c in chosen}
        and (row["metric"]["root_excess_s"] <=
             initial_root_excess_s - min(0.05,0.001*source_root_scale))
        and row["metric"]["total_excess_s"] <= max(
            12.0, initial_root_excess_s*1.6+8.0
        )
    ]
    candidates.sort(key=lambda x:(
        x["metric"]["root_excess_s"],
        x["metric"]["worst_task_excess_s"],
        x["metric"]["total_excess_s"],
        x["metric"]["route_distance_m"],
        x["label"],
    ))
    for row in candidates:
        if len(chosen)>=beam_width:break
        if _move_family(row["label"])!=first_family:
            chosen.append(row)
            bridge_choices+=1
            search_diversity+=1
            break
    if len(chosen)<beam_width:
        for row in candidates:
            if row["sig"] not in {c["sig"] for c in chosen}:
                chosen.append(row)
                bridge_choices+=1
                break
    if len(chosen)<beam_width:
        for row in ordered:
            if row["sig"] not in {c["sig"] for c in chosen}:
                chosen.append(row)
                if _move_family(row["label"])!=first_family:
                    search_diversity+=1
            if len(chosen)>=beam_width:break
    return chosen,{
        "explicit_root_bridge_selections":bridge_choices,
        "different_move_family_beam_entries":search_diversity,
    }


def search_progressive(
    instance, source, *,
    policy,
    beam_width=2,
    depth=4,
    exact_limit=3,
    generation_cap_s=4.0,
):
    """Search fixed candidate families with at most depth passes and soft cap.

    Infeasible D are permitted in *the beam only*. Stage-1 is NEVER called
    on an optimistic queue-precheck-failing D, and the final accepted energy
    is always computed/independently audited by the original solver.
    """
    if policy not in ("plain_depth","bridge_depth"):
        raise ValueError(policy)
    if min(beam_width,depth,exact_limit)<=0 or generation_cap_s<=0:
        raise ValueError("Expected positive search limits")
    t0=perf_counter()
    root=queue_gap(instance,source)
    root_task_ids=[
        r["task_id"] for r in root["task_offenders"][:3]
    ]
    if not root_task_ids:
        # No explicit task deadline exceeds the optimistic bound; the
        # average delay / cycle may still be responsible.
        info=build_event_info(instance,source)
        q=queue_aware_feasibility_precheck(instance,source,info)
        root_task_ids=sorted(
            instance.tasks,
            key=lambda tid:q.task_completion_lb_s[tid]
                -instance.tasks[tid].deadline_s,
            reverse=True,
        )[:3]
    baseline=_metric(instance,source,root_task_ids=root_task_ids)
    beam=[{"label":"root","sol":deepcopy(source),"metric":baseline}]
    seen={solution_signature(source)}
    good={}
    counters=Counter()
    trace=[]
    generation_soft_overrun=False

    for turn in range(1,depth+1):
        if perf_counter()-t0 >= generation_cap_s:
            generation_soft_overrun=True
            break
        layer=[]
        for state in beam:
            if perf_counter()-t0 >= generation_cap_s:
                generation_soft_overrun=True
                break
            proposals=new_move_candidates(
                instance,state["sol"],
                mode="queue_dependency_joint",
                offenders=3,
            )
            counters["raw_generated"]+=len(proposals)
            for label,candidate in proposals:
                if perf_counter()-t0 >= generation_cap_s:
                    generation_soft_overrun=True
                    break
                sig=solution_signature(candidate)
                if sig in seen:
                    counters["already_seen"]+=1
                    continue
                seen.add(sig)
                metric=_metric(
                    instance,candidate,root_task_ids=root_task_ids,
                )
                counters["unique_generated"]+=1
                if metric["passed"]:
                    counters["queue_passed"]+=1
                if (metric["root_excess_s"]<
                    state["metric"]["root_excess_s"]-1e-5
                    and metric["total_excess_s"]>
                        state["metric"]["total_excess_s"]+1e-4):
                    counters["temporary_total_worsening_with_root_progress"]+=1
                row={
                    "sig":sig,
                    "label":label,
                    "sol":candidate,
                    "metric":metric,
                    "depth":turn,
                    "parent":state["label"],
                    "family":_move_family(label),
                }
                layer.append(row)
                if metric["passed"]:
                    good[sig]=row
            if generation_soft_overrun:break

        if not layer:
            break

        layer.sort(key=lambda row:_legacy_global_key(row["metric"],row["label"]))
        if policy=="bridge_depth":
            chosen,diversity=_bridge_beam(
                layer,
                beam_width=beam_width,
                initial_root_excess_s=baseline["root_excess_s"],
            )
        else:
            chosen=layer[:beam_width]
            diversity={}
        beam=[
            {"label":row["label"],"sol":row["sol"],"metric":row["metric"]}
            for row in chosen
        ]
        counters["beam_expanded_depths"]+=1
        counters["bridge_selected"]+=diversity.get(
            "explicit_root_bridge_selections",0,
        )
        trace.append({
            "depth":turn,
            "new_structures":len(layer),
            "precheck_passing_in_layer":sum(
                r["metric"]["passed"] for r in layer
            ),
            "min_queue_gap_s":layer[0]["metric"]["total_excess_s"],
            "beam_labels":[r["label"] for r in chosen],
            "beam_root_excess_s":[r["metric"]["root_excess_s"] for r in chosen],
            "beam_total_excess_s":[r["metric"]["total_excess_s"] for r in chosen],
            "bridge_diversity":diversity,
        })
    shortlist=sorted(
        good.values(),
        key=lambda row:_legacy_global_key(row["metric"],row["label"]),
    )[:exact_limit]
    return shortlist,{
        "policy":policy,
        "root_task_ids":root_task_ids,
        "original_queue":baseline,
        "unique_candidates":counters["unique_generated"],
        "precheck_passing":len(good),
        "candidate_worsen_then_root_improve":counters[
            "temporary_total_worsening_with_root_progress"
        ],
        "beam_diverse_selections":counters["bridge_selected"],
        "actual_depth":counters["beam_expanded_depths"],
        "generation_soft_overrun":generation_soft_overrun,
        "generation_wall_s":perf_counter()-t0,
        "trace":trace,
        "strict_shortlist":[x["label"] for x in shortlist],
    }


def run_progressive_arm(
    instance,source, *, arm,
    beam_width=2,depth=4,exact_limit=3,
    generation_cap_s=4.0,
):
    if arm not in ARMS[1:]:
        raise ValueError(arm)
    began=perf_counter()
    shortlist,stats=search_progressive(
        instance,source,
        policy=("plain_depth" if arm=="queue_plain_depth4"
                else "bridge_depth"),
        beam_width=beam_width,depth=depth,
        exact_limit=exact_limit,
        generation_cap_s=generation_cap_s,
    )
    oracle=Stage1CVXObjectiveOracle()
    good=[]
    candidate_records=[]
    for candidate in shortlist:
        label=candidate["label"]
        result=oracle.solve(instance,candidate["sol"])
        passed=stage1_is_qualified(result)
        candidate_records.append({
            "label":label,
            "family":candidate["family"],
            "depth":candidate["depth"],
            "stage1_qualified":passed,
            "solver_status":result.diagnostics.get("stage1_status"),
            "stage1_energy_j":(
                float(result.energy_stage1_j) if passed else None
            ),
        })
        if passed:
            good.append((float(result.energy_stage1_j),candidate))
    both=False
    final_energy=None
    final_status=None
    final_label=None
    if good:
        _,candidate=min(good,key=lambda x:x[0])
        final=finalize(
            instance,candidate["sol"],method=arm,seed=None,
            initialization_s=0.0,search_s=0.0,
            diagnostics={"repair_trace":stats},
        )
        both=bool(final["stage1"]["qualified"]
                  and final["stage2"]["qualified"])
        final_status=final["resources"].diagnostics.get("stage1_status")
        final_label=candidate["label"]
        if both:
            final_energy=float(final["resources"].energy_stage1_j)
    return {
        "arm":arm,
        "strict_both_recovered":both,
        "strict_energy_j":final_energy,
        "final_label":final_label,
        "final_stage1_status":final_status,
        "strict_stage1_qualified_candidates":len(good),
        "strict_stage1_oracle_calls":oracle.calls,
        "candidate_results":candidate_records,
        "search_diagnostics":stats,
        "search_generation_wall_s":stats["generation_wall_s"],
        "total_wall_s":perf_counter()-began,
        "strict_candidate_limit":exact_limit,
    }


def frozen_queue_depth2(instance,source,*,exact_limit=3):
    start=perf_counter()
    control=strict_queue_repair(
        instance,source,mode="queue_dependency_joint",
        beam_width=2,max_depth=2,exact_limit=exact_limit,
    )
    return {
        "arm":"queue_original_depth2",
        "strict_both_recovered":bool(control["strict_both_recovered"]),
        "strict_energy_j":control["recovery_energy_j"],
        "final_label":control.get("accepted_move"),
        "strict_stage1_qualified_candidates":len([
            x for x in control.get("cvx_records",[])
            if x.get("stage1_qualified")
        ]),
        "strict_stage1_oracle_calls":control.get("strict_cvx_calls",0),
        "search_diagnostics":{
            "precheck_passing":control.get("queue_precheck_passing",0),
            "unique_candidates":control.get("generated_unique",0),
            "actual_depth":len(control.get("search_trace",[])),
            "trace":control.get("search_trace",[]),
        },
        "total_wall_s":perf_counter()-start,
        "strict_candidate_limit":exact_limit,
    }
