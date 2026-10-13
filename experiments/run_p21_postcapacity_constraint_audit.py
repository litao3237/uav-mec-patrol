"""P21 retrospective mechanism audit of exact P20 frozen-capacity outcomes.

Read immutable archived P20 numerical results. Do NOT rerun the optimizer or
claim that correlated candidates / nested seeds are independent evidence.
Isolate deadline, patrol-cycle, and mean-delay optimistic necessary-bound
violations after 4x MEC CPU+bandwidth. The bounds are necessary, not sufficient.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

SCENES = (89, 91, 93, 95, 96)
CANDIDATES = ("B_frozen", "cheapest_P19", "regret2_P19")
FACTORS = ("unchanged", "CPU_x2", "BW_x2", "CPU_BW_x2", "CPU_BW_x4")
EPS = 1e-4


def _vector(q):
    return {
        "late_task_count": int(q["late_task_count"]),
        "worst_task_deadline_excess_s": float(q["worst_task_deadline_excess_s"]),
        "total_task_deadline_excess_s": float(q["total_task_deadline_excess_s"]),
        "average_delay_lb_excess_s": float(q["average_delay_lb_excess_s"]),
        "max_cycle_lb_excess_s": float(q["max_cycle_lb_excess_s"]),
        "total_normalized_all_constraint_excess": float(
            q["total_normalized_all_constraint_excess"]
        ),
        "queue_reason_count": int(q["queue_reason_count"]),
        "MEC_offloaded_count": int(q["MEC_offloaded_count"]),
        "MEC_contact_count": int(q["MEC_contact_count"]),
        "route_total_distance_m": float(q["route_total_distance_m"]),
    }


def audit(collected: Path, output: Path):
    files = sorted(collected.rglob("p20-capacity-S*.json"))
    all_rows = []
    errors = []
    seen_scenes = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        p = d["protocol"]
        seen_scenes.append(int(p["scene"]))
        if not d["complete"] or d["errors"]:
            errors.append(f"incomplete or errors: {f.name}")
        if p.get("id") != "P20_P19_exact_frozen_D_resource_capacity_factorial_v1":
            errors.append(f"unexpected source protocol {f.name}")
        all_rows.extend(d["rows"])

    if sorted(seen_scenes) != list(SCENES) or len(all_rows) != 6:
        errors.append("missing or duplicate P20 original scenario/case archives")

    samples = []
    for r in all_rows:
        for candidate in CANDIDATES:
            record = r["methods"][candidate]
            capacities = record["capacities"]
            if tuple(capacities) != FACTORS:
                errors.append(f"missing capacity factor {r['scene']} {candidate}")
            if len({v["fixed_D_sha"] for v in capacities.values()}) != 1:
                errors.append(f"physical discrete route or contact changed {r['scene']}")
            b = capacities["unchanged"]
            x4 = capacities["CPU_BW_x4"]
            old = _vector(b["queue"])
            stretched = _vector(x4["queue"])
            key = {
                "scene": r["scene"],
                "profile": r["profile"],
                "seed": r["seed"],
                "candidate": candidate,
                "frozen_D_sha": record["fixed_D_sha"],
            }
            samples.append({
                **key,
                "strict_by_capacity": {
                    f: bool(capacities[f]["strict_both"]) for f in FACTORS
                },
                "queue_pass_by_capacity": {
                    f: bool(capacities[f]["queue"]["queue_necessary_pass"])
                    for f in FACTORS
                },
                "stage1_status_by_capacity": {
                    f: capacities[f]["strict"]["Stage1_solver_status"]
                    for f in FACTORS
                },
                "unchanged_queue": old,
                "fourfold_queue": stretched,
                "fourfold_excess_delta": {
                    k: round(stretched[k] - old[k], 6)
                    for k in ("total_task_deadline_excess_s",
                              "average_delay_lb_excess_s",
                              "max_cycle_lb_excess_s",
                              "total_normalized_all_constraint_excess")
                },
                "fourfold_violations": {
                    "task_deadlines": stretched["late_task_count"] > 0,
                    "mean_delay": stretched["average_delay_lb_excess_s"] > EPS,
                    "patrol_cycle": stretched["max_cycle_lb_excess_s"] > EPS,
                },
            })
    by_kind = {}
    for candidate in CANDIDATES:
        entries = [x for x in samples if x["candidate"] == candidate]
        hard = [
            x for x in entries
            if not x["queue_pass_by_capacity"]["CPU_BW_x4"]
        ]
        failures = [
            x for x in entries
            if not x["strict_by_capacity"]["CPU_BW_x4"]
        ]
        by_kind[candidate] = {
            "n": len(entries),
            "unchanged_strict": sum(x["strict_by_capacity"]["unchanged"] for x in entries),
            "fourfold_strict": sum(x["strict_by_capacity"]["CPU_BW_x4"] for x in entries),
            "fourfold_queue_necessary_fail": len(hard),
            "fourfold_strict_fail": len(failures),
            "hard_still_exceed_deadline": sum(
                x["fourfold_violations"]["task_deadlines"] for x in hard
            ),
            "hard_still_exceed_mean_delay": sum(
                x["fourfold_violations"]["mean_delay"] for x in hard
            ),
            "hard_still_exceed_patrol_cycle": sum(
                x["fourfold_violations"]["patrol_cycle"] for x in hard
            ),
            "fourfold_queue_reason_count": Counter(
                x["fourfold_queue"]["queue_reason_count"] for x in hard
            ),
            "persistent_original_physical_sources": [
                {"scene": x["scene"], "profile": x["profile"], "seed": x["seed"]}
                for x in hard
            ],
        }

    # Paired changes when repair modifies the original exact B structure.
    paired = []
    for r in all_rows:
        sub = {
            x["candidate"]: x for x in samples
            if (x["scene"], x["profile"], x["seed"])
            == (r["scene"], r["profile"], r["seed"])
        }
        baseline = sub["B_frozen"]["unchanged_queue"]
        for name in CANDIDATES[1:]:
            updated = sub[name]["unchanged_queue"]
            paired.append({
                "scene": r["scene"], "profile": r["profile"], "seed": r["seed"],
                "repair": name,
                "changed_D": (
                    sub[name]["frozen_D_sha"] != sub["B_frozen"]["frozen_D_sha"]
                ),
                "route_distance_delta_m": round(
                    updated["route_total_distance_m"] -
                    baseline["route_total_distance_m"], 4
                ),
                "worst_deadline_excess_delta_s": round(
                    updated["worst_task_deadline_excess_s"] -
                    baseline["worst_task_deadline_excess_s"], 4
                ),
                "reason_count_delta": (
                    updated["queue_reason_count"] -
                    baseline["queue_reason_count"]
                ),
            })

    report = {
        "source_P20_run": 38368976798,
        "independent_scene_count": len(set(seen_scenes)),
        "frozen_original_source_cases": len(all_rows),
        "physically_correlated_repeated_D_structures": len(samples),
        "no_new_search_no_physical_model_modification": True,
        "optimistic_necessary_gate_not_proof_of_global_impossibility": True,
        "by_candidate": by_kind,
        "paired_changes_vs_original_B": paired,
        "complete_case_diagnostics": samples,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    concise = {k: v for k, v in report.items()
               if k not in ("complete_case_diagnostics", "paired_changes_vs_original_B")}
    print("P21_ROOT_CONSTRAINT_AGGREGATE=" +
          json.dumps(concise, ensure_ascii=False, default=dict), flush=True)
    print("P21_PAIRED_REPAIR_PERTURBATIONS=" +
          json.dumps(paired, ensure_ascii=False), flush=True)
    if errors:
        raise RuntimeError("P21 source attribution incomplete: " + str(errors[:3]))
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--collected", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    audit(args.collected, args.output)
