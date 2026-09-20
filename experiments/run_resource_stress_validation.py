from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_resource_stress_cases
from uav_mec.optimization.resource import (
    solve_kkt_resource_problem,
    solve_resource_problem,
    verify_kkt,
)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj:
            return None
        if obj == float("inf"):
            return "inf"
        if obj == float("-inf"):
            return "-inf"
    return obj


def _max_positive(values: dict[str, float] | None) -> float:
    if not values:
        return 0.0
    return max(0.0, *(float(v) for v in values.values()))


def _run_case(name, instance, solution) -> dict[str, Any]:
    info = build_event_info(instance, solution)

    t0 = perf_counter()
    cvx = solve_resource_problem(instance, solution, info, verbose=False)
    cvx_time = perf_counter() - t0

    t0 = perf_counter()
    kkt = solve_kkt_resource_problem(instance, solution, info)
    kkt_time = perf_counter() - t0

    row: dict[str, Any] = {
        "name": name,
        "cvx_status": cvx.status,
        "kkt_status": kkt.status,
        "cvx_feasible": cvx.feasible,
        "kkt_feasible": kkt.feasible,
        "cvx_runtime_s": cvx_time,
        "kkt_runtime_s": kkt_time,
        "kkt_iterations": kkt.diagnostics.get("iterations"),
        "kkt_termination_reason": kkt.diagnostics.get("termination_reason"),
    }

    if cvx.feasible:
        row.update(
            {
                "cvx_energy_stage1_j": cvx.energy_stage1_j,
                "cvx_avg_delay_s": cvx.diagnostics.get("avg_delay_stage1_reduced_s"),
                "cvx_max_deadline_violation_s": _max_positive(
                    cvx.diagnostics.get("stage1_deadline_violation_s")
                ),
                "cvx_max_cycle_violation_s": _max_positive(
                    cvx.diagnostics.get("stage1_cycle_violation_s")
                ),
                "cvx_max_battery_violation_j": _max_positive(
                    cvx.diagnostics.get("stage1_battery_violation_j")
                ),
                "cvx_dual_avg_delay": cvx.stage1_duals.get("avg_delay", 0.0),
                "cvx_dual_bandwidth_E1": cvx.stage1_duals.get("bandwidth_cap::E1", 0.0),
                "cvx_dual_mec_cpu_E1": cvx.stage1_duals.get("mec_cpu_cap::E1", 0.0),
            }
        )

    if kkt.feasible:
        kkt_report = verify_kkt(instance, solution, info, kkt)
        row.update(
            {
                "kkt_energy_stage1_j": kkt.energy_stage1_j,
                "kkt_avg_delay_s": kkt.diagnostics.get("avg_delay_final_s"),
                "kkt_max_deadline_violation_s": _max_positive(
                    kkt.diagnostics.get("deadline_violation_s")
                ),
                "kkt_max_cycle_violation_s": _max_positive(
                    kkt.diagnostics.get("cycle_violation_s")
                ),
                "kkt_max_battery_violation_j": _max_positive(
                    kkt.diagnostics.get("battery_violation_j")
                ),
                "kkt_stationarity_residual": kkt_report.get("max_abs_stationarity_residual"),
                "kkt_dual_avg_delay": kkt.stage1_duals.get("avg_delay", 0.0),
                "kkt_dual_bandwidth_E1": kkt.stage1_duals.get("bandwidth_cap::E1", 0.0),
                "kkt_dual_mec_cpu_E1": kkt.stage1_duals.get("mec_cpu_cap::E1", 0.0),
            }
        )

    if cvx.feasible and kkt.feasible:
        denom = max(1.0, abs(cvx.energy_stage1_j))
        row["relative_energy_gap"] = abs(kkt.energy_stage1_j - cvx.energy_stage1_j) / denom

    return row


def main() -> None:
    rows: list[dict[str, Any]] = []
    print(
        "case                    cvx-status          kkt-status          rel-gap      "
        "kkt-iters  term"
    )
    print("-" * 106)
    for name, instance, solution in build_resource_stress_cases():
        row = _run_case(name, instance, solution)
        rows.append(row)
        gap = row.get("relative_energy_gap")
        gap_text = "-" if gap is None else f"{gap:.3e}"
        print(
            f"{name:<23} {row['cvx_status']:<19} {row['kkt_status']:<19} "
            f"{gap_text:<12} {str(row.get('kkt_iterations')):<10} "
            f"{row.get('kkt_termination_reason')}"
        )

    comparable = [r for r in rows if "relative_energy_gap" in r]
    if comparable:
        print("\nmax relative Stage-1 energy gap:", max(r["relative_energy_gap"] for r in comparable))
        print("mean relative Stage-1 energy gap:", sum(r["relative_energy_gap"] for r in comparable) / len(comparable))
        print("max KKT stationarity residual:", max(float(r.get("kkt_stationarity_residual", 0.0)) for r in comparable))

    print("\nDual activation summary:")
    for row in rows:
        if not row.get("kkt_feasible"):
            continue
        print(
            f"{row['name']:<23} beta={row.get('kkt_dual_avg_delay', 0.0):.3e} "
            f"lambdaB(E1)={row.get('kkt_dual_bandwidth_E1', 0.0):.3e} "
            f"lambdaF(E1)={row.get('kkt_dual_mec_cpu_E1', 0.0):.3e}"
        )

    out = Path("outputs/results/resource_stress_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_jsonable(rows), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
