from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from uav_mec.algorithms import (
    EnergyGuidedESIConfig,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    UavMecALNSSession,
    energy_guided_intensification,
)
from uav_mec.algorithms.alns.problem_operators import (
    contact_mode_intensification,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


FROZEN_BUDGETS = {
    50: {"total_s": 15.0, "prefix_s": 12.0, "branch_s": 3.0},
    80: {"total_s": 45.0, "prefix_s": 36.0, "branch_s": 9.0},
}


def _parse_int_list(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def _stage1_status(result) -> str:
    return str(
        result.diagnostics.get(
            "stage1_status",
            result.status,
        )
    )


def _strict(result) -> bool:
    return bool(
        result.feasible
        and _stage1_status(result) == "optimal"
    )


def _energy(result) -> float | None:
    return (
        float(result.energy_stage1_j)
        if _strict(result)
        else None
    )


def _accepted_families(stats: dict[str, Any]) -> list[str]:
    families: list[str] = []
    for item in stats.get("accepted_moves", []):
        if isinstance(item, dict):
            value = item.get("family") or item.get("move")
        else:
            value = item
        if value is not None:
            families.append(str(value))
    return families


def _metrics(
    checkpoint_energy_j: float,
    arm_energy_j: float | None,
    branch_runtime_s: float,
    exact_cvx_calls: int,
) -> dict[str, float | None]:
    if arm_energy_j is None:
        return {
            "delta_energy_j": None,
            "gain_j_per_s": None,
            "gain_j_per_cvx": None,
        }

    delta = checkpoint_energy_j - arm_energy_j
    return {
        "delta_energy_j": delta,
        "gain_j_per_s": (
            delta / branch_runtime_s
            if branch_runtime_s > 1e-12
            else None
        ),
        "gain_j_per_cvx": (
            delta / exact_cvx_calls
            if exact_cvx_calls > 0
            else None
        ),
    }


def _run_continued_b_alns(
    checkpoint,
    checkpoint_energy_j: float,
    branch_s: float,
) -> dict[str, Any]:
    arm = checkpoint.fork()
    result = arm.run_segment(max_runtime_s=branch_s)

    verify = Stage1CVXObjectiveOracle()
    final = verify.solve(
        checkpoint.instance,
        result.best_solution,
    )
    final_energy = _energy(final)

    row = {
        "arm": "continued_b_alns",
        "strict": _strict(final),
        "stage1_status": _stage1_status(final),
        "energy_j": final_energy,
        "branch_runtime_s": result.runtime_s,
        "iterations": result.iterations,
        "exact_cvx_calls": result.exact_cvx_calls,
        "exact_cvx_accepted": result.exact_cvx_accepted,
        "exact_cvx_accepted_hit_rate": (
            result.exact_cvx_accepted_hit_rate
        ),
        "accepted_move_families": [],
    }
    row.update(
        _metrics(
            checkpoint_energy_j,
            final_energy,
            result.runtime_s,
            result.exact_cvx_calls,
        )
    )
    return row


def _new_esi_state(checkpoint) -> UavMecState:
    fork = checkpoint.fork()
    return UavMecState(
        checkpoint.instance,
        deepcopy(checkpoint.best_solution),
        fork.evaluator,
    )


def _run_legacy_esi(
    checkpoint,
    checkpoint_energy_j: float,
    branch_s: float,
    max_rounds: int,
) -> dict[str, Any]:
    state = _new_esi_state(checkpoint)
    oracle = Stage1CVXObjectiveOracle()

    # Common checkpoint verification is deliberately outside branch timing.
    baseline = oracle.solve(
        checkpoint.instance,
        checkpoint.best_solution,
    )
    if not _strict(baseline):
        raise RuntimeError(
            "legacy ESI received a non-strict checkpoint"
        )
    calls_before = oracle.calls

    started = perf_counter()
    final_state, stats = contact_mode_intensification(
        state,
        config=checkpoint.config.problem,
        objective=oracle,
        max_rounds=max_rounds,
        max_runtime_s=branch_s,
    )
    runtime_s = perf_counter() - started
    calls_after_algorithm = oracle.calls

    final = oracle.solve(
        checkpoint.instance,
        final_state.solution,
    )
    final_energy = _energy(final)
    exact_calls = max(0, calls_after_algorithm - calls_before)
    accepted = int(stats.get("improvements", 0))

    row = {
        "arm": "legacy_esi",
        "strict": _strict(final),
        "stage1_status": _stage1_status(final),
        "energy_j": final_energy,
        "branch_runtime_s": runtime_s,
        "iterations": 0,
        "exact_cvx_calls": exact_calls,
        "exact_cvx_accepted": accepted,
        "exact_cvx_accepted_hit_rate": (
            accepted / exact_calls
            if exact_calls > 0
            else 0.0
        ),
        "accepted_move_families": _accepted_families(stats),
        "esi_stats": stats,
    }
    row.update(
        _metrics(
            checkpoint_energy_j,
            final_energy,
            runtime_s,
            exact_calls,
        )
    )
    return row


def _run_energy_guided_esi(
    checkpoint,
    checkpoint_energy_j: float,
    branch_s: float,
    max_rounds: int,
) -> dict[str, Any]:
    state = _new_esi_state(checkpoint)
    oracle = Stage1CVXObjectiveOracle()
    baseline = oracle.solve(
        checkpoint.instance,
        checkpoint.best_solution,
    )
    if not _strict(baseline):
        raise RuntimeError(
            "energy-guided ESI received a non-strict checkpoint"
        )
    calls_before = oracle.calls

    started = perf_counter()
    final_state, stats = energy_guided_intensification(
        state,
        config=checkpoint.config.problem,
        objective=oracle,
        guidance=EnergyGuidedESIConfig(),
        max_rounds=max_rounds,
        max_runtime_s=branch_s,
    )
    runtime_s = perf_counter() - started
    calls_after_algorithm = oracle.calls

    final = oracle.solve(
        checkpoint.instance,
        final_state.solution,
    )
    final_energy = _energy(final)
    exact_calls = max(0, calls_after_algorithm - calls_before)
    accepted = int(stats.get("improvements", 0))

    row = {
        "arm": "energy_guided_esi",
        "strict": _strict(final),
        "stage1_status": _stage1_status(final),
        "energy_j": final_energy,
        "branch_runtime_s": runtime_s,
        "iterations": 0,
        "exact_cvx_calls": exact_calls,
        "exact_cvx_accepted": accepted,
        "exact_cvx_accepted_hit_rate": (
            accepted / exact_calls
            if exact_calls > 0
            else 0.0
        ),
        "accepted_move_families": _accepted_families(stats),
        "esi_stats": stats,
    }
    row.update(
        _metrics(
            checkpoint_energy_j,
            final_energy,
            runtime_s,
            exact_calls,
        )
    )
    return row


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in sorted({int(row["tasks"]) for row in rows}):
        out[str(k)] = {}
        for arm in (
            "continued_b_alns",
            "legacy_esi",
            "energy_guided_esi",
        ):
            arm_rows = [
                arm_row
                for row in rows
                if int(row["tasks"]) == k
                for arm_row in row.get("arms", [])
                if arm_row["arm"] == arm
            ]
            strict_rows = [
                row for row in arm_rows if row["strict"]
            ]
            gains = [
                float(row["delta_energy_j"])
                for row in strict_rows
                if row["delta_energy_j"] is not None
            ]
            jps = [
                float(row["gain_j_per_s"])
                for row in strict_rows
                if row["gain_j_per_s"] is not None
            ]
            out[str(k)][arm] = {
                "runs": len(arm_rows),
                "strict": len(strict_rows),
                "mean_delta_energy_j": (
                    mean(gains) if gains else None
                ),
                "mean_gain_j_per_s": (
                    mean(jps) if jps else None
                ),
            }
    return out


def _write_output(
    path: Path,
    args,
    rows: list[dict[str, Any]],
    *,
    complete: bool,
) -> None:
    payload = {
        "experiment": "paired_checkpoint_fork_v7",
        "complete": complete,
        "protocol": {
            "budgets": FROZEN_BUDGETS,
            "checkpoint": "shared B-ALNS prefix historical best",
            "arms": [
                "continued_b_alns",
                "legacy_esi",
                "energy_guided_esi",
            ],
            "posthoc_stage1_verification_in_branch_budget": False,
            "checkpoint_stage1_verification_in_branch_budget": False,
        },
        "arguments": vars(args),
        "rows": rows,
        "aggregate": _aggregate(rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "v7 paired checkpoint fork: same B-ALNS prefix state, "
            "same extra wall-clock budget, three continuation arms."
        )
    )
    parser.add_argument(
        "--config",
        default="configs/baseline.yaml",
    )
    parser.add_argument(
        "--tasks",
        default="50,80",
    )
    parser.add_argument(
        "--scenario-seeds",
        default="85,86,87,88",
        help="development scenarios only; S93-100 are already seen hold-out",
    )
    parser.add_argument(
        "--algorithm-seeds",
        default="100,101,102",
    )
    parser.add_argument(
        "--mecs",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--uavs",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--max-esi-rounds",
        type=int,
        default=100,
        help="safety cap; wall-clock branch budget is the primary stop",
    )
    parser.add_argument(
        "--output",
        default="outputs/results/paired_checkpoint_fork_v7.json",
    )
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    tasks = _parse_int_list(args.tasks)
    scenario_seeds = _parse_int_list(args.scenario_seeds)
    algorithm_seeds = _parse_int_list(args.algorithm_seeds)
    unsupported = [k for k in tasks if k not in FROZEN_BUDGETS]
    if unsupported:
        raise ValueError(
            f"v7 frozen budgets only define K=50/80, got {unsupported}"
        )

    rows: list[dict[str, Any]] = []
    output = Path(args.output)

    for k in tasks:
        budget = FROZEN_BUDGETS[k]
        for scenario_seed in scenario_seeds:
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=k,
                num_uavs=args.uavs,
                num_mecs=args.mecs,
                scenario_seed=scenario_seed,
            )

            for algorithm_seed in algorithm_seeds:
                alns_cfg = UavMecALNSConfig(
                    seed=algorithm_seed,
                    max_runtime_s=budget["total_s"],
                    time_scaled_rrt=True,
                    enable_problem_operators=False,
                )
                session = UavMecALNSSession(
                    instance,
                    config=alns_cfg,
                )
                prefix = session.run_segment(
                    max_runtime_s=budget["prefix_s"],
                )
                checkpoint = session.checkpoint()

                checkpoint_oracle = Stage1CVXObjectiveOracle()
                checkpoint_cvx = checkpoint_oracle.solve(
                    instance,
                    checkpoint.best_solution,
                )
                checkpoint_strict = _strict(checkpoint_cvx)
                checkpoint_energy = _energy(checkpoint_cvx)

                row: dict[str, Any] = {
                    "tasks": k,
                    "mecs": args.mecs,
                    "uavs": args.uavs,
                    "scenario_seed": scenario_seed,
                    "algorithm_seed": algorithm_seed,
                    "total_budget_s": budget["total_s"],
                    "prefix_budget_s": budget["prefix_s"],
                    "branch_budget_s": budget["branch_s"],
                    "prefix_runtime_s": prefix.runtime_s,
                    "prefix_iterations": prefix.iterations,
                    "checkpoint_total_iterations": (
                        checkpoint.iterations_completed
                    ),
                    "checkpoint_strict": checkpoint_strict,
                    "checkpoint_stage1_status": _stage1_status(
                        checkpoint_cvx
                    ),
                    "checkpoint_energy_j": checkpoint_energy,
                    "arms": [],
                }

                if checkpoint_strict and checkpoint_energy is not None:
                    row["arms"].append(
                        _run_continued_b_alns(
                            checkpoint,
                            checkpoint_energy,
                            budget["branch_s"],
                        )
                    )
                    row["arms"].append(
                        _run_legacy_esi(
                            checkpoint,
                            checkpoint_energy,
                            budget["branch_s"],
                            args.max_esi_rounds,
                        )
                    )
                    row["arms"].append(
                        _run_energy_guided_esi(
                            checkpoint,
                            checkpoint_energy,
                            budget["branch_s"],
                            args.max_esi_rounds,
                        )
                    )

                rows.append(row)
                _write_output(
                    output,
                    args,
                    rows,
                    complete=False,
                )

                summary = "SKIP"
                if row["arms"]:
                    summary = " | ".join(
                        (
                            f"{arm['arm']}: "
                            f"dE={arm['delta_energy_j']:.3f} J "
                            f"J/s={arm['gain_j_per_s']:.3f}"
                            if arm["delta_energy_j"] is not None
                            and arm["gain_j_per_s"] is not None
                            else f"{arm['arm']}: non-strict"
                        )
                        for arm in row["arms"]
                    )
                print(
                    f"K={k} S={scenario_seed} A={algorithm_seed} "
                    f"prefix={prefix.runtime_s:.2f}s/"
                    f"{prefix.iterations}it "
                    f"checkpoint={row['checkpoint_stage1_status']} "
                    f"{summary}",
                    flush=True,
                )

    _write_output(
        output,
        args,
        rows,
        complete=True,
    )


if __name__ == "__main__":
    main()
