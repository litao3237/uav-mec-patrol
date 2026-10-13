"""P25 two-step post-swap MEC reassignment with joint BW-CPU bound.

Mechanism development only. P22 fixed task-exchange candidate D is restored
with its exact SHA. One-step offload changes are expanded to *two distinct*
offload-task changes using an unchanged paper physics and original Stage1/2.

A common two-move candidate search pool is built once (no expensive CVX).
Top-4 root moves by three preregistered P24 rankings + four seeded random
roots are expanded. The same final shortlist (top-20 per cheap ranking + ten
seeded random) is ranked by:
  - CPU-only necessary bound
  - optimistic queue deadline bound only
  - joint bandwidth/CPU necessary bound (24 bins)
Every ranker receives identical final candidates and <=5 *posthoc* original
numerical Stage1/Stage2 tests; do not call this full ALNS or independent test.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from run_p12_insertion_finish_audit import CASES, _strict_numerical_check
from run_p22_deadline_cross_uav_exchange import (
    one_cross_uav_exchange, owner_map,
)
from run_p24_postswap_offload_redistribution import (
    _one_task_offload_moves, _audit_candidate, _key as p24_rank_key,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

P22_ARM="deadline_critical_pairs"
POLICIES=("joint_bw_cpu_rank", "cpu_lb_rank", "queue_rank")
PARENT_POLICIES=("cpu_lb_rank", "queue_rank", "heavy_task_rank")
FIRST_PER_RANK=4
FIRST_RANDOM=4
SECOND_PER_RANK=20
SECOND_RANDOM=10
STRICT_CVX_PER_RANK=5
JOINT_BINS=24


def _record(instance, label, changed_task, candidate, parent=None):
    return {
        "label":label,
        "changed_task":changed_task,
        "root":parent,
        "task_workload_gcycles":instance.tasks[changed_task].workload_gcycles,
        "sha":content_hash(candidate),
        "audit":_audit_candidate(instance,candidate),
    }


def _general_key(rec,policy):
    return p24_rank_key({
        "label":rec["label"],
        "task_workload_gcycles":rec["task_workload_gcycles"],
        "audit":rec["audit"],
    }, policy)


def pick_parent_roots(instance, source, seed):
    generated, skipped=_one_task_offload_moves(instance,source)
    original_sha=content_hash(source)
    if not generated:
        raise RuntimeError("No legal first offload actions")
    roots=[]
    for label,tid,candidate in generated:
        rec=_record(instance,label,tid,candidate)
        roots.append((rec,candidate))
    selected={}
    reasons={}
    for rule in PARENT_POLICIES:
        ranked=sorted(roots,key=lambda p:_general_key(p[0],rule))
        for rec,state in ranked[:FIRST_PER_RANK]:
            selected[rec["sha"]]=(rec,state)
            reasons.setdefault(rec["sha"],[]).append(rule)
    rng=np.random.default_rng(seed+252500)
    picks=rng.choice(len(roots),size=min(len(roots),FIRST_RANDOM),replace=False)
    for i in picks:
        rec,state=roots[int(i)]
        selected[rec["sha"]]=(rec,state)
        reasons.setdefault(rec["sha"],[]).append("random_control")
    if content_hash(source)!=original_sha:
        raise RuntimeError("Original root D mutated by candidate generation")
    return roots, [(r,s,reasons[r["sha"]]) for r,s in selected.values()], skipped


def expand_second_moves(instance, parents):
    unique={}
    for first,first_state,selection_reasons in parents:
        children,skips=_one_task_offload_moves(instance,first_state)
        for label,tid,candidate in children:
            if tid==first["changed_task"]:
                continue  # exactly two DISTINCT offload task decisions
            sha=content_hash(candidate)
            if sha==first["sha"] or sha in unique:
                continue
            rec=_record(instance,label,tid,candidate,parent={
                "first_task":first["changed_task"],
                "first_action":first["label"],
                "root_selected_by":selection_reasons,
                "first_SHA":first["sha"],
            })
            rec["label"]=first["label"]+" | "+label
            rec["second_task"]=tid
            unique[sha]=(rec,candidate)
    return list(unique.values())


def common_shortlist(second, seed):
    if not second:
        raise RuntimeError("No legal two-distinct-task offload candidates")
    selected={}
    for rule in PARENT_POLICIES:
        for rec,candidate in sorted(second,key=lambda p:_general_key(p[0],rule))[
            :SECOND_PER_RANK
        ]:
            selected[rec["sha"]]=(rec,candidate)
    rng=np.random.default_rng(seed+252501)
    picks=rng.choice(len(second),size=min(len(second),SECOND_RANDOM),replace=False)
    for i in picks:
        rec,state=second[int(i)]
        selected[rec["sha"]]=(rec,state)
    return list(selected.values())


def audit_joint(instance, solution, record):
    q=record["audit"]["queue"]
    if not q["queue_necessary_pass"]:
        return {
            "evaluated":False,
            "passes_joint_necessary_test":False,
            "reason":"already_fails_optimistic_queue_necessary_bound",
            "max_station_joint_CPU_over":None,
            "joint_wall_s":0.,
        }
    info=build_event_info(instance,solution)
    r=joint_station_bw_cpu_necessary_bound(
        instance,solution,info=info,n_bins=JOINT_BINS
    )
    return {
        "evaluated":True,
        "passes_joint_necessary_test":r["passes_joint_necessary_test"],
        "joint_necessary_reject":r["joint_necessary_reject"],
        "max_station_joint_CPU_over":max(
            [
                st["oversubscription_cpu_ghz"] or 0.
                for st in r["stations"].values()
            ],
            default=0.,
        ),
        "by_station": {
            k:{
                "joint_necessary_violation":v["joint_necessary_violation"],
                "optimistic_min_total_cpu_ghz":v["optimistic_min_total_cpu_ghz"],
                "physical_CPU_ghz":v["physical_cpu_ghz"],
                "oversubscription_cpu_ghz":v["oversubscription_cpu_ghz"],
            }
            for k,v in r["stations"].items()
        },
        "joint_wall_s":r["joint_test_wall_s"],
    }


def final_score(rec,policy):
    queue=rec["audit"]["queue"]
    cpu=rec["audit"]["cpu_lb"]
    gate=(not queue["queue_necessary_pass"],queue["queue_reason_count"])
    if policy=="joint_bw_cpu_rank":
        joint=rec["joint"]
        return gate+(
            not joint["passes_joint_necessary_test"],
            cpu["certified_cpu_share_failure"],
            float("inf") if joint["max_station_joint_CPU_over"] is None
            else joint["max_station_joint_CPU_over"],
            cpu["sum_station_cpu_excess_lb_ghz"],
            queue["total_normalized_all_constraint_excess"],
            rec["label"],
        )
    return _general_key(rec,policy)


def run(source_path:Path,p22_path:Path,output:Path,selected):
    if output.exists():
        raise FileExistsError(output)
    original=json.loads(source_path.read_text(encoding="utf-8"))
    p22=json.loads(p22_path.read_text(encoding="utf-8"))
    scene=int(original["protocol"]["independent_scenario_seed"])
    cases=[(p,int(s)) for p,s in selected]
    if (
        not original.get("complete") or not p22.get("complete") or p22.get("errors")
        or scene not in CASES or any(x not in CASES[scene] for x in cases)
        or set(cases)!={(r["profile"],int(r["seed"])) for r in p22["rows"]}
    ):
        raise ValueError("Only exact preinspected P22 original K80 physical states")
    frozen_index={
        (r["profile"],int(r["seed"]),r["method"]):r for r in original["rows"]
    }
    prev={
        (r["profile"],int(r["seed"])):r for r in p22["rows"]
    }
    result={
        "complete":False,
        "protocol":{
            "id":"P25_two_offload_task_postswap_joint_BW_CPU_repair_v1",
            "original_source_SHA":content_hash(original),
            "P22_source_SHA":content_hash(p22),
            "scene":scene,
            "first_roots_each_rank":FIRST_PER_RANK,
            "first_extra_random_roots":FIRST_RANDOM,
            "second_common_shortlist_each_rank":SECOND_PER_RANK,
            "second_extra_random_candidates":SECOND_RANDOM,
            "joint_optimistic_necessary_bins":JOINT_BINS,
            "same_final_candidate_pool_for_all_ranking_policies":True,
            "selected_strict_CVX_per_ranking":STRICT_CVX_PER_RANK,
            "original_resource_capacity_and_P1R_unchanged":True,
            "2_distinct_task_offload_decisions_only":True,
            "development_already_inspected_not_independent_holdout":True,
            "not_matched_wall_ALNS_algorithm":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,result)
    for profile,seed in cases:
        inst=restore_instance(original["profiles"][profile]["instance"])
        phys_sha=original["profiles"][profile]["instance_sha256"]
        if content_hash(inst)!=phys_sha:
            raise RuntimeError("Physical source mutated")
        b=frozen_index[profile,seed,"B-ALNS"]
        init=restore_solution(b["solution"])
        frozen_B=b["solution_sha256"]
        if content_hash(init)!=frozen_B:
            raise RuntimeError("Frozen original B SHA drift")
        former=prev[profile,seed]["policies"][P22_ARM]
        frozen_pair=tuple(former["best"]["task_pair"])
        recreated,base=one_cross_uav_exchange(inst,init,owner_map(init),frozen_pair)
        base_sha=content_hash(base)
        if base_sha!=former["best"]["finished_D_sha"]:
            raise RuntimeError("Exact P22 positive swap reconstruction SHA mismatch")
        original_strict=_strict_numerical_check(inst,deepcopy(base))
        if bool(original_strict["Stage1_and_Stage2_strict"]) != bool(
            former["strict_posthoc"]["Stage1_and_Stage2_strict"]
        ):
            raise RuntimeError("Original P22 strict numerical drift")
        base_audit=_audit_candidate(inst,base)
        roots,parents,skipped=pick_parent_roots(inst,base,seed)
        second=expand_second_moves(inst,parents)
        shortlist=common_shortlist(second,seed)
        strict_cache={}
        full=[]
        candidates={}
        for rec,state in shortlist:
            rec["joint"]=audit_joint(inst,state,rec)
            full.append(rec)
            candidates[rec["sha"]]=state
        record={
            "scene":scene,"profile":profile,"seed":seed,
            "original_B_SHA":frozen_B,
            "original_physical_SHA":phys_sha,
            "reconstructed_P22_swap_pair":list(frozen_pair),
            "reconstructed_P22_D_SHA":base_sha,
            "P22_swap_strict":original_strict,
            "P22_swap_queue_CPU":base_audit,
            "first_full_generated":len(roots),
            "first_parent_states":len(parents),
            "first_parent_qualifications":[
                {"label":r["label"],"task":r["changed_task"],
                 "chosen_by":why,"queue_pass":r["audit"]["queue"]["queue_necessary_pass"],
                 "cpu_LB_pass":not r["audit"]["cpu_lb"]["certified_cpu_share_failure"]}
                for r,_,why in parents
            ],
            "first_skipped":skipped,
            "second_full_generated":len(second),
            "common_final_pool_size":len(full),
            "common_final_pool":full,
            "policies":{},
        }
        result["rows"].append(record)
        write_json(output,result)
        for policy in POLICIES:
            ranked=sorted(full,key=lambda r:final_score(r,policy))
            top=ranked[:STRICT_CVX_PER_RANK]
            outputs=[]
            for item in top:
                sha=item["sha"]
                if sha not in strict_cache:
                    strict_cache[sha]=_strict_numerical_check(
                        inst,deepcopy(candidates[sha])
                    )
                check=strict_cache[sha]
                outputs.append({
                    "label":item["label"],
                    "candidate_sha":sha,
                    "queue_pass":item["audit"]["queue"]["queue_necessary_pass"],
                    "cpu_necessary_pass":not item["audit"]["cpu_lb"]["certified_cpu_share_failure"],
                    "joint_necessary_pass":item["joint"]["passes_joint_necessary_test"],
                    "strict_both":check["Stage1_and_Stage2_strict"],
                    "strict":check,
                })
            record["policies"][policy]={
                "common_candidate_sha_set":[x["sha"] for x in full],
                "checked":outputs,
                "any_strict":any(x["strict_both"] for x in outputs),
                "strict_count":sum(x["strict_both"] for x in outputs),
                "selected_CVX_quota":len(outputs),
            }
            write_json(output,result)
            print("P25_TWO_STEP_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "policy":policy,"base_strict":original_strict["Stage1_and_Stage2_strict"],
                "first_moves":len(roots),"parents":len(parents),
                "second_moves":len(second),"common_shortlist":len(full),
                "strict_selected":[
                    {"label":r["label"],
                     "queue":r["queue_pass"],
                     "cpu":r["cpu_necessary_pass"],
                     "joint":r["joint_necessary_pass"],
                     "stage1":r["strict"]["Stage1_strict_qualified"],
                     "strict":r["strict_both"]}
                    for r in outputs
                ],
            },ensure_ascii=False),flush=True)
        if content_hash(init)!=frozen_B or content_hash(base)!=base_sha:
            raise RuntimeError("Original B/P22 solution mutated during P25")
    result["complete"]=True
    result["summary"]={
        "physical_case_n":len(result["rows"]),
        "strict_by_policy":{
            k:sum(r["policies"][k]["any_strict"] for r in result["rows"])
            for k in POLICIES
        },
        "selected_strict_checks_by_policy":{
            k:sum(len(r["policies"][k]["checked"]) for r in result["rows"])
            for k in POLICIES
        },
        "errors":len(result["errors"]),
    }
    write_json(output,result)
    print("P25_TWO_STEP_SCENE_SUMMARY="+json.dumps(
        {"scene":scene,**result["summary"]},ensure_ascii=False),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--p22",type=Path,required=True)
    ap.add_argument("--cases",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    run(args.source,args.p22,args.output,[x.split(":") for x in args.cases.split(",")])
