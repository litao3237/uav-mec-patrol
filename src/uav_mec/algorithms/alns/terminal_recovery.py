from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import (
    CVXResourceSolver,
    ResourceSolveResult,
)

from .continuous import (
    ContinuousESIConfig,
    ContinuousESIResult,
    run_uav_mec_continuous_esi_alns,
)
from .evaluator import (
    ScreenedProxyObjectiveEvaluator,
    solution_signature,
)
from .hybrid import Stage1CVXObjectiveOracle
from .problem_operators import strict_neighbor_recovery
from .runner import UavMecALNSConfig
from .state import ObjectiveEvaluator, UavMecState


@dataclass(frozen=True)
class TerminalRecoveryESIConfig:
    """Terminal-first strict recovery policy for continuous ESI.

    The main search keeps approximately the same generic exploration share as
    v2. A small outer reserve is held for terminal recertification/recovery.
    """

    total_runtime_s: float
    recovery_reserve_fraction: float = 0.08
    inner_final_cert_reserve_fraction: float = 0.02
    min_structural_recovery_runtime_s: float = 0.10


@dataclass
class TerminalRecoveryESIResult:
    continuous: ContinuousESIResult
    best_solution: DiscreteSolution
    final_cvx: ResourceSolveResult
    terminal_solution: DiscreteSolution
    terminal_recovery_cvx: ResourceSolveResult | None
    selection: str
    high_accuracy_attempted: bool
    high_accuracy_succeeded: bool
    structural_recovery_attempted: bool
    structural_recovery_succeeded: bool
    fallback_available: bool
    fallback_used: bool
    recovery_runtime_s: float
    total_runtime_s: float
    recovery_oracle_calls: int
    recovery_oracle_cache_hits: int
    recovery_stats: dict[str, Any] | None

    @property
    def final_energy_j(self) -> float:
        return float(self.final_cvx.energy_stage1_j)


def _stage1_status(result: ResourceSolveResult) -> str:
    return str(
        result.diagnostics.get(
            "stage1_status",
            result.status,
        )
    )


def _strict(result: ResourceSolveResult) -> bool:
    return bool(
        result.feasible
        and _stage1_status(result) == "optimal"
    )


def _validate_policy(policy: TerminalRecoveryESIConfig) -> None:
    if policy.total_runtime_s <= 0.0:
        raise ValueError("total_runtime_s must be positive")
    if not 0.0 < policy.recovery_reserve_fraction < 0.5:
        raise ValueError(
            "recovery_reserve_fraction must be in (0, 0.5)"
        )
    if not 0.0 < policy.inner_final_cert_reserve_fraction < 0.5:
        raise ValueError(
            "inner_final_cert_reserve_fraction must be in (0, 0.5)"
        )
    if policy.min_structural_recovery_runtime_s < 0.0:
        raise ValueError(
            "min_structural_recovery_runtime_s must be non-negative"
        )


def run_uav_mec_terminal_recovery_esi_alns(
    instance: Instance,
    *,
    terminal: TerminalRecoveryESIConfig,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    continuous_config: ContinuousESIConfig | None = None,
    search_oracle: Stage1CVXObjectiveOracle | None = None,
) -> TerminalRecoveryESIResult:
    """Run continuous ESI, then recover the terminal candidate if necessary.

    Selection priority:

    1. terminal screened-best if it is already strict-certified;
    2. the same terminal structure after a fresh high-accuracy recertification;
    3. a nearby strict structural recovery of that terminal state;
    4. the continuous-search strict archive as a fallback;
    5. the terminal candidate itself if no strict solution exists.

    This makes the strict archive insurance rather than the unconditional
    returned solution.
    """

    _validate_policy(terminal)
    started = perf_counter()
    objective_evaluator = (
        evaluator or ScreenedProxyObjectiveEvaluator()
    )
    base_cfg = config or UavMecALNSConfig()
    oracle = search_oracle or Stage1CVXObjectiveOracle()

    inner_runtime_s = (
        terminal.total_runtime_s
        * (1.0 - terminal.recovery_reserve_fraction)
    )
    if continuous_config is None:
        continuous_cfg = ContinuousESIConfig(
            total_runtime_s=inner_runtime_s,
            final_cert_reserve_fraction=(
                terminal.inner_final_cert_reserve_fraction
            ),
        )
    else:
        continuous_cfg = replace(
            continuous_config,
            total_runtime_s=inner_runtime_s,
            final_cert_reserve_fraction=(
                terminal.inner_final_cert_reserve_fraction
            ),
        )

    continuous_result = run_uav_mec_continuous_esi_alns(
        instance,
        initial_solution=initial_solution,
        config=base_cfg,
        continuous=continuous_cfg,
        evaluator=objective_evaluator,
        elite_oracle=oracle,
    )

    terminal_solution = deepcopy(
        continuous_result.exploration.best_solution
    )
    terminal_signature = solution_signature(terminal_solution)
    fallback_signature = solution_signature(
        continuous_result.best_solution
    )
    fallback_available = bool(
        continuous_result.strict_incumbent_found
        and _strict(continuous_result.final_cvx)
    )

    # If v2 already returned this exact terminal structure with a strict
    # certificate, no extra solver work is needed.
    if (
        fallback_available
        and terminal_signature == fallback_signature
    ):
        validate_solution(instance, terminal_solution)
        return TerminalRecoveryESIResult(
            continuous=continuous_result,
            best_solution=terminal_solution,
            final_cvx=continuous_result.final_cvx,
            terminal_solution=terminal_solution,
            terminal_recovery_cvx=continuous_result.final_cvx,
            selection="terminal_already_strict",
            high_accuracy_attempted=False,
            high_accuracy_succeeded=False,
            structural_recovery_attempted=False,
            structural_recovery_succeeded=False,
            fallback_available=True,
            fallback_used=False,
            recovery_runtime_s=0.0,
            total_runtime_s=perf_counter() - started,
            recovery_oracle_calls=0,
            recovery_oracle_cache_hits=0,
            recovery_stats=None,
        )

    recovery_started = perf_counter()
    recovery_oracle = Stage1CVXObjectiveOracle(
        CVXResourceSolver(
            run_stage2=False,
            solver_profile="recovery",
        )
    )

    high_accuracy_attempted = True
    terminal_cvx = recovery_oracle.solve(
        instance,
        terminal_solution,
    )
    high_accuracy_succeeded = _strict(terminal_cvx)

    if high_accuracy_succeeded:
        validate_solution(instance, terminal_solution)
        return TerminalRecoveryESIResult(
            continuous=continuous_result,
            best_solution=terminal_solution,
            final_cvx=terminal_cvx,
            terminal_solution=terminal_solution,
            terminal_recovery_cvx=terminal_cvx,
            selection="terminal_recertified",
            high_accuracy_attempted=high_accuracy_attempted,
            high_accuracy_succeeded=True,
            structural_recovery_attempted=False,
            structural_recovery_succeeded=False,
            fallback_available=fallback_available,
            fallback_used=False,
            recovery_runtime_s=perf_counter() - recovery_started,
            total_runtime_s=perf_counter() - started,
            recovery_oracle_calls=recovery_oracle.calls,
            recovery_oracle_cache_hits=recovery_oracle.cache_hits,
            recovery_stats=None,
        )

    elapsed = perf_counter() - started
    remaining_s = terminal.total_runtime_s - elapsed
    structural_attempted = bool(
        remaining_s
        >= terminal.min_structural_recovery_runtime_s
    )
    structural_succeeded = False
    recovery_stats: dict[str, Any] | None = None
    recovered_solution: DiscreteSolution | None = None
    recovered_cvx: ResourceSolveResult | None = None

    if structural_attempted:
        state = UavMecState(
            instance,
            deepcopy(terminal_solution),
            objective_evaluator,
        )
        recovered_state, recovery_stats = strict_neighbor_recovery(
            state,
            config=base_cfg.problem,
            objective=recovery_oracle,
            max_runtime_s=max(0.0, remaining_s),
        )
        if bool(recovery_stats.get("recovered", False)):
            candidate = deepcopy(recovered_state.solution)
            candidate_cvx = recovery_oracle.solve(
                instance,
                candidate,
            )
            if _strict(candidate_cvx):
                structural_succeeded = True
                recovered_solution = candidate
                recovered_cvx = candidate_cvx

    if (
        structural_succeeded
        and recovered_solution is not None
        and recovered_cvx is not None
    ):
        best_solution = recovered_solution
        final_cvx = recovered_cvx
        selection = "terminal_neighbor_recovered"
        fallback_used = False
    elif fallback_available:
        best_solution = deepcopy(continuous_result.best_solution)
        final_cvx = continuous_result.final_cvx
        selection = "strict_archive_fallback"
        fallback_used = True
    else:
        best_solution = terminal_solution
        final_cvx = terminal_cvx
        selection = "terminal_nonstrict_no_fallback"
        fallback_used = False

    validate_solution(instance, best_solution)
    return TerminalRecoveryESIResult(
        continuous=continuous_result,
        best_solution=best_solution,
        final_cvx=final_cvx,
        terminal_solution=terminal_solution,
        terminal_recovery_cvx=terminal_cvx,
        selection=selection,
        high_accuracy_attempted=high_accuracy_attempted,
        high_accuracy_succeeded=high_accuracy_succeeded,
        structural_recovery_attempted=structural_attempted,
        structural_recovery_succeeded=structural_succeeded,
        fallback_available=fallback_available,
        fallback_used=fallback_used,
        recovery_runtime_s=perf_counter() - recovery_started,
        total_runtime_s=perf_counter() - started,
        recovery_oracle_calls=recovery_oracle.calls,
        recovery_oracle_cache_hits=recovery_oracle.cache_hits,
        recovery_stats=recovery_stats,
    )
