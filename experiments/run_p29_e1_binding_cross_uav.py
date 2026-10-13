"""P29 E1 binding-pair cross-UAV task relocation, unchanged original MEC.

Fix the frozen P22 critical-swap D (SHA-verified). Diagnose original
(UAV,E1) static-pair CPU binding tasks and FIFO predecessor batches.
Compare bound-chain targets to load-only and seeded random E1 targets.
For each target, transplant it to another UAV at exactly the same original
insertion-option positions in two legal variants: local execution or reuse
an already-existing downstream E2 contact. Do NOT invoke a greedy global
MEC reconstruction, alter physics, or accept optimistic bound passes as strict.

The three selection policies use the same generated candidates within
each target group: joint BW+CPU necessary, static CPU LB, queue only.
Select <=6 for original posthoc Stage1+Stage2 per group/policy. This is
a causal development probe on previously seen scenes, not a new ALNS
or a same-wall-time algorithm comparison.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from run_p12_insertion_finish_audit import _strict_numerical_check, queue_metrics
from run_p22_deadline_cross_uav_exchange import one_cross_uav_exchange, owner_map
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState, operators as ops
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
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

SCENE_CASES = {(91,"compute_x1p5",128), (93,"baseline",129)}
TARGET_GROUPS = ("binding_chain_E1", "heavy_E1", "random_E1")
RANKS = ("joint_bw_cpu", "static_cpu", "queue_only")
TASKS_PER_GROUP = 6
POSITIONS_PER_DESTINATION = 3
STRICT_CHECKS_PER_RANK = 6
JOINT_BINS = 24


def task_groups(instance, solution, seed):
    info=build_event_info(instance,solution)
    q=queue_aware_feasibility_precheck(instance,solution,info)
    bound=station_cpu_share_necessary_bound(instance,solution,info=info,queue=q)
    E1_pairs=[
        (key,p) for key,p in bound["pair_demands"].items()
        if p["station_id"] == "E1"
    ]
    E1_pairs.sort(key=lambda x:(
        -(x[1]["needed_cpu_ghz_lb"] or 0.), x[0]
    ))
    chain=[]
    for key,p in E1_pairs:
        binding=p["deadline_binding"]
        if not binding:continue
        uid,mid=p["pair"]
        visit_order=[
            vid for vid in info.contact_order[uid]
            if visit_mec_id(instance,solution,vid)==mid
        ]
        prefix=[]
        for vid in visit_order:
            for tid in info.batch_edf_order[vid]:
                prefix.append(tid)
                if tid==binding["task_id"]:
                    break
            if vid==binding["visit_id"]:
                break
        candidates=[binding["task_id"]]+sorted(
            (t for t in prefix if t!=binding["task_id"]),
            key=lambda tid:(-instance.tasks[tid].workload_gcycles,tid)
        )[:2]
        for tid in candidates:
            if tid not in chain:chain.append(tid)
    all_E1=sorted({
        tid for vid,tasks in info.batch_tasks.items()
        if visit_mec_id(instance,solution,vid)=="E1"
        for tid in tasks
    })
    if not chain or not all_E1:raise RuntimeError("No E1 queue binding tasks")
    chain=chain[:min(TASKS_PER_GROUP,len(all_E1))]
    target_n=len(chain)
    heavy=sorted(all_E1,key=lambda tid:(
        -instance.tasks[tid].workload_gcycles,tid))[:target_n]
    rng=np.random.default_rng(seed+292900)
    random_ids=rng.choice(all_E1,size=target_n,replace=False).tolist()
    return {
        TARGET_GROUPS[0]:chain,
        TARGET_GROUPS[1]:heavy,
        TARGET_GROUPS[2]:random_ids,
    }, {
        "E1_station_capacity_GHz":instance.mecs["E1"].cpu_ghz,
        "optimistic_E1_required_GHz":bound["stations"]["E1"]["required_cpu_lb_ghz"],
        "source_queue_necessary_pass":q.feasible,
        "binding_E1_pairs":[{
            "pair":key,"offloaded_task_count":p["n_offloaded_tasks"],
            "needed_static_CPU_GHz_lb":p["needed_cpu_ghz_lb"],
            "binding":p["deadline_binding"],
        } for key,p in E1_pairs],
        "E1_offload_tasks_all":all_E1,
    }


def _candidate_records(instance,source,targets):
    """Generate legal cross-UAV routes with local or existing E2 reuse."""
    original_sha=content_hash(source)
    before=owner_map(source)
    rows=[]
    D_seen={original_sha}
    skipped=Counter()
    for tid in targets:
        source_owner=before[tid]
        base=UavMecState(
            instance,deepcopy(source),ScreenedProxyObjectiveEvaluator()
        )
        damaged=ops._destroy_tasks(base,[tid])
        opts=ops._options_for_task(damaged,tid)
        by_destination={}
        for option in opts:
            if option.uav_id==source_owner:continue
            by_destination.setdefault(option.uav_id,[]).append(option)
        for dest,available in sorted(by_destination.items()):
            subset=list(available[:POSITIONS_PER_DESTINATION])
            earliest=min(available,key=lambda x:(x.position,x.key))
            if earliest not in subset:subset.append(earliest)
            for opt in subset:
                moved=damaged.copy()
                ops._apply_local_insertion(moved,tid,opt)
                baseline=moved.solution
                task_idx=next(
                    i for i,stop in enumerate(baseline.routes[dest].stops)
                    if stop.kind is StopType.TASK and stop.ref_id==tid
                )
                choices=[("local",None)]
                for i,stop in enumerate(baseline.routes[dest].stops):
                    if (i<=task_idx or stop.kind is not StopType.CONTACT):
                        continue
                    if visit_mec_id(instance,baseline,stop.ref_id)=="E2":
                        choices.append(("existing_E2",stop.ref_id))
                # At most first two downstream contact choices in that UAV.
                choices=choices[:3]
                for kind,visit in choices:
                    alt=deepcopy(baseline)
                    if visit:
                        alt.task_decisions[tid]=TaskDecision.offload(visit)
                    try:
                        validate_solution(instance,alt)
                        sha=content_hash(alt)
                        if sha in D_seen:
                            skipped["duplicate"]=skipped.get("duplicate",0)+1
                            continue
                        D_seen.add(sha)
                        rows.append({
                            "target_task":tid,
                            "from_UAV":source_owner,
                            "to_UAV":dest,
                            "to_execution":kind,
                            "existing_E2_visit":visit,
                            "original_insertion_key":list(opt.key),
                            "insertion_pos":opt.position,
                            "physical_D_SHA":sha,
                            "D":alt,
                        })
                    except (ValueError,KeyError) as exc:
                        skipped[type(exc).__name__]+=1
    if content_hash(source)!=original_sha:
        raise RuntimeError("P29 original source mutated")
    return rows,dict(skipped)


def _read_only(instance,candidate):
    info=build_event_info(instance,candidate)
    queue=queue_metrics(instance,candidate)
    bound=station_cpu_share_necessary_bound(instance,candidate,info=info)
    pressure=bound["stations"]["E1"]
    joint={"evaluated":False,"passes_joint_necessary_test":False,
           "E1_joint_cpu_oversubscription_ghz":None}
    if queue["queue_necessary_pass"] and not bound["certified_cpu_share_failure"]:
        estimate=joint_station_bw_cpu_necessary_bound(
            instance,candidate,info=info,n_bins=JOINT_BINS
        )
        joint={
            "evaluated":True,
            "passes_joint_necessary_test":estimate["passes_joint_necessary_test"],
            "E1_joint_cpu_oversubscription_ghz":estimate["stations"]["E1"][
                "oversubscription_cpu_ghz"],
        }
    return {
        "queue":queue,
        "CPU_share": {
            "certified_failure":bound["certified_cpu_share_failure"],
            "E1_required_cpu_lb":pressure["required_cpu_lb_ghz"],
            "E1_CPU_ratio_lb":pressure["min_cpu_pressure_ratio"],
            "E1_excess_lb_GHz":pressure["excess_cpu_ghz_lb"],
        },
        "joint":joint,
    }


def _rank(candidate,method):
    v=candidate["read_only"]
    q=v["queue"]
    cpu=v["CPU_share"]
    joint=v["joint"]
    common=(
        not q["queue_necessary_pass"],
        q["queue_reason_count"]
    )
    if method=="joint_bw_cpu":
        return common+(
            not joint["passes_joint_necessary_test"],
            cpu["certified_failure"],
            float("inf") if joint["E1_joint_cpu_oversubscription_ghz"] is None
            else joint["E1_joint_cpu_oversubscription_ghz"],
            q["total_normalized_all_constraint_excess"],
            candidate["physical_D_SHA"],
        )
    if method=="static_cpu":
        return common+(
            cpu["certified_failure"],
            float("inf") if cpu["E1_excess_lb_GHz"] is None
            else cpu["E1_excess_lb_GHz"],
            q["total_normalized_all_constraint_excess"],
            candidate["physical_D_SHA"],
        )
    if method=="queue_only":
        return common+(
            q["total_normalized_all_constraint_excess"],
            q["worst_task_deadline_excess_s"],
            candidate["physical_D_SHA"],
        )
    raise ValueError(method)


def run(source_path:Path,p22_path:Path,out:Path,profile:str,seed:int):
    if out.exists():raise FileExistsError(out)
    d=json.loads(source_path.read_text(encoding="utf-8"))
    earlier=json.loads(p22_path.read_text(encoding="utf-8"))
    scene=int(d["protocol"]["independent_scenario_seed"])
    if (scene,profile,seed) not in SCENE_CASES or not d.get("complete") or not earlier.get("complete"):
        raise ValueError("Only frozen S91 compute stress / S93 baseline development sources")
    inst=restore_instance(d["profiles"][profile]["instance"])
    instance_sha=d["profiles"][profile]["instance_sha256"]
    if content_hash(inst)!=instance_sha:raise RuntimeError("Physical model SHA mismatch")
    previous_B=next(x for x in d["rows"] if x["profile"]==profile
                    and x["seed"]==seed and x["method"]=="B-ALNS")
    original_B=restore_solution(previous_B["solution"])
    if content_hash(original_B)!=previous_B["solution_sha256"]:
        raise RuntimeError("Original B source SHA drift")
    earlier_case=next(x for x in earlier["rows"] if x["profile"]==profile and x["seed"]==seed)
    frozen_swap=earlier_case["policies"]["deadline_critical_pairs"]
    pair=tuple(frozen_swap["best"]["task_pair"])
    _,base=one_cross_uav_exchange(inst,original_B,owner_map(original_B),pair)
    base_sha=content_hash(base)
    if base_sha!=frozen_swap["best"]["finished_D_sha"]:
        raise RuntimeError("P29 changed original frozen P22 D")
    strict_source=_strict_numerical_check(inst,deepcopy(base))
    if strict_source["Stage1_and_Stage2_strict"] != frozen_swap["strict_posthoc"]["Stage1_and_Stage2_strict"]:
        raise RuntimeError("Original numerical solver changed from P22")
    groups,focus=task_groups(inst,base,seed)
    record={
        "complete":False,
        "protocol":{
            "id":"P29_E1_virtual_pair_binding_cross_uav_E2_reuse_v1",
            "scene":scene,"profile":profile,"seed":seed,
            "original_instance_SHA":instance_sha,
            "original_B_SHA":previous_B["solution_sha256"],
            "P22_frozen_D_SHA":base_sha,
            "P22_original_strict":strict_source["Stage1_and_Stage2_strict"],
            "candidate_generator_identical_per_target_task":True,
            "same_candidate_pool_for_each_ranking_within_target_group":True,
            "original_MEC_bandwidth_CPU_UAV_and_FIFO_EDF_unchanged":True,
            "one_task_cross_UAV_exact_original_insertion_option":True,
            "source_scenes_previously_inspected":True,
            "not_full_matched_wall_ALNS_benchmark":True,
            "expensive_original_CVX_posthoc_only":True,
            "strict_checks_per_group_per_rank":STRICT_CHECKS_PER_RANK,
        },
        "E1_precheck_binding":focus,
        "target_groups":groups,
        "results":{},
        "errors":[],
    }
    write_json(out,record)
    strict_cache={}
    for group,targets in groups.items():
        candidates,skipped=_candidate_records(inst,base,targets)
        if not candidates:raise RuntimeError(f"No legal cross-UAV relocation for group {group}")
        scored=[]
        retained={}
        for item in candidates:
            physical=item.pop("D")
            item["read_only"]=_read_only(inst,physical)
            retained[item["physical_D_SHA"]]=physical
            scored.append(item)
        snap={
            "targets":targets,
            "legal_distinct_candidates":len(scored),
            "generation_skipped":skipped,
            "candidate_pool":scored,
            "policy":{},
        }
        record["results"][group]=snap
        write_json(out,record)
        for method in RANKS:
            ordered=sorted(scored,key=lambda v:_rank(v,method))
            selection=ordered[:STRICT_CHECKS_PER_RANK]
            checked=[]
            for cand in selection:
                sha=cand["physical_D_SHA"]
                if sha not in strict_cache:
                    strict_cache[sha]=_strict_numerical_check(
                        inst,deepcopy(retained[sha])
                    )
                result=strict_cache[sha]
                checked.append({
                    "task":cand["target_task"],
                    "to_UAV":cand["to_UAV"],
                    "execution":cand["to_execution"],
                    "visit":cand["existing_E2_visit"],
                    "SHA":sha,
                    "queue_pass":cand["read_only"]["queue"]["queue_necessary_pass"],
                    "E1_cpu_required_lb_GHz":cand["read_only"]["CPU_share"]["E1_required_cpu_lb"],
                    "joint_gate_pass":cand["read_only"]["joint"]["passes_joint_necessary_test"],
                    "Stage1_qualified":result["Stage1_strict_qualified"],
                    "strict_both":result["Stage1_and_Stage2_strict"],
                    "strict_result":result,
                })
            snap["policy"][method]={
                "common_candidate_SHA":[v["physical_D_SHA"] for v in scored],
                "strict_checks":checked,
                "strict_sources":sum(v["strict_both"] for v in checked),
                "any_strict":any(v["strict_both"] for v in checked),
                "quota":len(checked),
            }
            write_json(out,record)
            print("P29_E1_TRANSFER_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "group":group,"method":method,"targets":targets,
                "pool":len(scored),
                "queue_pass_full":sum(v["read_only"]["queue"]["queue_necessary_pass"] for v in scored),
                "joint_pass_full":sum(v["read_only"]["joint"]["passes_joint_necessary_test"] for v in scored),
                "strict_checks":[{
                    k:v[k] for k in ("task","to_UAV","execution","visit",
                                     "queue_pass","E1_cpu_required_lb_GHz",
                                     "joint_gate_pass","Stage1_qualified","strict_both")
                } for v in checked],
            },ensure_ascii=False),flush=True)
    if content_hash(original_B)!=previous_B["solution_sha256"] or content_hash(base)!=base_sha:
        raise RuntimeError("P29 original frozen source state mutated")
    record["complete"]=True
    record["summary"]={
        "scene":scene,"profile":profile,"seed":seed,
        "groups":{
            g:{
                "legal_D":v["legal_distinct_candidates"],
                "selected_strict_success_by_rank":{
                    rule:vals["strict_sources"]
                    for rule,vals in v["policy"].items()
                }
            }
            for g,v in record["results"].items()
        }
    }
    write_json(out,record)
    print("P29_E1_TRANSFER_SUMMARY="+json.dumps(record["summary"],ensure_ascii=False),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--p22",type=Path,required=True)
    p.add_argument("--profile",required=True)
    p.add_argument("--seed",type=int,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.p22,a.output,a.profile,a.seed)
