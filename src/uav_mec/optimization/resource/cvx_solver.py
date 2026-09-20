from __future__ import annotations

from typing import Any
import warnings

import cvxpy as cp
import numpy as np

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo, build_event_info

from .precheck import fast_feasibility_precheck
from .reduced import evaluate_reduced_resources
from .problem import build_resource_model
from .result import ResourceSolveResult


def _solver_candidates() -> list[str]:
    installed = set(cp.installed_solvers())
    preferred = ("CLARABEL", "SCS", "ECOS")
    candidates = [solver for solver in preferred if solver in installed]
    if not candidates:
        raise RuntimeError(
            f"No supported conic solver found. Installed={sorted(installed)}. "
            "Install clarabel or scs."
        )
    return candidates


def _solver_kwargs(solver: str, verbose: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"verbose": verbose}
    if solver == "SCS":
        kwargs.update({"eps": 1e-6, "max_iters": 100000})
    return kwargs


def _solve_with_fallback(
    problem: cp.Problem,
    *,
    verbose: bool,
    preferred_solver: str | None = None,
) -> tuple[str | None, list[str]]:
    """Solve robustly and prefer an exact CVXPY status over an inaccurate one.

    A solver may return OPTIMAL_INACCURATE (or another *_INACCURATE status)
    without raising SolverError. Treat that as a usable fallback, but continue
    trying the remaining installed conic solvers first. This prevents Clarabel
    or SCS from stopping the fallback chain prematurely on a numerically
    difficult candidate.

    The generic CVXPY "Solution may be inaccurate" warning is suppressed here
    because the status is recorded explicitly in diagnostics. If every solver
    is inaccurate, the final ResourceSolveResult still exposes that status.
    """

    candidates = _solver_candidates()
    if preferred_solver in candidates:
        candidates.remove(preferred_solver)
        candidates.insert(0, preferred_solver)

    errors: list[str] = []
    inaccurate_solver: str | None = None

    inaccurate_statuses = {
        cp.OPTIMAL_INACCURATE,
        cp.INFEASIBLE_INACCURATE,
        cp.UNBOUNDED_INACCURATE,
    }

    for solver in candidates:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Solution may be inaccurate.*",
                    category=UserWarning,
                )
                problem.solve(
                    solver=solver,
                    **_solver_kwargs(solver, verbose),
                )
        except cp.error.SolverError as exc:
            errors.append(f"{solver}: {exc}")
            continue

        status = problem.status
        if status in inaccurate_statuses:
            errors.append(f"{solver}: status={status}")
            inaccurate_solver = solver
            continue

        # Exact optimal / infeasible / unbounded statuses are terminal.
        if status is not None:
            return solver, errors

    if inaccurate_solver is not None:
        # A later solver may have raised after the inaccurate solution was
        # obtained. Re-solve with the selected fallback so problem.value and
        # variable/dual values definitely correspond to the returned solver.
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Solution may be inaccurate.*",
                    category=UserWarning,
                )
                problem.solve(
                    solver=inaccurate_solver,
                    **_solver_kwargs(inaccurate_solver, verbose),
                )
        except cp.error.SolverError as exc:
            errors.append(
                f"{inaccurate_solver}: fallback re-solve failed: {exc}"
            )
            return None, errors
        return inaccurate_solver, errors

    return None, errors


def _value(x: Any) -> float:
    if x is None:
        return float("nan")
    arr = np.asarray(x, dtype=float)
    return float(arr.reshape(-1)[0])




def _numeric_group(mapping: dict[Any, Any]) -> dict[Any, float]:
    return {key: _value(var.value) for key, var in mapping.items()}


def _snapshot_vars(vars_dict: dict[str, dict[Any, Any]]) -> dict[str, dict[str, float]]:
    return {
        group: {str(key): _value(var.value) for key, var in mapping.items()}
        for group, mapping in vars_dict.items()
    }


def _snapshot_duals(named_constraints: dict[str, Any]) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for name, con in named_constraints.items():
        if not hasattr(con, "dual_value"):
            raise TypeError(
                f"Named constraint {name!r} is not a CVXPY constraint: "
                f"{type(con).__name__}"
            )
        snapshot[name] = _value(con.dual_value)
    return snapshot


def solve_resource_problem(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo | None = None,
    *,
    verbose: bool = False,
    energy_tol_rel: float = 1e-6,
    run_stage2: bool = True,
) -> ResourceSolveResult:
    info = info or build_event_info(instance, solution)

    # Reject obvious infeasible discrete candidates before paying the conic-solver cost.
    precheck = fast_feasibility_precheck(instance, solution, info)
    if not precheck.feasible:
        return ResourceSolveResult(
            status="infeasible_precheck",
            solver="PRECHECK",
            is_dcp=True,
            energy_stage1_j=float("inf"),
            energy_final_j=float("inf"),
            diagnostics={
                "message": "Fixed discrete solution failed optimistic feasibility lower bounds.",
                "precheck_reasons": list(precheck.reasons),
                "task_completion_lb_s": precheck.task_completion_lb_s,
                "return_time_lb_s": precheck.return_time_lb_s,
            },
        )

    model = build_resource_model(instance, solution, info)
    problem1 = cp.Problem(cp.Minimize(model.total_energy), model.constraints)
    if not problem1.is_dcp():
        raise RuntimeError("P1-R was expected to be DCP, but CVXPY reports is_dcp=False")

    solver1, stage1_errors = _solve_with_fallback(problem1, verbose=verbose)
    if solver1 is None:
        return ResourceSolveResult(
            status="solver_error",
            solver="NONE",
            is_dcp=problem1.is_dcp(),
            energy_stage1_j=float("inf"),
            energy_final_j=float("inf"),
            diagnostics={
                "message": "All installed conic solvers failed.",
                "solver_errors": stage1_errors,
            },
        )

    if problem1.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        return ResourceSolveResult(
            status=str(problem1.status),
            solver=solver1,
            is_dcp=problem1.is_dcp(),
            energy_stage1_j=float("inf"),
            energy_final_j=float("inf"),
            diagnostics={
                "message": "Stage-1 problem is infeasible or otherwise non-optimal.",
                "solver_errors": stage1_errors,
            },
        )

    energy_star = float(problem1.value)
    stage1_values = _snapshot_vars(model.variables)
    stage1_duals = _snapshot_duals(model.named_constraints)
    stage1_avg_delay = _value(model.avg_delay_expr.value)
    stage1_reduced = evaluate_reduced_resources(
        instance,
        solution,
        info,
        bandwidth_mhz=_numeric_group(model.variables["bandwidth_mhz"]),
        mec_cpu_ghz=_numeric_group(model.variables["mec_cpu_ghz"]),
        local_cpu_ghz=_numeric_group(model.variables["local_cpu_ghz"]),
    )
    stage1_return_times = {
        u: _value(expr.value if hasattr(expr, "value") else expr)
        for u, expr in model.return_time.items()
    }

    # Lexicographic stage 2: among energy-optimal solutions, minimize MEC CPU
    # occupation. Diagnostic experiments that only need the Stage-1 energy
    # optimum may skip this second solve; doing so avoids an unnecessarily tight
    # energy-guarded conic problem and keeps Stage-1 oracle checks independent
    # from Stage-2 numerical accuracy.
    tol_j = max(1e-5, energy_tol_rel * max(1.0, abs(energy_star)))
    solver2 = None
    stage2_errors: list[str] = []

    if run_stage2:
        energy_guard = model.total_energy <= energy_star + tol_j
        problem2 = cp.Problem(
            cp.Minimize(model.normalized_mec_cpu),
            model.constraints + [energy_guard],
        )
        solver2, stage2_errors = _solve_with_fallback(
            problem2,
            verbose=verbose,
            preferred_solver=solver1,
        )

        if solver2 is None or problem2.status not in (
            cp.OPTIMAL,
            cp.OPTIMAL_INACCURATE,
        ):
            final_values = stage1_values
            final_energy = energy_star
            stage2_status = (
                "solver_error" if solver2 is None else str(problem2.status)
            )
            solver_final = solver1
        else:
            final_values = _snapshot_vars(model.variables)
            final_energy = _value(model.total_energy.value)
            stage2_status = str(problem2.status)
            solver_final = solver2
    else:
        final_values = stage1_values
        final_energy = energy_star
        stage2_status = "skipped"
        solver_final = solver1

    diagnostics = {
        "stage1_status": str(problem1.status),
        "stage2_status": stage2_status,
        "stage1_solver": solver1,
        "stage2_solver": solver2,
        "stage1_solver_errors": stage1_errors,
        "stage2_solver_errors": stage2_errors,
        "energy_tolerance_j": tol_j,
        "avg_delay_stage1_s": stage1_avg_delay,
        "avg_delay_stage1_reduced_s": stage1_reduced.avg_delay_s,
        "energy_stage1_reduced_j": stage1_reduced.total_energy_j,
        "stage1_deadline_violation_s": stage1_reduced.deadline_violation_s,
        "stage1_cycle_violation_s": stage1_reduced.cycle_violation_s,
        "stage1_battery_violation_j": stage1_reduced.battery_violation_j,
        "return_times_stage1_s": stage1_return_times,
        "avg_delay_final_s": _value(model.avg_delay_expr.value),
        "return_times_final_s": {
            u: _value(expr.value if hasattr(expr, "value") else expr)
            for u, expr in model.return_time.items()
        },
        "fixed_energy_j": {
            u: info.fixed_flight_energy_j[u] + info.fixed_collection_energy_j[u]
            for u in instance.uavs
        },
        "problem1_is_dcp": problem1.is_dcp(),
        "problem1_is_dpp": problem1.is_dpp(),
    }

    return ResourceSolveResult(
        status=stage2_status if final_values is not stage1_values else str(problem1.status),
        solver=solver_final,
        is_dcp=problem1.is_dcp(),
        energy_stage1_j=energy_star,
        energy_final_j=final_energy,
        stage1_values=stage1_values,
        final_values=final_values,
        stage1_duals=stage1_duals,
        diagnostics=diagnostics,
    )
