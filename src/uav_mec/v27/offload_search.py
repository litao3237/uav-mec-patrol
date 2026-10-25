"""Offloading / contact search with the task visiting order held fixed.

Used by the coupling check: it answers "how much can the non-route decisions
(computation mode, upload contact, contact insertion) change the objective
when routes are frozen?". Moves, applied by first improvement on the
lexicographic key (late tasks, normalized tardiness, J):

* set a task to onboard processing (if allowed),
* attach it to an existing later visit of the same UAV,
* insert a new contact visit after it (best few detour positions per station),
* attach it to the terminal depot upload (end of route, not counted in H_max).
"""

from __future__ import annotations

from dataclasses import dataclass

from .evaluate import Evaluation, evaluate
from .instance import Instance
from .solution import Structure


@dataclass
class SearchResult:
    structure: Structure
    evaluation: Evaluation
    evaluations: int
    passes: int


def _owner(d: Structure, task: str) -> str:
    return next(u for u, s in d.routes.items() if task in s)


def _with_local(d: Structure, t: str) -> Structure:
    c = d.copy()
    c.upload.pop(t, None)
    c.drop_empty_visits()
    return c


def _with_existing(d: Structure, t: str, v: str) -> Structure:
    c = d.copy()
    c.upload[t] = v
    c.drop_empty_visits()
    return c


def _with_new_visit(d: Structure, t: str, u: str, pos: int, point: str) -> Structure:
    c = d.copy()
    vid = c.new_visit_id()
    c.visits[vid] = point
    c.routes[u].insert(pos, vid)
    c.upload[t] = vid
    c.drop_empty_visits()
    return c


def _terminal(d: Structure, inst: Instance, t: str, u: str) -> Structure:
    stops = d.routes[u]
    if stops and stops[-1] in d.visits and d.visits[stops[-1]] == inst.depot_point_id:
        return _with_existing(d, t, stops[-1])
    return _with_new_visit(d, t, u, len(stops), inst.depot_point_id)


def _node(inst: Instance, d: Structure, s: str) -> str:
    return s if s in inst.tasks else d.visits[s]


def candidate_moves(inst: Instance, d: Structure, t: str, *, allow_local: bool,
                    per_station: int = 2) -> list[Structure]:
    u = _owner(d, t)
    stops = d.routes[u]
    i = stops.index(t)
    out: list[Structure] = []
    if allow_local and inst.tasks[t].onboard_allowed and t in d.upload:
        out.append(_with_local(d, t))
    for v in stops[i + 1:]:
        if v in d.visits and d.upload.get(t) != v:
            out.append(_with_existing(d, t, v))
    out.append(_terminal(d, inst, t, u))
    if d.en_route_visit_count(inst, u) < inst.params.max_contacts_per_uav:
        path = ["DEPOT", *[_node(inst, d, s) for s in stops], "DEPOT"]
        for st in inst.stations:
            opts = []
            for pos in range(i + 1, len(stops) + 1):
                a, b = path[pos], path[pos + 1]
                for pid, pt in inst.points.items():
                    if pt.station_id != st or pid == inst.depot_point_id:
                        continue
                    detour = inst.dist(a, pid) + inst.dist(pid, b) - inst.dist(a, b)
                    opts.append((detour, pos, pid))
            for _, pos, pid in sorted(opts)[:per_station]:
                out.append(_with_new_visit(d, t, u, pos, pid))
    return out


def optimize_offloading(inst: Instance, start: Structure, *, allow_local: bool = True,
                        max_passes: int = 6) -> SearchResult:
    d = start.copy()
    if not allow_local:                       # force every task to the edge first
        for t in inst.tasks:
            if t not in d.upload:
                d = _terminal(d, inst, t, _owner(d, t))
    best = evaluate(inst, d)
    n_eval, passes = 1, 0
    improved = True
    while improved and passes < max_passes:
        improved, passes = False, passes + 1
        for t in sorted(inst.tasks, key=lambda x: int(x[1:])):
            for cand in candidate_moves(inst, d, t, allow_local=allow_local):
                ev = evaluate(inst, cand)
                n_eval += 1
                if ev.key() < best.key():
                    d, best, improved = cand, ev, True
                    break
    return SearchResult(d, best, n_eval, passes)
