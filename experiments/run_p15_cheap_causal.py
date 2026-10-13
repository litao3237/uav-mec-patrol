"""P15 pre-existing causal counterexamples S96/S23 and S93/S68.

Evaluate the FROZEN cheap scorer without any reparameterization.
For all original top3 insertions from the SAME destroyed B-ALNS D:
1. Compute cheap LOCAL and hypothetical single-existing-contact queue
   necessary scores without completing MEC again.
2. Choose by 4 fixed policies; no CVX used for ranking.
3. Separately reconstruct each distinct top3 via original MEC builder,
   then original Stage1+Stage2 independent resource acceptance (postpaid).
These development cases are already seen, and P15 firstuse S117-S120
was launched BEFORE any P15 causal outcomes were inspected.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from p15_cheap_virtual_contact_repair import (
    POLICIES,CheapCounters,cheap_score_for_option,_selection_key,
)
from run_p12_insertion_finish_audit import (
    queue_metrics,_strict_numerical_check,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns import operators as ops
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)

CASES={
    96:("deadline_x0p9",130,"S23"),
    93:("baseline",129,"S68"),
}


def run(source_path:Path,output:Path):
    if output.exists():raise FileExistsError(output)
    original=json.loads(source_path.read_text(encoding="utf-8"))
    scene=int(original["protocol"]["independent_scenario_seed"])
    if scene not in CASES or not original.get("complete"):
        raise ValueError("Only previously known S96/S23, S93/S68 source cases")
    profile,seed,tid=CASES[scene]
    b=next(r for r in original["rows"] if r["profile"]==profile
           and int(r["seed"])==seed and r["method"]=="B-ALNS")
    instance=restore_instance(original["profiles"][profile]["instance"])
    solution=restore_solution(b["solution"])
    if content_hash(solution)!=b["solution_sha256"]:
        raise RuntimeError("Frozen original B source changed")
    parent=UavMecState(
        instance,deepcopy(solution),ScreenedProxyObjectiveEvaluator())
    destroyed=ops._destroy_tasks(parent,[tid])
    options=ops._options_for_task(destroyed,tid)
    if len(options)<3:raise RuntimeError("Need original top3 positions")
    counters=CheapCounters("all_arms_equal")
    candidates=[
        cheap_score_for_option(destroyed,tid,options[i-1],
                               rank=i,counters=counters)
        for i in (1,2,3)]
    indices={
        "cheap_sham":1,
        "cheap_contact":min(candidates,
            key=lambda x:_selection_key(x,"cheap_contact"))["rank"],
        "cheap_virtual":min(candidates,
            key=lambda x:_selection_key(x,"cheap_virtual"))["rank"],
        "cheap_guarded":(
            1 if not candidates[0]["local_key"][0] else
            min(candidates,key=lambda x:_selection_key(
                x,"cheap_virtual"))["rank"]),
    }
    result={
        "complete":False,
        "protocol":{
            "id":"P15_original_top3_cheap_causal_development_replay_v1",
            "scene":scene,"profile":profile,"seed":seed,"task":tid,
            "old_B_SHA":content_hash(solution),
            "non_independent_previously_seen_case":True,
            "all_policies_pre_registered_before_firstuse_run":True,
            "no_actual_MEC_rebuild_used_in_cheap_selection":True,
            "strict_CVX_is_postpaid_for_diagnostic_only":True,
        },
        "cheap_candidates":[],"policy_winners":indices,
        "physical_counterfactuals":[],"errors":[],
    }
    write_json(output,result)
    for x in candidates:
        result["cheap_candidates"].append({
            "rank":x["rank"],
            "uav":x["option"].uav_id,
            "position":x["option"].position,
            "delta_distance_m":x["option"].delta_distance_m,
            "reachable_existing_contacts":x["reachable_old_contacts"],
            "first_reachable_contact_position":x[
                "first_reachable_contact_position"],
            "local_queue_necessary":list(x["local_key"]),
            "best_virtual_necessary":list(x["best_virtual_key"]),
            "hypothetical_best_contact":x["best_virtual_mode"],
        })
    for x in candidates:
        start=perf_counter()
        full=ops._finish_repair(x["state"].copy())
        metrics=queue_metrics(instance,full.solution)
        evaluated=_strict_numerical_check(instance,full.solution)
        result["physical_counterfactuals"].append({
            "rank":x["rank"],
            "full_MEC_rebuild_and_original_CVX_wall_s":perf_counter()-start,
            "real_completed_D_SHA":content_hash(full.solution),
            "real_post_MEC_queue_necessary":metrics,
            "real_strict_original_stage1_stage2":evaluated,
        })
        write_json(output,result)
    result["summary"]={
        "scene":scene,"task":tid,
        "winners":{
            p:{
                "original_rank":r,
                "strict":result["physical_counterfactuals"][r-1][
                    "real_strict_original_stage1_stage2"][
                        "Stage1_and_Stage2_strict"],
                "post_MEC_queue_pass":result["physical_counterfactuals"][r-1][
                    "real_post_MEC_queue_necessary"]["queue_necessary_pass"],
            } for p,r in indices.items()},
        "cheap_virtual_checks":counters.virtual_offload_checked,
        "cheap_proxy_wall_s":counters.all_cheap_prediction_wall_s,
        "original_source_immutable":content_hash(solution)==b["solution_sha256"],
    }
    result["complete"]=True
    write_json(output,result)
    print("P15_CAUSAL="+json.dumps(result["summary"],ensure_ascii=False),flush=True)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    opts=p.parse_args()
    run(opts.source,opts.output)
