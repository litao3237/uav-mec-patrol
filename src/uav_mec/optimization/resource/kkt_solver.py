from __future__ import annotations

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo, build_event_info

from .kkt_resources import (
    _allocate_resources,
    _build_dual_snapshot,
    _initial_resources,
    _is_feasible,
    _snapshot_values,
)
from .kkt_temporal import KKTResourceSolverConfig, _TemporalPrices, _temporal_prices
from .precheck import fast_feasibility_precheck
from .reduced import ReducedResourceEvaluation, evaluate_reduced_resources
from .result import ResourceSolveResult


def _clip(value: float, bound: float) -> float:
    if bound <= 0.0:
        return value
    return max(-bound, min(bound, value))


def _normalized_outer_complementarity(
    instance: Instance,
    evaluation: ReducedResourceEvaluation,
    *,
    alpha: dict[str, float],
    beta: float,
    xi_cycle: dict[str, float],
    mu_battery: dict[str, float],
) -> float:
    """Dimensionless complementarity monitor for the outer QoS duals.

    The old stopping rule checked only primal feasibility and energy stability.
    That can terminate at a feasible but clearly non-KKT point: a large positive
    deadline price may coexist with a very slack deadline. Normalizing each slack
    by its natural scale lets one convergence threshold cover deadline, average
    delay, patrol cycle and battery multipliers.
    """

    residuals: list[float] = []

    for task_id, task in instance.tasks.items():
        normalized_slack = abs(evaluation.deadline_violation_s[task_id]) / max(
            1.0, task.deadline_s
        )
        residuals.append(alpha[task_id] * normalized_slack)

    avg_normalized = abs(
        evaluation.avg_delay_s - instance.avg_delay_budget_s
    ) / max(1.0, instance.avg_delay_budget_s)
    residuals.append(beta * avg_normalized)

    for uav_id, uav in instance.uavs.items():
        cycle_normalized = abs(evaluation.cycle_violation_s[uav_id]) / max(
            1.0, instance.cycle_s
        )
        residuals.append(xi_cycle[uav_id] * cycle_normalized)

        battery_normalized = abs(evaluation.battery_violation_j[uav_id]) / max(
            1.0, uav.energy_budget_j
        )
        residuals.append(mu_battery[uav_id] * battery_normalized)

    return max(residuals, default=0.0)


def solve_kkt_resource_problem(
    instance: Instance,
    solution: DiscreteSolution,
    info: EventInfo | None = None,
    *,
    config: KKTResourceSolverConfig | None = None,
) -> ResourceSolveResult:
    """Experimental analytical KKT/dual solver for P1-R stage 1.

    This solver eliminates start/completion epigraph variables, propagates their
    shadow prices backward through the fixed FIFO/EDF event graph, obtains CPU
    allocations from closed-form KKT equations, and obtains bandwidth by dual
    price bisection. Only the Stage-1 energy problem is targeted here; the
    lexicographic Stage-2 MEC-CPU minimization remains in the CVXPY oracle.
    """

    cfg = config or KKTResourceSolverConfig()
    info = info or build_event_info(instance, solution)
    precheck = fast_feasibility_precheck(instance, solution, info)
    if not precheck.feasible:
        return ResourceSolveResult(
            status="infeasible_precheck",
            solver="KKT-DUAL",
            is_dcp=True,
            energy_stage1_j=float("inf"),
            energy_final_j=float("inf"),
            diagnostics={"precheck_reasons": list(precheck.reasons)},
        )

    alpha = {task_id: cfg.initial_task_price for task_id in instance.tasks}
    beta = 0.0
    xi_cycle = {u: 0.0 for u in instance.uavs}
    mu_battery = {u: 0.0 for u in instance.uavs}

    bandwidth, mec_cpu, local_cpu = _initial_resources(instance, info)
    evaluation = evaluate_reduced_resources(
        instance,
        solution,
        info,
        bandwidth_mhz=bandwidth,
        mec_cpu_ghz=mec_cpu,
        local_cpu_ghz=local_cpu,
    )

    # The equal-share / max-local-CPU resource point is a constructive primal
    # seed. On larger paper-scale instances the dual subgradient iterations can
    # temporarily leave the feasible set and may fail to return to it within a
    # finite iteration budget. Never discard a resource point that has already
    # been verified feasible: doing so would misclassify a feasible P1-R.
    initial_seed_feasible = _is_feasible(
        instance,
        evaluation,
        time_tol=cfg.feasibility_tol_s,
        avg_tol=cfg.avg_delay_tol_s,
        energy_tol_j=cfg.energy_tol_j,
    )
    seed_evaluation = evaluation
    seed_bandwidth = dict(bandwidth)
    seed_mec_cpu = dict(mec_cpu)
    seed_local_cpu = dict(local_cpu)

    Snapshot = tuple[
        float,
        ReducedResourceEvaluation,
        dict[tuple[str, str], float],
        dict[tuple[str, str], float],
        dict[str, float],
        _TemporalPrices,
        dict[str, float],
        dict[str, float],
        dict[str, float],
        float,
        dict[str, float],
        dict[str, float],
    ]

    best: Snapshot | None = None
    stable = 0
    last_energy = float("inf")
    iteration = 0
    termination_reason = "max_iterations"
    outer_complementarity = float("inf")

    for iteration in range(1, cfg.max_iterations + 1):
        prices = _temporal_prices(
            instance,
            solution,
            info,
            evaluation,
            alpha=alpha,
            beta=beta,
            xi_cycle=xi_cycle,
            mu_battery=mu_battery,
            tie_tol_s=cfg.tie_tol_s,
        )
        bandwidth, mec_cpu, local_cpu, lambda_b, lambda_f = _allocate_resources(
            instance,
            solution,
            info,
            prices,
            mu_battery=mu_battery,
            min_bandwidth_mhz=cfg.min_bandwidth_mhz,
            min_cpu_ghz=cfg.min_cpu_ghz,
        )
        evaluation = evaluate_reduced_resources(
            instance,
            solution,
            info,
            bandwidth_mhz=bandwidth,
            mec_cpu_ghz=mec_cpu,
            local_cpu_ghz=local_cpu,
        )

        current: Snapshot = (
            evaluation.total_energy_j,
            evaluation,
            dict(bandwidth),
            dict(mec_cpu),
            dict(local_cpu),
            prices,
            dict(lambda_b),
            dict(lambda_f),
            dict(alpha),
            beta,
            dict(xi_cycle),
            dict(mu_battery),
        )

        feasible = _is_feasible(
            instance,
            evaluation,
            time_tol=cfg.feasibility_tol_s,
            avg_tol=cfg.avg_delay_tol_s,
            energy_tol_j=cfg.energy_tol_j,
        )
        if feasible and (best is None or evaluation.total_energy_j < best[0]):
            best = current

        outer_complementarity = _normalized_outer_complementarity(
            instance,
            evaluation,
            alpha=alpha,
            beta=beta,
            xi_cycle=xi_cycle,
            mu_battery=mu_battery,
        )
        energy_change = abs(evaluation.total_energy_j - last_energy)

        # Stationarity of the inner resource variables is enforced analytically.
        # Convergence therefore also requires:
        #   1) primal feasibility,
        #   2) outer complementary slackness,
        #   3) a stable primal objective.
        if (
            iteration >= cfg.min_iterations
            and feasible
            and outer_complementarity <= cfg.normalized_complementarity_tol
            and energy_change <= max(1e-5, 1e-8 * evaluation.total_energy_j)
        ):
            stable += 1
            if stable >= cfg.convergence_patience:
                termination_reason = "converged"
                # Use the certified current iterate so returned duals and primal
                # resources describe the same approximate KKT point.
                best = current
                break
        else:
            stable = 0
        last_energy = evaluation.total_energy_j

        decay = 1.0 / (1.0 + iteration / cfg.step_decay_blocks) ** 0.5

        # Projected dual ascent. Extremely small CPU frequencies can create huge
        # one-step deadline violations; clipping the dimensionless subgradient
        # prevents a single excursion from inflating alpha by orders of magnitude
        # and then requiring hundreds of iterations merely to unwind it.
        for task_id, task in instance.tasks.items():
            normalized = evaluation.deadline_violation_s[task_id] / max(
                1.0, task.deadline_s
            )
            normalized = _clip(normalized, cfg.normalized_subgradient_clip)
            alpha[task_id] = max(
                0.0,
                alpha[task_id] + cfg.task_step * decay * normalized,
            )

        avg_normalized = (
            evaluation.avg_delay_s - instance.avg_delay_budget_s
        ) / max(1.0, instance.avg_delay_budget_s)
        avg_normalized = _clip(
            avg_normalized,
            cfg.normalized_subgradient_clip,
        )
        beta = max(
            0.0,
            beta + cfg.average_step * decay * avg_normalized,
        )

        for uav_id, uav in instance.uavs.items():
            cycle_normalized = evaluation.cycle_violation_s[uav_id] / max(
                1.0, instance.cycle_s
            )
            cycle_normalized = _clip(
                cycle_normalized,
                cfg.normalized_subgradient_clip,
            )
            xi_cycle[uav_id] = max(
                0.0,
                xi_cycle[uav_id] + cfg.cycle_step * decay * cycle_normalized,
            )

            battery_normalized = evaluation.battery_violation_j[uav_id] / max(
                1.0, uav.energy_budget_j
            )
            battery_normalized = _clip(
                battery_normalized,
                cfg.normalized_subgradient_clip,
            )
            mu_battery[uav_id] = max(
                0.0,
                mu_battery[uav_id]
                + cfg.battery_step * decay * battery_normalized,
            )

    if best is None:
        if initial_seed_feasible:
            seed_values = _snapshot_values(
                seed_evaluation,
                bandwidth=seed_bandwidth,
                mec_cpu=seed_mec_cpu,
                local_cpu=seed_local_cpu,
            )
            return ResourceSolveResult(
                status="feasible_seed",
                solver="KKT-DUAL",
                is_dcp=True,
                energy_stage1_j=seed_evaluation.total_energy_j,
                energy_final_j=seed_evaluation.total_energy_j,
                stage1_values=seed_values,
                final_values=seed_values,
                stage1_duals={},
                diagnostics={
                    "iterations": iteration,
                    "termination_reason": "initial_feasible_seed_fallback",
                    "converged": False,
                    "initial_seed_feasible": True,
                    "dual_certificate_available": False,
                    "normalized_outer_complementarity": outer_complementarity,
                    "avg_delay_final_s": seed_evaluation.avg_delay_s,
                    "return_times_final_s": seed_evaluation.return_time_s,
                    "deadline_violation_s": seed_evaluation.deadline_violation_s,
                    "cycle_violation_s": seed_evaluation.cycle_violation_s,
                    "battery_violation_j": seed_evaluation.battery_violation_j,
                    "last_energy_j": evaluation.total_energy_j,
                    "last_avg_delay_s": evaluation.avg_delay_s,
                    "last_deadline_violation_s": evaluation.deadline_violation_s,
                    "last_cycle_violation_s": evaluation.cycle_violation_s,
                },
            )

        return ResourceSolveResult(
            status="kkt_no_feasible_iterate",
            solver="KKT-DUAL",
            is_dcp=True,
            energy_stage1_j=float("inf"),
            energy_final_j=float("inf"),
            diagnostics={
                "iterations": iteration,
                "termination_reason": termination_reason,
                "converged": False,
                "initial_seed_feasible": False,
                "normalized_outer_complementarity": outer_complementarity,
                "last_energy_j": evaluation.total_energy_j,
                "last_avg_delay_s": evaluation.avg_delay_s,
                "last_deadline_violation_s": evaluation.deadline_violation_s,
                "last_cycle_violation_s": evaluation.cycle_violation_s,
            },
        )

    (
        energy,
        best_eval,
        best_b,
        best_F,
        best_f,
        best_prices,
        best_lambda_b,
        best_lambda_f,
        best_alpha,
        best_beta,
        best_xi_cycle,
        best_mu_battery,
    ) = best

    best_outer_complementarity = _normalized_outer_complementarity(
        instance,
        best_eval,
        alpha=best_alpha,
        beta=best_beta,
        xi_cycle=best_xi_cycle,
        mu_battery=best_mu_battery,
    )

    values = _snapshot_values(
        best_eval,
        bandwidth=best_b,
        mec_cpu=best_F,
        local_cpu=best_f,
    )
    duals = _build_dual_snapshot(
        instance,
        solution,
        info,
        best_eval,
        best_prices,
        alpha=best_alpha,
        beta=best_beta,
        xi_cycle=best_xi_cycle,
        mu_battery=best_mu_battery,
        bandwidth=best_b,
        mec_cpu=best_F,
        local_cpu=best_f,
        lambda_b=best_lambda_b,
        lambda_f=best_lambda_f,
        min_bandwidth_mhz=cfg.min_bandwidth_mhz,
        min_cpu_ghz=cfg.min_cpu_ghz,
    )

    converged = termination_reason == "converged"
    return ResourceSolveResult(
        status="optimal_approx" if converged else "feasible_approx",
        solver="KKT-DUAL",
        is_dcp=True,
        energy_stage1_j=energy,
        energy_final_j=energy,
        stage1_values=values,
        final_values=values,
        stage1_duals=duals,
        diagnostics={
            "iterations": iteration,
            "termination_reason": termination_reason,
            "converged": converged,
            "initial_seed_feasible": initial_seed_feasible,
            "dual_certificate_available": True,
            "normalized_outer_complementarity": best_outer_complementarity,
            "stage2_status": "not_implemented_in_kkt_v0.3",
            "avg_delay_final_s": best_eval.avg_delay_s,
            "return_times_final_s": best_eval.return_time_s,
            "deadline_violation_s": best_eval.deadline_violation_s,
            "cycle_violation_s": best_eval.cycle_violation_s,
            "battery_violation_j": best_eval.battery_violation_j,
            "fixed_energy_j": {
                u: info.fixed_flight_energy_j[u]
                + info.fixed_collection_energy_j[u]
                for u in instance.uavs
            },
            "dual_alpha": best_alpha,
            "dual_beta": best_beta,
            "dual_cycle": best_xi_cycle,
            "dual_battery": best_mu_battery,
        },
    )
