"""Aggregate P20 fixed-D capacity diagnosis; preserve strict numerical failures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CANDIDATES = ("B_frozen", "cheapest_P19", "regret2_P19")
FACTORS = ("unchanged", "CPU_x2", "BW_x2", "CPU_BW_x2", "CPU_BW_x4")

EXPECTED_SCENES = (89, 91, 93, 95, 96)


def summarize(collected: Path, output: Path):
    files = sorted(collected.rglob("p20-capacity-S*.json"))
    data = []
    errors = []
    seen = set()
    for path in files:
        d = json.loads(path.read_text(encoding="utf-8"))
        scene = d["protocol"]["scene"]
        if scene in seen:
            errors.append(f"duplicated scene {scene}")
        seen.add(scene)
        if not d.get("complete"):
            errors.append(f"incomplete scene {scene}")
        errors.extend(d.get("errors", []))
        data.extend(d["rows"])
    if sorted(seen) != list(EXPECTED_SCENES) or len(data) != 6:
        errors.append(f"expected 5 complete scenes and 6 source cases, got {seen}/{len(data)}")

    units = len(data) * len(CANDIDATES)
    res = {
        "independent_spatial_scenes": len(seen),
        "already_inspected_development_scenes": True,
        "original_frozen_B_cases": len(data),
        "physical_structures_with_repeated_capacity_audits": units,
        "planned_strict_numerical_checks": units * len(FACTORS),
        "repeated_versions_not_independent_samples": True,
        "not_new_algorithm": True,
        "by_candidate": {},
        "paired_rescue": {},
        "errors": errors,
    }
    for candidate in CANDIDATES:
        blocks = []
        for row in data:
            block = row.get("methods", {}).get(candidate, {}).get("capacities")
            if block is None or set(block) != set(FACTORS):
                errors.append(f"missing {candidate} S{row['scene']} {row['profile']}")
                continue
            if any("strict" not in record for record in block.values()):
                errors.append(f"incomplete numerical check {candidate} S{row['scene']}")
                continue
            blocks.append((row, block))
        res["by_candidate"][candidate] = {
            factor: {
                "N": len(blocks),
                "queue_necessary_pass": sum(
                    bool(b[factor]["queue"]["queue_necessary_pass"])
                    for _, b in blocks
                ),
                "stage1_strict": sum(
                    bool(b[factor]["strict"]["Stage1_strict_qualified"])
                    for _, b in blocks
                ),
                "stage1_and_stage2_strict": sum(
                    bool(b[factor]["strict_both"])
                    for _, b in blocks
                ),
            }
            for factor in FACTORS
        }
        rescued = {}
        for factor in tuple(FACTORS)[1:]:
            rescued[factor] = [
                {
                    "scene": row["scene"],
                    "profile": row["profile"],
                    "seed": row["seed"],
                }
                for row, block in blocks
                if block[factor]["strict_both"]
                and not block["unchanged"]["strict_both"]
            ]
        cpu_only = []
        bw_only = []
        joint_needed = []
        joint4_needed = []
        for row, block in blocks:
            if block["unchanged"]["strict_both"]:
                continue
            x = {
                "scene": row["scene"],
                "profile": row["profile"],
                "seed": row["seed"],
            }
            cpu = block["CPU_x2"]["strict_both"]
            bw = block["BW_x2"]["strict_both"]
            joint = block["CPU_BW_x2"]["strict_both"]
            joint4 = block["CPU_BW_x4"]["strict_both"]
            if cpu and not bw:
                cpu_only.append(x)
            if bw and not cpu:
                bw_only.append(x)
            if joint and not (cpu or bw):
                joint_needed.append(x)
            if joint4 and not (cpu or bw or joint):
                joint4_needed.append(x)
        res["paired_rescue"][candidate] = {
            "rescued_vs_original_by_factor": rescued,
            "CPU_x2_success_BW_x2_failure": cpu_only,
            "BW_x2_success_CPU_x2_failure": bw_only,
            "CPU_BW_x2_synergy": joint_needed,
            "only_CPU_BW_x4": joint4_needed,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    res["errors"] = errors
    output.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("P20_CAPACITY_AGGREGATE=" + json.dumps(res, ensure_ascii=False),
          flush=True)
    if errors:
        raise RuntimeError("P20 audit incomplete: " + str(errors[:3]))
    return res


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--collected", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    summarize(args.collected, args.output)
