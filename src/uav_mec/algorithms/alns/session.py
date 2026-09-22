from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np
from alns import Outcome
from alns.accept import RecordToRecordTravel

from uav_mec.algorithms.initial import (
    build_greedy_initial_solution,
    build_mec_assisted_initial_solution,
)
from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation.validator import validate_solution

from .evaluator import ScreenedProxyObjectiveEvaluator
from .operators import make_destroy_operators, make_repair_operators
from .problem_operators import (
    make_problem_destroy_operators,
    make_problem_repair_operators,
)
from .runner import (
    UavMecALNSConfig,
    _TimeScaledRecordToRecordTravel,
    _TrackingRouletteWheel,
    _filter_operator_profile,
    _operator_coupling,
)
from .state import ObjectiveEvaluator, UavMecState


@dataclass
class UavMecALNSSegmentResult:
    """One resumable ALNS segment."""

    best_solution: DiscreteSolution
    current_solution: DiscreteSolution
    best_objective: float
    current_objective: float
    iterations: int
    runtime_s: float
    total_iterations: int
    operator_pair_counts: dict[str, list[int]]


@dataclass
class UavMecALNSCheckpoint:
    """Paused ALNS state suitable for independent paired forks."""

    instance: Instance
    config: UavMecALNSConfig
    initial_solution: DiscreteSolution
    initial_objective: float
    current_solution: DiscreteSolution
    best_solution: DiscreteSolution
    evaluator: ObjectiveEvaluator
    selector: _TrackingRouletteWheel
    acceptance: Any
    rng_state: dict[str, Any]
    iterations_completed: int
    search_runtime_s: float

    def fork(self) -> "UavMecALNSSession":
        """Restore an independent session from exactly this checkpoint."""

        evaluator = deepcopy(self.evaluator)
        current_state = UavMecState(
            self.instance,
            deepcopy(self.current_solution),
            evaluator,
        )
        best_state = UavMecState(
            self.instance,
            deepcopy(self.best_solution),
            evaluator,
        )

        rng = np.random.default_rng()
        rng.bit_generator.state = deepcopy(self.rng_state)

        selector = deepcopy(self.selector)
        if isinstance(
            self.acceptance,
            _TimeScaledRecordToRecordTravel,
        ):
            acceptance = self.acceptance.checkpoint_copy()
        else:
            acceptance = deepcopy(self.acceptance)

        return UavMecALNSSession._restore(
            instance=self.instance,
            config=self.config,
            initial_solution=deepcopy(self.initial_solution),
            initial_objective=self.initial_objective,
            evaluator=evaluator,
            current_state=current_state,
            best_state=best_state,
            rng=rng,
            selector=selector,
            acceptance=acceptance,
            iterations_completed=self.iterations_completed,
            search_runtime_s=self.search_runtime_s,
        )


class UavMecALNSSession:
    """Resumable ALNS trajectory for paired-checkpoint experiments.

    The session owns current state, historical best, RNG, adaptive selector
    weights and RRT progress. A second ordinary ALNS call would reset these.
    """

    def __init__(
        self,
        instance: Instance,
        *,
        initial_solution: DiscreteSolution | None = None,
        config: UavMecALNSConfig | None = None,
        evaluator: ObjectiveEvaluator | None = None,
    ) -> None:
        cfg = config or UavMecALNSConfig()
        _validate_session_config(cfg)

        if initial_solution is None:
            route_seed = build_greedy_initial_solution(instance)
            initial_solution = build_mec_assisted_initial_solution(
                instance,
                base_solution=route_seed,
            )
        else:
            initial_solution = deepcopy(initial_solution)

        validate_solution(instance, initial_solution)
        objective_evaluator = (
            evaluator or ScreenedProxyObjectiveEvaluator()
        )
        initial_state = UavMecState(
            instance,
            initial_solution,
            objective_evaluator,
        )
        initial_objective = float(initial_state.objective())

        rng = np.random.default_rng(cfg.seed)
        destroy_operators, repair_operators = _build_operators(cfg)
        selector = _build_selector(
            cfg,
            destroy_operators,
            repair_operators,
        )
        acceptance = _build_acceptance(
            cfg,
            initial_objective,
        )

        self.instance = instance
        self.config = cfg
        self.initial_solution = deepcopy(initial_solution)
        self.initial_objective = initial_objective
        self.evaluator = objective_evaluator
        self.current_state = initial_state
        self.best_state = initial_state.copy()
        self.rng = rng
        self.destroy_operators = destroy_operators
        self.repair_operators = repair_operators
        self.selector = selector
        self.acceptance = acceptance
        self.iterations_completed = 0
        self.search_runtime_s = 0.0

    @classmethod
    def _restore(
        cls,
        *,
        instance: Instance,
        config: UavMecALNSConfig,
        initial_solution: DiscreteSolution,
        initial_objective: float,
        evaluator: ObjectiveEvaluator,
        current_state: UavMecState,
        best_state: UavMecState,
        rng: np.random.Generator,
        selector: _TrackingRouletteWheel,
        acceptance: Any,
        iterations_completed: int,
        search_runtime_s: float,
    ) -> "UavMecALNSSession":
        self = cls.__new__(cls)
        destroy_operators, repair_operators = _build_operators(config)

        self.instance = instance
        self.config = config
        self.initial_solution = initial_solution
        self.initial_objective = float(initial_objective)
        self.evaluator = evaluator
        self.current_state = current_state
        self.best_state = best_state
        self.rng = rng
        self.destroy_operators = destroy_operators
        self.repair_operators = repair_operators
        self.selector = selector
        self.acceptance = acceptance
        self.iterations_completed = int(iterations_completed)
        self.search_runtime_s = float(search_runtime_s)
        return self

    def run_segment(
        self,
        *,
        max_runtime_s: float | None = None,
        max_iterations: int | None = None,
    ) -> UavMecALNSSegmentResult:
        """Advance the same ALNS trajectory for one additional segment."""

        if max_runtime_s is None and max_iterations is None:
            raise ValueError(
                "run_segment requires max_runtime_s or max_iterations"
            )
        if max_runtime_s is not None and max_runtime_s < 0.0:
            raise ValueError("max_runtime_s must be non-negative")
        if max_iterations is not None and max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")

        started = perf_counter()
        segment_iterations = 0

        while True:
            elapsed = perf_counter() - started
            if (
                max_runtime_s is not None
                and elapsed >= max_runtime_s
            ):
                break
            if (
                max_iterations is not None
                and segment_iterations >= max_iterations
            ):
                break

            d_idx, r_idx = self.selector(
                self.rng,
                self.best_state,
                self.current_state,
            )
            _, destroy = self.destroy_operators[d_idx]
            _, repair = self.repair_operators[r_idx]

            destroyed = destroy(
                self.current_state,
                self.rng,
            )
            candidate = repair(
                destroyed,
                self.rng,
            )

            self.best_state, self.current_state, outcome = (
                _evaluate_candidate(
                    self.rng,
                    self.acceptance,
                    self.best_state,
                    self.current_state,
                    candidate,
                )
            )
            self.selector.update(
                candidate,
                d_idx,
                r_idx,
                outcome,
            )

            segment_iterations += 1
            self.iterations_completed += 1

        runtime_s = perf_counter() - started
        self.search_runtime_s += runtime_s

        if self.best_state.removed_tasks:
            raise RuntimeError(
                "ALNS session produced a partially repaired best state"
            )
        if self.current_state.removed_tasks:
            raise RuntimeError(
                "ALNS session produced a partially repaired current state"
            )

        validate_solution(
            self.instance,
            self.best_state.solution,
        )
        validate_solution(
            self.instance,
            self.current_state.solution,
        )

        return UavMecALNSSegmentResult(
            best_solution=deepcopy(self.best_state.solution),
            current_solution=deepcopy(self.current_state.solution),
            best_objective=float(self.best_state.objective()),
            current_objective=float(self.current_state.objective()),
            iterations=segment_iterations,
            runtime_s=runtime_s,
            total_iterations=self.iterations_completed,
            operator_pair_counts=self.selector.pair_counts,
        )

    def checkpoint(self) -> UavMecALNSCheckpoint:
        """Pause the trajectory without charging idle wall time to RRT."""

        acceptance = self.acceptance
        if isinstance(
            acceptance,
            _TimeScaledRecordToRecordTravel,
        ):
            acceptance = acceptance.checkpoint_copy()
        else:
            acceptance = deepcopy(acceptance)

        return UavMecALNSCheckpoint(
            instance=self.instance,
            config=self.config,
            initial_solution=deepcopy(self.initial_solution),
            initial_objective=self.initial_objective,
            current_solution=deepcopy(self.current_state.solution),
            best_solution=deepcopy(self.best_state.solution),
            evaluator=deepcopy(self.evaluator),
            selector=deepcopy(self.selector),
            acceptance=acceptance,
            rng_state=deepcopy(self.rng.bit_generator.state),
            iterations_completed=self.iterations_completed,
            search_runtime_s=self.search_runtime_s,
        )


def _validate_session_config(cfg: UavMecALNSConfig) -> None:
    if cfg.iterations <= 0:
        raise ValueError("ALNS iterations must be positive")
    if cfg.max_runtime_s is not None and cfg.max_runtime_s <= 0.0:
        raise ValueError(
            "session config max_runtime_s must be positive when supplied"
        )
    if cfg.time_scaled_rrt and cfg.max_runtime_s is None:
        raise ValueError(
            "time_scaled_rrt requires config.max_runtime_s as the "
            "full logical RRT horizon"
        )


def _build_operators(cfg: UavMecALNSConfig):
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

    return _filter_operator_profile(
        destroy_operators,
        repair_operators,
        enabled=cfg.enable_problem_operators,
        profile=cfg.problem_operator_profile,
    )


def _build_selector(
    cfg: UavMecALNSConfig,
    destroy_operators,
    repair_operators,
) -> _TrackingRouletteWheel:
    coupling = _operator_coupling(
        destroy_operators,
        repair_operators,
    )
    return _TrackingRouletteWheel(
        scores=list(cfg.operator_scores),
        decay=cfg.operator_decay,
        num_destroy=len(destroy_operators),
        num_repair=len(repair_operators),
        op_coupling=coupling,
        destroy_names=[
            name for name, _ in destroy_operators
        ],
        repair_names=[
            name for name, _ in repair_operators
        ],
    )


def _build_acceptance(
    cfg: UavMecALNSConfig,
    initial_objective: float,
):
    if cfg.time_scaled_rrt:
        assert cfg.max_runtime_s is not None
        return _TimeScaledRecordToRecordTravel(
            initial_objective,
            cfg.rrt_start_gap,
            cfg.rrt_end_gap,
            cfg.max_runtime_s,
        )

    return RecordToRecordTravel.autofit(
        initial_objective,
        cfg.rrt_start_gap,
        cfg.rrt_end_gap,
        cfg.iterations,
    )


def _evaluate_candidate(
    rng: np.random.Generator,
    accept,
    best: UavMecState,
    current: UavMecState,
    candidate: UavMecState,
) -> tuple[UavMecState, UavMecState, Outcome]:
    """Mirror the pinned alns<8 candidate-evaluation semantics."""

    best_obj = float(best.objective())
    curr_obj = float(current.objective())
    cand_obj = float(candidate.objective())

    if cand_obj < best_obj:
        return candidate, candidate, Outcome.BEST

    if accept(rng, best, current, candidate):
        outcome = (
            Outcome.BETTER
            if cand_obj < curr_obj
            else Outcome.ACCEPT
        )
        return best, candidate, outcome

    return best, current, Outcome.REJECT
