"""实验运行：在一个机队实例上运行全部方法，输出统一格式的记录，供汇总与作图

记录内容对应实验规划 29_ 第 5.3 节：每份数据的 AoI、是否超时、采集与送达时刻；每架机的任务时长、能耗、航程、停靠次数；
本文方法的收敛过程、下界与精确值成对样本、计时；实例特征（离覆盖边界距离、各机时间余量）。
所有方案都用独立事件模拟评估，指标口径一致
"""

from __future__ import annotations

import math
import statistics
import time

from .baselines import base_only_plan, deadline_plan, greedy_stop_plan, static_cluster_plan, two_stage_plan
from .instance import Instance
from .search import Budget, SearchConfig, reference_t_hat, solve_fleet
from .stops import simulate
from .tsp import shortest_tour

METHODS = ("B0", "B1", "B2", "B3", "B4", "P1", "P2")
BUILDERS = {"B0": base_only_plan, "B1": greedy_stop_plan, "B2": two_stage_plan,
            "B3": static_cluster_plan, "B4": deadline_plan}


def evaluate_solution(inst: Instance, plan, budget: Budget) -> dict:
    """用独立事件模拟评估一个方案

    :param inst: 实例
    :param plan: 每架机的 (航线, 停靠方案)
    :param budget: 时长预算（用于判断每架机是否可行）
    :return: {"summary": 汇总指标, "tasks": 逐份数据, "uavs": 每机统计}
    """
    p = inst.params
    tasks, uavs, total = [], [], 0.0
    for u, (route, stops) in enumerate(plan):
        if not route:
            uavs.append({"uav": u, "n": 0, "mission_s": 0.0, "fly_s": 0.0, "hover_s": 0.0, "energy_j": 0.0,
                         "distance_m": 0.0, "stops": 0, "cap_s": None, "feasible": True})
            continue
        sim = simulate(inst, list(route), list(stops))
        cap = budget.cap(route)
        uavs.append({"uav": u, "n": len(route), "mission_s": sim.mission_s, "fly_s": sim.fly_s, "hover_s": sim.hover_s,
                     "energy_j": sim.energy_j, "distance_m": sim.fly_s * p.speed_mps,
                     "stops": sum(1 for k, _ in stops if k < len(route)), "cap_s": cap,
                     "feasible": sim.fly_s <= cap + 1e-6 and sim.energy_j <= p.battery_j + 1e-6})
        for g, a, c, d in zip(route, sim.aoi, sim.collect, sim.deliver):
            tasks.append({"gid": g, "uav": u, "aoi_s": a, "delta_s": inst.delta[g], "on_time": a <= inst.delta[g] + 1e-9,
                          "collect_s": c, "deliver_s": d})
        total += sim.objective
    n = len(tasks)
    aois = sorted(t["aoi_s"] for t in tasks)
    used = [x for x in uavs if x["n"] > 0]
    summary = {
        "obj": total,
        "norm_aoi": total / n,
        "mean_aoi_s": statistics.mean(aois),
        "p95_aoi_s": statistics.quantiles(aois, n=20, method="inclusive")[18] if n >= 2 else aois[0],
        "max_aoi_s": aois[-1],
        "on_time_rate": sum(t["on_time"] for t in tasks) / n,
        "norm_overtime": sum(max(0.0, t["aoi_s"] - t["delta_s"]) / t["delta_s"] for t in tasks) / n,
        "max_mission_min": max(x["mission_s"] for x in used) / 60.0,
        "energy_kj": sum(x["energy_j"] for x in used) / 1000.0,
        "distance_km": sum(x["distance_m"] for x in used) / 1000.0,
        "stops_per_uav": statistics.mean(x["stops"] for x in used),
        "feasible": all(x["feasible"] for x in uavs),
        "assigned_once": sorted(t["gid"] for t in tasks) == list(range(inst.n)),
    }
    return {"summary": summary, "tasks": tasks, "uavs": uavs}


def per_item_lower_bound(inst: Instance) -> float:
    """逐份下界 Σ LBᵢ ÷ N：每份数据采集后直飞最近上传点并单独上传（问题定义文档 7.1 节）

    基地也可作为最后一站的上传点，一并取最近者；冻结参数下基地与 E1 圆心重合，结果与只看候选上传点相同，
    敏感性实验改动站点时下界仍然有效
    """
    tau = inst.params.tau_s
    return sum((min(min(inst.tp[g]), inst.dt[g]) + inst.up[g] + tau) / inst.delta[g] for g in range(inst.n)) / inst.n


def instance_features(inst: Instance, groups, budget: Budget) -> dict:
    """实例特征（E4 分析用）：离覆盖边界的距离、初始分配下各机的时间余量"""
    st = inst.params.stations
    dc = [min(math.hypot(t.x - sx, t.y - sy) - r for _, sx, sy, r in st) for t in inst.tasks]
    v = inst.params.speed_mps
    slack = []
    for g in groups:
        if g:
            tour, length = shortest_tour(inst, g)
            slack.append(budget.cap(tour) - length / v)
    return {"n": inst.n, "m": len(groups), "per_uav": [len(g) for g in groups],
            "mean_dist_to_coverage_m": statistics.mean(dc), "inside_coverage_frac": sum(d < 0 for d in dc) / len(dc),
            "slack_mean_s": statistics.mean(slack), "slack_std_s": statistics.pstdev(slack), "slack_min_s": min(slack),
            "t_hat_s": budget.t_hat, "eps": budget.eps, "lb_norm": per_item_lower_bound(inst)}


def instance_geometry(inst: Instance) -> dict:
    """航线图与时间线需要的几何信息，随记录保存，作图时不必重新生成实例"""
    p = inst.params
    return {"depot": list(p.depot), "stations": [[name, x, y, r] for name, x, y, r in p.stations],
            "points": [list(q) for q in inst.points], "tasks": [[t.x, t.y, inst.delta[g]] for g, t in enumerate(inst.tasks)]}


def run_methods(inst: Instance, groups, eps: float, methods=METHODS, cfg: SearchConfig | None = None,
                tag=("run",), lb_samples: int = 0) -> dict:
    """在一个机队实例上运行指定方法

    P1 与 P2 来自同一次 solve_fleet：P1 为机内搜索阶段结束时的方案，P2 为加入跨机移动后的最终方案
    :param inst: 实例
    :param groups: 初始分配
    :param eps: 时长预算 ε
    :param methods: 要运行的方法
    :param cfg: 本文方法的搜索设置
    :param tag: 本文方法的随机种子标签
    :param lb_samples: 下界与精确值成对样本的个数
    :return: 记录 {"eps", "t_hat", "features", "methods": {方法: 评估结果 + 计时 + 方案}}
    """
    t_hat = reference_t_hat(inst, groups)
    budget = Budget(inst, eps, t_hat)
    rec = {"eps": eps, "t_hat": t_hat, "t_max": (1 + eps) * t_hat, "features": instance_features(inst, groups, budget),
           "geometry": instance_geometry(inst), "methods": {}}
    for m in methods:
        if m not in BUILDERS:
            continue
        t0 = time.perf_counter()
        plan, info = BUILDERS[m](inst, groups, budget)
        secs = time.perf_counter() - t0
        out = evaluate_solution(inst, plan, budget)
        out.update(secs=secs, info=info, routes=[list(r) for r, _ in plan], stops=[[list(s) for s in st] for _, st in plan])
        rec["methods"][m] = out
    if "P1" in methods or "P2" in methods:
        t0 = time.perf_counter()
        res = solve_fleet(inst, groups, eps, cfg, tag=tag, t_hat=t_hat, lb_samples=lb_samples)
        secs = time.perf_counter() - t0
        cut = next(i for i, h in enumerate(res.history) if h[2] == "intra_end")
        variants = {"P1": (res.per_route_routes, res.per_route_plans, res.history[:cut + 1]),
                    "P2": (res.routes, res.plans, res.history)}
        for m, (routes, plans, hist) in variants.items():
            if m not in methods:
                continue
            plan = [(r, list(pl[2]) if pl is not None else []) for r, pl in zip(routes, plans)]
            out = evaluate_solution(inst, plan, budget)
            out.update(secs=secs, history=[list(h) for h in hist], routes=[list(r) for r in routes],
                       stops=[[list(s) for s in st] for _, st in plan], stats=res.stats)
            if m == "P2":
                out["lb_pairs"] = [list(x) for x in res.lb_pairs]
                out["two_stage_obj"] = res.two_stage
            rec["methods"][m] = out
    return rec


def summary_rows(rec: dict, meta: dict) -> list[dict]:
    """把一条记录展开成 CSV 行：每种方法一行，含实例元数据、实例特征与汇总指标"""
    rows = []
    feats = {k: v for k, v in rec["features"].items() if not isinstance(v, list)}
    for m, out in rec["methods"].items():
        rows.append(dict(meta, method=m, secs=out["secs"], **feats, **out["summary"]))
    return rows
