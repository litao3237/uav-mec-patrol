"""Diagnostic elastic-slack conic model for frozen UAV-MEC Stage-1 resources.

This is NOT the published algorithm and is NEVER used to accept an ALNS
candidate. Build the EXACT frozen P1-R resource model (scaled representation)
and relax only an explicitly named set of hard-end QoS constraints:

    deadline, average delay, UAV patrol cycle, UAV battery

In an alternate counterfactual diagnosis, also allow aggregate MEC station
bandwidth/CPU CAPACITY increases. Crucially, ALL fixed route/contact/offload
decisions and actual FIFO/EDF/local CPU/channel/upload constraints remain
unaltered and hard. A positive optimal elastic violation is a *numerical*
indication of fixed-D incompatibility, not a mathematically certified minimal
infeasible subsystem or proof that the entire combinatorial problem is
infeasible. Unitless normalized slacks are appropriate for debugging but their
sum does not measure a causal effect of an individual discrete move.

The underlying original resource solver, acceptance tolerances, and Stage-2
verification stay untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from time import perf_counter
import warnings

import cvxpy as cp
import numpy as np

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import build_event_info, visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.problem import build_resource_model


PROTOCOLS = ("qos_only", "qos_plus_mec_capacity", "mec_capacity_only")
# Opt-in post-holdout attribution only; do not broaden frozen legacy PROTOCOLS.
SINGLE_CAPACITY_DIAGNOSTIC_MODES = ("cpu_capacity_only", "bandwidth_capacity_only")
QOS_GROUPS = frozenset(("deadline", "avg_delay", "cycle", "battery"))
CAPACITY_GROUPS = frozenset(("bandwidth_cap", "mec_cpu_cap"))


def constraint_family(name: str) -> str | None:
    """Classify only constraints that have an interpretable elastic unit."""
    if name.startswith("deadline::"):
        return "deadline"
    if name == "avg_delay":
        return "avg_delay"
    if name.startswith("cycle::"):
        return "cycle"
    if name.startswith("battery::"):
        return "battery"
    if name.startswith("bandwidth_cap::"):
        return "bandwidth_cap"
    if name.startswith("mec_cpu_cap::"):
        return "mec_cpu_cap"
    return None


def relaxation_scale(instance: Instance, name: str) -> tuple[float, str]:
    """Restore normalized model slacks to the *actual unit* of this constraint.

    build_resource_model(..., numerical_scaling=True) scales the residual
    of QoS constraints by max(1,cycle_s), battery by per-UAV energy budget,
    and aggregate MEC caps by the individual station capacity.
    """
    family = constraint_family(name)
    if family in ("deadline", "avg_delay", "cycle"):
        return max(1.0, float(instance.cycle_s)), "s"
    if family == "battery":
        return float(instance.uavs[name.split("::")[-1]].energy_budget_j), "J"
    if family == "bandwidth_cap":
        return float(instance.mecs[name.split("::")[-1]].bandwidth_mhz), "MHz"
    if family == "mec_cpu_cap":
        return float(instance.mecs[name.split("::")[-1]].cpu_ghz), "GHz"
    raise ValueError(f"Cannot convert diagnostic slack for {name}")


def _float_expr(expr) -> float | None:
    if expr.value is None:
        return None
    try:
        val = float(np.asarray(expr.value).reshape(-1)[0])
    except (ValueError,TypeError,IndexError):
        return None
    return val if math.isfinite(val) else None


def _critical_dependencies(instance: Instance, solution: DiscreteSolution,
                           info, slack_rows: list[dict], *, limit: int = 8):
    """Explain the *modeled scheduling predecessors*, not causal blame."""
    result = []
    for entry in slack_rows:
        if entry["family"] != "deadline" or entry["normalized_slack"] <= 1e-7:
            continue
        task_id = entry["constraint"].split("::")[-1]
        owner = info.task_owner[task_id]
        decision = solution.task_decisions[task_id]
        if decision.mode.value == "local":
            order = info.local_order[owner]
            earlier = list(order[:order.index(task_id)])
            relation = {
                "execution": "local_fifo",
                "UAV": owner,
                "predecessors": earlier[-4:],
                "predecessor_workload_gcycles": {
                    t: instance.tasks[t].workload_gcycles for t in earlier[-4:]
                },
            }
        else:
            v = decision.contact_visit_id
            mec_id = visit_mec_id(instance, solution, v)
            edf = info.batch_edf_order[v]
            earlier = list(edf[:edf.index(task_id)])
            relation = {
                "execution": "mec_edf_in_batch_with_same_pair_fifo",
                "UAV": owner, "MEC": mec_id, "contact": v,
                "within_batch_predecessors": earlier[-4:],
                "previous_batch_same_pair": info.contact_predecessor_same_mec[v],
                "predecessor_workload_gcycles": {
                    t: instance.tasks[t].workload_gcycles for t in earlier[-4:]
                },
            }
        result.append({
            "task_id": task_id,
            "diagnostic_slack_s": entry["physical_slack"],
            "task_deadline_s": instance.tasks[task_id].deadline_s,
            "dependency_context": relation,
        })
        if len(result) >= limit:
            break
    return result


def diagnose_elastic_resources(instance: Instance,
                               solution: DiscreteSolution,
                               *, mode: str = "qos_only",
                               numerical_violation_tol: float = 2e-4,
                               solve_tol: float = 1e-7,
                               max_scs_iters: int = 60000,
                               top_k: int = 10) -> dict:
    """Minimize aggregate normalized relaxation under the unchanged P1-R model.

    Returns detailed numerical status; NO returned solution is asserted feasible
    under the original physical constraints. Never read a non-credible
    solver status as a valid conflict certificate.
    """
    if mode not in (*PROTOCOLS, *SINGLE_CAPACITY_DIAGNOSTIC_MODES):
        raise ValueError(mode)
    if numerical_violation_tol <= 0 or solve_tol <= 0 or max_scs_iters <= 0:
        raise ValueError("Positive numerical tolerances required")
    validate_solution(instance,solution)
    started = perf_counter()
    info = build_event_info(instance,solution)
    model = build_resource_model(
        instance, solution, info, numerical_scaling=True,
    )
    soft = set(CAPACITY_GROUPS) if mode == "mec_capacity_only" else set(QOS_GROUPS)
    if mode == "qos_plus_mec_capacity":
        soft |= set(CAPACITY_GROUPS)
    if mode == "cpu_capacity_only":
        soft = {"mec_cpu_cap"}
    if mode == "bandwidth_capacity_only":
        soft = {"bandwidth_cap"}

    if len(model.constraints) != len(model.named_constraints):
        raise RuntimeError("Unexpected unnamed constraints in resource model")
    hard = []
    relaxed = []
    slack_by_name = {}
    for i,(name,constraint) in enumerate(model.named_constraints.items()):
        family = constraint_family(name)
        if family in soft:
            s = cp.Variable(nonneg=True, name=f"elastic_{i:04d}")
            slack_by_name[name] = s
            relaxed.append(constraint.expr <= s)
        else:
            hard.append(constraint)

    # No offloading/contact: there is no MEC capacity constraint to relax.
    # Return a transparent "not applicable" result rather than interpreting
    # a model with no elastic variables as zero resource pressure.
    if not slack_by_name:
        return {
            "mode":mode,
            "solver":None,
            "status":"no_applicable_elastic_capacity_constraints",
            "numerically_credible":False,
            "normalized_total_elastic_slack":None,
            "slack_sum_by_family":None,
            "top_constraints":[],
            "top_dependency_context":[],
            "diagnostic_build_and_solve_s":perf_counter()-started,
            "attempts":[],
            "scope":"fixed_D_elastic_counterfactual_not_alns_repair",
            "algorithm_acceptance_unchanged":True,
        }
    obj = cp.sum(cp.hstack(list(slack_by_name.values())))
    # The diagnostic objective is normalized QoS/capacity violation, NOT UAV
    # energy and not the energy-optimal continuation of this fixed structure.
    problem = cp.Problem(cp.Minimize(obj), hard + relaxed)
    if not problem.is_dcp():
        raise RuntimeError("Elastic diagnostic must remain DCP")

    solver_schedule = [
        ("CLARABEL", dict(max_iter=450, tol_gap_abs=solve_tol,
                          tol_gap_rel=solve_tol, tol_feas=solve_tol)),
        ("SCS", dict(eps=max(solve_tol, 3e-7), max_iters=max_scs_iters)),
    ]
    installed = set(cp.installed_solvers())
    trials = []
    credible = None
    available = [x for x in solver_schedule if x[0] in installed]
    if not available:
        raise RuntimeError("Neither Clarabel nor SCS installed")
    for solver, kwargs in available:
        t0 = perf_counter()
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore",
                    message="Solution may be inaccurate.*", category=UserWarning)
                problem.solve(solver=solver, verbose=False, **kwargs)
        except (cp.error.SolverError, ValueError, ArithmeticError) as exc:
            trials.append({
                "solver":solver, "status":"solver_error",
                "exception_type":type(exc).__name__, "message":str(exc),
                "runtime_s":perf_counter()-t0,
            })
            continue

        trial = {
            "solver":solver, "status":str(problem.status),
            "runtime_s":perf_counter()-t0,
            "solve_time_s":getattr(problem.solver_stats,"solve_time",None),
            "num_iters":getattr(problem.solver_stats,"num_iters",None),
        }
        if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
            trials.append(trial)
            continue

        vals = {name:_float_expr(s) for name,s in slack_by_name.items()}
        hard_violations = [
            _float_expr(c.expr) for c in hard
        ]
        soft_violations = [
            _float_expr(con.expr - slack_by_name[name])
            for name,con in model.named_constraints.items()
            if name in slack_by_name
        ]
        if (
            any(v is None for v in vals.values())
            or any(v is None for v in hard_violations)
            or any(v is None for v in soft_violations)
        ):
            trial["reason"] = "missing_or_nonfinite_primal"
            trials.append(trial)
            continue
        hard_max = max([0.0]+[max(0.0,v) for v in hard_violations])
        soft_max = max([0.0]+[max(0.0,v) for v in soft_violations])
        objective_value = _float_expr(obj)
        total_slack = sum(max(0.0,v) for v in vals.values())
        credible_status = (
            problem.status == cp.OPTIMAL
            and hard_max <= numerical_violation_tol
            and soft_max <= numerical_violation_tol
            and objective_value is not None
            and abs(objective_value-total_slack) <=
                max(1e-4, 1e-5*max(1.0,abs(objective_value)))
        )
        trial.update(
            max_hard_normalized_residual=hard_max,
            max_elastic_normalized_residual=soft_max,
            raw_normalized_objective=objective_value,
            weighted_normalized_slack=total_slack,
            numerically_credible=credible_status,
        )
        trials.append(trial)
        if not credible_status:
            continue
        slacks = []
        for name,value in vals.items():
            family = constraint_family(name)
            scale,unit = relaxation_scale(instance,name)
            slacks.append({
                "constraint":name,
                "family":family,
                "normalized_slack":max(0.0,value),
                "physical_slack":max(0.0,value)*scale,
                "physical_unit":unit,
            })
        slacks.sort(key=lambda r:(-r["normalized_slack"],r["constraint"]))
        family_sums = {}
        family_max = {}
        family_counts = {}
        for row in slacks:
            fam=row["family"]
            family_sums[fam]=family_sums.get(fam,0.0)+row["normalized_slack"]
            family_max[fam]=max(family_max.get(fam,0.0),row["normalized_slack"])
            family_counts[fam]=family_counts.get(fam,0)+1
        credible = {
            "mode":mode,
            "solver":solver,
            "status":str(problem.status),
            "numerically_credible":True,
            "normalized_total_elastic_slack":total_slack,
            "normalized_max_elastic_slack":max(
                (r["normalized_slack"] for r in slacks), default=0.0,
            ),
            "max_hard_normalized_residual":hard_max,
            "max_elastic_normalized_residual":soft_max,
            "soft_constraint_count":len(slacks),
            "hard_constraint_count":len(hard),
            "slack_sum_by_family":family_sums,
            "slack_max_by_family":family_max,
            "n_slacks_by_family":family_counts,
            "nonzero_slack_counts_by_family":{
                f:sum(1 for r in slacks
                      if r["family"]==f and r["normalized_slack"]>1e-5)
                for f in family_counts
            },
            "top_constraints":[r for r in slacks
                               if r["normalized_slack"]>1e-7][:top_k],
            "top_dependency_context":_critical_dependencies(
                instance,solution,info,slacks,limit=top_k,
            ),
            "capacity_relaxation_interpretation":(
                "soft capacity is a counterfactual hardware expansion, "
                "not a feasible resource allocation on the real station"
                if bool(soft.intersection(CAPACITY_GROUPS)) else
                "actual MEC station capacities remain hard"
            ),
        }
        break
    return {
        **(credible or {
            "mode":mode,
            "status":trials[-1]["status"] if trials else "not_run",
            "solver":trials[-1]["solver"] if trials else None,
            "numerically_credible":False,
            "normalized_total_elastic_slack":None,
            "slack_sum_by_family":None,
            "top_constraints":[],
            "top_dependency_context":[],
        }),
        "diagnostic_build_and_solve_s":perf_counter()-started,
        "attempts":trials,
        "scope":"fixed_D_elastic_counterfactual_not_alns_repair",
        "algorithm_acceptance_unchanged":True,
    }
