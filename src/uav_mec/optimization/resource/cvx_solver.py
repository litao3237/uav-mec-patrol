from __future__ import annotations

from typing import Any
from statistics import mean
from time import perf_counter
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


def solve_stage2_realization(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo,
    *,
    energy_star_j: float,
    energy_tolerance_j: float,
    verbose: bool = False,
    solver_profile: str = "default",
) -> dict[str, Any]:
    """固定Stage-1能耗锚点，在等价缩放模型上求Stage-2并核验全部物理约束。

    仅接受optimal且原始/重建两套残差都合格的解。固定重试顺序对所有方法
    一致；失败保留诊断，不放宽能耗容差，也不把Stage-1回退冒充第二阶段。
    """
    # 延迟导入避免analysis包初始化与resource后端形成循环依赖。
    from uav_mec.analysis.constraint_audit import audit_both_timelines

    if (not np.isfinite(energy_star_j) or not np.isfinite(energy_tolerance_j)
            or energy_tolerance_j < 0):
        raise ValueError("Stage-2能耗锚点与容差必须有限，且容差非负")
    available = _solver_candidates(solver_profile)
    # CPU目标乘正数不改变最优解；备用尺度用于内点法退化时的固定数值重试。
    schedule = [(s, scale) for s in available for scale in
                ((1.0, 100.0) if s == "CLARABEL" else (1.0,))]
    attempts = []
    outcome: dict[str, Any] = {"accepted": False, "status": "solver_error",
                              "solver": None, "raw_values": None, "energy_j": None}
    for solver, objective_scale in schedule:
        model = build_resource_model(instance, solution, info, numerical_scaling=True)
        # 1 kJ=1000 J：改变数值表示，不改变能耗保护上限。
        energy_guard = (model.total_energy - energy_star_j - energy_tolerance_j) / 1000.0 <= 0
        problem = cp.Problem(cp.Minimize(objective_scale * model.normalized_mec_cpu),
                             model.constraints + [energy_guard])
        kwargs = _solver_kwargs(solver, verbose, solver_profile)
        if solver == "CLARABEL":
            kwargs.update(max_iter=300, tol_gap_abs=1e-9, tol_gap_rel=1e-9, tol_feas=1e-9)
        elif solver == "SCS":
            kwargs.update(eps=1e-8, max_iters=200000)
        started = perf_counter()
        attempt: dict[str, Any] = {"solver": solver, "objective_scale": objective_scale}
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Solution may be inaccurate.*", category=UserWarning)
                problem.solve(solver=solver, **kwargs)
        except cp.error.SolverError as exc:
            attempt.update(status="solver_error", error=str(exc), accepted=False)
            outcome.update(accepted=False, status="solver_error", solver=solver,
                           raw_values=None, energy_j=None)
        else:
            status = str(problem.status)
            values = None
            audit = None
            if status in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
                values = _snapshot_vars(model.variables)
                audit = audit_both_timelines(instance, solution, values,
                                            energy_limit_j=energy_star_j + energy_tolerance_j)
            passed = audit is not None and all(a["passed"] for a in audit.values())
            accepted = status == cp.OPTIMAL and passed
            attempt.update(status=status, accepted=accepted,
                           iterations=problem.solver_stats.num_iters,
                           audit={k: {f: v.get(f) for f in
                                      ("passed", "max_normalized_violation", "worst_constraint", "reason")}
                                  for k, v in (audit or {}).items()})
            outcome.update(accepted=accepted, status="invalid_residual" if status == cp.OPTIMAL and not passed else status,
                           solver=solver, raw_values=values,
                           energy_j=_value(model.total_energy.value) if values is not None else None)
        attempt["runtime_s"] = perf_counter() - started
        attempts.append(attempt)
        if outcome["accepted"]:
            break
    outcome["attempts"] = attempts
    return outcome


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

    stage2_attempts: list[dict[str, Any]] = []
    stage2_accepted = False
    if run_stage2:
        stage2 = solve_stage2_realization(
            instance, solution, info, energy_star_j=energy_star,
            energy_tolerance_j=tol_j, verbose=verbose, solver_profile=solver_profile,
        )
        solver2 = stage2["solver"]
        stage2_status = stage2["status"]
        stage2_attempts = stage2["attempts"]
        stage2_accepted = stage2["accepted"]
        stage2_errors = [f"{a['solver']}: {a.get('error', a['status'])}"
                         for a in stage2_attempts if not a["accepted"]]
        if capture_stage2_raw_values:
            stage2_raw_values = stage2["raw_values"]
        if stage2_accepted:
            # 完整残差已经核验；直接返回未裁剪变量，不再事后修改最优资源。
            final_values = stage2["raw_values"]
            final_energy = stage2["energy_j"]
            solver_final = solver2
        else:
            # 保留Stage-1返回兼容性；Stage-2状态及accepted明确记录失败。
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
        "stage2_accepted": stage2_accepted,
        "stage2_attempts": stage2_attempts,
        "stage2_formulation": "dimensionless_rate_epigraph_v1" if run_stage2 else "skipped",
        "energy_tolerance_j": tol_j,
        "avg_delay_stage1_s": stage1_avg_delay,
        "avg_delay_stage1_reduced_s": stage1_reduced.avg_delay_s,
        "energy_stage1_reduced_j": stage1_reduced.total_energy_j,
        "stage1_deadline_violation_s": stage1_reduced.deadline_violation_s,
        "stage1_cycle_violation_s": stage1_reduced.cycle_violation_s,
        "stage1_battery_violation_j": stage1_reduced.battery_violation_j,
        "return_times_stage1_s": stage1_return_times,
        # 最终诊断必须来自实际返回快照，不能读失败Stage-2遗留的模型变量。
        "avg_delay_final_s": mean(final_values["task_completion_s"][t] - instance.tasks[t].release_s
                                  for t in instance.tasks),
        "return_times_final_s": {
            u: info.base_return_s[u] + sum(final_values["tau_s"][v] for v in info.contact_order[u])
            for u in instance.uavs
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
