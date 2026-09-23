from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from uav_mec.algorithms import (
    UavMecALNSConfig,
    run_uav_mec_alns,
    run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.initial import (
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
)
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


METHODS = ["GR-MR", "FTR-NM", "RGA-MR", "B-ALNS", "ESI-ALNS"]


def parse_ints(value: str) -> list[int]:
    return [int(x) for x in value.split(",") if x.strip()]


def stage1_result(instance, solution):
    from uav_mec.algorithms import Stage1CVXObjectiveOracle

    oracle = Stage1CVXObjectiveOracle()
    result = oracle.solve(instance, solution)
    status = str(result.diagnostics.get("stage1_status", result.status))
    strict = bool(result.feasible and status == "optimal")
    return {
        "strict": strict,
        "stage1_status": status,
        "energy_j": float(result.energy_stage1_j) if strict else None,
    }


def run_method(instance, method: str, seed: int):
    if method == "GR-MR":
        sol = build_greedy_initial_solution(instance)
    elif method == "FTR-NM":
        sol = build_mec_assisted_initial_solution(
            instance,
            base_solution=build_greedy_initial_solution(instance),
        )
    elif method == "RGA-MR":
        return run_uav_mec_alns(
            instance,
            config=UavMecALNSConfig(seed=seed, iterations=100),
        )
    elif method == "B-ALNS":
        return run_uav_mec_alns(
            instance,
            config=UavMecALNSConfig(seed=seed, iterations=100),
        )
    else:
        return run_uav_mec_hybrid_alns(
            instance,
            config=UavMecALNSConfig(seed=seed, iterations=100),
        )

    validate_solution(instance, sol)
    return sol


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default="30,40,60,70")
    parser.add_argument("--scenario-seeds", default="45,46,47,48,49,50,51,52")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--output", default="outputs/results/multiscale_baseline.json")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=5)
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    rows = []

    for k in parse_ints(args.tasks):
        for scenario in parse_ints(args.scenario_seeds):
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=k,
                num_uavs=args.uavs,
                num_mecs=args.mecs,
                scenario_seed=scenario,
            )
            for seed in parse_ints(args.algorithm_seeds):
                for method in METHODS:
                    result = run_method(instance, method, seed)
                    if hasattr(result, "best_solution"):
                        solution = result.best_solution
                    elif hasattr(result, "solution"):
                        solution = result.solution
                    else:
                        solution = result
                    rows.append({
                        "tasks": k,
                        "scenario_seed": scenario,
                        "algorithm_seed": seed,
                        "method": method,
                        **stage1_result(instance, solution),
                    })

    payload = {
        "experiment": "multiscale_baseline_expansion",
        "tasks": parse_ints(args.tasks),
        "methods": METHODS,
        "rows": rows,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "rows": len(rows),
        "strict": sum(r["strict"] for r in rows),
        "mean_energy": mean([r["energy_j"] for r in rows if r["energy_j"]]) if rows else None,
    }, indent=2))


if __name__ == "__main__":
    main()
