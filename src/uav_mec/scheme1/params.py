"""方案一（多无人机路线 + 上传停靠）的模型参数

数值全部从 v27 冻结配置推出（飞行与悬停功率由 Zeng 旋翼模型计算，覆盖半径由链路预算计算），
不在代码里另写一套数值；检验脚本用过的四舍五入常数可通过 with_overrides 复现
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from ..v27.params import ModelParams, load_params
from ..v27.physics import coverage_radius_m, flight_power_w, hover_power_w


@dataclass(frozen=True)
class Scheme1Params:
    """方案一的模型参数

    覆盖圈内上传速率按常数计（问题定义文档假设 2）；当前实现要求所用各站速率相同，
    这样悬停时间只取决于分配，电池约束才能折算为飞行时间上限
    """

    width_m: float
    height_m: float
    margin_m: float
    depot: tuple[float, float]
    stations: tuple[tuple[str, float, float, float], ...]   # (名称, x, y, 覆盖半径 m)，第一个为基地站
    speed_mps: float
    p_fly_w: float
    p_hover_w: float
    battery_j: float
    rate_mbps: float
    tau_s: float                      # 送达后的地面处理时间，按常数计
    ring_fractions: tuple[float, ...]
    points_per_ring: int
    include_center: bool
    data_mbit: tuple[float, float]
    freshness_s: tuple[float, float]
    collect_s: float

    def with_overrides(self, **kwargs) -> "Scheme1Params":
        return replace(self, **kwargs)


def params_from_v27(p: ModelParams, tau_s: float = 1.0) -> Scheme1Params:
    """由 v27 冻结参数构造方案一参数；观测点的数据量、时效窗与采集时间取火线态势类（heavy）

    :param p: v27 参数（load_params 的结果）
    :param tau_s: 地面处理时间（s）
    :return: 方案一参数
    :raises ValueError: 所用站点带宽不同（覆盖圈内速率不是同一常数）
    """
    sites = p.sites[: p.num_sites]
    if len({s.bandwidth_mhz for s in sites}) != 1:
        raise ValueError("当前实现要求所用站点带宽相同，覆盖圈内速率为同一常数")
    stations = tuple((s.name, s.x, s.y, coverage_radius_m(p, s.bandwidth_mhz)) for s in sites)
    return Scheme1Params(
        width_m=p.width_m, height_m=p.height_m, margin_m=p.task_margin_m, depot=tuple(p.depot_xy),
        stations=stations, speed_mps=p.speed_mps, p_fly_w=flight_power_w(p), p_hover_w=hover_power_w(p),
        battery_j=p.battery_j, rate_mbps=p.min_rate_mbps, tau_s=tau_s, ring_fractions=tuple(p.ring_fractions),
        points_per_ring=p.points_per_ring, include_center=p.include_center, data_mbit=tuple(p.heavy.data_mbit),
        freshness_s=tuple(p.heavy.freshness_s), collect_s=p.heavy.collect_s)


def load_scheme1_params(path: str | Path = "configs/v27_timeliness.yaml", tau_s: float = 1.0) -> Scheme1Params:
    return params_from_v27(load_params(path), tau_s)


def candidate_points(sp: Scheme1Params) -> list[tuple[float, float]]:
    """候选上传点：每站圆心与若干同心环上的等角点（从 0° 起），只保留区域内的点"""
    pts = []
    for _, sx, sy, radius in sp.stations:
        if sp.include_center:
            pts.append((sx, sy))
        for frac in sp.ring_fractions:
            for j in range(sp.points_per_ring):
                a = 2 * math.pi * j / sp.points_per_ring
                x, y = sx + frac * radius * math.cos(a), sy + frac * radius * math.sin(a)
                if 0 <= x <= sp.width_m and 0 <= y <= sp.height_m:
                    pts.append((x, y))
    return pts


def script_constants(sp: Scheme1Params) -> Scheme1Params:
    """第二、三道检验脚本用过的四舍五入常数（飞行功率 125.98 W、覆盖半径 597 m），仅用于回归对比"""
    return sp.with_overrides(p_fly_w=125.98, p_hover_w=168.49,
                             stations=tuple((name, x, y, 597.0) for name, x, y, _ in sp.stations))
