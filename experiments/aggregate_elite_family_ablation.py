from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from typing import Any


def _load_rows(input_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result file: {path}")
        rows.extend(payload.get("rows", []))
        experiments.append(payload.get("experiment", {}))
    if not rows:
        raise ValueError(f"No result JSON files found in {input_dir}")
    return rows, experiments


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    keys = sorted({(row["K"], row["E"], row["profile"]) for row in rows})
    for k, e, profile in keys:
        subset = [
            row
            for row in rows
            if row["K"] == k
            and row["E"] == e
            and row["profile"] == profile
        ]
        strict = [row for row in subset if row["strict_pair"]]
        gains = [
            float(row["gain_pct"])
            for row in strict
            if row["gain_pct"] is not None
        ]
        groups.append(
            {
                "K": k,
                "E": e,
                "profile": profile,
                "runs": len(subset),
                "strict_pairs": len(strict),
                "strict_pair_rate": len(strict) / len(subset),
                "improved_runs": sum(gain > 1e-9 for gain in gains),
                "unchanged_runs": sum(abs(gain) <= 1e-9 for gain in gains),
                "mean_gain_pct": mean(gains) if gains else None,
                "median_gain_pct": median(gains) if gains else None,
                "mean_elite_cvx_calls": mean(
                    row["elite_cvx_calls"] for row in subset
                ),
                "mean_elite_runtime_s": mean(
                    row["elite_runtime_s"] for row in subset
                ),
            }
        )
    return groups


def _paired(
    rows: list[dict[str, Any]],
    *,
    ablation_profile: str,
) -> list[dict[str, Any]]:
    paired: list[dict[str, Any]] = []
    keys = sorted(
        {
            (
                row["K"],
                row["E"],
                row["scenario_seed"],
                row["algorithm_seed"],
            )
            for row in rows
        }
    )
    for k, e, scenario_seed, algorithm_seed in keys:
        by_profile = {
            row["profile"]: row
            for row in rows
            if row["K"] == k
            and row["E"] == e
            and row["scenario_seed"] == scenario_seed
            and row["algorithm_seed"] == algorithm_seed
        }
        full = by_profile["full"]
        ablated = by_profile[ablation_profile]
        comparable = (
            full["strict_pair"]
            and ablated["strict_pair"]
            and full["final_energy_j"] is not None
            and ablated["final_energy_j"] is not None
        )
        advantage = (
            100.0
            * (
                float(ablated["final_energy_j"])
                - float(full["final_energy_j"])
            )
            / max(1.0, abs(float(ablated["final_energy_j"])))
            if comparable
            else None
        )
        paired.append(
            {
                "K": k,
                "E": e,
                "scenario_seed": scenario_seed,
                "algorithm_seed": algorithm_seed,
                "comparable": comparable,
                "ablation_profile": ablation_profile,
                "full_energy_j": full["final_energy_j"],
                "ablated_energy_j": ablated["final_energy_j"],
                "full_advantage_pct": advantage,
            }
        )
    return paired


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate per-seed elite-family ablation JSON files."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output = Path(args.output)
    rows, experiments = _load_rows(input_dir)
    profiles = sorted({row["profile"] for row in rows})
    ablated_profiles = [
        profile for profile in profiles if profile != "full"
    ]
    if "full" not in profiles or len(ablated_profiles) != 1:
        raise ValueError(
            "Expected full plus exactly one ablated profile, got "
            f"{profiles}"
        )
    ablation_profile = ablated_profiles[0]

    aggregate = _aggregate(rows)
    paired = _paired(
        rows,
        ablation_profile=ablation_profile,
    )

    advantages = [
        float(row["full_advantage_pct"])
        for row in paired
        if row["comparable"]
        and row["full_advantage_pct"] is not None
    ]
    summary = {
        "comparable_pairs": len(advantages),
        "total_pairs": len(paired),
        "full_better": sum(value > 1e-9 for value in advantages),
        "equal": sum(abs(value) <= 1e-9 for value in advantages),
        "ablation_profile": ablation_profile,
        "ablated_better": sum(value < -1e-9 for value in advantages),
        "mean_full_advantage_pct": mean(advantages) if advantages else None,
        "median_full_advantage_pct": median(advantages) if advantages else None,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "experiments": experiments,
                "aggregate": aggregate,
                "paired": paired,
                "summary": summary,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("Aggregate")
    for group in aggregate:
        print(group)
    print("Paired summary")
    print(summary)
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
