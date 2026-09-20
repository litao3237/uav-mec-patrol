from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from uav_mec.domain import DiscreteSolution, Instance

ObjectiveEvaluator = Callable[[Instance, DiscreteSolution], float]


@dataclass
class UavMecState:
    """State adapter reserved for the external `alns` package.

    The state intentionally contains only the discrete solution. Resource variables
    are recourse decisions and should be evaluated by the injected evaluator.
    """

    instance: Instance
    solution: DiscreteSolution
    evaluator: ObjectiveEvaluator
    _objective_cache: float | None = field(default=None, init=False, repr=False)

    def objective(self) -> float:
        if self._objective_cache is None:
            self._objective_cache = float(self.evaluator(self.instance, self.solution))
        return self._objective_cache

    def copy(self) -> "UavMecState":
        return UavMecState(self.instance, deepcopy(self.solution), self.evaluator)

    def invalidate(self) -> None:
        self._objective_cache = None
