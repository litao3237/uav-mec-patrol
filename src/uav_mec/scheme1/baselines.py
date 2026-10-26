"""基线方法：B0 只在基地上传、B1 就近贪心停靠、B2 两阶段、B3 仿 Huang 2026 的静态分簇、B4 仿 Raj 2026 的截止驱动

所有基线使用与本文方法相同的初始分配（扇形或弧段）、同一时长预算与电池约束。
每个函数返回 (方案, 附加信息)：方案为每架机的 (航线, 停靠方案)，由 experiment.evaluate_solution 用独立事件模拟统一评估
"""

from __future__ import annotations

import itertools
import math

from .instance import Instance
from .search import Budget
from .stops import TOL, exact_stops, simulate
from .tsp import shortest_tour


def _better_direction(inst: Instance, tour: list[int], make_stops) -> tuple[list[int], list]:
    """对最短回路的两个方向分别构造停靠方案，取目标较小者（与两阶段一样给基线选方向的机会）"""
    cands = []
    for r in (tour, tour[::-1]):
        stops = make_stops(r)
        cands.append((simulate(inst, r, stops).objective, r, stops))
    _, r, stops = min(cands, key=lambda c: c[0])
    return r, stops


def base_only_plan(inst: Instance, groups, budget: Budget):
    """B0：每架机走最短回路，返回基地后统一上传"""
    plan = []
    for g in groups:
        tour, _ = shortest_tour(inst, g)
        plan.append(_better_direction(inst, tour, lambda r: [(len(r), -1)]) if tour else ([], []))
    return plan, {}


def two_stage_plan(inst: Instance, groups, budget: Budget):
    """B2：最短回路取较好方向 + 精确停靠；与 solve_fleet 的起点相同"""
    plan = []
    for g in groups:
        tour, _ = shortest_tour(inst, g)
        if not tour:
            plan.append(([], []))
            continue
        cands = [(exact_stops(inst, r, budget.cap(r)), r) for r in (tour, tour[::-1])]
        k = min(range(2), key=lambda i: cands[i][0][0])
        plan.append((cands[k][1], list(cands[k][0][2])))
    return plan, {}


def greedy_stop_plan(inst: Instance, groups, budget: Budget):
    """B1：沿最短回路，每采一份后，若到最近上传点的绕路不超出剩余预算就停靠；最后一站同理，否则回基地上传

    剩余预算 = 飞行时间上限 − 不停靠回路的飞行时间 − 已用掉的绕路；"最近"按距离取，体现简单规则的做法
    """
    n_pts = len(inst.points)
    tt, tp, dt, pd = inst.tt, inst.tp, inst.dt, inst.pd

    def make_stops(r):
        n = len(r)
        slack = budget.cap(r) - inst.route_length_m(r) / inst.params.speed_mps
        stops = []
        for k in range(1, n):
            a, b = r[k - 1], r[k]
            p = min(range(n_pts), key=tp[a].__getitem__)
            detour = tp[a][p] + tp[b][p] - tt[a][b]
            if detour <= slack + TOL:
                stops.append((k, p))
                slack -= detour
        a = r[-1]
        p = min(range(n_pts), key=tp[a].__getitem__)
        stops.append((n, p) if tp[a][p] + pd[p] - dt[a] <= slack + TOL else (n, -1))
        return stops

    plan = []
    for g in groups:
        tour, _ = shortest_tour(inst, g)
        plan.append(_better_direction(inst, tour, make_stops) if tour else ([], []))
    return plan, {}


def _open_path(inst: Instance, start: int | None, gids: list[int]) -> list[int]:
    """从 start（上传点下标，None 表示基地）出发、访问 gids 的开放路径：最近邻构造 + 2-opt（起点固定、终点自由）"""
    def d0(g):
        return inst.dt[g] if start is None else inst.tp[g][start]

    rest, path, cur = list(gids), [], None
    while rest:
        nxt = min(rest, key=d0 if cur is None else inst.tt[cur].__getitem__)
        path.append(nxt)
        rest.remove(nxt)
        cur = nxt

    def length(p):
        return d0(p[0]) + sum(inst.tt[a][b] for a, b in itertools.pairwise(p))

    improved = True
    while improved:
        improved = False
        for i in range(len(path) - 1):
            for j in range(i + 1, len(path)):
                cand = path[:i] + path[i:j + 1][::-1] + path[j + 1:]
                if length(cand) < length(path) - 1e-12:
                    path, improved = cand, True
    return path


def static_cluster_plan(inst: Instance, groups, budget: Budget):
    """B3（仿 Huang 2026）：每机观测点按最近站点分簇，逐簇访问（簇内最近邻 + 2-opt），每簇采完去该站上传

    簇的访问顺序在全部排列中取飞行时间最短者（站点至多 4 个）；送达点是静态分配的，不随时效需求调整。
    超出飞行时间上限时从后往前删去途中停靠、最后一站改回基地；仍超限（分簇顺序的回路比最短回路长）则退回 B0 的方案
    """
    stations = inst.params.stations
    pt_station = [min(range(len(stations)), key=lambda s: math.hypot(x - stations[s][1], y - stations[s][2]))
                  for x, y in inst.points]
    plan, fallbacks = [], 0
    for g in groups:
        if not g:
            plan.append(([], []))
            continue
        clusters: dict = {}
        for gid in g:
            t = inst.tasks[gid]
            s = min(range(len(stations)), key=lambda s: math.hypot(t.x - stations[s][1], t.y - stations[s][2]))
            clusters.setdefault(s, []).append(gid)
        best = None
        for order in itertools.permutations(sorted(clusters)):
            route, stops, pos = [], [], None
            for s in order:
                path = _open_path(inst, pos, clusters[s])
                route += path
                last = path[-1]
                p = min((i for i, ps in enumerate(pt_station) if ps == s), key=inst.tp[last].__getitem__)
                stops.append((len(route), p))
                pos = p
            fly = simulate(inst, route, stops).fly_s
            if best is None or fly < best[2] - 1e-12:
                best = (route, stops, fly)
        route, stops, _ = best
        cap = budget.cap(route)
        while simulate(inst, route, stops).fly_s > cap + TOL:
            mids = [s for s in stops if s[0] < len(route)]
            if mids:
                stops.remove(mids[-1])
            elif stops[-1][1] != -1:
                stops[-1] = (len(route), -1)
            else:
                break
        if simulate(inst, route, stops).fly_s > cap + TOL:
            fallbacks += 1
            tour, _ = shortest_tour(inst, g)
            route, stops = _better_direction(inst, tour, lambda r: [(len(r), -1)])
        plan.append((route, stops))
    return plan, {"fallbacks": fallbacks}


def deadline_plan(inst: Instance, groups, budget: Budget):
    """B4（仿 Raj 2026 的 DA 规则）：沿最短回路按采集顺序检查每份数据，若在当前方案下会超时，
    就在它采集之后、原送达位置之前，选一个能让它按时送达且不超预算、绕路最少的停靠加入方案

    每个位置的候选上传点取绕路最少者（"最便宜的停靠"）；找不到可行的停靠则让这份数据超时
    """
    n_pts = len(inst.points)
    tt, tp, dt, pd = inst.tt, inst.tp, inst.dt, inst.pd

    def make_stops(r):
        n = len(r)
        cap = budget.cap(r)
        cheapest = {}
        for k in range(1, n + 1):
            a = r[k - 1]
            if k < n:
                b = r[k]
                cost = [tp[a][p] + tp[b][p] - tt[a][b] for p in range(n_pts)]
            else:
                cost = [tp[a][p] + pd[p] - dt[a] for p in range(n_pts)]
            p = min(range(n_pts), key=cost.__getitem__)
            cheapest[k] = (p, cost[p])
        stops = {n: -1}
        for idx in range(1, n + 1):
            g_i = r[idx - 1]
            sim = simulate(inst, r, sorted(stops.items()))
            if sim.aoi[idx - 1] <= inst.delta[g_i]:
                continue
            k_next = min(k for k in stops if k >= idx)
            options = []
            for k in range(idx, k_next + 1):
                if k == k_next and stops[k] != -1:
                    continue
                p, det = cheapest[k]
                trial = dict(stops)
                trial[k] = p
                s2 = simulate(inst, r, sorted(trial.items()))
                if s2.fly_s <= cap + TOL and s2.aoi[idx - 1] <= inst.delta[g_i]:
                    options.append((det, k, p))
            if options:
                _, k, p = min(options)
                stops[k] = p
        return sorted(stops.items())

    plan = []
    for g in groups:
        tour, _ = shortest_tour(inst, g)
        plan.append(_better_direction(inst, tour, make_stops) if tour else ([], []))
    return plan, {}
