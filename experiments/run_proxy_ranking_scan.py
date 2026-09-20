from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    ProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    evaluate_initial_proxy,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import DestroyConfig, solution_signature
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while (
            j < len(order)
            and math.isclose(
                values[order[j]],
                values[order[i]],
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ):
            j += 1
        average_rank = 0.5 * ((i + 1) + j)
        for idx in order[i:j]:
            ranks[idx] = average_rank
        i = j
    return ranks


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 2 or len(x) != len(y):
        return None
    mx = mean(x)
    my = mean(y)
    dx = [value - mx for value in x]
    dy = [value - my for value in y]
    denom_x = math.sqrt(sum(value * value for value in dx))
    denom_y = math.sqrt(sum(value * value for value in dy))
    if denom_x <= 0.0 or denom_y <= 0.0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / (denom_x * denom_y)


def _spearman(x: list[float], y: list[float]) -> float | None:
    return _pearson(_average_ranks(x), _average_ranks(y))


def _pairwise_order_agreement(
    proxy_values: list[float],
    cvx_values: list[float],
) -> tuple[float | None, int]:
    agree = 0
    compared = 0
    for i in range(len(proxy_values)):
        for j in range(i + 1, len(proxy_values)):
            p_delta = proxy_values[i] - proxy_values[j]
            c_delta = cvx_values[i] - cvx_values[j]
            p_scale = max(1.0, abs(proxy_values[i]), abs(proxy_values[j]))
            c_scale = max(1.0, abs(cvx_values[i]), abs(cvx_values[j]))
            p_tie = abs(p_delta) <= 1e-9 * p_scale
            c_tie = abs(c_delta) <= 1e-9 * c_scale

            if p_tie and c_tie:
                agree += 1
                compared += 1
            elif p_tie or c_tie:
                compared += 1
            else:
                agree += int((p_delta < 0.0) == (c_delta < 0.0))
                compared += 1

    if compared == 0:
        return None, 0
    return agree / compared, compared


def _evaluate_candidate(instance, solution) -> dict[str, Any]:
    proxy = evaluate_initial_proxy(instance, solution)
    info = build_event_info(instance, solution)

    t0 = perf_counter()
    cvx = CVXResourceSolver().solve(instance, solution, info)
    cvx_runtime = perf_counter() - t0

    gap = None
    if cvx.feasible:
        gap = (
            abs(proxy.score.total_energy_j - cvx.energy_stage1_j)
            / max(1.0, abs(cvx.energy_stage1_j))
        )

    return {
        "proxy_violated_constraints": proxy.score.violated_constraints,
        "proxy_energy_j": proxy.score.total_energy_j,
        "cvx_status": cvx.status,
        "cvx_stage1_status": cvx.diagnostics.get(
            "stage1_status", cvx.status
        ),
        "cvx_stage2_status": cvx.diagnostics.get("stage2_status"),
        "cvx_stage1_solver": cvx.diagnostics.get("stage1_solver"),
        "cvx_feasible": cvx.feasible,
        "cvx_energy_stage1_j": cvx.energy_stage1_j,
        "proxy_vs_cvx_relative_gap": gap,
        "cvx_runtime_s": cvx_runtime,
        "contacts": len(solution.contact_visits),
        "route_signature": solution_signature(solution),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether the fast proxy preserves CVXPY Stage-1 ranking "
            "across diverse ALNS candidate solutions."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, default=30)
    parser.add_argument("--scenario-seeds", default="42,43,44")
    parser.add_argument("--algorithm-seeds", default="100,101,102,103,104")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--mecs", type=int, default=None)
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)

    all_rows: list[dict[str, Any]] = []
    scenario_stats: list[dict[str, Any]] = []

    print(
        "scenario   candidate        alg-seed   proxy-E-J      cvx-E-J        "
        "gap-%    cvx-s1       contacts"
    )
    print("-" * 108)

    for scenario_seed in scenario_seeds:
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=args.tasks,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=scenario_seed,
        )
        route_seed = build_greedy_initial_solution(instance)
        repaired = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )

        candidates: list[tuple[str, int | None, object]] = [
            ("repaired", None, repaired)
        ]
        seen = {solution_signature(repaired)}

        for algorithm_seed in algorithm_seeds:
            result = run_uav_mec_alns(
                instance,
                initial_solution=repaired,
                config=UavMecALNSConfig(
                    iterations=args.iterations,
                    seed=algorithm_seed,
                    destroy=DestroyConfig(),
                ),
                evaluator=ProxyObjectiveEvaluator(),
            )
            signature = solution_signature(result.best_solution)
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(
                ("alns-best", algorithm_seed, result.best_solution)
            )

        scenario_rows: list[dict[str, Any]] = []
        for idx, (source, algorithm_seed, solution) in enumerate(candidates):
            metrics = _evaluate_candidate(instance, solution)
            row = {
                "scenario_seed": scenario_seed,
                "candidate_index": idx,
                "source": source,
                "algorithm_seed": algorithm_seed,
                **metrics,
            }
            scenario_rows.append(row)
            all_rows.append(row)

            cvx_energy = (
                f"{metrics['cvx_energy_stage1_j']:.3f}"
                if metrics["cvx_feasible"]
                else "-"
            )
            gap = metrics["proxy_vs_cvx_relative_gap"]
            gap_text = f"{100.0 * gap:.3f}" if gap is not None else "-"
            print(
                f"{scenario_seed:<10} "
                f"{source:<16} "
                f"{str(algorithm_seed):<10} "
                f"{metrics['proxy_energy_j']:<14.3f} "
                f"{cvx_energy:<14} "
                f"{gap_text:<8} "
                f"{str(metrics['cvx_stage1_status']):<12} "
                f"{metrics['contacts']}"
            )

        comparable = [
            row
            for row in scenario_rows
            if row["cvx_feasible"]
            and row["proxy_violated_constraints"] == 0
        ]
        proxy_values = [row["proxy_energy_j"] for row in comparable]
        cvx_values = [row["cvx_energy_stage1_j"] for row in comparable]
        gaps = [
            row["proxy_vs_cvx_relative_gap"]
            for row in comparable
            if row["proxy_vs_cvx_relative_gap"] is not None
        ]
        trusted = [
            row
            for row in comparable
            if row["cvx_stage1_status"] == "optimal"
        ]
        trusted_proxy = [row["proxy_energy_j"] for row in trusted]
        trusted_cvx = [row["cvx_energy_stage1_j"] for row in trusted]

        agreement, pair_count = _pairwise_order_agreement(
            proxy_values,
            cvx_values,
        )
        trusted_agreement, trusted_pair_count = _pairwise_order_agreement(
            trusted_proxy,
            trusted_cvx,
        )

        stats = {
            "scenario_seed": scenario_seed,
            "unique_candidates": len(candidates),
            "comparable_candidates": len(comparable),
            "trusted_stage1_candidates": len(trusted),
            "mean_relative_gap": mean(gaps) if gaps else None,
            "max_relative_gap": max(gaps) if gaps else None,
            "pearson_energy": _pearson(proxy_values, cvx_values),
            "spearman_rank": _spearman(proxy_values, cvx_values),
            "pairwise_order_agreement": agreement,
            "pairwise_pairs": pair_count,
            "trusted_spearman_rank": _spearman(
                trusted_proxy,
                trusted_cvx,
            ),
            "trusted_pairwise_order_agreement": trusted_agreement,
            "trusted_pairwise_pairs": trusted_pair_count,
        }
        scenario_stats.append(stats)

        print(
            f"  -> seed {scenario_seed}: unique={len(candidates)}, "
            f"mean-gap={100.0 * stats['mean_relative_gap']:.3f}% "
            f"max-gap={100.0 * stats['max_relative_gap']:.3f}% "
            f"spearman={stats['spearman_rank']} "
            f"order={stats['pairwise_order_agreement']}\n"
        )

    valid_spearman = [
        item["spearman_rank"]
        for item in scenario_stats
        if item["spearman_rank"] is not None
    ]
    valid_order = [
        item["pairwise_order_agreement"]
        for item in scenario_stats
        if item["pairwise_order_agreement"] is not None
    ]
    all_gaps = [
        row["proxy_vs_cvx_relative_gap"]
        for row in all_rows
        if row["proxy_vs_cvx_relative_gap"] is not None
    ]

    aggregate = {
        "scenario_count": len(scenario_stats),
        "candidate_count": len(all_rows),
        "mean_relative_gap": mean(all_gaps) if all_gaps else None,
        "max_relative_gap": max(all_gaps) if all_gaps else None,
        "mean_spearman_rank": (
            mean(valid_spearman) if valid_spearman else None
        ),
        "mean_pairwise_order_agreement": (
            mean(valid_order) if valid_order else None
        ),
    }

    print(
        "Aggregate: "
        f"candidates={len(all_rows)} "
        f"mean-gap={100.0 * aggregate['mean_relative_gap']:.3f}% "
        f"max-gap={100.0 * aggregate['max_relative_gap']:.3f}% "
        f"mean-spearman={aggregate['mean_spearman_rank']} "
        f"mean-order={aggregate['mean_pairwise_order_agreement']}"
    )

    out = Path("outputs/results/proxy_ranking_scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "aggregate": aggregate,
                "scenario_stats": scenario_stats,
                "rows": all_rows,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
