"""P16 audit WHY optimistic offload reuse score misranks old S96/S23.

P15 virtual FIFO/EDF test gives perfect necessary pass to ALL three
old Top3 locations for S96/S23, yet only original rank3 triggers a
REAL MEC greedy reuse that restores strict Stage1+2. What is missing?

P16 does not create new ALNS yet: it records exactly the original MEC
greedy constructor's actionable constraints WITHOUT running its 24-step
search: baseline evaluate_initial_proxy() and original
_critical_local_tasks(...,limit=8), then on each existing downstream
contact evaluate_initial_proxy for ONE actual candidate offload and
_original _strictly_better() exact lexicographic decision. This captures
whether a virtual contact would actually be considered by the
published MEC builder, not only whether hypothetically offloading
would pass the optimistic FIFO/EDF lower bound.

The original full MEC builder is then run ONCE per original rank for
strict posthoc verification and actual greedy move trace. No extra
CVX in the selection of a prospective rank. This is only development
mechanism diagnosis on already-inspected S96/S23 and S93/S68.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from run_p12_insertion_finish_audit import (
    _strict_numerical_check,queue_metrics,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.algorithms.initial.mec_repair import (
    GreedyMECRepairConfig,_critical_local_tasks,
    _existing_contacts_after_task,_reuse_contact_candidate,
    _strictly_better,evaluate_initial_proxy,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)

CASES={
    96:("deadline_x0p9",130,"S23"),
    93:("baseline",129,"S68"),
}


def audit(source_path:Path,out:Path):
    if out.exists():raise FileExistsError(out)
    data=json.loads(source_path.read_text(encoding="utf-8"))
    s=int(data["protocol"]["independent_scenario_seed"])
    if s not in CASES or not data.get("complete"):
        raise ValueError("Only known P12/P13 strict development exemplars")
    profile,seed,task=CASES[s]
    src=next(r for r in data["rows"] if r["profile"]==profile and
             int(r["seed"])==seed and r["method"]=="B-ALNS")
    inst=restore_instance(data["profiles"][profile]["instance"])
    start=restore_solution(src["solution"])
    if content_hash(start)!=src["solution_sha256"]:
        raise RuntimeError("Original strict source fingerprint changed")
    destroyed=ops._destroy_tasks(
        UavMecState(inst,deepcopy(start),ScreenedProxyObjectiveEvaluator()),
        [task])
    original_options=ops._options_for_task(destroyed,task)
    results={
        "complete":False,
        "protocol":{
            "id":"P16_original_greedy_MEC_actionable_reuse_vs_hypothetical_lb_v1",
            "scene":s,"profile":profile,"seed":seed,"task":task,
            "source_B_SHA":src["solution_sha256"],
            "all_sources_previously_inspected":True,
            "unchanged_original_MEC_proxy_score_and_critical_task_logic":True,
            "no_extra_CVX_during_cheap_predictor":True,
            "strict_CVX_and_full_MEC_rebuild_are_posthoc_diagnostic":True,
        },
        "candidates":[],"winner_policy":None,
        "errors":[],
    }
    write_json(out,results)
    for rank,option in enumerate(original_options[:3],start=1):
        t0=perf_counter()
        clone=destroyed.copy()
        ops._apply_local_insertion(clone,task,option)
        local=clone.solution
        base=evaluate_initial_proxy(inst,local)
        critical=(
            _critical_local_tasks(
                inst,local,base,limit=GreedyMECRepairConfig().critical_task_limit)
            if base.score.violated_constraints>0 else [])
        rows=[]
        for visit in _existing_contacts_after_task(local,task):
            candidate=_reuse_contact_candidate(
                inst,local,task_id=task,visit_id=visit)
            proxy=evaluate_initial_proxy(inst,candidate)
            accept=bool(
                task in critical and
                _strictly_better(proxy.score,base.score,
                                 tolerance=GreedyMECRepairConfig().improvement_tolerance))
            rows.append({
                "contact":visit,
                "single_task_reuse_score_key":list(proxy.score.key),
                "old_builder_would_allow_this_reuse_candidate":accept,
                "strict_better_than_original_proxy_score":bool(
                    _strictly_better(proxy.score,base.score,
                                     tolerance=GreedyMECRepairConfig().improvement_tolerance)),
            })
        elapsed_proxy=perf_counter()-t0
        outcomes={
            "original_insertion_rank":rank,
            "uav":option.uav_id,"position":option.position,
            "original_incremental_distance_m":option.delta_distance_m,
            "original_route_only_proxy_score_key":list(base.score.key),
            "new_task_is_in_original_MEC_critical_pool":task in critical,
            "critical_pool_size":len(critical),
            "old_eligible_existing_contact_moves":rows,
            "one_step_original_MEC_proxy_compute_wall_s":elapsed_proxy,
        }
        full_start=perf_counter()
        completed=ops._finish_repair(clone.copy())
        outcomes["actual_unmodified_MEC_repair_moves"]=completed.solution.metadata.get(
            "mec_repair_moves",[])
        outcomes["actual_unmodified_MEC_rebuild_wall_s"]=perf_counter()-full_start
        outcomes["real_completed_D_SHA"]=content_hash(completed.solution)
        outcomes["real_queue_necessary_after_MEC"]=queue_metrics(
            inst,completed.solution)["queue_necessary_pass"]
        outcomes["original_strict_posthoc"]=_strict_numerical_check(
            inst,completed.solution)
        results["candidates"].append(outcomes)
        write_json(out,results)
        print("P16_MEC_ELIGIBLE="+json.dumps({
            "scene":s,"task":task,"rank":rank,
            "base_violations":base.score.violated_constraints,
            "critical":task in critical,
            "contacts":len(rows),
            "actionable":sum(x["old_builder_would_allow_this_reuse_candidate"] for x in rows),
            "real_rebuild_moves":outcomes["actual_unmodified_MEC_repair_moves"],
            "strict":outcomes["original_strict_posthoc"]["Stage1_and_Stage2_strict"],
            "proxy_wall_s":elapsed_proxy,
            "builder_wall_s":outcomes["actual_unmodified_MEC_rebuild_wall_s"],
        },ensure_ascii=False),flush=True)
    # Test one conservative actionability rule rather than tuning weights:
    # preserve old rank1 if its original MEC proxy is already fully
    # feasible, otherwise choose minimum available original greedy
    # lexicographic improved candidate score among actual critical pool
    # candidates. If none, keep old rank1.
    all_eligible=[]
    for x in results["candidates"]:
        for move in x["old_eligible_existing_contact_moves"]:
            if move["old_builder_would_allow_this_reuse_candidate"]:
                all_eligible.append((
                    tuple(move["single_task_reuse_score_key"]),
                    x["original_insertion_rank"],
                    move["contact"],
                ))
    top=results["candidates"][0]
    if top["original_route_only_proxy_score_key"][0]==0:
        chosen=1
        rule="old_rank1_proxy_feasible_original_MEC_would_stop"
    elif all_eligible:
        _,chosen,_=min(all_eligible)
        rule="min_original_greedy_accepted_reuse_proxy_key"
    else:
        chosen=1
        rule="no_single_task_reuse_in_critical_pool"
    results["winner_policy"]={
        "rule":rule,
        "chosen_original_rank":chosen,
        "posthoc_strict":results["candidates"][chosen-1][
            "original_strict_posthoc"]["Stage1_and_Stage2_strict"],
        "old_rank1_posthoc_strict":top["original_strict_posthoc"][
            "Stage1_and_Stage2_strict"],
        "original_source_unchanged":content_hash(start)==src["solution_sha256"],
    }
    results["complete"]=True
    write_json(out,results)
    print("P16_GREEDY_WITNESS="+json.dumps({
        "scene":s,**results["winner_policy"],
    },ensure_ascii=False),flush=True)
    return results


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    audit(args.source,args.output)
