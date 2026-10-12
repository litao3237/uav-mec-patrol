"""P8 frozen FIRST-USE original-ALNS wall-budget controlled evaluation.

S101-S104 were not used for P0-P8 algorithm development. Freeze
physical profiles and two nested stochastic seeds before observing
any S101-S104 experimental result.

Three arms differ ONLY in objective evaluation DURING the original
ALNS exploration: old original, FIFO/EDF normalized sum gradient, and
FIFO/EDF worst-violation gradient. The original destroy/repair, RRT
acceptance implementation, CVX Stage1 and Stage2 physical constraints,
elite intensification and residual thresholds are NOT altered.

All arms receive equal 6-second exploration MaxRuntime and the same
2-second cap for original ESI elite intensification. The original
Stage1 CVX, Stage2 and read-only output audits are included in the
reported ACTUAL total runtime. This is matched exploration+elite
clock budgets, NOT a strict hard cap on all numerical solver calls:
a running conic optimizer can finish past a specified deadline, and
final independent audits have variable cost. Report both budget and
actual complete end-to-end wall time transparently.

The same read-only observation is added to ALL arms to count each
visited D and its queue/staticCPU/joint necessary feasibility stage.
This incurs measured overhead INSIDE each arm's 6s runtime; no oracle
is secretly called on extra candidate snapshots.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from queue_guided_alns_evaluator import QueueGuidedObjectiveEvaluator
from run_p8_queue_alns_pilot import ARMS,P8ReadOnlyFunnel
from run_seven_methods import finalize
from run_model_sensitivity import (
    make_profile,shared_task_geometry_hash,describe_instance,PROFILES
)
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
    UavMecALNSConfig,build_greedy_initial_solution,
    build_mec_assisted_initial_solution,run_uav_mec_hybrid_alns,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash,write_json,
)
from uav_mec.instances import build_paper_scale_instance,load_paper_scale_config

NEW_SCENARIOS=(101,102,103,104)
ALGORITHM_SEEDS=(137,138)
PROFILES_TO_RUN=(
    "baseline","compute_x1p5","compute_x2p0",
    "deadline_x0p9","deadline_x0p8",
)
EXPLORATION_CLOCK_SECONDS=6.
ELITE_CLOCK_SECONDS=2.
SOURCE_CONFIG=Path("configs/baseline.yaml")


def _audit(instance,solution,*,name,seed,actual_search_elapsed_s):
    saved=finalize(
        instance,solution,method=name,seed=seed,
        initialization_s=0.,search_s=actual_search_elapsed_s,
        diagnostics={"origin":"P8_new_scenario_matched_wall_search"},
    )
    both=bool(saved["stage1"]["qualified"] and saved["stage2"]["qualified"])
    return {
        "solution_sha256":content_hash(solution),
        "strict_Stage1":bool(saved["stage1"]["qualified"]),
        "strict_Stage2":bool(saved["stage2"]["qualified"]),
        "strict_both":both,
        "Stage1_status":saved["resources"].diagnostics.get("stage1_status"),
        "Stage2_status":saved["resources"].diagnostics.get("stage2_status"),
        "energy_j":float(saved["resources"].energy_stage1_j) if both else None,
        "resource_audit_wall_s":float(
            saved["timing"]["resource_recompute_s"]+
            saved["timing"]["independent_audit_s"]),
    }


def _run_arm(instance,initial,seed,arm,initialization_s):
    evaluator=(ScreenedProxyObjectiveEvaluator() if arm=="original"
               else QueueGuidedObjectiveEvaluator(policy=arm))
    observer=P8ReadOnlyFunnel(evaluator)
    oracle=Stage1CVXObjectiveOracle()
    search_begin=perf_counter()
    hybrid=run_uav_mec_hybrid_alns(
        instance,
        initial_solution=deepcopy(initial),
        config=UavMecALNSConfig(
            iterations=100000,seed=seed,
            enable_problem_operators=False,
            max_runtime_s=EXPLORATION_CLOCK_SECONDS,
            time_scaled_rrt=True,
        ),
        evaluator=observer,elite_rounds=2,elite_oracle=oracle,
        exploration_max_runtime_s=EXPLORATION_CLOCK_SECONDS,
        elite_max_runtime_s=ELITE_CLOCK_SECONDS,
    )
    entire_hybrid_search_s=perf_counter()-search_begin
    audits={
        name:_audit(
            instance,sol,
            name=f"P8_firstuse_{arm}_{name}",
            seed=seed,
            actual_search_elapsed_s=entire_hybrid_search_s,
        )
        for name,sol in (
            ("B",hybrid.exploration.best_solution),
            ("ESI",hybrid.best_solution),
        )
    }
    return {
        "arm":arm,
        "B":audits["B"],"ESI":audits["ESI"],
        "B_search_iterations":len(hybrid.exploration.raw_result.objectives)-1,
        "B_best_scalar":float(hybrid.exploration.best_objective),
        "ESI_elite_skipped":hybrid.elite_stats.get("skipped"),
        "ESI_elite_stats":hybrid.elite_stats,
        "ESI_exact_oracle_calls":oracle.calls,
        "ESI_Stage1_solve_records":oracle.solve_records,
        "feasibility_funnel":observer.summary(),
        "initialization_wall_s_shared":initialization_s,
        "original_B_exploration_wall_s":hybrid.exploration_runtime_s,
        "original_ESI_elite_phase_wall_s":hybrid.elite_phase_runtime_s,
        "hybrid_explore_and_elite_wall_s":entire_hybrid_search_s,
        "original_BESI_independent_audits_wall_s":sum(
            v["resource_audit_wall_s"] for v in audits.values()),
        "actual_end_to_end_wall_s":(
            initialization_s+entire_hybrid_search_s+
            sum(v["resource_audit_wall_s"] for v in audits.values())),
        "budget_exploration_s":EXPLORATION_CLOCK_SECONDS,
        "budget_elite_phase_s":ELITE_CLOCK_SECONDS,
        "no_hard_end_to_end_wall_cap":True,
    }


def run(scene,output_dir:Path):
    if scene not in NEW_SCENARIOS:
        raise ValueError("Only preregistered new S101-S104 physical scenarios")
    if output_dir.exists() and list(output_dir.iterdir()):
        raise FileExistsError("Do not overwrite unseen evidence")
    output_dir.mkdir(parents=True,exist_ok=True)
    destination=output_dir/f"p8-fresh-K80_S{scene}.json"
    cfg=load_paper_scale_config(SOURCE_CONFIG)
    base=build_paper_scale_instance(
        cfg,num_tasks=80,num_uavs=5,num_mecs=2,
        scenario_seed=scene,
    )
    base_hash=content_hash(base)
    geometry=shared_task_geometry_hash(base)
    payload={
        "complete":False,
        "protocol":{
            "id":"P8_QueueGradient_FirstUse_EqualExplorationClock_S101_S104_v1",
            "scenario":scene,
            "task_scale":80,
            "independent_new_physical_scenarios":list(NEW_SCENARIOS),
            "nested_algorithm_seeds":list(ALGORITHM_SEEDS),
            "all_frozen_stress_profiles":list(PROFILES_TO_RUN),
            "methods":list(ARMS),
            "same_original_greedy_MEC_initial_D":True,
            "original_ALNS_destroy_repair_unmodified":True,
            "original_ESI_elite_rounds":2,
            "same_exploration_wall_budget_s":EXPLORATION_CLOCK_SECONDS,
            "same_elite_wall_cap_s":ELITE_CLOCK_SECONDS,
            "time_scaled_original_RRT_for_wall_budget":True,
            "original_P1R_Stage1_and_Stage2_independent_audit":True,
            "read_only_feasibility_observer_in_all_arms":True,
            "all_seed_variants_nested_within_physical_scenario":True,
            "actual_complete_run_wall_time_explicitly_reported":True,
            "strict_hard_end_to_end_time_matched":False,
            "config_sha256":sha256(SOURCE_CONFIG.read_bytes()).hexdigest(),
            "physical_base_sha256":base_hash,
            "physical_geometry_sha256":geometry,
        },
        "profiles":{},"rows":[],"errors":[],
    }
    write_json(destination,payload)
    for profile in PROFILES_TO_RUN:
        instance=make_profile(base,profile)
        if content_hash(base)!=base_hash:
            raise RuntimeError("Original baseline physical input mutated")
        if shared_task_geometry_hash(instance)!=geometry:
            raise RuntimeError("Paired physical scenario geometry was altered")
        payload["profiles"][profile]={
            "instance_sha256":content_hash(instance),
            "geometry_sha256":geometry,
            "summary":describe_instance(
                instance,
                configured_fastest_cpu=max(site.cpu_ghz for site in cfg.mec_sites),
            ),
            "factor":PROFILES[profile][0],
            "multiplier":PROFILES[profile][1],
        }
        write_json(destination,payload)
        for seed in ALGORITHM_SEEDS:
            initialized_at=perf_counter()
            initial=build_mec_assisted_initial_solution(
                instance,
                base_solution=build_greedy_initial_solution(instance))
            init_s=perf_counter()-initialized_at
            init_hash=content_hash(initial)
            row={
                "scenario":scene,"profile":profile,"seed":seed,
                "initial_solution_sha256":init_hash,
                "initialization_wall_s":init_s,
                "arms":{},
            }
            payload["rows"].append(row)
            write_json(destination,payload)
            for arm in ARMS:
                try:
                    measure=_run_arm(instance,initial,seed,arm,init_s)
                    if content_hash(initial)!=init_hash:
                        raise RuntimeError("Shared initial solution was mutated")
                    row["arms"][arm]=measure
                    print("P8_FIRSTUSE_CASE="+json.dumps({
                        "scene":scene,"profile":profile,"seed":seed,
                        "arm":arm,
                        "B_Strict":measure["B"]["strict_both"],
                        "ESI_Strict":measure["ESI"]["strict_both"],
                        "ESI_Energy":measure["ESI"]["energy_j"],
                        "unique_D":measure["feasibility_funnel"]["counters"].get("unique_visited",0),
                        "queue_pass_D":measure["feasibility_funnel"]["counters"].get("queue_necessary_pass",0),
                        "joint_pass_D":measure["feasibility_funnel"]["counters"].get("joint_bw_cpu_necessary_pass",0),
                        "actual_full_wall":round(measure["actual_end_to_end_wall_s"],3),
                    },ensure_ascii=False),flush=True)
                except Exception as exc:
                    error={
                        "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                        "type":type(exc).__name__,"message":str(exc),
                    }
                    payload["errors"].append(error)
                    row["arms"][arm]={"error":error}
                    print("P8_FIRSTUSE_ERROR="+json.dumps(error),flush=True)
                write_json(destination,payload)
    payload["complete"]=True
    payload["summary"]={
        "experiment_rows":len(payload["rows"]),
        "strict_both":{arm:sum(
            bool(r["arms"].get(arm,{}).get("ESI",{}).get("strict_both"))
            for r in payload["rows"]) for arm in ARMS},
        "unexpected_errors":len(payload["errors"]),
    }
    write_json(destination,payload)
    print("P8_FIRSTUSE_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError("P8 new physical source had numerical/program errors: "+
                           str(payload["errors"][:2]))
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario",type=int,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    opts=p.parse_args()
    run(opts.scenario,opts.output_dir)
