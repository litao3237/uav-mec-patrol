from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from typing import Any


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result: {path}")

        experiment = payload.get("experiment", {})
        num_uavs = experiment.get("uavs")
        if num_uavs is None:
            raise ValueError(f"Missing experiment.uavs in {path}")

        for row in payload.get("rows", []):
            enriched = dict(row)
            enriched["M"] = int(num_uavs)
            rows.append(enriched)

    if not rows:
        raise ValueError(f"No result rows found in {input_dir}")
    return rows


def _strict(row: dict[str, Any]) -> bool:
    return (
        row["base_stage1_status"] == "optimal"
        and row["hybrid_stage1_status"] == "optimal"
    )


def _group(rows: list[dict[str, Any]], m: int) -> dict[str, Any]:
    subset = [row for row in rows if int(row["M"]) == m]
    strict = [row for row in subset if _strict(row)]

    improvements = [
        float(row["improvement_pct"])
        for row in strict
        if row["improvement_pct"] is not None
    ]
    energies = [
        float(row["hybrid_cvx_energy_j"])
        for row in strict
        if row["hybrid_cvx_energy_j"] is not None
    ]
    base_energies = [
        float(row["base_cvx_energy_j"])
        for row in strict
        if row["base_cvx_energy_j"] is not None
    ]

    return {
        "K": int(subset[0]["K"]) if subset else None,
        "M": m,
        "E": int(subset[0]["E"]) if subset else None,
        "runs": len(subset),
        "strict_pairs": len(strict),
        "strict_pair_rate": (
            len(strict) / len(subset) if subset else 0.0
        ),
        "strict_improved_runs": sum(value > 1e-9 for value in improvements),
        "strict_unchanged_runs": sum(
            abs(value) <= 1e-9 for value in improvements
        ),
        "base_status_counts": {
            status: sum(
                row["base_stage1_status"] == status
                for row in subset
            )
            for status in sorted(
                {row["base_stage1_status"] for row in subset}
            )
        },
        "hybrid_status_counts": {
            status: sum(
                row["hybrid_stage1_status"] == status
                for row in subset
            )
            for status in sorted(
                {row["hybrid_stage1_status"] for row in subset}
            )
        },
        "mean_base_energy_j": mean(base_energies) if base_energies else None,
        "mean_hybrid_energy_j": mean(energies) if energies else None,
        "median_hybrid_energy_j": median(energies) if energies else None,
        "mean_gain_pct": mean(improvements) if improvements else None,
        "median_gain_pct": median(improvements) if improvements else None,
        "mean_offload_ratio": (
            mean(
                float(row["hybrid_solution"]["offloaded"])
                / max(1, int(row["K"]))
                for row in strict
            )
            if strict
            else None
        ),
        "mean_contacts_per_uav": (
            mean(
                float(row["hybrid_solution"]["contacts"])
                / max(1, m)
                for row in strict
            )
            if strict
            else None
        ),
        "mean_route_distance_km": (
            mean(
                float(row["hybrid_solution"]["distance_m"]) / 1000.0
                for row in strict
            )
            if strict
            else None
        ),
        "mean_active_uav_mec_pairs": (
            mean(
                float(row["hybrid_solution"]["active_pairs"])
                for row in strict
            )
            if strict
            else None
        ),
        "mean_exploration_runtime_s": (
            mean(float(row["exploration_runtime_s"]) for row in subset)
            if subset
            else None
        ),
        "mean_elite_runtime_s": (
            mean(float(row["elite_runtime_s"]) for row in subset)
            if subset
            else None
        ),
        "mean_total_runtime_s": (
            mean(float(row["total_runtime_s"]) for row in subset)
            if subset
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate M=3/5/8 UAV-count sensitivity results."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _load_rows(Path(args.input_dir))
    m_values = sorted({int(row["M"]) for row in rows})
    aggregate = [_group(rows, m) for m in m_values]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "aggregate": aggregate,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "M    runs strict rate    mean-E-J      median-E-J    "
        "mean-gain-% med-gain-% offload contacts/UAV dist-km runtime-s"
    )
    print("-" * 118)
    for group in aggregate:
        def fmt(value: float | None, digits: int = 3) -> str:
            return "-" if value is None else f"{value:.{digits}f}"

        print(
            f"{group['M']:<4} "
            f"{group['runs']:<4} "
            f"{group['strict_pairs']:<6} "
            f"{group['strict_pair_rate']:<7.3f} "
            f"{fmt(group['mean_hybrid_energy_j']):<13} "
            f"{fmt(group['median_hybrid_energy_j']):<13} "
            f"{fmt(group['mean_gain_pct']):<11} "
            f"{fmt(group['median_gain_pct']):<10} "
            f"{fmt(group['mean_offload_ratio']):<7} "
            f"{fmt(group['mean_contacts_per_uav']):<12} "
            f"{fmt(group['mean_route_distance_km']):<7} "
            f"{fmt(group['mean_total_runtime_s'])}"
        )

    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
