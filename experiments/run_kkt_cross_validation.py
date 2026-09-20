from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_random_validation_instance, build_small_instance
from uav_mec.optimization.resource import (
    solve_kkt_resource_problem,
    solve_resource_problem,
    verify_kkt,
)


def _run_case(name, instance, solution):
    info = build_event_info(instance, solution)

    t0 = perf_counter()
    cvx = solve_resource_problem(instance, solution, info, verbose=False)
    cvx_time = perf_counter() - t0

    t0 = perf_counter()
    kkt = solve_kkt_resource_problem(instance, solution, info)
    kkt_time = perf_counter() - t0

    row = {
        "name": name,
        "cvx_status": cvx.status,
        "kkt_status": kkt.status,
        "cvx_energy_stage1_j": cvx.energy_stage1_j,
        "kkt_energy_stage1_j": kkt.energy_stage1_j,
        "cvx_runtime_s": cvx_time,
        "kkt_runtime_s": kkt_time,
    }
    if cvx.feasible and kkt.feasible:
        denom = max(1.0, abs(cvx.energy_stage1_j))
        row["relative_energy_gap"] = abs(kkt.energy_stage1_j - cvx.energy_stage1_j) / denom
        row["kkt_stationarity_residual"] = verify_kkt(instance, solution, info, kkt).get(
            "max_abs_stationarity_residual"
        )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10, help="number of random validation seeds")
    args = parser.parse_args()

    cases = [("baseline", *build_small_instance())]
    cases.extend(
        (f"seed-{seed}", *build_random_validation_instance(seed))
        for seed in range(args.seeds)
    )

    rows = []
    print("case        cvx-status          kkt-status          rel-gap       cvx-s     kkt-s")
    print("-" * 86)
    for name, instance, solution in cases:
        row = _run_case(name, instance, solution)
        rows.append(row)
        gap = row.get("relative_energy_gap")
        gap_text = "-" if gap is None else f"{gap:.3e}"
        print(
            f"{name:<11} {row['cvx_status']:<19} {row['kkt_status']:<19} "
            f"{gap_text:<12} {row['cvx_runtime_s']:<9.4f} {row['kkt_runtime_s']:<9.4f}"
        )

    comparable = [r for r in rows if "relative_energy_gap" in r]
    if comparable:
        print("\nmax relative Stage-1 energy gap:", max(r["relative_energy_gap"] for r in comparable))
        print("mean CVX runtime:", sum(r["cvx_runtime_s"] for r in comparable) / len(comparable))
        print("mean KKT runtime:", sum(r["kkt_runtime_s"] for r in comparable) / len(comparable))

    out = Path("outputs/results/kkt_cross_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
