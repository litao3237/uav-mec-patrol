from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
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
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import (
    CVXResourceSolver,
    fast_feasibility_precheck,
)


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _reason_counts(reasons: tuple[str, ...]) -> dict[str, int]:
    counts = {"task_deadline": 0, "avg_delay": 0, "cycle": 0, "other": 0}
    for reason in reasons:
        if reason.startswith("task "):
            counts["task_deadline"] += 1
        elif reason.startswith("average delay:"):
            counts["avg_delay"] += 1
        elif reason.startswith("UAV "):
            counts["cycle"] += 1
        else:
            counts["other"] += 1
    return counts


def _state_check(instance, solution, *, cvx_check: bool) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    proxy = evaluate_initial_proxy(instance, solution)
    precheck = fast_feasibility_precheck(instance, solution, info)
    reason_counts = _reason_counts(precheck.reasons)

    cvx_status = "not-run"
    cvx_feasible = None
    cvx_energy = None
    if cvx_check and precheck.feasible:
        cvx = CVXResourceSolver(run_stage2=False).solve(
            instance,
            solution,
            info,
        )
        cvx_status = cvx.diagnostics.get("stage1_status", cvx.status)
        cvx_feasible = cvx.feasible
        cvx_energy = cvx.energy_stage1_j if cvx.feasible else None

    return {
        "proxy_violations": proxy.score.violated_constraints,
        "proxy_max_violation": proxy.score.max_normalized_violation,
        "proxy_sum_violation": proxy.score.sum_normalized_violation,
        "proxy_energy_j": proxy.score.total_energy_j,
        "precheck_feasible": precheck.feasible,
        "precheck_reason_count": len(precheck.reasons),
        "precheck_reason_counts": reason_counts,
        "precheck_reasons": list(precheck.reasons),
        "cvx_status": cvx_status,
        "cvx_feasible": cvx_feasible,
        "cvx_energy_stage1_j": cvx_energy,
        "contacts": len(solution.contact_visits),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose whether high-load infeasibility is mainly a search-budget "
            "issue or a neighborhood/operator limitation."
        )
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", type=int, default=80)
    parser.add_argument("--mecs", default="2,3")
    parser.add_argument("--scenario-seeds", default="43")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--iterations", default="20,100,300")
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument(
        "--skip-cvx",
        action="store_true",
        help="skip final Stage-1 CVX confirmation for precheck-feasible states",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    mec_counts = _parse_int_list(args.mecs)
    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)
    iteration_budgets = _parse_int_list(args.iterations)

    rows: list[dict[str, Any]] = []

    print(
        "E    scen   alg    iters   init-pv   best-pv   precheck   "
        "pre-task   pre-avg   pre-cycle   cvx-s1       contacts"
    )
    print("-" * 116)

    for e in mec_counts:
        for scenario_seed in scenario_seeds:
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=args.tasks,
                num_uavs=args.uavs,
                num_mecs=e,
                scenario_seed=scenario_seed,
            )
            route_seed = build_greedy_initial_solution(instance)
            repaired = build_mec_assisted_initial_solution(
                instance,
                base_solution=route_seed,
            )
            initial = _state_check(
                instance,
                repaired,
                cvx_check=False,
            )

            for iterations in iteration_budgets:
                for algorithm_seed in algorithm_seeds:
                    result = run_uav_mec_alns(
                        instance,
                        initial_solution=repaired,
                        config=UavMecALNSConfig(
                            iterations=iterations,
                            seed=algorithm_seed,
                            destroy=DestroyConfig(),
                        ),
                        evaluator=ProxyObjectiveEvaluator(),
                    )
                    best = _state_check(
                        instance,
                        result.best_solution,
                        cvx_check=not args.skip_cvx,
                    )
                    counts = best["precheck_reason_counts"]

                    row = {
                        "K": args.tasks,
                        "E": e,
                        "scenario_seed": scenario_seed,
                        "algorithm_seed": algorithm_seed,
                        "iterations": iterations,
                        "initial": initial,
                        "best": best,
                        "initial_objective": result.initial_objective,
                        "best_objective": result.best_objective,
                    }
                    rows.append(row)

                    print(
                        f"{e:<4} "
                        f"{scenario_seed:<6} "
                        f"{algorithm_seed:<6} "
                        f"{iterations:<7} "
                        f"{initial['proxy_violations']:<9} "
                        f"{best['proxy_violations']:<9} "
                        f"{str(best['precheck_feasible']):<10} "
                        f"{counts['task_deadline']:<10} "
                        f"{counts['avg_delay']:<9} "
                        f"{counts['cycle']:<11} "
                        f"{str(best['cvx_status']):<12} "
                        f"{best['contacts']}"
                    )

    summary: list[dict[str, Any]] = []
    for e in mec_counts:
        for iterations in iteration_budgets:
            subset = [
                row
                for row in rows
                if row["E"] == e and row["iterations"] == iterations
            ]
            if not subset:
                continue

            proxy_feasible = sum(
                row["best"]["proxy_violations"] == 0 for row in subset
            )
            precheck_feasible = sum(
                row["best"]["precheck_feasible"] for row in subset
            )
            cvx_checked = [
                row
                for row in subset
                if row["best"]["cvx_feasible"] is not None
            ]
            cvx_feasible = sum(
                bool(row["best"]["cvx_feasible"])
                for row in cvx_checked
            )
            group = {
                "E": e,
                "iterations": iterations,
                "runs": len(subset),
                "proxy_feasible_rate": proxy_feasible / len(subset),
                "precheck_feasible_rate": precheck_feasible / len(subset),
                "cvx_checked_runs": len(cvx_checked),
                "cvx_feasible_rate": (
                    cvx_feasible / len(cvx_checked) if cvx_checked else None
                ),
                "mean_proxy_violations": mean(
                    row["best"]["proxy_violations"] for row in subset
                ),
                "mean_precheck_task_reasons": mean(
                    row["best"]["precheck_reason_counts"]["task_deadline"]
                    for row in subset
                ),
                "mean_precheck_cycle_reasons": mean(
                    row["best"]["precheck_reason_counts"]["cycle"]
                    for row in subset
                ),
            }
            summary.append(group)

    print("\nSummary by (E, iterations)")
    print(
        "E    iters   runs   proxy-feas   precheck-feas   "
        "cvx-feas   mean-pv   mean-pre-task   mean-pre-cycle"
    )
    print("-" * 108)
    for group in summary:
        cvx_text = (
            f"{group['cvx_feasible_rate']:.3f}"
            if group["cvx_feasible_rate"] is not None
            else "-"
        )
        print(
            f"{group['E']:<4} "
            f"{group['iterations']:<7} "
            f"{group['runs']:<6} "
            f"{group['proxy_feasible_rate']:<12.3f} "
            f"{group['precheck_feasible_rate']:<15.3f} "
            f"{cvx_text:<10} "
            f"{group['mean_proxy_violations']:<9.2f} "
            f"{group['mean_precheck_task_reasons']:<15.2f} "
            f"{group['mean_precheck_cycle_reasons']:.2f}"
        )

    out = Path("outputs/results/high_load_feasibility_scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"summary": summary, "rows": rows},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
