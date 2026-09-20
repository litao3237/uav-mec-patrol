from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from uav_mec.domain import DiscreteSolution, Instance

ObjectiveEvaluator = Callable[[Instance, DiscreteSolution], float]


@dataclass
class UavMecState:
    """State adapter for the external ALNS package.

    The state stores only discrete decisions plus a list of temporarily removed
    tasks. Continuous communication/computing variables remain recourse
    decisions and are evaluated through the injected objective evaluator.
    """

    instance: Instance
    solution: DiscreteSolution
    evaluator: ObjectiveEvaluator
    removed_tasks: list[str] = field(default_factory=list)
    _objective_cache: float | None = field(default=None, init=False, repr=False)

    def objective(self) -> float:
        if self.removed_tasks:
            raise RuntimeError(
                "ALNS objective requested for a partially destroyed state: "
                f"{self.removed_tasks}"
            )
        if self._objective_cache is None:
            self._objective_cache = float(
                self.evaluator(self.instance, self.solution)
            )
        return self._objective_cache

    def get_context(self):
        """Context hook required only by context-aware ALNS selectors."""

        return None

    def copy(self) -> "UavMecState":
        return UavMecState(
            self.instance,
            deepcopy(self.solution),
            self.evaluator,
            list(self.removed_tasks),
        )

    def invalidate(self) -> None:
        self._objective_cache = None
