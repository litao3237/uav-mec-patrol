from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from uav_mec.algorithms import (
    ProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import DestroyConfig
from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _pair_stats(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    counts = Counter(mec_id for _, mec_id in info.active_uav_mec_pairs)
    offloaded = sum(
        decision.mode is ExecutionMode.OFFLOAD
        for decision in solution.task_decisions.values()
    )
    return {
        "offloaded": offloaded,
        "contacts": len(solution.contact_visits),
        "active_pairs": len(info.active_uav_mec_pairs),
        "used_mecs": len(counts),
        "shared_mecs": sum(count >= 2 for count in counts.values()),
        "max_pairs_per_mec": max(counts.values(), default=0),
        "pairs_per_mec": dict(sorted(counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cheap scale sweep for genuine multi-UAV competition at MECs. "
            "No CVXPY solve is performed."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30,50,80")
    parser.add_argument("--mecs", default="2,3,4")
    parser.add_argument("--seeds", default="42,43,44")
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--alns-iterations", type=int, default=20)
    parser.add_argument(
        "--candidate",
        choices=("repaired", "alns", "both"),
        default="both",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    task_counts = _parse_int_list(args.tasks)
    mec_counts = _parse_int_list(args.mecs)
    seeds = _parse_int_list(args.seeds)

    rows: list[dict[str, Any]] = []

    print(
        "K    E    seed   source     offload   contacts   "
        "pairs   used-MEC   shared-MEC   max-pairs/MEC"
    )
    print("-" * 104)

    for k in task_counts:
        for e in mec_counts:
            for seed_idx, scenario_seed in enumerate(seeds):
                instance = build_paper_scale_instance(
                    cfg,
                    num_tasks=k,
                    num_uavs=args.uavs,
                    num_mecs=e,
                    scenario_seed=scenario_seed,
                )

                route_seed = build_greedy_initial_solution(instance)
                repaired = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=route_seed,
                )

                candidates: list[tuple[str, object]] = []
                if args.candidate in ("repaired", "both"):
                    candidates.append(("repaired", repaired))

                if args.candidate in ("alns", "both"):
                    result = run_uav_mec_alns(
                        instance,
                        initial_solution=repaired,
                        config=UavMecALNSConfig(
                            iterations=args.alns_iterations,
                            seed=cfg.algorithm_seed + seed_idx,
                            destroy=DestroyConfig(),
                        ),
                        evaluator=ProxyObjectiveEvaluator(),
                    )
                    candidates.append(("alns-best", result.best_solution))

                for source, solution in candidates:
                    stats = _pair_stats(instance, solution)
                    row = {
                        "K": k,
                        "E": e,
                        "scenario_seed": scenario_seed,
                        "source": source,
                        **stats,
                    }
                    rows.append(row)
                    print(
                        f"{k:<4} "
                        f"{e:<4} "
                        f"{scenario_seed:<6} "
                        f"{source:<10} "
                        f"{stats['offloaded']:<9} "
                        f"{stats['contacts']:<10} "
                        f"{stats['active_pairs']:<7} "
                        f"{stats['used_mecs']:<10} "
                        f"{stats['shared_mecs']:<12} "
                        f"{stats['max_pairs_per_mec']}"
                    )

    grouped: list[dict[str, Any]] = []
    for k in task_counts:
        for e in mec_counts:
            subset = [
                row
                for row in rows
                if row["K"] == k and row["E"] == e
            ]
            if not subset:
                continue
            shared_states = sum(
                row["shared_mecs"] > 0 for row in subset
            )
            group = {
                "K": k,
                "E": e,
                "states": len(subset),
                "shared_states": shared_states,
                "shared_state_rate": shared_states / len(subset),
                "mean_offloaded": mean(
                    row["offloaded"] for row in subset
                ),
                "mean_active_pairs": mean(
                    row["active_pairs"] for row in subset
                ),
                "max_pairs_per_mec": max(
                    row["max_pairs_per_mec"] for row in subset
                ),
            }
            grouped.append(group)

    print("\nSummary by (K,E)")
    print(
        "K    E    states   shared-states   shared-rate   "
        "mean-offload   mean-pairs   max-pairs/MEC"
    )
    print("-" * 96)
    for group in grouped:
        print(
            f"{group['K']:<4} "
            f"{group['E']:<4} "
            f"{group['states']:<8} "
            f"{group['shared_states']:<15} "
            f"{group['shared_state_rate']:<13.3f} "
            f"{group['mean_offloaded']:<14.2f} "
            f"{group['mean_active_pairs']:<12.2f} "
            f"{group['max_pairs_per_mec']}"
        )

    out = Path("outputs/results/shared_mec_scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"summary": grouped, "rows": rows},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
