"""Independent residual audit of an evaluated v27 solution.

The audit does not rerun the simulator. It checks the recorded schedule
directly against every model constraint and recomputes energy, AoI and the
objective from first principles, so an error in ``timeline.py``, ``dvfs.py``
or ``evaluate.py`` shows up as a nonzero residual.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .evaluate import Evaluation
from .instance import Instance
from .physics import flight_power_w, hover_power_w, rate_mbps
from .solution import Structure

TOL = 1e-6


def audit(inst: Instance, d: Structure, ev: Evaluation, *, energy_weight: float | None = None) -> list[str]:
    p = inst.params
    lam = p.energy_weight if energy_weight is None else energy_weight
    tl = ev.timeline
    errs: list[str] = list(d.violations(inst))
    if tl is None:
        return errs + ["no timeline recorded"]

    def bad(cond: bool, msg: str) -> None:
        if cond:
            errs.append(msg)

    # 1. Geometry, coverage and flight kinematics per UAV.
    by_uav = defaultdict(list)
    for rec in tl.stops:
        by_uav[rec.uav].append(rec)
    dist_total = {}
    for u in inst.uav_ids:
        recs = by_uav[u]
        bad([r.stop for r in recs] != d.routes.get(u, []), f"{u}: recorded stops differ from route")
        pos, t, dist = "DEPOT", 0.0, 0.0
        for r in recs:
            node = r.stop if r.kind == "task" else d.visits[r.stop]
            leg = inst.dist(pos, node)
            dist += leg
            bad(abs(r.arrive - (t + leg / p.speed_mps)) > TOL, f"{u}/{r.stop}: arrival residual")
            if r.kind == "task":
                bad(abs(r.depart - r.arrive - inst.tasks[r.stop].collect_s) > TOL,
                    f"{u}/{r.stop}: collection duration residual")
                bad(abs(tl.collect_done[r.stop] - r.depart) > TOL, f"{r.stop}: t_col residual")
            else:
                pt = inst.points[d.visits[r.stop]]
                st = inst.stations[pt.station_id]
                bad(math.hypot(pt.x - st.x, pt.y - st.y) > st.radius_m + TOL,
                    f"{r.stop}: contact point outside coverage")
                bad(r.start < r.arrive - TOL, f"{r.stop}: upload before arrival")
            pos, t = node, r.depart
        leg = inst.dist(pos, "DEPOT")
        dist += leg
        dist_total[u] = dist
        bad(abs(tl.return_time.get(u, math.nan) - (t + leg / p.speed_mps)) > TOL, f"{u}: return residual")

    # 2. TDMA uploads: duration = batch / full-band rate, no overlap, FCFS, no idling.
    by_station = defaultdict(list)
    for up in tl.uploads:
        pt = inst.points[d.visits[up.visit]]
        st = inst.stations[pt.station_id]
        data = sum(inst.tasks[t].data_mbit for t in d.batch(up.visit))
        r = rate_mbps(st.bandwidth_mhz, _gamma(inst, pt))
        bad(abs((up.end - up.start) - data / r) > TOL, f"{up.visit}: upload duration residual")
        for t in d.batch(up.visit):
            bad(tl.collect_done[t] > up.start + TOL, f"{t}: uploaded before collected")
        by_station[st.station_id].append(up)
    for s, ups in by_station.items():
        ups.sort(key=lambda x: (x.arrive, x.start))
        free = 0.0
        for up in ups:
            bad(abs(up.start - max(up.arrive, free)) > TOL, f"{s}/{up.visit}: TDMA FCFS residual")
            free = up.end

    # 3. MEC single server: release after upload, durations, no overlap.
    end_of_upload = {up.visit: up.end for up in tl.uploads}
    by_srv = defaultdict(list)
    for t, v in d.upload.items():
        job = tl.mec_jobs.get(t)
        if job is None:
            errs.append(f"{t}: missing MEC job"); continue
        st = inst.stations[inst.points[d.visits[v]].station_id]
        bad(job.start < end_of_upload[v] - TOL, f"{t}: MEC start before upload end")
        bad(abs(job.end - job.start - inst.tasks[t].workload_gc / st.cpu_gcps) > TOL,
            f"{t}: MEC duration residual")
        bad(abs(ev.completion[t] - job.end) > TOL, f"{t}: edge completion residual")
        by_srv[st.station_id].append(job)
    for s, jobs in by_srv.items():
        jobs.sort(key=lambda j: j.start)
        for a, b in zip(jobs, jobs[1:]):
            bad(b.start < a.end - TOL, f"{s}: MEC jobs overlap ({a.task},{b.task})")

    # 4. Onboard FIFO computing with DVFS bounds.
    compute_e = defaultdict(float)
    for u in inst.uav_ids:
        prev = -math.inf
        for t in [s for s in d.routes.get(u, []) if s in inst.tasks and s not in d.upload]:
            f = ev.freq[t]
            w = inst.tasks[t].workload_gc
            bad(f < p.cpu_min_gcps - TOL or f > p.cpu_max_gcps + TOL, f"{t}: frequency out of bounds")
            bad(ev.local_start[t] < tl.collect_done[t] - TOL, f"{t}: computed before collection")
            bad(ev.local_start[t] < prev - TOL, f"{t}: onboard FIFO overlap")
            bad(abs(ev.completion[t] - ev.local_start[t] - w / f) > 1e-5, f"{t}: onboard duration residual")
            prev = ev.completion[t]
            compute_e[u] += p.kappa_bar * w * f * f

    # 5. Energy and battery from first principles.
    pf, ph = flight_power_w(p), hover_power_w(p)
    total = 0.0
    for u in inst.uav_ids:
        hover = sum(r.depart - r.arrive for r in by_uav[u])
        tx = sum(up.end - up.start for up in tl.uploads if up.uav == u)
        e = pf * dist_total[u] / p.speed_mps + ph * hover + p.tx_power_w * tx + compute_e[u]
        total += e
        bad(abs(e - ev.energy[u].total_j) > 1e-3, f"{u}: energy residual {e - ev.energy[u].total_j:.3g} J")
        bad(e > p.battery_j * (1 + 1e-9), f"{u}: battery exceeded")

    # 6. Objective.
    K, M = len(inst.tasks), inst.num_uavs
    aoi_term = sum(inst.tasks[t].weight * (ev.completion[t] - tl.collect_done[t])
                   / inst.tasks[t].freshness_s for t in inst.tasks) / K
    obj = aoi_term + lam * total / (M * p.battery_j)
    bad(abs(obj - ev.objective) > 1e-6 * max(1.0, abs(obj)), f"objective residual {obj - ev.objective:.3g}")
    return errs


def _gamma(inst: Instance, pt) -> float:
    from .physics import snr_coefficient_mhz
    st = inst.stations[pt.station_id]
    return snr_coefficient_mhz(inst.params, math.hypot(pt.x - st.x, pt.y - st.y))
