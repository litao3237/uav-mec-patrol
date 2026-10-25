"""Distance-only route construction used to freeze routes for the coupling check.

Angular sweep around the depot into M balanced clusters, nearest-neighbour
ordering, then 2-opt per UAV. Purely geometric: it knows nothing about
stations or offloading, so it is a neutral fixed route for comparing
offloading policies.
"""

from __future__ import annotations

import math

from .instance import Instance


def _tour_len(inst: Instance, seq: list[str]) -> float:
    path = ["DEPOT", *seq, "DEPOT"]
    return sum(inst.dist(a, b) for a, b in zip(path, path[1:]))


def _two_opt(inst: Instance, seq: list[str]) -> list[str]:
    best = seq[:]
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                if _tour_len(inst, cand) < _tour_len(inst, best) - 1e-9:
                    best, improved = cand, True
    return best


def sweep_routes(inst: Instance) -> dict[str, list[str]]:
    dx, dy = inst.params.depot_xy
    ids = sorted(inst.tasks, key=lambda t: (math.atan2(inst.tasks[t].y - dy, inst.tasks[t].x - dx), t))
    m, n = inst.num_uavs, len(ids)
    routes: dict[str, list[str]] = {}
    for k, u in enumerate(inst.uav_ids):
        group = ids[k * n // m:(k + 1) * n // m]
        seq, pos, left = [], "DEPOT", set(group)
        while left:
            nxt = min(left, key=lambda t: (inst.dist(pos, t), t))
            seq.append(nxt); left.remove(nxt); pos = nxt
        routes[u] = _two_opt(inst, seq)
    return routes
