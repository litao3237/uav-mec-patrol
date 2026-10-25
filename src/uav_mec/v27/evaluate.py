"""Evaluate a discrete structure: timeline + per-UAV convex DVFS + metrics.

Objective (to minimise):

    J = (1/K) * sum_i w_i * AoI_i / delta_i  +  lambda * E_total / (M * E_max)

AoI_i = c_i - t_i^col is the result age from collection completion to
computation completion. Freshness deadlines delta_i are reported (late count,
normalized tardiness) and used lexicographically by the discrete search, but
are not hard constraints, so every structurally valid mission within battery
has a finite value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .dvfs import solve_dvfs
from .instance import Instance
from .solution import Structure
from .timeline import Timeline, simulate


@dataclass
class UavEnergy:
    flight_j: float
    hover_j: float
    tx_j: float
    compute_j: float

    @property
    def total_j(self) -> float:
        return self.flight_j + self.hover_j + self.tx_j + self.compute_j


@dataclass
class Evaluation:
    feasible: bool
    reasons: list[str]
    objective: float
    aoi_term: float
    energy_term: float
    completion: dict[str, float] = field(default_factory=dict)
    aoi: dict[str, float] = field(default_factory=dict)
    freq: dict[str, float] = field(default_factory=dict)
    local_start: dict[str, float] = field(default_factory=dict)
    energy: dict[str, UavEnergy] = field(default_factory=dict)
    timeline: Timeline | None = None
    dvfs_status: dict[str, str] = field(default_factory=dict)

    @property
    def late_tasks(self) -> int:
        return self._late

    @property
    def total_energy_j(self) -> float:
        return sum(e.total_j for e in self.energy.values())

    def key(self) -> tuple:
        """Lexicographic ranking used by discrete search."""
        if not self.feasible:
            return (1, float("inf"), float("inf"), float("inf"))
        return (0, self._late, self._tardiness, self.objective)

    _late: int = 0
    _tardiness: float = 0.0
    _mean_aoi: float = 0.0

    def summary(self) -> dict:
        return {
            "feasible": self.feasible,
            "objective": self.objective,
            "aoi_term": self.aoi_term,
            "energy_term": self.energy_term,
            "late_tasks": self._late,
            "norm_tardiness": self._tardiness,
            "mean_aoi_s": self._mean_aoi,
            "energy_kj": self.total_energy_j / 1e3,
            "flight_kj": sum(e.flight_j for e in self.energy.values()) / 1e3,
            "hover_kj": sum(e.hover_j for e in self.energy.values()) / 1e3,
            "compute_kj": sum(e.compute_j for e in self.energy.values()) / 1e3,
            "offloaded": sum(1 for t in self.aoi if t not in self.freq),
        }


def evaluate(inst: Instance, d: Structure, *, energy_weight: float | None = None) -> Evaluation:
    p = inst.params
    lam = p.energy_weight if energy_weight is None else energy_weight
    K = len(inst.tasks)
    M = inst.num_uavs
    reasons = d.violations(inst)
    if reasons:
        return Evaluation(False, reasons, float("inf"), float("inf"), float("inf"))

    tl = simulate(inst, d)
    p_fly, p_hov = inst.flight_power_w, inst.hover_power_w
    mu = lam / (M * p.battery_j)
    ev = Evaluation(True, [], 0.0, 0.0, 0.0, timeline=tl)

    for u in inst.uav_ids:
        fixed = (p_fly * tl.distance_m[u] / p.speed_mps + p_hov * tl.hover_s[u]
                 + p.tx_power_w * tl.upload_s[u])
        local = [s for s in d.routes.get(u, []) if s in inst.tasks and s not in d.upload]
        tc = np.array([tl.collect_done[t] for t in local])
        wk = np.array([inst.tasks[t].workload_gc for t in local])
        ak = np.array([inst.tasks[t].weight / (K * inst.tasks[t].freshness_s) for t in local])
        res = solve_dvfs(tc, wk, ak, mu=mu, kappa=p.kappa_bar, f_min=p.cpu_min_gcps,
                         f_max=p.cpu_max_gcps, battery_residual=p.battery_j - fixed)
        ev.dvfs_status[u] = res.status
        if res.status == "infeasible_battery":
            ev.feasible = False
            ev.reasons.append(f"UAV {u} exceeds battery")
        for k, t in enumerate(local):
            ev.completion[t] = float(res.finish[k])
            ev.local_start[t] = float(res.start[k])
            ev.freq[t] = float(res.freq[k])
        ev.energy[u] = UavEnergy(
            flight_j=p_fly * tl.distance_m[u] / p.speed_mps,
            hover_j=p_hov * tl.hover_s[u],
            tx_j=p.tx_power_w * tl.upload_s[u],
            compute_j=res.energy_j,
        )
    for t, job in tl.mec_jobs.items():
        ev.completion[t] = job.end

    aoi_term = 0.0
    late = 0
    tard = 0.0
    for t, task in inst.tasks.items():
        age = ev.completion[t] - tl.collect_done[t]
        ev.aoi[t] = age
        ratio = age / task.freshness_s
        aoi_term += task.weight * ratio / K
        if ratio > 1.0 + 1e-9:
            late += 1
            tard += ratio - 1.0
    ev.aoi_term = aoi_term
    ev.energy_term = lam * ev.total_energy_j / (M * p.battery_j)
    ev.objective = aoi_term + ev.energy_term if ev.feasible else float("inf")
    ev._late, ev._tardiness = late, tard
    ev._mean_aoi = float(np.mean(list(ev.aoi.values())))
    return ev
