from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from uav_mec.algorithms import UavMecALNSConfig, run_uav_mec_alns
from uav_mec.algorithms.alns.problem_operators import (
    ProblemOperatorConfig,
    contact_mode_intensification,
)
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.algorithms.alns.hybrid import Stage1CVXObjectiveOracle
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


VARIANTS = {
    "full_esi": {},
    "wo_route_compute_relocation": {
        "elite_enable_route_compute_relocate": False,
    },
    "wo_contact_operations": {
        "elite_enable_contact_relocate": False,
        "elite_enable_contact_point_replace": False,
        "elite_enable_contact_remove": False,
    },
    "wo_batch_operations": {
        "elite_enable_batch_merge": False,
        "elite_enable_batch_split": False,
        "elite_enable_mode_batch_reassign": False,
    },
    "wo_progressive_widening": {
        "elite_progressive_widening": False,
    },
}


def parse_list(value: str):
    return [int(x) for x in value.split(",") if x.strip()]


def strict_energy(oracle, instance, solution):
    result = oracle.solve(instance, solution)
    status = str(result.diagnostics.get("stage1_status", result.status))
    return {
        "strict": bool(result.feasible and status == "optimal"),
        "stage1_status": status,
        "energy_j": float(result.energy_stage1_j)
        if result.feasible and status == "optimal"
        else None,
    }


def run_variant(instance, seed: int, variant: str):
    config = UavMecALNSConfig(seed=seed, iterations=100)
    exploration = run_uav_mec_alns(instance, config=config)
    oracle = Stage1CVXObjectiveOracle()
    base = strict_energy(oracle, instance, exploration.best_solution)

    if not base["strict"]:
        return {
            "variant": variant,
            **base,
            "accepted": 0,
            "cvx_calls": oracle.calls,
        }

    state = UavMecState(
        instance,
        deepcopy(exploration.best_solution),
        oracle,
    )
    op_config = ProblemOperatorConfig(**VARIANTS[variant])
    final_state, stats = contact_mode_intensification(
        state,
        config=op_config,
        objective=oracle,
        max_rounds=2,
    )
    final = strict_energy(oracle, instance, final_state.solution)
    return {
        "variant": variant,
        **final,
        "baseline_energy_j": base["energy_j"],
        "improvement_j": (
            base["energy_j"] - final["energy_j"]
            if final["energy_j"] is not None
            else None
        ),
        "accepted": int(stats.get("improvements", 0)),
        "cvx_calls": oracle.calls,
        "stats": stats,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default="30,50,70,80")
    parser.add_argument("--scenario-seeds", default="45,46,47")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--output", default="outputs/results/multiscale_ablation.json")
    args = parser.parse_args()

    cfg = load_paper_scale_instance if False else load_paper_scale_config("configs/baseline.yaml")
    rows = []
    for k in parse_list(args.tasks):
        for scenario in parse_list(args.scenario_seeds):
            instance = build_paper_scale_instance(
                cfg,
                num_tasks=k,
                num_uavs=5,
                num_mecs=2,
                scenario_seed=scenario,
            )
            for seed in parse_list(args.algorithm_seeds):
                for variant in VARIANTS:
                    rows.append({
                        "tasks": k,
                        "scenario_seed": scenario,
                        "algorithm_seed": seed,
                        **run_variant(instance, seed, variant),
                    })

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"experiment": "multiscale_ablation", "rows": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
