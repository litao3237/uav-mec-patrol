from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import numpy as np
from alns import ALNS
from alns.accept import RecordToRecordTravel
from alns.select import RouletteWheel
from alns.stop import MaxIterations, MaxRuntime

from uav_mec.algorithms.initial import (
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
)
from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation.validator import validate_solution

from .evaluator import ScreenedProxyObjectiveEvaluator
from .operators import (
    DestroyConfig,
    make_destroy_operators,
    make_repair_operators,
)
from .problem_operators import (
    ProblemOperatorConfig,
    make_problem_destroy_operators,
    make_problem_repair_operators,
)
from .state import ObjectiveEvaluator, UavMecState


class _TimeScaledRecordToRecordTravel:
    """RRT whose threshold follows elapsed wall-clock time.

    The stock ALNS RRT cools once per iteration. Under a wall-clock stopping
    rule, scenario-dependent operator/evaluator costs then change the effective
    cooling schedule. This experimental criterion keeps the start/end gap tied
    to the fraction of the requested runtime that has elapsed.
    """

    def __init__(
        self,
        init_obj: float,
        start_gap: float,
        end_gap: float,
        max_runtime_s: float,
        *,
        started_at: float | None = None,
    ) -> None:
        if not (0.0 <= end_gap <= start_gap):
            raise ValueError("Must have 0 <= end_gap <= start_gap")
        if max_runtime_s <= 0.0:
            raise ValueError("max_runtime_s must be positive")

        self.start_threshold = start_gap * init_obj
        self.end_threshold = end_gap * init_obj
        self.max_runtime_s = max_runtime_s
        self._started: float | None = started_at
        self.last_threshold = self.start_threshold

    def __call__(self, rng, best, current, candidate) -> bool:
        del rng, current
        now = perf_counter()
        if self._started is None:
            self._started = now

        elapsed = max(0.0, now - self._started)
        progress = min(1.0, elapsed / self.max_runtime_s)
        threshold = (
            self.start_threshold
            + (self.end_threshold - self.start_threshold) * progress
        )
        self.last_threshold = threshold
        return (
            candidate.objective() - best.objective()
            <= threshold
        )


class _MaxRuntimeOrStagnation:
    """Stop on total runtime or lack of best-objective improvement."""

    def __init__(
        self,
        max_runtime_s: float,
        *,
        stagnation_runtime_s: float | None = None,
        min_runtime_s: float = 0.0,
        improvement_tol: float = 1e-12,
    ) -> None:
        if max_runtime_s < 0.0:
            raise ValueError("max_runtime_s must be non-negative")
        if (
            stagnation_runtime_s is not None
            and stagnation_runtime_s <= 0.0
        ):
            raise ValueError(
                "stagnation_runtime_s must be positive"
            )
        if min_runtime_s < 0.0:
            raise ValueError("min_runtime_s must be non-negative")

        self.max_runtime_s = max_runtime_s
        self.stagnation_runtime_s = stagnation_runtime_s
        self.min_runtime_s = min_runtime_s
        self.improvement_tol = improvement_tol

        self._started: float | None = None
        self._last_improvement: float | None = None
        self._best_objective: float | None = None
        self.stop_reason: str | None = None
        self.elapsed_s: float = 0.0
        self.last_improvement_elapsed_s: float = 0.0

    def __call__(self, rng, best, current) -> bool:
        del rng, current
        now = perf_counter()
        best_obj = float(best.objective())

        if self._started is None:
            self._started = now
            self._last_improvement = now
            self._best_objective = best_obj

        assert self._started is not None
        assert self._last_improvement is not None
        assert self._best_objective is not None

        if best_obj < self._best_objective - self.improvement_tol:
            self._best_objective = best_obj
            self._last_improvement = now

        self.elapsed_s = now - self._started
        self.last_improvement_elapsed_s = (
            self._last_improvement - self._started
        )

        if self.elapsed_s >= self.max_runtime_s:
            self.stop_reason = "runtime"
            return True

        if (
            self.stagnation_runtime_s is not None
            and self.elapsed_s >= self.min_runtime_s
            and now - self._last_improvement
            >= self.stagnation_runtime_s
        ):
            self.stop_reason = "stagnation"
            return True

        return False


def _filter_operator_profile(
    destroy_operators,
    repair_operators,
    *,
    enabled: bool,
    profile: str,
):
    if not enabled:
        return destroy_operators, repair_operators

    valid_profiles = {"core", "full"}
    if profile not in valid_profiles:
        raise ValueError(
            f"Unknown problem_operator_profile={profile!r}; "
            f"expected one of {sorted(valid_profiles)}"
        )

    if profile == "full":
        return destroy_operators, repair_operators

    destroy_keep = {
        "random_task_removal",
        "critical_task_removal",
        "shared_mec_pressure_removal",
    }
    repair_keep = {
        "cheapest_insertion_mec_repair",
        "regret2_insertion_mec_repair",
        "contact_opportunity_repair",
        "mode_batch_repair",
    }

    return (
        [item for item in destroy_operators if item[0] in destroy_keep],
        [item for item in repair_operators if item[0] in repair_keep],
    )


def _operator_coupling(
    destroy_operators,
    repair_operators,
) -> np.ndarray:
    """Restrict semantically weak destroy/repair pairings."""

    d_names = [name for name, _ in destroy_operators]
    r_names = [name for name, _ in repair_operators]
    coupling = np.ones(
        (len(d_names), len(r_names)),
        dtype=bool,
    )

    preferred: dict[str, set[str]] = {
        "route_segment_removal": {
            "cheapest_insertion_mec_repair",
            "regret2_insertion_mec_repair",
            "compute_aware_insertion_repair",
        },
        "mec_batch_pressure_removal": {
            "regret2_insertion_mec_repair",
            "contact_opportunity_repair",
            "mode_batch_repair",
        },
        "shared_mec_pressure_removal": {
            "regret2_insertion_mec_repair",
            "contact_opportunity_repair",
            "mode_batch_repair",
        },
    }

    for d_idx, d_name in enumerate(d_names):
        allowed = preferred.get(d_name)
        if allowed is None:
            continue
        coupling[d_idx, :] = [
            r_name in allowed
            for r_name in r_names
        ]

    return coupling


class _TrackingRouletteWheel(RouletteWheel):
    """Roulette wheel with destroy-repair pair outcome diagnostics."""

    def __init__(
        self,
        *args,
        destroy_names: list[str],
        repair_names: list[str],
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._destroy_names = destroy_names
        self._repair_names = repair_names
        self._pair_counts: dict[str, list[int]] = {}

    @property
    def pair_counts(self) -> dict[str, list[int]]:
        return {
            key: list(values)
            for key, values in self._pair_counts.items()
        }

    def update(self, cand, d_idx, r_idx, outcome):
        key = (
            f"{self._destroy_names[d_idx]}"
            f" -> {self._repair_names[r_idx]}"
        )
        counts = self._pair_counts.setdefault(
            key,
            [0, 0, 0, 0],
        )
        counts[outcome] += 1
        super().update(
            cand,
            d_idx,
            r_idx,
            outcome,
        )


@dataclass(frozen=True)
class UavMecALNSConfig:
    iterations: int = 300
    seed: int = 100
    destroy: DestroyConfig = field(default_factory=DestroyConfig)
    problem: ProblemOperatorConfig = field(
        default_factory=ProblemOperatorConfig
    )
    enable_problem_operators: bool = False
    problem_operator_profile: str = "core"
    operator_scores: tuple[float, float, float, float] = (
        25.0,
        5.0,
        1.0,
        0.0,
    )
    operator_decay: float = 0.8
    rrt_start_gap: float = 0.02
    rrt_end_gap: float = 0.0
    max_runtime_s: float | None = None
    time_scaled_rrt: bool = False
    stagnation_runtime_s: float | None = None
    min_runtime_s: float = 0.0


@dataclass
class UavMecALNSResult:
    initial_solution: DiscreteSolution
    best_solution: DiscreteSolution
    initial_objective: float
    best_objective: float
    raw_result: Any
    evaluator: ObjectiveEvaluator
    operator_pair_counts: dict[str, list[int]]
    stop_reason: str = "iterations"
    stop_elapsed_s: float | None = None
    last_improvement_elapsed_s: float | None = None


def run_uav_mec_alns(
    instance: Instance,
    *,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    acceptance_criterion: Any | None = None,
    stopping_criterion: Any | None = None,
) -> UavMecALNSResult:
    """Run the external ALNS framework on the UAV-MEC discrete problem.

    The mature ALNS package owns operator selection, adaptive weights,
    acceptance and stopping. This project supplies only the domain state,
    destroy/repair operators, and screened P1-R objective evaluation.

    Experimental wall-clock controls are opt-in. Existing fixed-iteration and
    legacy MaxRuntime behaviour remain unchanged unless the corresponding
    config flags are enabled.
    """

    cfg = config or UavMecALNSConfig()
    if cfg.iterations <= 0:
        raise ValueError("ALNS iterations must be positive")
    if cfg.max_runtime_s is not None and cfg.max_runtime_s < 0:
        raise ValueError("ALNS max_runtime_s must be non-negative")
    if cfg.time_scaled_rrt and cfg.max_runtime_s is None:
        raise ValueError(
            "time_scaled_rrt requires max_runtime_s"
        )
    if (
        cfg.stagnation_runtime_s is not None
        and cfg.max_runtime_s is None
    ):
        raise ValueError(
            "stagnation_runtime_s requires max_runtime_s"
        )
    if (
        cfg.stagnation_runtime_s is not None
        and cfg.stagnation_runtime_s <= 0.0
    ):
        raise ValueError(
            "stagnation_runtime_s must be positive"
        )
    if cfg.min_runtime_s < 0.0:
        raise ValueError("min_runtime_s must be non-negative")

    if initial_solution is None:
        route_seed = build_greedy_initial_solution(instance)
        initial_solution = build_mec_assisted_initial_solution(
            instance,
            base_solution=route_seed,
        )
    else:
        initial_solution = deepcopy(initial_solution)

    validate_solution(instance, initial_solution)
    objective_evaluator = evaluator or ScreenedProxyObjectiveEvaluator()
    initial_state = UavMecState(
        instance,
        initial_solution,
        objective_evaluator,
    )
    initial_objective = initial_state.objective()

    engine = ALNS(np.random.default_rng(cfg.seed))

    destroy_operators = make_destroy_operators(cfg.destroy)
    repair_operators = make_repair_operators()
    if cfg.enable_problem_operators:
        destroy_operators += make_problem_destroy_operators(
            cfg.destroy,
            cfg.problem,
        )
        repair_operators += make_problem_repair_operators(
            cfg.problem,
        )

    destroy_operators, repair_operators = _filter_operator_profile(
        destroy_operators,
        repair_operators,
        enabled=cfg.enable_problem_operators,
        profile=cfg.problem_operator_profile,
    )
    op_coupling = _operator_coupling(
        destroy_operators,
        repair_operators,
    )

    for name, operator in destroy_operators:
        engine.add_destroy_operator(operator, name=name)
    for name, operator in repair_operators:
        engine.add_repair_operator(operator, name=name)

    select = _TrackingRouletteWheel(
        scores=list(cfg.operator_scores),
        decay=cfg.operator_decay,
        num_destroy=len(destroy_operators),
        num_repair=len(repair_operators),
        op_coupling=op_coupling,
        destroy_names=[
            name for name, _ in destroy_operators
        ],
        repair_names=[
            name for name, _ in repair_operators
        ],
    )

    if acceptance_criterion is not None:
        accept = acceptance_criterion
    elif cfg.time_scaled_rrt:
        assert cfg.max_runtime_s is not None
        accept = _TimeScaledRecordToRecordTravel(
            initial_objective,
            cfg.rrt_start_gap,
            cfg.rrt_end_gap,
            cfg.max_runtime_s,
        )
    else:
        accept = RecordToRecordTravel.autofit(
            initial_objective,
            cfg.rrt_start_gap,
            cfg.rrt_end_gap,
            cfg.iterations,
        )

    tracked_stop: _MaxRuntimeOrStagnation | None = None
    if stopping_criterion is not None:
        stop = stopping_criterion
        stop_reason = "custom"
    elif cfg.max_runtime_s is None:
        stop = MaxIterations(cfg.iterations)
        stop_reason = "iterations"
    elif cfg.stagnation_runtime_s is not None:
        tracked_stop = _MaxRuntimeOrStagnation(
            cfg.max_runtime_s,
            stagnation_runtime_s=cfg.stagnation_runtime_s,
            min_runtime_s=cfg.min_runtime_s,
        )
        stop = tracked_stop
        stop_reason = "runtime"
    else:
        stop = MaxRuntime(cfg.max_runtime_s)
        stop_reason = "runtime"

    raw_result = engine.iterate(
        initial_state,
        select,
        accept,
        stop,
    )
    best_state = raw_result.best_state
    if best_state.removed_tasks:
        raise RuntimeError(
            "ALNS returned a partially repaired best state"
        )
    validate_solution(instance, best_state.solution)

    stop_elapsed_s = None
    last_improvement_elapsed_s = None
    if tracked_stop is not None:
        stop_reason = tracked_stop.stop_reason or stop_reason
        stop_elapsed_s = tracked_stop.elapsed_s
        last_improvement_elapsed_s = (
            tracked_stop.last_improvement_elapsed_s
        )
    elif stopping_criterion is not None:
        stop_reason = str(
            getattr(
                stopping_criterion,
                "stop_reason",
                stop_reason,
            )
        )
        stop_elapsed_s = getattr(
            stopping_criterion,
            "elapsed_s",
            None,
        )
        last_improvement_elapsed_s = getattr(
            stopping_criterion,
            "last_improvement_elapsed_s",
            None,
        )

    return UavMecALNSResult(
        initial_solution=deepcopy(initial_solution),
        best_solution=deepcopy(best_state.solution),
        initial_objective=initial_objective,
        best_objective=float(best_state.objective()),
        raw_result=raw_result,
        evaluator=objective_evaluator,
        operator_pair_counts=select.pair_counts,
        stop_reason=stop_reason,
        stop_elapsed_s=stop_elapsed_s,
        last_improvement_elapsed_s=(
            last_improvement_elapsed_s
        ),
    )
