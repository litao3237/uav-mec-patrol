"""M0.3 four-way ablation with identical M0 physical/resource recourse.

No new physics, no historical result mutation and no hidden extra resources.
All four search arms start from the exact same deterministic initial solution,
use 100 ALNS iterations, then run the same independent M0 finalizer/auditor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

from diagnose_m02 import (
    BASE_CVX_SHA, BASE_MODEL_SHA, CONFIG_SHA, FROZEN_S45,
    FROZEN_M0_B_CANDIDATE,
)
from run_seven_methods import PROTOCOL, finalize_task_qos
from uav_mec.algorithms.alns import (
    ScreenedProxyObjectiveEvaluator, UavMecALNSConfig, run_uav_mec_alns,
)
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.initial import (
    build_greedy_initial_solution, build_mec_assisted_initial_solution,
)
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.task_objective import ON_TIME_TOL_S
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


ARMS = (
    ("baseline", "scalar_rrt", "roulette"),
    ("unit_acceptance", "qos_physical_rrt", "roulette"),
    ("unit_credit", "scalar_rrt", "unit_credit_ucb"),
    ("combined", "qos_physical_rrt", "unit_credit_ucb"),
)
M02_SOURCE = "a806f2b40173e643ba5ff39b6f97b0ffdcbc1dba"
CASES = (
    (30, 45, 100), (50, 45, 100), (80, 45, 100),
    (50, 46, 100), (50, 47, 100), (50, 45, 101),
)


def verify_physics_sources():
    for path, expected in (
        ("configs/baseline.yaml", CONFIG_SHA),
        ("src/uav_mec/optimization/resource/cvx_solver.py", BASE_CVX_SHA),
        ("src/uav_mec/optimization/resource/problem.py", BASE_MODEL_SHA),
    ):
        got=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if got != expected:
            raise RuntimeError(f"Physics/config identity changed: {path}")


def normalized_lateness(instance, outcomes: dict) -> float:
    return sum(
        max(0., record["delay_s"] - record["deadline_s"] - ON_TIME_TOL_S)
        / max(1., record["deadline_s"])
        for record in outcomes.values() if record["delay_s"] is not None
    )


def execute(tasks:int, scenario:int, seed:int, output:Path):
    if (tasks,scenario,seed) not in CASES:
        raise ValueError("Requested case is not a registered M0.3 diagnostic")
    if output.exists():
        raise FileExistsError(f"Would overwrite a previous checkpoint: {output}")
    verify_physics_sources()
    cfg=load_paper_scale_config("configs/baseline.yaml")
    instance=replace(build_paper_scale_instance(
        cfg,num_tasks=tasks,num_uavs=PROTOCOL["uavs"],
        num_mecs=PROTOCOL["mecs"],scenario_seed=scenario,
    ),qos_hard=False)
    started=perf_counter()
    route=build_greedy_initial_solution(instance)
    initial=build_mec_assisted_initial_solution(instance,base_solution=route)
    init_s=perf_counter()-started
    instance_hash, init_hash=content_hash(instance),content_hash(initial)
    if scenario==45 and (instance_hash,init_hash)!=FROZEN_S45[tasks]:
        raise RuntimeError(f"Frozen source instance/initial mismatch at K{tasks} S45")
    output.parent.mkdir(parents=True,exist_ok=True)
    report={
        "schema":"m03_unit_acceptance_credit_v1","complete":False,
        "tasks":tasks,"scenario":scenario,"seed":seed,
        "iterations":PROTOCOL["iterations"],
        "base_search_commit":M02_SOURCE,
        "physics_hashes":{
            "cvx_solver":BASE_CVX_SHA,"resource_problem":BASE_MODEL_SHA,
            "config":CONFIG_SHA,
        },
        "initial_sha256":init_hash,"instance_sha256":instance_hash,
        "initialization_s":init_s,
        "registered_arms":[x[0] for x in ARMS],
        "arms":[],
    }
    write_json(output,report)
    for name,acceptance,selection in ARMS:
        evaluator=ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile="m0")
        conf=UavMecALNSConfig(
            iterations=PROTOCOL["iterations"],seed=seed,
            enable_problem_operators=False,
            acceptance_mode=acceptance, selection_mode=selection,
            diagnostic_trace=True,
        )
        started=perf_counter()
        result=run_uav_mec_alns(
            instance,initial_solution=deepcopy(initial),
            config=conf,evaluator=evaluator,
        )
        search_s=perf_counter()-started
        if content_hash(initial)!=init_hash:
            raise RuntimeError("One search arm modified the shared initial solution")
        candidate_sha=content_hash(result.best_solution)
        replay_archive = None
        if name=="baseline" and scenario==45 and seed==100:
            replay_archive=candidate_sha==FROZEN_M0_B_CANDIDATE[tasks]
            if not replay_archive:
                raise RuntimeError(
                    f"M0.2 search replay changed unexpectedly: K{tasks}"
                )
        finalized=finalize_task_qos(
            instance,result.best_solution,method="B-ALNS",seed=seed,
            initialization_s=init_s,search_s=search_s,
            diagnostics={"m03_acceptance":acceptance,"m03_selector":selection},
        )
        m=finalized["metrics"]
        if not m["physical_feasible"]:
            raise RuntimeError("Cannot report an unverified physical ALNS state")
        info=build_event_info(instance,result.best_solution)
        trace=result.search_trace
        if len(trace)!=PROTOCOL["iterations"]:
            raise RuntimeError("Missing ALNS operator/outcome observations")
        outcome_hist={
            name:sum(x["outcome_index"]==i for x in trace)
            for i,name in enumerate(("best","better","accepted","rejected"))
        }
        if sum(outcome_hist.values())!=PROTOCOL["iterations"]:
            raise AssertionError("Incorrect ALNS outcome histogram")
        if selection=="unit_credit_ucb" and len(result.credit_history)!=PROTOCOL["iterations"]:
            raise RuntimeError("Missing unit-aware credit trace")
        if acceptance=="qos_physical_rrt" and not result.acceptance_trace:
            raise RuntimeError("No unit-aware RRT acceptance observations")
        score=(
            -int(m["on_time_tasks"]), normalized_lateness(instance,m["task_outcomes"]),
            float(m["total_energy"]),float(m["route_distance"]),
        )
        item={
            "arm":name,
            "acceptance_mode":acceptance,"selection_mode":selection,
            "search_s":search_s,
            "resource_s":finalized["timing"]["resource_recompute_s"],
            "total_time_s":finalized["timing"]["total_to_resources_s"],
            "on_time":int(m["on_time_tasks"]),
            "success_rate":m["success_rate"],
            "served":m["served_tasks"],
            "unserved":m["unserved_tasks"],
            "late":m["late_tasks"],
            "normalized_lateness":score[1],
            "energy_j":m["total_energy"],
            "stage1_energy_j":m["stage1_energy"],
            "stage2_energy_j":m["stage2_energy"],
            "route_distance_m":m["route_distance"],
            "mean_delay_all_s":m["mean_delay_all"],
            "contact_visits":len(result.best_solution.contact_visits),
            "offloaded_tasks":sum(d.contact_visit_id is not None
                                  for d in result.best_solution.task_decisions.values()),
            "final_signature":hashlib.sha256(
                repr(solution_signature(result.best_solution)).encode()
            ).hexdigest(),
            "candidate_solution_sha256":candidate_sha,
            "accepted_solution_sha256":finalized["solution_sha256"],
            "replicates_m02_m0_reference_sha":replay_archive,
            "initial_search_score":result.initial_objective,
            "best_search_score":result.best_objective,
            "operator_pair_counts":result.operator_pair_counts,
            "outcomes":outcome_hist,
            "operator_trace":trace,
            "acceptance_trace":result.acceptance_trace,
            "credit_trace":result.credit_history,
            "energy_source":m["energy_source"],
            "stage2_status":finalized["stage2"]["status"],
            "admission_source":finalized["admission"]["source"],
            "screening_stats":asdict(evaluator.stats),
            "physical_feasible":m["physical_feasible"],
        }
        report["arms"].append(item)
        write_json(output,report)
        print(json.dumps({
            "K":tasks,"S":scenario,"A":seed,"arm":name,
            "successes":item["on_time"],"energy_j":item["energy_j"],
            "route_distance_m":item["route_distance_m"],
            "search_s":item["search_s"],"physical":item["physical_feasible"],
        },ensure_ascii=False),flush=True)
    report["complete"]=True
    write_json(output,report)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tasks",type=int,required=True)
    p.add_argument("--scenario",type=int,required=True)
    p.add_argument("--seed",type=int,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    execute(a.tasks,a.scenario,a.seed,a.output)
