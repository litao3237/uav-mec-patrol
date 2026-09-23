from __future__ import annotations

"""Paired multiscale ESI family ablation.

Protocol
--------
K = 30,50,70,80
scenario seeds = 45,46,47
algorithm seeds = 100,101,102
iterations = 100
elite rounds = 2

For every (K, scenario_seed, algorithm_seed), one generic B-ALNS exploration
trajectory is generated and shared by all five elite profiles. This preserves
the paired-ablation semantics of experiments/run_elite_family_ablation.py.
"""

import argparse
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.problem_operators import (
    contact_mode_intensification,
)
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


PROFILES = (
    "full",
    "no-route",
    "no-contact",
    "no-batch",
    "no-widening",
)


def parse_ints(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def stage1_status(result) -> str:
    return str(result.diagnostics.get("stage1_status", result.status))


def profile_problem_config(base, profile: str):
    """Match the frozen paper-facing elite-family ablation definitions."""
    if profile == "full":
        return base
    if profile == "no-route":
        return replace(
            base,
            elite_enable_route_compute_relocate=False,
        )
    if profile == "no-contact":
        return replace(
            base,
            elite_enable_contact_relocate=False,
            elite_enable_contact_point_replace=False,
            elite_enable_contact_remove=False,
        )
    if profile == "no-batch":
        # Keep mode/batch reassignment enabled. The frozen family ablation
        # removes only the explicit merge/split family.
        return replace(
            base,
            elite_enable_batch_merge=False,
            elite_enable_batch_split=False,
        )
    if profile == "no-widening":
        return replace(
            base,
            elite_progressive_widening=False,
        )
    raise ValueError(f"Unknown profile: {profile}")


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def paired_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for profile in PROFILES:
        if profile == "full":
            continue
        pairs: list[dict[str, Any]] = []
        keys = sorted(
            {
                (
                    row["tasks"],
                    row["scenario_seed"],
                    row["algorithm_seed"],
                )
                for row in rows
            }
        )
        for tasks, scenario_seed, algorithm_seed in keys:
            subset = [
                row
                for row in rows
                if row["tasks"] == tasks
                and row["scenario_seed"] == scenario_seed
                and row["algorithm_seed"] == algorithm_seed
            ]
            by_profile = {row["profile"]: row for row in subset}
            full = by_profile["full"]
            ablated = by_profile[profile]
            comparable = bool(
                full["strict_pair"]
                and ablated["strict_pair"]
                and full["final_energy_j"] is not None
                and ablated["final_energy_j"] is not None
            )
            full_advantage_pct = None
            loss_vs_full_pct = None
            if comparable:
                full_e = float(full["final_energy_j"])
                ablated_e = float(ablated["final_energy_j"])
                full_advantage_pct = (
                    100.0 * (ablated_e - full_e)
                    / max(1.0, abs(ablated_e))
                )
                loss_vs_full_pct = (
                    100.0 * (ablated_e - full_e)
                    / max(1.0, abs(full_e))
                )
            pairs.append(
                {
                    "tasks": tasks,
                    "scenario_seed": scenario_seed,
                    "algorithm_seed": algorithm_seed,
                    "profile": profile,
                    "comparable": comparable,
                    "full_energy_j": full["final_energy_j"],
                    "ablated_energy_j": ablated["final_energy_j"],
                    "full_advantage_pct": full_advantage_pct,
                    "loss_vs_full_pct": loss_vs_full_pct,
                }
            )

        values = [
            float(row["full_advantage_pct"])
            for row in pairs
            if row["comparable"]
            and row["full_advantage_pct"] is not None
        ]
        summaries.append(
            {
                "profile": profile,
                "pairs": pairs,
                "comparable_pairs": len(values),
                "total_pairs": len(pairs),
                "full_better": sum(v > 1e-9 for v in values),
                "equal": sum(abs(v) <= 1e-9 for v in values),
                "ablated_better": sum(v < -1e-9 for v in values),
                "mean_full_advantage_pct": (
                    mean(values) if values else None
                ),
                "median_full_advantage_pct": (
                    median(values) if values else None
                ),
            }
        )
    return summaries


def aggregate_profiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tasks in sorted({int(row["tasks"]) for row in rows}):
        for profile in PROFILES:
            subset = [
                row for row in rows
                if int(row["tasks"]) == tasks
                and row["profile"] == profile
            ]
            strict = [row for row in subset if row["strict_pair"]]
            energies = [
                float(row["final_energy_j"])
                for row in strict
                if row["final_energy_j"] is not None
            ]
            gains = [
                float(row["gain_vs_base_pct"])
                for row in strict
                if row["gain_vs_base_pct"] is not None
            ]
            out.append(
                {
                    "tasks": tasks,
                    "profile": profile,
                    "runs": len(subset),
                    "strict_pairs": len(strict),
                    "strict_pair_rate": (
                        len(strict) / len(subset) if subset else 0.0
                    ),
                    "mean_final_energy_j": (
                        mean(energies) if energies else None
                    ),
                    "mean_gain_vs_base_pct": (
                        mean(gains) if gains else None
                    ),
                    "improved_vs_base": sum(v > 1e-9 for v in gains),
                    "unchanged_vs_base": sum(abs(v) <= 1e-9 for v in gains),
                    "mean_elite_cvx_calls": (
                        mean(row["elite_cvx_calls"] for row in subset)
                        if subset else 0.0
                    ),
                    "mean_elite_runtime_s": (
                        mean(row["elite_runtime_s"] for row in subset)
                        if subset else 0.0
                    ),
                }
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30,50,70,80")
    parser.add_argument("--scenario-seeds", default="45,46,47")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--mecs", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=5)
    parser.add_argument(
        "--output",
        default="outputs/results/multiscale_ablation.json",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    task_counts = parse_ints(args.tasks)
    scenario_seeds = parse_ints(args.scenario_seeds)
    algorithm_seeds = parse_ints(args.algorithm_seeds)
    output = Path(args.output)

    rows: list[dict[str, Any]] = []
    protocol = {
        "tasks": task_counts,
        "scenario_seeds": scenario_seeds,
        "algorithm_seeds": algorithm_seeds,
        "profiles": list(PROFILES),
        "iterations": args.iterations,
        "elite_rounds": args.elite_rounds,
        "mecs": args.mecs,
        "uavs": args.uavs,
        "shared_exploration": True,
        "strict_definition": "Stage-1 status == optimal",
        "no_batch_definition": (
            "disable explicit batch_merge and batch_split only; "
            "keep mode_batch_reassign enabled"
        ),
    }

    for tasks in task_counts:
        for scenario_seed in scenario_seeds:
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=tasks,
                num_uavs=args.uavs,
                num_mecs=args.mecs,
                scenario_seed=scenario_seed,
            )
            route_seed = build_greedy_initial_solution(instance)
            initial = build_mec_assisted_initial_solution(
                instance,
                base_solution=route_seed,
            )

            for algorithm_seed in algorithm_seeds:
                evaluator = ScreenedProxyObjectiveEvaluator()
                config = UavMecALNSConfig(
                    seed=algorithm_seed,
                    iterations=args.iterations,
                )
                exploration = run_uav_mec_alns(
                    instance,
                    initial_solution=initial,
                    config=config,
                    evaluator=evaluator,
                )

                base_oracle = Stage1CVXObjectiveOracle()
                base_cvx = base_oracle.solve(
                    instance,
                    exploration.best_solution,
                )
                base_status = stage1_status(base_cvx)
                base_energy = (
                    float(base_cvx.energy_stage1_j)
                    if base_cvx.feasible and base_status == "optimal"
                    else None
                )

                for profile in PROFILES:
                    oracle = Stage1CVXObjectiveOracle()
                    stats: dict[str, Any] = {
                        "rounds": 0,
                        "candidates_evaluated": 0,
                        "improvements": 0,
                        "accepted_moves": [],
                        "evaluated_moves": [],
                        "widenings": 0,
                        "widened_candidates_evaluated": 0,
                        "widened_families": [],
                    }
                    started = perf_counter()
                    if base_energy is not None:
                        state = UavMecState(
                            instance,
                            deepcopy(exploration.best_solution),
                            evaluator,
                        )
                        final_state, stats = contact_mode_intensification(
                            state,
                            config=profile_problem_config(
                                config.problem,
                                profile,
                            ),
                            objective=oracle,
                            max_rounds=args.elite_rounds,
                        )
                        final_cvx = oracle.solve(
                            instance,
                            final_state.solution,
                        )
                    else:
                        final_cvx = base_cvx
                        stats["skipped"] = (
                            "exploration_stage1_not_strict_optimal"
                            if base_cvx.feasible
                            else "exploration_stage1_infeasible"
                        )
                    elite_runtime_s = perf_counter() - started

                    final_status = stage1_status(final_cvx)
                    final_energy = (
                        float(final_cvx.energy_stage1_j)
                        if final_cvx.feasible
                        and final_status == "optimal"
                        else None
                    )
                    strict_pair = bool(
                        base_energy is not None
                        and final_energy is not None
                    )
                    gain_vs_base_pct = (
                        100.0 * (base_energy - final_energy)
                        / max(1.0, abs(base_energy))
                        if strict_pair else None
                    )
                    rows.append(
                        {
                            "tasks": tasks,
                            "scenario_seed": scenario_seed,
                            "algorithm_seed": algorithm_seed,
                            "profile": profile,
                            "base_stage1_status": base_status,
                            "base_energy_j": base_energy,
                            "final_stage1_status": final_status,
                            "final_energy_j": final_energy,
                            "strict_pair": strict_pair,
                            "gain_vs_base_pct": gain_vs_base_pct,
                            "accepted": int(stats.get("improvements", 0)),
                            "elite_cvx_calls": oracle.calls,
                            "elite_cvx_cache_hits": oracle.cache_hits,
                            "elite_runtime_s": elite_runtime_s,
                            "elite_stats": stats,
                        }
                    )

                write_output(
                    output,
                    {
                        "complete": False,
                        "experiment": "multiscale_elite_family_ablation",
                        "protocol": protocol,
                        "rows": rows,
                    },
                )

    aggregate = aggregate_profiles(rows)
    paired = paired_summaries(rows)
    payload = {
        "complete": True,
        "experiment": "multiscale_elite_family_ablation",
        "protocol": protocol,
        "aggregate": aggregate,
        "paired": paired,
        "rows": rows,
    }
    write_output(output, payload)

    print(
        json.dumps(
            {
                "complete": True,
                "rows": len(rows),
                "expected_rows": (
                    len(task_counts)
                    * len(scenario_seeds)
                    * len(algorithm_seeds)
                    * len(PROFILES)
                ),
                "shared_exploration": True,
                "aggregate": aggregate,
                "paired_summary": [
                    {
                        k: v
                        for k, v in item.items()
                        if k != "pairs"
                    }
                    for item in paired
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
