"""数值验证方案一（路线 + 上传停靠）简化模型的结构性质，结果写入同目录 stop_dp_verify_out.txt

性质 1 分段时间不变性：一段航程（上一停靠点出发 -> 采集若干航点 -> 到下一停靠点传完）的归一化 AoI 之和
       与该段出发时刻无关，整条航线的目标等于各段从 0 时刻独立计算之和；能耗同样可加
性质 2 全部上传最优：逐份送达且站内按加权最短处理时间（WSPT）排序时，"停靠时传完全部携带数据"
       不劣于任何推迟上传的方案；整批送达语义下统计反例
性质 3 给定航线顺序，停靠位置、站点与上传点可由动态规划精确求解：与穷举对拍，含电池约束版本
参数取自冻结配置：速度 10 m/s，Zeng 飞行 125.98 W、悬停 168.49 W，数据 80-160 Mbit，采集 10 s，
时效窗 300-600 s；站点沿用 E1(基地)/E2/E3 坐标，覆盖半径 597 m，覆盖内上传速率取常数
"""

from __future__ import annotations

import itertools
import math
import random
import time
from pathlib import Path

V, P_FLY, P_HOV = 10.0, 125.98, 168.49
W = H = 3000.0
STATIONS = {"E1": (300.0, 300.0), "E2": (2500.0, 700.0), "E3": (1500.0, 2600.0)}
DEPOT = STATIONS["E1"]
RADIUS = 597.0
RATE = 10.0          # Mbit/s，覆盖边缘的保守速率；性质与具体取值无关
TAU = 1.0            # 边缘处理时间（s），按常数计
TOL = 1e-7


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def candidate_points(per_station: int) -> list[tuple[float, float]]:
    """每个站点取圆心加 per_station 个 0.85R 环上的点（保留区域内的点）"""
    pts = []
    for sx, sy in STATIONS.values():
        pts.append((sx, sy))
        for j in range(per_station):
            a = 2 * math.pi * j / per_station + 0.3
            x, y = sx + 0.85 * RADIUS * math.cos(a), sy + 0.85 * RADIUS * math.sin(a)
            if 0 <= x <= W and 0 <= y <= H:
                pts.append((x, y))
    return pts


def make_tasks(rng: random.Random, n: int) -> list[dict]:
    return [{"q": (rng.uniform(50, W - 50), rng.uniform(50, H - 50)), "D": rng.uniform(80, 160),
             "tc": 10.0, "delta": rng.uniform(300, 600)} for _ in range(n)]


def upload_batch(arrive: float, batch: list[dict], semantics: str) -> tuple[dict, float]:
    """一次停靠的上传：返回每份数据的送达时刻与上传结束时刻

    :param arrive: 到达停靠点的时刻
    :param batch: 本次上传的数据
    :param semantics: "wspt" 逐份送达且按 D*delta 升序；"batch" 整批传完才算送达
    :return: (id -> 送达时刻, 离开时刻)
    """
    out = {}
    if semantics == "batch":
        end = arrive + sum(t["D"] for t in batch) / RATE
        for t in batch:
            out[id(t)] = end + TAU
        return out, end
    clock = arrive
    for t in sorted(batch, key=lambda x: x["D"] * x["delta"]):    # Smith 规则：p/w = (D/r)*delta
        clock += t["D"] / RATE
        out[id(t)] = clock + TAU
    return out, clock


def simulate(tasks: list[dict], stops: dict[int, tuple], semantics: str, assign: dict | None = None,
             t0: float = 0.0) -> tuple[float, float]:
    """按给定停靠方案模拟整条航线

    :param tasks: 已排好顺序的航点
    :param stops: 航点序号 j（1..n-1）-> 上传点；最后一站固定为基地
    :param assign: 可选，航点序号 -> 停靠序号（用于推迟上传测试）；缺省为在采集后的第一个停靠全部上传
    :param t0: 出发时刻偏移
    :return: (归一化 AoI 之和, 能耗 J)
    """
    n = len(tasks)
    stop_pos = sorted(stops) + [n]
    stop_pt = [stops[j] for j in sorted(stops)] + [DEPOT]
    if assign is None:
        assign = {i: next(k for k, j in enumerate(stop_pos) if j >= i) for i in range(1, n + 1)}
    clock, pos, energy = t0, DEPOT, 0.0
    collect, deliver = {}, {}
    k = 0
    for i in range(1, n + 1):
        task = tasks[i - 1]
        d = dist(pos, task["q"]); energy += P_FLY * d / V; clock += d / V
        clock += task["tc"]; energy += P_HOV * task["tc"]
        collect[i] = clock; pos = task["q"]
        while k < len(stop_pos) and stop_pos[k] == i:
            d = dist(pos, stop_pt[k]); energy += P_FLY * d / V; clock += d / V
            batch = [tasks[m - 1] for m in range(1, n + 1) if assign[m] == k]
            got, end = upload_batch(clock, batch, semantics)
            energy += P_HOV * (end - clock); clock = end; pos = stop_pt[k]
            for m in range(1, n + 1):
                if assign[m] == k:
                    deliver[m] = got[id(tasks[m - 1])]
            k += 1
    obj = sum((deliver[i] - collect[i]) / tasks[i - 1]["delta"] for i in range(1, n + 1))
    return obj, energy


def segment(tasks: list[dict], start, j: int, k: int, end, semantics: str) -> tuple[float, float]:
    """航点 j+1..k 构成一段，从 start 出发、到 end 停靠并传完；从 0 时刻独立计算"""
    clock, pos, energy, collect = 0.0, start, 0.0, {}
    for i in range(j + 1, k + 1):
        task = tasks[i - 1]
        d = dist(pos, task["q"]); energy += P_FLY * d / V; clock += d / V
        clock += task["tc"]; energy += P_HOV * task["tc"]; collect[i] = clock; pos = task["q"]
    d = dist(pos, end); energy += P_FLY * d / V; clock += d / V
    batch = tasks[j:k]
    got, fin = upload_batch(clock, batch, semantics)
    energy += P_HOV * (fin - clock)
    obj = sum((got[id(tasks[i - 1])] - collect[i]) / tasks[i - 1]["delta"] for i in range(j + 1, k + 1))
    return obj, energy


def dp_exact(tasks, points, semantics: str, e_max: float | None = None) -> tuple[float, float]:
    """给定顺序下的停靠动态规划；状态 (最后上传的航点序号, 上传点)；带电池时用 (目标, 能耗) 帕累托标签"""
    n = len(tasks)
    labels = {(0, DEPOT): [(0.0, 0.0)]}
    order = [(0, DEPOT)] + [(j, p) for j in range(1, n) for p in points]
    best = None
    for (j, p) in order:
        if (j, p) not in labels:
            continue
        for k in range(j + 1, n + 1):
            ends = [DEPOT] if k == n else points
            for q in ends:
                c, e = segment(tasks, p, j, k, q, semantics)
                for (c0, e0) in labels[(j, p)]:
                    cand = (c0 + c, e0 + e)
                    if e_max is not None and cand[1] > e_max + TOL:
                        continue
                    if k == n:
                        if best is None or cand[0] < best[0] - 1e-12:
                            best = cand
                        continue
                    key = (k, q)
                    cur = labels.setdefault(key, [])
                    if e_max is None:
                        if not cur or cand[0] < cur[0][0]:
                            labels[key] = [cand]
                    elif not any(a <= cand[0] + 1e-12 and b <= cand[1] + 1e-9 for a, b in cur):
                        labels[key] = [x for x in cur if not (cand[0] <= x[0] + 1e-12 and cand[1] <= x[1] + 1e-9)] + [cand]
    return best if best is not None else (math.inf, math.inf)


def brute_force(tasks, points, semantics: str, e_max: float | None = None) -> tuple[float, float]:
    n = len(tasks)
    best = (math.inf, math.inf)
    for r in range(n):
        for pos in itertools.combinations(range(1, n), r):
            for pts in itertools.product(points, repeat=r):
                c, e = simulate(tasks, dict(zip(pos, pts)), semantics)
                if (e_max is None or e <= e_max + TOL) and c < best[0] - 1e-12:
                    best = (c, e)
    return best


def main() -> None:
    rng = random.Random(20261026)
    out = []
    t_start = time.perf_counter()

    # 性质 1：分段时间不变性与可加性
    pts4 = candidate_points(4)
    worst = 0.0
    for _ in range(500):
        n = rng.randint(4, 12)
        tasks = make_tasks(rng, n)
        r = rng.randint(0, n - 1)
        stops = dict(zip(sorted(rng.sample(range(1, n), r)), (rng.choice(pts4) for _ in range(r))))
        for sem in ("wspt", "batch"):
            full_c, full_e = simulate(tasks, stops, sem, t0=rng.uniform(0, 5000))
            bounds = [0] + sorted(stops) + [n]
            starts = [DEPOT] + [stops[j] for j in sorted(stops)]
            ends = [stops[j] for j in sorted(stops)] + [DEPOT]
            seg = [segment(tasks, starts[s], bounds[s], bounds[s + 1], ends[s], sem) for s in range(len(bounds) - 1)]
            worst = max(worst, abs(full_c - sum(x[0] for x in seg)), abs(full_e - sum(x[1] for x in seg)) / 1e3)
    out.append(f"性质1 分段时间不变性：500 条随机航线 x 2 种送达语义，随机出发偏移 0-5000 s；"
               f"整条航线目标/能耗与各段独立计算之和的最大偏差 = {worst:.2e}（能耗按 kJ 计）")

    # 性质 2：全部上传 vs 任意推迟方案
    beat = {"wspt": 0, "batch": 0}
    gap_batch = 0.0
    trials = 400
    for _ in range(trials):
        n = rng.randint(4, 6)
        tasks = make_tasks(rng, n)
        r = rng.randint(1, min(3, n - 1))
        pos = sorted(rng.sample(range(1, n), r))
        stops = dict(zip(pos, (rng.choice(pts4) for _ in range(r))))
        stop_pos = pos + [n]
        elig = [[k for k, j in enumerate(stop_pos) if j >= i] for i in range(1, n + 1)]
        for sem in ("wspt", "batch"):
            base, base_e = simulate(tasks, stops, sem)
            best = min(simulate(tasks, stops, sem, dict(zip(range(1, n + 1), choice)))[0]
                       for choice in itertools.product(*elig))
            if best < base - 1e-9:
                beat[sem] += 1
                if sem == "batch":
                    gap_batch = max(gap_batch, 100 * (base - best) / base)
    out.append(f"性质2 全部上传最优：{trials} 个随机停靠方案，枚举每份数据可上传的所有停靠（推迟方案）。"
               f"逐份送达 + WSPT 下被推迟方案击败 {beat['wspt']} 次；整批送达下被击败 {beat['batch']} 次"
               f"（最大改善 {gap_batch:.2f}%）")

    # 性质 3：动态规划 vs 穷举（无电池约束与紧电池约束）
    pts2 = candidate_points(2)
    res = {"free": [0, 0, 0.0], "tight": [0, 0, 0.0]}
    dp_time = bf_time = 0.0
    cases = 0
    for n, reps in ((5, 60), (6, 40), (7, 4)):
        for _ in range(reps):
            tasks = make_tasks(rng, n)
            no_stop_e = simulate(tasks, {}, "wspt")[1]
            for mode in ("free", "tight"):
                e_max = None if mode == "free" else no_stop_e * rng.uniform(1.0, 1.08)
                a = time.perf_counter(); dp = dp_exact(tasks, pts2, "wspt", e_max); dp_time += time.perf_counter() - a
                a = time.perf_counter(); bf = brute_force(tasks, pts2, "wspt", e_max); bf_time += time.perf_counter() - a
                res[mode][0] += 1
                same = (math.isinf(dp[0]) and math.isinf(bf[0])) or abs(dp[0] - bf[0]) <= 1e-9
                res[mode][1] += same
                if not same:
                    res[mode][2] = max(res[mode][2], abs(dp[0] - bf[0]))
            cases += 1
    out.append(f"性质3 动态规划精确性：{cases} 个随机航线（5/6/7 个航点，每站圆心 + 2 个环上点共 {len(pts2)} 个候选上传点）。"
               f"无电池约束 {res['free'][1]}/{res['free'][0]} 例与穷举最优值一致；"
               f"紧电池约束（上限为不停靠能耗的 1.00-1.08 倍）{res['tight'][1]}/{res['tight'][0]} 例一致；"
               f"最大偏差 {max(res['free'][2], res['tight'][2]):.2e}")
    out.append(f"    计时：动态规划合计 {dp_time:.1f} s，穷举合计 {bf_time:.1f} s")

    # 规模感受：单机 16 个航点、每站 8 个候选点时动态规划的耗时
    tasks = make_tasks(rng, 16)
    pts8 = candidate_points(8)
    a = time.perf_counter(); dp = dp_exact(tasks, pts8, "wspt"); t_dp = time.perf_counter() - a
    out.append(f"规模示例：16 个航点、{len(pts8)} 个候选上传点，无电池约束动态规划耗时 {t_dp:.2f} s（纯 Python，未优化）")
    out.append(f"总耗时 {time.perf_counter() - t_start:.1f} s")
    Path(__file__).with_name("stop_dp_verify_out.txt").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
