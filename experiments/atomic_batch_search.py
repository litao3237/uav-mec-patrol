"""Controlled atomic-bundle ablation atop frozen queue dependence repair.

The plain4 baseline and atomic4 arms use the exact SAME ranking policy,
beam width, depth, capped queue-candidate enumeration CPU time, and at most
three Stage-1 CVX candidate checks. The only difference is the presence
of atomic 2-task MEC batch/contact and optional two-task cross-UAV moves.

The original queue2 comparator is reported for context but is NOT same-depth.
This remains selected conditional rescue, not a complete ESI-ALNS benchmark.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from time import perf_counter

from atomic_batch_moves import atomic_batch_moves
from progressive_bridge_core import (
    _metric, _legacy_global_key, run_progressive_arm, frozen_queue_depth2,
)
from run_queue_guided_repair import new_move_candidates,queue_gap
from run_seven_methods import finalize
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


ARMS=(
    "queue_original_depth2",
    "queue_plain_depth4",
    "atomic_offload_depth4",
    "atomic_offload_and_cross_uav_depth4",
)


def atomic_search(instance, source, *, include_atomic,
                  include_cross_uav=False, beam_width=2, depth=4,
                  exact_limit=3, generation_cap_s=4.0):
    if include_cross_uav and not include_atomic:
        raise ValueError("Cross-UAV atomic moves require atomic candidate arm")
    if min(beam_width,depth,exact_limit)<=0 or generation_cap_s<=0:
        raise ValueError("Positive limits are required")
    t0=perf_counter()
    root=queue_gap(instance,source)
    root_ids=[
        d["task_id"] for d in root["task_offenders"][:3]
    ]
    if not root_ids:
        # The exact comparator chooses the three greatest optimistic
        # deadline gaps when no positive task-only deadline violations exist.
        ev=queue_aware_feasibility_precheck(
            instance,source,build_event_info(instance,source),
        )
        root_ids=sorted(
            instance.tasks,
            key=lambda t:ev.task_completion_lb_s[t]-instance.tasks[t].deadline_s,
            reverse=True,
        )[:3]
    original_metric=_metric(instance,source,root_task_ids=root_ids)
    beam=[{"label":"root","sol":deepcopy(source),"metric":original_metric}]
    unique_seen={solution_signature(source)}
    viable={}
    counters=Counter()
    trace=[]
    exceeded=False

    for turn in range(1,depth+1):
        if perf_counter()-t0>=generation_cap_s:
            exceeded=True
            break
        layer=[]
        for item in beam:
            if perf_counter()-t0>=generation_cap_s:
                exceeded=True
                break
            proposals=list(new_move_candidates(
                instance,item["sol"],mode="queue_dependency_joint",offenders=3,
            ))
            counters["legacy_raw"]+=len(proposals)
            if include_atomic and perf_counter()-t0<generation_cap_s:
                bundle,stats=atomic_batch_moves(
                    instance,item["sol"],
                    include_cross_uav=include_cross_uav,
                )
                proposals+=bundle
                counters["atomic_raw"]+=stats["unique_valid_candidates"]
                for fam,n in stats["families"].items():
                    counters[f"generated_{fam}"]+=n
            for label,candidate in proposals:
                if perf_counter()-t0>=generation_cap_s:
                    exceeded=True
                    break
                sig=solution_signature(candidate)
                if sig in unique_seen:
                    counters["already_seen"]+=1
                    continue
                unique_seen.add(sig)
                metric=_metric(instance,candidate,root_task_ids=root_ids)
                counters["unique_generated"]+=1
                if metric["passed"]:
                    counters["queue_passed"]+=1
                row={
                    "label":label,"sol":candidate,"sig":sig,
                    "metric":metric,"depth":turn,
                    "parent":item["label"],
                    "family":label.split("::")[0],
                }
                layer.append(row)
                if metric["passed"]:
                    viable[sig]=row
            if exceeded:
                break
        if not layer:
            break
        layer.sort(
            key=lambda row:_legacy_global_key(row["metric"],row["label"]),
        )
        chosen=layer[:beam_width]
        beam=[{
            "label":r["label"],"sol":r["sol"],"metric":r["metric"],
        } for r in chosen]
        trace.append({
            "depth":turn,
            "new_unique":len(layer),
            "queue_pass":sum(r["metric"]["passed"] for r in layer),
            "beam_labels":[r["label"] for r in chosen],
            "best_queue_gap_s":layer[0]["metric"]["total_excess_s"],
        })
        counters["depth_steps"]+=1

    ordered=sorted(
        viable.values(),
        key=lambda row:_legacy_global_key(row["metric"],row["label"]),
    )
    shortlist=ordered[:exact_limit]
    return shortlist,{
        "include_atomic":include_atomic,
        "include_cross_uav":include_cross_uav,
        "source_queue_excess_s":original_metric["total_excess_s"],
        "unique_generated":counters["unique_generated"],
        "legacy_raw":counters["legacy_raw"],
        "atomic_raw":counters["atomic_raw"],
        "atomic_family_counts":{
            fam:counters[f"generated_{fam}"]
            for fam in (
                "bundle_reuse_contact","bundle_new_contact",
                "bundle_early_split","bundle_cross_uav",
            )
        },
        "queue_passed":len(viable),
        "beam_depth_reached":counters["depth_steps"],
        "soft_generation_overrun":exceeded,
        "generation_wall_s":perf_counter()-t0,
        "strict_shortlist_labels":[r["label"] for r in shortlist],
        "strict_shortlist_depth":[r["depth"] for r in shortlist],
        "trace":trace,
    }


def run_atomic_arm(instance,source,*,arm,beam_width=2,depth=4,
                   exact_limit=3,generation_cap_s=4.0):
    if arm not in ARMS[2:]:
        raise ValueError(arm)
    started=perf_counter()
    shortlist,stats=atomic_search(
        instance,source,include_atomic=True,
        include_cross_uav=arm=="atomic_offload_and_cross_uav_depth4",
        beam_width=beam_width,depth=depth,
        exact_limit=exact_limit,generation_cap_s=generation_cap_s,
    )
    oracle=Stage1CVXObjectiveOracle()
    good=[]
    evaluated=[]
    for rank,proposal in enumerate(shortlist,1):
        res=oracle.solve(instance,proposal["sol"])
        qualified=stage1_is_qualified(res)
        evaluated.append({
            "rank":rank,
            "label":proposal["label"],
            "family":proposal["family"],
            "depth":proposal["depth"],
            "strict_stage1_qualified":qualified,
            "stage1_solver_status":res.diagnostics.get("stage1_status"),
            "stage1_energy_j":float(res.energy_stage1_j) if qualified else None,
        })
        if qualified:
            good.append((float(res.energy_stage1_j),proposal))
    strict=False
    strict_energy=None
    final_label=None
    failure_reason=None
    if good:
        for _,candidate in sorted(good,key=lambda pair:pair[0]):
            # A stage1-optimal low-energy solution could still fail the
            # independent Stage2 audit. Continue through already-confirmed
            # Stage1 options without additional candidate oracle calls.
            full=finalize(
                instance,candidate["sol"],method=arm,seed=None,
                initialization_s=0.0,search_s=0.0,
                diagnostics={"strict_candidate":candidate["label"]},
            )
            accepted=bool(
                full["stage1"]["qualified"] and full["stage2"]["qualified"]
            )
            if accepted:
                strict=True
                strict_energy=float(full["resources"].energy_stage1_j)
                final_label=candidate["label"]
                break
            failure_reason={
                "stage1_qualified":bool(full["stage1"]["qualified"]),
                "stage2_qualified":bool(full["stage2"]["qualified"]),
                "stage1_status":full["resources"].diagnostics.get("stage1_status"),
                "stage2_status":full["resources"].diagnostics.get("stage2_status"),
            }
    return {
        "arm":arm,
        "strict_both_recovered":strict,
        "strict_energy_j":strict_energy,
        "final_label":final_label,
        "strict_stage1_qualified_candidates":len(good),
        "strict_stage1_oracle_calls":oracle.calls,
        "strict_candidate_limit":exact_limit,
        "candidate_results":evaluated,
        "final_failed_audits":failure_reason,
        "search_diagnostics":stats,
        "total_wall_s":perf_counter()-started,
    }


def run_control_arm(instance,source,*,arm,beam_width=2,depth=4,
                    exact_limit=3,generation_cap_s=4.0):
    if arm=="queue_original_depth2":
        return frozen_queue_depth2(instance,source,exact_limit=exact_limit)
    if arm!="queue_plain_depth4":
        raise ValueError(arm)
    return run_progressive_arm(
        instance,source,arm="queue_plain_depth4",
        beam_width=beam_width,depth=depth,
        exact_limit=exact_limit,generation_cap_s=generation_cap_s,
    )
