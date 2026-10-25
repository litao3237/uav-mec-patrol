"""Discrete structure D of the v27 model."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .instance import Instance


@dataclass
class Structure:
    """Discrete decisions for a fixed mission.

    routes[u]  ordered stops of UAV u (depot excluded at both ends). A stop is a
               task id or a contact-visit id.
    visits[v]  contact point of visit v (one visit = one upload event).
    upload[i]  visit at which edge task i is uploaded; tasks absent from
               ``upload`` are processed onboard.

    Station upload order is not a decision: stations serve uploads FCFS by
    arrival (TDMA), so it follows from the routes.
    """

    routes: dict[str, list[str]]
    visits: dict[str, str] = field(default_factory=dict)
    upload: dict[str, str] = field(default_factory=dict)

    def copy(self) -> "Structure":
        return copy.deepcopy(self)

    def mode(self, task_id: str) -> str:
        return "edge" if task_id in self.upload else "local"

    def uav_of_visit(self, visit_id: str) -> str:
        for u, stops in self.routes.items():
            if visit_id in stops:
                return u
        raise KeyError(visit_id)

    def batch(self, visit_id: str) -> list[str]:
        return [t for t, v in self.upload.items() if v == visit_id]

    def new_visit_id(self) -> str:
        n = 1
        while f"V{n}" in self.visits:
            n += 1
        return f"V{n}"

    def drop_empty_visits(self) -> None:
        used = set(self.upload.values())
        for v in [v for v in self.visits if v not in used]:
            for stops in self.routes.values():
                if v in stops:
                    stops.remove(v)
            del self.visits[v]

    def en_route_visit_count(self, inst: Instance, uav: str) -> int:
        stops = self.routes[uav]
        n = 0
        for j, s in enumerate(stops):
            if s in self.visits:
                terminal = j == len(stops) - 1 and self.visits[s] == inst.depot_point_id
                n += 0 if terminal else 1
        return n

    def violations(self, inst: Instance) -> list[str]:
        """Structural feasibility (independent of continuous variables)."""
        out: list[str] = []
        seen: dict[str, int] = {}
        for u, stops in self.routes.items():
            if u not in inst.uav_ids:
                out.append(f"unknown UAV {u}")
            for s in stops:
                seen[s] = seen.get(s, 0) + 1
                if s not in inst.tasks and s not in self.visits:
                    out.append(f"unknown stop {s}")
        for t in inst.tasks:
            if seen.get(t, 0) != 1:
                out.append(f"task {t} visited {seen.get(t, 0)} times")
        for v, pt in self.visits.items():
            if seen.get(v, 0) != 1:
                out.append(f"visit {v} appears {seen.get(v, 0)} times")
            if pt not in inst.points:
                out.append(f"visit {v} uses unknown point {pt}")
            if not self.batch(v):
                out.append(f"visit {v} uploads nothing")
        for t, v in self.upload.items():
            if v not in self.visits:
                out.append(f"task {t} uploads at unknown visit {v}")
                continue
            ut = next((u for u, st in self.routes.items() if t in st), None)
            uv = next((u for u, st in self.routes.items() if v in st), None)
            if ut is None or ut != uv:
                out.append(f"task {t} uploaded by a different UAV")
            elif self.routes[ut].index(v) < self.routes[ut].index(t):
                out.append(f"task {t} uploaded before collection")
        for t, task in inst.tasks.items():
            if not task.onboard_allowed and t not in self.upload:
                out.append(f"task {t} cannot run onboard")
        for u in self.routes:
            if self.en_route_visit_count(inst, u) > inst.params.max_contacts_per_uav:
                out.append(f"UAV {u} exceeds the en-route contact limit")
        return out
