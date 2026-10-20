from __future__ import annotations

import argparse
import json
from dataclasses import replace
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


def _strict_energy(result) -> float | None:
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


def _strong_config(
    *,
    iterations: int,
    seed: int,
    num_tasks: int,
) -> UavMecALNSConfig:
    base = UavMecALNSConfig(
        iterations=iterations,
        seed=seed,
    )
    p = base.problem
    p = replace(
        p,
        elite_shortlist_limit=32,
        elite_task_limit=min(num_tasks, 12),
        elite_positions_per_contact=4,
        elite_points_per_mec=2,
        elite_route_options_per_task=min(num_tasks + 1, 8),
        elite_family_quota=4,
        elite_min_improvement_rel=1e-6,
        elite_min_improvement_j=1e-3,
        elite_progressive_widening=True,
        elite_widen_trigger_rel=1e-6,
        elite_widen_extra_limit=24,
        elite_widen_task_limit=min(num_tasks, 12),
        elite_widen_route_options_per_task=min(num_tasks + 1, 10),
        elite_widen_family_quota=6,
    )
    return replace(base, problem=p)


def _write(
    out: Path,
    *,
    experiment: dict[str, Any],
    rows: list[dict[str, Any]],
    complete: bool,
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "complete": complete,
                "experiment": experiment,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Small-scale best-known strong-reference benchmark. "
            "This is not a global-optimality certificate."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--uavs", type=int, default=2)
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--scenario-seeds", default="45")
    parser.add_argument("--standard-seeds", default="100,101,102")
    parser.add_argument(
        "--strong-seeds",
        default="700,701,702,703,704,705,706,707,708,709,710,711",
    )
    parser.add_argument("--standard-iterations", type=int, default=100)
    parser.add_argument("--strong-iterations", type=int, default=1000)
    parser.add_argument("--standard-elite-rounds", type=int, default=2)
    parser.add_argument("--strong-elite-rounds", type=int, default=6)
    parser.add_argument(
        "--hit-tolerance-rel",
        type=float,
        default=1e-5,
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.tasks <= 0 or args.uavs <= 0 or args.mecs <= 0:
        raise ValueError("tasks/uavs/mecs must be positive")
    if args.strong_iterations <= args.standard_iterations:
        raise ValueError(
            "strong_iterations should exceed standard_iterations"
        )

    scenario_seeds = _parse_int_list(args.scenario_seeds)
    standard_seeds = _parse_int_list(args.standard_seeds)
    strong_seeds = _parse_int_list(args.strong_seeds)
    if not scenario_seeds or not standard_seeds or not strong_seeds:
        raise ValueError("seed lists must be non-empty")

    cfg = load_paper_scale_config(args.config)
    out = Path(args.output)
    experiment = {
        "benchmark_type": "best_known_strong_reference",
        "global_optimality_claim": False,
        "tasks": args.tasks,
        "uavs": args.uavs,
        "mecs": args.mecs,
        "scenario_seeds": scenario_seeds,
        "standard_seeds": standard_seeds,
        "strong_seeds": strong_seeds,
        "standard_iterations": args.standard_iterations,
        "strong_iterations": args.strong_iterations,
        "standard_elite_rounds": args.standard_elite_rounds,
        "strong_elite_rounds": args.strong_elite_rounds,
        "hit_tolerance_rel": args.hit_tolerance_rel,
        "strong_elite_config": {
            "shortlist_limit": 32,
            "task_limit": min(args.tasks, 12),
            "positions_per_contact": 4,
            "points_per_mec": 2,
            "route_options_per_task": min(args.tasks + 1, 8),
            "family_quota": 4,
            "min_improvement_rel": 1e-6,
            "min_improvement_j": 1e-3,
            "widen_extra_limit": 24,
            "widen_task_limit": min(args.tasks, 12),
            "widen_route_options_per_task": min(args.tasks + 1, 10),
            "widen_family_quota": 6,
        },
    }

    rows: list[dict[str, Any]] = []

    print(
        "K    scen   mode      seed   stage1       energy-J        "
        "iters   elite-cvx   runtime-s   contacts offload distance-km"
    )
    print("-" * 116)

    for scenario_seed in scenario_seeds:
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=args.tasks,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=scenario_seed,
        )
        route_seed = build_greedy_initial_solution(instance)
        initial = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )

        scenario_rows: list[dict[str, Any]] = []

        def run_one(
            *,
            mode: str,
            algorithm_seed: int,
            iterations: int,
            elite_rounds: int,
        ) -> None:
            evaluator = ScreenedProxyObjectiveEvaluator()
            if mode == "strong":
                config = _strong_config(
                    iterations=iterations,
                    seed=algorithm_seed,
                    num_tasks=args.tasks,
                )
            else:
                config = UavMecALNSConfig(
                    iterations=iterations,
                    seed=algorithm_seed,
                )

            t0 = perf_counter()
            result = run_uav_mec_hybrid_alns(
                instance,
                initial_solution=initial,
                config=config,
                evaluator=evaluator,
                elite_rounds=elite_rounds,
            )
            runtime_s = perf_counter() - t0
            status = _stage1_status(result.final_cvx)
            energy = _strict_energy(result.final_cvx)
            summary = _solution_summary(
                instance,
                result.best_solution,
            )

            row = {
                "K": args.tasks,
                "M": args.uavs,
                "E": args.mecs,
                "scenario_seed": scenario_seed,
                "mode": mode,
                "algorithm_seed": algorithm_seed,
                "iterations": iterations,
                "elite_rounds": elite_rounds,
                "stage1_status": status,
                "strict_energy_j": energy,
                "runtime_s": runtime_s,
                "elite_cvx_calls": result.elite_cvx_calls,
                "elite_cvx_cache_hits": result.elite_cvx_cache_hits,
                "screened_cvx_refinements": (
                    evaluator.stats.cvx_refinements
                ),
                "screened_precheck_rejects": (
                    evaluator.stats.precheck_rejects
                ),
                "solution": summary,
                "best_known_energy_j": None,
                "gap_to_best_known_pct": None,
                "is_best_known_hit": False,
            }
            rows.append(row)
            scenario_rows.append(row)
            _write(
                out,
                experiment=experiment,
                rows=rows,
                complete=False,
            )

            energy_text = (
                f"{energy:.6f}" if energy is not None else "-"
            )
            print(
                f"{args.tasks:<4} {scenario_seed:<6} {mode:<9} "
                f"{algorithm_seed:<6} {status:<12} "
                f"{energy_text:<15} {iterations:<7} "
                f"{result.elite_cvx_calls:<11} "
                f"{runtime_s:<11.3f} "
                f"{summary['contacts']:<8} "
                f"{summary['offloaded']:<7} "
                f"{summary['distance_m'] / 1000.0:.3f}"
            )

        for seed in standard_seeds:
            run_one(
                mode="standard",
                algorithm_seed=seed,
                iterations=args.standard_iterations,
                elite_rounds=args.standard_elite_rounds,
            )

        for seed in strong_seeds:
            run_one(
                mode="strong",
                algorithm_seed=seed,
                iterations=args.strong_iterations,
                elite_rounds=args.strong_elite_rounds,
            )

        strict_rows = [
            row
            for row in scenario_rows
            if row["strict_energy_j"] is not None
        ]
        if not strict_rows:
            continue

        best_known = min(
            float(row["strict_energy_j"])
            for row in strict_rows
        )
        tolerance_j = (
            args.hit_tolerance_rel * max(1.0, abs(best_known))
        )

        for row in scenario_rows:
            energy = row["strict_energy_j"]
            row["best_known_energy_j"] = best_known
            if energy is None:
                continue
            gap = (
                100.0
                * (float(energy) - best_known)
                / max(1.0, abs(best_known))
            )
            row["gap_to_best_known_pct"] = gap
            row["is_best_known_hit"] = (
                float(energy) <= best_known + tolerance_j
            )

        standard_gaps = [
            float(row["gap_to_best_known_pct"])
            for row in scenario_rows
            if (
                row["mode"] == "standard"
                and row["gap_to_best_known_pct"] is not None
            )
        ]
        strong_hits = sum(
            bool(row["is_best_known_hit"])
            for row in scenario_rows
            if row["mode"] == "strong"
        )
        strict_strong = sum(
            row["strict_energy_j"] is not None
            for row in scenario_rows
            if row["mode"] == "strong"
        )

        print(
            "  reference: "
            f"best_known={best_known:.6f} J; "
            f"standard_gap_mean="
            f"{mean(standard_gaps) if standard_gaps else float('nan'):.6f}%; "
            f"standard_gap_median="
            f"{median(standard_gaps) if standard_gaps else float('nan'):.6f}%; "
            f"strong_hits={strong_hits}/{len(strong_seeds)}; "
            f"strict_strong={strict_strong}/{len(strong_seeds)}"
        )

    _write(
        out,
        experiment=experiment,
        rows=rows,
        complete=True,
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
