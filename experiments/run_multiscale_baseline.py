from __future__ import annotations

"""Corrected multiscale five-method baseline experiment.

Formal protocol:
- task counts: K = 30,40,60,70 (combined later with frozen K=50,80)
- independent scenarios: S45-S52
- stochastic repetitions: A100-A102
- deterministic methods are evaluated once per scenario
- stochastic methods are evaluated once per (scenario, algorithm seed)

Method definitions are identical to the paper-facing baseline runners:
GR-MR   = Greedy Route + MEC Repair
FTR-NM  = Fixed Task Route + Nearest MEC
RGA-MR  = Route GA + MEC Repair
B-ALNS  = generic ALNS exploration of the frozen hybrid runner
ESI-ALNS= generic ALNS exploration + elite structural intensification
"""

import argparse
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    GARouteConfig,
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_fixed_route_nearest_mec_solution,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_route_ga,
    run_uav_mec_hybrid_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config
from uav_mec.optimization.resource import CVXResourceSolver


METHODS = ("GR-MR", "FTR-NM", "RGA-MR", "B-ALNS", "ESI-ALNS")


def parse_ints(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def stage1_status(result) -> str:
    return str(result.diagnostics.get("stage1_status", result.status))


def strict_energy(result) -> float | None:
    if result.feasible and stage1_status(result) == "optimal":
        return float(result.energy_stage1_j)
    return None


def solve_stage1(instance, solution):
    info = build_event_info(instance, solution)
    return CVXResourceSolver(run_stage2=False).solve(instance, solution, info)


def append_row(
    rows: list[dict[str, Any]],
    *,
    tasks: int,
    scenario_seed: int,
    algorithm_seed: int | None,
    method: str,
    cvx,
    runtime_s: float,
    extra: dict[str, Any] | None = None,
) -> None:
    energy = strict_energy(cvx)
    row: dict[str, Any] = {
        "tasks": tasks,
        "scenario_seed": scenario_seed,
        "algorithm_seed": algorithm_seed,
        "method": method,
        "stage1_status": stage1_status(cvx),
        "strict": energy is not None,
        "energy_j": energy,
        "runtime_s": float(runtime_s),
    }
    if extra:
        row.update(extra)
    rows.append(row)


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tasks in sorted({int(row["tasks"]) for row in rows}):
        for method in METHODS:
            subset = [
                row for row in rows
                if int(row["tasks"]) == tasks and row["method"] == method
            ]
            energies = [
                float(row["energy_j"])
                for row in subset
                if row["strict"] and row["energy_j"] is not None
            ]
            out.append({
                "tasks": tasks,
                "method": method,
                "runs": len(subset),
                "strict": len(energies),
                "strict_rate": len(energies) / len(subset) if subset else 0.0,
                "mean_energy_j": mean(energies) if energies else None,
                "median_energy_j": median(energies) if energies else None,
                "mean_runtime_s": mean(float(row["runtime_s"]) for row in subset)
                if subset else None,
            })
    return out


def paired_esi(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tasks in sorted({int(row["tasks"]) for row in rows}):
        stochastic = [
            row for row in rows
            if int(row["tasks"]) == tasks and row["algorithm_seed"] is not None
        ]
        by_key: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
        for row in stochastic:
            key = (int(row["scenario_seed"]), int(row["algorithm_seed"]))
            by_key.setdefault(key, {})[row["method"]] = row

        for baseline in ("RGA-MR", "B-ALNS"):
            gains: list[float] = []
            for methods in by_key.values():
                if baseline not in methods or "ESI-ALNS" not in methods:
                    continue
                base = methods[baseline]["energy_j"]
                esi = methods["ESI-ALNS"]["energy_j"]
                if base is None or esi is None:
                    continue
                gains.append(
                    100.0 * (float(base) - float(esi))
                    / max(1.0, abs(float(base)))
                )
            out.append({
                "tasks": tasks,
                "baseline": baseline,
                "comparable": len(gains),
                "esi_better": sum(v > 1e-9 for v in gains),
                "equal": sum(abs(v) <= 1e-9 for v in gains),
                "baseline_better": sum(v < -1e-9 for v in gains),
                "mean_esi_advantage_pct": mean(gains) if gains else None,
                "median_esi_advantage_pct": median(gains) if gains else None,
            })
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30,40,60,70")
    parser.add_argument("--scenario-seeds", default="45,46,47,48,49,50,51,52")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--ga-population", type=int, default=16)
    parser.add_argument("--ga-generations", type=int, default=12)
    parser.add_argument(
        "--output",
        default="outputs/results/multiscale_baseline_corrected.json",
    )
    args = parser.parse_args()

    task_counts = parse_ints(args.tasks)
    scenario_seeds = parse_ints(args.scenario_seeds)
    algorithm_seeds = parse_ints(args.algorithm_seeds)
    cfg = load_paper_scale_config(args.config)
    rows: list[dict[str, Any]] = []

    for tasks in task_counts:
        for scenario_seed in scenario_seeds:
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=tasks,
                num_uavs=args.uavs,
                num_mecs=args.mecs,
                scenario_seed=scenario_seed,
            )

            # Shared route seed. The two deterministic methods are executed
            # exactly once per independent scenario.
            route_seed = build_greedy_initial_solution(instance)

            t0 = perf_counter()
            gr_solution = build_mec_assisted_initial_solution(
                instance,
                base_solution=route_seed,
            )
            gr_cvx = solve_stage1(instance, gr_solution)
            append_row(
                rows,
                tasks=tasks,
                scenario_seed=scenario_seed,
                algorithm_seed=None,
                method="GR-MR",
                cvx=gr_cvx,
                runtime_s=perf_counter() - t0,
            )

            t0 = perf_counter()
            ftr_solution = build_fixed_route_nearest_mec_solution(
                instance,
                base_solution=route_seed,
            )
            ftr_cvx = solve_stage1(instance, ftr_solution)
            append_row(
                rows,
                tasks=tasks,
                scenario_seed=scenario_seed,
                algorithm_seed=None,
                method="FTR-NM",
                cvx=ftr_cvx,
                runtime_s=perf_counter() - t0,
            )

            # The paper-facing B-ALNS/ESI pair shares one hybrid run per seed.
            initial = gr_solution
            for algorithm_seed in algorithm_seeds:
                ga_cfg = GARouteConfig(
                    population_size=args.ga_population,
                    generations=args.ga_generations,
                )
                t0 = perf_counter()
                ga_result = run_route_ga(
                    instance,
                    seed=algorithm_seed,
                    config=ga_cfg,
                )
                ga_cvx = solve_stage1(instance, ga_result.best_solution)
                append_row(
                    rows,
                    tasks=tasks,
                    scenario_seed=scenario_seed,
                    algorithm_seed=algorithm_seed,
                    method="RGA-MR",
                    cvx=ga_cvx,
                    runtime_s=perf_counter() - t0,
                    extra={
                        "ga_evaluations": int(ga_result.evaluations),
                        "ga_cache_hits": int(ga_result.cache_hits),
                    },
                )

                evaluator = ScreenedProxyObjectiveEvaluator()
                alns_cfg = UavMecALNSConfig(
                    seed=algorithm_seed,
                    iterations=args.iterations,
                )
                t0 = perf_counter()
                hybrid = run_uav_mec_hybrid_alns(
                    instance,
                    initial_solution=initial,
                    config=alns_cfg,
                    evaluator=evaluator,
                    elite_rounds=args.elite_rounds,
                )
                hybrid_wall_s = perf_counter() - t0

                append_row(
                    rows,
                    tasks=tasks,
                    scenario_seed=scenario_seed,
                    algorithm_seed=algorithm_seed,
                    method="B-ALNS",
                    cvx=hybrid.exploration_cvx,
                    runtime_s=float(
                        hybrid.exploration.raw_result.statistics.total_runtime
                    ),
                )
                append_row(
                    rows,
                    tasks=tasks,
                    scenario_seed=scenario_seed,
                    algorithm_seed=algorithm_seed,
                    method="ESI-ALNS",
                    cvx=hybrid.final_cvx,
                    runtime_s=hybrid_wall_s,
                    extra={
                        "elite_cvx_calls": int(hybrid.elite_cvx_calls),
                        "elite_runtime_s": float(hybrid.elite_runtime_s),
                    },
                )

    payload = {
        "complete": True,
        "experiment": "multiscale_baseline_corrected",
        "protocol": {
            "tasks": task_counts,
            "scenario_seeds": scenario_seeds,
            "algorithm_seeds": algorithm_seeds,
            "mecs": args.mecs,
            "uavs": args.uavs,
            "iterations": args.iterations,
            "elite_rounds": args.elite_rounds,
            "ga_population": args.ga_population,
            "ga_generations": args.ga_generations,
            "deterministic_unit": "one result per scenario",
            "stochastic_unit": "three nested algorithm repetitions per scenario",
        },
        "aggregate": aggregate(rows),
        "paired": paired_esi(rows),
        "rows": rows,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps({
        "complete": True,
        "rows": len(rows),
        "expected_rows": (
            len(task_counts)
            * (
                2 * len(scenario_seeds)
                + 3 * len(scenario_seeds) * len(algorithm_seeds)
            )
        ),
        "aggregate": payload["aggregate"],
        "paired": payload["paired"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
