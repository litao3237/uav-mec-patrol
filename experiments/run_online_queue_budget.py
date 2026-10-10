"""Online queue-aware vs legacy ALNS/ESI under identical nominal end-to-end caps.

This is the first *actual search-trajectory* gate for the independently
validated FIFO/EDF necessary bound. No algorithm postprocessing is appended.
We compare published ScreenedProxyObjectiveEvaluator against the opt-in
QueueAwareScreenedProxyObjectiveEvaluator, separately for B-ALNS and ESI.

The two evaluators use the same instance, original MEC-assisted initial
solution, ALNS RNG seed, time-scaled acceptance and nominal runtime allocation;
the candidate trajectories may diverge, which is the treatment being tested.

K50 budget 15s; K80 budget 45s; B receives 80% search, ESI receives
60% ALNS + 20% strict original ESI, both reserve 20% for Stage1/2 audits.
Single CVX calls are non-preemptible, so soft overruns and strict failures
are tracked, not disguised. The study is pre-registered on new S69/S70
scenarios and A115/A116 algorithm seeds, with three predeclared physical
profiles baseline, compute_x1p5 and deadline_x0p9.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import numpy as np

from experiment_common import current_source_hashes, provenance
from run_seven_methods import finalize
from run_model_sensitivity import make_profile, shared_task_geometry_hash
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_alns,
    run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns.queue_evaluator import (
    QueueAwareScreenedProxyObjectiveEvaluator,
)
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


PROFILES = ("baseline", "compute_x1p5", "deadline_x0p9")
METHODS = ("B-ALNS-legacy", "B-ALNS-queue", "ESI-ALNS-legacy", "ESI-ALNS-queue")
TIME_BUDGET_S = {50: 15.0, 80: 45.0}


def split_budget(budget_s, initialization_s, method):
    if method not in METHODS:
        raise ValueError(method)
    if budget_s <= 0 or initialization_s < 0:
        raise ValueError("Invalid nominal time budget")
    is_esi = method.startswith("ESI-")
    return {
        "alns_s": max(
            0.0,
            (0.6 if is_esi else 0.8) * budget_s - initialization_s,
        ),
        "elite_s": 0.2 * budget_s if is_esi else 0.0,
        "reserved_final_s": 0.2 * budget_s,
    }


def scenario_equal(rows, delta_key="energy_stage1_j", *, strict_time=False):
    grouped = defaultdict(list)
    for r in rows:
        if r.get("both_qualified") and (not strict_time or r.get("within_budget")):
            grouped[r["scenario"]].append(float(r[delta_key]))
    return (
        mean(mean(arr) for arr in grouped.values()) if grouped else None,
        len(grouped),
    )


def summarize(rows):
    summarized = []
    for K in sorted({r["tasks"] for r in rows}):
        for profile in PROFILES:
            groups = {
                (r["scenario"], r["seed"]): {}
                for r in rows if r["tasks"] == K and r["profile"] == profile
            }
            for r in rows:
                if r["tasks"] == K and r["profile"] == profile:
                    groups[r["scenario"], r["seed"]][r["method"]] = r
            for method in METHODS:
                sample = [
                    r for r in rows
                    if r["tasks"] == K and r["profile"] == profile
                    and r["method"] == method
                ]
                paired = []
                paired_within = []
                ref_name = method.replace("-queue", "-legacy")
                if ref_name != method:
                    for (S, seed), block in groups.items():
                        current, original = block.get(method), block.get(ref_name)
                        if not current or not original:
                            continue
                        if current.get("both_qualified") and original.get("both_qualified"):
                            diff = original["energy_stage1_j"] - current["energy_stage1_j"]
                            paired.append((S, diff))
                            if current["within_budget"] and original["within_budget"]:
                                paired_within.append((S, diff))
                def paired_effect(pairs):
                    g = defaultdict(list)
                    for s, delta in pairs:
                        g[s].append(delta)
                    return (
                        mean(mean(v) for v in g.values()) if g else None,
                        len(g),
                    )
                savings, independent = paired_effect(paired)
                timed_savings, timed_independent = paired_effect(paired_within)
                valid = [r for r in sample if r.get("both_qualified")]
                q = [r["queue_stats"] for r in sample if r.get("queue_stats")]
                base = [r["evaluator_stats"] for r in sample if r.get("evaluator_stats")]
                summarized.append({
                    "tasks": K,
                    "profile": profile,
                    "method": method,
                    "planned": len(sample),
                    "stage1_qualified": sum(r.get("stage1_qualified", False) for r in sample),
                    "both_qualified": len(valid),
                    "qualified_within_budget": sum(
                        r.get("both_qualified") and r.get("within_budget")
                        for r in sample
                    ),
                    "overruns": sum(
                        r.get("status") == "ok" and not r.get("within_budget")
                        for r in sample
                    ),
                    "errors": sum(r.get("status") == "error" for r in sample),
                    "mean_total_s": (
                        mean(r["total_s"] for r in sample
                             if r.get("total_s") is not None)
                        if any(r.get("total_s") is not None for r in sample)
                        else None
                    ),
                    "mean_energy_stage1_j_conditional": (
                        mean(r["energy_stage1_j"] for r in valid) if valid else None
                    ),
                    "mean_queue_additional_rejects": (
                        mean(x["additional_rejections"] for x in q) if q else None
                    ),
                    "mean_queue_avoided_exact_cvx": (
                        mean(x["avoided_exact_cvx_calls"] for x in q) if q else None
                    ),
                    "mean_queue_cpu_s": (
                        mean(x["queue_precheck_time_s"] for x in q) if q else None
                    ),
                    "mean_cvx_refinements": (
                        mean(x["cvx_refinements"] for x in base) if base else None
                    ),
                    "mean_evaluator_unique_candidates": (
                        mean(x["calls"] - x["cache_hits"] for x in base)
                        if base else None
                    ),
                    "paired_vs_legacy": len(paired),
                    "paired_scenario_count": independent,
                    "paired_saving_vs_legacy_j": savings,
                    "timed_pairs_vs_legacy": len(paired_within),
                    "timed_paired_scenario_count": timed_independent,
                    "timed_paired_saving_vs_legacy_j": timed_savings,
                    "wins_vs_legacy": sum(delta > 1.0 for _, delta in paired),
                    "losses_vs_legacy": sum(delta < -1.0 for _, delta in paired),
                    "ties_vs_legacy": sum(abs(delta) <= 1.0 for _, delta in paired),
                })
    return summarized


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    Ks = [int(t) for t in args.tasks.split(",") if t.strip()]
    Ss = [int(s) for s in args.scenarios.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    if not Ks or not Ss or not seeds or not profiles or len(set(profiles)) != len(profiles):
        raise ValueError("Missing or duplicate experiment dimensions")
    if any(k not in TIME_BUDGET_S for k in Ks):
        raise ValueError("Unsupported task size")
    if any(p not in PROFILES for p in profiles):
        raise ValueError("Unknown physical sensitivity profile")

    cfg = load_paper_scale_config(args.config)
    payload = {
        "complete": False,
        "protocol": {
            "id": "queue_aware_online_budget_v1",
            "tasks": Ks, "scenarios": Ss, "algorithm_seeds": seeds,
            "profiles": profiles, "methods": METHODS,
            "budgets_s": TIME_BUDGET_S,
            "scenario_seed_pre_registered": "S69,S70 (fresh)",
            "algorithm_seeds_pre_registered": "A115,A116 (fresh)",
            "one_factor_immutable_geometry": True,
            "default_develop_evaluator_and_hybrid_untouched": True,
            "queue_only_extra_time_lower_bound": True,
            "time_protocol": "B 80%, ESI 60% exploration+20% elite, all reserve 20% finalization",
            "limits": "soft end-to-end time; single solver calls not preempted",
            "source_hashes": current_source_hashes(Path(__file__)),
            "provenance": provenance(),
        },
        "rows": [],
    }
    write_json(args.output, payload)
    errors = []
    for K in Ks:
        for S in Ss:
            original = build_paper_scale_instance(
                cfg, num_tasks=K, num_uavs=5, num_mecs=2,
                scenario_seed=S,
            )
            geometry_hash = shared_task_geometry_hash(original)
            for profile in profiles:
                instance = make_profile(original, profile)
                if shared_task_geometry_hash(instance) != geometry_hash:
                    raise RuntimeError("Physical sensitivity modified paired geometry")
                for seed in seeds:
                    t0 = perf_counter()
                    try:
                        initial = build_mec_assisted_initial_solution(
                            instance, base_solution=build_greedy_initial_solution(instance),
                        )
                    except Exception as exc:
                        failure_s = perf_counter() - t0
                        for method in METHODS:
                            payload["rows"].append({
                                "tasks": K, "scenario": S,
                                "profile": profile, "seed": seed,
                                "method": method, "status": "error",
                                "error": {"type": type(exc).__name__, "message": str(exc)},
                                "failure_stage": "initialization",
                                "initialization_s": failure_s,
                                "both_qualified": False,
                                "stage1_qualified": False,
                                "within_budget": False,
                                "queue_stats": None,
                                "evaluator_stats": None,
                            })
                        errors.append(f"K{K} S{S} profile={profile} seed={seed}: {exc}")
                        write_json(args.output, payload)
                        continue
                    init_s = perf_counter() - t0
                    init_hash = content_hash(initial)
                    order = list(np.random.default_rng(
                        [20261010, K, S, seed],
                    ).permutation(METHODS))
                    for method in order:
                        is_esi = method.startswith("ESI-")
                        use_queue = method.endswith("-queue")
                        split = split_budget(TIME_BUDGET_S[K], init_s, method)
                        ev = (
                            QueueAwareScreenedProxyObjectiveEvaluator()
                            if use_queue else ScreenedProxyObjectiveEvaluator()
                        )
                        search_started = perf_counter()
                        row = {
                            "tasks": K, "scenario": S, "seed": seed,
                            "profile": profile, "method": method,
                            "status": "ok", "initial_sha256": init_hash,
                            "instance_sha256": content_hash(instance),
                            "geometry_sha256": geometry_hash,
                            "initialization_s": init_s,
                            "requested_ALNS_runtime_s": split["alns_s"],
                            "requested_ESI_runtime_s": split["elite_s"],
                            "nominal_budget_s": TIME_BUDGET_S[K],
                            "method_execution_order": order,
                        }
                        try:
                            config = UavMecALNSConfig(
                                seed=seed, iterations=100,
                                max_runtime_s=split["alns_s"],
                                time_scaled_rrt=split["alns_s"] > 0.0,
                                enable_problem_operators=False,
                            )
                            if is_esi:
                                result = run_uav_mec_hybrid_alns(
                                    instance, initial_solution=deepcopy(initial),
                                    config=config, evaluator=ev,
                                    elite_rounds=2,
                                    exploration_max_runtime_s=split["alns_s"],
                                    elite_max_runtime_s=split["elite_s"],
                                )
                                solution = result.best_solution
                                stats = {
                                    "exploration_s": result.exploration_runtime_s,
                                    "elite_phase_s": result.elite_phase_runtime_s,
                                    "elite_stats": result.elite_stats,
                                    "elite_cvx_calls": result.elite_cvx_calls,
                                    "B_checkpoint_sha256": content_hash(
                                        result.exploration.best_solution
                                    ),
                                }
                            else:
                                result = run_uav_mec_alns(
                                    instance, initial_solution=deepcopy(initial),
                                    config=config, evaluator=ev,
                                )
                                solution = result.best_solution
                                stats = {
                                    "stop_reason": result.stop_reason,
                                    "stop_elapsed_s": result.stop_elapsed_s,
                                }
                            search_s = perf_counter() - search_started
                            row["evaluator_stats"] = asdict(ev.stats)
                            row["queue_stats"] = (
                                asdict(ev.queue_stats) if use_queue else None
                            )
                            row["diagnostics"] = stats
                            output = finalize(
                                instance, solution,
                                method=method, seed=seed,
                                initialization_s=init_s,
                                search_s=search_s,
                                diagnostics=stats,
                            )
                            both = bool(
                                output["stage1"]["qualified"]
                                and output["stage2"]["qualified"]
                            )
                            total_s = float(output["timing"]["total_with_audit_s"])
                            row.update(
                                strict_result=output,
                                total_s=total_s,
                                search_s=search_s,
                                overrun_s=max(0.0, total_s - TIME_BUDGET_S[K]),
                                within_budget=total_s <= TIME_BUDGET_S[K],
                                stage1_qualified=bool(output["stage1"]["qualified"]),
                                stage2_qualified=bool(output["stage2"]["qualified"]),
                                both_qualified=both,
                                energy_stage1_j=(
                                    float(output["resources"].energy_stage1_j)
                                    if both else None
                                ),
                                solution_sha256=content_hash(solution),
                                failure_stage=(
                                    None if both else (
                                        "stage1" if not output["stage1"]["qualified"]
                                        else "stage2"
                                    )
                                ),
                            )
                        except Exception as exc:
                            row.update(
                                status="error", failure_stage="exception",
                                stage1_qualified=False, stage2_qualified=False,
                                both_qualified=False,
                                total_s=init_s + perf_counter() - search_started,
                                queue_stats=(
                                    asdict(ev.queue_stats) if use_queue else None
                                ),
                                evaluator_stats=asdict(ev.stats),
                                error={"type": type(exc).__name__, "message": str(exc)},
                            )
                            errors.append(
                                f"K{K} S{S} A{seed} {profile} {method}: {exc}"
                            )
                        payload["rows"].append(row)
                        write_json(args.output, payload)
                        print(
                            f"ONLINE_QUEUE K{K} S{S} A{seed} {profile} {method}: "
                            f"qualified={row['both_qualified']} "
                            f"E={row.get('energy_stage1_j')} "
                            f"total={row.get('total_s',0):.3f}s "
                            f"queue_extra={((row.get('queue_stats') or {}).get('additional_rejections'))} "
                            f"avoided_cvx={((row.get('queue_stats') or {}).get('avoided_exact_cvx_calls'))}",
                            flush=True,
                        )
    payload["summary"] = summarize(payload["rows"])
    payload["complete"] = True
    payload["unexpected_errors"] = errors
    write_json(args.output, payload)
    print("ONLINE_QUEUE_SUMMARY=" + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    if errors:
        raise RuntimeError(f"Unexpected evaluator/program errors, preserved: {errors[:3]}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tasks", default="50")
    p.add_argument("--scenarios", default="69,70")
    p.add_argument("--seeds", default="115,116")
    p.add_argument("--profiles", default=",".join(PROFILES))
    p.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())


if __name__ == "__main__":
    main()
