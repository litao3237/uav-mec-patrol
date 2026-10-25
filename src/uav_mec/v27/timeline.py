"""Event timeline of flight, collection, TDMA uploads and MEC processing.

For a fixed structure the whole flight/upload/MEC timeline is independent of
the onboard DVFS frequencies (onboard computation overlaps flight), so it is
computed once here; only onboard completion times depend on the continuous
decisions (see ``dvfs.py``).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .instance import Instance
from .physics import rate_mbps
from .solution import Structure


@dataclass
class StopRecord:
    uav: str
    stop: str
    kind: str          # "task" | "visit"
    arrive: float
    start: float       # collection start, or upload start (after TDMA wait)
    depart: float


@dataclass
class UploadRecord:
    visit: str
    uav: str
    station: str
    arrive: float
    start: float
    end: float
    data_mbit: float
    rate_mbps: float


@dataclass
class MecJob:
    task: str
    station: str
    available: float   # upload completion
    start: float
    end: float


@dataclass
class Timeline:
    stops: list[StopRecord] = field(default_factory=list)
    uploads: list[UploadRecord] = field(default_factory=list)
    mec_jobs: dict[str, MecJob] = field(default_factory=dict)
    collect_done: dict[str, float] = field(default_factory=dict)
    return_time: dict[str, float] = field(default_factory=dict)
    distance_m: dict[str, float] = field(default_factory=dict)
    hover_s: dict[str, float] = field(default_factory=dict)       # collection + wait + upload
    upload_s: dict[str, float] = field(default_factory=dict)


def simulate(inst: Instance, d: Structure) -> Timeline:
    v = inst.params.speed_mps
    tl = Timeline()
    station_free = {s: 0.0 for s in inst.stations}
    state = {u: {"pos": "DEPOT", "idx": 0, "t": 0.0} for u in inst.uav_ids}
    for u in inst.uav_ids:
        tl.distance_m[u] = 0.0
        tl.hover_s[u] = 0.0
        tl.upload_s[u] = 0.0

    heap: list[tuple[float, int, str]] = []
    order = {u: k for k, u in enumerate(inst.uav_ids)}

    def schedule_next(u: str) -> None:
        st = state[u]
        stops = d.routes.get(u, [])
        nxt = stops[st["idx"]] if st["idx"] < len(stops) else "DEPOT"
        node = nxt if nxt in inst.tasks or nxt == "DEPOT" else d.visits[nxt]
        leg = inst.dist(st["pos"], node)
        tl.distance_m[u] += leg
        st["pos"] = node
        heapq.heappush(heap, (st["t"] + leg / v, order[u], u))

    for u in inst.uav_ids:
        schedule_next(u)

    while heap:
        arrive, _, u = heapq.heappop(heap)
        st = state[u]
        stops = d.routes.get(u, [])
        if st["idx"] >= len(stops):
            tl.return_time[u] = arrive
            continue
        s = stops[st["idx"]]
        if s in inst.tasks:
            a = inst.tasks[s].collect_s
            tl.collect_done[s] = arrive + a
            tl.stops.append(StopRecord(u, s, "task", arrive, arrive, arrive + a))
            tl.hover_s[u] += a
            st["t"] = arrive + a
        else:
            pt = inst.points[d.visits[s]]
            station = inst.stations[pt.station_id]
            batch = d.batch(s)
            data = sum(inst.tasks[t].data_mbit for t in batch)
            r = rate_mbps(station.bandwidth_mhz, pt.gamma_mhz)
            start = max(arrive, station_free[station.station_id])
            end = start + data / r
            station_free[station.station_id] = end
            tl.uploads.append(UploadRecord(s, u, station.station_id, arrive, start, end, data, r))
            tl.stops.append(StopRecord(u, s, "visit", arrive, start, end))
            tl.hover_s[u] += end - arrive
            tl.upload_s[u] += end - start
            st["t"] = end
        st["idx"] += 1
        schedule_next(u)

    # MEC: one server per station, FIFO by upload completion, EDF inside a batch.
    upload_end = {rec.visit: rec.end for rec in tl.uploads}
    jobs: dict[str, list[tuple[float, float, str]]] = {s: [] for s in inst.stations}
    for t, visit in d.upload.items():
        station = inst.points[d.visits[visit]].station_id
        due = tl.collect_done[t] + inst.tasks[t].freshness_s
        jobs[station].append((upload_end[visit], due, t))
    for station, items in jobs.items():
        free = 0.0
        for avail, _, t in sorted(items):
            start = max(free, avail)
            end = start + inst.tasks[t].workload_gc / inst.stations[station].cpu_gcps
            tl.mec_jobs[t] = MecJob(t, station, avail, start, end)
            free = end
    return tl
