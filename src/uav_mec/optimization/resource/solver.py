from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import EventInfo

from .kkt_solver import KKTResourceSolverConfig, solve_kkt_resource_problem
from .result import ResourceSolveResult


class ResourceSolver(Protocol):
    """Common interface consumed later by local search and ALNS."""

    def solve(
        self,
        instance: Instance,
        solution: DiscreteSolution,
        info: EventInfo | None = None,
    ) -> ResourceSolveResult: ...


@dataclass
class CVXResourceSolver:
    verbose: bool = False
    energy_tol_rel: float = 1e-6
    run_stage2: bool = True
    solver_profile: str = "default"

    def solve(
        self,
        instance: Instance,
        solution: DiscreteSolution,
        info: EventInfo | None = None,
    ) -> ResourceSolveResult:
        from .cvx_solver import solve_resource_problem

        return solve_resource_problem(
            instance,
            solution,
            info,
            verbose=self.verbose,
            energy_tol_rel=self.energy_tol_rel,
            run_stage2=self.run_stage2,
            solver_profile=self.solver_profile,
        )


@dataclass
class KKTResourceSolver:
    config: KKTResourceSolverConfig = field(default_factory=KKTResourceSolverConfig)

    def solve(
        self,
        instance: Instance,
        solution: DiscreteSolution,
        info: EventInfo | None = None,
    ) -> ResourceSolveResult:
        return solve_kkt_resource_problem(instance, solution, info, config=self.config)
