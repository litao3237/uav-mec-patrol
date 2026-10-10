"""Run elastic fixed-D resource conflict diagnosis on immutable archived scenarios.

Source archive: original K50/K80 Stage-1/Stage-2 sensitivity run 38043248604.
No paths, MEC contacts, task modes or ALNS implementations are modified.

For every source candidate, compute:
  - OLD necessary task-only feasibility certificate
  - independently audited FIFO/EDF queue-aware necessary certificate
  - QoS/battery elastic conic resource diagnosis with *hard* MEC capacities
  - QoS/battery+MEC-capacity counterfactual elastic diagnosis

Strictly validated Stage-1 examples are positive controls: a *credible* zero
elastic violation should be available. The elastic feasibility problem is
not the original energy-minimization program; it only helps locate which
fixed structure/resource constraints are under pressure. All original
numerical failures and raw resource status classes remain visible.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
from statistics import mean

from experiment_common import current_source_hashes, provenance
from run_model_sensitivity import METHODS, PROFILES
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource import fast_feasibility_precheck
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.elastic_diagnosis import (
    diagnose_elastic_resources, PROTOCOLS,
)


def _source_stage1_status(row):
    diag = (row.get("resources") or {}).get("diagnostics") or {}
    return str(diag.get("stage1_status") or row.get("stage1",{}).get("status")
               or "unknown")


def _old_and_queue(instance, solution):
    info = build_event_info(instance,solution)
    old = fast_feasibility_precheck(instance,solution,info)
    queue = queue_aware_feasibility_precheck(instance,solution,info)
    return {
        "old_passed":old.feasible,
        "old_reasons":list(old.reasons[:8]),
        "queue_passed":queue.feasible,
        "queue_reasons":list(queue.reasons[:8]),
        "extra_queue_certificate":bool(old.feasible and not queue.feasible),
    }


def summarize(rows):
    output = []
    for K in sorted({r["tasks"] for r in rows}):
        for profile in PROFILES:
            for method in METHODS:
                sample=[
                    r for r in rows if r["tasks"]==K
                    and r["profile"]==profile and r["method"]==method
                ]
                old_valid=[r for r in sample if r["original_stage1_qualified"]]
                for mode in PROTOCOLS:
                    good=[r for r in sample
                          if r["diagnoses"][mode]["numerically_credible"]]
                    stressed=[r for r in good
                              if r["diagnoses"][mode]["normalized_total_elastic_slack"]>0.002]
                    groups=Counter()
                    top=Counter()
                    for r in stressed:
                        diagnosis=r["diagnoses"][mode]
                        groups.update({
                            k:float(v)
                            for k,v in diagnosis["slack_sum_by_family"].items()
                        })
                        top.update({
                            x["family"]:1 for x in diagnosis["top_constraints"][:1]
                        })
                    control_flags=[
                        r for r in old_valid
                        if r["diagnoses"][mode]["numerically_credible"]
                        and r["diagnoses"][mode]["normalized_total_elastic_slack"]>0.002
                    ]
                    output.append({
                        "tasks":K,
                        "profile":profile,
                        "method":method,
                        "elastic_protocol":mode,
                        "n_attempt":len(sample),
                        "original_stage1_qualified":len(old_valid),
                        "original_stage2_qualified":sum(r["original_stage2_qualified"] for r in sample),
                        "original_status_counts":dict(Counter(r["original_stage1_status"] for r in sample)),
                        "old_precheck_rejected":sum(not r["old_passed"] for r in sample),
                        "queue_precheck_rejected":sum(not r["queue_passed"] for r in sample),
                        "credible_elastic_solutions":len(good),
                        "credibly_positive_elastic_slack":len(stressed),
                        "elastic_solver_unreliable_or_error":len(sample)-len(good),
                        "previously_strict_controls_with_positive_slack":len(control_flags),
                        "diagnostic_family_sum_normalized":dict(groups),
                        "top_conflict_family_count":dict(top),
                        "mean_normalized_slack_on_credible":(
                            mean(r["diagnoses"][mode]["normalized_total_elastic_slack"]
                                 for r in good) if good else None
                        ),
                        "mean_diagnostic_wall_s":(
                            mean(r["diagnoses"][mode]["diagnostic_build_and_solve_s"]
                                 for r in sample) if sample else None
                        ),
                    })
    return output


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    raw=json.loads(args.input.read_text(encoding="utf-8"))
    if not raw.get("complete") or raw["protocol"]["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Expected completed physical sensitivity archive")
    p=raw["protocol"]
    K,S=int(p["task_scale"]),int(p["independent_scenario_seed"])
    profiles=[name for name in args.profiles.split(",") if name]
    if not profiles or any(x not in PROFILES for x in profiles):
        raise ValueError("Unknown or absent parameter profiles")
    cache={}
    payload={
        "complete":False,
        "protocol":{
            "id":"resource_elastic_conflict_attribution_v1",
            "tasks":K,"independent_scenario_seed":S,
            "nested_algorithm_seeds":p["algorithm_seeds"],
            "profile_names":profiles,
            "methods":METHODS,
            "modes":PROTOCOLS,
            "original_archived_run_id":38043248604,
            "original_develop_commit":"0bdf3a26d4c042e13f96f84977261ffdd33cfc89",
            "same_fixed_D_and_same_P1R_conic_constraints":True,
            "no_original_fast_precheck_before_elastic_solve":True,
            "relaxed_groups_qos_only":["deadline","avg_delay","cycle","battery"],
            "relaxed_groups_plus_capacity":["deadline","avg_delay","cycle","battery",
                                            "bandwidth_cap","mec_cpu_cap"],
            "hard_constraints":"all original FIFO, EDF, upload epigraph, local CPU bounds, nonnegativity",
            "does_not_demonstrate_global_infeasibility_or_smallest_unsat_core":True,
            "credible_control_slack_threshold_normalized":.002,
            "physical_diagnosis_only_not_used_as_ALNS_acceptance":True,
            "source_hashes":current_source_hashes(Path(__file__)),
            "provenance":provenance(),
        },
        "rows":[],
    }
    write_json(args.output,payload)
    errors=[]
    profiles_instances={}
    for profile in profiles:
        snap=raw["profiles"][profile]
        instance=restore_instance(snap["instance"])
        if content_hash(instance)!=snap["instance_sha256"]:
            raise RuntimeError("Archived instance SHA mismatch: "+profile)
        profiles_instances[profile]=instance
    index={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    for profile in profiles:
        instance=profiles_instances[profile]
        for seed in p["algorithm_seeds"]:
            for method in METHODS:
                old=index[(profile,seed,method)]
                if old.get("status")=="error" or "solution" not in old:
                    row={
                        "tasks":K,"scenario":S,"seed":seed,
                        "profile":profile,"method":method,
                        "status":"unavailable_source_discrete_structure",
                        "original_stage1_status":_source_stage1_status(old),
                        "original_stage1_qualified":False,
                        "original_stage2_qualified":False,
                        "diagnoses":{},
                    }
                    payload["rows"].append(row)
                    write_json(args.output,payload)
                    continue
                sol=restore_solution(old["solution"])
                signature=content_hash(sol)
                if signature!=old.get("solution_sha256"):
                    raise RuntimeError("Archived solution SHA mismatch")
                feasibility=_old_and_queue(instance,sol)
                cache_key=(profile,signature)
                if cache_key in cache:
                    diagnoses=deepcopy(cache[cache_key])
                    from_cache=True
                else:
                    diagnoses={}
                    for mode in PROTOCOLS:
                        try:
                            diagnoses[mode]=diagnose_elastic_resources(
                                instance,sol,mode=mode,
                            )
                        except Exception as exc:
                            errors.append({
                                "profile":profile,"seed":seed,"method":method,
                                "mode":mode,"type":type(exc).__name__,
                                "message":str(exc),
                            })
                            diagnoses[mode]={
                                "mode":mode,
                                "numerically_credible":False,
                                "status":"exception",
                                "diagnostic_build_and_solve_s":None,
                                "error_type":type(exc).__name__,
                                "error_message":str(exc),
                            }
                    cache[cache_key]=deepcopy(diagnoses)
                    from_cache=False

                stage1_ok=bool(old.get("stage1_qualified"))
                stage2_ok=bool(old.get("stage2_qualified"))
                row={
                    "tasks":K,"scenario":S,"seed":seed,"profile":profile,
                    "method":method,"status":"ok",
                    "instance_sha256":content_hash(instance),
                    "solution_sha256":signature,
                    "original_stage1_status":_source_stage1_status(old),
                    "original_stage1_qualified":stage1_ok,
                    "original_stage2_qualified":stage2_ok,
                    "original_both_qualified":bool(old.get("both_qualified")),
                    "original_strict_energy_j":old.get("energy_stage1_j")
                        if stage1_ok else None,
                    **feasibility,
                    "cache_reused":from_cache,
                    "diagnoses":diagnoses,
                }
                for mode,diag in diagnoses.items():
                    if stage1_ok and diag.get("numerically_credible") and (
                        diag["normalized_total_elastic_slack"]>.002
                    ):
                        row.setdefault("control_warning",[]).append({
                            "mode":mode,
                            "positive_slack_for_prior_strict_solution":
                            diag["normalized_total_elastic_slack"],
                        })
                payload["rows"].append(row)
                write_json(args.output,payload)
                summary={
                    mode:{
                        "credible":v.get("numerically_credible",False),
                        "status":v.get("status"),
                        "slack":v.get("normalized_total_elastic_slack"),
                        "top":(v.get("top_constraints") or [])[:2],
                    } for mode,v in diagnoses.items()
                }
                print(
                    f"ELASTIC K{K} S{S} A{seed} {profile} {method}: "
                    f"orig={row['original_stage1_status']} old={feasibility['old_passed']} "
                    f"queue={feasibility['queue_passed']} cached={from_cache} "
                    f"elastic={json.dumps(summary,ensure_ascii=False)}",
                    flush=True,
                )
    payload["summary"]=summarize(payload["rows"])
    payload["unique_fixed_solutions_solved"]=len(cache)
    payload["unhandled_program_errors"]=errors
    payload["complete"]=True
    write_json(args.output,payload)
    print("ELASTIC_SUMMARY="+json.dumps({
        "K":K,"S":S,"records":len(payload["rows"]),
        "unique_fixed":len(cache),
        "error_count":len(errors),
        "rows":[{
            k:r[k] for k in (
                "profile","method","elastic_protocol","n_attempt",
                "original_stage1_qualified","credible_elastic_solutions",
                "credibly_positive_elastic_slack","elastic_solver_unreliable_or_error",
                "previously_strict_controls_with_positive_slack",
                "top_conflict_family_count"
            )
        } for r in payload["summary"]],
    },ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError(
            f"Unexpected diagnostic errors persisted: {errors[:3]}"
        )
    return payload


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--input",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--profiles",default=",".join(PROFILES))
    run(a.parse_args())


if __name__=="__main__":
    main()
