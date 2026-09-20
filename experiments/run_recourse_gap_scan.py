from __future__ import annotations

import argparse
import json
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
from uav_mec.algorithms.alns import DestroyConfig
from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import (
    CVXResourceSolver,
    solve_kkt_resource_problem,
)


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _candidate_summary(instance, solution) -> dict[str, Any]:
    proxy = evaluate_initial_proxy(instance, solution)
    return {
        "contacts": len(solution.contact_visits),
        "offloaded": sum(
            decision.mode is ExecutionMode.OFFLOAD
            for decision in solution.task_decisions.values()
        ),
        "proxy_violated_constraints": proxy.score.violated_constraints,
        "proxy_energy_j": proxy.score.total_energy_j,
        "proxy_max_normalized_violation": proxy.score.max_normalized_violation,
    }


def _resource_compare(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)

    t0 = perf_counter()
    kkt = solve_kkt_resource_problem(instance, solution, info)
    kkt_runtime = perf_counter() - t0

    t0 = perf_counter()
    cvx = CVXResourceSolver().solve(instance, solution, info)
    cvx_runtime = perf_counter() - t0

    gap = None
    if kkt.feasible and cvx.feasible:
        gap = (
            abs(kkt.energy_stage1_j - cvx.energy_stage1_j)
            / max(1.0, abs(cvx.energy_stage1_j))
        )

    return {
        "kkt_status": kkt.status,
        "kkt_feasible": kkt.feasible,
        "kkt_energy_stage1_j": kkt.energy_stage1_j,
        "kkt_iterations": kkt.diagnostics.get("iterations"),
        "kkt_converged": kkt.diagnostics.get("converged"),
        "kkt_initial_seed_feasible": kkt.diagnostics.get(
            "initial_seed_feasible"
        ),
        "kkt_runtime_s": kkt_runtime,
        "cvx_status": cvx.status,
        "cvx_stage1_status": cvx.diagnostics.get(
            "stage1_status", cvx.status
        ),
        "cvx_stage2_status": cvx.diagnostics.get("stage2_status"),
        "cvx_stage1_solver": cvx.diagnostics.get("stage1_solver"),
        "cvx_stage2_solver": cvx.diagnostics.get("stage2_solver"),
        "cvx_feasible": cvx.feasible,
        "cvx_energy_stage1_j": cvx.energy_stage1_j,
        "cvx_runtime_s": cvx_runtime,
        "reported_vs_cvx_relative_gap": gap,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare analytical-resource output against the CVXPY Stage-1 "
            "oracle on representative paper-scale discrete states."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30")
    parser.add_argument("--seeds", default="42,43,44")
    parser.add_argument(
        "--candidate",
        choices=("repaired", "alns", "both"),
        default="both",
    )
    parser.add_argument("--alns-iterations", type=int, default=20)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--mecs", type=int, default=None)
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    task_counts = _parse_int_list(args.tasks)
    seeds = _parse_int_list(args.seeds)
    rows: list[dict[str, Any]] = []

    print(
        "K    seed   source     p-vio   contacts   offload   "
        "kkt-status        cvx-s1       cvx-s2       "
        "kkt-E-J       cvx-E-J       gap-%    kkt-s    cvx-s"
    )
    print("-" * 162)

    for k in task_counts:
        for seed_idx, scenario_seed in enumerate(seeds):
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=k,
                num_uavs=args.uavs,
                num_mecs=args.mecs,
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
                evaluator = ProxyObjectiveEvaluator()
                alns_cfg = UavMecALNSConfig(
                    iterations=args.alns_iterations,
                    seed=cfg.algorithm_seed + seed_idx,
                    destroy=DestroyConfig(),
                )
                alns_result = run_uav_mec_alns(
                    instance,
                    initial_solution=repaired,
                    config=alns_cfg,
                    evaluator=evaluator,
                )
                candidates.append(("alns-best", alns_result.best_solution))

            for source, solution in candidates:
                summary = _candidate_summary(instance, solution)
                resource = _resource_compare(instance, solution)
                gap = resource["reported_vs_cvx_relative_gap"]
                gap_pct = None if gap is None else 100.0 * gap

                row = {
                    "K": k,
                    "scenario_seed": scenario_seed,
                    "source": source,
                    "summary": summary,
                    **resource,
                }
                rows.append(row)

                kkt_energy = (
                    f"{resource['kkt_energy_stage1_j']:.3f}"
                    if resource["kkt_feasible"]
                    else "-"
                )
                cvx_energy = (
                    f"{resource['cvx_energy_stage1_j']:.3f}"
                    if resource["cvx_feasible"]
                    else "-"
                )
                gap_text = f"{gap_pct:.3f}" if gap_pct is not None else "-"

                print(
                    f"{k:<4} "
                    f"{scenario_seed:<6} "
                    f"{source:<10} "
                    f"{summary['proxy_violated_constraints']:<7} "
                    f"{summary['contacts']:<10} "
                    f"{summary['offloaded']:<9} "
                    f"{resource['kkt_status']:<17} "
                    f"{str(resource['cvx_stage1_status']):<12} "
                    f"{str(resource['cvx_stage2_status']):<12} "
                    f"{kkt_energy:<13} "
                    f"{cvx_energy:<13} "
                    f"{gap_text:<8} "
                    f"{resource['kkt_runtime_s']:<8.2f} "
                    f"{resource['cvx_runtime_s']:.2f}"
                )

    gaps = [
        row["reported_vs_cvx_relative_gap"]
        for row in rows
        if row["reported_vs_cvx_relative_gap"] is not None
    ]
    fallback_count = sum(row["kkt_status"] == "feasible_seed" for row in rows)
    converged_count = sum(
        row["kkt_status"] in ("optimal_approx", "feasible_approx")
        for row in rows
    )

    trusted_gaps = [
        row["reported_vs_cvx_relative_gap"]
        for row in rows
        if (
            row["reported_vs_cvx_relative_gap"] is not None
            and row["cvx_stage1_status"] == "optimal"
        )
    ]
    approximate_oracle_rows = sum(
        row["cvx_stage1_status"] == "optimal_inaccurate"
        for row in rows
    )

    aggregate = {
        "rows": len(rows),
        "comparable_rows": len(gaps),
        "trusted_stage1_optimal_rows": len(trusted_gaps),
        "stage1_optimal_inaccurate_rows": approximate_oracle_rows,
        "feasible_seed_rows": fallback_count,
        "kkt_iterate_rows": converged_count,
        "mean_reported_vs_cvx_relative_gap": mean(gaps) if gaps else None,
        "max_reported_vs_cvx_relative_gap": max(gaps) if gaps else None,
        "mean_trusted_stage1_gap": (
            mean(trusted_gaps) if trusted_gaps else None
        ),
        "max_trusted_stage1_gap": (
            max(trusted_gaps) if trusted_gaps else None
        ),
    }

    if gaps:
        message = (
            "\nAggregate: "
            f"all-mean={100.0 * aggregate['mean_reported_vs_cvx_relative_gap']:.3f}%  "
            f"all-max={100.0 * aggregate['max_reported_vs_cvx_relative_gap']:.3f}%  "
            f"feasible-seed={fallback_count}/{len(rows)}"
        )
        if trusted_gaps:
            message += (
                f"  trusted-S1-mean={100.0 * aggregate['mean_trusted_stage1_gap']:.3f}%"
                f"  trusted-S1-max={100.0 * aggregate['max_trusted_stage1_gap']:.3f}%"
            )
        print(message)

    out = Path("outputs/results/recourse_gap_scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"aggregate": aggregate, "rows": rows},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
