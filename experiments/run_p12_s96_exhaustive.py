"""P12 exact S96 proof-case FULL insertion-position enumeration.

Confirms that earlier rank1 vs rank3 example was NOT an artifact of
selecting 12 of 90 possible legal original positions. Replays all
original legal _insertion_option entries, unchanged apply_local,
unchanged MEC _finish_repair, evaluates real queue necessary after
each rebuilt complete D, and independently verifies first few
queue-passing ranks with unchanged original Stage1+Stage2.

This is a retrospective development-case replay, NOT independent
holdout, and extra full MEC repairs/CVX calls are not an ALNS budget.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from run_p12_insertion_finish_audit import (
    _task_counterfactual,_strict_numerical_check,queue_rank,
)
from uav_mec.algorithms import ScreenedProxyObjectiveEvaluator
from uav_mec.algorithms.alns import operators as ops,UavMecState
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,restore_solution,content_hash,write_json,
)
from uav_mec.algorithms.alns.evaluator import solution_signature


def run(source_file:Path,output_file:Path):
    if output_file.exists():raise FileExistsError(output_file)
    data=json.loads(source_file.read_text(encoding="utf-8"))
    if (not data.get("complete") or
        data["protocol"]["independent_scenario_seed"]!=96 or
        data["protocol"]["id"]!="uav_mec_one_factor_coupling_sensitivity_v1"):
        raise RuntimeError("Expected original frozen S96 physical source archive")
    profile="deadline_x0p9"
    seed=130
    original=next(r for r in data["rows"] if (
        r["profile"]==profile and r["seed"]==seed and r["method"]=="B-ALNS"))
    snap=data["profiles"][profile]
    inst=restore_instance(snap["instance"])
    sol=restore_solution(original["solution"])
    if content_hash(inst)!=snap["instance_sha256"] or (
        content_hash(sol)!=original["solution_sha256"]):
        raise RuntimeError("Original source fingerprint mismatch")
    result={
        "complete":False,
        "protocol":{
            "id":"P12_S96_S23_ALL_original_insertion_positions_necessary_vs_strict_v1",
            "source_sha256":content_hash(data),
            "source_D_sha256":original["solution_sha256"],
            "source_profile":profile,"algorithm_seed":seed,
            "original_B_stage1_status":(
                ((original.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status")),
            "target_task":"S23",
            "all_positions_not_sampled":True,
            "original_functions_unmodified":True,
            "extra_Stage1_Stage2_validation_not_matched_ALNS_runtime":True,
        },
        "case":None,
        "strict_rank_confirmations":[],
        "summary":None,
        "errors":[],
    }
    write_json(output_file,result)
    try:
        began=perf_counter()
        whole=_task_counterfactual(
            inst,sol,"S23",sample_max=1000,include_strict=True)
        if whole["all_original_legal_positions"]!=len(
                whole["sampled_positions"]):
            raise RuntimeError("P12 failed to enumerate ALL legal positions")
        result["case"]=whole
        write_json(output_file,result)
        ranks_pass=[
            p["original_insertion_rank"] for p in whole["sampled_positions"]
            if p["after_MEC_rebuild"]["queue_necessary_pass"]
        ]
        # Check whether first short-ranked candidates that are only
        # NECESSARY feasible are truly numerically feasible as well.
        first_six=ranks_pass[:6]
        old=UavMecState(
            inst,deepcopy(sol),ScreenedProxyObjectiveEvaluator())
        destroyed=ops._destroy_tasks(old,["S23"])
        available=ops._options_for_task(destroyed,"S23")
        seen={}
        for rank in first_six:
            cp=destroyed.copy()
            ops._apply_local_insertion(cp,"S23",available[rank-1])
            finished=ops._finish_repair(cp).solution
            sig=solution_signature(finished)
            if sig not in seen:
                seen[sig]=_strict_numerical_check(inst,finished)
            result["strict_rank_confirmations"].append({
                "original_insertion_rank":rank,
                "stage1_stage2":seen[sig],
                "same_physical_candidate_as_earlier_rank":next(
                    (r["original_insertion_rank"]
                     for r in result["strict_rank_confirmations"]
                     if r["stage1_stage2"]["candidate_sha256"]==
                        seen[sig]["candidate_sha256"]),None),
            })
            write_json(output_file,result)
        all_rows=whole["sampled_positions"]
        best_post=min(
            all_rows,key=lambda p:(
                queue_rank(p["after_MEC_rebuild"]),
                p["original_insertion_rank"]))
        top=all_rows[0]
        if top["original_insertion_rank"]!=1:
            raise RuntimeError("Original top1 position identity drift")
        result["summary"]={
            "legal_original_options_exhaustively_checked":len(all_rows),
            "top_rank_queue_necessary_pass_after_MEC":top[
                "after_MEC_rebuild"]["queue_necessary_pass"],
            "first_queue_necessary_passing_original_rank":(
                min(ranks_pass) if ranks_pass else None),
            "queue_necessary_passing_original_ranks":ranks_pass,
            "queue_necessary_passing_options":len(ranks_pass),
            "best_after_MEC_necessary_score_original_rank":best_post[
                "original_insertion_rank"],
            "MEC_reconstruction_changed_physical_decisions":sum(
                r["structural_effect"]["physical_signature_changed"]
                for r in all_rows),
            "original_top1_deadline_excess_s_after":top[
                "after_MEC_rebuild"]["total_task_deadline_excess_s"],
            "best_after_MEC_deadline_excess_s":best_post[
                "after_MEC_rebuild"]["total_task_deadline_excess_s"],
            "strict_different_CVX_candidates_in_first_six":len(seen),
            "strict_candidates_in_first_six":sum(
                bool(r["Stage1_and_Stage2_strict"])
                for r in seen.values()),
            "first_strict_original_insertion_rank_within_first_six":next((
                r["original_insertion_rank"]
                for r in result["strict_rank_confirmations"]
                if r["stage1_stage2"]["Stage1_and_Stage2_strict"]),None),
            "total_offline_posthoc_wall_s":perf_counter()-began,
            "original_D_unchanged":content_hash(sol)==original["solution_sha256"],
        }
        result["complete"]=True
        write_json(output_file,result)
        print("P12_EXHAUSTIVE_S96="+json.dumps(result["summary"],ensure_ascii=False),flush=True)
        if not result["summary"]["original_D_unchanged"]:
            raise RuntimeError("Original D mutated")
        return result
    except Exception as exc:
        result["errors"].append({
            "type":type(exc).__name__,"message":str(exc)})
        write_json(output_file,result)
        raise


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    run(args.source,args.output)
