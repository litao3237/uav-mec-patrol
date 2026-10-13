"""P27 credible elastic CPU/BW/QoS infeasibility attribution of frozen P22 D.

Already seen development cases only. The original fixed-D Stage1/Stage2
acceptance is NEVER replaced; elastic relaxations are diagnostics, not
physically feasible repairs. P24 and P26 structural candidates must match
the exact previously archived candidate SHA.

Aim: isolate which MEC station's fixed pair-CPU capacity still blocks S91
after a real task exchange, and whether CPU, bandwidth, or QoS-only
relaxation can make the original conic model numerically credible.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from run_p12_insertion_finish_audit import _strict_numerical_check, queue_metrics
from run_p22_deadline_cross_uav_exchange import (
    one_cross_uav_exchange, owner_map,
)
from run_p24_postswap_offload_redistribution import (
    _one_task_offload_moves,
)
from run_p26_postswap_mec_batch_transfer import (
    generate_batch_moves, joint_read_only,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.optimization.resource.elastic_diagnosis import (
    diagnose_elastic_resources,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)

SAMPLES={
    (91,"compute_x1p5",128):{
        "single":"new::S75->E2:E2_R2_A05@10",
        "batch":"edf_tail:2:G_U1_1->E1:new:E1_R1_A00",
    },
    (93,"baseline",129):{
        "single":"new::S45->E2:E2_R2_A04@19",
        "batch":"edf_head:2:G_U5_1->E2:new:E2_R2_A04",
    },
}
MODES=("cpu_capacity_only","bandwidth_capacity_only",
       "mec_capacity_only","qos_only")


def _lookup_evidence(prior,label,key,category):
    if category=="single":
        entries=prior["P22_parent_arm_results"][
            "deadline_critical_pairs"]["candidate_pool"]
        return next(r for r in entries if r["label"]==label)
    if category=="batch":
        entries=prior["complete_candidate_pool"]
        return next(r for r in entries if r["label"]==label)
    raise ValueError(category)


def run(source:Path,p22:Path,p24:Path,p26:Path,output:Path,cases):
    if output.exists():
        raise FileExistsError(output)
    original=json.loads(source.read_text(encoding="utf-8"))
    previous=json.loads(p22.read_text(encoding="utf-8"))
    one=json.loads(p24.read_text(encoding="utf-8"))
    batch=json.loads(p26.read_text(encoding="utf-8"))
    scene=int(original["protocol"]["independent_scenario_seed"])
    target=[(profile,int(seed)) for profile,seed in cases]
    if (not original.get("complete") or not previous.get("complete")
        or not one.get("complete") or not batch.get("complete")
        or len(target)!=1 or (scene,target[0][0],target[0][1]) not in SAMPLES):
        raise ValueError("Only P27 preregistered previously inspected physical cases")
    profile,seed=target[0]
    expected=SAMPLES[scene,profile,seed]
    lookup={(r["profile"],int(r["seed"]),r["method"]):r for r in original["rows"]}
    source_row=lookup[profile,seed,"B-ALNS"]
    instance=restore_instance(original["profiles"][profile]["instance"])
    physical_sha=original["profiles"][profile]["instance_sha256"]
    if content_hash(instance)!=physical_sha:
        raise RuntimeError("Frozen paper hardware mutated")
    B=restore_solution(source_row["solution"])
    Bsha=source_row["solution_sha256"]
    if content_hash(B)!=Bsha:
        raise RuntimeError("Frozen original B endpoint changed")
    p22row=next(r for r in previous["rows"] if
                (r["profile"],int(r["seed"]))==(profile,seed))
    p24row=next(r for r in one["rows"] if
                (r["profile"],int(r["seed"]))==(profile,seed))
    p26row=next(r for r in batch["rows"] if
                (r["profile"],int(r["seed"]))==(profile,seed))
    if (p24row["original_B_SHA"]!=Bsha or p26row["original_B_SHA"]!=Bsha):
        raise RuntimeError("P24/P26 source identity mismatch")
    fixed=p22row["policies"]["deadline_critical_pairs"]
    pair=tuple(fixed["best"]["task_pair"])
    _,D=one_cross_uav_exchange(instance,B,owner_map(B),pair)
    Dsha=content_hash(D)
    if Dsha!=fixed["best"]["finished_D_sha"]:
        raise RuntimeError("P22 restored source SHA mismatch")

    single_candidates=_one_task_offload_moves(instance,D)[0]
    one_evidence=_lookup_evidence(p24row,expected["single"],None,"single")
    modified_single=next(sol for label,tid,sol in single_candidates
                         if label==expected["single"])
    if content_hash(modified_single)!=one_evidence["candidate_SHA"]:
        raise RuntimeError("P24 selected factual source SHA drift")

    batch_candidates=generate_batch_moves(instance,D)[0]
    batch_evidence=_lookup_evidence(p26row,expected["batch"],None,"batch")
    modified_batch=next(r["D"] for r in batch_candidates
                        if r["label"]==expected["batch"])
    if content_hash(modified_batch)!=batch_evidence["candidate_SHA"]:
        raise RuntimeError("P26 selected factual source SHA drift")

    frozen_solutions={
        "exact_P22_swap":D,
        "P24_one_offload_change":modified_single,
        "P26_batch_offload_change":modified_batch,
    }
    report={
        "complete":False,
        "protocol":{
            "id":"P27_fixedD_originalMEC_elastic_CPU_BW_QoS_attribution_v1",
            "scene":scene,"profile":profile,"seed":seed,
            "B_original_SHA":Bsha,
            "original_instance_SHA":physical_sha,
            "P22_original_selected_D_SHA":Dsha,
            "P24_selected_action":expected["single"],
            "P26_selected_action":expected["batch"],
            "elastic_modes":list(MODES),
            "numerical_credibility_required_for_slack_claim":True,
            "elastic_solution_not_original_physical_feasible":True,
            "strict_stage1_stage2_unchanged_original_model":True,
            "all_previously_inspected_development_examples":True,
            "not_matched_wall_time_ALNS":True,
        },
        "candidates":{},"errors":[],
    }
    write_json(output,report)
    for name,solution in frozen_solutions.items():
        sha=content_hash(solution)
        strict=_strict_numerical_check(instance,deepcopy(solution))
        bound=station_cpu_share_necessary_bound(instance,solution)
        q=queue_metrics(instance,solution)
        joint=joint_read_only(instance,solution,q["queue_necessary_pass"])
        entry={
            "D_SHA":sha,
            "original_strict_Stage1_Stage2":strict,
            "queue":q,
            "cpu_share_bound":{
                "certified_failure":bound["certified_cpu_share_failure"],
                "stations":bound["stations"],
                "pair_demands":bound["pair_demands"],
            },
            "joint_bw_cpu_necessary":joint,
            "elastic_diagnoses":{},
        }
        report["candidates"][name]=entry
        write_json(output,report)
        for mode in MODES:
            diagnostic=diagnose_elastic_resources(
                instance,solution,mode=mode,
                numerical_violation_tol=2e-4,
                solve_tol=1e-7,
                max_scs_iters=45000,
                top_k=12,
            )
            entry["elastic_diagnoses"][mode]=diagnostic
            write_json(output,report)
            print("P27_ELASTIC_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "candidate":name,"mode":mode,
                "strict":strict["Stage1_and_Stage2_strict"],
                "queue_pass":q["queue_necessary_pass"],
                "static_cpu_necessary_fail":bound["certified_cpu_share_failure"],
                "joint_necessary_fail":joint["joint_necessary_reject"],
                "elastic_status":diagnostic["status"],
                "credible":diagnostic["numerically_credible"],
                "total_slack":diagnostic["normalized_total_elastic_slack"],
                "families":diagnostic["slack_sum_by_family"],
                "top_constraints":diagnostic["top_constraints"][:5],
            },ensure_ascii=False),flush=True)
    if content_hash(instance)!=physical_sha or content_hash(B)!=Bsha:
        raise RuntimeError("P27 original paper instance/source mutated")
    report["complete"]=True
    report["summary"]={
        "source_case":(scene,profile,seed),
        "D_variants":len(report["candidates"]),
        "elastic_n":len(MODES)*len(report["candidates"]),
        "original_strict_pass":{
            name:data["original_strict_Stage1_Stage2"]["Stage1_and_Stage2_strict"]
            for name,data in report["candidates"].items()
        },
        "CPU_capacity_only_credible":{
            name:data["elastic_diagnoses"]["cpu_capacity_only"]["numerically_credible"]
            for name,data in report["candidates"].items()
        },
        "errors":len(report["errors"]),
    }
    write_json(output,report)
    print("P27_ELASTIC_SCENE_SUMMARY="+json.dumps(
        report["summary"],ensure_ascii=False),flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--p22",type=Path,required=True)
    p.add_argument("--p24",type=Path,required=True)
    p.add_argument("--p26",type=Path,required=True)
    p.add_argument("--cases",required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    run(args.source,args.p22,args.p24,args.p26,args.output,
        [r.split(":") for r in args.cases.split(",")])
