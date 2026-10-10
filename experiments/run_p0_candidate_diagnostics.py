"""Diagnostic-only audit: CVX vs proxy ranking and optimistic UAV energy LB.

This script does not change the ESI algorithm, remove candidates, or claim
the approximate proxy ranks all generated possibilities. It evaluates both
the default six-slot ESI shortlist and a LIMITED widened candidate sample
from the same B-ALNS checkpoint. Only Stage-1 qualified energies count.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from time import perf_counter
from statistics import mean

from experiment_common import provenance, current_source_hashes
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
)
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.alns.problem_operators import (
    _structural_elite_candidates,
    _proxy_precheck_key,
)
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config
from uav_mec.optimization.resource.energy_lower_bound import (
    fixed_structure_energy_lower_bound,
    can_certify_no_meaningful_improvement,
)
from run_p0_contact_diagnostics import parse_ids, profile_config


PROFILES = ("original_esi", "retain_remove_combined")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="50")
    parser.add_argument("--scenarios", default="47")
    parser.add_argument("--seeds", default="103")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--widen-limit", type=int, default=12)
    parser.add_argument("--new-cvx-limit", type=int, default=12)
    parser.add_argument("--geometric-pool", type=int, default=10)
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    instance_config = load_paper_scale_config(args.config)
    payload = {
        "complete": False,
        "protocol": {
            "id": "p0_proxy_lowerbound_coverage_v1",
            "tasks": parse_ids(args.tasks),
            "scenarios": parse_ids(args.scenarios),
            "seeds": parse_ids(args.seeds),
            "profiles": list(PROFILES),
            "widen_limit": args.widen_limit,
            "new_cvx_limit": args.new_cvx_limit,
            "interpretation": "diagnostic only: default shortlist plus limited widened pool, NO online pruning",
            "provenance": provenance(),
            "source_hashes": current_source_hashes(Path(__file__)),
        },
        "rows": [],
    }
    write_json(args.output, payload)
    try:
        for K in parse_ids(args.tasks):
            for S in parse_ids(args.scenarios):
                instance = build_paper_scale_instance(
                    instance_config, num_tasks=K, num_uavs=5,
                    num_mecs=2, scenario_seed=S,
                )
                initial = build_mec_assisted_initial_solution(
                    instance, base_solution=build_greedy_initial_solution(instance),
                )
                for seed in parse_ids(args.seeds):
                    evaluator = ScreenedProxyObjectiveEvaluator()
                    explore = run_uav_mec_alns(
                        instance,
                        initial_solution=deepcopy(initial),
                        config=UavMecALNSConfig(iterations=args.iterations, seed=seed),
                        evaluator=evaluator,
                    )
                    base = explore.best_solution
                    oracle = Stage1CVXObjectiveOracle()
                    anchor = oracle.solve(instance, base)
                    if not stage1_is_qualified(anchor):
                        payload["rows"].append({
                            "tasks": K, "scenario_seed": S, "seed": seed,
                            "skipped": "unqualified_B_ALNS",
                            "stage1_status": anchor.status,
                        })
                        write_json(args.output, payload)
                        continue
                    baseline_energy = float(anchor.energy_stage1_j)
                    for profile in PROFILES:
                        state = UavMecState(instance, deepcopy(base), evaluator)
                        cfg = profile_config(
                            UavMecALNSConfig().problem,
                            profile, args.geometric_pool,
                        )
                        standard_trace = {}
                        expanded_trace = {}
                        started = perf_counter()
                        standard = _structural_elite_candidates(
                            state, config=cfg, trace=standard_trace,
                        )
                        wide = _structural_elite_candidates(
                            state,
                            config=replace(
                                cfg,
                                elite_shortlist_limit=args.widen_limit,
                                elite_family_quota=2,
                            ),
                            trace=expanded_trace,
                        )
                        candidate_generation_s = perf_counter() - started
                        entries = []
                        seen = set()
                        std_sigs = {solution_signature(c) for _, c in standard}
                        for label, candidate in standard + wide:
                            key = solution_signature(candidate)
                            if key in seen or len(entries) >= args.new_cvx_limit:
                                continue
                            seen.add(key)
                            entries.append(
                                (label, candidate, key in std_sigs)
                            )

                        candidate_stats = []
                        false_prune_count = 0
                        for rank, (label, candidate, from_standard) in enumerate(entries, start=1):
                            optimistic_lb = fixed_structure_energy_lower_bound(
                                instance, candidate,
                            )
                            key = _proxy_precheck_key(state, candidate)
                            screened_out = can_certify_no_meaningful_improvement(
                                optimistic_lb, baseline_energy,
                            )
                            started = perf_counter()
                            solved = oracle.solve(instance, candidate)
                            elapsed = perf_counter() - started
                            qualified = stage1_is_qualified(solved)
                            energy = (
                                float(solved.energy_stage1_j) if qualified else None
                            )
                            saving_j = (
                                baseline_energy - energy if qualified else None
                            )
                            accept_tol = max(
                                1.0,
                                1e-4 * max(1.0, baseline_energy, energy or 0.0),
                            )
                            improving = bool(
                                qualified and saving_j > accept_tol
                            )
                            safety_tol = max(
                                0.02,
                                2e-6 * max(1.0, energy or baseline_energy),
                            )
                            lb_consistent = (
                                not qualified or optimistic_lb <= energy + safety_tol
                            )
                            if not lb_consistent:
                                raise RuntimeError(
                                    f"Optimistic energy LB exceeded strict CVX result:"
                                    f" K{K} S{S} seed{seed} {label}, "
                                    f"bound={optimistic_lb}, strict={energy}"
                                )
                            if screened_out and improving:
                                false_prune_count += 1
                            candidate_stats.append({
                                "rank": rank,
                                "label": label,
                                "in_default_shortlist": from_standard,
                                "proxy_rank_key": list(key),
                                "lower_bound_j": optimistic_lb,
                                "certified_non_improving": screened_out,
                                "stage1_qualified": qualified,
                                "stage1_status": solved.status,
                                "strict_energy_j": energy,
                                "strict_saving_j": saving_j,
                                "strict_improving": improving,
                                "lb_consistent": lb_consistent,
                                "cvx_wall_s": elapsed,
                            })
                        if false_prune_count:
                            raise RuntimeError(
                                f"Found {false_prune_count} false energy-bound exclusions"
                            )
                        improvements_std = [
                            x["strict_saving_j"] for x in candidate_stats
                            if x["in_default_shortlist"] and x["strict_improving"]
                        ]
                        improvements_wide_only = [
                            x["strict_saving_j"] for x in candidate_stats
                            if not x["in_default_shortlist"] and x["strict_improving"]
                        ]
                        payload["rows"].append({
                            "tasks": K, "scenario_seed": S, "seed": seed,
                            "profile": profile,
                            "base_energy_j": baseline_energy,
                            "B_checkpoint_sha256": content_hash(base),
                            "default_trace": standard_trace,
                            "widened_trace": expanded_trace,
                            "generation_s": candidate_generation_s,
                            "candidate_results": candidate_stats,
                            "sample_size": len(candidate_stats),
                            "prunable_count": sum(
                                x["certified_non_improving"] for x in candidate_stats
                            ),
                            "false_prune_count": false_prune_count,
                            "strict_improving_in_default": len(improvements_std),
                            "strict_improving_below_default": len(improvements_wide_only),
                            "best_default_saving_j": max(improvements_std, default=0.0),
                            "best_extra_saving_j": max(improvements_wide_only, default=0.0),
                            "oracle_calls": oracle.calls,
                        })
                        write_json(args.output, payload)
                        print(
                            f"LB_AUDIT K{K} S{S} A{seed} {profile}: "
                            f"n={len(candidate_stats)}, prunable={sum(x['certified_non_improving'] for x in candidate_stats)}, "
                            f"strict_good_default={len(improvements_std)}, "
                            f"strict_good_extra={len(improvements_wide_only)}, "
                            f"best_extra={max(improvements_wide_only,default=0.0):.3f}J",
                            flush=True,
                        )
        payload["complete"] = True
        write_json(args.output, payload)
    except Exception as exc:
        payload["execution_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        write_json(args.output, payload)
        raise


if __name__ == "__main__":
    main()
