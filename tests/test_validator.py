from __future__ import annotations

from copy import deepcopy

import pytest

from uav_mec.domain import Route, RouteStop, TaskDecision
from uav_mec.evaluation import SolutionValidationError, validate_solution
from uav_mec.instances import build_small_instance


def test_small_solution_is_valid() -> None:
    instance, solution = build_small_instance()
    validate_solution(instance, solution)


def test_store_carry_precedence_is_checked() -> None:
    instance, solution = build_small_instance()
    bad = deepcopy(solution)
    bad.routes["U1"] = Route(
        "U1",
        (
            RouteStop.depot(),
            RouteStop.contact("V11"),
            RouteStop.task("S1"),
            RouteStop.task("S2"),
            RouteStop.task("S3"),
            RouteStop.depot(),
        ),
    )
    with pytest.raises(SolutionValidationError, match="Store-carry-offload"):
        validate_solution(instance, bad)


def test_unused_contact_is_rejected() -> None:
    instance, solution = build_small_instance()
    bad = deepcopy(solution)
    bad.task_decisions["S1"] = TaskDecision.local()
    bad.task_decisions["S2"] = TaskDecision.local()
    with pytest.raises(SolutionValidationError, match="serves no tasks"):
        validate_solution(instance, bad)
