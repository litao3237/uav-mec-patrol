"""P23: frozen P22 two-UAV exchange × MEC capacity interaction.

Read exact P22 posthoc QUEUE-SELECTED candidates, reconstruct same final
discrete D and verify SHA. For each D, change only MEC CPU or bandwidth,
then run the ORIGINAL Stage1 and independent Stage2 numerical solver.
This is not a new algorithm or equal-wall ALNS benchmark. Only previously
inspected K80 physical scenes are used, and no routing/offload changes are
made between resource factors. Report negative and positive checks alike.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from run_p12_insertion_finish_audit import (
    CASES, _strict_numerical_check, queue_metrics,
)
from run_p22_deadline_cross_uav_exchange import (
    ARMS, one_cross_uav_exchange, owner_map,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.evaluation.validator import validate_solution


CAPACITY = {
    "unchanged": (1.0, 1.0),
    "CPU_x2": (2.0, 1.0),
    "BW_x2": (1.0, 2.0),
    "CPU_BW_x2": (2.0, 2.0),
    "CPU_BW_x4": (4.0, 4.0),
}


def perturb_only_mec_capacity(instance, cpu: float, bw: float):
    if cpu < 1 or bw < 1:
        raise ValueError("P23 accepts upward capacity factors only")
    changed = replace(
        instance, mecs={
            mid: replace(
                mec,
                cpu_ghz=mec.cpu_ghz * cpu,
                bandwidth_mhz=mec.bandwidth_mhz * bw,
            )
            for mid, mec in instance.mecs.items()
        }
    )
    for prop in ("tasks", "uavs", "contact_points", "depot_xy",
                 "cycle_s", "avg_delay_budget_s", "max_contacts_per_uav"):
        if content_hash(getattr(changed, prop)) != content_hash(getattr(instance, prop)):
            raise RuntimeError("P23 changed something besides MEC capacity")
    for mid, original in instance.mecs.items():
        after = changed.mecs[mid]
        if (original.x, original.y, original.radius_m) != (
            after.x, after.y, after.radius_m
        ):
            raise RuntimeError("P23 changed MEC contact geometry")
    return changed


def run(source_path: Path, p22_path: Path, output: Path, cases):
    if output.exists():
        raise FileExistsError(output)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    prior = json.loads(p22_path.read_text(encoding="utf-8"))
    scene = int(source["protocol"]["independent_scenario_seed"])
    selected = [(p, int(s)) for p, s in cases]
    if not selected or scene not in CASES or any(s not in CASES[scene] for s in selected):
        raise ValueError("P23 accepts only frozen P22 inspected source cases")
    if not source.get("complete") or not prior.get("complete") or prior.get("errors"):
        raise ValueError("Source or P22 repairs are not complete")
    if prior["protocol"]["id"] != "P22_critical_deadline_two_UAV_task_swap_v1":
        raise ValueError("P23 requires full original P22 comparison")
    if int(prior["protocol"]["scene"]) != scene:
        raise ValueError("Mixed scenario identities")
    original_cases = {(r["profile"], int(r["seed"]), r["method"]):r for r in source["rows"]}
    prior_cases = {(r["profile"], int(r["seed"])):r for r in prior["rows"]}
    if set(selected) != set(prior_cases):
        raise ValueError("Missing or duplicate P22 frozen physical cases")

    report = {
        "complete":False,
        "protocol":{
            "id":"P23_fixed_P22_D_MEC_capacity_interaction_v1",
            "source_scene":scene,
            "source_original_B_SHA":content_hash(source),
            "source_P22_run_SHA":content_hash(prior),
            "resource_factors":CAPACITY,
            "algorithms":list(ARMS),
            "original_D_and_repaired_D_comparison_preselected_by_P22":True,
            "original_D_MEC_contact_structure_frozen_between_factors":True,
            "only_MEC_CPU_and_BW_changed":True,
            "original_Stage1_Stage2_strict_and_same_numerical_tolerance":True,
            "read_only_development_diagnostic_not_independent_holdout":True,
            "not_a_full_ALNS_match_clock_comparison":True,
        },
        "rows":[],
        "errors":[],
    }
    write_json(output,report)
    unique_physics={}
    for profile, seed in selected:
        instance=restore_instance(source["profiles"][profile]["instance"])
        if content_hash(instance)!=source["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("P23 changed original frozen source")
        b=original_cases[profile,seed,"B-ALNS"]
        D=restore_solution(b["solution"])
        original_sha=b["solution_sha256"]
        if content_hash(D)!=original_sha:
            raise RuntimeError("Frozen original B SHA changed")
        p22=prior_cases[profile,seed]
        if p22["frozen_B_SHA"]!=original_sha:
            raise RuntimeError("Frozen P22 physical source SHA changed")
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "original_B_SHA":original_sha,
            "P22_source_initial_strict":bool(
                p22["original_strict"]["Stage1_and_Stage2_strict"]),
            "arms":{},
        }
        report["rows"].append(row)
        write_json(output,report)
        owners=owner_map(D)
        for arm in ARMS:
            prior_arm=p22["policies"][arm]
            stored=prior_arm["best"]
            frozen_pair=tuple(stored["task_pair"])
            reconstructed, candidate=one_cross_uav_exchange(
                instance, D, owners, frozen_pair,
            )
            sha=content_hash(candidate)
            if sha!=stored["finished_D_sha"] or reconstructed["finished_D_sha"]!=sha:
                raise RuntimeError("P23 candidate did not reproduce P22 chosen D SHA")
            arm_record={
                "P22_best_pair":list(frozen_pair),
                "fixed_D_sha":sha,
                "original_B_sha":original_sha,
                "unchanged_P22_queue":stored["after"],
                "prior_P22_strict":bool(
                    prior_arm["strict_posthoc"]["Stage1_and_Stage2_strict"]),
                "capacity":{},
            }
            row["arms"][arm]=arm_record
            for label,(cpu,bw) in CAPACITY.items():
                physical=perturb_only_mec_capacity(instance,cpu,bw)
                validate_solution(physical,candidate)
                assert content_hash(candidate)==sha
                physics_key=(content_hash(physical),sha)
                if physics_key not in unique_physics:
                    q=queue_metrics(physical,candidate)
                    strict=_strict_numerical_check(physical,deepcopy(candidate))
                    unique_physics[physics_key]={
                        "queue":q,"strict":strict,
                    }
                actual=unique_physics[physics_key]
                arm_record["capacity"][label]={
                    "cpu":cpu,
                    "bw":bw,
                    "frozen_D_sha":sha,
                    "physical_instance_sha":content_hash(physical),
                    "queue":actual["queue"],
                    "strict":actual["strict"],
                    "Stage1_and_Stage2_strict":bool(
                        actual["strict"]["Stage1_and_Stage2_strict"]),
                }
                write_json(output,report)
            if (
                bool(arm_record["capacity"]["unchanged"]["Stage1_and_Stage2_strict"])
                != arm_record["prior_P22_strict"]
            ):
                raise RuntimeError("P23 baseline strict check disagrees with P22")
            print("P23_INTERACTION_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "arm":arm,"pair":list(frozen_pair),
                "queue_pass":{
                    k:v["queue"]["queue_necessary_pass"]
                    for k,v in arm_record["capacity"].items()
                },
                "stage1_status":{
                    k:v["strict"]["Stage1_solver_status"]
                    for k,v in arm_record["capacity"].items()
                },
                "strict_success":{
                    k:v["Stage1_and_Stage2_strict"]
                    for k,v in arm_record["capacity"].items()
                },
            },ensure_ascii=False),flush=True)
        if content_hash(D)!=original_sha:
            raise RuntimeError("P23 mutated original source after arm comparison")
    report["summary"]={
        "physical_sources":len(report["rows"]),
        "fixed_posthoc_pairs":len(report["rows"])*len(ARMS),
        "selected_D_capacity_checks":len(report["rows"])*len(ARMS)*len(CAPACITY),
        "unique_numerical_check_count":len(unique_physics),
        "strict_by_arm":{
            arm:{
                name:sum(r["arms"][arm]["capacity"][name]["Stage1_and_Stage2_strict"]
                         for r in report["rows"])
                for name in CAPACITY
            }
            for arm in ARMS
        },
        "errors":len(report["errors"]),
    }
    report["complete"]=True
    write_json(output,report)
    print("P23_INTERACTION_SCENE_SUMMARY="+
          json.dumps({"scene":scene,**report["summary"]},ensure_ascii=False),flush=True)
    return report


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--p22",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--cases",required=True)
    args=p.parse_args()
    run(args.source,args.p22,args.output,
        [v.split(":") for v in args.cases.split(",")])
