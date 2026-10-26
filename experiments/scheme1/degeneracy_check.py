"""检查"只优化 AoI、能耗只作约束"在冻结参数下是否退化为"每采一份就去送"的往返方案

做法：按冻结配置生成实例（3000 m 见方、基地 E1、3 个站点、5 架机），扇形分配 + 最近邻 + 2-opt 得到最短航线，
再在固定顺序上用停靠动态规划求 AoI 最优停靠，分别在无约束、360 kJ 电池、任务时长预算 (1+eps)*T_不停靠 下比较
关键事实：同一条航线上悬停时间（采集 + 上传）与停靠方案无关，所以电池约束等价于飞行时间（即任务时长）上限
结果写入同目录 degeneracy_check_out.txt
"""

from __future__ import annotations

import math
import random
import statistics
import time
from pathlib import Path

V, P_FLY, P_HOV = 10.0, 125.98, 168.49
W = H = 3000.0
MARGIN = 50.0
STATIONS = [(300.0, 300.0), (2500.0, 700.0), (1500.0, 2600.0)]
DEPOT = STATIONS[0]
RADIUS, RATE, TAU = 597.0, 10.0, 1.0
E_MAX = 360000.0
M_UAV = 5
TOL = 1e-9


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def candidate_points() -> list[tuple[float, float]]:
    """与冻结配置一致：每站圆心 + 0.5R、0.85R 两圈各 8 个点，保留区域内的点"""
    pts = []
    for sx, sy in STATIONS:
        pts.append((sx, sy))
        for frac in (0.5, 0.85):
            for j in range(8):
                a = 2 * math.pi * j / 8
                x, y = sx + frac * RADIUS * math.cos(a), sy + frac * RADIUS * math.sin(a)
                if 0 <= x <= W and 0 <= y <= H:
                    pts.append((x, y))
    return pts


def make_tasks(rng: random.Random, n: int) -> list[dict]:
    return [{"q": (rng.uniform(MARGIN, W - MARGIN), rng.uniform(MARGIN, H - MARGIN)),
             "D": rng.uniform(80, 160), "tc": 10.0, "delta": rng.uniform(300, 600)} for _ in range(n)]


def tour_len(seq: list[dict]) -> float:
    pts = [DEPOT] + [t["q"] for t in seq] + [DEPOT]
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def two_opt(seq: list[dict]) -> list[dict]:
    """最近邻初始解 + 2-opt，近似最短闭合航线（基地出发、回基地）"""
    rest, cur, route = list(seq), DEPOT, []
    while rest:
        nxt = min(rest, key=lambda t: dist(cur, t["q"]))
        route.append(nxt); rest.remove(nxt); cur = nxt["q"]
    improved = True
    while improved:
        improved = False
        for i in range(len(route) - 1):
            for k in range(i + 1, len(route)):
                cand = route[:i] + route[i:k + 1][::-1] + route[k + 1:]
                if tour_len(cand) < tour_len(route) - 1e-9:
                    route, improved = cand, True
    return route


def sweep_assign(tasks: list[dict]) -> list[list[dict]]:
    """按相对基地的方位角排序后等分给各无人机（扇形分配）"""
    order = sorted(tasks, key=lambda t: math.atan2(t["q"][1] - DEPOT[1], t["q"][0] - DEPOT[0]))
    size = math.ceil(len(order) / M_UAV)
    return [order[i:i + size] for i in range(0, len(order), size)]


def hover_time(route: list[dict]) -> float:
    return sum(t["tc"] + t["D"] / RATE for t in route)


def seg_terms(route, j, k):
    """航点 j+1..k 一段中与上传点无关的量：段内飞行到最后一个航点的时间、Σ(-c_i/δ_i)、WSPT 上传项、Σ1/δ、上传总时长"""
    items = route[j:k]
    order = sorted(items, key=lambda t: t["D"] * t["delta"])
    clock, up_term = 0.0, 0.0
    for t in order:
        clock += t["D"] / RATE
        up_term += clock / t["delta"]
    return order, up_term, sum(1.0 / t["delta"] for t in items), clock


def dp(route: list[dict], points, flight_cap: float | None, free_final: bool = True):
    """固定顺序下的停靠动态规划；flight_cap 为飞行时间上限（None 表示不限），返回 (Σ AoI/δ, 飞行时间, 停靠次数)

    时间不变性：段目标 = Σ_i (A + 前缀上传/r + τ - c_i)/δ_i，A 与 c_i 都从段起点 0 时刻计
    free_final=True：最后一个观测点之后可在任一上传点（含基地）传完剩余数据，再空载返回基地；
    返航段只计飞行时间、不影响 AoI。False 为旧规则（最后必须在基地上传）
    """
    n = len(route)
    labels = {(0, -1): [(0.0, 0.0, 0)]}           # 上传点序号 -1 表示基地
    pts = points
    best = None
    for j in range(0, n):
        for pi in ([-1] if j == 0 else range(len(pts))):
            if (j, pi) not in labels:
                continue
            start = DEPOT if pi == -1 else pts[pi]
            # 沿航点推进，累计段内飞行时间与 Σ c_i/δ_i
            fly, clock, c_over_d, pos = 0.0, 0.0, 0.0, start
            for k in range(j + 1, n + 1):
                t = route[k - 1]
                d = dist(pos, t["q"]) / V
                fly += d; clock += d + t["tc"]; c_over_d += clock / t["delta"]; pos = t["q"]
                _, up_term, inv_d, up_time = seg_terms(route, j, k)
                if k < n:
                    ends = list(enumerate(pts))
                else:
                    ends = [(-1, DEPOT)] + (list(enumerate(pts)) if free_final else [])
                for qi, q in ends:
                    tail = dist(pos, q) / V
                    arrive = clock + tail
                    obj = arrive * inv_d + up_term + TAU * inv_d - c_over_d
                    seg_fly = fly + tail + (dist(q, DEPOT) / V if k == n else 0.0)
                    for (o0, f0, s0) in labels[(j, pi)]:
                        cand = (o0 + obj, f0 + seg_fly, s0 + (0 if k == n else 1))
                        if flight_cap is not None and cand[1] > flight_cap + TOL:
                            continue
                        if k == n:
                            if best is None or cand[0] < best[0] - 1e-12:
                                best = cand
                            continue
                        key = (k, qi)
                        cur = labels.setdefault(key, [])
                        if flight_cap is None:
                            if not cur or cand[0] < cur[0][0]:
                                labels[key] = [cand]
                        elif not any(a <= cand[0] + 1e-12 and b <= cand[1] + 1e-9 for a, b, _ in cur):
                            labels[key] = [x for x in cur if not (cand[0] <= x[0] + 1e-12 and cand[1] <= x[1] + 1e-9)] + [cand]
    return best


def no_stop(route):
    """只在返回基地时上传：返回 (Σ AoI/δ, 飞行时间)"""
    return dp_fixed(route, {})


def dp_fixed(route, stops: dict[int, tuple]):
    """按给定停靠 {航点序号: 上传点} 计算 (Σ AoI/δ, 飞行时间)，最后一站为基地"""
    n = len(route)
    bounds = [0] + sorted(stops) + [n]
    starts = [DEPOT] + [stops[j] for j in sorted(stops)]
    ends = [stops[j] for j in sorted(stops)] + [DEPOT]
    total_obj = total_fly = 0.0
    for s in range(len(bounds) - 1):
        j, k = bounds[s], bounds[s + 1]
        fly, clock, c_over_d, pos = 0.0, 0.0, 0.0, starts[s]
        for i in range(j + 1, k + 1):
            t = route[i - 1]
            d = dist(pos, t["q"]) / V
            fly += d; clock += d + t["tc"]; c_over_d += clock / t["delta"]; pos = t["q"]
        _, up_term, inv_d, _ = seg_terms(route, j, k)
        tail = dist(pos, ends[s]) / V
        total_obj += (clock + tail) * inv_d + up_term + TAU * inv_d - c_over_d
        total_fly += fly + tail
    return total_obj, total_fly


def lower_bound(route, points) -> float:
    """每份数据 AoI 的下界：采集后直飞最近上传点并单独上传"""
    return sum((min(dist(t["q"], p) for p in points) / V + t["D"] / RATE + TAU) / t["delta"] for t in route)


def main() -> None:
    rng = random.Random(20261026)
    points = candidate_points()
    out = [f"候选上传点 {len(points)} 个；覆盖半径 {RADIUS} m；速率 {RATE} Mbit/s；电池 {E_MAX / 1e3:.0f} kJ；{M_UAV} 架机，扇形分配 + 2-opt 航线"]
    t0 = time.perf_counter()
    for n in (30, 50, 80):
        rows = []
        for seed in range(3):
            tasks = make_tasks(rng, n)
            for route in sweep_assign(tasks):
                route = two_opt(route)
                hov = hover_time(route)
                cap_batt = (E_MAX - P_HOV * hov) / P_FLY                 # 电池折算的飞行时间上限
                o_ns, f_ns = no_stop(route)
                o_free, f_free, s_free = dp(route, points, None)
                o_old = dp(route, points, None, free_final=False)[0]
                lb = lower_bound(route, points)
                row = {"n_u": len(route), "ns": (o_ns, f_ns), "free": (o_free, f_free, s_free), "lb": lb,
                       "old": o_old, "cap_batt": cap_batt, "hov": hov, "W": sum(1 / t["delta"] for t in route)}
                # 无约束最优若已满足上限，它就是带约束问题的最优解，省去帕累托标签计算
                capped = lambda cap: (o_free, f_free, s_free) if f_free <= cap + TOL else dp(route, points, cap)
                row["batt"] = capped(cap_batt)
                for eps in (0.1, 0.25, 0.5):
                    row[eps] = capped((1 + eps) * (f_ns + hov) - hov)   # 任务时长 ≤ (1+eps) * 不停靠时长
                rows.append(row)

        def mean_aoi(key):
            # 换算为按 δ 加权的平均 AoI（秒）：Σ AoI/δ ÷ Σ 1/δ
            return statistics.mean(r[key][0] / r["W"] for r in rows)

        def mean_T(key):
            return statistics.mean(r[key][1] + r["hov"] for r in rows) / 60

        free_ok = sum(r["free"][1] <= r["cap_batt"] + 1e-6 for r in rows)
        e_ns = statistics.mean((P_FLY * r["ns"][1] + P_HOV * r["hov"]) / 1e3 for r in rows)
        e_free = statistics.mean((P_FLY * r["free"][1] + P_HOV * r["hov"]) / 1e3 for r in rows)
        e_batt = statistics.mean((P_FLY * r["batt"][1] + P_HOV * r["hov"]) / 1e3 for r in rows)
        out.append(f"n = {n}（每机约 {statistics.mean(r['n_u'] for r in rows):.0f} 个观测点，3 个种子 x {M_UAV} 架机 = {len(rows)} 条航线）")
        out.append(f"  不停靠（回基地统一上传）：加权平均 AoI {mean_aoi('ns'):.0f} s，任务时长 {mean_T('ns'):.1f} min，能耗 {e_ns:.0f} kJ")
        gap_lb = max(abs(r["free"][0] - r["lb"]) for r in rows)
        out.append(f"  无约束 AoI 最优停靠：加权平均 AoI {mean_aoi('free'):.0f} s（逐份下界 {statistics.mean(r['lb'] / r['W'] for r in rows):.0f} s，"
                   f"与下界的最大偏差 {gap_lb:.1e}；旧规则即最后必须回基地上传时为 {statistics.mean(r['old'] / r['W'] for r in rows):.0f} s），"
                   f"平均停靠 {statistics.mean(r['free'][2] for r in rows):.1f} 次（不含最后一次），任务时长 {mean_T('free'):.1f} min，能耗 {e_free:.0f} kJ；"
                   f"{free_ok}/{len(rows)} 条航线在 360 kJ 以内")
        out.append(f"  360 kJ 电池约束下 AoI 最优：加权平均 AoI {mean_aoi('batt'):.0f} s，平均停靠 {statistics.mean(r['batt'][2] for r in rows):.1f} 次，"
                   f"任务时长 {mean_T('batt'):.1f} min，能耗 {e_batt:.0f} kJ")
        for eps in (0.1, 0.25, 0.5):
            out.append(f"  任务时长 ≤ {1 + eps:.2f} x 不停靠时长：加权平均 AoI {mean_aoi(eps):.0f} s，"
                       f"平均停靠 {statistics.mean(r[eps][2] for r in rows):.1f} 次，任务时长 {mean_T(eps):.1f} min")
    out.append(f"总耗时 {time.perf_counter() - t0:.1f} s")
    Path(__file__).with_name("degeneracy_check_out.txt").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
