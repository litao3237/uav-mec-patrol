"""P0 exploratory time-allocation sweep with pre-registered NEW scenarios.

Hypothesis: the fixed 60%-exploration / 20%-ESI allocation sacrifices too
much effective ALNS search time. This trial holds the nominal end-to-end
budget, initial conditions, strict Stage-1/Stage-2 validation and proposed
2-opt* neighborhood fixed while reallocating time between exploration
and ESI (the remaining 20% is reserved for final validation).

S57-S60 and algorithm seeds 109/110 have NOT appeared in previous P0
diagnostics. This is a small exploratory confirmation set (4 independent
scenarios, seeds nested), not a population-level statistical proof.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import numpy as np

from experiment_common import provenance, current_source_hashes
from run_seven_methods import finalize
from run_p0_contact_diagnostics import profile_config
from run_p0_matched_budget import BUDGET_S, wall_clock_alns_config
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.problem_operators import contact_mode_intensification
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config

# All variants have the same soft end-to-end cap and 20% finalization reserve.
METHOD_FRACTIONS = {
    "B-ALNS": (0.80, 0.00),
    "original_60_20": (0.60, 0.20),
    "twoopt_60_20": (0.60, 0.20),
    "twoopt_65_15": (0.65, 0.15),
    "twoopt_70_10": (0.70, 0.10),
    "twoopt_75_05": (0.75, 0.05),
}
METHODS = tuple(METHOD_FRACTIONS)


def fractions(budget_s, initialization_s, exploration_fraction, esi_fraction):
    """Return disjoint nominal budget portions, counting initialization once."""
    if not (0 <= exploration_fraction <= .8 and 0 <= esi_fraction <= .2):
        raise ValueError("Bad time fractions")
    if abs(exploration_fraction + esi_fraction - .8) > 1e-10:
        raise ValueError("Exploration + ESI must consume 80% total")
    if budget_s <= 0 or initialization_s < 0:
        raise ValueError("Invalid budget or initialization")
    return {
        "exploration_s": max(0.0, exploration_fraction * budget_s - initialization_s),
        "elite_plus_anchor_s": esi_fraction * budget_s,
        "finalization_reserve_s": .20 * budget_s,
    }


def summarize(rows):
    out = []
    for K in sorted(set(row["tasks"] for row in rows)):
        blocks = {}
        for row in rows:
            if row["tasks"] == K:
                blocks.setdefault(
                    (row["scenario_seed"], row["algorithm_seed"]), {},
                )[row["method"]] = row
        for method in METHODS:
            own = [r for r in rows if r["tasks"] == K and r["method"] == method]
            def paired(reference):
                scen = {}
                pairs = []
                for (scenario, seed), block in blocks.items():
                    if method not in block or reference not in block:
                        continue
                    v, b = block[method], block[reference]
                    if v["qualified_both"] and b["qualified_both"]:
                        saving = b["stage1_energy_j"] - v["stage1_energy_j"]
                        pairs.append((scenario, saving))
                        scen.setdefault(scenario, []).append(saving)
                return {
                    "valid_pairs": len(pairs),
                    "independent_scenarios": len(scen),
                    "mean_saving_j": (
                        mean(mean(v) for v in scen.values()) if scen else None
                    ),
                    "per_scenario_mean_j": {
                        str(s): mean(xs) for s, xs in sorted(scen.items())
                    },
                    "wins": sum(diff > 1.0 for _, diff in pairs),
                    "losses": sum(diff < -1.0 for _, diff in pairs),
                    "ties": sum(abs(diff) <= 1.0 for _, diff in pairs),
                }
            out.append({
                "tasks": K,
                "method": method,
                "planned": len(own),
                "qualified_both": sum(r["qualified_both"] for r in own),
                "qualified_within_budget": sum(
                    r["qualified_both"] and r["within_budget"] for r in own
                ),
                "overruns": sum(not r["within_budget"] for r in own),
                "mean_end_to_end_s": mean(r["total_s"] for r in own),
                "mean_elite_candidates_evaluated": mean(
                    r["diagnostics"].get("elite_stats", {})
                    .get("candidates_evaluated", 0) for r in own
                ),
                "mean_elite_rounds": mean(
                    r["diagnostics"].get("elite_stats", {})
                    .get("rounds", 0) for r in own
                ),
                "vs_B": paired("B-ALNS"),
                "vs_original_ESI": paired("original_60_20"),
            })
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="50")
    parser.add_argument("--scenarios", default="57,58,59,60")
    parser.add_argument("--seeds", default="109,110")
    parser.add_argument("--geometric-pool", type=int, default=8)
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    task_sizes = [int(x.strip()) for x in args.tasks.split(",") if x.strip()]
    scenario_ids = [int(x.strip()) for x in args.scenarios.split(",") if x.strip()]
    algorithm_ids = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
    if not task_sizes or not scenario_ids or not algorithm_ids:
        raise ValueError("Empty evaluation matrix")
    if any(K not in BUDGET_S for K in task_sizes):
        raise ValueError(f"Unknown task scale: {task_sizes}")

    cfg = load_paper_scale_config(args.config)
    payload = {
        "complete": False,
        "protocol": {
            "id": "p0_fixed_budget_exploration_allocation_sweep_v1",
            "tasks": task_sizes,
            "scenarios": scenario_ids,
            "seeds": algorithm_ids,
            "methods": {method: list(fractions) for method, fractions in METHOD_FRACTIONS.items()},
            "finalization_reserve_fraction": .20,
            "soft_time_cap_s": BUDGET_S,
            "no_postprocessing": True,
            "paired_initial_state_and_frozen_instance": True,
            "same_60pct_exploration_checkpoint_for_original_and_twoopt": True,
            "all_failure_and_overrun_records_kept": True,
            "pre_register_before_holdout": "S57-S60, seeds A109-A110",
            "provenance": provenance(),
            "source_hashes": current_source_hashes(Path(__file__)),
        },
        "rows": [],
    }
    write_json(args.output, payload)

    try:
        for K in task_sizes:
            for S in scenario_ids:
                instance = build_paper_scale_instance(
                    cfg, num_tasks=K, num_uavs=5,
                    num_mecs=2, scenario_seed=S,
                )
                for seed in algorithm_ids:
                    init_started = perf_counter()
                    initial = build_mec_assisted_initial_solution(
                        instance, base_solution=build_greedy_initial_solution(instance),
                    )
                    initialization_s = perf_counter() - init_started
                    initial_sha = content_hash(initial)
                    budget_s = BUDGET_S[K]

                    # Randomize execution order to reduce server thermal/order
                    # effects. Group all variants sharing 60% exploration.
                    groups = ["B", "f60", "f65", "f70", "f75"]
                    order = list(np.random.default_rng(
                        [20261010, K, S, seed],
                    ).permutation(groups))
                    for group in order:
                        if group == "B":
                            method_names = ["B-ALNS"]
                        elif group == "f60":
                            method_names = list(np.random.default_rng(
                                [20261010, K, S, seed, 1],
                            ).permutation(["original_60_20", "twoopt_60_20"]))
                        else:
                            method_names = [f"twoopt_{group[1:]}_{80-int(group[1:]):02d}"]
                            # f65 -> twoopt_65_15, f70 -> twoopt_70_10 etc.
                        method0 = method_names[0]
                        fraction_e, fraction_esi = METHOD_FRACTIONS[method0]
                        split = fractions(
                            budget_s, initialization_s, fraction_e, fraction_esi,
                        )
                        evaluator = ScreenedProxyObjectiveEvaluator()
                        started = perf_counter()
                        search = run_uav_mec_alns(
                            instance, initial_solution=deepcopy(initial),
                            config=wall_clock_alns_config(
                                seed, split["exploration_s"],
                            ),
                            evaluator=evaluator,
                        )
                        exploration_s = perf_counter() - started
                        base = deepcopy(search.best_solution)
                        checkpoint_sha = content_hash(base)

                        anchor = None
                        anchor_valid = False
                        anchor_s = 0.0
                        if group != "B":
                            oracle_anchor = Stage1CVXObjectiveOracle()
                            started = perf_counter()
                            anchor = oracle_anchor.solve(instance, base)
                            anchor_s = perf_counter() - started
                            anchor_valid = stage1_is_qualified(anchor)

                        for method in method_names:
                            final = deepcopy(base)
                            elite_s = 0.0
                            prime_s = 0.0
                            stats = {
                                "exploration_fraction": fraction_e,
                                "elite_fraction": fraction_esi,
                                "initial_sha256": initial_sha,
                                "exploration_checkpoint_sha256": checkpoint_sha,
                                "exploration_runtime_s": exploration_s,
                                "exploration_cap_s": split["exploration_s"],
                                "anchor_runtime_s": anchor_s,
                                "B_stop_reason": search.stop_reason,
                                "B_checkpoint_strict": anchor_valid if group != "B" else None,
                            }
                            if group != "B":
                                oracle = Stage1CVXObjectiveOracle()
                                started = perf_counter()
                                oracle.prime(instance, base, anchor)
                                prime_s = perf_counter() - started
                                remain = max(
                                    0.0,
                                    split["elite_plus_anchor_s"] - anchor_s - prime_s,
                                )
                                stats["esi_time_remaining_s"] = remain
                                if anchor_valid:
                                    started = perf_counter()
                                    elite, elite_stats = contact_mode_intensification(
                                        UavMecState(
                                            instance, deepcopy(base), evaluator,
                                        ),
                                        config=(
                                            UavMecALNSConfig().problem
                                            if method == "original_60_20"
                                            else profile_config(
                                                UavMecALNSConfig().problem,
                                                "retain_remove_two_opt_star",
                                                args.geometric_pool,
                                            )
                                        ),
                                        objective=oracle,
                                        max_rounds=2,
                                        max_runtime_s=remain,
                                    )
                                    elite_s = perf_counter() - started
                                    final = elite.solution
                                    stats["elite_stats"] = elite_stats
                                else:
                                    stats["elite_skipped"] = "unqualified_anchor"
                                stats["esi_oracle_calls"] = oracle.calls

                            search_s = exploration_s + anchor_s + prime_s + elite_s
                            completed = finalize(
                                instance, final, method=method, seed=seed,
                                initialization_s=initialization_s,
                                search_s=search_s,
                                diagnostics=stats,
                            )
                            total_s = float(completed["timing"]["total_with_audit_s"])
                            stage1_ok = bool(completed["stage1"]["qualified"])
                            stage2_ok = bool(completed["stage2"]["qualified"])
                            completed.update(
                                tasks=K,
                                scenario_seed=S,
                                algorithm_seed=seed,
                                method=method,
                                initial_sha256=initial_sha,
                                checkpoint_sha256=checkpoint_sha,
                                nominal_budget_s=budget_s,
                                total_s=total_s,
                                overrun_s=max(0.0, total_s - budget_s),
                                within_budget=total_s <= budget_s,
                                qualified_both=stage1_ok and stage2_ok,
                                stage1_energy_j=(
                                    float(completed["resources"].energy_stage1_j)
                                    if stage1_ok else None
                                ),
                            )
                            payload["rows"].append(completed)
                            write_json(args.output, payload)
                            print(
                                f"ALLOCATION K{K} S{S} A{seed} {method}: "
                                f"E={completed['stage1_energy_j']}, "
                                f"qualified={completed['qualified_both']}, "
                                f"elite_evals={stats.get('elite_stats', {}).get('candidates_evaluated',0)}, "
                                f"total_s={total_s:.3f}/{budget_s} "
                                f"overrun={completed['overrun_s']:.3f}",
                                flush=True,
                            )
        payload["summary"] = summarize(payload["rows"])
        payload["complete"] = True
        write_json(args.output, payload)
        print("ALLOCATION_SUMMARY=" + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    except Exception as exc:
        payload["execution_error"] = {
            "type": type(exc).__name__, "message": str(exc),
        }
        write_json(args.output, payload)
        raise


if __name__ == "__main__":
    main()
