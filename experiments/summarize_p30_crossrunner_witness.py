"""P30 cross-platform SHA-identical strict S91 witness independent residual audit."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

EXPECTED_SHA="e2e7d90260a5fe6d9e2139f359fdcb9039a4b79b690905d9af35bbfe873998a5"


def summary(folder:Path,output:Path):
    files=sorted(folder.rglob("p30-witness-*.json"))
    records=[json.loads(f.read_text(encoding="utf-8")) for f in files]
    errors=[]
    if len(records)!=2 or set(r["protocol"]["runner"] for r in records)!={"windows","ubuntu"}:
        errors.append("Expected two independent operating-system numerical runs")
    for r in records:
        if not r.get("complete") or r.get("errors"):
            errors.append("Incomplete cross-platform source evidence")
        if r["protocol"]["exact_p29_recovery_D_SHA"]!=EXPECTED_SHA:
            errors.append("Witness SHA changed in independent Stage1/Stage2 run")
        if r["baseline_p22_strict"]:
            errors.append("Original impossible P22 baseline incorrectly qualified")
        a=r["independent_full_audit"]
        if not all(a[x] for x in (
            "stage1_qualified","stage2_qualified",
            "stage2_saved_complete_and_passed",
            "stage2_reconstructed_complete_and_passed",
            "E1_CPU_certificate_pass","joint_CPU_BW_certificate_pass",
            "queue_necessary_pass",
        )):
            errors.append("Saved and reconstructed strict original resource residual failure")
    if len(records)==2:
        e1,e2=(r["independent_full_audit"]["energy_j"] for r in records)
        if abs(e1-e2)>max(1.,1e-4*max(abs(e1),abs(e2))):
            errors.append("Independent Windows and Linux physical energy disagreement")
        if records[0]["protocol"]["original_physical_instance_SHA"]!=records[1]["protocol"]["original_physical_instance_SHA"]:
            errors.append("Different input physics on independent runners")
        if records[0]["protocol"]["exact_p22_source_D_SHA"]!=records[1]["protocol"]["exact_p22_source_D_SHA"]:
            errors.append("Different parent P22 physical structure on independent runners")
    result={
        "previously_inspected_single_S91_development_case":True,
        "not_new_unseen_scene_validation_or_ALNS_benchmark":True,
        "unchanged_original_P1R_resource_capacity":True,
        "independent_two_OS_systems":len(records),
        "baseline_P22_strict_failure_required":True,
        "frozen_S36_direct_E2_contact_recovery_SHA":EXPECTED_SHA,
        "cross_platform_independent_strict_verified":not errors,
        "runs":[{
            "runner":r["protocol"]["runner"],
            "Stage1_and_Stage2_saved_reconstructed_strict":all(
                r["independent_full_audit"][key]
                for key in (
                    "stage1_qualified","stage2_qualified",
                    "stage2_saved_complete_and_passed",
                    "stage2_reconstructed_complete_and_passed",
                )),
            "energy_j":r["independent_full_audit"]["energy_j"],
            "parent_strict":r["baseline_p22_strict"],
            "cpu_e1_original_GHz":r["independent_full_audit"]["original_E1_cpu_ghz"],
        } for r in records],
        "errors":errors,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P30_CROSS_PLATFORM_AGGREGATE="+json.dumps(result,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("Cross-platform strict original model classification mismatch: "+str(errors))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    summary(a.collected,a.output)
