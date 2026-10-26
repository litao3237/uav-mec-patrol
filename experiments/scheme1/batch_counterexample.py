"""构造整批送达语义下"全部上传"非最优的反例，并在同一实例上检查逐份送达 + WSPT 时性质 2 仍成立

推导：整批送达时把数据 m 从停靠 k 推迟到下一停靠，停靠 k 上其余数据都提前 D_m/r 送达，
m 自身推迟约"两次停靠完成时刻之差"；当停靠 k 上时限紧的数据多、m 数据量大且时限宽、下一停靠很近时推迟更优
结果写入同目录 batch_counterexample_out.txt
"""

from __future__ import annotations

import itertools
from pathlib import Path

from stop_dp_verify import DEPOT, candidate_points, dist, simulate


def best_all_upload(tasks, points, semantics):
    """枚举全部"停靠位置 x 上传点"组合（每次停靠传完携带数据），返回最优值与方案"""
    n = len(tasks)
    best = (float("inf"), None)
    for r in range(n):
        for pos in itertools.combinations(range(1, n), r):
            for pts in itertools.product(points, repeat=r):
                stops = dict(zip(pos, pts))
                c, _ = simulate(tasks, stops, semantics)
                if c < best[0] - 1e-12:
                    best = (c, stops)
    return best


def best_deferral(tasks, stops, semantics):
    """在给定停靠方案上枚举每份数据可上传的所有停靠（含推迟），返回最优值与分配"""
    n = len(tasks)
    stop_pos = sorted(stops) + [n]
    elig = [[k for k, j in enumerate(stop_pos) if j >= i] for i in range(1, n + 1)]
    best = (float("inf"), None)
    for choice in itertools.product(*elig):
        assign = dict(zip(range(1, n + 1), choice))
        c, _ = simulate(tasks, stops, semantics, assign)
        if c < best[0] - 1e-12:
            best = (c, assign)
    return best


def fmt(p) -> str:
    return f"({p[0]:.1f}, {p[1]:.1f})"


def check(tasks, stops, semantics, n) -> str:
    """给定停靠方案，比较全部上传与允许推迟的最优目标"""
    c_all, _ = simulate(tasks, stops, semantics)
    c_def, assign = best_deferral(tasks, stops, semantics)
    stop_desc = "，".join(f"观测点{j}后停 {fmt(p)}" for j, p in sorted(stops.items())) or "不停靠"
    line = f"[{stop_desc}] 全部上传 {c_all:.4f}，允许推迟后最优 {c_def:.4f}"
    if c_def < c_all - 1e-9:
        first = {i: next(kk for kk, j in enumerate(sorted(stops) + [n]) if j >= i) for i in range(1, n + 1)}
        moved = [f"观测点{i}: 第{first[i] + 1}次 -> 第{k + 1}次停靠" for i, k in assign.items() if k != first[i]]
        line += f"，改善 {100 * (c_all - c_def) / c_all:.2f}%（{'；'.join(moved)}）"
    else:
        line += "，推迟无改善"
    return line


def main() -> None:
    points = candidate_points(2)
    ring_e1 = min((p for p in points if p != DEPOT), key=lambda p: dist(p, DEPOT))
    mid = ((ring_e1[0] + DEPOT[0]) / 2, (ring_e1[1] + DEPOT[1]) / 2)
    offsets = [(0.0, 0.0), (50.0, 50.0), (100.0, 0.0), (50.0, -50.0), (0.0, -100.0), (-50.0, -50.0)]
    out = [f"候选上传点 {len(points)} 个：" + "，".join(fmt(p) for p in points),
           f"E1 环上点 {fmt(ring_e1)}；观测点 7 固定在该点与基地连线中点 {fmt(mid)}；顺序固定为 1..7",
           "观测点 1-6：D = 80 Mbit、δ = 300 s，其中观测点 3 为 D = 160 Mbit、δ = 600 s；观测点 7：D = 80 Mbit、δ = 600 s"]
    # 几何 A：观测点群靠近 E2 环上点；几何 B：观测点群远离 E2、E3，回基地途中最近的是 E1 环上点
    for label, center in (("几何 A（观测点群中心 (1500, 300)，距 E2 环上点约 550 m）", (1500.0, 300.0)),
                          ("几何 B（观测点群中心 (1000, 1200)，距 E1 环上点约 780 m、距其余候选点均超过 1.1 km）", (1000.0, 1200.0))):
        tasks = []
        for idx, (dx, dy) in enumerate(offsets, start=1):
            big = idx == 3
            tasks.append({"q": (center[0] + dx, center[1] + dy), "D": 160.0 if big else 80.0, "tc": 10.0,
                          "delta": 600.0 if big else 300.0})
        tasks.append({"q": mid, "D": 80.0, "tc": 10.0, "delta": 600.0})
        n = len(tasks)
        out.append(label)
        for sem, name in (("batch", "整批送达"), ("wspt", "逐份送达 + WSPT")):
            c_all, stops = best_all_upload(tasks, points, sem)
            out.append(f"  {name}，全部上传的全局最优方案：" + check(tasks, stops, sem, n))
            out.append(f"  {name}，固定方案（观测点 6 后停 E1 环上点）：" + check(tasks, {6: ring_e1}, sem, n))
    Path(__file__).with_name("batch_counterexample_out.txt").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
