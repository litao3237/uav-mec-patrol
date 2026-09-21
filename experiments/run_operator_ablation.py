from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _solution_summary(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    offloaded = sum(
        decision.mode.value == "offload"
        for decision in solution.task_decisions.values()
    )
    return {
        "contacts": len(solution.contact_visits),
        "offloaded": offloaded,
        "distance_m": sum(info.route_distance_m.values()),
        "active_pairs": len(info.active_uav_mec_pairs),
    }



def _operator_counts(raw_result) -> dict[str, dict[str, list[int]]]:
    stats = raw_result.statistics
    return {
        "destroy": {
            name: list(counts)
            for name, counts in stats.destroy_operator_counts.items()
        },
        "repair": {
            name: list(counts)
            for name, counts in stats.repair_operator_counts.items()
        },
    }


def _count_summary(counts: dict[str, list[int]]) -> dict[str, dict[str, int]]:
    return {
        name: {
            "best": int(values[0]),
            "better": int(values[1]),
            "accepted": int(values[2]),
            "rejected": int(values[3]),
            "uses": int(sum(values)),
        }
        for name, values in counts.items()
    }


def _print_operator_summary(
    mode: str,
    raw_result,
) -> None:
    counts = _operator_counts(raw_result)
    print(f"  Operator outcomes [{mode}]")
    for family in ("destroy", "repair"):
        summary = _count_summary(counts[family])
        items = sorted(
            summary.items(),
            key=lambda item: (
                -item[1]["best"],
                -item[1]["better"],
                -item[1]["accepted"],
                item[1]["rejected"],
                item[0],
            ),
        )
        print(f"    {family}:")
        for name, values in items:
            print(
                f"      {name}: uses={values['uses']} "
                f"best={values['best']} better={values['better']} "
                f"accepted={values['accepted']} "
                f"rejected={values['rejected']}"
            )

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ablate generic ALNS against the proposed problem-specific "
            "contact/batch/compute operator families."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="80")
    parser.add_argument("--mecs", default="2")
    parser.add_argument("--scenario-seeds", default="42,43,44")
    parser.add_argument("--algorithm-seeds", default="100")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--uavs", type=int, default=None)
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    task_counts = _parse_int_list(args.tasks)
    mec_counts = _parse_int_list(args.mecs)
    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)

    rows: list[dict[str, Any]] = []

    print(
        "K    E    scen   alg    mode       cvx-s1       "
        "cvx-E-J        contacts   offload   pairs   "
        "cvx-ref   pre-rej   runtime-s"
    )
    print("-" * 132)

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
                    for mode, enabled in (
                        ("generic", False),
                        ("proposed", True),
                    ):
                        evaluator = ScreenedProxyObjectiveEvaluator()
                        config = UavMecALNSConfig(
                            iterations=args.iterations,
                            seed=algorithm_seed,
                            enable_problem_operators=enabled,
                        )

                        t0 = perf_counter()
                        result = run_uav_mec_alns(
                            instance,
                            initial_solution=initial,
                            config=config,
                            evaluator=evaluator,
                        )
                        runtime_s = perf_counter() - t0

                        best_info = build_event_info(
                            instance,
                            result.best_solution,
                        )
                        cvx = CVXResourceSolver(
                            run_stage2=False
                        ).solve(
                            instance,
                            result.best_solution,
                            best_info,
                        )
                        cvx_status = cvx.diagnostics.get(
                            "stage1_status",
                            cvx.status,
                        )
                        summary = _solution_summary(
                            instance,
                            result.best_solution,
                        )

                        row = {
                            "K": k,
                            "E": e,
                            "scenario_seed": scenario_seed,
                            "algorithm_seed": algorithm_seed,
                            "mode": mode,
                            "iterations": args.iterations,
                            "best_search_objective": (
                                result.best_objective
                            ),
                            "best_cvx_status": cvx_status,
                            "best_cvx_feasible": cvx.feasible,
                            "best_cvx_energy_j": (
                                cvx.energy_stage1_j
                                if cvx.feasible
                                else None
                            ),
                            "runtime_s": runtime_s,
                            "evaluator_calls": evaluator.stats.calls,
                            "cache_hits": evaluator.stats.cache_hits,
                            "precheck_rejects": (
                                evaluator.stats.precheck_rejects
                            ),
                            "ambiguous_proxy_calls": (
                                evaluator.stats.ambiguous_proxy_calls
                            ),
                            "cvx_refinements": (
                                evaluator.stats.cvx_refinements
                            ),
                            "solution": summary,
                            "operator_counts": _operator_counts(
                                result.raw_result
                            ),
                        }
                        rows.append(row)

                        energy_text = (
                            f"{cvx.energy_stage1_j:.3f}"
                            if cvx.feasible
                            else "-"
                        )
                        print(
                            f"{k:<4} "
                            f"{e:<4} "
                            f"{scenario_seed:<6} "
                            f"{algorithm_seed:<6} "
                            f"{mode:<10} "
                            f"{str(cvx_status):<12} "
                            f"{energy_text:<14} "
                            f"{summary['contacts']:<10} "
                            f"{summary['offloaded']:<9} "
                            f"{summary['active_pairs']:<7} "
                            f"{evaluator.stats.cvx_refinements:<9} "
                            f"{evaluator.stats.precheck_rejects:<9} "
                            f"{runtime_s:.2f}"
                        )
                        _print_operator_summary(
                            mode,
                            result.raw_result,
                        )

    aggregate: list[dict[str, Any]] = []
    for k in task_counts:
        for e in mec_counts:
            for mode in ("generic", "proposed"):
                subset = [
                    row
                    for row in rows
                    if (
                        row["K"] == k
                        and row["E"] == e
                        and row["mode"] == mode
                    )
                ]
                if not subset:
                    continue
                feasible = [
                    row for row in subset
                    if row["best_cvx_feasible"]
                ]
                group = {
                    "K": k,
                    "E": e,
                    "mode": mode,
                    "runs": len(subset),
                    "cvx_feasible_rate": (
                        len(feasible) / len(subset)
                    ),
                    "mean_cvx_energy_j": (
                        mean(
                            row["best_cvx_energy_j"]
                            for row in feasible
                        )
                        if feasible
                        else None
                    ),
                    "mean_runtime_s": mean(
                        row["runtime_s"] for row in subset
                    ),
                    "mean_cvx_refinements": mean(
                        row["cvx_refinements"] for row in subset
                    ),
                    "mean_precheck_rejects": mean(
                        row["precheck_rejects"] for row in subset
                    ),
                }
                aggregate.append(group)

    print("\nAggregate")
    print(
        "K    E    mode       runs   feasible-rate   "
        "mean-cvx-E-J   mean-runtime-s   mean-cvx-ref"
    )
    print("-" * 92)
    for group in aggregate:
        energy_text = (
            f"{group['mean_cvx_energy_j']:.3f}"
            if group["mean_cvx_energy_j"] is not None
            else "-"
        )
        print(
            f"{group['K']:<4} "
            f"{group['E']:<4} "
            f"{group['mode']:<10} "
            f"{group['runs']:<6} "
            f"{group['cvx_feasible_rate']:<15.3f} "
            f"{energy_text:<14} "
            f"{group['mean_runtime_s']:<16.2f} "
            f"{group['mean_cvx_refinements']:.2f}"
        )

    out = Path("outputs/results/operator_ablation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"aggregate": aggregate, "rows": rows},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
