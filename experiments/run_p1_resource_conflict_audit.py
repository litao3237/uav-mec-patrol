"""P1 physical conflict and missed-candidate attribution on frozen S85-S88.

This is a *development-only* replay after the holdout was inspected.
No source D, official ESI-ALNS, objective, strict audit, or numerical
acceptance criterion is relaxed or modified. Top8 adds STRICT Stage1
calls beyond the frozen top3 ONLY to measure screening regret; never
use this as equal-budget algorithm improvement.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from atomic_batch_search import atomic_search
from progressive_bridge_core import PROFILES
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.elastic_diagnosis import (
    diagnose_elastic_resources,
)
from run_seven_methods import finalize


def certificate(instance, sol):
    q=queue_aware_feasibility_precheck(instance, sol,
                                      build_event_info(instance, sol))
    bad=[]
    for tid,lb in q.task_completion_lb_s.items():
        d=instance.tasks[tid]
        extra=lb-d.release_s-d.deadline_s
        if extra>1e-4:
            bad.append({
                "task":tid, "execution":sol.task_decisions[tid].mode.value,
                "optimistic_gap_s":float(extra),
            })
    bad.sort(key=lambda x:(-x["optimistic_gap_s"],x["task"]))
    return {
        "passed":q.feasible,
        "deadline_count":len(bad),
        "deadline_by_mode":dict(Counter(x["execution"] for x in bad)),
        "worst_tasks":bad[:8],
        "avg_delay_excess_s":max(0.,float(q.avg_delay_lb_s-instance.avg_delay_budget_s)),
        "cycle_excess_s":sum(max(0.,float(x-instance.cycle_s))
                             for x in q.return_time_lb_s.values()),
        "reasons":list(q.reasons[:8]),
    }


def _compact_diagnosis(x):
    return {
        k:x.get(k) for k in (
            "mode","status","solver","numerically_credible",
            "normalized_total_elastic_slack",
            "max_hard_normalized_residual",
            "max_elastic_normalized_residual",
            "diagnostic_build_and_solve_s",
        )
    }|{
        "slack_sum_by_family":x.get("slack_sum_by_family"),
        "top_constraints":(x.get("top_constraints") or [])[:6],
        "top_dependency_context":(x.get("top_dependency_context") or [])[:4],
        "attempts":(x.get("attempts") or [])[-2:],
    }


def _build_context(old, profile, seed, source_hash, candidate_results):
    prior=old["arms"]["atomic_offload_and_cross_uav_depth4"]
    prev_labels=prior["search_diagnostics"]["strict_shortlist_labels"]
    new_labels=[r["label"] for r in candidate_results[:3]]
    return {
        "prior_strict_recovered":prior["strict_both_recovered"],
        "prior_labels":prev_labels,
        "replay_labels":new_labels,
        "top3_exact_label_match":prev_labels==new_labels,
        "source_hash":source_hash,
    }


def run(source_path:Path, old_path:Path, output_path:Path):
    if output_path.exists():
        raise FileExistsError("Never overwrite original or partial evidence")
    raw=json.loads(source_path.read_text(encoding="utf-8"))
    previous=json.loads(old_path.read_text(encoding="utf-8"))
    proto=raw["protocol"]
    if (not raw.get("complete") or
            proto.get("id")!="uav_mec_one_factor_coupling_sensitivity_v1"):
        raise ValueError("Expected complete original B-ALNS source")
    if (not previous.get("complete") or previous["protocol"]["id"] !=
            "p1_atomic_coupled_MEC_dependency_repair_v1"):
        raise ValueError("Expected complete frozen original P1 holdout")
    scene=int(proto["independent_scenario_seed"])
    if scene not in (85,86,87,88) or scene!=previous["protocol"]["scenario"]:
        raise ValueError("S85-S88 frozen source mismatch")
    by_source={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    by_old={(r["profile"],int(r["seed"])):r for r in previous["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"p1_frozen_resource_conflict_attribution_v1",
            "scenario":scene,"original_run_id":38134649545,
            "frozen_source_sha256":content_hash(raw),
            "frozen_p1_sha256":content_hash(previous),
            "inspected_development_scenarios_only":True,
            "top8_diagnostic_not_equal_exact_budget":True,
            "max_queue_passed_stage1_checks_per_source":8,
            "candidate_shortlist_original_quota":3,
            "model":"unchanged_original_p1_r_with_explicit_elastic_diagnostic_only",
            "no_main_algorithm_changes":True,
            "qos_soft_groups":["deadline","avg_delay","cycle","battery"],
            "only_mec_capacity_soft_groups":["mec_cpu_cap","bandwidth_cap"],
        },
        "rows":[],"errors":[],
    }
    write_json(output_path,payload)
    for profile in PROFILES:
        snapshot=raw["profiles"][profile]
        instance=restore_instance(snapshot["instance"])
        if content_hash(instance)!=snapshot["instance_sha256"]:
            raise RuntimeError("Frozen instance hash mismatch: "+profile)
        for seed in (125,126):
            old=by_old[profile,seed]
            if not old["eligible"]:
                continue
            src=by_source[profile,seed,"B-ALNS"]
            if (((src.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status")!="infeasible_precheck"):
                raise RuntimeError("Archived Stage1 classification changed")
            sol=restore_solution(src["solution"])
            sha=content_hash(sol)
            if sha!=src["solution_sha256"] or sha!=old["source_solution_sha256"]:
                raise RuntimeError("Frozen discrete structure hash mismatch")
            row={
                "scenario":scene,"profile":profile,"seed":seed,
                "source_hash":sha,
                "source_queue_certificate":certificate(instance,sol),
                "source_original_stage1_status":"infeasible_precheck",
                "previous_strict_recovered":bool(old["arms"][
                    "atomic_offload_and_cross_uav_depth4"]["strict_both_recovered"]),
                "candidate_results":[],
                "diagnosed_indices":[],
                "error":None,
            }
            payload["rows"].append(row)
            write_json(output_path,payload)
            try:
                shortlist,meta=atomic_search(
                    instance,sol,include_atomic=True,include_cross_uav=True,
                    beam_width=2,depth=4,exact_limit=8,generation_cap_s=4.,
                    diagnostic_trace=True,
                )
                assert len(shortlist)<=8
                if content_hash(sol)!=sha:
                    raise RuntimeError("Search mutated frozen source")
                row["search_summary"]={k:v for k,v in meta.items()
                                       if k!="diagnostic_shortlist"}
                prior_labels=old["arms"][
                    "atomic_offload_and_cross_uav_depth4"][
                    "search_diagnostics"]["strict_shortlist_labels"]
                new_labels=[r["label"] for r in shortlist[:3]]
                row["original_top3_labels"]=prior_labels
                row["replay_top3_labels"]=new_labels
                row["frozen_shortlist_reproduced"]=prior_labels==new_labels
                if not row["frozen_shortlist_reproduced"]:
                    # No causal claim from a different shortlist. We still
                    # archive this visible run so timing drift is auditable.
                    row["replay_mismatch"]="Candidate labels differ from frozen P1"
                oracle=Stage1CVXObjectiveOracle()
                for rank,proposal in enumerate(shortlist,1):
                    saved=meta["diagnostic_shortlist"][rank-1]
                    if saved["node_hash"]!=content_hash(proposal["sol"]):
                        raise RuntimeError("Candidate identity mismatch")
                    result=oracle.solve(instance,proposal["sol"])
                    ok=bool(stage1_is_qualified(result))
                    d={
                        **saved,
                        "inside_original_three":rank<=3,
                        "has_atomic_ancestor":any(
                            x.startswith("bundle_") for x in saved["path"]),
                        "stage1_qualified":ok,
                        "stage1_solver_status":result.diagnostics.get("stage1_status"),
                        "stage1_energy_j":float(result.energy_stage1_j) if ok else None,
                        "stage2_complete_audit":None,
                    }
                    if rank>3 and ok:
                        complete=finalize(
                            instance,proposal["sol"],method="p1_diagnostic_only",
                            seed=None,initialization_s=0.,search_s=0.,
                            diagnostics={"origin":"post_original_top3_diagnostic",
                                         "candidate_hash":saved["node_hash"]},
                        )
                        d["stage2_complete_audit"]={
                            "stage1_qualified":bool(complete["stage1"]["qualified"]),
                            "stage2_qualified":bool(complete["stage2"]["qualified"]),
                            "strict_both_qualified":bool(
                                complete["stage1"]["qualified"] and
                                complete["stage2"]["qualified"]),
                        }
                    row["candidate_results"].append(d)
                    # Incremental evidence is important if a later conic
                    # diagnostic reaches an unexpected numerical state.
                    write_json(output_path,payload)
                if len(row["candidate_results"])!=oracle.calls:
                    raise RuntimeError("Oracle call-count mismatch")

                # Model-based attribution on the first rejected candidate,
                # plus a positive control if a Stage1 qualified candidate
                # exists. EXACT same model/constraint families for both.
                neg=next((i for i,r in enumerate(row["candidate_results"])
                          if not r["stage1_qualified"]),None)
                pos=next((i for i,r in enumerate(row["candidate_results"])
                          if r["stage1_qualified"]),None)
                targets=[]
                if neg is not None: targets.append(("negative",neg))
                if pos is not None: targets.append(("positive_control",pos))
                for kind,idx in targets:
                    row["diagnosed_indices"].append({"kind":kind,"index":idx+1})
                    modes=("qos_only","mec_capacity_only") if kind=="negative" else ("qos_only",)
                    q_record=row["candidate_results"][idx]
                    for mode in modes:
                        result=diagnose_elastic_resources(
                            instance,shortlist[idx]["sol"],mode=mode,
                        )
                        q_record.setdefault("elastic",{})[mode]=_compact_diagnosis(result)
                        write_json(output_path,payload)
                row["diagnosis_complete"]=True
                row["diagnosis_wall_s"]=sum(
                    v["diagnostic_build_and_solve_s"]
                    for rec in row["candidate_results"]
                    for v in rec.get("elastic",{}).values()
                    if v.get("diagnostic_build_and_solve_s") is not None)
                print("P1_RESOURCE_CASE="+json.dumps({
                    "s":scene,"p":profile,"seed":seed,
                    "queue_pass":meta["queue_passed"],
                    "original_labels_match":row["frozen_shortlist_reproduced"],
                    "stage1_checked":len(row["candidate_results"]),
                    "original_top3_stage1":sum(
                        r["stage1_qualified"] for r in row["candidate_results"][:3]),
                    "extra_stage1":sum(
                        r["stage1_qualified"] for r in row["candidate_results"][3:]),
                    "extra_strict_stage2":sum(
                        bool((r.get("stage2_complete_audit") or {}).get("strict_both_qualified"))
                        for r in row["candidate_results"][3:]),
                    "diagnosed":row["diagnosed_indices"],
                }),flush=True)
            except Exception as exc:
                err={"scenario":scene,"profile":profile,"seed":seed,
                     "error_type":type(exc).__name__,"message":str(exc)}
                payload["errors"].append(err)
                row["error"]=err
                print("P1_RESOURCE_ERROR="+json.dumps(err),flush=True)
            write_json(output_path,payload)

    payload["complete"]=True
    cases=payload["rows"]
    payload["summary"]={
        "eligible_sources":len(cases),
        "source_queue_deadline_local":sum(
            bool(r["source_queue_certificate"]["deadline_by_mode"].get("local"))
            for r in cases),
        "source_queue_deadline_offload":sum(
            bool(r["source_queue_certificate"]["deadline_by_mode"].get("offload"))
            for r in cases),
        "source_queue_average_budget_excess":sum(
            r["source_queue_certificate"]["avg_delay_excess_s"]>0 for r in cases),
        "source_queue_cycle_excess":sum(
            r["source_queue_certificate"]["cycle_excess_s"]>0 for r in cases),
        "frozen_top3_replayed":sum(
            r.get("frozen_shortlist_reproduced",False) for r in cases),
        "frozen_top3_mismatch":sum(
            not r.get("frozen_shortlist_reproduced",False) for r in cases),
        "positive_stage1_behind_quota":sum(
            r["stage1_qualified"] for case in cases
            for r in case["candidate_results"][3:]),
        "strict_stage2_behind_quota":sum(
            bool((r.get("stage2_complete_audit") or {}).get("strict_both_qualified"))
            for case in cases for r in case["candidate_results"][3:]),
        "credible_positive_qos_conflict":sum(
            bool(d.get("numerically_credible")) and
            (d.get("normalized_total_elastic_slack") or 0)>0.002
            for case in cases for r in case["candidate_results"]
            for d in [r.get("elastic",{}).get("qos_only",{})]
            if not r["stage1_qualified"]),
        "diagnostic_errors":len(payload["errors"]),
    }
    write_json(output_path,payload)
    print("P1_RESOURCE_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"],"errors":payload["errors"],
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"Resource attribution diagnostics errors: {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--previous",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.previous,a.output)
