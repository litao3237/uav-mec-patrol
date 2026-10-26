"""方案一的实例：观测点、候选上传点与预计算的距离和飞行时间，以及扇形、火线两种实例生成器"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .params import Scheme1Params, candidate_points


@dataclass(frozen=True)
class Task:
    gid: int
    x: float
    y: float
    data_mbit: float
    freshness_s: float
    collect_s: float


class Instance:
    """一个机队实例；观测点的全局编号 gid 即其在 tasks 中的下标

    预计算两套矩阵：米制距离（回路长度检查与最短回路，与检验脚本的求和方式一致）
    和飞行时间（停靠动态规划），避免在内层循环里反复开方
    """

    def __init__(self, params: Scheme1Params, tasks: list[Task], points: list[tuple[float, float]] | None = None):
        self.params = params
        self.tasks = list(tasks)
        self.points = list(points) if points is not None else candidate_points(params)
        v = params.speed_mps
        dep = params.depot
        tp_xy = [(t.x, t.y) for t in self.tasks]
        hyp = math.hypot
        self.dm_tt = [[hyp(a[0] - b[0], a[1] - b[1]) for b in tp_xy] for a in tp_xy]
        self.dm_dt = [hyp(dep[0] - a[0], dep[1] - a[1]) for a in tp_xy]
        self.tt = [[d / v for d in row] for row in self.dm_tt]
        self.dt = [d / v for d in self.dm_dt]
        self.tp = [[hyp(a[0] - b[0], a[1] - b[1]) / v for b in self.points] for a in tp_xy]
        self.pd = [hyp(b[0] - dep[0], b[1] - dep[1]) / v for b in self.points]
        self.tc = [t.collect_s for t in self.tasks]
        self.delta = [t.freshness_s for t in self.tasks]
        self.up = [t.data_mbit / params.rate_mbps for t in self.tasks]
        self.wspt_key = [t.data_mbit * t.freshness_s for t in self.tasks]

    @property
    def n(self) -> int:
        return len(self.tasks)

    def hover_time(self, route) -> float:
        """一条航线的悬停时间（采集 + 上传），按航线顺序逐点累加，与检验脚本一致"""
        return sum(self.tc[g] + self.up[g] for g in route)

    def route_length_m(self, route) -> float:
        """基地出发、按顺序访问、回基地的回路长度（米），求和顺序与检验脚本一致"""
        if not route:
            return 0.0
        s = self.dm_dt[route[0]]
        for a, b in zip(route, route[1:]):
            s += self.dm_tt[a][b]
        return s + self.dm_dt[route[-1]]


# ---------- 实例生成（随机数调用顺序与检验脚本一致，保证可复现） ----------

def seed_of(*parts) -> int:
    """由整数与短字符串确定的随机种子，不依赖 Python 的哈希随机化"""
    s = 0
    for p in parts:
        for ch in str(p):
            s = (s * 131 + ord(ch)) % (2 ** 61 - 1)
    return s


def uniform_points(rng: random.Random, n: int, sp: Scheme1Params) -> list[tuple[float, float, float, float]]:
    """区域内均匀随机的观测点 (x, y, 数据量, 时效窗)"""
    out = []
    for _ in range(n):
        x = rng.uniform(sp.margin_m, sp.width_m - sp.margin_m)
        y = rng.uniform(sp.margin_m, sp.height_m - sp.margin_m)
        d = rng.uniform(*sp.data_mbit)
        delta = rng.uniform(*sp.freshness_s)
        out.append((x, y, d, delta))
    return out


def fireline_points(rng: random.Random, n: int, sp: Scheme1Params) -> list[tuple[float, float, float, float]]:
    """椭圆火线：长半轴 700–1100 m、长宽比 1.5–2.5、朝向随机，沿火线按参数角等距布点并加小幅扰动"""
    a = rng.uniform(700, 1100)
    b = a / rng.uniform(1.5, 2.5)
    th = rng.uniform(0, math.pi)
    # 椭圆外接矩形的半宽、半高，保证全部观测点留在区域内
    hx = math.sqrt((a * math.cos(th)) ** 2 + (b * math.sin(th)) ** 2)
    hy = math.sqrt((a * math.sin(th)) ** 2 + (b * math.cos(th)) ** 2)
    m = sp.margin_m
    cx = rng.uniform(m + hx + 30, sp.width_m - m - hx - 30)
    cy = rng.uniform(m + hy + 30, sp.height_m - m - hy - 30)
    phase = rng.uniform(0, 2 * math.pi)
    out = []
    for k in range(n):
        t = phase + 2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / n
        x0, y0 = a * math.cos(t), b * math.sin(t)
        x = cx + x0 * math.cos(th) - y0 * math.sin(th) + rng.uniform(-20, 20)
        y = cy + x0 * math.sin(th) + y0 * math.cos(th) + rng.uniform(-20, 20)
        q = (min(max(x, m), sp.width_m - m), min(max(y, m), sp.height_m - m))
        out.append((q[0], q[1], rng.uniform(*sp.data_mbit), rng.uniform(*sp.freshness_s)))
    return out


def sweep_assign(inst: Instance, gids: list[int], m: int) -> list[list[int]]:
    """按相对基地的方位角排序后等分给 m 架机（扇形分配）"""
    dep = inst.params.depot
    order = sorted(gids, key=lambda g: math.atan2(inst.tasks[g].y - dep[1], inst.tasks[g].x - dep[0]))
    size = math.ceil(len(order) / m)
    return [order[i:i + size] for i in range(0, len(order), size)]


def arc_assign(inst: Instance, gids: list[int], m: int) -> list[list[int]]:
    """gids 为沿火线的次序；从离基地最近的观测点开始切成 m 段连续弧"""
    start = min(range(len(gids)), key=lambda i: inst.dm_dt[gids[i]])
    order = gids[start:] + gids[:start]
    size = math.ceil(len(order) / m)
    return [order[i:i + size] for i in range(0, len(order), size)]


def make_instance(layout: str, n: int, m: int, seed: int, sp: Scheme1Params) -> tuple[Instance, list[list[int]]]:
    """生成机队实例与初始分配；与第三道检验 fleet_groups 的随机数流一致

    :param layout: "sector"（均匀布点 + 扇形分配）或 "fireline"（椭圆火线 + 连续弧段分配）
    :param n: 观测点总数
    :param m: 无人机数
    :param seed: 种子序号
    :param sp: 模型参数
    :return: (实例, 每架机的观测点 gid 列表)
    """
    rng = random.Random(seed_of("gate3", layout, n, seed))
    raw = uniform_points(rng, n, sp) if layout == "sector" else fireline_points(rng, n, sp)
    tasks = [Task(i, x, y, d, delta, sp.collect_s) for i, (x, y, d, delta) in enumerate(raw)]
    inst = Instance(sp, tasks)
    gids = list(range(n))
    groups = sweep_assign(inst, gids, m) if layout == "sector" else arc_assign(inst, gids, m)
    return inst, groups
