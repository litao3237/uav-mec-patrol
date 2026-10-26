"""每架无人机的最短回路（基地出发、回基地）：16 个观测点以内精确求解，更多时用启发式"""

from __future__ import annotations

import math
import random

from .instance import Instance

EXACT_MAX = 16      # Held–Karp 的内存与时间随 2ⁿ 增长，16 个点约 1 s


def held_karp(dm: list[list[float]], n: int) -> tuple[list[int], float]:
    """精确最短回路，Held–Karp 动态规划，O(n² 2ⁿ)

    :param dm: 含基地（下标 0）的距离矩阵，观测点为 1..n
    :param n: 观测点数
    :return: (访问顺序，元素为 0..n-1, 回路长度)；两个方向长度相同，返回其中一个
    """
    inf = math.inf
    full = (1 << n) - 1
    dp = [[inf] * n for _ in range(1 << n)]
    par = [[-1] * n for _ in range(1 << n)]
    for j in range(n):
        dp[1 << j][j] = dm[0][j + 1]
    for mask in range(1, 1 << n):
        row = dp[mask]
        for j in range(n):
            cur = row[j]
            if cur == inf:
                continue
            dj = dm[j + 1]
            for k in range(n):
                bit = 1 << k
                if mask & bit:
                    continue
                v = cur + dj[k + 1]
                nm = mask | bit
                if v < dp[nm][k]:
                    dp[nm][k] = v
                    par[nm][k] = j
    best, last = min((dp[full][j] + dm[j + 1][0], j) for j in range(n))
    perm, mask, j = [], full, last
    while j != -1:
        perm.append(j)
        pj = par[mask][j]
        mask ^= 1 << j
        j = pj
    return perm[::-1], best


def _tour_len(order, dm) -> float:
    prev, s = 0, 0.0
    for i in order:
        s += dm[prev][i + 1]
        prev = i + 1
    return s + dm[prev][0]


def heuristic_tour(dm: list[list[float]], n: int, starts: int = 8, seed: int = 0) -> tuple[list[int], float]:
    """多起点（最近邻 + 随机）的 2-opt 与 Or-opt 下降，用于观测点多于 EXACT_MAX 的航线"""
    rng = random.Random(seed)
    best, best_len = None, math.inf
    for s in range(starts):
        if s == 0:
            rest, cur, order = set(range(n)), 0, []
            while rest:
                nxt = min(rest, key=lambda i: dm[cur][i + 1])
                order.append(nxt)
                rest.remove(nxt)
                cur = nxt + 1
        else:
            order = list(range(n))
            rng.shuffle(order)
        improved = True
        length = _tour_len(order, dm)
        while improved:
            improved = False
            for i in range(n - 1):
                for j in range(i + 1, n):
                    cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                    cl = _tour_len(cand, dm)
                    if cl < length - 1e-9:
                        order, length, improved = cand, cl, True
            for seg in (1, 2, 3):
                for i in range(n - seg + 1):
                    for p in range(n - seg + 1):
                        if p == i:
                            continue
                        rest_ = order[:i] + order[i + seg:]
                        cand = rest_[:p] + order[i:i + seg] + rest_[p:]
                        cl = _tour_len(cand, dm)
                        if cl < length - 1e-9:
                            order, length, improved = cand, cl, True
        if length < best_len - 1e-9:
            best, best_len = order, length
    return best, best_len


def shortest_tour(inst: Instance, gids: list[int]) -> tuple[list[int], float]:
    """一架机的最短回路（米）；返回 gid 顺序与长度。距离矩阵按与检验脚本相同的方式构造"""
    n = len(gids)
    if n == 0:
        return [], 0.0
    dep = inst.params.depot
    nodes = [dep] + [(inst.tasks[g].x, inst.tasks[g].y) for g in gids]
    dm = [[math.hypot(a[0] - b[0], a[1] - b[1]) for b in nodes] for a in nodes]
    order, length = held_karp(dm, n) if n <= EXACT_MAX else heuristic_tour(dm, n)
    return [gids[i] for i in order], length
