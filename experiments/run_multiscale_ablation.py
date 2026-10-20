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
from dataclasses import asdict, replace
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
from experiment_common import provenance, stage_snapshot
from uav_mec.analysis.constraint_audit import AuditTolerance
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified


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
    """原子写入完整快照，非有限能耗显式转为缺失值。"""
    write_json(path, payload)


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
        # 失败会令各场景有效种子数不同，先场景内平均，不能用运行均值代替场景等权。
        per_scenario = [
            {"tasks": k, "scenario_seed": s,
             "pairs": len(group), "mean_full_advantage_pct": mean(group)}
            for k, s in sorted({(p["tasks"], p["scenario_seed"]) for p in pairs})
            if (group := [p["full_advantage_pct"] for p in pairs
                          if p["tasks"] == k and p["scenario_seed"] == s and p["comparable"]])
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
                    mean(s["mean_full_advantage_pct"] for s in per_scenario) if per_scenario else None
                ),
                "run_equal_mean_full_advantage_pct": mean(values) if values else None,
                "per_scenario": per_scenario,
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



TASK_LEVEL_ABLATION_METRICS = (
    "success_rate", "mean_delay_all", "mean_delay_success", "p95_delay_all",
    "total_energy", "energy_per_successful_task", "mec_cpu_utilization",
    "runtime", "strict_all_tasks_success", "deadline_violation_rate",
)


def aggregate_task_qos_profiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Include every physical run, averaging seeds within scenario first."""
    out = []
    for tasks in sorted({int(r["tasks"]) for r in rows}):
        for profile in PROFILES:
            selected = [r for r in rows if int(r["tasks"]) == tasks and r["profile"] == profile]
            if not selected:
                continue
            for metric in TASK_LEVEL_ABLATION_METRICS:
                per_scenario = []
                observed = 0
                for scenario in sorted({r["scenario_seed"] for r in selected}):
                    vals = [float(r["metrics"][metric]) for r in selected
                            if r["scenario_seed"] == scenario and
                            r.get("metrics") and r["metrics"][metric] is not None]
                    observed += len(vals)
                    if vals:
                        per_scenario.append({"scenario_seed": scenario, "mean": mean(vals)})
                out.append({
                    "tasks": tasks, "profile": profile, "metric": metric,
                    "planned_runs": len(selected),
                    "physical_feasible_runs": sum(r["metrics"]["physical_feasible"] for r in selected),
                    "observed_runs": observed, "scenarios": len(per_scenario),
                    "scenario_equal_mean": (
                        mean(x["mean"] for x in per_scenario) if per_scenario else None),
                    "per_scenario": per_scenario,
                })
    return out


def paired_task_qos_profiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Directly paired, task success prioritized; never discard late runs."""
    groups = {}
    for r in rows:
        groups.setdefault((r["tasks"], r["scenario_seed"], r["algorithm_seed"]), {})[
            r["profile"]] = r
    result = []
    for key, by_profile in sorted(groups.items()):
        if "full" not in by_profile:
            raise ValueError(f"Missing paired full profile: {key}")
        full = by_profile["full"]["metrics"]
        for profile in PROFILES:
            if profile == "full":
                continue
            if profile not in by_profile:
                raise ValueError(f"Missing paired ablation {profile}: {key}")
            ablated = by_profile[profile]["metrics"]
            if not full["physical_feasible"] or not ablated["physical_feasible"]:
                raise ValueError(f"Uncertified paired physical run: {key}")
            result.append({
                "tasks": key[0], "scenario_seed": key[1], "algorithm_seed": key[2],
                "profile": profile,
                "full_minus_ablation_success_rate": (
                    full["success_rate"] - ablated["success_rate"]),
                "full_minus_ablation_mean_delay_all_s": (
                    full["mean_delay_all"] - ablated["mean_delay_all"]),
                "full_minus_ablation_energy_j": (
                    full["total_energy"] - ablated["total_energy"]),
                "full_minus_ablation_energy_per_successful_task": (
                    full["energy_per_successful_task"] - ablated["energy_per_successful_task"]
                    if full["energy_per_successful_task"] is not None and
                       ablated["energy_per_successful_task"] is not None else None),
                "full_strict_success": full["strict_all_tasks_success"],
                "ablation_strict_success": ablated["strict_all_tasks_success"],
            })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument('--qos-mode',choices=['strict','task-level'],default='strict')
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
    if args.qos_mode == 'task-level':
        from run_seven_methods import finalize
    task_counts = parse_ints(args.tasks)
    scenario_seeds = parse_ints(args.scenario_seeds)
    algorithm_seeds = parse_ints(args.algorithm_seeds)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有实验：{output}")

    rows: list[dict[str, Any]] = []
    protocol = {
        "tasks": task_counts,
        "qos_mode": args.qos_mode,
        "protocol_version": "v26_task_qos" if args.qos_mode == "task-level" else "v25_strict",
        "scenario_seeds": scenario_seeds,
        "algorithm_seeds": algorithm_seeds,
        "profiles": list(PROFILES),
        "iterations": args.iterations,
        "elite_rounds": args.elite_rounds,
        "mecs": args.mecs,
        "uavs": args.uavs,
        "shared_exploration": True,
        "strict_definition": "optimal plus saved/reconstructed residuals and energy consistency",
        "audit_tolerance": asdict(AuditTolerance()),
        "provenance": provenance(),
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
            instance = replace(instance, qos_hard=(args.qos_mode == 'strict'))
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
                    if stage1_is_qualified(base_cvx)
                    else None
                )

                for profile in PROFILES:
                    oracle = Stage1CVXObjectiveOracle()
                    # 各消融分支使用相同基线快照，不能重新求解成另一份连续解。
                    oracle.prime(instance, exploration.best_solution, base_cvx)
                    final_solution = deepcopy(exploration.best_solution)
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
                        final_solution = final_state.solution
                    else:
                        final_cvx = base_cvx
                        stats["skipped"] = (
                            "exploration_stage1_unqualified"
                            if base_cvx.feasible
                            else "exploration_stage1_infeasible"
                        )
                    elite_runtime_s = perf_counter() - started

                    final_status = stage1_status(final_cvx)
                    final_energy = (
                        float(final_cvx.energy_stage1_j)
                        if stage1_is_qualified(final_cvx)
                        else None
                    )
                    strict_pair = bool(
                        base_energy is not None
                        and final_energy is not None
                    )
                    gain_vs_base_pct = (
                        100.0 * (base_energy - final_energy)
                        / max(1.0, abs(base_energy))
                        if strict_pair and instance.qos_hard else None
                    )
                    soft_metrics = None
                    soft_admission = None
                    if not instance.qos_hard:
                        recovered = finalize(instance, final_solution, method="ESI-"+profile,
                                             seed=algorithm_seed, initialization_s=0.0,
                                             search_s=elite_runtime_s,
                                             diagnostics={"profile": profile})
                        soft_metrics, soft_admission = recovered["metrics"], recovered["admission"]
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
                            "strict_pair": strict_pair if instance.qos_hard else False,
                            "metrics": soft_metrics,
                            "admission": soft_admission,
                            "gain_vs_base_pct": gain_vs_base_pct,
                            "accepted": int(stats.get("improvements", 0)),
                            "elite_cvx_calls": oracle.calls,
                            "elite_cvx_cache_hits": oracle.cache_hits,
                            "elite_runtime_s": elite_runtime_s,
                            "elite_stats": stats,
                            "instance": instance,
                            "base_solution": exploration.best_solution,
                            "base_solution_sha256": content_hash(exploration.best_solution),
                            "solution": final_solution,
                            "solution_sha256": content_hash(final_solution),
                            "base_stage1": stage_snapshot(instance, exploration.best_solution, base_cvx, stage=1),
                            "final_stage1": stage_snapshot(instance, final_solution, final_cvx, stage=1),
                            "oracle_records": oracle.solve_records,
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

    aggregate = (aggregate_profiles(rows) if instance.qos_hard else
                 aggregate_task_qos_profiles(rows))
    paired = (paired_summaries(rows) if instance.qos_hard else
              paired_task_qos_profiles(rows))
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
