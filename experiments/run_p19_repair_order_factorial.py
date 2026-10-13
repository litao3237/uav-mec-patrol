"""P19: fixed-destroy-set repair ORDER vs POSITION causal factorial audit.

For each frozen original B-ALNS D and ONE identical critical-destroy
set, reconstruct original cheapest and regret2 traces exactly. Then:
- order effect: replay the original task order while retaining the
  same ORIGINAL top1 insertion option function at each step;
- position effect: replay same task order with ONLY final position
  changed to the original rank2/rank3 (P12/P17 location effect);
- order-only counterfactual: reverse original task sequence, with
  original top1 location choice each step;
- alternative order: descending original deadline pressure, with
  original top1 location choice each step.

Every complete route-only D is passed to the UNCHANGED original
_finish_repair exactly once, followed by the original optimistic
FIFO/EDF necessary checker. Stage1+Stage2 strict checks are POSTHOC,
only for baseline and one preregistered alternative per source, not
for candidate selection or claims of matched-runtime ALNS gains.

The source scenario/seed, removed task SET, MEC initial contacts and
hardware are held identical. In the reverse/deadline arms, the actual
insertion position of every task is still recalculated by the ORIGINAL
_insertion_option. Hence order interventions can affect positions as
a consequence, but no scoring rule is changed. This is a mechanism
diagnostic, not a final new algorithm or independent holdout.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from run_p12_insertion_finish_audit import (
    CASES,queue_metrics,_strict_numerical_check,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)

KINDS=("cheapest","regret2")
POLICIES=("original_order","reverse_order","deadline_pressure_order",
          "original_order_last_rank2","original_order_last_rank3")


def _original_next(state,kind):
    if kind=="cheapest":
        best=None
        for tid in list(state.removed_tasks):
            option=ops._options_for_task(state,tid)[0]
            cand=(option.key,tid,option)
            if best is None or cand[:2]<best[:2]:best=cand
        return best[1],best[2]
    selected=None
    for tid in list(state.removed_tasks):
        options=ops._options_for_task(state,tid)
        a=options[0];b=options[1] if len(options)>1 else a
        regret=(
            max(0.,b.cycle_overflow_s-a.cycle_overflow_s),
            max(0.,b.deadline_lb_violation_s-a.deadline_lb_violation_s),
            max(0.,b.delta_distance_m-a.delta_distance_m))
        if selected is None or regret>selected[0]:
            selected=(regret,tid,a)
    return selected[1],selected[2]


def _original_task_order(destroyed,kind):
    current=destroyed.copy()
    order=[]
    while current.removed_tasks:
        tid,option=_original_next(current,kind)
        order.append(tid)
        ops._apply_local_insertion(current,tid,option)
    return order


def _deadline_priority(inst,task_id):
    task=inst.tasks[task_id]
    return (
        -task.workload_gcycles/max(1.,task.deadline_s),
        task.release_s+task.deadline_s,task_id)


def replay(destroyed,kind,policy,reference_order):
    state=destroyed.copy()
    order=(
        reference_order if policy.startswith("original_order")
        else list(reversed(reference_order)) if policy=="reverse_order"
        else sorted(reference_order,key=lambda t:_deadline_priority(
            destroyed.instance,t)))
    history=[]
    for ix,tid in enumerate(order):
        if tid not in state.removed_tasks:
            raise RuntimeError("Replayed order missing a destroyed task")
        options=ops._options_for_task(state,tid)
        rank=1
        if ix==len(order)-1 and policy.endswith("rank2"):rank=min(2,len(options))
        if ix==len(order)-1 and policy.endswith("rank3"):rank=min(3,len(options))
        option=options[rank-1]
        history.append({
            "task":tid,"uav":option.uav_id,"position":option.position,
            "original_option_rank":rank,
            "original_key":list(option.key),
        })
        ops._apply_local_insertion(state,tid,option)
    if state.removed_tasks:raise RuntimeError("Partial repair cannot be evaluated")
    before=queue_metrics(state.instance,state.solution)
    local_sha=content_hash(state.solution)
    start=perf_counter()
    finished=ops._finish_repair(state)
    rebuild_s=perf_counter()-start
    after=queue_metrics(state.instance,finished.solution)
    return {
        "order":list(order),"insertions":history,
        "route_only_sha":local_sha,
        "finished_sha":content_hash(finished.solution),
        "before":before,"after":after,
        "original_MEC_builder_wall_s":rebuild_s,
    },finished.solution


def run(source_path:Path,output:Path,cases):
    if output.exists():raise FileExistsError(output)
    raw=json.loads(source_path.read_text(encoding="utf-8"))
    scene=int(raw["protocol"]["independent_scenario_seed"])
    requested=[(p,int(s)) for p,s in cases]
    if not raw.get("complete") or scene not in CASES or any(
        item not in CASES[scene] for item in requested):
        raise ValueError("Only previously seen P12 frozen development cases")
    lookup={(r["profile"],int(r["seed"]),r["method"]):r
            for r in raw["rows"]}
    data={
        "complete":False,
        "protocol":{
            "id":"P19_fixed_destroy_same_D_task_order_vs_final_position_factorial_v1",
            "scene":scene,
            "frozen_original_source_sha256":content_hash(raw),
            "original_destroy_set_unchanged_per_comparison":True,
            "original_position_key_unchanged":True,
            "original_MEC_builder_unchanged":True,
            "strict_Stage1_Stage2_extra_posthoc_only":True,
            "already_inspected_development_scenes_not_new_holdout":True,
            "policies":list(POLICIES),"original_repairs":list(KINDS),
        },
        "rows":[],"errors":[],
    }
    write_json(output,data)
    for profile,seed in requested:
        record=lookup[profile,seed,"B-ALNS"]
        instance=restore_instance(raw["profiles"][profile]["instance"])
        source=restore_solution(record["solution"])
        if content_hash(source)!=record["solution_sha256"]:
            raise RuntimeError("Original B source SHA drift")
        if content_hash(instance)!=raw["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Original physical instance SHA drift")
        result={
            "scene":scene,"profile":profile,"seed":seed,
            "original_source_B_sha":record["solution_sha256"],
            "repairs":{},
        }
        data["rows"].append(result)
        write_json(output,data)
        try:
            base=UavMecState(
                instance,deepcopy(source),ScreenedProxyObjectiveEvaluator())
            destroyed=ops.critical_task_removal(
                base,np.random.default_rng(seed+4356),
                config=ops.DestroyConfig())
            original_removed=list(destroyed.removed_tasks)
            if not original_removed:raise RuntimeError("No original destroyed tasks")
            result["same_destroyed_task_set"]=original_removed
            result["same_destroyed_D_sha"]=content_hash(destroyed.solution)
            for kind in KINDS:
                order=_original_task_order(destroyed,kind)
                out={}
                kept={}
                for policy in POLICIES:
                    snapshot,finished=replay(
                        destroyed,kind,policy,order)
                    out[policy]=snapshot
                    kept[policy]=finished
                # Positive-control: EXACT original production operator
                original_fn=(
                    ops.cheapest_insertion_repair if kind=="cheapest"
                    else ops.regret2_insertion_repair)
                real=original_fn(destroyed,np.random.default_rng(seed+4357))
                if content_hash(real.solution)!=out["original_order"]["finished_sha"]:
                    raise RuntimeError("P19 original operator SHA identity mismatch")
                # Check ONLY original and a fixed reversed-order alternative
                # with costly strict CVX, not selecting the best posthoc arm.
                for policy in ("original_order","reverse_order"):
                    out[policy]["strict_posthoc"]=_strict_numerical_check(
                        instance,kept[policy])
                result["repairs"][kind]={
                    "original_task_order":order,
                    "original_removed_task_count":len(original_removed),
                    "policies":out,
                    "original_operator_sha_reproduced":True,
                }
                write_json(output,data)
                print("P19_ORDER_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,
                    "kind":kind,"removed":len(original_removed),
                    "original_queue_pass":out["original_order"]["after"]["queue_necessary_pass"],
                    "reverse_queue_pass":out["reverse_order"]["after"]["queue_necessary_pass"],
                    "deadline_queue_pass":out["deadline_pressure_order"]["after"]["queue_necessary_pass"],
                    "last_rank3_queue_pass":out["original_order_last_rank3"]["after"]["queue_necessary_pass"],
                    "original_strict":out["original_order"]["strict_posthoc"]["Stage1_and_Stage2_strict"],
                    "reverse_strict":out["reverse_order"]["strict_posthoc"]["Stage1_and_Stage2_strict"],
                },ensure_ascii=False),flush=True)
            if content_hash(source)!=record["solution_sha256"]:
                raise RuntimeError("Original B source was mutated")
        except Exception as exc:
            error={"scene":scene,"profile":profile,"seed":seed,
                   "type":type(exc).__name__,"message":str(exc)}
            result["error"]=error
            data["errors"].append(error)
            write_json(output,data)
    data["complete"]=True
    checks=[p for row in data["rows"] for rep in row["repairs"].values()
            for p in [rep["policies"]]]
    data["summary"]={
        "source_cases":len(data["rows"]),
        "original_destroy_repair_comparisons":len(checks),
        "actual_completed_counterfactuals":sum(len(p) for p in checks),
        "original_strict":sum(p["original_order"]["strict_posthoc"]["Stage1_and_Stage2_strict"] for p in checks),
        "reverse_strict":sum(p["reverse_order"]["strict_posthoc"]["Stage1_and_Stage2_strict"] for p in checks),
        "original_queue_pass":sum(p["original_order"]["after"]["queue_necessary_pass"] for p in checks),
        "reverse_queue_pass":sum(p["reverse_order"]["after"]["queue_necessary_pass"] for p in checks),
        "deadline_queue_pass":sum(p["deadline_pressure_order"]["after"]["queue_necessary_pass"] for p in checks),
        "last_rank3_queue_pass":sum(p["original_order_last_rank3"]["after"]["queue_necessary_pass"] for p in checks),
        "program_errors":len(data["errors"]),
    }
    write_json(output,data)
    print("P19_ORDER_SUMMARY="+json.dumps({
        "scene":scene,**data["summary"]},ensure_ascii=False),flush=True)
    if data["errors"]:
        raise RuntimeError("P19 incomplete: "+str(data["errors"][:2]))
    return data


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--cases",required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    run(args.source,args.output,[v.split(":") for v in args.cases.split(",")])
