"""P30 independent Windows and Linux verification of P29 S91 strict rescue.

Freeze ORIGINAL K80 S91 compute_x1p5 seed128 P3 source, original P22
cross-UAV S17/S60 swap SHA and P29 SAME physical D e2e7d9... witness.
Reconstruct P29 S36 from U2 to U1 and offload at U1's existing E2
G_U1_1 (no new MEC station, CPU, BW, task or deadline change).

Two independent runners re-solve untouched P1-R Stage1/Stage2 and verify
independent original saved/reconstructed residual acceptance. Original P22
failure is preserved as the paired negative control. No elastic relaxation,
no CPU capacity doubling, no selection, no full ALNS improvement claim.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from run_p12_insertion_finish_audit import (
    _strict_numerical_check,queue_metrics,
)
from run_p22_deadline_cross_uav_exchange import one_cross_uav_exchange,owner_map
from run_p29_e1_binding_cross_uav import _candidate_records,task_groups
from run_seven_methods import finalize
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.evaluation import build_event_info,visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

WITNESS_SHA="e2e7d90260a5fe6d9e2139f359fdcb9039a4b79b690905d9af35bbfe873998a5"
TARGET_TASK="S36"
TARGET_OWNER="U1"
TARGET_CONTACT="G_U1_1"
PROFILE="compute_x1p5"
SEED=128
SCENE=91


def run(original:Path,p22:Path,p29:Path,output:Path,runner:str):
    if output.exists():raise FileExistsError(output)
    raw=json.loads(original.read_text(encoding="utf-8"))
    prior=json.loads(p22.read_text(encoding="utf-8"))
    earlier=json.loads(p29.read_text(encoding="utf-8"))
    if (not raw.get("complete") or not prior.get("complete")
        or not earlier.get("complete") or
        earlier["protocol"]["scene"]!=SCENE or
        earlier["protocol"]["profile"]!=PROFILE or
        earlier["protocol"]["seed"]!=SEED):
        raise ValueError("Expected exactly completed P29 physical source")
    instance=restore_instance(raw["profiles"][PROFILE]["instance"])
    i_sha=raw["profiles"][PROFILE]["instance_sha256"]
    if content_hash(instance)!=i_sha:
        raise RuntimeError("Original scientific scenario hardware drift")
    B_row=next(x for x in raw["rows"] if
               (x["profile"],int(x["seed"]),x["method"])
               ==(PROFILE,SEED,"B-ALNS"))
    B=restore_solution(B_row["solution"])
    Bsha=B_row["solution_sha256"]
    if content_hash(B)!=Bsha:
        raise RuntimeError("Original B endpoint SHA mismatch")
    p22r=next(x for x in prior["rows"] if
              (x["profile"],int(x["seed"]))==(PROFILE,SEED))
    selected=p22r["policies"]["deadline_critical_pairs"]
    _,swapped=one_cross_uav_exchange(
        instance,B,owner_map(B),tuple(selected["best"]["task_pair"])
    )
    if content_hash(swapped)!=selected["best"]["finished_D_sha"]:
        raise RuntimeError("Exact original two-task P22 cross-UAV swapped D drift")
    if content_hash(swapped)!=earlier["protocol"]["P22_frozen_D_SHA"]:
        raise RuntimeError("P22 physical D SHA disagrees with P29 source")
    selection=earlier["results"]["binding_chain_E1"]["policy"]["joint_bw_cpu"][
        "strict_checks"
    ]
    registered=[
        x for x in selection
        if (x["SHA"]==WITNESS_SHA and x["task"]==TARGET_TASK and
            x["to_UAV"]==TARGET_OWNER and
            x["execution"]=="existing_E2" and x["visit"]==TARGET_CONTACT)
    ]
    if len(registered)!=1 or not registered[0]["strict_both"]:
        raise RuntimeError("Original first strict rescue witness not archived")
    groups,meta=task_groups(instance,swapped,SEED)
    if TARGET_TASK not in groups["binding_chain_E1"]:
        raise RuntimeError("P30 no longer contains P28 binding E1 task")
    all_candidates,_=_candidate_records(
        instance,swapped,groups["binding_chain_E1"]
    )
    variants=[
        x for x in all_candidates if x["physical_D_SHA"]==WITNESS_SHA
    ]
    if len(variants)!=1:
        raise RuntimeError("Missing exact P29 original strictly qualified D SHA")
    candidate=variants[0]["D"]
    validate_solution(instance,candidate)
    owners=owner_map(candidate)
    if owners[TARGET_TASK]!=TARGET_OWNER:
        raise RuntimeError("S36 did not migrate to U1")
    task_decision=candidate.task_decisions[TARGET_TASK]
    if task_decision.contact_visit_id!=TARGET_CONTACT:
        raise RuntimeError("S36 did not offload at existing E2 U1 contact")
    if visit_mec_id(instance,candidate,TARGET_CONTACT)!="E2":
        raise RuntimeError("Offload destination is no longer original E2")
    if set(candidate.contact_visits)-set(swapped.contact_visits):
        raise RuntimeError("P30 unexpectedly created a new MEC visit")
    if content_hash(candidate)!=WITNESS_SHA:
        raise RuntimeError("Original published witness physical SHA changed")

    neg=_strict_numerical_check(instance,deepcopy(swapped))
    if neg["Stage1_and_Stage2_strict"]:
        raise RuntimeError("Negative control unexpectedly strict feasible")
    strict=_strict_numerical_check(instance,deepcopy(candidate))
    if not strict["Stage1_and_Stage2_strict"]:
        raise RuntimeError("Independent P30 strict P29 rescue did not reproduce")

    audit=finalize(
        instance,deepcopy(candidate),method="P30_independent_witness_reaudit",
        seed=SEED,initialization_s=0.,search_s=0.,
        diagnostics={"purpose":"extra_independent_posthoc_residual_reaudit"},
    )
    stage1=bool(audit["stage1"]["qualified"])
    stage2=bool(audit["stage2"]["qualified"])
    checks=audit["stage2"]["audit"]
    saved=bool(checks["saved"]["complete"] and checks["saved"]["passed"])
    reconstructed=bool(checks["reconstructed"]["complete"] and checks["reconstructed"]["passed"])
    if not (stage1 and stage2 and saved and reconstructed):
        raise RuntimeError("Independent Stage2 saved and reconstructed physical residual check failed")
    energy=float(audit["resources"].energy_stage1_j)
    if abs(energy-float(strict["strict_energy_j"]))>max(.1,1e-5*energy):
        raise RuntimeError("Independent two recomputations disagree on energy")

    queue=queue_metrics(instance,candidate)
    if not queue["queue_necessary_pass"]:
        raise RuntimeError("Qualified strict D did not pass optimistic queue necessary bound")
    cpu=station_cpu_share_necessary_bound(instance,candidate)
    joint=joint_station_bw_cpu_necessary_bound(instance,candidate,n_bins=24)
    if cpu["certified_cpu_share_failure"] or joint["joint_necessary_reject"]:
        raise RuntimeError("Qualified strict D falsely rejected by safe necessary bound")
    after=build_event_info(instance,candidate)
    before=build_event_info(instance,swapped)
    report={
        "complete":True,
        "protocol":{
            "id":"P30_cross_runner_original_P1R_exact_S91_first_strict_recovery_v1",
            "runner":runner,
            "scene":SCENE,"profile":PROFILE,"seed":SEED,
            "original_physical_instance_SHA":i_sha,
            "original_B_endpoint_SHA":Bsha,
            "exact_p22_source_D_SHA":content_hash(swapped),
            "exact_p29_recovery_D_SHA":WITNESS_SHA,
            "unchanged_original_tasks_UAVs_MEC_hardware":True,
            "unchanged_original_resource_solver_and_residual_tolerances":True,
            "additional_independent_full_Stage1_Stage2_reaudit":True,
            "no_cpu_bw_capacity_relaxation":True,
            "not_matched_search_clock_full_ALNS_comparison":True,
        },
        "task_migration":{
            "task":TARGET_TASK,
            "old_UAV":owner_map(swapped)[TARGET_TASK],
            "new_UAV":owners[TARGET_TASK],
            "new_execution":task_decision.mode.value,
            "existing_contact":TARGET_CONTACT,
            "physical_MEC":"E2",
            "old_station":visit_mec_id(instance,swapped,
                    swapped.task_decisions[TARGET_TASK].contact_visit_id),
            "original_contact_visits":len(swapped.contact_visits),
            "new_contact_visits":len(candidate.contact_visits),
        },
        "baseline_p22_strict":neg["Stage1_and_Stage2_strict"],
        "original_P29_strict":strict,
        "independent_full_audit":{
            "stage1_qualified":stage1,
            "stage2_qualified":stage2,
            "stage2_saved_complete_and_passed":saved,
            "stage2_reconstructed_complete_and_passed":reconstructed,
            "energy_j":energy,
            "second_energy_j":strict["strict_energy_j"],
            "original_E1_cpu_ghz":instance.mecs["E1"].cpu_ghz,
            "original_E2_cpu_ghz":instance.mecs["E2"].cpu_ghz,
            "E1_static_CPU_lower_bound_ghz":cpu["stations"]["E1"]["required_cpu_lb_ghz"],
            "E1_CPU_certificate_pass":not cpu["certified_cpu_share_failure"],
            "joint_CPU_BW_certificate_pass":joint["passes_joint_necessary_test"],
            "queue_necessary_pass":queue["queue_necessary_pass"],
        },
        "errors":[],
    }
    if content_hash(instance)!=i_sha or content_hash(B)!=Bsha:
        raise RuntimeError("Original source changed during cross-runner P30")
    write_json(output,report)
    print("P30_INDEPENDENT_STRICT_REPRODUCED="+json.dumps({
        "runner":runner,
        "witness_SHA":WITNESS_SHA,
        "paired_P22_baseline_strict":neg["Stage1_and_Stage2_strict"],
        "new_unchanged_hardware_strict":strict["Stage1_and_Stage2_strict"],
        "independent_Stage2_saved_pass":saved,
        "independent_Stage2_reconstructed_pass":reconstructed,
        "stage1_energy_j":energy,
        "migrated_task":TARGET_TASK,
        "new_UAV":TARGET_OWNER,
        "new_MEC":"E2",
    },ensure_ascii=False),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--p22",type=Path,required=True)
    p.add_argument("--p29",type=Path,required=True)
    p.add_argument("--runner",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.p22,a.p29,a.output,a.runner)
