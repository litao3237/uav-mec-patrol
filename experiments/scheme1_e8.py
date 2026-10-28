"""方案一 E8：更强搜索对照（实验规划 29_ 第 2 节 E8；判定规则运行前写定）

在大规模实例（N = 80、120，5 架机，两种布点，ε ∈ {0.1, 0.25}，种子 100–119；N = 50 作参照）上，用多起点 +
扰动的迭代局部搜索（ILS）在 P2 评估次数的 10 倍预算内继续搜索，量出本文方法的局部搜索还留下多少改进空间。
ILS 与 P2 用同一个评估器、同一套机内与跨机邻域、同一个时长预算；求解器代码（src/uav_mec/scheme1/）不改。
冻结求解器的跨机阶段写在 solve_fleet 内部、不能单独调用，所以在本脚本里按同样的规则重写，并在每个实例上
逐步复现一次 P2，核对与冻结求解器逐位相同

每个实例内部并行（--workers 个进程）：先同时跑 P2、P2 的逐步复现与冷启动链的初始求解，再同时跑 4 条链；
各任务的随机数流互相独立，单进程顺序运行的结果相同

N = 50、80 的 P2 目标还与 E1 的记录比对（参考值取自 E1 汇总产物 E1_rows.csv，run 40295745598，
存为 experiments/scheme1_e8_e1_p2_ref.csv）

用法：
  python experiments/scheme1_e8.py shard --shard 0 --shards 40 --workers 4 --out 目录
  python experiments/scheme1_e8.py summary --inputs 目录 --out 目录
  python experiments/scheme1_e8.py smoke --out 目录
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from uav_mec.scheme1 import (
    Budget,
    RouteEvaluator,
    SearchConfig,
    evaluate_solution,
    load_scheme1_params,
    make_instance,
    reference_t_hat,
    route_local_search,
    seed_of,
    shortest_tour,
    solve_fleet,
)

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
REF_E1 = ROOT / "experiments" / "scheme1_e8_e1_p2_ref.csv"
LAYOUTS = ("fireline", "sector")
SIZES = (50, 80, 120)
DECIDE_SIZES = (80, 120)              # 判定只用这两个规模；N = 50 只作参照
M_UAV = 5
EPS = (0.1, 0.25)
SEEDS = tuple(range(100, 120))
BUDGET_X = 10.0                       # ILS 的总评估预算 = P2 在同一实例上评估次数的倍数
CHAINS = 4                            # 1 条热启动（从 P2 的解）+ 3 条冷启动，各占 1/4 预算，在 4 个进程中并行；
                                      # 可行的冷启动起点不足 3 个时，以不同随机数流增开热启动链补足
CHECKPOINTS = (2.0, 5.0, 10.0)        # 另报告的预算倍数；4 条链各按同一比例截取，等价于 4 条链并行
KICK_TRIES = 20                       # 扰动后回路长度超限时的重抽次数
MAX_IDLE = 50                         # 连续这么多次迭代没有新的评估（候选都见过，或扰动重抽后仍不可行）就停止该链
# 用于分片均衡的 P2 单次耗时估计（s）：N = 50、80 为 E1 在 Actions 上的均值；N = 120 的 ε = 0.1 取 E5 的计时，
# ε = 0.25 按 N = 80 时两档 ε 的耗时比外推（火线约 4.2 倍、扇形约 7.1 倍）
P2_SECS = {("fireline", 50, 0.1): 13.2, ("fireline", 50, 0.25): 34.0, ("sector", 50, 0.1): 13.5,
           ("sector", 50, 0.25): 52.1, ("fireline", 80, 0.1): 63.2, ("fireline", 80, 0.25): 268.1,
           ("sector", 80, 0.1): 92.9, ("sector", 80, 0.25): 661.9, ("fireline", 120, 0.1): 258.0,
           ("fireline", 120, 0.25): 1094.0, ("sector", 120, 0.1): 114.0, ("sector", 120, 0.25): 812.0}


def jobs(sizes=SIZES, seeds=SEEDS, eps_list=EPS, layouts=LAYOUTS) -> list[tuple]:
    """全部运行单元 (布点, N, 种子, ε)"""
    return [(lay, n, s, e) for lay in layouts for n in sizes for e in eps_list for s in seeds]


def est_cost(job: tuple) -> float:
    """单实例在作业中的墙钟耗时估计（只用于均匀分片）

    P2、逐步复现与冷启动初始求解并行（约 2 次 P2 的时间），4 条链再并行（约 2.5 次），合计约 4.5 次 P2
    """
    layout, n, _, eps = job
    base = P2_SECS.get((layout, n, eps), (n / M_UAV / 10) ** 2 * 10.0 * (1 + 8 * eps))
    return base * 4.5


def shard_jobs(shard: int, shards: int, job_list=None) -> list[tuple]:
    """按估计耗时降序蛇形分配到各分片"""
    order = sorted(job_list or jobs(), key=lambda j: (-est_cost(j), j))
    return [j for i, j in enumerate(order) if (i % (2 * shards) if i % (2 * shards) < shards
                                               else 2 * shards - 1 - i % (2 * shards)) == shard]


def record_name(meta: dict) -> str:
    return f"E8_{meta['layout']}_n{meta['n']}_s{meta['seed']}_e{meta['eps']}"


def base_order(inst, layout: str) -> list[int]:
    """初始分配所依据的观测点次序，与 instance.arc_assign / sweep_assign 相同

    火线：沿火线（生成次序），从离基地最近的观测点起；扇形：按相对基地的方位角
    """
    gids = list(range(inst.n))
    if layout == "fireline":
        start = min(range(len(gids)), key=lambda i: inst.dm_dt[gids[i]])
        return gids[start:] + gids[:start]
    dep = inst.params.depot
    return sorted(gids, key=lambda g: math.atan2(inst.tasks[g].y - dep[1], inst.tasks[g].x - dep[0]))


def rotated_groups(inst, layout: str, m: int, offset: int) -> list[list[int]]:
    """冷启动的初始分配：把切分点沿上述次序整体平移 offset 个观测点

    :param offset: 平移的观测点数；0 时与 make_instance 给出的初始分配相同
    :return: 每架机的观测点 gid 列表
    """
    order = base_order(inst, layout)
    order = order[offset:] + order[:offset]
    size = math.ceil(len(order) / m)
    return [order[i:i + size] for i in range(0, len(order), size)]


def cross_phase(inst, ev, routes: list, vals: list, cfg, rng: random.Random, tag) -> dict:
    """跨机移动与交换：规则与冻结求解器 solve_fleet 的跨机阶段逐行相同，就地修改 routes、vals

    候选为每个观测点最近的 cfg.neighbors 个异机观测点（移到其前或其后、或与之交换），首次改进；
    接受后对两条航线各做至多 cfg.reopt_evals 次评估的短局部搜索；评估上限 cfg.inter_evals
    :param tag: 短局部搜索的随机种子标签（在 solve_fleet 中即求解标签）
    :return: {"inter_evals", "reopt_evals", "accepted"}
    """
    all_g = [g for r in routes for g in r]
    near = {g: sorted(all_g, key=lambda x: inst.dm_tt[x][g])[1:cfg.neighbors * 3 + 1] for g in all_g}
    incs = [ev.incumbent(r, v) for r, v in zip(routes, vals)]
    inter_evals = accepted = reopt_evals = 0
    while inter_evals < cfg.inter_evals:
        where = {g: (u, i) for u, r in enumerate(routes) for i, g in enumerate(r)}
        moves = []
        for g1, (u, i) in where.items():
            cnt = 0
            for g2 in near[g1]:
                w, j = where[g2]
                if w == u:
                    continue
                moves += [("rel", u, i, w, j), ("rel", u, i, w, j + 1), ("swp", u, i, w, j)]
                cnt += 1
                if cnt >= cfg.neighbors:
                    break
        rng.shuffle(moves)
        improved = False
        for kind, u, i, w, j in moves:
            ru, rw = list(routes[u]), list(routes[w])
            if kind == "rel":
                if len(ru) <= 1:
                    continue
                rw.insert(j, ru.pop(i))
            else:
                ru[i], rw[j] = rw[j], ru[i]
            ok_u, ok_w = ev.length_ok(ru), ev.length_ok(rw)
            inter_evals += (ok_u and ev.touch(ru)) + (ok_w and ev.touch(rw))
            if ok_u and ok_w:
                threshold = vals[u][0] + vals[w][0]
                pair = ev.pair_values(ru, rw, incs[u], incs[w], threshold)
                if pair is not None and pair[0] is not None and pair[1] is not None \
                        and pair[0][0] + pair[1][0] < threshold - 1e-12:
                    ru, vu, used_u, _ = route_local_search(ev, ru, cfg.reopt_evals,
                                                           random.Random(seed_of(*tag, accepted, "u")))
                    rw, vw, used_w, _ = route_local_search(ev, rw, cfg.reopt_evals,
                                                           random.Random(seed_of(*tag, accepted, "w")))
                    reopt_evals += used_u + used_w
                    routes[u], routes[w], vals[u], vals[w] = ru, rw, vu, vw
                    incs[u] = ev.incumbent(ru, vu, prev=incs[u])
                    incs[w] = ev.incumbent(rw, vw, prev=incs[w])
                    accepted += 1
                    improved = True
                    break
            if inter_evals >= cfg.inter_evals:
                break
        if not improved:
            break
    return {"inter_evals": inter_evals, "reopt_evals": reopt_evals, "accepted": accepted}


def replicate_p2(inst, groups, eps: float, t_hat: float, cfg, tag) -> dict:
    """按 solve_fleet 的步骤逐步复现 P2：两阶段 → 每机局部搜索（两个方向起步）→ 跨机阶段

    用途：核对本脚本重写的跨机阶段与冻结求解器逐位相同（ILS 用的就是这个函数），
    并记录每机局部搜索是否在评估上限内收敛（solve_fleet 不返回这一信息）
    :return: {"routes", "vals", "per_route", "objective", "intra_converged", "inter_evals", ...}
    """
    budget = Budget(inst, eps, t_hat)
    ev = RouteEvaluator(inst, budget.cap, cfg.accelerate, 0, cfg.depot_terminal)
    tours = [shortest_tour(inst, g) for g in groups]
    for tour, _ in tours:
        cands = [tour, tour[::-1]]
        for c in cands:
            if ev.length_ok(c):
                ev.touch(c)
        for c in cands:
            ev.exact(c)
    routes, vals, converged = [], [], []
    for u, (tour, _) in enumerate(tours):
        best = None
        for si, start in enumerate((tour, tour[::-1])):
            r, v, _, ok = route_local_search(ev, start, cfg.evals(len(tour)), random.Random(seed_of(*tag, u, si)))
            converged.append(bool(ok))
            if best is None or v[0] < best[1][0]:
                best = (r, v)
        routes.append(best[0])
        vals.append(best[1])
    per_route = sum(v[0] for v in vals)
    st = cross_phase(inst, ev, routes, vals, cfg, random.Random(seed_of(*tag, "inter")), tag)
    return {"routes": routes, "vals": vals, "per_route": per_route, "objective": sum(v[0] for v in vals),
            "intra_converged": converged, **st}


# ---------------------------------------------------------------------------
# 扰动与迭代局部搜索
# ---------------------------------------------------------------------------

KICK_KINDS = ("bridge", "block", "swaps")


def kick_bridge(inst, routes, rng):
    """double-bridge：某架机的航线切成 A B C D 四段，重排为 A C B D；只对至少 8 个观测点的航线做

    :return: (扰动后的航线, 改动的机号) 或 None（没有足够长的航线）
    """
    cand = [u for u, r in enumerate(routes) if len(r) >= 8]
    if not cand:
        return None
    u = rng.choice(cand)
    r = routes[u]
    i, j, k = sorted(rng.sample(range(1, len(r)), 3))
    new = [list(x) for x in routes]
    new[u] = r[:i] + r[j:k] + r[i:j] + r[k:]
    return new, [u]


def kick_block(inst, routes, rng):
    """整块移交：从某架机取连续 2–4 个观测点，插到离块中点最近的异机观测点之后；原航线至少留 2 个点"""
    cand = [u for u, r in enumerate(routes) if len(r) >= 4]
    if not cand:
        return None
    u = rng.choice(cand)
    r = routes[u]
    length = rng.choice([k for k in (2, 3, 4) if k <= len(r) - 2])
    s = rng.randrange(len(r) - length + 1)
    blk = r[s:s + length]
    mid = blk[length // 2]
    others = [(g, w, j) for w, rw in enumerate(routes) if w != u for j, g in enumerate(rw)]
    if not others:
        return None
    _, w, j = min(others, key=lambda x: (inst.dm_tt[mid][x[0]], x[0]))
    new = [list(x) for x in routes]
    new[u] = r[:s] + r[s + length:]
    new[w] = routes[w][:j + 1] + blk + routes[w][j + 1:]
    return new, [u, w]


def kick_swaps(inst, routes, rng, times: int = 2, neighbors: int = 5):
    """跨机交换 times 次：随机取一个观测点，与它最近的 neighbors 个异机观测点之一交换"""
    new = [list(x) for x in routes]
    changed = set()
    for _ in range(times):
        where = {g: (u, i) for u, r in enumerate(new) for i, g in enumerate(r)}
        g = rng.choice(sorted(where))
        u, i = where[g]
        others = sorted((h for h in where if where[h][0] != u), key=lambda h: (inst.dm_tt[g][h], h))[:neighbors]
        if not others:
            return None
        h = rng.choice(others)
        w, j = where[h]
        new[u][i], new[w][j] = h, g
        changed |= {u, w}
    return new, sorted(changed)


KICKS = {"bridge": kick_bridge, "block": kick_block, "swaps": kick_swaps}


def kick(inst, ev, routes, rng):
    """随机选一种扰动并施加；改动的航线回路长度超出上限时重抽

    :return: (扰动后的航线, 改动的机号, 扰动类型) 或 None（重抽 KICK_TRIES 次仍不可行）
    """
    for _ in range(KICK_TRIES):
        kind = rng.choice(KICK_KINDS)
        res = KICKS[kind](inst, routes, rng)
        if res is None:
            continue
        new, changed = res
        if all(ev.length_ok(new[u]) for u in changed):
            return new, changed, kind
    return None


def ils_chain(inst, budget, cfg, routes, chain_budget: float, used0: int, tag, rng: random.Random) -> dict:
    """一条迭代局部搜索链：扰动 → 改动航线的机内局部搜索 → 跨机阶段 → 机队目标更好才接受，否则退回

    评估器、邻域与评估上限都与 P2 相同；评估次数按不同候选航线的个数计（RouteEvaluator.touch），与 P2 一致
    :param routes: 起点方案的各机航线（热启动为 P2 的解，冷启动为扰动分配后按 P2 流程求得的解）
    :param chain_budget: 本链的评估预算（含起点已用的评估）
    :param used0: 起点已用的评估次数（冷启动链的初始求解计入本链）
    :param tag: 随机种子标签前缀
    :param rng: 选择扰动用的随机数
    :return: {"routes", "stops", "obj", "evals", "iters", "accepted", "stop", "kinds", "history"}；
             history 为 (累计评估次数, 至今最好的机队目标)
    """
    ev = RouteEvaluator(inst, budget.cap, cfg.accelerate, 0, cfg.depot_terminal)
    cur_r = [list(r) for r in routes]
    cur_v = [ev.exact(r) for r in cur_r]
    cur = sum(v[0] for v in cur_v)
    evals, history = used0, [(used0, cur)]
    it = accepted = idle = 0
    stop = "budget"
    kinds = {k: [0, 0] for k in KICK_KINDS}          # 每种扰动：(尝试次数, 被接受次数)
    while evals < chain_budget:
        it += 1
        kk = kick(inst, ev, cur_r, rng)
        if kk is None:
            # 重抽 KICK_TRIES 次仍超出回路长度上限：记为一次空转，随机数已前进，下次迭代换一组扰动；
            # 只停这一次就结束整条链会白白浪费预算（时长预算紧时扰动常不可行），连续空转 MAX_IDLE 次才停止
            idle += 1
            if idle >= MAX_IDLE:
                stop = "no_feasible_kick"
                break
            continue
        new_r, changed, kind = kk
        new_v = list(cur_v)
        before = evals
        # 机内搜索与跨机阶段的评估上限再按本链剩余预算截断，使总用量贴近预算（只影响每条链的最后一次迭代）；
        # 上限为 0 时 route_local_search 只评估扰动后的航线本身，跨机阶段不做
        for u in changed:
            lim = max(0, min(cfg.evals(len(new_r[u])), math.ceil(chain_budget - evals)))
            r, v, used, _ = route_local_search(ev, new_r[u], lim, random.Random(seed_of(*tag, it, u)))
            new_r[u], new_v[u] = r, v
            evals += used
        cfg_it = replace(cfg, inter_evals=max(0, min(cfg.inter_evals, math.ceil(chain_budget - evals))))
        st = cross_phase(inst, ev, new_r, new_v, cfg_it, random.Random(seed_of(*tag, it, "inter")), (*tag, it))
        evals += st["inter_evals"] + st["reopt_evals"]
        kinds[kind][0] += 1
        obj = sum(v[0] for v in new_v)
        if obj < cur - 1e-12:
            cur_r, cur_v, cur = new_r, new_v, obj
            accepted += 1
            kinds[kind][1] += 1
        history.append((evals, cur))
        idle = idle + 1 if evals == before else 0
        if idle >= MAX_IDLE:
            stop = "idle"
            break
    return {"routes": cur_r, "stops": [list(v[2]) for v in cur_v], "obj": cur, "evals": evals, "iters": it,
            "accepted": accepted, "stop": stop, "kinds": kinds, "history": history}


def feasible_offsets(inst, layout: str, budget, cfg, rng: random.Random, need: int) -> list[int]:
    """冷启动用的轮转偏移：按随机次序逐个试，只用"每架机最短回路不停靠也在预算内"的偏移

    预算 (1+ε)T̂ 按原实例的初始分配计算、保持不变；轮转后的分配可能有某架机不停靠也超预算，
    这样的分配不能作起点（冻结求解器假定初始分配可行）
    :param need: 需要的偏移个数
    :return: 至多 need 个可行偏移（可行的不足时少于 need）
    """
    ev = RouteEvaluator(inst, budget.cap, cfg.accelerate, 0, cfg.depot_terminal)
    cand = list(range(1, math.ceil(inst.n / M_UAV)))
    rng.shuffle(cand)
    out = []
    for off in cand:
        groups = rotated_groups(inst, layout, M_UAV, off)
        if all(ev.length_ok(shortest_tour(inst, g)[0]) for g in groups):
            out.append(off)
            if len(out) == need:
                break
    return out


def fleet_evals(stats: dict) -> int:
    """solve_fleet 的评估次数：机内、跨机与跨机后短搜索之和（与其收敛记录的横轴一致）"""
    return int(stats["intra_evals"] + stats["inter_evals"] + stats["reopt_evals"])


def setup(job: tuple):
    """由运行单元重建实例与求解设置（各工作进程各自重建，不在进程间传大对象；生成过程确定，结果相同）

    :return: (实例, 初始分配, 搜索设置, T̂, 预算, 与 E1 相同的随机种子标签)
    """
    layout, n, seed, eps = job
    inst, groups = make_instance(layout, n, M_UAV, seed, load_scheme1_params(str(CONFIG)))
    t_hat = reference_t_hat(inst, groups)
    return inst, groups, SearchConfig(), t_hat, Budget(inst, eps, t_hat), (layout, n, M_UAV, seed, eps)


def task_p2(job: tuple) -> dict:
    """冻结求解器的 P2（与 E1 同一随机种子标签）"""
    inst, groups, cfg, t_hat, _, tag = setup(job)
    t0 = time.perf_counter()
    res = solve_fleet(inst, groups, job[3], cfg, tag=tag, t_hat=t_hat)
    return {"routes": res.routes, "plans": res.plans, "objective": res.objective, "per_route": res.per_route,
            "stats": {k: v for k, v in res.stats.items() if isinstance(v, (int, float))},
            "secs": time.perf_counter() - t0}


def task_replica(job: tuple) -> dict:
    """在本脚本中逐步复现 P2（见 replicate_p2）"""
    inst, groups, cfg, t_hat, _, tag = setup(job)
    t0 = time.perf_counter()
    rep = replicate_p2(inst, groups, job[3], t_hat, cfg, tag)
    rep["secs"] = time.perf_counter() - t0
    return rep


def task_cold_init(job: tuple, k: int, offset: int) -> dict:
    """冷启动链的起点：轮转后的初始分配按 P2 的流程求解（T̂ 与预算保持原实例的值）"""
    inst, _, cfg, t_hat, _, tag = setup(job)
    t0 = time.perf_counter()
    r0 = solve_fleet(inst, rotated_groups(inst, job[0], M_UAV, offset), job[3], cfg, tag=("E8cold", *tag, k),
                     t_hat=t_hat)
    return {"k": k, "offset": offset, "routes": r0.routes, "objective": r0.objective, "evals": fleet_evals(r0.stats),
            "secs": time.perf_counter() - t0}


def task_chain(job: tuple, routes, chain_budget: float, used0: int, key: tuple) -> dict:
    """一条 ILS 链（见 ils_chain）；key 决定随机数流"""
    inst, _, cfg, _, budget, tag = setup(job)
    t0 = time.perf_counter()
    ch = ils_chain(inst, budget, cfg, routes, chain_budget, used0, ("E8", *tag, *key),
                   random.Random(seed_of("E8", *tag, *key)))
    ch["secs"] = time.perf_counter() - t0
    return ch


def chain_specs(p2: dict, colds: list[dict]) -> list[dict]:
    """4 条链的起点：链 0 从 P2 的解出发；可行的冷启动有几条就用几条；不足 3 条时以不同随机数流增开热启动链

    每条链的预算相同（总预算的 1/4），这样 4 条链总能在 4 个进程中并行
    :return: [{"start", "offset", "routes", "init_obj", "used0", "key"}]，共 CHAINS 条
    """
    specs = [{"start": "warm", "offset": 0, "routes": p2["routes"], "init_obj": p2["objective"], "used0": 0,
              "key": (0,)}]
    specs += [{"start": "warm", "offset": 0, "routes": p2["routes"], "init_obj": p2["objective"], "used0": 0,
               "key": ("warm", j)} for j in range(1, CHAINS - len(colds))]
    specs += [{"start": "cold", "offset": c["offset"], "routes": c["routes"], "init_obj": c["objective"],
               "used0": c["evals"], "key": (c["k"],)} for c in colds]
    return specs


class _Done:
    """单进程运行时的"已完成的任务"，接口与 concurrent.futures.Future 的 result() 相同"""

    def __init__(self, value):
        self.value = value

    def result(self):
        return self.value


def submit(pool, fn, *args):
    """有进程池时提交任务，没有时就地运行（测试里用 importlib 载入本模块时，函数无法被子进程按名导入）"""
    return pool.submit(fn, *args) if pool is not None else _Done(fn(*args))


def run_instance(job: tuple, pool=None) -> dict:
    """一个实例：P2（冻结求解器）、P2 逐步复现与冷启动的初始求解并行 → 4 条 ILS 链并行 → 用独立事件模拟评估

    :param job: (布点, N, 种子, ε)
    :param pool: 进程池；None 时按顺序就地运行，结果相同（各任务的随机数流互相独立）
    :return: 记录（P2 与 ILS 的结果、各链过程、预算截点上的最好目标与改善）
    """
    layout, n, seed, eps = job
    t0 = time.perf_counter()
    inst, _, cfg, t_hat, budget, tag = setup(job)
    offsets = feasible_offsets(inst, layout, budget, cfg, random.Random(seed_of("E8cold", *tag)), CHAINS - 1)
    f_p2, f_rep = submit(pool, task_p2, job), submit(pool, task_replica, job)
    f_cold = [submit(pool, task_cold_init, job, k, off) for k, off in enumerate(offsets, start=1)]
    p2, rep, colds = f_p2.result(), f_rep.result(), [f.result() for f in f_cold]
    e_p2 = fleet_evals(p2["stats"])
    share = BUDGET_X * e_p2 / CHAINS
    specs = chain_specs(p2, colds)
    futs = [submit(pool, task_chain, job, s["routes"], share, s["used0"], s["key"]) for s in specs]
    chains = [{"start": s["start"], "offset": s["offset"], "init_obj": s["init_obj"], "budget": share, **f.result()}
              for s, f in zip(specs, futs)]
    replica_ok = (rep["routes"] == p2["routes"] and rep["objective"] == p2["objective"]
                  and rep["per_route"] == p2["per_route"] and rep["inter_evals"] == p2["stats"]["inter_evals"])
    p2_eval = evaluate_solution(inst, [(r, list(pl[2])) for r, pl in zip(p2["routes"], p2["plans"])], budget)["summary"]
    ils_secs = sum(c["secs"] for c in chains) + sum(c["secs"] for c in colds)      # 计算量：各链与冷启动求解的耗时之和
    # 预算截点：各链截取本链预算的同一比例，取其中最好者与 P2 的较小值（热启动链从 P2 的解出发）。
    # 每条链在预算用完前开始的迭代都会做完（最后一次迭代按剩余预算截断），满预算的截点取全部记录
    res_obj, res_routes, res_stops = p2["objective"], p2["routes"], [list(pl[2]) for pl in p2["plans"]]
    checkpoints = {}
    for x in CHECKPOINTS:
        best = res_obj
        for c in chains:
            lim = math.inf if x >= BUDGET_X else c["budget"] * x / BUDGET_X
            vs = [o for e, o in c["history"] if e <= lim + 1e-9]
            if vs:
                best = min(best, min(vs))
        checkpoints[f"{x:g}"] = best
    k_best = min(range(len(chains)), key=lambda i: (chains[i]["obj"], i))
    if chains[k_best]["obj"] < res_obj - 1e-12:
        best_routes, best_stops, best_dp = chains[k_best]["routes"], chains[k_best]["stops"], chains[k_best]["obj"]
    else:
        k_best, best_routes, best_stops, best_dp = -1, res_routes, res_stops, res_obj
    ils_eval = evaluate_solution(inst, list(zip(best_routes, best_stops)), budget)["summary"]
    gain = {f"{x:g}": 100.0 * (res_obj - checkpoints[f"{x:g}"]) / res_obj for x in CHECKPOINTS}
    gain["final"] = 100.0 * (p2_eval["obj"] - ils_eval["obj"]) / p2_eval["obj"]     # 判定用：独立事件模拟的目标
    warm = [c["obj"] for c in chains if c["start"] == "warm"]
    cold = [c["obj"] for c in chains if c["start"] == "cold"]
    return {
        "meta": {"exp": "E8", "layout": layout, "n": n, "m": M_UAV, "seed": seed, "eps": eps},
        "t_hat": t_hat, "share": share,
        "p2": {"obj": p2_eval["obj"], "norm_aoi": p2_eval["norm_aoi"], "dp_obj": res_obj, "evals": e_p2,
               "secs": p2["secs"], "feasible": p2_eval["feasible"], "assigned_once": p2_eval["assigned_once"],
               "inter_evals": p2["stats"]["inter_evals"],
               "inter_cap_hit": p2["stats"]["inter_evals"] >= cfg.inter_evals,
               "intra_runs": len(rep["intra_converged"]), "intra_nonconverged": rep["intra_converged"].count(False),
               "replica_ok": replica_ok, "replica_secs": rep["secs"]},
        "ils": {"obj": ils_eval["obj"], "norm_aoi": ils_eval["norm_aoi"], "dp_obj": best_dp,
                "feasible": ils_eval["feasible"], "assigned_once": ils_eval["assigned_once"],
                "evals": sum(c["evals"] for c in chains), "secs": ils_secs, "best_chain": k_best,
                "routes": best_routes, "stops": best_stops},
        "chains": chains, "cold_chains": len(cold), "checkpoints": checkpoints, "gain": gain,
        "warm_gain": 100.0 * (res_obj - min(res_obj, *warm)) / res_obj,
        "cold_gain": 100.0 * (res_obj - min(cold)) / res_obj if cold else 0.0,
        "job_secs": time.perf_counter() - t0,
    }


def run_jobs(job_list: list[tuple], out: Path, workers: int, log_name: str) -> None:
    """运行一组单元：实例逐个运行，每个实例内部的任务在进程池中并行；逐个写记录 JSON 与耗时日志

    单进程（workers ≤ 1）时不开进程池，任务就地运行（测试里用 importlib 载入本模块时进程池无法序列化）
    """
    (out / "records").mkdir(parents=True, exist_ok=True)
    log, t0 = [], time.perf_counter()
    order = sorted(job_list, key=lambda j: -est_cost(j))
    pool = ProcessPoolExecutor(workers) if workers > 1 else None
    try:
        for j in order:
            rec = run_instance(j, pool)
            name = record_name(rec["meta"])
            (out / "records" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            log.append(f"{name}\t{rec['job_secs']:.1f}")
    finally:
        if pool is not None:
            pool.shutdown()
    log.append(f"total\t{time.perf_counter() - t0:.1f}")
    (out / f"log_{log_name}.txt").write_text("\n".join(log) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def load_records(inputs) -> list[dict]:
    recs = []
    for d in inputs:
        for p in sorted(Path(d).rglob("records/*.json")):
            recs.append(json.loads(p.read_text(encoding="utf-8")))
    return recs


def load_ref(path: Path = REF_E1) -> dict:
    """E1 中 P2 的目标（独立事件模拟）：{(布点, N, 种子, ε): 目标}；CSV 里的浮点数按 repr 写出，读回逐位不变"""
    if not path.is_file():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["layout"], int(r["n"]), int(r["seed"]), float(r["eps"])): float(r["obj"]) for r in csv.DictReader(f)}


def inst_row(rec: dict) -> dict:
    """每个实例一行：两者的平均归一化 AoI、各预算截点的改善、热/冷启动链的贡献、评估与耗时比、P2 的上限情况"""
    m, p2, il = rec["meta"], rec["p2"], rec["ils"]
    row = {"layout": m["layout"], "n": m["n"], "eps": m["eps"], "seed": m["seed"],
           "p2_norm_aoi": p2["norm_aoi"], "ils_norm_aoi": il["norm_aoi"]}
    row.update({f"gain_{k}": v for k, v in rec["gain"].items()})
    row.update({"warm_gain": rec["warm_gain"], "cold_gain": rec["cold_gain"], "best_chain": il["best_chain"],
                "cold_chains": rec["cold_chains"],
                "eval_ratio": il["evals"] / p2["evals"], "time_ratio": il["secs"] / max(p2["secs"], 1e-9),
                "p2_evals": p2["evals"], "inter_cap_hit": p2["inter_cap_hit"],
                "intra_nonconv": p2["intra_nonconverged"] / max(p2["intra_runs"], 1), "replica_ok": p2["replica_ok"]})
    return row


def checks(recs: list[dict], expected: int, ref: dict) -> tuple[list[str], int]:
    """事先写定的检查：实例齐全；方案可行、分配无误；ILS 不劣于 P2；P2 的逐步复现与冻结求解器相同；与 E1 逐位相同

    :return: (不通过的说明, 与 E1 比对的实例数)
    """
    bad = []
    if len(recs) != expected:
        bad.append(f"实例数 {len(recs)}/{expected}")
    def names(f):
        return [record_name(r["meta"]) for r in recs if f(r)]

    infeasible = names(lambda r: not (r["p2"]["feasible"] and r["p2"]["assigned_once"]
                                      and r["ils"]["feasible"] and r["ils"]["assigned_once"]))
    worse = names(lambda r: r["ils"]["obj"] > r["p2"]["obj"] * (1 + 1e-12))
    replica = names(lambda r: not r["p2"]["replica_ok"])
    keyed = [(r, (r["meta"]["layout"], r["meta"]["n"], r["meta"]["seed"], r["meta"]["eps"])) for r in recs]
    compared = [(r, k) for r, k in keyed if k in ref]
    e1_bad = [record_name(r["meta"]) for r, k in compared if r["p2"]["obj"] != ref[k]]
    for label, lst in (("不可行或分配有误", infeasible), ("ILS 劣于 P2", worse), ("P2 复现与冻结求解器不同", replica),
                       ("P2 与 E1 不同", e1_bad)):
        if lst:
            bad.append(f"{label}：{len(lst)} 个 {lst[:3]}")
    return bad, len(compared)


BANDS = {"sufficient": "局部搜索已足够：P2 不变，论文以 E8 回应“为什么不用更强的元启发式”",
         "upgrade": "需要升级：把更强的搜索升级为本文方法，冻结新版本后重跑 E1、E3、E5、E6，并重画 E7",
         "middle": "中间档：P2 不变，把 ILS 作为高耗时变体报告，并把差距写进局限"}


def decide(rows: list[dict], sizes=DECIDE_SIZES) -> dict:
    """按 29_ 中写定的规则判定（10 倍预算的改善，独立事件模拟的目标）

    平均改善 < 1% 且各格均值都 < 2%：足够；平均改善 ≥ 3% 或任一格均值 ≥ 5%：升级；其余为中间档
    :return: {"band", "pooled", "worst", "cells", "count"}
    """
    sel = [r for r in rows if r["n"] in sizes]
    if not sel:
        return {"band": None, "pooled": None, "worst": None, "cells": {}, "count": 0}
    cells = {}
    for r in sel:
        cells.setdefault((r["layout"], r["n"], r["eps"]), []).append(r["gain_final"])
    means = {k: statistics.fmean(v) for k, v in sorted(cells.items())}
    pooled, worst = statistics.fmean(r["gain_final"] for r in sel), max(means.values())
    band = ("sufficient" if pooled < 1.0 and worst < 2.0 else
            "upgrade" if pooled >= 3.0 or worst >= 5.0 else "middle")
    return {"band": band, "pooled": pooled, "worst": worst, "cells": means, "count": len(sel)}


def table_lines(rows: list[dict]) -> list[str]:
    """各格（布点 × N × ε）的汇总表"""
    head = ("  布点      N    ε     P2 归一化AoI   ILS   改善 均值/中位/最大(%)  改善≥0.1%  2×/5×/10× 均值(%)"
            "   热/冷启动(%)  评估比  耗时比  P2 跨机上限/机内未收敛")
    lines = [head]
    cells = {}
    for r in rows:
        cells.setdefault((r["layout"], r["n"], r["eps"]), []).append(r)
    for (lay, n, eps), rs in sorted(cells.items()):
        g = [r["gain_final"] for r in rs]

        def mean(key, rs=rs):
            return statistics.fmean(r[key] for r in rs)

        lines.append(
            f"  {lay:<8}  {n:>3}  {eps:<4}  {mean('p2_norm_aoi'):10.4f}  {mean('ils_norm_aoi'):6.4f}"
            f"   {statistics.fmean(g):5.2f}/{statistics.median(g):5.2f}/{max(g):5.2f}"
            f"   {100 * sum(x >= 0.1 for x in g) / len(g):6.1f}%"
            f"   {mean('gain_2'):4.2f}/{mean('gain_5'):4.2f}/{mean('gain_10'):4.2f}"
            f"   {mean('warm_gain'):4.2f}/{mean('cold_gain'):4.2f}"
            f"  {mean('eval_ratio'):6.2f}  {mean('time_ratio'):6.2f}"
            f"   {100 * mean('inter_cap_hit'):5.1f}%/{100 * mean('intra_nonconv'):5.1f}%")
    return lines


E8_LABELS = {
    "zh": {"budget": "评估预算（SCOUT 的倍数）", "gain": "SCOUT+ 相对 SCOUT 的改善（%）", "fireline": "火线布点", "sector": "扇形布点",
           "median": "中位数", "iqr": "四分位范围", "n": "N"},
    "en": {"budget": "Evaluation budget (× SCOUT)", "gain": "Gain of SCOUT+ over SCOUT (%)", "fireline": "Fire line", "sector": "Sector",
           "median": "Median", "iqr": "Interquartile range", "n": "N"},
}
LAYOUT_STYLE = {"fireline": ("o", "-"), "sector": ("s", (0, (3, 1.5)))}   # 火线实线圆点、扇形虚线方点，与其余布点图一致
LAYOUT_SHORT = {"zh": {"fireline": "火线", "sector": "扇形"}, "en": {"fireline": "Fire line", "sector": "Sector"}}


def fig_budget(rows: list[dict], lang: str):
    """X16：改善随评估预算的变化（中位数，ε 合并），一张图 6 条线 = 两种布点 × 三档 N

    按参考论文"方法 × 关键参数"的画法：N 用本文方法的蓝色由浅到深，布点用线型与标记区分。
    不画四分位带，6 条线时色带互相遮挡；每例改善的分布见 X17
    :return: 图
    """
    import scheme1_plots as sp
    from matplotlib.lines import Line2D

    lab = E8_LABELS[lang]
    xs = [0.0, *CHECKPOINTS]
    sizes = sorted({r["n"] for r in rows})
    colors = dict(zip(sizes, sp.level_colors(sp.COLORS["P2"], len(sizes))))
    fig, ax = sp.new_fig(height=2.7)
    handles = []
    for lay in LAYOUTS:
        mk, ls = LAYOUT_STYLE[lay]
        for n in sizes:
            rs = [r for r in rows if r["layout"] == lay and r["n"] == n]
            if not rs:
                continue
            med = [statistics.median(0.0 if x == 0 else r[f"gain_{x:g}"] for r in rs) for x in xs]
            c = colors[n]
            ax.plot(xs, med, color=c, linestyle=ls, marker=mk, markerfacecolor=sp.INK["surface"], markeredgecolor=c,
                    markeredgewidth=0.9, zorder=3)
            handles.append(Line2D([], [], color=c, linestyle=ls, marker=mk, markerfacecolor=sp.INK["surface"],
                                  markeredgecolor=c, markeredgewidth=0.9, label=f"{LAYOUT_SHORT[lang][lay]} N = {n}"))
    ax.set_xticks(xs, ["SCOUT" if x == 0 else f"{x:g}×" for x in xs])
    ax.set_xlabel(lab["budget"])
    ax.set_ylabel(lab["gain"])
    ax.grid(True, axis="both")
    sp.legend_top(fig, handles, ncol=3, rows_first=True)
    return fig


def fig_gain_box(rows: list[dict], lang: str):
    """X17：每例改善（10 倍预算）的分布，按布点与 N 分组"""
    import scheme1_plots as sp

    lab = E8_LABELS[lang]
    data = {}
    for lay in LAYOUTS:
        for n in sorted({r["n"] for r in rows}):
            vals = [r["gain_final"] for r in rows if r["layout"] == lay and r["n"] == n]
            if vals:
                data[f"{lab[lay]}\nN = {n}"] = vals
    fig, ax = sp.new_fig(width=sp.DOUBLE_W, height=2.4)
    sp.box(ax, data, lang, rotate=0)
    ax.set_ylabel(lab["gain"])
    ax.grid(True, axis="y")
    return fig


def summarize(inputs, out: Path, expected: int | None = None, sizes=DECIDE_SIZES) -> bool:
    """合并全部分片：检查、各格汇总表、判定、中英文图；检查不通过时返回 False

    :param expected: 期望的实例数，缺省为全部运行单元数
    :param sizes: 参与判定的 N（冒烟时取冒烟用的规模）
    """
    import scheme1_plots as sp

    recs = load_records(inputs)
    out.mkdir(parents=True, exist_ok=True)
    rows = [inst_row(r) for r in recs]
    sp.write_rows(out / "E8_rows.csv", rows)
    bad, n_ref = checks(recs, expected if expected is not None else len(jobs()), load_ref())
    dec = decide(rows, sizes)
    sizes_all = sorted({r["n"] for r in rows})
    eps_all = ", ".join(f"{e:g}" for e in sorted({r["eps"] for r in rows}))
    title = (f"## E8 更强搜索对照：{len(recs)} 个实例（5 架机，N ∈ {{{', '.join(map(str, sizes_all))}}}，"
             f"ε ∈ {{{eps_all}}}，两种布点）")
    note = (f"预算：ILS 的总评估次数为 P2 的 {BUDGET_X:g} 倍，{CHAINS} 条链平分（1 条从 P2 的解出发，其余从轮转后的初始分配出发，"
            "可行的轮转不足时以不同随机数流增开从 P2 出发的链）；改善 = 100·(P2 − ILS)/P2")
    lines = [title, note, *table_lines(rows)]
    short = sum(r["cold_chains"] < CHAINS - 1 for r in rows)
    lines.append(f"  冷启动链不足 {CHAINS - 1} 条（轮转后的分配有机不停靠也超预算）的实例：{short} 个，"
                 "缺的链以不同随机数流从 P2 的解出发补足")
    stops = Counter(c["stop"] for r in recs for c in r["chains"])
    early = "、".join(f"{k} {v} 条" for k, v in sorted(stops.items()) if k != "budget") or "无"
    lines.append(f"  预算用完前停止的链（共 {sum(stops.values())} 条）：{early}")
    if dec["band"] is not None:
        cells = "、".join(f"{lay} N={n} ε={e:g} {v:.2f}%" for (lay, n, e), v in dec["cells"].items())
        verdict = (f"判定（N ∈ {{{', '.join(map(str, sizes))}}} 的 {dec['count']} 个实例，{BUDGET_X:g} 倍预算）："
                   f"平均改善 {dec['pooled']:.2f}%，格子均值最大 {dec['worst']:.2f}% → {BANDS[dec['band']]}")
        lines += ["", verdict, f"  各格均值：{cells}"]
    lines.append("")
    lines.append(f"检查：{'全部通过' if not bad else '有不通过'}（实例齐全、方案可行、分配无误、ILS 不劣于 P2、"
                 f"P2 逐步复现与冻结求解器相同、与 E1 比对 {n_ref} 个实例逐位相同）")
    lines += [f"  {b}" for b in bad]
    files = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = out / "figures" / lang
        files += sp.save(fig_budget(rows, lang), d, "E8_X16_gain_vs_budget")
        files += sp.save(fig_gain_box(rows, lang), d, "E8_X17_gain_box")
    lines.append(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    text = "\n".join(lines) + "\n"
    (out / "summary.txt").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return not bad


SMOKE = {"sizes": (20, 30), "seeds": (97,), "eps": (0.1,)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一 E8：更强搜索对照")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("shard")
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--shards", type=int, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("summary")
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("smoke")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "shard":
        run_jobs(shard_jobs(a.shard, a.shards), a.out, a.workers, f"E8_{a.shard}")
        return 0
    if a.cmd == "summary":
        return 0 if summarize(a.inputs, a.out) else 1
    jl = jobs(sizes=SMOKE["sizes"], seeds=SMOKE["seeds"], eps_list=SMOKE["eps"])
    run_jobs(jl, a.out / "shards", a.workers, "E8_smoke")
    return 0 if summarize([a.out / "shards"], a.out / "summary", expected=len(jl), sizes=SMOKE["sizes"]) else 1


if __name__ == "__main__":
    sys.exit(main())
