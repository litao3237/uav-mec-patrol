"""Aggregate audited one-factor UAV-MEC runs by independent scenario.

Nested ALNS random seeds are averaged *within* each scenario. Optional
bootstrap resamples scenarios, never individual algorithm seeds. Failed
strict Stage-1/Stage-2 results and missing jobs remain visible rather than
being imputed with feasible energy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from run_model_sensitivity import METHODS, PROFILES


MEASURES = {
    "energy_stage1_j": ("energy_stage1_j",),
    "offload_ratio": ("physical", "offload_ratio"),
    "flight_collection_share_pct": ("physical", "flight_collection_share_pct"),
    "upload_energy_share_pct": ("physical", "upload_energy_share_pct"),
    "local_compute_energy_share_pct": ("physical", "local_compute_energy_share_pct"),
    "total_route_distance_m": ("physical", "total_route_distance_m"),
    "contacts": ("physical", "contact_visits"),
    "mean_deadline_slack_s": ("physical", "mean_deadline_slack_s"),
    "max_mec_bw_occupation": ("physical", "max_mec_bandwidth_occupation"),
    "max_mec_cpu_occupation": ("physical", "max_mec_cpu_occupation"),
}
BASELINE = "baseline"


def lookup(entry, keypath):
    v = entry
    for k in keypath:
        if v is None:
            return None
        v = v.get(k)
    return v


def scenario_equal_effect(values: dict[int, list[float]], *, seed: int):
    grouped = [mean(values[k]) for k in sorted(values) if values[k]]
    if not grouped:
        return None, None
    central = mean(grouped)
    if len(grouped) < 3:
        return central, None
    rng = np.random.default_rng(seed)
    draws = rng.choice(grouped, size=(10000, len(grouped)), replace=True)
    bounds = np.quantile(draws.mean(axis=1), [0.025, 0.975]).tolist()
    return central, bounds


def aggregate(blocks: list[dict], *, expected_tasks: list[int],
              expected_scenarios: list[int]) -> dict:
    keys: set[tuple] = set()
    all_rows = []
    instances = {}
    incomplete = []
    missing = []
    for payload in blocks:
        p = payload["protocol"]
        key = (int(p["task_scale"]), int(p["independent_scenario_seed"]))
        if key in keys:
            raise ValueError(f"Duplicate (K,scenario) output {key}")
        keys.add(key)
        if not payload.get("complete"):
            incomplete.append(key)
        for profile, record in payload.get("profiles", {}).items():
            instances[(key[0], key[1], profile)] = record["instance_summary"]
        for row in payload.get("rows", []):
            item = {
                "tasks": key[0], "scenario": key[1], **row,
            }
            all_rows.append(item)
    for k in expected_tasks:
        for s in expected_scenarios:
            if (k, s) not in keys:
                missing.append((k, s))

    indexed = {
        (r["tasks"], r["scenario"], r["seed"], r["profile"], r["method"]): r
        for r in all_rows
    }
    output = []
    for k in expected_tasks:
        for profile in PROFILES:
            for method in METHODS:
                sample = [
                    row for row in all_rows
                    if row["tasks"] == k and row["profile"] == profile
                    and row["method"] == method
                ]
                valid = [r for r in sample if r.get("both_qualified")]
                entry: dict[str, Any] = {
                    "tasks": k,
                    "profile": profile,
                    "factor": PROFILES[profile][0],
                    "multiplier": PROFILES[profile][1],
                    "method": method,
                    "attempted": len(sample),
                    "stage1_qualified": sum(
                        bool(r.get("stage1_qualified")) for r in sample
                    ),
                    "both_qualified": len(valid),
                    "failures_by_stage": dict(Counter(
                        r.get("failure_stage", "other")
                        for r in sample if not r.get("both_qualified")
                    )),
                    "independent_scenarios_attempted": len({
                        r["scenario"] for r in sample
                    }),
                    "independent_scenarios_both_qualified": len({
                        r["scenario"] for r in valid
                    }),
                    "paired_with_baseline_valid": 0,
                    "paired_with_baseline_scenarios": 0,
                }
                by_measure = {name: defaultdict(list) for name in MEASURES}
                pairs_by_measure = {name: defaultdict(list) for name in MEASURES}
                for r in valid:
                    baseline = indexed.get(
                        (k, r["scenario"], r["seed"], BASELINE, method)
                    )
                    for name, path in MEASURES.items():
                        v = lookup(r, path)
                        if v is not None:
                            by_measure[name][r["scenario"]].append(float(v))
                        if baseline and baseline.get("both_qualified"):
                            u = lookup(baseline, path)
                            if v is not None and u is not None:
                                pairs_by_measure[name][r["scenario"]].append(
                                    float(v) - float(u)
                                )
                # Pair coverage measures do NOT infer validation from energies
                paired = [
                    r for r in valid
                    if indexed.get(
                        (k, r["scenario"], r["seed"], BASELINE, method), {}
                    ).get("both_qualified")
                ]
                entry["paired_with_baseline_valid"] = len(paired)
                entry["paired_with_baseline_scenarios"] = len({
                    r["scenario"] for r in paired
                })
                for j, name in enumerate(MEASURES):
                    absolute, _ = scenario_equal_effect(
                        by_measure[name], seed=31000 + k + j
                    )
                    delta, ci = scenario_equal_effect(
                        pairs_by_measure[name], seed=41000 + k + j
                    )
                    entry[f"qualified_mean_{name}"] = absolute
                    entry[f"paired_delta_{name}"] = delta
                    if name == "energy_stage1_j":
                        entry["paired_delta_energy_boot95_scenario"] = ci
                desc = [
                    instances[(k, s, profile)]
                    for s in expected_scenarios
                    if (k, s, profile) in instances
                ]
                entry["mean_instance_compute_gcycles"] = (
                    mean(x["total_workload_gcycles"] for x in desc)
                    if desc else None
                )
                entry["mean_actual_deadline_s"] = (
                    mean(x["mean_deadline_s"] for x in desc)
                    if desc else None
                )
                entry["optimistically_impossible_task_count_total"] = sum(
                    x["n_individual_optimistic_deadline_impossible"]
                    for x in desc
                )
                entry["n_instance_scenarios"] = len(desc)
                output.append(entry)

    return {
        "study": "one_factor_coupling_sensitivity_v1",
        "independent_unit": "scenario (algorithm seed nested)",
        "expected_blocks": len(expected_tasks) * len(expected_scenarios),
        "received_blocks": len(keys),
        "missing_blocks": [list(key) for key in missing],
        "incomplete_blocks": [list(key) for key in incomplete],
        "run_errors": [
            (p["protocol"]["task_scale"],
             p["protocol"]["independent_scenario_seed"],
             p.get("errors", []))
            for p in blocks if p.get("error_count")
        ],
        "total_method_records": len(all_rows),
        "rows": output,
    }


def report_markdown(aggregate_data: dict) -> str:
    d = aggregate_data
    lines = [
        "# UAV-MEC parameter sensitivity — diagnostic report",
        "",
        "All methods are frozen from \`develop\`; experiments vary one",
        "physical factor at a time. **Not an equal-runtime algorithm comparison.**",
        "Only results passing both Stage-1 and Stage-2 independent residual",
        "audits enter the conditional physical/energy means.",
        "",
        f"Complete blocks: {d['received_blocks']}/{d['expected_blocks']}; "
        f"records: {d['total_method_records']}; "
        f"missing: {d['missing_blocks']}; incomplete: {d['incomplete_blocks']}",
        "",
        "Positive Δ energy means the changed parameter increased UAV energy.",
        "Per-factor Δ is paired against the baseline using the *same*",
        "scenario, algorithm seed and method. Algorithm seeds are averaged",
        "within scenario; scenario means are equally weighted.",
        "",
        "| K | Factor | Method | Both qualified / attempted | Paired | ΔEnergy vs base (J) | Offload ratio | Flight+collection % | Max MEC BW util | Deadline slack (s) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(v, digits=3):
        return "—" if v is None else f"{v:.{digits}f}"
    for row in d["rows"]:
        lines.append(
            f"| {row['tasks']} | {row['profile']} | {row['method']} | "
            f"{row['both_qualified']}/{row['attempted']} | "
            f"{row['paired_with_baseline_valid']} | "
            f"{fmt(row['paired_delta_energy_stage1_j'],1)} | "
            f"{fmt(row['qualified_mean_offload_ratio'],3)} | "
            f"{fmt(row['qualified_mean_flight_collection_share_pct'],2)} | "
            f"{fmt(row['qualified_mean_max_mec_bw_occupation'],3)} | "
            f"{fmt(row['qualified_mean_mean_deadline_slack_s'],2)} |"
        )
    lines += [
        "",
        "## Interpretation rules",
        "",
        "- Differences are conditional on strict feasibility. A factor that",
        "  changes the proportion of feasible runs cannot be ranked using",
        "  the survivor-only conditional energy mean alone.",
        "- Task deadlines are scaled AFTER generation, so the generator's",
        "  optimistic deadline floor is not silently reapplied. The number",
        "  of individually optimistic-impossible tasks is reported.",
        "- Factors do not resample coordinates, data sizes or contact",
        "  geometry. All variant instances are generated from the same",
        "  original sampled scenario and can be compared as paired workloads.",
        "- All Stage-1 / Stage-2 solver failures, numerical nonqualification",
        "  and algorithm exceptions remain part of coverage.",
        "- Original ESI receives extra CVX search compared with B-ALNS.",
        "  Do not interpret the difference between methods as a fair-time win.",
        "- Four independent scenarios per task scale remain exploratory.",
        "  Bootstrap intervals resample independent scenarios only; never",
        "  nested algorithm random seeds.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--tasks", default="50,80")
    ap.add_argument("--scenarios", default="61,62,63,64")
    args = ap.parse_args()
    paths = sorted(args.input_dir.rglob("sensitivity-K*_S*.json"))
    if not paths:
        raise FileNotFoundError(f"No scenario results under {args.input_dir}")
    blocks = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    summary = aggregate(
        blocks,
        expected_tasks=[int(x) for x in args.tasks.split(",")],
        expected_scenarios=[int(x) for x in args.scenarios.split(",")],
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(
        report_markdown(summary),
        encoding="utf-8",
    )
    rows = summary["rows"]
    with (args.output_dir / "summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            })
    brief = {
        "blocks": summary["received_blocks"],
        "expected": summary["expected_blocks"],
        "failed": summary["run_errors"],
        "qualifications": [
            {
                key: row[key] for key in (
                    "tasks", "profile", "method", "both_qualified",
                    "attempted", "paired_delta_energy_stage1_j",
                    "qualified_mean_offload_ratio",
                    "qualified_mean_flight_collection_share_pct",
                )
            }
            for row in rows
        ],
    }
    print("SENSITIVITY_AGGREGATE=" + json.dumps(brief, ensure_ascii=False), flush=True)
    if summary["missing_blocks"] or summary["incomplete_blocks"] or summary["run_errors"]:
        raise RuntimeError("Incomplete sensitivity matrix; partial summary preserved")


if __name__ == "__main__":
    main()
