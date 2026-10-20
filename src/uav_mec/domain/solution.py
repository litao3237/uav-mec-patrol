from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Tuple

from .enums import ExecutionMode, StopType


@dataclass(frozen=True)
class RouteStop:
    kind: StopType
    ref_id: str = "DEPOT"

    @staticmethod
    def depot() -> "RouteStop":
        return RouteStop(StopType.DEPOT, "DEPOT")

    @staticmethod
    def task(task_id: str) -> "RouteStop":
        return RouteStop(StopType.TASK, task_id)

    @staticmethod
    def contact(visit_id: str) -> "RouteStop":
        return RouteStop(StopType.CONTACT, visit_id)

    @property
    def label(self) -> str:
        return "DEPOT" if self.kind is StopType.DEPOT else self.ref_id


@dataclass(frozen=True)
class Route:
    uav_id: str
    stops: Tuple[RouteStop, ...]

    def labels(self) -> list[str]:
        return [stop.label for stop in self.stops]

    def task_ids(self) -> list[str]:
        return [s.ref_id for s in self.stops if s.kind is StopType.TASK]

    def contact_visit_ids(self) -> list[str]:
        return [s.ref_id for s in self.stops if s.kind is StopType.CONTACT]


@dataclass(frozen=True)
class ContactVisit:
    visit_id: str
    uav_id: str
    point_id: str


@dataclass(frozen=True)
class TaskDecision:
    mode: ExecutionMode
    contact_visit_id: str | None = None

    @staticmethod
    def local() -> "TaskDecision":
        return TaskDecision(ExecutionMode.LOCAL, None)

    @staticmethod
    def offload(contact_visit_id: str) -> "TaskDecision":
        return TaskDecision(ExecutionMode.OFFLOAD, contact_visit_id)


@dataclass
class DiscreteSolution:
    routes: Dict[str, Route]
    contact_visits: Dict[str, ContactVisit]
    task_decisions: Dict[str, TaskDecision]
    metadata: Dict[str, object] = field(default_factory=dict)

    def iter_task_ids(self) -> Iterable[str]:
        for route in self.routes.values():
            yield from route.task_ids()
