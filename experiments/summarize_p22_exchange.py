"""Aggregate P22 deadline-critical cross-UAV exchange vs matched random controls."""
from __future__ import annotations
import argparse
from statistics import mean
import json
from pathlib import Path

ARMS = ("deadline_critical_pairs", "random_cross_uav_pairs")
SCENES = (89, 91, 93, 95, 96)


def summarize(directory: Path, output: Path):
    files = sorted(directory.rglob("p22-exchange-S*.json"))
    source_rows = []
    scene_ids = []
    errors = []
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        scene_ids.append(doc["protocol"]["scene"])
        if not doc["complete"]:
            errors.append(f"not complete {f.name}")
        errors.extend(doc.get("errors", []))
        source_rows.extend(doc["rows"])

    if sorted(scene_ids) != list(SCENES) or len(source_rows) != 6:
        errors.append(f"expected five inspected scenes and six B sources: {scene_ids}/{len(source_rows)}")
    control = {
        "already_seen_original_K80_scenarios": True,
        "new_unseen_holdout": False,
        "matched_real_MEC_rebuilder_count_not_wall_time": True,
        "independent_spatial_scenes": len(set(scene_ids)),
        "frozen_B_sources": len(source_rows),
        "strict_original_B": sum(
            bool(r["original_strict"]["Stage1_and_Stage2_strict"])
            for r in source_rows
        ),
        "methods": {},
        "paired_methods": [],
        "errors": errors,
    }
    for arm in ARMS:
        methods = [r["policies"][arm] for r in source_rows]
        trial_counts = [len(item["trials"]) for item in methods]
        budget_counts = [r["equal_builder_trials_per_policy"] for r in source_rows]
        if trial_counts != budget_counts:
            errors.append(f"not matched same MEC rebuild quota for {arm}")
        methods_complete = all(
            all("after" in x for x in item["trials"])
            for item in methods
        )
        if not methods_complete:
            errors.append(f"missing legal full reconstruction in {arm}")
        outcomes = [bool(x["strict_posthoc"]["Stage1_and_Stage2_strict"])
                    for x in methods]
        improvements = [
            r["original_queue"]["worst_task_deadline_excess_s"] -
            r["policies"][arm]["best"]["after"]["worst_task_deadline_excess_s"]
            for r in source_rows
        ]
        control["methods"][arm] = {
            "attempts": len(source_rows),
            "actual_complete_full_MEC_rebuilder_calls": sum(trial_counts),
            "best_queue_necessary_pass": sum(
                bool(x["best"]["after"]["queue_necessary_pass"])
                for x in methods
            ),
            "best_strict_Stage1_and_Stage2": sum(outcomes),
            "new_strict_vs_original": [
                {"s": r["scene"], "profile": r["profile"], "seed": r["seed"]}
                for r in source_rows if (
                    r["policies"][arm]["strict_posthoc"]["Stage1_and_Stage2_strict"]
                    and not r["original_strict"]["Stage1_and_Stage2_strict"]
                )
            ],
            "lost_original_strict": [
                {"s": r["scene"], "profile": r["profile"], "seed": r["seed"]}
                for r in source_rows if (
                    r["original_strict"]["Stage1_and_Stage2_strict"]
                    and not r["policies"][arm]["strict_posthoc"]["Stage1_and_Stage2_strict"]
                )
            ],
            "cases_with_lower_worst_deadline_excess": sum(
                x > 1e-4 for x in improvements
            ),
            "mean_worst_deadline_excess_reduction_s": mean(improvements),
            "total_full_MEC_rebuild_wall_s": sum(
                sum(entry["complete_rebuild_wall_s"] for entry in x["trials"])
                for x in methods
            ),
        }
    control["paired_methods"] = [
        {
            "scene": r["scene"], "profile": r["profile"], "seed": r["seed"],
            "original_queue": r["original_queue"]["queue_necessary_pass"],
            "targeted_queue": r["policies"][ARMS[0]]["best"]["after"]["queue_necessary_pass"],
            "random_queue": r["policies"][ARMS[1]]["best"]["after"]["queue_necessary_pass"],
            "targeted_strict": r["policies"][ARMS[0]]["strict_posthoc"]["Stage1_and_Stage2_strict"],
            "random_strict": r["policies"][ARMS[1]]["strict_posthoc"]["Stage1_and_Stage2_strict"],
            "targeted_worst_late_s": r["policies"][ARMS[0]]["best"]["after"]["worst_task_deadline_excess_s"],
            "random_worst_late_s": r["policies"][ARMS[1]]["best"]["after"]["worst_task_deadline_excess_s"],
        }
        for r in source_rows
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(control, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("P22_EXCHANGE_AGGREGATE=" + json.dumps(control, ensure_ascii=False), flush=True)
    if errors:
        raise RuntimeError("P22 incomplete: " + str(errors[:3]))
    return control


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--collected", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    summarize(args.collected, args.output)
