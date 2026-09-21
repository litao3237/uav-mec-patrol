from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_hybrid_alns,
)
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


def _cummin(values: list[float]) -> list[float]:
    result: list[float] = []
    best = float("inf")
    for value in values:
        best = min(best, float(value))
        result.append(best)
    return result


def _write(
    path: Path,
    *,
    experiment: dict[str, Any],
    rows: list[dict[str, Any]],
    complete: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
            "Paired iteration-budget convergence study for Proposed Hybrid."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, default=80)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--scenario-seed", type=int, required=True)
    parser.add_argument("--algorithm-seed", type=int, required=True)
    parser.add_argument("--budgets", default="25,50,100,200")
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    budgets = _parse_int_list(args.budgets)
    if not budgets or any(value <= 0 for value in budgets):
        raise ValueError("--budgets must contain positive integers")
    if budgets != sorted(set(budgets)):
        raise ValueError("--budgets must be unique and increasing")

    cfg = load_paper_scale_config(args.config)
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=args.tasks,
        num_uavs=args.uavs,
        num_mecs=args.mecs,
        scenario_seed=args.scenario_seed,
    )
    route_seed = build_greedy_initial_solution(instance)
    initial = build_mec_assisted_initial_solution(
        instance,
        base_solution=route_seed,
    )

    experiment = {
        "study": "iteration_budget_convergence",
        "tasks": args.tasks,
        "uavs": args.uavs,
        "mecs": args.mecs,
        "scenario_seed": args.scenario_seed,
        "algorithm_seed": args.algorithm_seed,
        "budgets": budgets,
        "elite_rounds": args.elite_rounds,
        "interpretation": (
            "Independent paired runs with the same seed at different total "
            "iteration budgets; not prefixes of one identical acceptance "
            "schedule."
        ),
    }
    out = Path(args.output)
    rows: list[dict[str, Any]] = []

    print(
        "budget base-s1 hybrid-s1 base-E-J hybrid-E-J improve-% "
        "runtime-s elite-cvx proxy-final proxy-best"
    )
    print("-" * 108)

    for budget in budgets:
        evaluator = ScreenedProxyObjectiveEvaluator()
        config = UavMecALNSConfig(
            iterations=budget,
            seed=args.algorithm_seed,
        )
        t0 = perf_counter()
        result = run_uav_mec_hybrid_alns(
            instance,
            initial_solution=initial,
            config=config,
            evaluator=evaluator,
            elite_rounds=args.elite_rounds,
        )
        total_runtime_s = perf_counter() - t0

        base_status = _stage1_status(result.exploration_cvx)
        hybrid_status = _stage1_status(result.final_cvx)
        base_energy = (
            float(result.exploration_cvx.energy_stage1_j)
            if result.exploration_cvx.feasible
            and base_status == "optimal"
            else None
        )
        hybrid_energy = (
            float(result.final_cvx.energy_stage1_j)
            if result.final_cvx.feasible
            and hybrid_status == "optimal"
            else None
        )

        raw_objectives = [
            float(value)
            for value in result.exploration.raw_result.statistics.objectives
        ]
        proxy_best_trace = _cummin(raw_objectives)
        row = {
            "K": args.tasks,
            "M": args.uavs,
            "E": args.mecs,
            "scenario_seed": args.scenario_seed,
            "algorithm_seed": args.algorithm_seed,
            "iterations": budget,
            "base_stage1_status": base_status,
            "hybrid_stage1_status": hybrid_status,
            "base_energy_j": base_energy,
            "hybrid_energy_j": hybrid_energy,
            "hybrid_vs_generic_gain_pct": (
                result.improvement_pct
                if base_energy is not None and hybrid_energy is not None
                else None
            ),
            "exploration_runtime_s": float(
                result.exploration.raw_result.statistics.total_runtime
            ),
            "elite_runtime_s": float(result.elite_runtime_s),
            "total_runtime_s": total_runtime_s,
            "elite_cvx_calls": int(result.elite_cvx_calls),
            "screened_cvx_refinements": int(
                evaluator.stats.cvx_refinements
            ),
            "screened_precheck_rejects": int(
                evaluator.stats.precheck_rejects
            ),
            "proxy_objectives": raw_objectives,
            "proxy_best_trace": proxy_best_trace,
            "pair_best_energy_j": None,
            "gap_to_pair_best_pct": None,
        }
        rows.append(row)
        _write(
            out,
            experiment=experiment,
            rows=rows,
            complete=False,
        )

        def e(value: float | None) -> str:
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{budget:<6} {base_status:<12} {hybrid_status:<12} "
            f"{e(base_energy):<10} {e(hybrid_energy):<11} "
            f"{e(row['hybrid_vs_generic_gain_pct']):<9} "
            f"{total_runtime_s:<9.3f} {result.elite_cvx_calls:<9} "
            f"{raw_objectives[-1]:<11.3f} "
            f"{proxy_best_trace[-1]:.3f}"
        )

    strict_energies = [
        float(row["hybrid_energy_j"])
        for row in rows
        if row["hybrid_energy_j"] is not None
    ]
    if strict_energies:
        pair_best = min(strict_energies)
        for row in rows:
            row["pair_best_energy_j"] = pair_best
            if row["hybrid_energy_j"] is not None:
                row["gap_to_pair_best_pct"] = (
                    100.0
                    * (float(row["hybrid_energy_j"]) - pair_best)
                    / max(1.0, abs(pair_best))
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
