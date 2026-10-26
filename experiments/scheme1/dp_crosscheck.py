"""对拍 degeneracy_check 的加速动态规划，结果写入同目录 dp_crosscheck_out.txt

A. 旧终点规则（最后在基地上传）：对 stop_dp_verify 已验证的动态规划（不限电池）与穷举（飞行时间上限）
B. 新终点规则（最后可在任一上传点传完再返航）：对独立的事件模拟 + 穷举（不限与飞行时间上限）
"""
import itertools
import math
import random
from pathlib import Path

import degeneracy_check as fast
import stop_dp_verify as ref


def simulate_free_final(tasks, stops, final_pt):
    """事件模拟：stops 为 {航点序号: 上传点}，最后一个观测点之后在 final_pt 传完剩余数据再返回基地；返回 (Σ AoI/δ, 飞行时间)"""
    n = len(tasks)
    seq = sorted(stops) + [n]
    pts = [stops[j] for j in sorted(stops)] + [final_pt]
    clock, pos, fly, carried, obj = 0.0, ref.DEPOT, 0.0, [], 0.0
    k = 0
    for i in range(1, n + 1):
        t = tasks[i - 1]
        d = ref.dist(pos, t["q"]) / ref.V
        clock += d + t["tc"]; fly += d; pos = t["q"]; carried.append((t, clock))
        if k < len(seq) and seq[k] == i:
            d = ref.dist(pos, pts[k]) / ref.V
            clock += d; fly += d; pos = pts[k]
            for task, c in sorted(carried, key=lambda x: x[0]["D"] * x[0]["delta"]):
                clock += task["D"] / ref.RATE
                obj += (clock + ref.TAU - c) / task["delta"]
            carried = []
            k += 1
    fly += ref.dist(pos, ref.DEPOT) / ref.V
    return obj, fly


def brute_free_final(tasks, points, cap):
    n = len(tasks)
    best = math.inf
    for r in range(n):
        for pos in itertools.combinations(range(1, n), r):
            for pts in itertools.product(points, repeat=r):
                for fin in [ref.DEPOT] + list(points):
                    o, f = simulate_free_final(tasks, dict(zip(pos, pts)), fin)
                    if (cap is None or f <= cap + 1e-9) and o < best - 1e-12:
                        best = o
    return best


rng = random.Random(7)
pts = ref.candidate_points(2)
wa = wb = 0.0
na = nb = 0
for trial in range(40):
    n = rng.randint(4, 6)
    tasks = ref.make_tasks(rng, n)
    hov = fast.hover_time(tasks)
    f_ns = fast.no_stop(tasks)[1]
    cap = f_ns * rng.uniform(1.0, 1.3)
    # A：旧终点规则
    wa = max(wa, abs(fast.dp(tasks, pts, None, free_final=False)[0] - ref.dp_exact(tasks, pts, "wspt")[0]))
    wa = max(wa, abs(fast.dp(tasks, pts, cap, free_final=False)[0]
                     - ref.brute_force(tasks, pts, "wspt", ref.P_FLY * cap + ref.P_HOV * hov)[0]))
    wa = max(wa, abs(fast.no_stop(tasks)[0] - ref.simulate(tasks, {}, "wspt")[0]))
    na += 3
    # B：新终点规则
    wb = max(wb, abs(fast.dp(tasks, pts, None)[0] - brute_free_final(tasks, pts, None)))
    wb = max(wb, abs(fast.dp(tasks, pts, cap)[0] - brute_free_final(tasks, pts, cap)))
    nb += 2
out = [f"A 旧终点规则：加速动态规划 vs 已验证动态规划/穷举/模拟，{na} 组，最大偏差 {wa:.2e}",
       f"B 新终点规则：加速动态规划 vs 独立事件模拟穷举（不限与飞行时间上限各 40 组），{nb} 组，最大偏差 {wb:.2e}"]
Path(__file__).with_name("dp_crosscheck_out.txt").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
