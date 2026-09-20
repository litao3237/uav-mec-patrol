from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uav_mec.evaluation import build_event_info, format_event_summary
from uav_mec.instances import build_small_instance
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


def _print_values(title: str, values: dict[str, dict[str, float]]) -> None:
    print(f"\n--- {title} ---")
    for pair, val in values["bandwidth_mhz"].items():
        print(f"bandwidth {pair}: {val:.6f} MHz")
    for pair, val in values["mec_cpu_ghz"].items():
        print(f"MEC CPU   {pair}: {val:.6f} GHz")
    for task_id, val in values["local_cpu_ghz"].items():
        print(f"local CPU {task_id}: {val:.6f} GHz")
    for visit_id, val in values["tau_s"].items():
        print(f"upload tau {visit_id}: {val:.6f} s")
    for task_id, val in values["task_completion_s"].items():
        print(f"completion {task_id}: {val:.6f} s")


def main() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)
    print(format_event_summary(instance, solution, info))

    print("\n=== CVXPY reference P1-R ===")
    result = solve_resource_problem(instance, solution, info, verbose=False)
    print(f"solver={result.solver}, status={result.status}, DCP={result.is_dcp}")
    if not result.feasible:
        print("No feasible solution.")
        print(result.diagnostics)
        raise SystemExit(2)

    print(f"stage-1 UAV energy = {result.energy_stage1_j:.6f} J")
    print(f"stage-1 avg delay  = {result.diagnostics['avg_delay_stage1_s']:.6f} s")
    _print_values("Stage-1 energy-optimal allocation", result.stage1_values)

    print("\n--- Stage-1 shadow prices ---")
    for name, val in sorted(result.stage1_duals.items()):
        if (
            name.startswith("bandwidth_cap::")
            or name.startswith("mec_cpu_cap::")
            or name.startswith("deadline::")
            or name == "avg_delay"
            or name.startswith("battery::")
        ):
            print(f"{name}: {val:.6e}")

    print(f"\nstage-2/final UAV energy = {result.energy_final_j:.6f} J")
    print(f"stage-2/final avg delay  = {result.diagnostics['avg_delay_final_s']:.6f} s")
    _print_values("Stage-2 minimum-MEC-CPU allocation", result.final_values)

    print("\n=== Analytical KKT/Dual Stage-1 solver ===")
    kkt_result = solve_kkt_resource_problem(instance, solution, info)
    print(
        f"solver={kkt_result.solver}, status={kkt_result.status}, "
        f"iterations={kkt_result.diagnostics.get('iterations')}"
    )
    if kkt_result.feasible:
        relative_gap = abs(kkt_result.energy_stage1_j - result.energy_stage1_j) / result.energy_stage1_j
        print(f"KKT stage-1 energy = {kkt_result.energy_stage1_j:.6f} J")
        print(f"CVX/KKT relative energy gap = {relative_gap:.6e}")
        _print_values("KKT Stage-1 allocation", kkt_result.stage1_values)
        kkt_self = verify_kkt(instance, solution, info, kkt_result)
        print(
            "KKT self stationarity residual = "
            f"{kkt_self.get('max_abs_stationarity_residual', float('nan')):.6e}"
        )
    else:
        print("KKT solver did not produce a feasible iterate:", kkt_result.diagnostics)

    print("\n=== KKT verification on CVXPY stage-1 optimum ===")
    cvx_kkt = verify_kkt(instance, solution, info, result)
    print(
        "CVXPY max |stationarity residual| = "
        f"{cvx_kkt.get('max_abs_stationarity_residual', float('nan')):.6e}"
    )

    output = {
        "cvx": {
            "status": result.status,
            "solver": result.solver,
            "energy_stage1_j": result.energy_stage1_j,
            "energy_final_j": result.energy_final_j,
            "stage1_values": result.stage1_values,
            "final_values": result.final_values,
            "stage1_duals": result.stage1_duals,
            "diagnostics": result.diagnostics,
        },
        "kkt_solver": {
            "status": kkt_result.status,
            "energy_stage1_j": kkt_result.energy_stage1_j,
            "stage1_values": kkt_result.stage1_values,
            "stage1_duals": kkt_result.stage1_duals,
            "diagnostics": kkt_result.diagnostics,
        },
        "cvx_kkt_verification": cvx_kkt,
    }
    out_path = Path("outputs/results/small_validation.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_jsonable(output), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved detailed results to: {out_path}")


if __name__ == "__main__":
    main()
