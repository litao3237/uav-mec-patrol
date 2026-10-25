"""Reproducible v27 instances."""

from __future__ import annotations

import math
from dataclasses import dataclass
from random import Random

from .params import ModelParams, TaskClassParams
from .physics import coverage_radius_m, flight_power_w, hover_power_w, snr_coefficient_mhz


@dataclass(frozen=True)
class Task:
    task_id: str
    kind: str                 # "light" | "heavy"
    x: float
    y: float
    data_mbit: float
    workload_gc: float        # Gcycles
    collect_s: float
    freshness_s: float        # delta_i, measured from collection completion
    weight: float
    onboard_allowed: bool


@dataclass(frozen=True)
class Station:
    station_id: str
    x: float
    y: float
    bandwidth_mhz: float
    cpu_gcps: float
    radius_m: float


@dataclass(frozen=True)
class ContactPoint:
    point_id: str
    station_id: str
    x: float
    y: float
    gamma_mhz: float          # SNR coefficient at this point (MHz)


@dataclass
class Instance:
    params: ModelParams
    tasks: dict[str, Task]
    stations: dict[str, Station]
    points: dict[str, ContactPoint]
    depot_point_id: str       # terminal upload point at the depot station
    num_uavs: int

    @property
    def uav_ids(self) -> list[str]:
        return [f"U{k}" for k in range(1, self.num_uavs + 1)]

    @property
    def flight_power_w(self) -> float:
        return flight_power_w(self.params)

    @property
    def hover_power_w(self) -> float:
        return hover_power_w(self.params)

    def xy(self, node: str) -> tuple[float, float]:
        if node == "DEPOT":
            return self.params.depot_xy
        if node in self.tasks:
            t = self.tasks[node]
            return t.x, t.y
        pt = self.points[node]
        return pt.x, pt.y

    def dist(self, a: str, b: str) -> float:
        (xa, ya), (xb, yb) = self.xy(a), self.xy(b)
        return math.hypot(xa - xb, ya - yb)


def _uniform(rng: Random, lo_hi: tuple[float, float]) -> float:
    return rng.uniform(lo_hi[0], lo_hi[1])


def _make_task(idx: int, cls: TaskClassParams, x: float, y: float, rng: Random,
               onboard_allowed: bool) -> Task:
    data = _uniform(rng, cls.data_mbit)
    cpb = _uniform(rng, cls.cycles_per_bit)
    return Task(
        task_id=f"T{idx}",
        kind=cls.name,
        x=x,
        y=y,
        data_mbit=data,
        workload_gc=data * cpb * 1e-3,   # Mbit * cycles/bit = 1e6 cycles -> Gcycles
        collect_s=cls.collect_s,
        freshness_s=_uniform(rng, cls.freshness_s),
        weight=cls.weight,
        onboard_allowed=onboard_allowed,
    )


def generate_instance(p: ModelParams, *, num_tasks: int | None = None,
                      num_uavs: int | None = None, seed: int | None = None) -> Instance:
    p.validate()
    k = p.num_tasks if num_tasks is None else int(num_tasks)
    m = p.num_uavs if num_uavs is None else int(num_uavs)
    rng = Random(p.scenario_seed if seed is None else int(seed))

    stations: dict[str, Station] = {}
    for s in p.sites[: p.num_sites]:
        stations[s.name] = Station(s.name, s.x, s.y, s.bandwidth_mhz, s.cpu_gcps,
                                   coverage_radius_m(p, s.bandwidth_mhz))

    points: dict[str, ContactPoint] = {}
    for st in stations.values():
        cand = [(f"{st.station_id}_C", st.x, st.y)] if p.include_center else []
        for ring_idx, frac in enumerate(p.ring_fractions, start=1):
            rad = frac * st.radius_m
            offset = (ring_idx % 2) * math.pi / p.points_per_ring
            for j in range(p.points_per_ring):
                a = 2 * math.pi * j / p.points_per_ring + offset
                cand.append((f"{st.station_id}_R{ring_idx}_{j:02d}",
                             st.x + rad * math.cos(a), st.y + rad * math.sin(a)))
        for pid, x, y in cand:
            if 0.0 <= x <= p.width_m and 0.0 <= y <= p.height_m:
                h = math.hypot(x - st.x, y - st.y)
                points[pid] = ContactPoint(pid, st.station_id, x, y, snr_coefficient_mhz(p, h))
    depot_station = p.sites[0].name
    depot_point = f"{depot_station}_C"
    if depot_point not in points:
        raise ValueError("depot station centre must be a contact point")

    tasks: dict[str, Task] = {}
    mg = p.task_margin_m
    for i in range(1, k + 1):
        x = rng.uniform(mg, p.width_m - mg)
        y = rng.uniform(mg, p.height_m - mg)
        heavy = rng.random() < p.heavy_fraction
        cls = p.heavy if heavy else p.light
        tasks[f"T{i}"] = _make_task(i, cls, x, y, rng,
                                    onboard_allowed=(not heavy) or p.heavy_onboard_allowed)

    return Instance(params=p, tasks=tasks, stations=stations, points=points,
                    depot_point_id=depot_point, num_uavs=m)
