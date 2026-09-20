from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    KKTObjectiveEvaluator,
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
from uav_mec.optimization.resource import solve_kkt_resource_problem


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _solution_summary(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    proxy = evaluate_initial_proxy(instance, solution)
    return {
        "contacts": len(solution.contact_visits),
        "total_distance_m": sum(info.route_distance_m.values()),
        "max_return_base_s": max(info.base_return_s.values(), default=0.0),
        "proxy_violated_constraints": proxy.score.violated_constraints,
        "proxy_max_normalized_violation": proxy.score.max_normalized_violation,
        "proxy_sum_normalized_violation": proxy.score.sum_normalized_violation,
        "proxy_energy_j": proxy.score.total_energy_j,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test the external ALNS framework on paper-scale instances."
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--mecs", type=int, default=None)
    parser.add_argument(
        "--objective",
        choices=("proxy", "kkt"),
        default="proxy",
        help="proxy is faster for structural validation; kkt uses exact P1-R recourse",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    seed = cfg.scenario_seed if args.seed is None else args.seed

    rows: list[dict[str, Any]] = []
    print(
        "K    objective   init-obj        best-obj        improve-%   "
        "contacts   best-kkt-status       eval-calls  cache-hits  runtime-s"
    )
    print("-" * 125)

    for k in _parse_int_list(args.tasks):
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=k,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=seed,
        )

        route_seed = build_greedy_initial_solution(instance)
        initial = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )
        initial_summary = _solution_summary(instance, initial)

        evaluator = (
            KKTObjectiveEvaluator()
            if args.objective == "kkt"
            else ProxyObjectiveEvaluator()
        )
        config = UavMecALNSConfig(
            iterations=args.iterations,
            seed=cfg.algorithm_seed,
            destroy=DestroyConfig(),
        )

        t0 = perf_counter()
        result = run_uav_mec_alns(
            instance,
            initial_solution=initial,
            config=config,
            evaluator=evaluator,
        )
        runtime = perf_counter() - t0

        best_summary = _solution_summary(
            instance,
            result.best_solution,
        )

        best_info = build_event_info(
            instance,
            result.best_solution,
        )
        best_kkt = solve_kkt_resource_problem(
            instance,
            result.best_solution,
            best_info,
        )

        improvement = (
            100.0
            * (result.initial_objective - result.best_objective)
            / max(1.0, abs(result.initial_objective))
        )
        stats = getattr(evaluator, "stats", None)
        calls = getattr(stats, "calls", None)
        hits = getattr(stats, "cache_hits", None)

        row = {
            "K": k,
            "objective_mode": args.objective,
            "iterations": args.iterations,
            "initial_objective": result.initial_objective,
            "best_objective": result.best_objective,
            "improvement_pct": improvement,
            "initial": initial_summary,
            "best": best_summary,
            "best_kkt_status": best_kkt.status,
            "best_kkt_feasible": best_kkt.feasible,
            "best_kkt_energy_j": best_kkt.energy_stage1_j,
            "best_kkt_iterations": best_kkt.diagnostics.get("iterations"),
            "evaluator_calls": calls,
            "evaluator_cache_hits": hits,
            "runtime_s": runtime,
        }
        rows.append(row)

        print(
            f"{k:<4} "
            f"{args.objective:<11} "
            f"{result.initial_objective:<15.3f} "
            f"{result.best_objective:<15.3f} "
            f"{improvement:<11.3f} "
            f"{best_summary['contacts']:<10} "
            f"{best_kkt.status:<21} "
            f"{str(calls):<11} "
            f"{str(hits):<11} "
            f"{runtime:.2f}"
        )

    out = Path("outputs/results/alns_sanity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
