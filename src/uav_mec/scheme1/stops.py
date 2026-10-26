"""给定访问顺序时的上传停靠：精确帕累托动态规划、时间价格下界与独立的事件模拟

停靠方案用 ((k, q), ...) 表示：在第 k 个观测点（1 起）之后到上传点 q 传完携带的全部数据；
q = -1 表示基地，最后一项必须 k = n（之后空载返回基地）。目标为 Σ AoI/δ（AoI 从采集完成起算）
"""

from __future__ import annotations

import itertools
import math
from bisect import insort
from dataclasses import dataclass
from operator import add, truediv

from .instance import Instance

TOL = 1e-9


def pareto(labels: list[tuple]) -> list[tuple]:
    """按 (目标, 飞行时间) 取非支配集合"""
    out, best_f = [], math.inf
    for lab in sorted(labels, key=lambda x: (x[0], x[1])):
        if lab[1] < best_f - 1e-9:
            out.append(lab)
            best_f = lab[1]
    return out


def insert_pareto(cur: list[tuple], lab: tuple) -> None:
    o, f = lab[0], lab[1]
    for x in cur:
        if x[0] <= o + 1e-12 and x[1] <= f + 1e-9:
            return
    cur[:] = [x for x in cur if not (o <= x[0] + 1e-12 and f <= x[1] + 1e-9)]
    cur.append(lab)


def pareto_front(inst: Instance, route: list[int], cap: float | None) -> list[tuple]:
    """固定顺序下的停靠动态规划，返回终点处（目标，飞行时间，停靠方案）的帕累托集合

    段的 AoI 与段起点无关（起点到段内第一个观测点的飞行发生在任何采集之前），起点只影响飞行时间，
    所以同一位置的全部状态先按"飞到下一个观测点"合并成一个帕累托集合再向后转移。
    运算顺序与第二、三道检验脚本的 pareto_dp 逐项一致，保证结果可逐位复现
    :param inst: 实例
    :param route: 观测点 gid 的访问顺序
    :param cap: 飞行时间上限（s），None 表示不限
    :return: 帕累托集合
    """
    n = len(route)
    tt, tp, dt, pd = inst.tt, inst.tp, inst.dt, inst.pd
    tc, delta, up, key = inst.tc, inst.delta, inst.up, inst.wspt_key
    tau = inst.params.tau_s
    n_pts = len(inst.points)
    big = math.inf if cap is None else cap
    # rest[k]：采完第 k 个观测点后不再停靠、按顺序采完并直接回基地的飞行时间，作为剩余飞行的下界
    rest = [0.0] * (n + 2)
    rest[n] = dt[route[n - 1]]
    for k in range(n - 1, 0, -1):
        rest[k] = rest[k + 1] + tt[route[k - 1]][route[k]]
    labels: list[dict] = [dict() for _ in range(n + 1)]
    labels[0][-1] = [(0.0, 0.0, ())]
    terminal: list[tuple] = []
    for j in range(n):
        first = route[j]
        merged = []
        for qi, labs in labels[j].items():
            d0 = dt[first] if qi == -1 else tp[first][qi]
            for (o, f, s) in labs:
                if f + d0 + rest[j + 1] <= big + TOL:
                    merged.append((o, f + d0, s))
        merged = pareto(merged)
        if not merged:
            continue
        t_rel = c_over_d = w_sum = path = 0.0
        srt: list = []          # 段内观测点按 D·δ 升序的有序表，逐个插入维护，迭代顺序与重新排序相同
        for k in range(j + 1, n + 1):
            g = route[k - 1]
            if k > j + 1:
                leg = tt[route[k - 2]][g]
                path += leg
                t_rel += leg
            t_rel += tc[g]
            c_over_d += t_rel / delta[g]
            w_sum += 1.0 / delta[g]
            insort(srt, (key[g], g))
            clock = up_term = 0.0
            for _, x in srt:                                       # 站内按 D·δ 升序上传（WSPT）
                clock += up[x]
                up_term += clock / delta[x]
            base_obj = t_rel * w_sum + up_term + tau * w_sum - c_over_d
            ends = range(n_pts) if k < n else itertools.chain((-1,), range(n_pts))
            row_k = labels[k] if k < n else None
            for qi in ends:
                tail = dt[g] if qi == -1 else tp[g][qi]
                seg_obj = base_obj + tail * w_sum
                seg_fly = path + tail + ((0.0 if qi == -1 else pd[qi]) if k == n else 0.0)
                min_after = tp[route[k]][qi] + rest[k + 1] if k < n else 0.0
                for (o, f, s) in merged:
                    nf = f + seg_fly
                    if nf + min_after > big + TOL:
                        continue
                    lab = (o + seg_obj, nf, s + ((k, qi),))
                    if k == n:
                        terminal.append(lab)
                        continue
                    # 与 insert_pareto 相同的支配判断，内联以省去函数调用
                    cur = row_k.get(qi)
                    if cur is None:
                        row_k[qi] = [lab]
                        continue
                    o2, f2 = lab[0], nf
                    for x in cur:
                        if x[0] <= o2 + 1e-12 and x[1] <= f2 + 1e-9:
                            break
                    else:
                        cur[:] = [x for x in cur if not (o2 <= x[0] + 1e-12 and f2 <= x[1] + 1e-9)]
                        cur.append(lab)
    return pareto(terminal)


def exact_stops(inst: Instance, route: list[int], cap: float) -> tuple | None:
    """上限 cap 内的最优停靠，返回 (Σ AoI/δ, 飞行时间, 停靠方案)；不可行时返回 None"""
    feas = [lab for lab in pareto_front(inst, route, cap) if lab[1] <= cap + TOL]
    return min(feas, key=lambda x: (x[0], x[1])) if feas else None


# ---------- 时间价格（拉格朗日）下界 ----------

@dataclass
class LambdaState:
    """λ 动态规划的中间结果，供共享前缀的候选航线复用

    vv[k][q]：在第 k 个观测点后于上传点 q 停靠的最小（目标 + λ·飞行）（k ≥ 1）；
    mv[j]：从位置 j 出发、飞到第 j+1 个观测点时的合并最小值
    """

    route: tuple
    lam: float
    vv: list
    mv: list
    value: float          # 终点处的最小（目标 + λ·飞行）


def lambda_dp(inst: Instance, route: list[int], lam: float, reuse: LambdaState | None = None) -> LambdaState:
    """时间价格 λ 下的无约束停靠：最小化 Σ AoI/δ + λ·飞行时间，只求最小值

    对任意 λ ≥ 0，value − λ·cap 都是上限 cap 下最优目标的有效下界（拉格朗日对偶）。
    状态只依赖前缀，与 reuse 共享前 m 个观测点时，前 m 个位置的状态与合并值直接复用，只重算之后的位置。
    内层循环用 map/min 等内置函数实现；结果只用作下界，浮点末位与精确动态规划的差异由剪枝时的余量覆盖
    :param inst: 实例
    :param route: 访问顺序
    :param lam: 时间价格（1/s）
    :param reuse: 同一 λ 下另一条航线的状态
    :return: 本航线的状态
    """
    n = len(route)
    tt, tp, dt, pd = inst.tt, inst.tp, inst.dt, inst.pd
    tc, delta, up, key = inst.tc, inst.delta, inst.up, inst.wspt_key
    tau = inst.params.tau_s
    n_pts = len(inst.points)
    inf = math.inf
    m = 0
    if reuse is not None and reuse.lam == lam:
        while m < min(n, len(reuse.route)) - 1 and route[m] == reuse.route[m]:
            m += 1
    vv = [None] * (n + 1)
    mv = [inf] * n
    for k in range(1, m + 1):
        vv[k] = reuse.vv[k]
    for j in range(m):
        mv[j] = reuse.mv[j]
    for k in range(m + 1, n):
        vv[k] = [inf] * n_pts
    lam_pd = [lam * d for d in pd]
    tv = inf
    for j in range(n):
        first = route[j]
        if j >= m:
            mv[j] = lam * dt[first] if j == 0 else min(map(add, vv[j], [lam * d for d in tp[first]]))
        base_v = mv[j]
        if base_v == inf:
            continue
        t_rel = c_over_d = w_sum = path = 0.0
        srt: list = []
        for k in range(j + 1, n + 1):
            g = route[k - 1]
            if k > j + 1:
                leg = tt[route[k - 2]][g]
                path += leg
                t_rel += leg
            t_rel += tc[g]
            c_over_d += t_rel / delta[g]
            w_sum += 1.0 / delta[g]
            insort(srt, (key[g], up[g], delta[g]))
            if k <= m:
                continue              # 这些位置的状态已复用，只需推进段内累计量
            up_term = sum(map(truediv, itertools.accumulate(x[1] for x in srt), [x[2] for x in srt]))
            # 段目标 + λ·段飞行 = A + tail·B，tail 为最后一个观测点到上传点的飞行时间
            a = base_v + t_rel * w_sum + up_term + tau * w_sum - c_over_d + lam * path
            b = w_sum + lam
            row_t = tp[g]
            if k < n:
                vv[k] = list(map(min, vv[k], [a + t * b for t in row_t]))
            else:
                tv = min(tv, a + dt[g] * b, min(a + t * b + lp for t, lp in zip(row_t, lam_pd)))
    return LambdaState(tuple(route), lam, vv, mv, tv)


def lambda_dp_fly(inst: Instance, route: list[int], lam: float) -> tuple[float, float]:
    """与 lambda_dp 相同的问题，额外记录最优方案的飞行时间（求 λ* 时需要次梯度）

    :return: (最小的 目标 + λ·飞行, 该方案的飞行时间)
    """
    n = len(route)
    tt, tp, dt, pd = inst.tt, inst.tp, inst.dt, inst.pd
    tc, delta, up, key = inst.tc, inst.delta, inst.up, inst.wspt_key
    tau = inst.params.tau_s
    n_pts = len(inst.points)
    inf = math.inf
    vv = [[inf] * n_pts for _ in range(n)]
    vf = [[0.0] * n_pts for _ in range(n)]
    tv, tf = inf, 0.0
    for j in range(n):
        first = route[j]
        # 合并：从位置 j 的所有状态飞到第 j+1 个观测点，取（目标 + λ·飞行）最小者，同值取飞行时间短者
        if j == 0:
            base_v, base_f = lam * dt[first], dt[first]
        else:
            base_v, base_f = inf, 0.0
            row_v, row_f = vv[j], vf[j]
            for qi in range(n_pts):
                val = row_v[qi]
                if val == inf:
                    continue
                d0 = tp[first][qi]
                c = val + lam * d0
                if c < base_v or (c == base_v and row_f[qi] + d0 < base_f):
                    base_v, base_f = c, row_f[qi] + d0
        if base_v == inf:
            continue
        t_rel = c_over_d = w_sum = path = 0.0
        srt: list = []
        for k in range(j + 1, n + 1):
            g = route[k - 1]
            if k > j + 1:
                leg = tt[route[k - 2]][g]
                path += leg
                t_rel += leg
            t_rel += tc[g]
            c_over_d += t_rel / delta[g]
            w_sum += 1.0 / delta[g]
            insort(srt, (key[g], g))
            clock = up_term = 0.0
            for _, x in srt:
                clock += up[x]
                up_term += clock / delta[x]
            base_obj = t_rel * w_sum + up_term + tau * w_sum - c_over_d
            row_t = tp[g]
            if k < n:
                row_v, row_f = vv[k], vf[k]
                for qi in range(n_pts):
                    tail = row_t[qi]
                    fly = base_f + path + tail
                    c = base_v + base_obj + tail * w_sum + lam * (path + tail)
                    if c < row_v[qi] or (c == row_v[qi] and fly < row_f[qi]):
                        row_v[qi], row_f[qi] = c, fly
            else:
                for qi in range(-1, n_pts):
                    tail = dt[g] if qi == -1 else row_t[qi]
                    back = 0.0 if qi == -1 else pd[qi]
                    fly = base_f + path + tail + back
                    c = base_v + base_obj + tail * w_sum + lam * (path + tail + back)
                    if c < tv or (c == tv and fly < tf):
                        tv, tf = c, fly
    return tv, tf


def best_lambda(inst: Instance, route: list[int], cap: float, guess: float | None = None,
                iters: int = 10) -> tuple[float, float]:
    """二分求使对偶下界最大的时间价格 λ*

    λ 增大时无约束最优方案的飞行时间不增；对偶最优在飞行时间跨过 cap 的位置，在区间两端取下界较大者。
    剪枝只需要较好的下界，不需要精确的 λ*，所以有上一次的 λ* 时以它为中心缩小区间、少迭代几次
    :param guess: 上一次的 λ*
    :return: (λ*, 该 λ 下的下界)
    """
    v0, f0 = lambda_dp_fly(inst, route, 0.0)
    if f0 <= cap + TOL:
        return 0.0, v0                              # 无约束最优已满足上限，下界即最优值
    fly = lambda lam: lambda_dp_fly(inst, route, lam)[1]
    if guess:
        lo, hi = guess / 3.0, guess * 3.0
        if fly(lo) <= cap + TOL:
            lo = 0.0
    else:
        lo, hi = 0.0, 1e-3
    while fly(hi) > cap + TOL and hi < 1e6:
        lo, hi = hi, hi * 4.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if fly(mid) > cap + TOL:
            lo = mid
        else:
            hi = mid
    d_lo = lambda_dp_fly(inst, route, lo)[0] - lo * cap
    d_hi = lambda_dp_fly(inst, route, hi)[0] - hi * cap
    return (lo, d_lo) if d_lo >= d_hi else (hi, d_hi)


# ---------- 独立的事件模拟（校验用） ----------

@dataclass
class PlanResult:
    objective: float          # Σ AoI/δ
    aoi: list                 # 每个观测点的 AoI（s），与航线顺序对应
    fly_s: float
    hover_s: float
    mission_s: float
    energy_j: float


def simulate(inst: Instance, route: list[int], stops) -> PlanResult:
    """按访问顺序与停靠方案逐事件模拟，独立于动态规划，用来校验目标、飞行时间与能耗"""
    p = inst.params
    pos_xy = p.depot
    clock = fly = hover = 0.0
    carried, aoi = [], {}
    stop_at = dict(stops)
    if not stops or stops[-1][0] != len(route):
        raise ValueError("停靠方案的最后一项必须在最后一个观测点之后")
    pt = (lambda qi: p.depot if qi == -1 else inst.points[qi])
    for k, g in enumerate(route, start=1):
        t = inst.tasks[g]
        d = math.hypot(t.x - pos_xy[0], t.y - pos_xy[1]) / p.speed_mps
        clock += d
        fly += d
        clock += t.collect_s
        hover += t.collect_s
        carried.append((g, clock))
        pos_xy = (t.x, t.y)
        if k in stop_at:
            q = pt(stop_at[k])
            d = math.hypot(q[0] - pos_xy[0], q[1] - pos_xy[1]) / p.speed_mps
            clock += d
            fly += d
            pos_xy = q
            for g2, c in sorted(carried, key=lambda x: inst.wspt_key[x[0]]):
                u = inst.up[g2]
                clock += u
                hover += u
                aoi[g2] = clock + p.tau_s - c
            carried = []
    d = math.hypot(p.depot[0] - pos_xy[0], p.depot[1] - pos_xy[1]) / p.speed_mps
    fly += d
    clock += d
    obj = sum(aoi[g] / inst.delta[g] for g in route)
    return PlanResult(obj, [aoi[g] for g in route], fly, hover, clock, p.p_fly_w * fly + p.p_hover_w * hover)
