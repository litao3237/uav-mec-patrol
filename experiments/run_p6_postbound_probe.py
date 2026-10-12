"""P6 post-bound structure rescue: same frozen first-generation beam.

This is a CONDITIONAL, development-only experiment using S93-S96 AFTER
P5 first-use independent evaluation; thus the current four scenarios
are NO LONGER unseen for P6. All methods start from the same original
precheck-infeasible B-ALNS D, same 100-iteration source checkpoint and
identical atomic beam candidate pool (width2, depth4, soft cap4s).

Arms:
  p5_joint48: frozen P5 necessary-gate control;
  postbound_workload: same post-gate action families but choose heavy
    offloaded tasks from the overloaded MEC instead of binding tasks;
  postbound_certificate_no_batch: same model-target policy, do not move
    whole contact batches as a unit;
  postbound_certificate_full: model-target binding tasks with entire
    contact batch MEC move included.

Target repairs are constructed ONLY from optimistic queue-passing states
that have failed the *joint* necessary BW/CPU check. All arms preserve
at most 3 strict Stage1 exact calls, unchanged Stage1+Stage2
residual verification and actual wall-clock-inclusive costs. Source
search is prepaid, so NOT a full-ALNS matched-end-to-end comparison.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from atomic_batch_search import atomic_search
from postbound_conflict_moves import postbound_conflict_moves
from progressive_bridge_core import PROFILES, _metric, _legacy_global_key
from run_p3_cpu_certificate_probe import _strict_check, _root_task_ids
from run_p5_joint_screening_probe import choose
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

ARMS=("p5_joint48","postbound_workload",
      "postbound_certificate_no_batch","postbound_certificate_full")
SOURCE_SCENES=(89,90,91,92,93,94,95,96)


def _eval_safe_bound(instance,solution):
    info=build_event_info(instance,solution)
    q=queue_aware_feasibility_precheck(instance,solution,info)
    if not q.feasible:
        return "queue_rejected",None
    cpu=station_cpu_share_necessary_bound(
        instance,solution,info=info,queue=q)
    if cpu["certified_cpu_share_failure"]:
        return "static_cpu_rejected",None
    joint=joint_station_bw_cpu_necessary_bound(
        instance,solution,info=info,queue=q,n_bins=48)
    if joint["joint_necessary_reject"]:
        return "joint_rejected",joint
    return "joint_necessary_pass",joint


def postbound_search(instance,original_queue_candidates,*,policy,
                     include_whole_batch,source,
                     original_selected,
                     postbound_soft_cap_s=3.0,
                     seed_limit=4,
                     max_total_move_evals=100):
    if policy not in ("certificate","workload"):
        raise ValueError(policy)
    if postbound_soft_cap_s<=0 or seed_limit<=0 or max_total_move_evals<=0:
        raise ValueError("Invalid post-bound search caps")
    begin=perf_counter()
    root_tasks=_root_task_ids(instance,source)
    selected=list(original_selected)
    seen={solution_signature(r["sol"]) for r in original_queue_candidates}
    passing_extra={}
    counters=Counter()
    seeds=[]
    for base in original_queue_candidates:
        if len(seeds)>=seed_limit:break
        if perf_counter()-begin>=postbound_soft_cap_s:break
        state,cert=_eval_safe_bound(instance,base["sol"])
        counters["base_candidates_scanned"]+=1
        if state in ("static_cpu_rejected","joint_rejected"):
            # Static-only rejection must ALSO violate the joint necessary
            # check; the joint bound is the more targeted witness.
            if cert is None:
                cert=joint_station_bw_cpu_necessary_bound(
                    instance,base["sol"],n_bins=48)
            if cert["joint_necessary_reject"]:
                seeds.append((base,cert))
                counters["failed_joint_seeds"]+=1
    explanation=[]
    for base,cert in seeds:
        if perf_counter()-begin>=postbound_soft_cap_s:break
        generated,diagnosis=postbound_conflict_moves(
            instance,base["sol"],policy=policy,
            target_limit=2,point_variants=2,joint_bound=cert)
        counters["generated_structural"]+=len(generated)
        if len(explanation)<4:
            explanation.append({
                "failed_parent":base["label"],
                "station":diagnosis.get("station"),
                "cpu_excess":diagnosis.get("bound_oversubscription_cpu_ghz"),
                "selected_targets":diagnosis.get("selected_targets",[]),
                "families":diagnosis["families"],
            })
        for label,candidate in generated:
            if perf_counter()-begin>=postbound_soft_cap_s:
                counters["generation_soft_timeout"]+=1
                break
            if counters["unique_checked"]>=max_total_move_evals:
                counters["move_eval_limit_hit"]+=1
                break
            if not include_whole_batch and label.startswith("p6_whole_batch_mec"):
                counters["whole_batch_ablation_skipped"]+=1
                continue
            sig=solution_signature(candidate)
            if sig in seen:
                counters["duplicate"]+=1
                continue
            seen.add(sig)
            counters["unique_checked"]+=1
            reason,_=_eval_safe_bound(instance,candidate)
            counters[reason]+=1
            if reason=="joint_necessary_pass":
                metric=_metric(instance,candidate,root_task_ids=root_tasks)
                if not metric["passed"]:
                    raise RuntimeError("Joint-admitted candidate failed queue certificate")
                passing_extra[sig]={
                    "label":label,"sol":candidate,"metric":metric,
                    "family":label.split("::")[0],
                    "from_parent":base["label"],
                }
        if counters["move_eval_limit_hit"] or counters["generation_soft_timeout"]:
            break
    # Keep original strict-admissible candidates ahead of all experimental
    # rescue paths: this prevents the extra neighborhood from simply
    # crowding out a proven pre-existing opportunity.
    ordered=sorted(passing_extra.values(),
                   key=lambda r:_legacy_global_key(r["metric"],r["label"]))
    if len(selected)<3:
        selected.extend(ordered[:3-len(selected)])
    return selected,{
        "policy":policy,"include_whole_batch":include_whole_batch,
        "generated_failure_seeds":len(seeds),
        "new_joint_necessary_passing":len(passing_extra),
        "counters":dict(counters),
        "target_examples":explanation,
        "postbound_wall_s":perf_counter()-begin,
        "extra_repair_labels":[r["label"] for r in ordered[:6]],
        "strict_shortlist_labels":[r["label"] for r in selected],
    }


def evaluate_source(instance,source):
    source_hash=content_hash(source)
    started=perf_counter()
    all_queue,raw=atomic_search(
        instance,source,include_atomic=True,include_cross_uav=True,
        beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.,
    )
    generation_wall_s=perf_counter()-started
    original_selection,old_gate=choose(
        instance,all_queue,arm="joint_bw_cpu_48",max_exact_checks=3)
    common_gate_wall=old_gate["gate_wall_s"]
    arms={}
    for arm in ARMS:
        if arm=="p5_joint48":
            shortlist=list(original_selection)
            extra={
                "postbound_wall_s":0.,
                "new_joint_necessary_passing":0,
                "strict_shortlist_labels":[r["label"] for r in shortlist],
            }
        else:
            shortlist,extra=postbound_search(
                instance,all_queue,
                policy=("workload" if arm=="postbound_workload" else
                        "certificate"),
                include_whole_batch=arm!="postbound_certificate_no_batch",
                source=source,original_selected=original_selection,
            )
        strict=_strict_check(
            instance,shortlist,arm="P6_"+arm)
        if strict["oracle_calls"]>3:
            raise RuntimeError("P6 exceeded unchanged strict Stage1 quota")
        arms[arm]={
            "arm":arm,
            "selected_labels":[r["label"] for r in shortlist],
            "queue_candidates_shared":len(all_queue),
            "common_generation_wall_s":generation_wall_s,
            "common_joint_gate_wall_s":common_gate_wall,
            "old_joint_gate":{
                "static_rejected":old_gate.get("static_rejected",0),
                "joint_extra_rejected":old_gate.get("joint_extra_rejected",0),
            },
            "extra_search":extra,
            **strict,
            "full_conditional_repair_wall_s":(
                generation_wall_s+common_gate_wall+
                extra["postbound_wall_s"]+strict["strict_eval_wall_s"]),
        }
    if content_hash(source)!=source_hash:
        raise RuntimeError("P6 mutated original frozen source D")
    return arms


def run(source_file:Path,output_file:Path):
    if output_file.exists():
        raise FileExistsError("Do not overwrite previous development evidence")
    raw=json.loads(source_file.read_text(encoding="utf-8"))
    p=raw["protocol"]
    scene=int(p["independent_scenario_seed"])
    if not raw.get("complete") or p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Expect complete original B/ESI physical source")
    if scene not in SOURCE_SCENES:
        raise ValueError("Only formerly inspected S89-S96 in P6 pilot")
    idx={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    out={
        "complete":False,
        "protocol":{
            "id":"P6_post_joint_screen_targeted_structural_repair_dev_v1",
            "scenario":scene,"original_source_sha256":content_hash(raw),
            "all_scenarios_previously_seen_in_P3_or_P5":True,
            "same_base_atomic_cross_uav_candidate_pool":True,
            "targeted_only_after_old_queue_and_joint_DP_failure":True,
            "P5_48grid_joint_bound_unchanged":True,
            "strict_stage1_CVX_quota_3":True,
            "independent_stage1_stage2_numerical_audit_unchanged":True,
            "candidate_generation_soft_cap_s":4.,
            "postbound_soft_cap_s":3.,
            "postbound_source_seed_limit":4,
            "postbound_max_move_evaluations":100,
            "same_four_move_families_for_certificate_and_workload_control":True,
            "source_original_ALNS_time_prepaid":True,
            "not_full_equal_walltime_B_ALNS_ESI_comparison":True,
            "arms":list(ARMS),
        },
        "rows":[],"errors":[],
    }
    write_json(output_file,out)
    seeds=list(p["algorithm_seeds"])
    for profile in PROFILES:
        entry=raw["profiles"][profile]
        instance=restore_instance(entry["instance"])
        if content_hash(instance)!=entry["instance_sha256"]:
            raise RuntimeError("Physical pressure scenario checksum mismatch")
        for seed in seeds:
            original=idx[profile,seed,"B-ALNS"]
            original_status=(
                ((original.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status"))
            row={
                "scenario":scene,"profile":profile,"seed":seed,
                "original_stage1_status":original_status,
                "original_source_sha256":original.get("solution_sha256"),
                "eligible":original_status=="infeasible_precheck",
                "arms":{},
            }
            out["rows"].append(row)
            write_json(output_file,out)
            if not row["eligible"]:continue
            try:
                sol=restore_solution(original["solution"])
                if content_hash(sol)!=row["original_source_sha256"]:
                    raise RuntimeError("Frozen B source D changed")
                row["arms"]=evaluate_source(instance,sol)
                print("P6_POSTBOUND_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,
                    "strict":{name:r["strict_both_recovered"]
                              for name,r in row["arms"].items()},
                    "cvx":{name:r["oracle_calls"]
                           for name,r in row["arms"].items()},
                    "new_joint_admissible":{
                        name:r["extra_search"]["new_joint_necessary_passing"]
                        for name,r in row["arms"].items()},
                },ensure_ascii=False),flush=True)
            except Exception as exc:
                error={
                    "scene":scene,"profile":profile,"seed":seed,
                    "type":type(exc).__name__,"message":str(exc),
                }
                row["error"]=error
                out["errors"].append(error)
                print("P6_POSTBOUND_ERROR="+json.dumps(error),flush=True)
            write_json(output_file,out)
    out["complete"]=True
    eligible=[r for r in out["rows"] if r["eligible"]]
    out["summary"]={
        "source_attempts":len(out["rows"]),
        "original_precheck_failed":len(eligible),
        "strict_recovery":{
            a:sum(r["arms"].get(a,{}).get("strict_both_recovered",False)
                  for r in eligible) for a in ARMS},
        "stage1_CVX_calls":{
            a:sum(r["arms"].get(a,{}).get("oracle_calls",0)
                  for r in eligible) for a in ARMS},
        "extra_joint_passing":{
            a:sum(r["arms"].get(a,{}).get("extra_search",{}).get(
                "new_joint_necessary_passing",0)
                for r in eligible) for a in ARMS},
        "exceptions":len(out["errors"]),
    }
    write_json(output_file,out)
    print("P6_POSTBOUND_SUMMARY="+json.dumps({
        "scene":scene,**out["summary"],
    },ensure_ascii=False),flush=True)
    if out["errors"]:
        raise RuntimeError(f"Undiagnosed P6 program errors {out['errors'][:2]}")
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.output)
