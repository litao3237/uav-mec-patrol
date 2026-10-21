"""M0.4 domain-aware operator feedback, frozen M0 resource and acceptance.

Five selectors differ ONLY in reward signals (M0.3 unit credit baseline, plus
flight cost, MEC-associated delay benefit, deadline pressure, and all three).
Original v26/M0/M0.1/M0.2/M0.3 results are read-only historical controls.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from time import perf_counter

from diagnose_m02 import (
    BASE_CVX_SHA, BASE_MODEL_SHA, CONFIG_SHA, FROZEN_S45,
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
from uav_mec.evaluation.task_objective import ON_TIME_TOL_S
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config

ARMS = (
    ("m03_unit_credit", "unit_credit_ucb", ()),
    ("flight_only", "domain_credit_ucb", ("flight",)),
    ("mec_only", "domain_credit_ucb", ("mec",)),
    ("deadline_only", "domain_credit_ucb", ("deadline",)),
    ("domain_all", "domain_credit_ucb", ("flight", "mec", "deadline")),
)
# 6 previously evaluated cases plus 5 untouched hold-out blocks. Weights are
# frozen before observing S48/S49/S50 outcomes.
CASES = (
    (30, 45, 100), (30, 48, 100),
    (50, 45, 100), (50, 45, 101), (50, 46, 100), (50, 47, 100),
    (50, 48, 100), (50, 49, 100), (50, 50, 100),
    (80, 45, 100), (80, 48, 100),
)
REFERENCE_M03_UCB = {
    (30,45,100): "a451b4a8f16436118323c65326d5ec404859b1a9e3e33cf64fd66a11262b882d",
    (50,45,100): "2d3a08fc13ef802e84eb093df74520f834e38efe67ef062c2d82e910b125904d",
    (50,45,101): "85ec9c9924045810c850179efcf5ba0a371bc1db3a30fff319528db88d0d239d",
    (50,46,100): "bf8cefe02ac4133cad7d6711c48af92888262bd4ec92683dbb8fe0088ca13a3e",
    (50,47,100): "55eadb87b71604e21bc43be2975369ec88389748c7c53efabee3653b68019e7b",
    (80,45,100): "b308a2e7850394476b4a99858fe394d21fd5cc6ccec0b0407dbcb8f6ebf0fa33",
}
M03_COMMIT = "7d116d692c7e97550e2dde1348d79c3164a10bd0"


def verify_source():
    for path, expected in (
        ("configs/baseline.yaml", CONFIG_SHA),
        ("src/uav_mec/optimization/resource/cvx_solver.py", BASE_CVX_SHA),
        ("src/uav_mec/optimization/resource/problem.py", BASE_MODEL_SHA),
    ):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"M0 source/config fingerprint mismatch: {path}")


def lateness(instance, task_outcomes: dict) -> float:
    return sum(
        max(0.0, event["delay_s"] - event["deadline_s"] - ON_TIME_TOL_S)
        / max(1.0, event["deadline_s"])
        for event in task_outcomes.values()
        if event["delay_s"] is not None
    )


def run(tasks: int, scenario: int, seed: int, output: Path):
    if (tasks, scenario, seed) not in CASES:
        raise ValueError("M0.4 case outside predeclared experimental matrix")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite M0.4 checkpoint: {output}")
    verify_source()
    cfg=load_paper_scale_config("configs/baseline.yaml")
    instance=replace(build_paper_scale_instance(
        cfg,num_tasks=tasks,num_uavs=PROTOCOL["uavs"],
        num_mecs=PROTOCOL["mecs"],scenario_seed=scenario,
    ),qos_hard=False)
    t0=perf_counter()
    route=build_greedy_initial_solution(instance)
    initial=build_mec_assisted_initial_solution(instance,base_solution=route)
    initialization_s=perf_counter()-t0
    instance_sha,initial_sha=content_hash(instance),content_hash(initial)
    if scenario==45 and (instance_sha,initial_sha)!=FROZEN_S45[tasks]:
        raise RuntimeError("Not the same source instance/initialization as M0")
    data={
        "schema":"m04_domain_credit_v1","complete":False,
        "tasks":tasks,"scenario":scenario,"seed":seed,
        "holdout":scenario in (48,49,50),"iterations":PROTOCOL["iterations"],
        "source_m03_commit":M03_COMMIT,
        "resource_source_hashes":{
            "cvx":BASE_CVX_SHA,"problem":BASE_MODEL_SHA,"config":CONFIG_SHA,
        },
        "instance_sha256":instance_sha,"initial_sha256":initial_sha,
        "initialization_s":initialization_s,
        "registered_arms":[a[0] for a in ARMS],
        "arms":[],
    }
    write_json(output,data)
    for arm,selector,components in ARMS:
        evaluator=ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile="m0")
        config=UavMecALNSConfig(
            iterations=PROTOCOL["iterations"],seed=seed,
            enable_problem_operators=False,
            selection_mode=selector,acceptance_mode="scalar_rrt",
            domain_credit_components=components if components else ("flight","mec","deadline"),
            diagnostic_trace=True,
        )
        t1=perf_counter()
        result=run_uav_mec_alns(
            instance,initial_solution=deepcopy(initial),
            config=config,evaluator=evaluator,
        )
        search_s=perf_counter()-t1
        if content_hash(initial)!=initial_sha:
            raise AssertionError("Shared initial route was mutated by an ALNS arm")
        candidate_sha=content_hash(result.best_solution)
        reproduction_check=None
        if arm=="m03_unit_credit" and (tasks,scenario,seed) in REFERENCE_M03_UCB:
            reproduction_check=(candidate_sha==REFERENCE_M03_UCB[(tasks,scenario,seed)])
            if not reproduction_check:
                raise RuntimeError("M0.3 unit-credit reference candidate did not reproduce")
        result_metrics=finalize_task_qos(
            instance,result.best_solution,
            method="B-ALNS",seed=seed,
            initialization_s=initialization_s,search_s=search_s,
            diagnostics={"m04_arm":arm,"m04_components":components},
        )
        m=result_metrics["metrics"]
        trace=result.search_trace
        if len(trace)!=PROTOCOL["iterations"]:
            raise RuntimeError(f"ALNS missing {PROTOCOL['iterations']} trace records")
        if len(result.credit_history)!=PROTOCOL["iterations"]:
            raise RuntimeError("Missing unit-credit feedback records")
        if selector=="domain_credit_ucb" and len(result.domain_history)!=PROTOCOL["iterations"]:
            raise RuntimeError("Missing domain features; feedback was not applied")
        if selector=="unit_credit_ucb" and result.domain_history:
            raise RuntimeError("Baseline selector was contaminated by M0.4 feedback")
        if not m["physical_feasible"]:
            raise RuntimeError("Invalid physical recourse unexpectedly accepted")
        event={
            "arm":arm,"selector":selector,"components":list(components),
            "iterations":PROTOCOL["iterations"],
            "candidate_solution_sha256":candidate_sha,
            "reproduced_m03_reference":reproduction_check,
            "structure_sha256":hashlib.sha256(
                repr(solution_signature(result.best_solution)).encode()
            ).hexdigest(),
            "search_s":search_s,
            "resource_s":result_metrics["timing"]["resource_recompute_s"],
            "total_s":result_metrics["timing"]["total_to_resources_s"],
            "on_time":m["on_time_tasks"],"served":m["served_tasks"],
            "late":m["late_tasks"],"unserved":m["unserved_tasks"],
            "normalized_lateness":lateness(instance,m["task_outcomes"]),
            "energy_j":m["total_energy"],"stage1_energy_j":m["stage1_energy"],
            "stage2_energy_j":m["stage2_energy"],
            "route_distance_m":m["route_distance"],
            "mean_delay_all_s":m["mean_delay_all"],
            "contact_visits":len(result.best_solution.contact_visits),
            "offloaded_tasks":sum(
                d.contact_visit_id is not None
                for d in result.best_solution.task_decisions.values()
            ),
            "physical_feasible":m["physical_feasible"],
            "stage2_status":result_metrics["stage2"]["status"],
            "admission_source":result_metrics["admission"]["source"],
            "energy_source":m["energy_source"],
            "screening_stats":asdict(evaluator.stats),
            "pair_counts":result.operator_pair_counts,
            "credit_history":result.credit_history,
            "domain_history":result.domain_history,
            "operator_trace":trace,
        }
        data["arms"].append(event)
        write_json(output,data)
        print(json.dumps({
            "K":tasks,"S":scenario,"A":seed,"arm":arm,
            "successes":event["on_time"],"energy_j":event["energy_j"],
            "route_m":event["route_distance_m"],
            "search_s":event["search_s"],"stage2":event["stage2_status"],
        },ensure_ascii=False),flush=True)
    data["complete"]=True
    write_json(output,data)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--tasks",type=int,required=True)
    parser.add_argument("--scenario",type=int,required=True)
    parser.add_argument("--seed",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.tasks,args.scenario,args.seed,args.output)
