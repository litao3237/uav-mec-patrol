from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_hybrid_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


def _parse_int_list(text: str) -> list[int]:
    return [
        int(item.strip())
        for item in text.split(",")
        if item.strip()
    ]


def _tag(values: list[int]) -> str:
    return "-".join(str(value) for value in values)


def _stage1_status(result) -> str:
    return str(
        result.diagnostics.get(
            "stage1_status",
            result.status,
        )
    )


def _energy_if_strict(result) -> float | None:
    if result.feasible and _stage1_status(result) == "optimal":
        return float(result.energy_stage1_j)
    return None


def _solution_summary(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    return {
        "contacts": len(solution.contact_visits),
        "offloaded": sum(
            decision.mode.value == "offload"
            for decision in solution.task_decisions.values()
        ),
        "active_pairs": len(info.active_uav_mec_pairs),
        "distance_m": sum(info.route_distance_m.values()),
    }


def _default_output_path(
    *,
    task_counts: list[int],
    mec_counts: list[int],
    scenario_seeds: list[int],
    algorithm_seeds: list[int],
    iterations: int,
) -> Path:
    return Path("outputs/results") / (
        "baseline_core"
        f"_K{_tag(task_counts)}"
        f"_E{_tag(mec_counts)}"
        f"_S{_tag(scenario_seeds)}"
        f"_A{_tag(algorithm_seeds)}"
        f"_I{iterations}.json"
    )


def _write(
    out: Path,
    *,
    experiment: dict[str, Any],
    rows: list[dict[str, Any]],
    aggregate: dict[str, Any],
    complete: bool,
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "complete": complete,
                "experiment": experiment,
                "aggregate": aggregate,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    methods = ("greedy_repair", "generic_alns", "hybrid")
    result: dict[str, Any] = {"methods": {}, "paired": {}}

    for method in methods:
        statuses = [row[method]["stage1_status"] for row in rows]
        energies = [
            float(row[method]["energy_j"])
            for row in rows
            if row[method]["energy_j"] is not None
        ]
        result["methods"][method] = {
            "runs": len(rows),
            "strict_optimal": sum(status == "optimal" for status in statuses),
            "strict_rate": (
                sum(status == "optimal" for status in statuses) / len(rows)
                if rows else 0.0
            ),
            "mean_energy_j": mean(energies) if energies else None,
            "median_energy_j": median(energies) if energies else None,
        }

    for baseline in ("greedy_repair", "generic_alns"):
        gains: list[float] = []
        for row in rows:
            base = row[baseline]["energy_j"]
            hybrid = row["hybrid"]["energy_j"]
            if base is None or hybrid is None:
                continue
            gains.append(
                100.0
                * (float(base) - float(hybrid))
                / max(1.0, abs(float(base)))
            )
        result["paired"][f"hybrid_vs_{baseline}"] = {
            "comparable": len(gains),
            "mean_hybrid_advantage_pct": mean(gains) if gains else None,
            "median_hybrid_advantage_pct": median(gains) if gains else None,
            "hybrid_better": sum(gain > 1e-9 for gain in gains),
            "equal": sum(abs(gain) <= 1e-9 for gain in gains),
            "baseline_better": sum(gain < -1e-9 for gain in gains),
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Core baseline comparison using one shared initialization and "
            "one shared Generic ALNS trajectory per seed."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="80")
    parser.add_argument("--mecs", default="2")
    parser.add_argument("--scenario-seeds", default="45,46,47")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    task_counts = _parse_int_list(args.tasks)
    mec_counts = _parse_int_list(args.mecs)
    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)

    out = (
        Path(args.output)
        if args.output
        else _default_output_path(
            task_counts=task_counts,
            mec_counts=mec_counts,
            scenario_seeds=scenario_seeds,
            algorithm_seeds=algorithm_seeds,
            iterations=args.iterations,
        )
    )
    experiment = {
        "tasks": task_counts,
        "mecs": mec_counts,
        "scenario_seeds": scenario_seeds,
        "algorithm_seeds": algorithm_seeds,
        "iterations": args.iterations,
        "elite_rounds": args.elite_rounds,
        "uavs": args.uavs,
    }

    cfg = load_paper_scale_config(args.config)
    rows: list[dict[str, Any]] = []

    print(
        "K    E    scen   alg    greedy-s1    generic-s1   hybrid-s1    "
        "greedy-E-J      generic-E-J     hybrid-E-J      "
        "H-vs-Greedy%   H-vs-Generic%"
    )
    print("-" * 142)

    for k in task_counts:
        for e in mec_counts:
            for scenario_seed in scenario_seeds:
                instance = build_paper_scale_instance(
                    cfg,
                    num_tasks=k,
                    num_uavs=args.uavs,
                    num_mecs=e,
                    scenario_seed=scenario_seed,
                )

                t0 = perf_counter()
                route_seed = build_greedy_initial_solution(instance)
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=route_seed,
                )
                init_runtime_s = perf_counter() - t0

                greedy_solver = CVXResourceSolver(run_stage2=False)
                greedy_info = build_event_info(instance, initial)
                t_greedy = perf_counter()
                greedy_cvx = greedy_solver.solve(
                    instance,
                    initial,
                    greedy_info,
                )
                greedy_cvx_runtime_s = perf_counter() - t_greedy

                for algorithm_seed in algorithm_seeds:
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    config = UavMecALNSConfig(
                        iterations=args.iterations,
                        seed=algorithm_seed,
                    )
                    t_hybrid = perf_counter()
                    hybrid_result = run_uav_mec_hybrid_alns(
                        instance,
                        initial_solution=initial,
                        config=config,
                        evaluator=evaluator,
                        elite_rounds=args.elite_rounds,
                    )
                    hybrid_wall_s = perf_counter() - t_hybrid

                    greedy_energy = _energy_if_strict(greedy_cvx)
                    generic_energy = _energy_if_strict(
                        hybrid_result.exploration_cvx
                    )
                    hybrid_energy = _energy_if_strict(
                        hybrid_result.final_cvx
                    )

                    def gain(base: float | None) -> float | None:
                        if base is None or hybrid_energy is None:
                            return None
                        return (
                            100.0
                            * (base - hybrid_energy)
                            / max(1.0, abs(base))
                        )

                    row = {
                        "K": k,
                        "E": e,
                        "scenario_seed": scenario_seed,
                        "algorithm_seed": algorithm_seed,
                        "greedy_repair": {
                            "stage1_status": _stage1_status(greedy_cvx),
                            "energy_j": greedy_energy,
                            "runtime_s": (
                                init_runtime_s + greedy_cvx_runtime_s
                            ),
                            "solution": _solution_summary(
                                instance,
                                initial,
                            ),
                        },
                        "generic_alns": {
                            "stage1_status": _stage1_status(
                                hybrid_result.exploration_cvx
                            ),
                            "energy_j": generic_energy,
                            "runtime_s": float(
                                hybrid_result.exploration.raw_result
                                .statistics.total_runtime
                            ),
                            "solution": _solution_summary(
                                instance,
                                hybrid_result.exploration.best_solution,
                            ),
                        },
                        "hybrid": {
                            "stage1_status": _stage1_status(
                                hybrid_result.final_cvx
                            ),
                            "energy_j": hybrid_energy,
                            "runtime_s": hybrid_wall_s,
                            "elite_runtime_s": (
                                hybrid_result.elite_runtime_s
                            ),
                            "elite_cvx_calls": (
                                hybrid_result.elite_cvx_calls
                            ),
                            "accepted_moves": list(
                                hybrid_result.elite_stats.get(
                                    "accepted_moves",
                                    [],
                                )
                            ),
                            "solution": _solution_summary(
                                instance,
                                hybrid_result.best_solution,
                            ),
                        },
                        "hybrid_advantage_vs_greedy_pct": gain(
                            greedy_energy
                        ),
                        "hybrid_advantage_vs_generic_pct": gain(
                            generic_energy
                        ),
                    }
                    rows.append(row)
                    _write(
                        out,
                        experiment=experiment,
                        rows=rows,
                        aggregate={},
                        complete=False,
                    )

                    def fmt(value: float | None) -> str:
                        return f"{value:.3f}" if value is not None else "-"

                    print(
                        f"{k:<4} {e:<4} {scenario_seed:<6} "
                        f"{algorithm_seed:<6} "
                        f"{row['greedy_repair']['stage1_status']:<12} "
                        f"{row['generic_alns']['stage1_status']:<12} "
                        f"{row['hybrid']['stage1_status']:<12} "
                        f"{fmt(greedy_energy):<15} "
                        f"{fmt(generic_energy):<15} "
                        f"{fmt(hybrid_energy):<15} "
                        f"{fmt(row['hybrid_advantage_vs_greedy_pct']):<14} "
                        f"{fmt(row['hybrid_advantage_vs_generic_pct'])}"
                    )

    aggregate = _aggregate(rows)
    print("\nAggregate")
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))

    _write(
        out,
        experiment=experiment,
        rows=rows,
        aggregate=aggregate,
        complete=True,
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
