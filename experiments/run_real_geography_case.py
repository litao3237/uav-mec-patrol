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
    build_fixed_route_nearest_mec_solution,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_hybrid_alns,
)
from uav_mec.analysis import build_paper_metrics
from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_stanislaus_real_instance
from uav_mec.optimization.resource import CVXResourceSolver


def _parse_int_list(text: str) -> list[int]:
    return [
        int(item.strip())
        for item in text.split(",")
        if item.strip()
    ]


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


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"methods": {}, "paired": {}}

    deterministic_by_scenario: dict[int, dict[str, Any]] = {}
    for row in rows:
        deterministic_by_scenario.setdefault(
            int(row["scenario_seed"]),
            row,
        )

    for method in ("greedy_repair", "nearest_mec"):
        unique_rows = list(deterministic_by_scenario.values())
        values = [row[method] for row in unique_rows]
        energies = [
            float(item["energy_j"])
            for item in values
            if item["energy_j"] is not None
        ]
        result["methods"][method] = {
            "independent_unique_scenarios": len(unique_rows),
            "strict_optimal": sum(
                item["stage1_status"] == "optimal"
                for item in values
            ),
            "mean_energy_j": mean(energies) if energies else None,
            "median_energy_j": median(energies) if energies else None,
        }

    for method in ("generic_alns", "hybrid"):
        values = [row[method] for row in rows]
        energies = [
            float(item["energy_j"])
            for item in values
            if item["energy_j"] is not None
        ]
        result["methods"][method] = {
            "runs": len(values),
            "strict_optimal": sum(
                item["stage1_status"] == "optimal"
                for item in values
            ),
            "mean_energy_j": mean(energies) if energies else None,
            "median_energy_j": median(energies) if energies else None,
        }

    for baseline in ("nearest_mec", "generic_alns"):
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
            "note": (
                "nearest_mec is deterministic within each scenario; repeated "
                "algorithm-seed pairs are descriptive, not independent "
                "baseline samples"
                if baseline == "nearest_mec"
                else "paired stochastic comparison"
            ),
        }

    metric_rows = [
        row["paper_metrics"]
        for row in rows
        if row.get("paper_metrics") is not None
    ]
    result["paper_metrics"] = {
        "runs": len(metric_rows),
        "stage2_strict": sum(
            metrics["stage2_status"] == "optimal"
            for metrics in metric_rows
        ),
        "mean_offload_ratio": (
            mean(float(m["offload_ratio"]) for m in metric_rows)
            if metric_rows else None
        ),
        "mean_contacts_per_uav": (
            mean(float(m["contacts_per_uav"]) for m in metric_rows)
            if metric_rows else None
        ),
        "mean_route_distance_km": (
            mean(float(m["total_distance_m"]) for m in metric_rows)
            / 1000.0
            if metric_rows else None
        ),
        "mean_delay_s": (
            mean(float(m["avg_delay_s"]) for m in metric_rows)
            if metric_rows else None
        ),
        "mean_deadline_slack_s": (
            mean(float(m["mean_deadline_slack_s"]) for m in metric_rows)
            if metric_rows else None
        ),
    }
    return result


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Stanislaus GIS-driven real-geography case study."
    )
    parser.add_argument(
        "--snapshot",
        default="outputs/results/stanislaus_real_case_scout.json",
    )
    parser.add_argument(
        "--config",
        default="configs/real_stanislaus.yaml",
    )
    parser.add_argument("--tasks", type=int, default=50)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument("--scenario-seeds", default="45,46,47")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)
    out = Path(args.output)
    rows: list[dict[str, Any]] = []
    case_metadata: dict[str, Any] | None = None

    experiment: dict[str, Any] = {
        "case": "stanislaus_groveland_real_geography",
        "snapshot": args.snapshot,
        "config": args.config,
        "tasks": args.tasks,
        "uavs": args.uavs,
        "mecs": 2,
        "scenario_seeds": scenario_seeds,
        "algorithm_seeds": algorithm_seeds,
        "iterations": args.iterations,
        "elite_rounds": args.elite_rounds,
        "case_metadata": None,
    }

    print(
        "scen alg greedy-s1 nearest-s1 generic-s1 hybrid-s1 "
        "nearest-E-J generic-E-J hybrid-E-J H-vs-N% H-vs-G% "
        "contacts offload dist-km runtime-s"
    )
    print("-" * 142)

    for scenario_seed in scenario_seeds:
        built = build_stanislaus_real_instance(
            args.snapshot,
            config_path=args.config,
            num_tasks=args.tasks,
            num_uavs=args.uavs,
            scenario_seed=scenario_seed,
        )
        instance = built.instance
        if case_metadata is None:
            case_metadata = built.metadata
            experiment["case_metadata"] = case_metadata

        t0 = perf_counter()
        route_seed = build_greedy_initial_solution(instance)
        route_seed_info = build_event_info(instance, route_seed)
        reference_distance_m = sum(
            route_seed_info.route_distance_m.values()
        )
        initial = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )
        init_runtime_s = perf_counter() - t0

        greedy_solver = CVXResourceSolver(run_stage2=False)
        greedy_info = build_event_info(instance, initial)
        t_g = perf_counter()
        greedy_cvx = greedy_solver.solve(
            instance,
            initial,
            greedy_info,
        )
        greedy_runtime_s = init_runtime_s + perf_counter() - t_g

        t_n = perf_counter()
        nearest_solution = build_fixed_route_nearest_mec_solution(
            instance,
            base_solution=route_seed,
        )
        nearest_build_s = perf_counter() - t_n
        nearest_info = build_event_info(instance, nearest_solution)
        nearest_solver = CVXResourceSolver(run_stage2=False)
        t_nc = perf_counter()
        nearest_cvx = nearest_solver.solve(
            instance,
            nearest_solution,
            nearest_info,
        )
        nearest_runtime_s = nearest_build_s + perf_counter() - t_nc

        greedy_energy = _energy_if_strict(greedy_cvx)
        nearest_energy = _energy_if_strict(nearest_cvx)

        for algorithm_seed in algorithm_seeds:
            evaluator = ScreenedProxyObjectiveEvaluator()
            config = UavMecALNSConfig(
                iterations=args.iterations,
                seed=algorithm_seed,
            )
            t_h = perf_counter()
            hybrid_result = run_uav_mec_hybrid_alns(
                instance,
                initial_solution=initial,
                config=config,
                evaluator=evaluator,
                elite_rounds=args.elite_rounds,
            )
            hybrid_runtime_s = perf_counter() - t_h

            generic_energy = _energy_if_strict(
                hybrid_result.exploration_cvx
            )
            hybrid_energy = _energy_if_strict(
                hybrid_result.final_cvx
            )

            metrics = None
            metrics_error = None
            if hybrid_energy is not None:
                try:
                    final_info = build_event_info(
                        instance,
                        hybrid_result.best_solution,
                    )
                    metrics_solver = CVXResourceSolver(
                        run_stage2=True,
                        energy_tol_rel=1e-5,
                    )
                    metrics_result = metrics_solver.solve(
                        instance,
                        hybrid_result.best_solution,
                        final_info,
                    )
                    if (
                        metrics_result.feasible
                        and _stage1_status(metrics_result) == "optimal"
                    ):
                        metrics = build_paper_metrics(
                            instance,
                            hybrid_result.best_solution,
                            metrics_result,
                            info=final_info,
                            reference_distance_m=reference_distance_m,
                        )
                    else:
                        metrics_error = (
                            "metrics Stage-1 is not strict optimal: "
                            f"{_stage1_status(metrics_result)}"
                        )
                except Exception as exc:
                    metrics_error = f"{type(exc).__name__}: {exc}"

            def gain(base: float | None) -> float | None:
                if base is None or hybrid_energy is None:
                    return None
                return (
                    100.0
                    * (base - hybrid_energy)
                    / max(1.0, abs(base))
                )

            row = {
                "scenario_seed": scenario_seed,
                "algorithm_seed": algorithm_seed,
                "greedy_repair": {
                    "stage1_status": _stage1_status(greedy_cvx),
                    "energy_j": greedy_energy,
                    "runtime_s": greedy_runtime_s,
                    "solution": _solution_summary(instance, initial),
                },
                "nearest_mec": {
                    "stage1_status": _stage1_status(nearest_cvx),
                    "energy_j": nearest_energy,
                    "runtime_s": nearest_runtime_s,
                    "solution": _solution_summary(
                        instance,
                        nearest_solution,
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
                    "runtime_s": hybrid_runtime_s,
                    "elite_cvx_calls": hybrid_result.elite_cvx_calls,
                    "solution": _solution_summary(
                        instance,
                        hybrid_result.best_solution,
                    ),
                },
                "hybrid_advantage_vs_nearest_pct": gain(nearest_energy),
                "hybrid_advantage_vs_generic_pct": gain(generic_energy),
                "paper_metrics": metrics,
                "paper_metrics_error": metrics_error,
            }
            rows.append(row)
            _write(
                out,
                experiment=experiment,
                rows=rows,
                aggregate={},
                complete=False,
            )

            summary = row["hybrid"]["solution"]

            def fmt(value: float | None) -> str:
                return "-" if value is None else f"{value:.3f}"

            print(
                f"{scenario_seed:<4} {algorithm_seed:<3} "
                f"{row['greedy_repair']['stage1_status']:<11} "
                f"{row['nearest_mec']['stage1_status']:<12} "
                f"{row['generic_alns']['stage1_status']:<10} "
                f"{row['hybrid']['stage1_status']:<9} "
                f"{fmt(nearest_energy):<11} "
                f"{fmt(generic_energy):<11} "
                f"{fmt(hybrid_energy):<10} "
                f"{fmt(row['hybrid_advantage_vs_nearest_pct']):<7} "
                f"{fmt(row['hybrid_advantage_vs_generic_pct']):<7} "
                f"{summary['contacts']:<8} "
                f"{summary['offloaded']:<7} "
                f"{summary['distance_m']/1000.0:<7.3f} "
                f"{hybrid_runtime_s:.3f}"
            )

    aggregate = _aggregate(rows)
    _write(
        out,
        experiment=experiment,
        rows=rows,
        aggregate=aggregate,
        complete=True,
    )
    print("\nAggregate")
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
