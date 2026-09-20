from .analytic import (
    allocate_bandwidth_by_kkt,
    allocate_mec_cpu_by_kkt,
    local_cpu_from_shadow_price,
    rate_mbps,
    upload_time_prime,
    upload_time_s,
)
from .kkt_solver import KKTResourceSolverConfig, solve_kkt_resource_problem
from .precheck import FeasibilityPrecheckResult, fast_feasibility_precheck
from .reduced import ReducedResourceEvaluation, evaluate_reduced_resources
from .result import ResourceSolveResult
from .solver import CVXResourceSolver, KKTResourceSolver, ResourceSolver


def solve_resource_problem(*args, **kwargs):
    """Lazy wrapper around the CVXPY reference solver.

    Keeping CVXPY lazy allows the analytical KKT solver and data model to be
    imported in lightweight environments while retaining the same public API.
    """

    from .cvx_solver import solve_resource_problem as _impl

    return _impl(*args, **kwargs)


def verify_kkt(*args, **kwargs):
    from .kkt_verify import verify_kkt as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "CVXResourceSolver",
    "FeasibilityPrecheckResult",
    "KKTResourceSolver",
    "KKTResourceSolverConfig",
    "ReducedResourceEvaluation",
    "ResourceSolver",
    "ResourceSolveResult",
    "allocate_bandwidth_by_kkt",
    "allocate_mec_cpu_by_kkt",
    "evaluate_reduced_resources",
    "fast_feasibility_precheck",
    "local_cpu_from_shadow_price",
    "rate_mbps",
    "solve_kkt_resource_problem",
    "solve_resource_problem",
    "upload_time_prime",
    "upload_time_s",
    "verify_kkt",
]
