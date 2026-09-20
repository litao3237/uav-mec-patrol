from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    evaluate_initial_proxy,
)
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


def _solution_stats(instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)
    proxy = evaluate_initial_proxy(instance, solution)
    return {
        "contacts": len(solution.contact_visits),
        "offloaded": sum(
            decision.mode is ExecutionMode.OFFLOAD
            for decision in solution.task_decisions.values()
        ),
        "total_distance_m": sum(info.route_distance_m.values()),
        "max_return_base_s": max(info.base_return_s.values(), default=0.0),
        "proxy_violated_constraints": proxy.score.violated_constraints,
        "proxy_max_normalized_violation": proxy.score.max_normalized_violation,
        "proxy_sum_normalized_violation": proxy.score.sum_normalized_violation,
        "proxy_energy_j": proxy.score.total_energy_j,
        "proxy_avg_delay_s": proxy.reduced.avg_delay_s,
        "proxy_max_deadline_violation_s": max(
            0.0,
            *proxy.reduced.deadline_violation_s.values(),
        ),
        "proxy_max_cycle_violation_s": max(
            0.0,
            *proxy.reduced.cycle_violation_s.values(),
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sanity-check greedy Local-to-MEC contact/offloading repair."
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30,50")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--mecs", type=int, default=None)
    parser.add_argument(
        "--cvx-check",
        action="store_true",
        help="also solve the repaired P1-R with the CVXPY correctness oracle",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    seed = cfg.scenario_seed if args.seed is None else args.seed
    rows: list[dict[str, Any]] = []

    print(
        "K    before-vio   after-vio    contacts   offload   "
        "after-max-vio   kkt-status              kkt-iters   "
        "cvx-status   kkt-E-J       cvx-E-J       gap-%"
    )
    print("-" * 166)

    for k in _parse_int_list(args.tasks):
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=k,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=seed,
        )

        base = build_greedy_initial_solution(instance)
        before = _solution_stats(instance, base)

        t0 = perf_counter()
        repaired = build_mec_assisted_initial_solution(
            instance,
            base_solution=base,
        )
        repair_runtime = perf_counter() - t0
        after = _solution_stats(instance, repaired)

        info = build_event_info(instance, repaired)
        t0 = perf_counter()
        kkt = solve_kkt_resource_problem(instance, repaired, info)
        kkt_runtime = perf_counter() - t0

        row = {
            "K": k,
            "before": before,
            "after": after,
            "repair_runtime_s": repair_runtime,
            "kkt_status": kkt.status,
            "kkt_feasible": kkt.feasible,
            "kkt_runtime_s": kkt_runtime,
            "kkt_iterations": kkt.diagnostics.get("iterations"),
            "kkt_termination_reason": kkt.diagnostics.get(
                "termination_reason"
            ),
            "kkt_converged": kkt.diagnostics.get("converged"),
            "kkt_initial_seed_feasible": kkt.diagnostics.get(
                "initial_seed_feasible"
            ),
            "metadata": repaired.metadata,
        }

        cvx_status = "not-run"
        cvx_energy = None
        gap_pct = None
        if args.cvx_check:
            t0 = perf_counter()
            cvx = CVXResourceSolver(run_stage2=False).solve(instance, repaired, info)
            row["cvx_runtime_s"] = perf_counter() - t0
            row["cvx_status"] = cvx.status
            row["cvx_feasible"] = cvx.feasible
            row["cvx_energy_stage1_j"] = cvx.energy_stage1_j
            cvx_status = cvx.status
            cvx_energy = cvx.energy_stage1_j
            if cvx.feasible and kkt.feasible:
                relative_gap = (
                    abs(kkt.energy_stage1_j - cvx.energy_stage1_j)
                    / max(1.0, abs(cvx.energy_stage1_j))
                )
                row["kkt_cvx_relative_gap"] = relative_gap
                gap_pct = 100.0 * relative_gap
        if kkt.feasible:
            row.update(
                {
                    "energy_stage1_j": kkt.energy_stage1_j,
                    "avg_delay_s": kkt.diagnostics.get(
                        "avg_delay_final_s"
                    ),
                    "deadline_violation_s": kkt.diagnostics.get(
                        "deadline_violation_s"
                    ),
                    "cycle_violation_s": kkt.diagnostics.get(
                        "cycle_violation_s"
                    ),
                }
            )
        else:
            row["kkt_diagnostics"] = kkt.diagnostics
        rows.append(row)

        kkt_energy_text = (
            f"{kkt.energy_stage1_j:.3f}" if kkt.feasible else "-"
        )
        cvx_energy_text = (
            f"{cvx_energy:.3f}" if cvx_energy is not None else "-"
        )
        gap_text = f"{gap_pct:.3f}" if gap_pct is not None else "-"

        print(
            f"{k:<4} "
            f"{before['proxy_violated_constraints']:<12} "
            f"{after['proxy_violated_constraints']:<12} "
            f"{after['contacts']:<10} "
            f"{after['offloaded']:<9} "
            f"{after['proxy_max_normalized_violation']:<15.3e} "
            f"{kkt.status:<23} "
            f"{str(kkt.diagnostics.get('iterations')):<11} "
            f"{cvx_status:<12} "
            f"{kkt_energy_text:<13} "
            f"{cvx_energy_text:<13} "
            f"{gap_text}"
        )

    out = Path("outputs/results/mec_repair_sanity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
