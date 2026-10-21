"""M0.2 controlled ALNS score/selector/acceptance experiment.

Both scores use the *same* M0 physical model, proxy and CVX recourse.
The legacy-score arm reproduces only the old scalar compression formula,
NOT the old v26 codebase or solver. Every final discrete candidate is
re-evaluated with the identical frozen M0 admission/Stage-1/Stage-2/audit.
No old outcome is substituted for an actual new resource calculation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from time import perf_counter

from uav_mec.algorithms.alns import (
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.initial import (
    build_greedy_initial_solution, build_mec_assisted_initial_solution,
)
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.task_objective import ON_TIME_TOL_S
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config

from run_seven_methods import PROTOCOL, finalize_task_qos


# Exact frozen M0 scene/S45 hashes, captured from verified run #39456198442.
FROZEN_S45 = {
    30: ("e763c889e2e72014c4d2d69e1d34446841c71bb1b9f419291fe734384f84d437",
         "dea7b7d2088b84957908ce8ea3ef51c21aafcdc0913e2d6c5e66431a918ff354"),
    50: ("5030ec70674cd4c65a1e3dfe110f984c3e62ad9bce2f38ea50354d68cc5b4f7e",
         "8062ed6784b69129841267d746e092fafb25bfde1bb0bc5ad1b7b47cca2725e3"),
    80: ("b0a997ecc4e79241cb9b0e2e2904df812e26a58ae5847ad615f757948b8bad03",
         "ae7e5b66bbc4bf2dfacde41b4910427cf30f0a75ef199957a9e4d41609d92c15"),
}

# The original M0 K30/50/80 B-ALNS candidate SHA under the same S45 A100.
FROZEN_M0_B_CANDIDATE = {
    30: "9daf537ae071ab9236ff7223bdae42af3616f5b7492712b8c9c8d63e1e7f507d",
    50: "4b60924af88df5e6ee26d55a8b89a6a7c0bb0227b78b5cca5b2c71bd261e4bb6",
    80: "894ea7c519683c618c7c82e9ffe4a49d796d0c136a9e13d9563827c88eade3cf",
}
BASE_M0 = "540e7b3193d28feb9bca57eb9998a8098c91c2a3"
BASE_CVX_SHA = "3e5e42360e00dcc8b0c015eddfa1871683ac378ab380787b6376332d9311283e"
BASE_MODEL_SHA = "86c96689b5176702e1fef742f7a828819e40401019404e496d307228109d3ec8"
CONFIG_SHA = "279a0bf295fc3a078a726fd2f633270746380489639cd784dd484a420b63bcc1"
SCORING_PROFILES = {"v26_scale", "m0"}


def arms(factorial: bool) -> list[tuple[str, str, float, float]]:
    primary = [
        ("legacy_adaptive_rrt", "v26_scale", .8, .02),
        ("m0_adaptive_rrt", "m0", .8, .02),
    ]
    if not factorial:
        return primary
    return primary + [
        ("legacy_frozen_rrt", "v26_scale", 1.0, .02),
        ("m0_frozen_rrt", "m0", 1.0, .02),
        ("legacy_adaptive_greedy", "v26_scale", .8, 0.0),
        ("m0_adaptive_greedy", "m0", .8, 0.0),
    ]


def summarize_trace(trace: list[dict], initial_objective: float) -> dict:
    counts = [sum(x["outcome_index"] == i for x in trace) for i in range(4)]
    pairs = {}
    for x in trace:
        key = f'{x["destroy"]} -> {x["repair"]}'
        p = pairs.setdefault(key, {"chosen":0, "best":0, "better":0, "accepted":0, "rejected":0})
        p["chosen"] += 1
        p[("best", "better", "accepted", "rejected")[x["outcome_index"]]] += 1
    return {
        "iterations_recorded": len(trace),
        "outcome_best": counts[0],
        "outcome_better": counts[1],
        "outcome_accepted": counts[2],
        "outcome_rejected": counts[3],
        "unique_candidate_structures": len({t["candidate_structure_sha256"] for t in trace}),
        "unique_operator_pairs": len(pairs),
        "operator_pair_outcomes": pairs,
        "candidate_distance_range_m": [
            min([x["candidate_distance_m"] for x in trace], default=None),
            max([x["candidate_distance_m"] for x in trace], default=None),
        ],
        "initial_objective": initial_objective,
    }


def execute(tasks: int, scenario: int, seed: int, factorial: bool, output: Path):
    if output.exists():
        raise FileExistsError(f"Will not overwrite {output}")
    if not tasks in (30,50,80) or scenario not in (45,46,47,48) or seed not in (100,101,102):
        raise ValueError("Only registered frozen task/seed ranges are accepted")
    cfgfile = Path("configs/baseline.yaml")
    if hashlib.sha256(cfgfile.read_bytes()).hexdigest() != CONFIG_SHA:
        raise RuntimeError("M0.2 must use the frozen v26/M0 scenario settings")
    for filename, expected in [
        ("src/uav_mec/optimization/resource/cvx_solver.py", BASE_CVX_SHA),
        ("src/uav_mec/optimization/resource/problem.py", BASE_MODEL_SHA),
    ]:
        actual = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Resource source changed: {filename}")
    cfg = load_paper_scale_config(cfgfile)
    instance = build_paper_scale_instance(
        cfg, num_tasks=tasks, num_uavs=PROTOCOL["uavs"],
        num_mecs=PROTOCOL["mecs"], scenario_seed=scenario,
    )
    instance = replace(instance, qos_hard=False)
    initial_started = perf_counter()
    greedy = build_greedy_initial_solution(instance)
    initial = build_mec_assisted_initial_solution(instance, base_solution=greedy)
    init_time = perf_counter() - initial_started
    instance_hash, initial_hash = content_hash(instance), content_hash(initial)
    if scenario == 45 and (instance_hash, initial_hash) != FROZEN_S45[tasks]:
        raise RuntimeError(f"Frozen M0 input does not match original: K{tasks} scenario {scenario}")
    initial_signature = repr(solution_signature(initial))
    payload = {
        "schema": "m02_score_factorial_v1", "complete": False,
        "tasks":tasks, "scenario":scenario, "seed":seed,
        "factorial":factorial, "base_resource_commit":BASE_M0,
        "resource_source_shas":{"cvx_solver.py":BASE_CVX_SHA,"problem.py":BASE_MODEL_SHA},
        "config_sha256":CONFIG_SHA,
        "instance_sha256":instance_hash, "initial_sha256":initial_hash,
        "initial_structure_signature":hashlib.sha256(initial_signature.encode()).hexdigest(),
        "initialization_s":init_time,
        "iterations":PROTOCOL["iterations"], "arms":[],
    }
    write_json(output,payload)
    for arm_name, profile, decay, start_gap in arms(factorial):
        evaluator=ScreenedProxyObjectiveEvaluator(soft_qos_scalar_profile=profile)
        alg_cfg=UavMecALNSConfig(
            iterations=PROTOCOL["iterations"], seed=seed,
            enable_problem_operators=False, operator_decay=decay,
            rrt_start_gap=start_gap, rrt_end_gap=0., diagnostic_trace=True,
        )
        started=perf_counter()
        result=run_uav_mec_alns(
            instance, initial_solution=deepcopy(initial),
            config=alg_cfg, evaluator=evaluator,
        )
        search_s=perf_counter()-started
        if content_hash(initial) != initial_hash:
            raise AssertionError("ALNS modified shared initial solution")
        # Control: The full M0 arm must replay the archived B exploration
        # with the same seed, initial input and fixed iteration count.
        candidate_hash = content_hash(result.best_solution)
        reference_check = None
        if scenario==45 and seed==100 and arm_name=="m0_adaptive_rrt":
            reference_check=(candidate_hash == FROZEN_M0_B_CANDIDATE[tasks])
        # All arms go through the *same* frozen M0 physical admission,
        # Stage-1A + Stage-1B, Stage-2 and independent physical audit.
        finalized=finalize_task_qos(
            instance, result.best_solution,
            method="B-ALNS", seed=seed,
            initialization_s=init_time, search_s=search_s,
            diagnostics={"m02_arm":arm_name,"scalar_profile":profile},
        )
        vals=finalized["metrics"]
        trace=result.search_trace
        if len(trace)!=PROTOCOL["iterations"]:
            raise RuntimeError(f"Missing selection/acceptance trace: {len(trace)}")
        info=build_event_info(instance,result.best_solution)
        payload["arms"].append({
            "arm":arm_name, "scalar_profile":profile, "selector_decay":decay,
            "rrt_start_gap":start_gap, "iterations":PROTOCOL["iterations"],
            "initial_score":result.initial_objective,
            "rrt_initial_absolute_gap":start_gap*result.initial_objective,
            "best_search_score":result.best_objective,
            "candidate_solution_sha256":candidate_hash,
            "candidate_structure_sha256":hashlib.sha256(
                repr(solution_signature(result.best_solution)).encode()).hexdigest(),
            "reference_m0_search_sha_match":reference_check,
            "route_distance_before_admission_m":sum(info.route_distance_m.values()),
            "contact_visits_before_admission":len(result.best_solution.contact_visits),
            "mode_offload_tasks":sum(d.contact_visit_id is not None
                                       for d in result.best_solution.task_decisions.values()),
            "trace":trace, "trace_summary":summarize_trace(trace,result.initial_objective),
            "selector_counts":result.operator_pair_counts,
            "search_s":search_s,
            "resources_s":finalized["timing"]["resource_recompute_s"],
            "total_s":finalized["timing"]["total_to_resources_s"],
            "physical_feasible":vals["physical_feasible"],
            "successes":vals["on_time_tasks"], "served":vals["served_tasks"],
            "late_tasks":vals["late_tasks"], "unserved":vals["unserved_tasks"],
            "total_energy_j":vals["total_energy"],"stage1_energy_j":vals["stage1_energy"],
            "stage2_energy_j":vals["stage2_energy"],
            "route_distance_m":vals["route_distance"],
            "mean_delay_all_s":vals["mean_delay_all"],
            "mean_delay_success_s":vals["mean_delay_success"],
            "p95_delay_all_s":vals["p95_delay_all"],
            "energy_source":vals["energy_source"],
            "stage2_status":finalized["stage2"]["status"],
            "admission_source":finalized["admission"]["source"],
        })
        write_json(output,payload)
        print(json.dumps({
            "arm":arm_name,"k":tasks,"scenario":scenario,"seed":seed,
            "successes":vals["on_time_tasks"],
            "energy_j":vals["total_energy"],
            "distance_m":vals["route_distance"],
            "search_s":search_s,
            "reference_m0_search_sha_match":reference_check,
        },ensure_ascii=False),flush=True)
    payload["complete"]=True
    write_json(output,payload)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--tasks",type=int,required=True)
    p.add_argument("--scenario",type=int,required=True)
    p.add_argument("--seed",type=int,required=True)
    p.add_argument("--factorial",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    execute(args.tasks,args.scenario,args.seed,args.factorial,args.output)


if __name__=="__main__":
    main()
