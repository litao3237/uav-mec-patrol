"""P10 conditional queue-gated one-slot destroy source-replay pilot.

S89-S96 physical settings have already been inspected; THIS IS NOT
AN INDEPENDENT NEW SCENE VALIDATION.

Compare identical original ALNS scalar objective and all repair
operators, with ONLY original "critical_task_removal" replaced:
  original: untouched proxy-critical removal
  queue_chain: original FIFO/EDF deadline+predecessor targets
  queue_guarded_task: queue deadline target when violating, otherwise ORIGINAL critical
  queue_guarded_chain: FIFO/EDF predecessor chain when violating, otherwise ORIGINAL critical
  workload_guarded: high-workload targets on violation, original fallback otherwise

Every arm has same physical input, random seed, destroy/repair counts,
100 iterations and unchanged P1-R resource/Stage2 feasibility audits.
A read-only P7 shadow sidecar counts each newly generated D passing
the queue/staticCPU/joint necessary constraints. It NEVER changes the
returned original score, roulette selection, acceptance, or solver.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from run_p7_alns_shadow_archive import ShadowPrecheckArchive,K80_CASES
from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
    UavMecALNSConfig,build_greedy_initial_solution,
    build_mec_assisted_initial_solution,run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns.queue_operators import queue_guided_task_rank
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,content_hash,write_json,
)

ARMS=("original","queue_chain","queue_guarded_task",
      "queue_guarded_chain","workload_guarded")


def _arm(instance,initial,seed,arm):
    scorer=ShadowPrecheckArchive(
        ScreenedProxyObjectiveEvaluator(),max_saved=5)
    oracle=Stage1CVXObjectiveOracle()
    started=perf_counter()
    hybrid=run_uav_mec_hybrid_alns(
        instance,initial_solution=deepcopy(initial),
        config=UavMecALNSConfig(
            iterations=100,seed=seed,
            enable_problem_operators=False,
            queue_destroy_policy=None if arm=="original" else arm,
        ),
        evaluator=scorer,elite_oracle=oracle,elite_rounds=2,
    )
    search_s=perf_counter()-started
    outcomes={}
    for tag,solution in (
        ("B",hybrid.exploration.best_solution),
        ("ESI",hybrid.best_solution),
    ):
        r=finalize(
            instance,solution,method=f"P10_{arm}_{tag}",
            seed=seed,initialization_s=0.,search_s=search_s,
            diagnostics={"origin":"P10_queue_removal_targeting_dev"},
        )
        strict=r["stage1"]["qualified"] and r["stage2"]["qualified"]
        outcomes[tag]={
            "sha256":content_hash(solution),
            "strict_Stage1":bool(r["stage1"]["qualified"]),
            "strict_Stage2":bool(r["stage2"]["qualified"]),
            "strict_both":bool(strict),
            "original_stage1_status":r["resources"].diagnostics.get("stage1_status"),
            "strict_energy_j":float(r["resources"].energy_stage1_j) if strict else None,
            "qualification_wall_s":float(
                r["timing"]["resource_recompute_s"]+
                r["timing"]["independent_audit_s"]),
        }
    return {
        "B":outcomes["B"],"ESI":outcomes["ESI"],
        "search_wall_s":search_s,
        "complete_wall_s":(
            search_s+sum(x["qualification_wall_s"] for x in outcomes.values())),
        "funnel":scorer.summary(),
        "ESI_elite_skipped":hybrid.elite_stats.get("skipped"),
        "ESI_elite_exact_CVX_calls":oracle.calls,
        "B_best_scalar":float(hybrid.exploration.best_objective),
        "ALNS_operator_outcomes":hybrid.exploration.operator_pair_counts,
    }


def run(source:Path,output:Path,selected):
    if output.exists():raise FileExistsError(output)
    raw=json.loads(source.read_text(encoding="utf-8"))
    p=raw["protocol"]
    scene=int(p["independent_scenario_seed"])
    if not raw.get("complete") or p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Expected original archived strict K80 B/ESI source")
    cases=[(a,int(b)) for a,b in selected]
    if not cases or any((scene,profile,seed) not in K80_CASES
                        for profile,seed in cases):
        raise ValueError("Only previously examined P7 source cases")
    old={(r["profile"],int(r["seed"]),r["method"]):r
         for r in raw["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"P10_original_ALNS_queue_guarded_original_fallback_100iterations_dev_v1",
            "scene":scene,
            "original_archive_sha256":content_hash(raw),
            "compared_arms":list(ARMS),
            "original_RRT_unchanged":True,
            "all_existing_ALNS_repair_operators_unchanged":True,
            "only_one_critical_destroy_operator_replaced":True,
            "original_critical_fallback_when_queue_task_deadlines_satisfied":True,
            "identical_original_ScreenedProxyObjectiveEvaluator":True,
            "same_ALNS_100_iterations_and_original_elite_2_rounds":True,
            "all_original_P1R_stage1_and_stage2_strict_audit_unchanged":True,
            "same_read_only_observer_all_methods":True,
            "previously_used_development_cases":True,
            "NOT_matching_total_wall_time":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,payload)
    for profile,seed in cases:
        inst=restore_instance(raw["profiles"][profile]["instance"])
        if content_hash(inst)!=raw["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Frozen physical profile mismatch")
        orig=old[profile,seed,"B-ALNS"]
        initial=build_mec_assisted_initial_solution(
            inst,base_solution=build_greedy_initial_solution(inst))
        sha=content_hash(initial)
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "frozen_initial_sha256":sha,
            "old_B_sha256":orig["solution_sha256"],
            "old_B_stage1_status":(
                ((orig.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status")),
            "top_original_queue_task_targets":{
                pol:queue_guided_task_rank(inst,initial,policy=pol)[0][:12]
                for pol in QUEUE_DESTROY_POLICIES
            },
            "arms":{},
        }
        payload["rows"].append(row)
        write_json(output,payload)
        for arm in ARMS:
            try:
                outcome=_arm(inst,initial,seed,arm)
                if content_hash(initial)!=sha:
                    raise RuntimeError("Original shared initial mutated")
                if arm=="original" and outcome["B"]["sha256"]!=orig["solution_sha256"]:
                    raise RuntimeError("Modified old ALNS baseline B endpoint")
                row["arms"][arm]=outcome
                print("P10_QUEUE_DESTROY_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                    "B_strict":outcome["B"]["strict_both"],
                    "ESI_strict":outcome["ESI"]["strict_both"],
                    "queue_passed":outcome["funnel"]["counters"].get(
                        "queue_necessary_pass",0),
                    "joint_passed":outcome["funnel"]["counters"].get(
                        "joint_bw_cpu_necessary_pass",0),
                    "runtime_s":round(outcome["complete_wall_s"],3),
                },ensure_ascii=False),flush=True)
            except Exception as exc:
                error={
                    "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                    "type":type(exc).__name__,"message":str(exc)}
                payload["errors"].append(error)
                row["arms"][arm]={"error":error}
                print("P10_QUEUE_DESTROY_ERROR="+json.dumps(error),flush=True)
            write_json(output,payload)
    payload["complete"]=True
    payload["summary"]={
        "cases":len(payload["rows"]),
        "strict_ESI":{a:sum(
            r["arms"].get(a,{}).get("ESI",{}).get("strict_both",False)
            for r in payload["rows"]) for a in ARMS},
        "original_SHA_reproduced":sum(
            r["arms"].get("original",{}).get("B",{}).get("sha256")==r["old_B_sha256"]
            for r in payload["rows"]),
        "errors":len(payload["errors"]),
    }
    write_json(output,payload)
    print("P10_QUEUE_DESTROY_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"P10 original search replay or operator failed: {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--cases",required=True)
    ap.add_argument("--output",type=Path,required=True)
    p=ap.parse_args()
    selected=[x.split(":") for x in p.cases.split(",")]
    run(p.source,p.output,selected)
