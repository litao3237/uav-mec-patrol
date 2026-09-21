from __future__ import annotations

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


def _profile_problem_config(base, profile: str):
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


def _default_output_path(
    *,
    task_counts: list[int],
    mec_counts: list[int],
    scenario_seeds: list[int],
    algorithm_seeds: list[int],
    iterations: int,
) -> Path:
    return Path("outputs/results") / (
        "elite_family_ablation"
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
    aggregate: list[dict[str, Any]],
    paired: list[dict[str, Any]],
    complete: bool,
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "complete": complete,
                "experiment": experiment,
                "aggregate": aggregate,
                "paired": paired,
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
            "Paired elite-family ablation from one shared generic ALNS "
            "exploration trajectory per scenario/algorithm seed."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="80")
    parser.add_argument("--mecs", default="2")
    parser.add_argument(
        "--scenario-seeds",
        default="45,46,47",
    )
    parser.add_argument(
        "--algorithm-seeds",
        default="100,101,102",
    )
    parser.add_argument(
        "--profiles",
        default="full,no-route",
        help=(
            "paired profiles: full plus one of "
            "no-route,no-contact,no-batch,no-widening"
        ),
    )
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    task_counts = _parse_int_list(args.tasks)
    mec_counts = _parse_int_list(args.mecs)
    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)
    profiles = [
        item.strip()
        for item in args.profiles.split(",")
        if item.strip()
    ]
    valid_profiles = {
        "full",
        "no-route",
        "no-contact",
        "no-batch",
        "no-widening",
    }
    invalid = set(profiles) - valid_profiles
    if invalid:
        raise ValueError(
            f"Unknown profiles: {sorted(invalid)}"
        )
    ablated_profiles = [
        profile for profile in profiles if profile != "full"
    ]
    if "full" not in profiles or len(ablated_profiles) != 1:
        raise ValueError(
            "Paired family ablation requires full plus exactly "
            "one ablated profile."
        )
    ablation_profile = ablated_profiles[0]

    cfg = load_paper_scale_config(args.config)
    out = (
        Path(args.output)
        if args.output is not None
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
        "profiles": profiles,
        "iterations": args.iterations,
        "elite_rounds": args.elite_rounds,
        "uavs": args.uavs,
        "shared_exploration": True,
        "ablation_profile": ablation_profile,
    }

    rows: list[dict[str, Any]] = []

    print(
        "K    E    scen   alg    profile    base-s1      final-s1     "
        "base-E-J       final-E-J      gain-%    elite-cvx   "
        "accepted   elite-s"
    )
    print("-" * 154)

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
                route_seed = build_greedy_initial_solution(instance)
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=route_seed,
                )

                for algorithm_seed in algorithm_seeds:
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    config = UavMecALNSConfig(
                        iterations=args.iterations,
                        seed=algorithm_seed,
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
                    base_status = _stage1_status(base_cvx)
                    base_energy = (
                        float(base_cvx.energy_stage1_j)
                        if base_cvx.feasible
                        else None
                    )

                    for profile in profiles:
                        problem_config = _profile_problem_config(
                            config.problem,
                            profile,
                        )
                        oracle = Stage1CVXObjectiveOracle()
                        accepted_moves: list[dict[str, Any]] = []
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

                        t0 = perf_counter()
                        if (
                            base_cvx.feasible
                            and base_status == "optimal"
                        ):
                            state = UavMecState(
                                instance,
                                deepcopy(exploration.best_solution),
                                evaluator,
                            )
                            final_state, stats = (
                                contact_mode_intensification(
                                    state,
                                    config=problem_config,
                                    objective=oracle,
                                    max_rounds=args.elite_rounds,
                                )
                            )
                            final_solution = final_state.solution
                            final_cvx = oracle.solve(
                                instance,
                                final_solution,
                            )
                            accepted_moves = list(
                                stats.get("accepted_moves", [])
                            )
                        else:
                            final_solution = deepcopy(
                                exploration.best_solution
                            )
                            final_cvx = base_cvx
                            stats["skipped"] = (
                                "exploration_stage1_not_strict_optimal"
                                if base_cvx.feasible
                                else "exploration_stage1_infeasible"
                            )
                        elite_runtime_s = perf_counter() - t0

                        final_status = _stage1_status(final_cvx)
                        final_energy = (
                            float(final_cvx.energy_stage1_j)
                            if final_cvx.feasible
                            else None
                        )
                        strict = (
                            base_status == "optimal"
                            and final_status == "optimal"
                            and base_energy is not None
                            and final_energy is not None
                        )
                        gain_pct = (
                            100.0
                            * (base_energy - final_energy)
                            / max(1.0, abs(base_energy))
                            if strict
                            else None
                        )
                        move_text = (
                            ",".join(
                                str(item["move"])
                                for item in accepted_moves
                            )
                            if accepted_moves
                            else "-"
                        )

                        row = {
                            "K": k,
                            "E": e,
                            "scenario_seed": scenario_seed,
                            "algorithm_seed": algorithm_seed,
                            "profile": profile,
                            "iterations": args.iterations,
                            "base_stage1_status": base_status,
                            "final_stage1_status": final_status,
                            "base_energy_j": base_energy,
                            "final_energy_j": final_energy,
                            "strict_pair": strict,
                            "gain_pct": gain_pct,
                            "elite_cvx_calls": oracle.calls,
                            "elite_cvx_cache_hits": oracle.cache_hits,
                            "elite_runtime_s": elite_runtime_s,
                            "elite_stats": stats,
                            "accepted_moves": accepted_moves,
                        }
                        rows.append(row)
                        _write(
                            out,
                            experiment=experiment,
                            rows=rows,
                            aggregate=[],
                            paired=[],
                            complete=False,
                        )

                        base_text = (
                            f"{base_energy:.3f}"
                            if base_energy is not None
                            else "-"
                        )
                        final_text = (
                            f"{final_energy:.3f}"
                            if final_energy is not None
                            else "-"
                        )
                        gain_text = (
                            f"{gain_pct:.3f}"
                            if gain_pct is not None
                            else "-"
                        )
                        print(
                            f"{k:<4} {e:<4} "
                            f"{scenario_seed:<6} "
                            f"{algorithm_seed:<6} "
                            f"{profile:<10} "
                            f"{base_status:<12} "
                            f"{final_status:<12} "
                            f"{base_text:<14} "
                            f"{final_text:<14} "
                            f"{gain_text:<9} "
                            f"{oracle.calls:<11} "
                            f"{move_text:<44} "
                            f"{elite_runtime_s:.2f}"
                        )

    aggregate: list[dict[str, Any]] = []
    for k in task_counts:
        for e in mec_counts:
            for profile in profiles:
                subset = [
                    row
                    for row in rows
                    if (
                        row["K"] == k
                        and row["E"] == e
                        and row["profile"] == profile
                    )
                ]
                strict_rows = [
                    row for row in subset if row["strict_pair"]
                ]
                gains = [
                    float(row["gain_pct"])
                    for row in strict_rows
                    if row["gain_pct"] is not None
                ]
                aggregate.append(
                    {
                        "K": k,
                        "E": e,
                        "profile": profile,
                        "runs": len(subset),
                        "strict_pairs": len(strict_rows),
                        "strict_pair_rate": (
                            len(strict_rows) / len(subset)
                            if subset
                            else 0.0
                        ),
                        "improved_runs": sum(
                            gain > 1e-9 for gain in gains
                        ),
                        "unchanged_runs": sum(
                            abs(gain) <= 1e-9 for gain in gains
                        ),
                        "mean_gain_pct": (
                            mean(gains) if gains else None
                        ),
                        "median_gain_pct": (
                            median(gains) if gains else None
                        ),
                        "mean_elite_cvx_calls": (
                            mean(
                                row["elite_cvx_calls"]
                                for row in subset
                            )
                            if subset
                            else 0.0
                        ),
                        "mean_elite_runtime_s": (
                            mean(
                                row["elite_runtime_s"]
                                for row in subset
                            )
                            if subset
                            else 0.0
                        ),
                    }
                )

    paired: list[dict[str, Any]] = []
    keys = sorted(
        {
            (
                row["K"],
                row["E"],
                row["scenario_seed"],
                row["algorithm_seed"],
            )
            for row in rows
        }
    )
    for k, e, scenario_seed, algorithm_seed in keys:
        by_profile = {
            row["profile"]: row
            for row in rows
            if (
                row["K"] == k
                and row["E"] == e
                and row["scenario_seed"] == scenario_seed
                and row["algorithm_seed"] == algorithm_seed
            )
        }
        full = by_profile["full"]
        ablated = by_profile[ablation_profile]
        comparable = (
            full["strict_pair"]
            and ablated["strict_pair"]
            and full["final_energy_j"] is not None
            and ablated["final_energy_j"] is not None
        )
        delta_pct = (
            100.0
            * (
                float(ablated["final_energy_j"])
                - float(full["final_energy_j"])
            )
            / max(1.0, abs(float(ablated["final_energy_j"])))
            if comparable
            else None
        )
        paired.append(
            {
                "K": k,
                "E": e,
                "scenario_seed": scenario_seed,
                "algorithm_seed": algorithm_seed,
                "comparable": comparable,
                "ablation_profile": ablation_profile,
                "full_energy_j": full["final_energy_j"],
                "ablated_energy_j": ablated["final_energy_j"],
                "full_advantage_pct": delta_pct,
            }
        )

    print("\nAggregate")
    print(
        "K    E    profile    runs   strict   improved   "
        "unchanged   mean-gain-%   median-gain-%   "
        "elite-cvx   elite-s"
    )
    print("-" * 112)
    for group in aggregate:
        mean_text = (
            f"{group['mean_gain_pct']:.3f}"
            if group["mean_gain_pct"] is not None
            else "-"
        )
        median_text = (
            f"{group['median_gain_pct']:.3f}"
            if group["median_gain_pct"] is not None
            else "-"
        )
        print(
            f"{group['K']:<4} {group['E']:<4} "
            f"{group['profile']:<10} "
            f"{group['runs']:<6} "
            f"{group['strict_pairs']:<8} "
            f"{group['improved_runs']:<10} "
            f"{group['unchanged_runs']:<11} "
            f"{mean_text:<13} "
            f"{median_text:<15} "
            f"{group['mean_elite_cvx_calls']:<11.2f} "
            f"{group['mean_elite_runtime_s']:.2f}"
        )

    comparable = [
        row for row in paired if row["comparable"]
    ]
    advantages = [
        float(row["full_advantage_pct"])
        for row in comparable
        if row["full_advantage_pct"] is not None
    ]
    print(f"\nFull vs {ablation_profile} paired comparison")
    if advantages:
        print(
            f"comparable={len(advantages)}/{len(paired)} "
            f"full-better={sum(v > 1e-9 for v in advantages)} "
            f"equal={sum(abs(v) <= 1e-9 for v in advantages)} "
            f"{ablation_profile}-better={sum(v < -1e-9 for v in advantages)} "
            f"mean-full-advantage={mean(advantages):.3f}% "
            f"median-full-advantage={median(advantages):.3f}%"
        )
    else:
        print("No strict comparable pairs.")

    _write(
        out,
        experiment=experiment,
        rows=rows,
        aggregate=aggregate,
        paired=paired,
        complete=True,
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
