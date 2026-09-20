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
from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)
from uav_mec.optimization.resource import CVXResourceSolver


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _energy_breakdown(
    instance,
    solution,
    info,
    *,
    local_cpu_ghz: dict[str, float],
    upload_time_s: dict[str, float],
) -> dict[str, float]:
    flight = sum(info.fixed_flight_energy_j.values())
    collection = sum(info.fixed_collection_energy_j.values())

    local_compute = 0.0
    for uav_id, order in info.local_order.items():
        uav = instance.uavs[uav_id]
        kappa_scaled = uav.kappa * 1e27
        for task_id in order:
            f = local_cpu_ghz[task_id]
            local_compute += (
                kappa_scaled
                * instance.tasks[task_id].workload_gcycles
                * f
                * f
            )

    offload_hover = 0.0
    transmit = 0.0
    for uav_id, visits in info.contact_order.items():
        uav = instance.uavs[uav_id]
        for visit_id in visits:
            tau = upload_time_s[visit_id]
            offload_hover += uav.hover_power_w * tau
            transmit += uav.tx_power_w * tau

    total = flight + collection + local_compute + offload_hover + transmit
    fixed_route = flight + collection
    variable = local_compute + offload_hover + transmit

    return {
        "flight_j": flight,
        "collection_j": collection,
        "fixed_route_j": fixed_route,
        "local_compute_j": local_compute,
        "offload_hover_j": offload_hover,
        "transmit_j": transmit,
        "variable_resource_j": variable,
        "total_j": total,
        "fixed_route_fraction": fixed_route / max(1.0, total),
        "variable_fraction": variable / max(1.0, total),
    }


def _proxy_breakdown(instance, solution, info):
    proxy = evaluate_initial_proxy(instance, solution)
    local_cpu = {
        task_id: instance.uavs[uav_id].local_cpu_ghz
        for uav_id, order in info.local_order.items()
        for task_id in order
    }
    breakdown = _energy_breakdown(
        instance,
        solution,
        info,
        local_cpu_ghz=local_cpu,
        upload_time_s=proxy.reduced.upload_time_s,
    )
    return proxy, breakdown


def _cvx_breakdown(instance, solution, info, cvx):
    local_cpu = {
        task_id: value
        for task_id, value in cvx.stage1_values["local_cpu_ghz"].items()
    }
    upload_time = {
        visit_id: value
        for visit_id, value in cvx.stage1_values["tau_s"].items()
    }
    return _energy_breakdown(
        instance,
        solution,
        info,
        local_cpu_ghz=local_cpu,
        upload_time_s=upload_time,
    )


def _resource_utilization(instance, info, cvx) -> dict[str, Any]:
    bandwidth_values = cvx.stage1_values["bandwidth_mhz"]
    mec_cpu_values = cvx.stage1_values["mec_cpu_ghz"]

    bw_util: dict[str, float] = {}
    cpu_util: dict[str, float] = {}
    pairs_per_mec: dict[str, int] = {}
    for mec_id, mec in instance.mecs.items():
        pairs = [
            pair
            for pair in info.active_uav_mec_pairs
            if pair[1] == mec_id
        ]
        if not pairs:
            continue
        pairs_per_mec[mec_id] = len(pairs)
        used_b = sum(
            bandwidth_values.get(str(pair), 0.0)
            for pair in pairs
        )
        used_f = sum(
            mec_cpu_values.get(str(pair), 0.0)
            for pair in pairs
        )
        bw_util[mec_id] = used_b / max(1e-12, mec.bandwidth_mhz)
        cpu_util[mec_id] = used_f / max(1e-12, mec.cpu_ghz)

    return {
        "bandwidth_utilization": bw_util,
        "mec_cpu_utilization": cpu_util,
        "pairs_per_mec": pairs_per_mec,
        "active_uav_mec_pairs": len(info.active_uav_mec_pairs),
        "shared_mec_count": sum(
            count >= 2 for count in pairs_per_mec.values()
        ),
        "max_pairs_per_mec": max(pairs_per_mec.values(), default=0),
        "max_bandwidth_utilization": max(bw_util.values(), default=0.0),
        "max_mec_cpu_utilization": max(cpu_util.values(), default=0.0),
    }


def _qos_utilization(instance, cvx) -> dict[str, float]:
    completion = cvx.stage1_values["task_completion_s"]
    deadline_ratios = [
        (
            completion[task_id] - task.release_s
        ) / max(1.0, task.deadline_s)
        for task_id, task in instance.tasks.items()
    ]

    avg_delay = cvx.diagnostics["avg_delay_stage1_s"]
    return_times = cvx.diagnostics["return_times_stage1_s"]
    battery_violation = cvx.diagnostics["stage1_battery_violation_j"]

    cycle_ratios = [
        return_times[uav_id] / max(1.0, instance.cycle_s)
        for uav_id in instance.uavs
    ]
    battery_ratios = [
        (
            instance.uavs[uav_id].energy_budget_j
            + battery_violation[uav_id]
        ) / max(1.0, instance.uavs[uav_id].energy_budget_j)
        for uav_id in instance.uavs
    ]

    return {
        "max_deadline_utilization": max(deadline_ratios, default=0.0),
        "mean_deadline_utilization": mean(deadline_ratios)
        if deadline_ratios
        else 0.0,
        "avg_delay_utilization": avg_delay
        / max(1.0, instance.avg_delay_budget_s),
        "max_cycle_utilization": max(cycle_ratios, default=0.0),
        "max_battery_utilization": max(battery_ratios, default=0.0),
    }


def _dual_summary(instance, cvx) -> dict[str, Any]:
    duals = cvx.stage1_duals
    deadline_duals = [
        duals.get(f"deadline::{task_id}", 0.0)
        for task_id in instance.tasks
    ]
    bw_duals = [
        duals.get(f"bandwidth_cap::{mec_id}", 0.0)
        for mec_id in instance.mecs
    ]
    cpu_duals = [
        duals.get(f"mec_cpu_cap::{mec_id}", 0.0)
        for mec_id in instance.mecs
    ]
    tol = 1e-7
    return {
        "active_deadline_duals": sum(value > tol for value in deadline_duals),
        "max_deadline_dual": max(deadline_duals, default=0.0),
        "avg_delay_dual": duals.get("avg_delay", 0.0),
        "active_bandwidth_duals": sum(value > tol for value in bw_duals),
        "max_bandwidth_dual": max(bw_duals, default=0.0),
        "active_mec_cpu_duals": sum(value > tol for value in cpu_duals),
        "max_mec_cpu_dual": max(cpu_duals, default=0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scan whether route, offloading and resource terms are all "
            "numerically meaningful in the paper-scale configuration."
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
        "K    seed   source     offload   contacts   fixed-%   "
        "proxy-var-J   cvx-var-J   var-gain-%   "
        "deadline-u   avg-u   cycle-u   bw-u   cpu-u   pairs   shared   bw-dual   cpu-dual"
    )
    print("-" * 190)

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
                info = build_event_info(instance, solution)
                proxy, proxy_energy = _proxy_breakdown(
                    instance,
                    solution,
                    info,
                )
                cvx = CVXResourceSolver(run_stage2=False).solve(
                    instance,
                    solution,
                    info,
                )
                if not cvx.feasible:
                    rows.append(
                        {
                            "K": k,
                            "scenario_seed": scenario_seed,
                            "source": source,
                            "cvx_status": cvx.status,
                            "proxy_violated_constraints": (
                                proxy.score.violated_constraints
                            ),
                        }
                    )
                    continue

                cvx_energy = _cvx_breakdown(
                    instance,
                    solution,
                    info,
                    cvx,
                )
                resources = _resource_utilization(
                    instance,
                    info,
                    cvx,
                )
                qos = _qos_utilization(instance, cvx)
                duals = _dual_summary(instance, cvx)

                variable_gain = (
                    proxy_energy["variable_resource_j"]
                    - cvx_energy["variable_resource_j"]
                )
                variable_gain_pct = (
                    100.0
                    * variable_gain
                    / max(1.0, cvx_energy["variable_resource_j"])
                )

                row = {
                    "K": k,
                    "scenario_seed": scenario_seed,
                    "source": source,
                    "offloaded": sum(
                        decision.mode is ExecutionMode.OFFLOAD
                        for decision in solution.task_decisions.values()
                    ),
                    "contacts": len(solution.contact_visits),
                    "proxy_violated_constraints": (
                        proxy.score.violated_constraints
                    ),
                    "cvx_stage1_status": cvx.diagnostics.get(
                        "stage1_status", cvx.status
                    ),
                    "cvx_stage2_status": cvx.diagnostics.get(
                        "stage2_status"
                    ),
                    "proxy_energy": proxy_energy,
                    "cvx_energy": cvx_energy,
                    "variable_resource_gain_j": variable_gain,
                    "variable_resource_gain_pct": variable_gain_pct,
                    "qos": qos,
                    "resources": resources,
                    "duals": duals,
                }
                rows.append(row)

                print(
                    f"{k:<4} "
                    f"{scenario_seed:<6} "
                    f"{source:<10} "
                    f"{row['offloaded']:<9} "
                    f"{row['contacts']:<10} "
                    f"{100.0 * cvx_energy['fixed_route_fraction']:<9.2f} "
                    f"{proxy_energy['variable_resource_j']:<13.2f} "
                    f"{cvx_energy['variable_resource_j']:<11.2f} "
                    f"{variable_gain_pct:<12.2f} "
                    f"{qos['max_deadline_utilization']:<12.3f} "
                    f"{qos['avg_delay_utilization']:<7.3f} "
                    f"{qos['max_cycle_utilization']:<9.3f} "
                    f"{resources['max_bandwidth_utilization']:<6.3f} "
                    f"{resources['max_mec_cpu_utilization']:<7.3f} "
                    f"{resources['active_uav_mec_pairs']:<7} "
                    f"{resources['shared_mec_count']:<8} "
                    f"{duals['active_bandwidth_duals']:<9} "
                    f"{duals['active_mec_cpu_duals']}"
                )

    valid = [row for row in rows if "cvx_energy" in row]
    aggregate = {}
    if valid:
        aggregate = {
            "rows": len(valid),
            "mean_fixed_route_fraction": mean(
                row["cvx_energy"]["fixed_route_fraction"]
                for row in valid
            ),
            "mean_variable_resource_gain_pct": mean(
                row["variable_resource_gain_pct"]
                for row in valid
            ),
            "max_variable_resource_gain_pct": max(
                row["variable_resource_gain_pct"]
                for row in valid
            ),
            "mean_max_deadline_utilization": mean(
                row["qos"]["max_deadline_utilization"]
                for row in valid
            ),
            "mean_avg_delay_utilization": mean(
                row["qos"]["avg_delay_utilization"]
                for row in valid
            ),
            "mean_max_cycle_utilization": mean(
                row["qos"]["max_cycle_utilization"]
                for row in valid
            ),
            "mean_max_bandwidth_utilization": mean(
                row["resources"]["max_bandwidth_utilization"]
                for row in valid
            ),
            "mean_max_mec_cpu_utilization": mean(
                row["resources"]["max_mec_cpu_utilization"]
                for row in valid
            ),
            "mean_active_uav_mec_pairs": mean(
                row["resources"]["active_uav_mec_pairs"]
                for row in valid
            ),
            "states_with_shared_mec": sum(
                row["resources"]["shared_mec_count"] > 0
                for row in valid
            ),
            "max_pairs_per_mec": max(
                row["resources"]["max_pairs_per_mec"]
                for row in valid
            ),
            "states_with_active_bandwidth_dual": sum(
                row["duals"]["active_bandwidth_duals"] > 0
                for row in valid
            ),
            "states_with_active_mec_cpu_dual": sum(
                row["duals"]["active_mec_cpu_duals"] > 0
                for row in valid
            ),
        }
        print(
            "\nAggregate: "
            f"fixed-route={100.0 * aggregate['mean_fixed_route_fraction']:.2f}%  "
            f"mean-var-gain={aggregate['mean_variable_resource_gain_pct']:.2f}%  "
            f"max-var-gain={aggregate['max_variable_resource_gain_pct']:.2f}%  "
            f"deadline-u={aggregate['mean_max_deadline_utilization']:.3f}  "
            f"avg-u={aggregate['mean_avg_delay_utilization']:.3f}  "
            f"cycle-u={aggregate['mean_max_cycle_utilization']:.3f}  "
            f"bw-u={aggregate['mean_max_bandwidth_utilization']:.3f}  "
            f"cpu-u={aggregate['mean_max_mec_cpu_utilization']:.3f}  "
            f"pairs={aggregate['mean_active_uav_mec_pairs']:.2f}  "
            f"shared={aggregate['states_with_shared_mec']}/{len(valid)}  "
            f"max-pairs/mec={aggregate['max_pairs_per_mec']}  "
            f"bw-dual={aggregate['states_with_active_bandwidth_dual']}/{len(valid)}  "
            f"cpu-dual={aggregate['states_with_active_mec_cpu_dual']}/{len(valid)}"
        )

    out = Path("outputs/results/nondegeneracy_scan.json")
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
