from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from uav_mec.algorithms import build_greedy_initial_solution
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import solve_kkt_resource_problem


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _max_positive(values: dict[str, float] | None) -> float:
    if not values:
        return 0.0
    return max(0.0, *(float(v) for v in values.values()))


def _row(instance, solution, *, solve_resources: bool) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    task_counts = {
        uav_id: len(route.task_ids())
        for uav_id, route in solution.routes.items()
    }
    row: dict[str, Any] = {
        "K": len(instance.tasks),
        "M": len(instance.uavs),
        "E": len(instance.mecs),
        "total_distance_m": sum(info.route_distance_m.values()),
        "max_route_distance_m": max(
            info.route_distance_m.values(),
            default=0.0,
        ),
        "max_base_return_s": max(info.base_return_s.values(), default=0.0),
        "max_cycle_overflow_s": max(
            0.0,
            *(value - instance.cycle_s for value in info.base_return_s.values()),
        ),
        "min_tasks_per_uav": min(task_counts.values(), default=0),
        "max_tasks_per_uav": max(task_counts.values(), default=0),
        "task_counts": task_counts,
    }

    if not solve_resources:
        return row

    t0 = perf_counter()
    result = solve_kkt_resource_problem(instance, solution, info)
    row["kkt_runtime_s"] = perf_counter() - t0
    row["kkt_status"] = result.status
    row["kkt_feasible"] = result.feasible
    row["energy_stage1_j"] = result.energy_stage1_j
    row["kkt_iterations"] = result.diagnostics.get("iterations")
    row["termination_reason"] = result.diagnostics.get("termination_reason")

    if result.feasible:
        row["avg_delay_s"] = result.diagnostics.get("avg_delay_final_s")
        row["max_deadline_violation_s"] = _max_positive(
            result.diagnostics.get("deadline_violation_s")
        )
        row["max_cycle_violation_s"] = _max_positive(
            result.diagnostics.get("cycle_violation_s")
        )
    else:
        row["precheck_reasons"] = result.diagnostics.get("precheck_reasons")
        row["last_deadline_violation_s"] = result.diagnostics.get(
            "last_deadline_violation_s"
        )
    return row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sanity-check the task-routing greedy initial solution."
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30,50")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--mecs", type=int, default=None)
    parser.add_argument(
        "--solve-resources",
        action="store_true",
        help="also run the analytical KKT resource solver on the all-local seed",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    seed = cfg.scenario_seed if args.seed is None else args.seed
    rows = []

    print(
        "K    M    E    total-km   max-return-s   cycle-over-s   "
        "tasks[min,max]   resource-status"
    )
    print("-" * 102)

    for k in _parse_int_list(args.tasks):
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=k,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=seed,
        )
        t0 = perf_counter()
        solution = build_greedy_initial_solution(instance)
        build_time = perf_counter() - t0
        row = _row(
            instance,
            solution,
            solve_resources=args.solve_resources,
        )
        row["build_runtime_s"] = build_time
        rows.append(row)

        status = row.get("kkt_status", "not-run")
        print(
            f"{row['K']:<4} {row['M']:<4} {row['E']:<4} "
            f"{row['total_distance_m'] / 1000.0:<10.3f} "
            f"{row['max_base_return_s']:<14.2f} "
            f"{row['max_cycle_overflow_s']:<14.2f} "
            f"[{row['min_tasks_per_uav']},{row['max_tasks_per_uav']}]"
            f"{'':<7} {status}"
        )

    out = Path("outputs/results/initial_solution_sanity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
