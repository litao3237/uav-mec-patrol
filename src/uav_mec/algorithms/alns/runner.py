from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from alns import ALNS
from alns.accept import RecordToRecordTravel
from alns.select import RouletteWheel
from alns.stop import MaxIterations

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
from .state import ObjectiveEvaluator, UavMecState


@dataclass(frozen=True)
class UavMecALNSConfig:
    iterations: int = 300
    seed: int = 100
    destroy: DestroyConfig = field(default_factory=DestroyConfig)
    operator_scores: tuple[float, float, float, float] = (
        25.0,
        5.0,
        1.0,
        0.0,
    )
    operator_decay: float = 0.8
    rrt_start_gap: float = 0.02
    rrt_end_gap: float = 0.0


@dataclass
class UavMecALNSResult:
    initial_solution: DiscreteSolution
    best_solution: DiscreteSolution
    initial_objective: float
    best_objective: float
    raw_result: Any
    evaluator: ObjectiveEvaluator


def run_uav_mec_alns(
    instance: Instance,
    *,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
) -> UavMecALNSResult:
    """Run the external ALNS framework on the UAV-MEC discrete problem.

    The mature ALNS package owns operator selection, adaptive weights,
    acceptance and stopping. This project supplies only the domain state,
    destroy/repair operators, and screened P1-R objective evaluation.
    """

    cfg = config or UavMecALNSConfig()
    if cfg.iterations <= 0:
        raise ValueError("ALNS iterations must be positive")

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

    for name, operator in destroy_operators:
        engine.add_destroy_operator(operator, name=name)
    for name, operator in repair_operators:
        engine.add_repair_operator(operator, name=name)

    select = RouletteWheel(
        scores=list(cfg.operator_scores),
        decay=cfg.operator_decay,
        num_destroy=len(destroy_operators),
        num_repair=len(repair_operators),
    )
    accept = RecordToRecordTravel.autofit(
        initial_objective,
        cfg.rrt_start_gap,
        cfg.rrt_end_gap,
        cfg.iterations,
    )
    stop = MaxIterations(cfg.iterations)

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

    return UavMecALNSResult(
        initial_solution=deepcopy(initial_solution),
        best_solution=deepcopy(best_state.solution),
        initial_objective=initial_objective,
        best_objective=float(best_state.objective()),
        raw_result=raw_result,
        evaluator=objective_evaluator,
    )
