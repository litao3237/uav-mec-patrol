"""Audit optimistic FIFO/EDF time bounds against every archived strict result.

Inputs are immutable snapshots from *two earlier GitHub workflows*:
- physical-parameter original run 38043248604: 224 reoptimized methods;
- fixed-discrete replay 38045837175: 224 replay evaluations.

Do not change the paper's actual fast precheck. Compare new queue-aware
optimistic precheck with the old one on exactly the same fixed discrete
solutions, and validate that no previously audited Stage-1 feasible solution
is falsely excluded or has a saved completion earlier than the new lower
bound. Heavy convex optimization is not rerun in this diagnostic.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
from statistics import mean

from experiment_common import provenance,current_source_hashes
from run_model_sensitivity import METHODS, PROFILES
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource import fast_feasibility_precheck
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


def evaluate_one(instance, solution, *, previous_stage1_qualified,
                 previous_stage1_values, label, source_status):
    info=build_event_info(instance,solution)
    old=fast_feasibility_precheck(instance,solution,info,tol_s=1e-4)
    new=queue_aware_feasibility_precheck(instance,solution,info,tol_s=1e-4)
    older_lb_underestimated=[
        t for t in instance.tasks
        if new.task_completion_lb_s[t]+1e-6<old.task_completion_lb_s[t]
    ]
    if older_lb_underestimated:
        raise RuntimeError(
            f"Queue bound cannot be smaller than task-only LB: "
            f"{label}, tasks={older_lb_underestimated}"
        )
    if previous_stage1_qualified and not new.feasible:
        raise RuntimeError(
            f"UNSOUND prune! Previously strict Stage-1 feasible {label}, "
            f"queue bound reasons={new.reasons}"
        )
    phys_safety_s=0.02
    physical_lb_violations=[]
    if previous_stage1_qualified and previous_stage1_values is not None:
        for t in instance.tasks:
            saved=float(previous_stage1_values["task_completion_s"][t])
            bound=new.task_completion_lb_s[t]
            if bound > saved + phys_safety_s:
                physical_lb_violations.append(
                    {"task":t,"lower_bound_s":bound,"audited_completion_s":saved}
                )
        if physical_lb_violations:
            raise RuntimeError(
                f"Queue LB exceeds audited physical completions: "
                f"{label} {physical_lb_violations[:3]}"
            )
    reasons=Counter()
    for r in new.reasons:
        if r.startswith("task "):
            tid=r.split(":",1)[0].split()[1]
            reasons["task_"+solution.task_decisions[tid].mode.value]+=1
        elif r.startswith("average delay:"):
            reasons["average_delay"]+=1
        elif r.startswith("UAV "):
            reasons["patrol_cycle"]+=1
        else:
            reasons["other"]+=1
    return {
        "prior_strict_stage1_qualified":previous_stage1_qualified,
        "prior_solver_status":source_status,
        "old_precheck_passed":old.feasible,
        "new_queue_precheck_passed":new.feasible,
        "extra_certified_infeasible":bool(old.feasible and not new.feasible),
        "old_reason_count":len(old.reasons),
        "queue_reason_count":len(new.reasons),
        "queue_reason_groups":dict(reasons),
        "queue_task_slack_min_s":min(
            instance.tasks[t].release_s+instance.tasks[t].deadline_s
            -new.task_completion_lb_s[t] for t in instance.tasks
        ),
        "max_task_queue_extension_s":max(
            new.task_completion_lb_s[t]-old.task_completion_lb_s[t]
            for t in instance.tasks
        ),
        "mean_task_queue_extension_s":mean(
            new.task_completion_lb_s[t]-old.task_completion_lb_s[t]
            for t in instance.tasks
        ),
        "old_precheck_reasons":list(old.reasons),
        "new_precheck_reasons":list(new.reasons),
        "physical_lb_violations":physical_lb_violations,
    }


def summarize(rows):
    out=[]
    for source in ("dynamically_reoptimized","baseline_structure_fixed"):
        for method in METHODS:
            for profile in PROFILES:
                z=[
                    r for r in rows
                    if r["source"]==source and r["method"]==method
                    and r["profile"]==profile
                ]
                groups=Counter()
                for r in z:
                    groups.update(r["queue_reason_groups"])
                out.append({
                    "source":source,
                    "method":method,
                    "profile":profile,
                    "attempted":len(z),
                    "previous_strict_stage1_qualified":sum(
                        r["prior_strict_stage1_qualified"] for r in z
                    ),
                    "old_precheck_rejected":sum(
                        not r["old_precheck_passed"] for r in z
                    ),
                    "queue_precheck_rejected":sum(
                        not r["new_queue_precheck_passed"] for r in z
                    ),
                    "additional_sound_rejections":sum(
                        r["extra_certified_infeasible"] for r in z
                    ),
                    "false_reject_strict_stage1":sum(
                        r["prior_strict_stage1_qualified"] and
                        not r["new_queue_precheck_passed"] for r in z
                    ),
                    "queue_reason_counts":dict(groups),
                    "solver_status_counts":dict(Counter(
                        r["prior_solver_status"] for r in z
                    )),
                    "mean_max_task_queue_extension_s":(
                        mean(r["max_task_queue_extension_s"] for r in z)
                        if z else None
                    ),
                })
    return out


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    orig=json.loads(args.source.read_text(encoding="utf-8"))
    fixed=json.loads(args.fixed.read_text(encoding="utf-8"))
    if not (orig.get("complete") and fixed.get("complete")):
        raise ValueError("Both archived experimental source files must be complete")
    K,S=orig["protocol"]["task_scale"],orig["protocol"]["independent_scenario_seed"]
    assert fixed["protocol"]["source_block"]=={"tasks":K,"scenario_seed":S}
    originals={
        (r["profile"],r["seed"],r["method"]):r
        for r in orig["rows"]
    }
    fixedrows={
        (r["profile"],r["seed"],r["method"]):r
        for r in fixed["rows"]
    }
    payload={
        "complete":False,
        "protocol":{
            "id":"queue_aware_optimistic_feasibility_certificate_v1",
            "tasks":K,"scenario":S,
            "source_physical_run_id":38043248604,
            "source_fixed_structure_run_id":38045837175,
            "original_frozen_develop_sha":"0bdf3a26d4c042e13f96f84977261ffdd33cfc89",
            "source_hashes":current_source_hashes(Path(__file__)),
            "provenance":provenance(),
            "not_enabled_in_main_algorithm":True,
            "strict_safety":"reject no previously Stage-1 qualified structure; task queue LB <= audited actual completion",
        },
        "rows":[],
    }
    write_json(args.output,payload)
    for method in METHODS:
        for seed in orig["protocol"]["algorithm_seeds"]:
            base=originals[("baseline",seed,method)]
            fixed_sol=restore_solution(base["solution"])
            expected_hash=base["solution_sha256"]
            if content_hash(fixed_sol)!=expected_hash:
                raise RuntimeError("Source fixed D checksum mismatch")
            for profile in PROFILES:
                instance=restore_instance(orig["profiles"][profile]["instance"])
                for source in ("dynamically_reoptimized","baseline_structure_fixed"):
                    if source=="dynamically_reoptimized":
                        row=originals[(profile,seed,method)]
                        sol=restore_solution(row["solution"])
                        old_ok=bool(row["stage1_qualified"])
                        stage1_vals=(
                            row["stage1"]["values"] if old_ok else None
                        )
                        status=row.get("resources",{}).get("diagnostics",{}).get(
                            "stage1_status","unknown"
                        )
                    else:
                        row=fixedrows[(profile,seed,method)]
                        sol=fixed_sol
                        old_ok=bool(row["stage1_qualified"])
                        stage1_vals=None
                        status=row["stage1_status"]
                    result=evaluate_one(
                        instance,sol,
                        previous_stage1_qualified=old_ok,
                        previous_stage1_values=stage1_vals,
                        label=f"K{K} S{S} A{seed} {profile} {method} {source}",
                        source_status=status,
                    )
                    entry={
                        "source":source,
                        "method":method,
                        "profile":profile,
                        "seed":seed,
                        "solution_sha256":content_hash(sol),
                        **result,
                    }
                    payload["rows"].append(entry)
                    write_json(args.output,payload)
                    if entry["extra_certified_infeasible"]:
                        print(
                            f"NEW_CERTIFICATE K{K} S{S} A{seed} {source} "
                            f"{method} {profile}: "
                            f"status={status}, "
                            f"extra_queue_gap={result['max_task_queue_extension_s']:.3f}s, "
                            f"reasons={result['queue_reason_groups']}",
                            flush=True,
                        )
    payload["summary"]=summarize(payload["rows"])
    payload["complete"]=True
    write_json(args.output,payload)
    print("QUEUE_BOUND_SUMMARY="+json.dumps({
        "tasks":K,"scenario":S,"rows":[
            {k:r[k] for k in
             ("source","method","profile","attempted",
              "previous_strict_stage1_qualified",
              "old_precheck_rejected","queue_precheck_rejected",
              "additional_sound_rejections","false_reject_strict_stage1")}
            for r in payload["summary"]
        ],
    },ensure_ascii=False),flush=True)
    return payload


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--source",type=Path,required=True)
    a.add_argument("--fixed",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    try:
        run(args)
    except Exception as exc:
        if args.output.exists():
            data=json.loads(args.output.read_text(encoding="utf-8"))
            data["execution_error"]={"type":type(exc).__name__,"message":str(exc)}
            write_json(args.output,data)
        raise


if __name__=="__main__":
    main()
