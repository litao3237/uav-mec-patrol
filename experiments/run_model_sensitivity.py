"""One-factor-at-a-time UAV-MEC parameter sensitivity (original develop algorithms).

For each (task scale, independent scenario seed), sample ONE immutable base
instance. Perturb ONLY computation density, realized per-task deadline, or
MEC bandwidth; preserve all other generated data, coordinates and contact
geometry. ALNS method and objective implementations are unchanged.

This is a *model-mechanism diagnosis*, not a hyperparameter search for a
favorable ESI result and NOT an equal-wall-time B-ALNS vs ESI benchmark.
B and ESI share the same 100-iteration exploration within each physical
configuration, and ESI runs up to two ADDITIONAL original elite rounds.
No failed numerical/structural stage is counted as a feasible observation.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

import numpy as np

from experiment_common import current_source_hashes, provenance
from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,
    Stage1CVXObjectiveOracle,
    UavMecALNSConfig,
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
    run_uav_mec_hybrid_alns,
)
from uav_mec.analysis.constraint_audit import AuditTolerance
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.domain import Instance, ExecutionMode
from uav_mec.evaluation.geometry import distance
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


# Freeze before formal runs. Multipliers are NOT tuned to ESI success.
PROFILES: dict[str, tuple[str, float]] = {
    "baseline": ("baseline", 1.0),
    "compute_x1p5": ("compute_density", 1.5),
    "compute_x2p0": ("compute_density", 2.0),
    "deadline_x0p9": ("deadline", 0.9),
    "deadline_x0p8": ("deadline", 0.8),
    "bandwidth_x0p5": ("mec_bandwidth", 0.5),
    "bandwidth_x1p5": ("mec_bandwidth", 1.5),
}
METHODS = ("B-ALNS", "ESI-ALNS")


def make_profile(base: Instance, profile: str) -> Instance:
    """Preserve paired instance identity while changing exactly one factor.

    Deadline scaling is applied to *realized* generated deadlines.
    Regenerating from YAML instead could reapply the deadline floor and
    silently weaken the intended experimental perturbation.
    """
    if profile not in PROFILES:
        raise ValueError(f"Unknown parameter profile: {profile}")
    factor, scale = PROFILES[profile]
    if factor == "baseline":
        return deepcopy(base)
    if factor == "compute_density":
        return replace(
            base,
            tasks={
                t: replace(task, cycles_per_bit=task.cycles_per_bit * scale)
                for t, task in base.tasks.items()
            },
        )
    if factor == "deadline":
        return replace(
            base,
            tasks={
                t: replace(task, deadline_s=task.deadline_s * scale)
                for t, task in base.tasks.items()
            },
        )
    if factor == "mec_bandwidth":
        return replace(
            base,
            mecs={
                m: replace(mec, bandwidth_mhz=mec.bandwidth_mhz * scale)
                for m, mec in base.mecs.items()
            },
        )
    raise AssertionError(factor)


def shared_task_geometry_hash(instance: Instance) -> str:
    """Should remain bit-for-bit equal across every profile in a scenario."""
    return content_hash({
        "depot": instance.depot_xy,
        "task_xy_data_collect_release": {
            t: (task.x, task.y, task.data_mb, task.collect_s, task.release_s)
            for t, task in sorted(instance.tasks.items())
        },
        "contact_xy": {
            p: (cp.mec_id, cp.x, cp.y)
            for p, cp in sorted(instance.contact_points.items())
        },
        "uav_model": instance.uavs,
    })


def describe_instance(instance: Instance, *, configured_fastest_cpu: float) -> dict:
    workloads = [t.workload_gcycles for t in instance.tasks.values()]
    deadlines = [t.deadline_s for t in instance.tasks.values()]
    # The generator's original bound uses ALL configured MEC sites (even
    # the inactive 3rd/4th); keep this optimistic convention transparent.
    fastest = max(
        configured_fastest_cpu,
        max(u.local_cpu_ghz for u in instance.uavs.values()),
    )
    individual_lb = [
        min(
            distance(instance.depot_xy, (t.x, t.y)) / u.speed_mps
            for u in instance.uavs.values()
        ) + t.collect_s + t.workload_gcycles / fastest
        for t in instance.tasks.values()
    ]
    violation_ratios = [
        lb / deadline
        for lb, deadline in zip(individual_lb, deadlines)
    ]
    return {
        "mean_workload_gcycles": mean(workloads),
        "total_workload_gcycles": sum(workloads),
        "mean_cycles_per_bit": mean(t.cycles_per_bit for t in instance.tasks.values()),
        "mean_deadline_s": mean(deadlines),
        "min_deadline_s": min(deadlines),
        "max_deadline_s": max(deadlines),
        "individual_optimistic_lb_fastest_cpu_ghz": fastest,
        "n_individual_optimistic_deadline_impossible": sum(
            lb > t.deadline_s + 1e-9
            for lb, t in zip(individual_lb, instance.tasks.values())
        ),
        "max_optimistic_lb_over_deadline": max(violation_ratios),
        "mean_optimistic_lb_over_deadline": mean(violation_ratios),
        "mec_bandwidth_mhz": {
            mec_id: mec.bandwidth_mhz
            for mec_id, mec in instance.mecs.items()
        },
        "mec_cpu_ghz": {
            mec_id: mec.cpu_ghz
            for mec_id, mec in instance.mecs.items()
        },
        "n_tasks": len(instance.tasks),
        "n_active_mecs_configured": len(instance.mecs),
    }


def physical_metrics(instance: Instance, solution, audited) -> dict | None:
    """Return physics only when BOTH saved and reconstructed Stage-2 pass."""
    stage1, stage2 = audited["stage1"], audited["stage2"]
    if not (stage1["qualified"] and stage2["qualified"]):
        return None
    stages = stage2["audit"]
    if not all(
        stages[which]["complete"] and stages[which]["passed"]
        for which in ("saved", "reconstructed")
    ):
        return None
    saved_values = stage2["values"]
    if saved_values is None:
        return None
    # Use earliest timeline from same Stage-2 resource allocation, not the
    # saved arbitrary/slack times. Report saved/reconstructed checks separately.
    reconstructed = stages["reconstructed"]
    m = reconstructed["metrics"]
    e = m["energy_components_j"]
    energy_total = m["energy_j"]
    bandwidth_by_mec = {key: 0.0 for key in instance.mecs}
    for raw_key, value in saved_values["bandwidth_mhz"].items():
        pair = ast.literal_eval(raw_key)
        bandwidth_by_mec[pair[1]] += float(value)
    bw_util = {
        mec_id: bandwidth_by_mec[mec_id] / instance.mecs[mec_id].bandwidth_mhz
        for mec_id in instance.mecs
    }
    task_delay = reconstructed["timeline"]["task_delay_s"]
    deadline_slack = [
        instance.tasks[t].deadline_s - delay
        for t, delay in task_delay.items()
    ]
    flight_collection = e["flight_j"] + e["collection_j"]
    upload = e["upload_hover_j"] + e["transmit_j"]
    cpu_util = m["cpu_occupation_by_mec"]
    return {
        "stage2_physical_energy_j": energy_total,
        "energy_components_j": e,
        "flight_collection_share_pct": 100.0 * flight_collection / energy_total,
        "upload_energy_share_pct": 100.0 * upload / energy_total,
        "local_compute_energy_share_pct": 100.0 * e["local_compute_j"] / energy_total,
        "offloaded_tasks": m["offloaded_tasks"],
        "offload_ratio": m["offload_ratio"],
        "contact_visits": m["contacts"],
        "total_route_distance_m": m["total_distance_m"],
        "mean_delay_s": m["mean_delay_s"],
        "p95_delay_s": m["p95_delay_s"],
        "minimum_deadline_slack_s": m["min_deadline_slack_s"],
        "mean_deadline_slack_s": mean(deadline_slack),
        "p10_deadline_slack_s": float(np.quantile(deadline_slack, .10)),
        "mec_bandwidth_occupation": bw_util,
        "mec_cpu_occupation": cpu_util,
        "max_mec_bandwidth_occupation": max(bw_util.values(), default=0),
        "max_mec_cpu_occupation": max(cpu_util.values(), default=0),
        "active_UAV_MEC_resource_pairs": len(saved_values["bandwidth_mhz"]),
        "stage1_and_stage2_energy_delta_j": energy_total - float(
            audited["resources"].energy_stage1_j
        ),
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict]:
    """Summaries respect qualification, scenario nesting, and factor pairs."""
    by_key = {
        (x["profile"], x["seed"], x["method"]): x
        for x in rows if x.get("method") in METHODS
    }
    output = []
    for profile in PROFILES:
        for method in METHODS:
            sample = [
                row for row in rows
                if row.get("profile") == profile and row.get("method") == method
            ]
            valid = [x for x in sample if x.get("both_qualified")]
            components = {
                key: mean(x["physical"]["energy_components_j"][key] for x in valid)
                if valid else None
                for key in (
                    "flight_j", "collection_j", "upload_hover_j",
                    "transmit_j", "local_compute_j"
                )
            }
            pairs = []
            for row in valid:
                baseline = by_key.get(("baseline", row["seed"], method))
                if baseline and baseline.get("both_qualified"):
                    # One scenario per Actions job. Seed matched within scenario.
                    pairs.append(row["energy_stage1_j"] - baseline["energy_stage1_j"])
            def ave(field: str):
                return mean(x["physical"][field] for x in valid) if valid else None
            output.append({
                "profile": profile,
                "factor": PROFILES[profile][0],
                "factor_multiplier": PROFILES[profile][1],
                "method": method,
                "attempts": len(sample),
                "stage1_qualified": sum(x.get("stage1_qualified", False) for x in sample),
                "both_qualified": len(valid),
                "exceptions": sum(x.get("status") == "error" for x in sample),
                "failure_stages": dict(Counter(
                    x.get("failure_stage", "unknown") for x in sample
                    if not x.get("both_qualified")
                )),
                "mean_energy_j_conditional": (
                    mean(x["energy_stage1_j"] for x in valid) if valid else None
                ),
                "mean_energy_components_j_conditional": components,
                "mean_offload_ratio_conditional": ave("offload_ratio"),
                "mean_contact_visits_conditional": ave("contact_visits"),
                "mean_flight_collection_share_pct_conditional": ave(
                    "flight_collection_share_pct"
                ),
                "mean_upload_energy_share_pct_conditional": ave(
                    "upload_energy_share_pct"
                ),
                "mean_local_compute_share_pct_conditional": ave(
                    "local_compute_energy_share_pct"
                ),
                "mean_mec_bw_max_util_conditional": ave(
                    "max_mec_bandwidth_occupation"
                ),
                "mean_mec_cpu_max_util_conditional": ave(
                    "max_mec_cpu_occupation"
                ),
                "mean_deadline_slack_s_conditional": ave(
                    "mean_deadline_slack_s"
                ),
                "mean_route_distance_m_conditional": ave("total_route_distance_m"),
                "mean_full_runtime_s": (
                    mean(x["timing"]["total_with_audit_s"] for x in sample
                         if x.get("status") == "ok")
                    if any(x.get("status") == "ok" for x in sample) else None
                ),
                "paired_with_baseline_both_qualified": len(pairs),
                "mean_delta_energy_vs_baseline_j_paired": mean(pairs) if pairs else None,
                "positive_delta_cases": sum(d > 1.0 for d in pairs),
                "negative_delta_cases": sum(d < -1.0 for d in pairs),
            })
    return output


def run_block(args) -> dict:
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing experiment {args.output}")
    selected = [x.strip() for x in args.profiles.split(",") if x.strip()]
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("Profile selection must be nonempty and unique")
    if any(p not in PROFILES for p in selected):
        raise ValueError(f"Unknown profiles {selected}")
    if "baseline" not in selected:
        raise ValueError("Include baseline in every independent scenario block")
    if args.iterations <= 0 or args.elite_rounds <= 0:
        raise ValueError("Positive iteration/round counts required")
    seeds = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Algorithm seeds must be nonempty and unique")

    cfg = load_paper_scale_config(args.config)
    base = build_paper_scale_instance(
        cfg, num_tasks=args.tasks, num_uavs=5,
        num_mecs=2, scenario_seed=args.scenario,
    )
    base_sha = content_hash(base)
    baseline_geometry_sha = shared_task_geometry_hash(base)
    base_original_sha = content_hash(base)

    payload = {
        "complete": False,
        "protocol": {
            "id": "uav_mec_one_factor_coupling_sensitivity_v1",
            "source_branch": "develop (frozen algorithm, experiment-only changes)",
            "method": list(METHODS),
            "task_scale": args.tasks,
            "independent_scenario_seed": args.scenario,
            "algorithm_seeds": seeds,
            "parameters": {
                p: {"factor": PROFILES[p][0], "multiplier": PROFILES[p][1]}
                for p in selected
            },
            "profiles_to_run": selected,
            "iteration_budget": args.iterations,
            "elite_round_budget": args.elite_rounds,
            "five_uavs_two_mecs": True,
            "fixed_stochastic_seed_within_profile": True,
            "paired_instance_geometry_hash": baseline_geometry_sha,
            "same_stage1_stage2_audit": True,
            "independent_unit": "scenario; algorithm seeds nested",
            "energy_ranking": "conditional on BOTH Stage-1 and Stage-2 qualified",
            "warning": "B/ESI share fixed iterations; ESI has ADDITIONAL CVX elite time, NOT equal-time benchmark",
            "baseline_config_sha256": hashlib.sha256(
                Path(args.config).read_bytes()
            ).hexdigest(),
            "source_hashes": current_source_hashes(Path(__file__)),
            "provenance": provenance(),
            "audit_tolerances": AuditTolerance(),
        },
        "base_instance": base,
        "base_instance_sha256": base_sha,
        "base_geometry_sha256": baseline_geometry_sha,
        "profiles": {},
        "rows": [],
    }
    write_json(args.output, payload)

    errors = []
    for profile in selected:
        kind, scale = PROFILES[profile]
        instance = make_profile(base, profile)
        if shared_task_geometry_hash(instance) != baseline_geometry_sha:
            raise RuntimeError(f"Paired task/contact geometry changed for {profile}")
        if content_hash(base) != base_original_sha:
            raise RuntimeError("Base instance mutated during profile construction")
        description = describe_instance(
            instance,
            configured_fastest_cpu=max(spec.cpu_ghz for spec in cfg.mec_sites),
        )
        payload["profiles"][profile] = {
            "factor": kind,
            "multiplier": scale,
            "instance_sha256": content_hash(instance),
            "geometry_sha256": shared_task_geometry_hash(instance),
            "instance": instance,
            "instance_summary": description,
        }
        write_json(args.output, payload)
        print(
            f"SENSITIVITY_INSTANCE K{args.tasks} S{args.scenario} {profile}: "
            f"total_Gcycles={description['total_workload_gcycles']:.2f} "
            f"mean_deadline_s={description['mean_deadline_s']:.2f} "
            f"n_optimistic_deadline_impossible="
            f"{description['n_individual_optimistic_deadline_impossible']}",
            flush=True,
        )
        for seed in seeds:
            elapsed = None
            initial = None
            try:
                start = perf_counter()
                initial = build_mec_assisted_initial_solution(
                    instance,
                    base_solution=build_greedy_initial_solution(instance),
                )
                init_s = perf_counter() - start
                initial_sha = content_hash(initial)
                evaluator = ScreenedProxyObjectiveEvaluator()
                oracle = Stage1CVXObjectiveOracle()
                started = perf_counter()
                hybrid = run_uav_mec_hybrid_alns(
                    instance,
                    initial_solution=deepcopy(initial),
                    config=UavMecALNSConfig(
                        iterations=args.iterations, seed=seed,
                        enable_problem_operators=False,
                    ),
                    evaluator=evaluator,
                    elite_oracle=oracle,
                    elite_rounds=args.elite_rounds,
                )
                full_search_s = perf_counter() - started
                common = {
                    "initial_sha256": initial_sha,
                    "exploration_solution_sha256": content_hash(
                        hybrid.exploration.best_solution
                    ),
                    "hybrid_total_search_s": full_search_s,
                    "exploration_search_s": hybrid.exploration_runtime_s,
                    "elite_extra_s": hybrid.elite_phase_runtime_s,
                    "elite_oracle_cvx_calls": oracle.calls,
                    "elite_oracle_cache_hits": oracle.cache_hits,
                    "elite_stats": hybrid.elite_stats,
                    "oracle_solve_records": oracle.solve_records,
                    "exploration_stage1_status": hybrid.exploration_cvx.diagnostics.get(
                        "stage1_status", hybrid.exploration_cvx.status
                    ),
                }
                if content_hash(initial) != initial_sha:
                    raise RuntimeError("Shared initial state mutated during run")
                for method, solution, wall in (
                    ("B-ALNS", hybrid.exploration.best_solution,
                     hybrid.exploration_runtime_s),
                    ("ESI-ALNS", hybrid.best_solution, full_search_s),
                ):
                    try:
                        finished = finalize(
                            instance, solution, method=method, seed=seed,
                            initialization_s=init_s,
                            search_s=wall,
                            diagnostics=common,
                        )
                        good_stage1 = bool(finished["stage1"]["qualified"])
                        good_stage2 = bool(finished["stage2"]["qualified"])
                        both = good_stage1 and good_stage2
                        measured = physical_metrics(instance, solution, finished)
                        row = {
                            **finished,
                            "status": "ok",
                            "profile": profile,
                            "factor": kind,
                            "factor_multiplier": scale,
                            "seed": seed,
                            "tasks": args.tasks,
                            "scenario_seed": args.scenario,
                            "instance_sha256": content_hash(instance),
                            "geometry_sha256": baseline_geometry_sha,
                            "stage1_qualified": good_stage1,
                            "stage2_qualified": good_stage2,
                            "both_qualified": both,
                            "energy_stage1_j": (
                                float(finished["resources"].energy_stage1_j)
                                if good_stage1 else None
                            ),
                            "physical": measured,
                            "failure_stage": (
                                None if both else
                                ("stage1" if not good_stage1 else "stage2")
                            ),
                        }
                        payload["rows"].append(row)
                        write_json(args.output, payload)
                        print(
                            f"SENSITIVITY_RESULT K{args.tasks} S{args.scenario} "
                            f"{profile} A{seed} {method}: "
                            f"stage1={good_stage1} stage2={good_stage2} "
                            f"E={row['energy_stage1_j']} "
                            f"offload={measured['offload_ratio'] if measured else None} "
                            f"flight_share={measured['flight_collection_share_pct'] if measured else None} "
                            f"runtime_s={finished['timing']['total_with_audit_s']:.3f}",
                            flush=True,
                        )
                    except Exception as exc:
                        errors.append({
                            "profile": profile, "seed": seed,
                            "method": method,
                            "type": type(exc).__name__, "message": str(exc),
                        })
                        payload["rows"].append({
                            "status": "error", "profile": profile,
                            "seed": seed, "method": method,
                            "factor": kind, "factor_multiplier": scale,
                            "stage1_qualified": False,
                            "stage2_qualified": False, "both_qualified": False,
                            "failure_stage": "exception",
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                        })
                        write_json(args.output, payload)
            except Exception as exc:
                errors.append({
                    "profile": profile, "seed": seed,
                    "method": "pair", "type": type(exc).__name__,
                    "message": str(exc),
                })
                for method in METHODS:
                    if not any(
                        r.get("profile") == profile
                        and r.get("seed") == seed
                        and r.get("method") == method
                        for r in payload["rows"]
                    ):
                        payload["rows"].append({
                            "status": "error",
                            "profile": profile, "seed": seed, "method": method,
                            "factor": kind, "factor_multiplier": scale,
                            "stage1_qualified": False,
                            "stage2_qualified": False, "both_qualified": False,
                            "failure_stage": "exception",
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                        })
                write_json(args.output, payload)

    payload["summary"] = summarize(payload["rows"])
    payload["complete"] = True
    payload["error_count"] = len(errors)
    payload["errors"] = errors
    write_json(args.output, payload)
    expected = len(selected) * len(seeds) * len(METHODS)
    if len(payload["rows"]) != expected:
        raise RuntimeError(
            f"Missing rows: {len(payload['rows'])} instead of {expected}"
        )
    print(
        "SENSITIVITY_SUMMARY="
        + json.dumps(payload["summary"], ensure_ascii=False),
        flush=True,
    )
    if errors:
        raise RuntimeError(
            f"Unexpected algorithm/program errors (not solver nonqualification): "
            f"{errors[:3]}. All results saved before failure."
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--scenario", type=int, required=True)
    parser.add_argument("--seeds", default="111,112")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--elite-rounds", type=int, default=2)
    parser.add_argument("--profiles", default=",".join(PROFILES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_block(args)


if __name__ == "__main__":
    main()
