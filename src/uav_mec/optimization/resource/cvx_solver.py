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


def _solver_candidates(
    solver_profile: str = "default",
) -> list[str]:
    installed = set(cp.installed_solvers())
    if solver_profile == "default":
        preferred = ("CLARABEL", "SCS", "ECOS")
    elif solver_profile == "recovery":
        # A fresh high-accuracy SCS attempt is useful when the default
        # Clarabel/SCS chain ended at OPTIMAL_INACCURATE.
        preferred = ("SCS", "CLARABEL", "ECOS")
    else:
        raise ValueError(
            f"Unknown solver_profile={solver_profile!r}"
        )
    candidates = [solver for solver in preferred if solver in installed]
    if not candidates:
        raise RuntimeError(
            f"No supported conic solver found. Installed={sorted(installed)}. "
            "Install clarabel or scs."
        )
    return candidates


def _solver_kwargs(
    solver: str,
    verbose: bool,
    solver_profile: str = "default",
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"verbose": verbose}
    if solver == "SCS":
        if solver_profile == "recovery":
            kwargs.update(
                {
                    "eps": 2e-7,
                    "max_iters": 300000,
                }
            )
        else:
            kwargs.update(
                {
                    "eps": 1e-6,
                    "max_iters": 100000,
                }
            )
    return kwargs


def _solve_with_fallback(
    problem: cp.Problem,
    *,
    verbose: bool,
    preferred_solver: str | None = None,
    excluded_solvers: set[str] | None = None,
    solver_profile: str = "default",
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

    candidates = [
        solver
        for solver in _solver_candidates(solver_profile)
        if solver not in (excluded_solvers or set())
    ]
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
                    **_solver_kwargs(
                        solver,
                        verbose,
                        solver_profile,
                    ),
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
                    **_solver_kwargs(
                        inaccurate_solver,
                        verbose,
                        solver_profile,
                    ),
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


def _sanitize_positive_group(
    mapping: dict[Any, Any],
    *,
    minimum: float,
    rel_tol: float = 1e-6,
) -> tuple[dict[Any, float], list[str]]:
    """Extract a positive resource group without hiding invalid solver primals.

    CVXPY may occasionally return a nominal optimal/inaccurate status with a
    tiny lower-bound violation. Values within a small numerical tolerance are
    clipped to the modeled lower bound for reduced-form diagnostics. Material
    violations (zero/negative, non-finite, or clearly below the bound) are
    reported so another conic solver can be tried instead of crashing in
    reciprocal rate/CPU calculations.
    """

    values: dict[Any, float] = {}
    violations: list[str] = []
    tol = rel_tol * max(1.0, abs(minimum))

    for key, var in mapping.items():
        value = _value(var.value)
        if not np.isfinite(value):
            violations.append(f"{key}: non-finite value={value}")
            continue
        if value < minimum - tol:
            violations.append(
                f"{key}: value={value:.12g} below minimum={minimum:.12g}"
            )
            continue
        values[key] = max(minimum, value)

    return values, violations


def _stage1_resource_values(
    model,
) -> tuple[
    dict[tuple[str, str], float],
    dict[tuple[str, str], float],
    dict[str, float],
    list[str],
]:
    bandwidth, bw_violations = _sanitize_positive_group(
        model.variables["bandwidth_mhz"],
        minimum=1e-3,
    )
    mec_cpu, mec_violations = _sanitize_positive_group(
        model.variables["mec_cpu_ghz"],
        minimum=1e-4,
    )
    local_cpu, local_violations = _sanitize_positive_group(
        model.variables["local_cpu_ghz"],
        minimum=1e-4,
    )
    violations = (
        [f"bandwidth_mhz::{item}" for item in bw_violations]
        + [f"mec_cpu_ghz::{item}" for item in mec_violations]
        + [f"local_cpu_ghz::{item}" for item in local_violations]
    )
    return bandwidth, mec_cpu, local_cpu, violations


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
    solver_profile: str = "default",
    capture_stage2_raw_values: bool = False,
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

    excluded_solvers: set[str] = set()
    stage1_errors: list[str] = []
    solver1: str | None = None
    bandwidth_values: dict[tuple[str, str], float] = {}
    mec_cpu_values: dict[tuple[str, str], float] = {}
    local_cpu_values: dict[str, float] = {}

    while True:
        solver1, solve_errors = _solve_with_fallback(
            problem1,
            verbose=verbose,
            excluded_solvers=excluded_solvers,
            solver_profile=solver_profile,
        )
        stage1_errors.extend(solve_errors)
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

        (
            bandwidth_values,
            mec_cpu_values,
            local_cpu_values,
            primal_violations,
        ) = _stage1_resource_values(model)
        if not primal_violations:
            break

        stage1_errors.append(
            f"{solver1}: invalid resource primal: "
            + "; ".join(primal_violations)
        )
        excluded_solvers.add(solver1)
        if len(excluded_solvers) >= len(
            _solver_candidates(solver_profile)
        ):
            return ResourceSolveResult(
                status="invalid_primal",
                solver=solver1,
                is_dcp=problem1.is_dcp(),
                energy_stage1_j=float("inf"),
                energy_final_j=float("inf"),
                diagnostics={
                    "message": (
                        "Conic solvers returned non-positive or non-finite "
                        "resource values despite modeled lower bounds."
                    ),
                    "stage1_status": str(problem1.status),
                    "solver_errors": stage1_errors,
                    "primal_violations": primal_violations,
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
        bandwidth_mhz=bandwidth_values,
        mec_cpu_ghz=mec_cpu_values,
        local_cpu_ghz=local_cpu_values,
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
    # 新补充实验可保存裁剪前变量，以独立核验真实求解残差；默认不增加归档字段。
    stage2_raw_values = None

    if run_stage2:
        energy_guard = model.total_energy <= energy_star + tol_j
        problem2 = cp.Problem(
            cp.Minimize(model.normalized_mec_cpu),
            model.constraints + [energy_guard],
        )

        stage2_excluded: set[str] = set()
        stage2_valid = False
        stage2_status = "solver_error"
        final_values = stage1_values
        final_energy = energy_star
        solver_final = solver1

        while True:
            solver2, solve_errors = _solve_with_fallback(
                problem2,
                verbose=verbose,
                preferred_solver=solver1,
                excluded_solvers=stage2_excluded,
                solver_profile=solver_profile,
            )
            stage2_errors.extend(solve_errors)

            if solver2 is None:
                stage2_status = "solver_error"
                break

            if problem2.status not in (
                cp.OPTIMAL,
                cp.OPTIMAL_INACCURATE,
            ):
                stage2_status = str(problem2.status)
                break

            (
                stage2_bandwidth,
                stage2_mec_cpu,
                stage2_local_cpu,
                stage2_primal_violations,
            ) = _stage1_resource_values(model)

            if stage2_primal_violations:
                stage2_errors.append(
                    f"{solver2}: invalid Stage-2 resource primal: "
                    + "; ".join(stage2_primal_violations)
                )
                stage2_excluded.add(solver2)
                if len(stage2_excluded) >= len(
                    _solver_candidates(solver_profile)
                ):
                    stage2_status = "invalid_primal"
                    break
                continue

            final_values = _snapshot_vars(model.variables)
            if capture_stage2_raw_values:
                stage2_raw_values = dict(final_values)
            # Reuse the same positive-resource sanitization used after Stage 1.
            # This clips only tiny numerical lower-bound violations while
            # preserving all non-resource Stage-2 values verbatim.
            final_values["bandwidth_mhz"] = {
                str(key): value
                for key, value in stage2_bandwidth.items()
            }
            final_values["mec_cpu_ghz"] = {
                str(key): value
                for key, value in stage2_mec_cpu.items()
            }
            final_values["local_cpu_ghz"] = {
                str(key): value
                for key, value in stage2_local_cpu.items()
            }
            final_energy = _value(model.total_energy.value)
            stage2_status = str(problem2.status)
            solver_final = solver2
            stage2_valid = True
            break

        if not stage2_valid:
            # Stage 1 remains the correctness result. A numerically invalid
            # lexicographic realization must never replace its valid primal.
            final_values = stage1_values
            final_energy = energy_star
            solver_final = solver1
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
        "solver_profile": solver_profile,
    }
    if capture_stage2_raw_values:
        diagnostics["stage2_raw_values"] = stage2_raw_values

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
