"""P24 retrospective paired outcomes; one source's duplicate policies are correlated."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

EXPECTED_SCENES = (89, 91, 93, 95, 96)
ARMS = ("deadline_critical_pairs", "random_cross_uav_pairs")
POLICIES = ("cpu_lb_rank", "queue_rank", "heavy_task_rank")


def aggregate(collected: Path, output: Path):
    docs = [
        json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(collected.rglob("p24-offload-S*.json"))
    ]
    errors = []
    seen = [d["protocol"]["scene"] for d in docs]
    if sorted(seen) != list(EXPECTED_SCENES):
        errors.append("Expected five previously used physical scenes")
    rows = [r for doc in docs for r in doc["rows"]]
    if len(rows) != 6:
        errors.append("Expected six frozen B profile+seed source cases")
    for doc in docs:
        if not doc.get("complete") or doc.get("errors"):
            errors.append(f"Missing complete data at S{doc['protocol']['scene']}")
    by_parent = {}
    details = []
    for parent in ARMS:
        scope = [
            (r, r["P22_parent_arm_results"][parent])
            for r in rows if parent in r["P22_parent_arm_results"]
        ]
        if len(scope) != len(rows):
            errors.append(f"Missing selected original P22 parent {parent}")
        by_parent[parent] = {
            "source_cases": len(scope),
            "strict_original_selected_parent": sum(
                bool(x["original_postswap_strict"]["Stage1_and_Stage2_strict"])
                for _, x in scope
            ),
            "candidate_count": sum(x["complete_candidate_pool_n"] for _, x in scope),
            "policies": {},
        }
        for policy in POLICIES:
            units = [
                (r, x, x["policies"][policy])
                for r, x in scope if policy in x["policies"]
            ]
            by_parent[parent]["policies"][policy] = {
                "attempts": len(units),
                "strict_posthoc_candidates_checked": sum(
                    len(v["checked"]) for _, _, v in units
                ),
                "strict_positive_source_cases": sum(
                    bool(v["strict_Stage1_and_Stage2_success"])
                    for _, _, v in units
                ),
                "new_strict_success_vs_P22_parent": [
                    {
                        "scene": r["scene"], "profile": r["profile"], "seed": r["seed"]
                    }
                    for r, x, v in units
                    if (
                        v["strict_Stage1_and_Stage2_success"]
                        and not x["original_postswap_strict"]["Stage1_and_Stage2_strict"]
                    )
                ],
                "lost_P22_parent_strict": [
                    {
                        "scene": r["scene"], "profile": r["profile"], "seed": r["seed"]
                    }
                    for r, x, v in units
                    if (
                        not v["strict_Stage1_and_Stage2_success"]
                        and x["original_postswap_strict"]["Stage1_and_Stage2_strict"]
                    )
                ],
                "selected_queue_passing": sum(
                    bool(z["queue_pass"])
                    for _, _, v in units for z in v["checked"]
                ),
                "selected_cpu_necessary_failure": sum(
                    bool(z["cpu_lb_certified_failure"])
                    for _, _, v in units for z in v["checked"]
                ),
            }

    for r in rows:
        item = {
            "scene": r["scene"], "profile": r["profile"], "seed": r["seed"],
            "parents": {},
        }
        for parent in ARMS:
            x = r["P22_parent_arm_results"][parent]
            item["parents"][parent] = {
                "base_strict": x["original_postswap_strict"]["Stage1_and_Stage2_strict"],
                "base_queue": x["original_postswap_queue_cpu"]["queue"][
                    "queue_necessary_pass"
                ],
                "base_cpu_lb": x["original_postswap_queue_cpu"]["cpu_lb"][
                    "certified_cpu_share_failure"
                ],
                "pool": x["complete_candidate_pool_n"],
                "policies": {
                    policy: [
                        {
                            "label": z["label"],
                            "queue_pass": z["queue_pass"],
                            "cpu_failure": z["cpu_lb_certified_failure"],
                            "strict": z["strict_both"],
                            "solver": z["strict"]["Stage1_solver_status"],
                        }
                        for z in x["policies"][policy]["checked"]
                    ]
                    for policy in POLICIES
                },
            }
        details.append(item)
    out = {
        "physical_independent_scenes": len(seen),
        "frozen_profile_seed_source_cases": len(rows),
        "previously_inspected_development_sources": True,
        "not_independent_arms_or_equal_wall_ALNS_benchmark": True,
        "same_candidate_pool_ranked_three_ways": True,
        "cpu_and_bandwidth_unchanged_from_original_paper": True,
        "by_parent": by_parent,
        "per_case": details,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("P24_OFFLOAD_AGGREGATE="+json.dumps(out, ensure_ascii=False), flush=True)
    if errors:
        raise RuntimeError("P24 incomplete data: "+str(errors[:3]))
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--collected", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    aggregate(a.collected, a.output)
