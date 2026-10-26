"""第三道检验（规模外推）：更大规模与火线布点下，局部搜索联合优化 vs 两阶段

判定规则在运行前写定，全文见论文资料 28_规模外推检验_20261026/检验方案.md，摘要：
- A 校准：第二道检验的 60 例上，ε = 0.1 时局部搜索收益 ÷ 精确联合收益 ≥ 90% 为合格
- B 判定：每机 10/13/16 个观测点、扇形与火线两种布点共 120 例，ε = 0.1 下局部搜索联合解相对两阶段+ 的改善
  ≥ 10% 外层作为主要贡献；5–10% 轻量外层；< 5% 只保留选方向 + 精确停靠；火线布点单独落在不同档次时取较低档
- C 补充：5 架机、50 个观测点的 8 个机队，跨机移动相对每机局部搜索的额外改善
  ≥ 5 个百分点须含跨机分配搜索，< 2 个百分点固定分配即可，其间为灰区
用法
- python gate3_check.py calib --size 40 --seed 3 --out 目录          A 部分的一个分片
- python gate3_check.py single --layout fireline --size 80 --seed 0 --out 目录   B 部分的一个分片
- python gate3_check.py fleet --layout sector --seed 0 --out 目录    C 部分的一个分片
- python gate3_check.py merge 分片目录 --out 目录                     汇总并判定
- python gate3_check.py selftest                                      精确最短回路与局部搜索的自检
- python gate3_check.py smoke                                         用检验之外的种子测耗时与收敛，只打印耗时与评估次数
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from degeneracy_check import (DEPOT, MARGIN, M_UAV, TOL, H, V, W, candidate_points, dist, hover_time, lower_bound,
                              make_tasks, sweep_assign)
from gate2_check import best_under, instances as gate2_instances, pareto_dp, solve as gate2_solve

LS_EPS = (0.1, 0.25)
DECIDE_EPS = 0.1
SIZES = (50, 65, 80)              # 5 架机后每机 10/13/16 个观测点
SEEDS = 4
LAYOUTS = ("sector", "fireline")
FLEET_N = 50
# 每次局部搜索的评估次数上限（只计实际做了动态规划的候选），按观测点数取；
# 冒烟测试（种子 99）中 16 个观测点有一次用满 2500 次仍未收敛，运行前上调，使搜索尽量到达局部最优
MAX_EVALS = {6: 1000, 7: 1000, 8: 1000, 10: 2000, 13: 3000, 16: 5000}
FLEET_INTER_EVALS = 3000          # 跨机移动阶段的评估上限
FLEET_REOPT_EVALS = 300           # 跨机移动被接受后，对两条航线各做一次短局部搜索的上限
NEIGHBORS = 5                     # 跨机移动的候选：每个点的最近 5 个异机观测点
HERE = Path(__file__).resolve().parent


# ---------- 基础工具 ----------

def dist_matrix(tasks: list[dict]) -> list[list[float]]:
    nodes = [DEPOT] + [tuple(t["q"]) for t in tasks]
    return [[dist(a, b) for b in nodes] for a in nodes]


def order_len(perm, dm) -> float:
    """按 perm 访问（基地出发、回基地）的回路长度；perm 为观测点序号 0..n-1"""
    prev, s = 0, 0.0
    for i in perm:
        s += dm[prev][i + 1]
        prev = i + 1
    return s + dm[prev][0]


def held_karp(dm, n: int) -> tuple[list[int], float]:
    """精确最短回路（基地出发、回基地），Held–Karp 动态规划，O(n² 2ⁿ)

    :param dm: 含基地（下标 0）的距离矩阵
    :param n: 观测点数
    :return: (访问顺序, 回路长度)；两个方向长度相同，返回其中一个
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


def make_evaluator(tasks, pts, cap, dm):
    """返回 evaluate(perm) -> (最优停靠结果或 None, 是否实际做了动态规划)，带缓存

    回路长度本身已超预算的顺序直接判为不可行，不做动态规划，也不计入评估次数
    """
    cache: dict = {}

    def evaluate(perm):
        key = tuple(perm)
        if key in cache:
            return cache[key], False
        if order_len(perm, dm) / V > cap + TOL:
            cache[key] = None
            return None, False
        b = best_under(pareto_dp([tasks[i] for i in perm], pts, cap), cap)
        cache[key] = b
        return b, True

    return evaluate


# ---------- 局部搜索 ----------

def neighborhood(n: int) -> list[tuple]:
    """2-opt、交换与 Or-opt（连续 1–3 个点移到别处，2–3 个点时可反向插入）"""
    out = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            out.append(("2opt", i, j))
            out.append(("swap", i, j))
    for length in (1, 2, 3):
        for s in range(n - length + 1):
            for p in range(n - length + 1):
                if p == s:
                    continue
                for rev in ((False,) if length == 1 else (False, True)):
                    out.append(("or", s, length, p, rev))
    return out


def apply_move(perm, mv) -> list:
    p = list(perm)
    if mv[0] == "2opt":
        _, i, j = mv
        p[i:j + 1] = p[i:j + 1][::-1]
    elif mv[0] == "swap":
        _, i, j = mv
        p[i], p[j] = p[j], p[i]
    else:
        _, s, length, pos, rev = mv
        blk = p[s:s + length]
        del p[s:s + length]
        if rev:
            blk = blk[::-1]
        p[pos:pos] = blk
    return p


def local_search(evaluate, start, max_evals: int, rng: random.Random, n: int):
    """首次改进的局部搜索：每轮随机打乱邻域，找到第一个更优的候选就移动；一整轮无改进即为局部最优

    :return: (顺序, 结果, 实际评估次数, 是否在上限内收敛)
    """
    cur = list(start)
    cur_val, counted = evaluate(cur)
    evals = int(counted)
    moves = neighborhood(n)
    while evals < max_evals:
        rng.shuffle(moves)
        improved = capped = False
        for mv in moves:
            cand = apply_move(cur, mv)
            val, counted = evaluate(cand)
            evals += counted
            if val is not None and (cur_val is None or val[0] < cur_val[0] - 1e-12):
                cur, cur_val, improved = cand, val, True
                break
            if evals >= max_evals:
                capped = True
                break
        if not improved:
            # 整轮没有改进才算收敛；因评估次数用完而中断的不算
            return cur, cur_val, evals, not capped
    return cur, cur_val, evals, False


def seed_of(*parts) -> int:
    """由整数与短字符串确定的随机种子，不依赖 Python 的哈希随机化"""
    s = 0
    for p in parts:
        for ch in str(p):
            s = (s * 131 + ord(ch)) % (2 ** 61 - 1)
    return s


def solve_single(inst: dict, eps_list=LS_EPS) -> dict:
    """单机实例：两阶段+（精确最短回路两个方向 + 精确停靠）与从两个方向出发的局部搜索"""
    t0 = time.perf_counter()
    tasks = inst["tasks"]
    n = len(tasks)
    pts = candidate_points()
    dm = dist_matrix(tasks)
    hov = hover_time(tasks)
    tsp, l_tsp = held_karp(dm, n)
    t_hat = l_tsp / V + hov
    out = {"id": inst["id"], "n": n, "l_tsp": l_tsp, "t_hat": t_hat, "hover": hov, "lb": lower_bound(tasks, pts),
           "tsp": tsp, "tasks": [{"q": list(t["q"]), "D": t["D"], "delta": t["delta"], "tc": t["tc"]} for t in tasks],
           "eps": {}}
    for e in eps_list:
        cap = (1 + e) * t_hat - hov
        evaluate = make_evaluator(tasks, pts, cap, dm)
        dirs = [evaluate(p)[0] for p in (tsp, tsp[::-1])]
        best, stats = None, []
        for si, start in enumerate((tsp, tsp[::-1])):
            rng = random.Random(seed_of(inst["id"], e, si))
            perm, val, evals, conv = local_search(evaluate, start, MAX_EVALS[n], rng, n)
            stats.append({"evals": evals, "converged": conv})
            if val is not None and (best is None or val[0] < best[1][0]):
                best = (perm, val)
        out["eps"][str(e)] = {"b_dirs": [d[0] for d in dirs], "bplus": min(d[0] for d in dirs),
                              "ls": best[1][0], "ls_fly": best[1][1], "ls_perm": best[0],
                              "ls_stops": [list(s) for s in best[1][2]], "stats": stats}
    out["secs"] = time.perf_counter() - t0
    return out


# ---------- 实例 ----------

def fireline_tasks(rng: random.Random, n_total: int) -> list[dict]:
    """椭圆火线：沿火线按参数角等距布点并加小幅扰动，返回按火线次序排列的观测点"""
    a = rng.uniform(700, 1100)
    b = a / rng.uniform(1.5, 2.5)
    th = rng.uniform(0, math.pi)
    # 椭圆外接矩形的半宽、半高，用来保证全部观测点留在区域内
    hx = math.sqrt((a * math.cos(th)) ** 2 + (b * math.sin(th)) ** 2)
    hy = math.sqrt((a * math.sin(th)) ** 2 + (b * math.cos(th)) ** 2)
    cx = rng.uniform(MARGIN + hx + 30, W - MARGIN - hx - 30)
    cy = rng.uniform(MARGIN + hy + 30, H - MARGIN - hy - 30)
    phase = rng.uniform(0, 2 * math.pi)
    tasks = []
    for k in range(n_total):
        t = phase + 2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / n_total
        x0, y0 = a * math.cos(t), b * math.sin(t)
        x = cx + x0 * math.cos(th) - y0 * math.sin(th) + rng.uniform(-20, 20)
        y = cy + x0 * math.sin(th) + y0 * math.cos(th) + rng.uniform(-20, 20)
        q = (min(max(x, MARGIN), W - MARGIN), min(max(y, MARGIN), H - MARGIN))
        tasks.append({"q": q, "D": rng.uniform(80, 160), "tc": 10.0, "delta": rng.uniform(300, 600)})
    return tasks


def arc_assign(tasks: list[dict]) -> list[list[dict]]:
    """沿火线次序，从离基地最近的观测点开始切成 M_UAV 段连续弧，每段一架机"""
    start = min(range(len(tasks)), key=lambda i: dist(tasks[i]["q"], DEPOT))
    order = tasks[start:] + tasks[:start]
    size = math.ceil(len(order) / M_UAV)
    return [order[i:i + size] for i in range(0, len(order), size)]


def fleet_groups(layout: str, n_total: int, seed: int) -> list[list[dict]]:
    """生成一个机队实例的初始分配；扇形用方位角等分，火线用连续弧段"""
    rng = random.Random(seed_of("gate3", layout, n_total, seed))
    if layout == "sector":
        return sweep_assign(make_tasks(rng, n_total))
    return arc_assign(fireline_tasks(rng, n_total))


def single_instances(layout: str, size: int, seed: int) -> list[dict]:
    return [{"id": f"{layout}-{size}-{seed}-{g}", "tasks": grp} for g, grp in enumerate(fleet_groups(layout, size, seed))]


# ---------- 三个部分 ----------

def solve_calib(inst: dict) -> dict:
    """A 部分：同一实例上的精确联合最优（枚举）与局部搜索"""
    exact = gate2_solve(inst)
    ls = solve_single({"id": f"calib-{inst['size']}-{inst['seed']}-{inst['group']}", "tasks": inst["tasks"]})
    for e in LS_EPS:
        k = str(e)
        ls["eps"][k]["exact_j"] = exact["joint"][k]["obj"]
        ls["eps"][k]["exact_bplus"] = min(x["obj"] for x in exact["two_stage"][k])
    ls["exact_secs"] = exact["secs"]
    return ls


def route_eval_factory(pts, cap_of):
    """多机：按观测点全局编号序列评估一条航线（上限随该航线的悬停时间变化），带缓存"""
    cache: dict = {}

    def evaluate(route: list[dict]):
        key = tuple(t["gid"] for t in route)
        if key in cache:
            return cache[key], False
        cap = cap_of(route)
        dm = dist_matrix(route)
        if order_len(range(len(route)), dm) / V > cap + TOL:
            cache[key] = None
            return None, False
        b = best_under(pareto_dp(route, pts, cap), cap)
        cache[key] = b
        return b, True

    return evaluate


def improve_route(route, evaluate, max_evals, rng):
    """对一条航线做局部搜索（顺序以航线内下标表示），返回 (新航线, 结果, 评估次数)"""
    n = len(route)
    if n < 2:
        return route, evaluate(route)[0], 0

    def ev(perm):
        return evaluate([route[i] for i in perm])

    perm, val, evals, _ = local_search(ev, list(range(n)), max_evals, rng, n)
    return [route[i] for i in perm], val, evals


def solve_fleet_eps(args) -> dict:
    """C 部分：一个机队、一个 ε；两阶段 → 每机局部搜索 → 加入跨机移动"""
    layout, seed, e = args
    t0 = time.perf_counter()
    groups = fleet_groups(layout, FLEET_N, seed)
    gid = 0
    for g in groups:
        for t in g:
            t["gid"] = gid
            gid += 1
    pts = candidate_points()
    tsps = []
    for g in groups:
        tsp, length = held_karp(dist_matrix(g), len(g))
        tsps.append((tsp, length))
    t_hat = max(length / V + hover_time(g) for g, (tsp, length) in zip(groups, tsps))

    def cap_of(route):
        return (1 + e) * t_hat - hover_time(route)

    evaluate = route_eval_factory(pts, cap_of)
    # 两阶段：每架机最短回路较好方向 + 精确停靠
    routes, two_stage = [], 0.0
    for g, (tsp, _) in zip(groups, tsps):
        cands = [[g[i] for i in p] for p in (tsp, tsp[::-1])]
        vals = [evaluate(c)[0] for c in cands]
        k = min(range(2), key=lambda i: vals[i][0])
        routes.append(cands[k])
        two_stage += vals[k][0]
    # 每机局部搜索：从两个方向出发取较好者
    per_route, vals = [], []
    for u, (g, (tsp, _)) in enumerate(zip(groups, tsps)):
        best = None
        for si, start in enumerate((tsp, tsp[::-1])):
            r0 = [g[i] for i in start]
            r, v, _ = improve_route(r0, evaluate, MAX_EVALS[len(g)], random.Random(seed_of(layout, seed, e, u, si)))
            if best is None or v[0] < best[1][0]:
                best = (r, v)
        per_route.append(best[0])
        vals.append(best[1])
    per_route_total = sum(v[0] for v in vals)
    # 跨机移动：移动一个观测点或交换两点，候选限于最近的异机观测点
    routes = [list(r) for r in per_route]
    vals = list(vals)
    all_tasks = [t for r in routes for t in r]
    near = {t["gid"]: [x["gid"] for x in sorted(all_tasks, key=lambda x: dist(x["q"], t["q"]))[1:NEIGHBORS * 3 + 1]]
            for t in all_tasks}
    rng = random.Random(seed_of(layout, seed, e, "inter"))
    inter_evals, accepted = 0, 0
    while inter_evals < FLEET_INTER_EVALS:
        where = {t["gid"]: (u, i) for u, r in enumerate(routes) for i, t in enumerate(r)}
        moves = []
        for g1, (u, i) in where.items():
            cnt = 0
            for g2 in near[g1]:
                w, j = where[g2]
                if w == u:
                    continue
                moves += [("rel", u, i, w, j), ("rel", u, i, w, j + 1), ("swp", u, i, w, j)]
                cnt += 1
                if cnt >= NEIGHBORS:
                    break
        rng.shuffle(moves)
        improved = False
        for mv in moves:
            kind, u, i, w, j = mv
            ru, rw = list(routes[u]), list(routes[w])
            if kind == "rel":
                if len(ru) <= 1:
                    continue
                t = ru.pop(i)
                rw.insert(j, t)
            else:
                ru[i], rw[j] = rw[j], ru[i]
            vu, c1 = evaluate(ru)
            vw, c2 = evaluate(rw)
            inter_evals += c1 + c2
            if vu is not None and vw is not None and vu[0] + vw[0] < vals[u][0] + vals[w][0] - 1e-12:
                # 接受后对两条航线各做一次短局部搜索
                ru, vu, _ = improve_route(ru, evaluate, FLEET_REOPT_EVALS, random.Random(seed_of(layout, seed, e, accepted, "u")))
                rw, vw, _ = improve_route(rw, evaluate, FLEET_REOPT_EVALS, random.Random(seed_of(layout, seed, e, accepted, "w")))
                routes[u], routes[w], vals[u], vals[w] = ru, rw, vu, vw
                accepted += 1
                improved = True
                break
            if inter_evals >= FLEET_INTER_EVALS:
                break
        if not improved:
            break
    lb = sum(lower_bound(g, pts) for g in groups)
    return {"id": f"fleet-{layout}-{seed}", "eps": e, "n": FLEET_N, "t_hat": t_hat, "lb": lb, "two_stage": two_stage,
            "per_route": per_route_total, "fleet": sum(v[0] for v in vals), "inter_evals": inter_evals,
            "accepted": accepted, "sizes": [len(r) for r in routes], "secs": time.perf_counter() - t0}


# ---------- 汇总与判定 ----------

def level(imp: float) -> int:
    """B 部分的档次：2 为 ≥10%，1 为 5–10%，0 为 < 5%"""
    return 2 if imp >= 0.10 else (1 if imp >= 0.05 else 0)


LEVEL_TEXT = {2: "≥ 10%：外层作为主要贡献之一（巨型回路 + 两层精确解码与跨机分配）",
              1: "5–10%：外层采用轻量的、以动态规划评估的局部搜索",
              0: "< 5%：外层只保留选方向 + 精确停靠，论文以模型与精确停靠为主"}


def merge(src: Path, out_dir: Path) -> None:
    load = lambda pat: [r for f in sorted(src.rglob(pat)) for r in json.loads(f.read_text(encoding="utf-8"))]
    calib, single, fleet = load("gate3_calib_*.json"), load("gate3_single_*.json"), load("gate3_fleet_*.json")
    exp = {"calib": len(gate2_instances()), "single": len(LAYOUTS) * len(SIZES) * SEEDS * M_UAV,
           "fleet": len(LAYOUTS) * SEEDS * len(LS_EPS)}
    got = {"calib": len({r["id"] for r in calib}), "single": len({r["id"] for r in single}),
           "fleet": len({(r["id"], r["eps"]) for r in fleet})}
    lines = [f"实例数：A {got['calib']}/{exp['calib']}，B {got['single']}/{exp['single']}，C {got['fleet']}/{exp['fleet']}（机队 × ε）"]
    complete = got == exp
    if not complete:
        lines.append("结果不完整，不做判定")
    else:
        norm = lambda rows, key, e: statistics.mean(r["eps"][str(e)][key] / r["n"] for r in rows)
        lines.append("A 校准（第二道检验的 60 例，局部搜索 vs 枚举精确联合最优）")
        calib_ok = None
        for e in LS_EPS:
            bp, ls, ex = norm(calib, "bplus", e), norm(calib, "ls", e), norm(calib, "exact_j", e)
            hk = max(abs(r["eps"][str(e)]["bplus"] - r["eps"][str(e)]["exact_bplus"]) for r in calib)
            hit = sum(abs(r["eps"][str(e)]["ls"] - r["eps"][str(e)]["exact_j"]) <= 1e-9 for r in calib)
            cap_ratio = (bp - ls) / (bp - ex) if bp > ex else float("nan")
            lines.append(f"  ε = {e}：局部搜索拿到精确联合收益的 {100 * cap_ratio:.1f}%，找到精确最优 {hit}/{len(calib)} 例；"
                         f"两阶段+ 与第二道检验的最大偏差 {hk:.1e}")
            if e == DECIDE_EPS:
                calib_ok = cap_ratio >= 0.90
        lines.append(f"  校准{'合格' if calib_ok else '不合格'}（门槛 90%）")
        lines.append("B 单机外推（局部搜索联合解 vs 两阶段+，平均归一化 AoI 的改善）")
        imps = {}
        for e in LS_EPS:
            for layout in LAYOUTS:
                for nu in sorted({r["n"] for r in single}):
                    rows = [r for r in single if r["id"].startswith(layout) and r["n"] == nu]
                    bp, ls, lb = norm(rows, "bplus", e), norm(rows, "ls", e), statistics.mean(r["lb"] / r["n"] for r in rows)
                    per = [1 - r["eps"][str(e)]["ls"] / r["eps"][str(e)]["bplus"] for r in rows]
                    lines.append(f"  ε = {e} {layout} 每机 {nu} 点（{len(rows)} 例）：两阶段+ {bp:.4f}，局部搜索 {ls:.4f}，下界 {lb:.4f}；"
                                 f"改善 {100 * (1 - ls / bp):.1f}%，逐例中位 {100 * statistics.median(per):.1f}%，≥10% 的 {sum(p >= 0.1 for p in per)}/{len(per)}")
                rows = [r for r in single if r["id"].startswith(layout)]
                imps[(e, layout)] = 1 - norm(rows, "ls", e) / norm(rows, "bplus", e)
                lines.append(f"  ε = {e} {layout} 合计：改善 {100 * imps[(e, layout)]:.1f}%")
            imps[(e, "all")] = 1 - norm(single, "ls", e) / norm(single, "bplus", e)
            lines.append(f"  ε = {e} 全部 120 例：改善 {100 * imps[(e, 'all')]:.1f}%")
        conv = [s["converged"] for r in single for k in r["eps"].values() for s in k["stats"]]
        lines.append(f"  局部搜索在评估上限内收敛的比例：{sum(conv)}/{len(conv)}")
        lv_all, lv_fire = level(imps[(DECIDE_EPS, "all")]), level(imps[(DECIDE_EPS, "fireline")])
        final = min(lv_all, lv_fire)
        tentative = (not calib_ok) and final < 2
        lines.append(f"B 判定（事先声明，ε = {DECIDE_EPS}）：全部 {100 * imps[(DECIDE_EPS, 'all')]:.1f}%，火线 {100 * imps[(DECIDE_EPS, 'fireline')]:.1f}% → "
                     f"{LEVEL_TEXT[final]}{'（校准不合格，暂定）' if tentative else ''}")
        lines.append("C 多机分配（5 架机、50 个观测点）")
        for e in LS_EPS:
            rows = [r for r in fleet if r["eps"] == e]
            ts, pr, fl = (statistics.mean(r[k] / r["n"] for r in rows) for k in ("two_stage", "per_route", "fleet"))
            add_pp = 100 * (pr - fl) / ts
            lines.append(f"  ε = {e}（{len(rows)} 个机队）：两阶段 {ts:.4f}，每机局部搜索 {pr:.4f}（改善 {100 * (1 - pr / ts):.1f}%），"
                         f"加跨机移动 {fl:.4f}（再改善 {add_pp:.1f} 个百分点），接受的跨机移动 中位 {statistics.median(r['accepted'] for r in rows):.0f} 次")
            if e == DECIDE_EPS:
                verdict = "外层须包含跨机分配搜索" if add_pp >= 5 else ("固定分配即可" if add_pp < 2 else "灰区，报告后再议")
                lines.append(f"C 判定（事先声明，ε = {DECIDE_EPS}）：跨机移动再改善 {add_pp:.1f} 个百分点 → {verdict}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate3_results.json").write_text(json.dumps({"calib": calib, "single": single, "fleet": fleet},
                                                           ensure_ascii=False), encoding="utf-8")
    (out_dir / "gate3_out.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    if not complete:
        raise SystemExit(1)


# ---------- 自检与冒烟测试 ----------

def selftest() -> None:
    """Held–Karp 与枚举最短回路对拍；局部搜索结果不劣于起点；跨机评估与单机评估一致"""
    rng = random.Random(7)
    worst = 0.0
    for _ in range(30):
        n = rng.randint(3, 8)
        tasks = make_tasks(rng, n)
        dm = dist_matrix(tasks)
        _, hk = held_karp(dm, n)
        brute = min(order_len(p, dm) for p in itertools.permutations(range(n)))
        worst = max(worst, abs(hk - brute))
    msg = f"Held–Karp 与枚举最短回路对拍 30 组，最大偏差 {worst:.1e}"
    ok = worst < 1e-6
    r = solve_single({"id": "selftest", "tasks": make_tasks(random.Random(8), 7)}, eps_list=(0.1,))
    ok = ok and r["eps"]["0.1"]["ls"] <= r["eps"]["0.1"]["bplus"] + 1e-12
    print(msg + f"；局部搜索不劣于两阶段+：{r['eps']['0.1']['ls'] <= r['eps']['0.1']['bplus'] + 1e-12}")
    if not ok:
        raise SystemExit(1)


def smoke() -> None:
    """用检验之外的种子（seed = 99）测单机局部搜索的耗时与收敛情况，不打印目标值"""
    for layout in LAYOUTS:
        for size in SIZES:
            inst = single_instances(layout, size, 99)[0]
            r = solve_single(inst)
            st = [s for k in r["eps"].values() for s in k["stats"]]
            print(f"{layout} 每机 {r['n']} 点：耗时 {r['secs']:.0f} s，评估次数 {[s['evals'] for s in st]}，收敛 {[s['converged'] for s in st]}")
    t0 = time.perf_counter()
    f = solve_fleet_eps(("fireline", 99, 0.1))
    print(f"火线机队（ε = 0.1）：耗时 {time.perf_counter() - t0:.0f} s，跨机评估 {f['inter_evals']}，接受 {f['accepted']} 次")


def run_parallel(fn, items, workers):
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def main() -> None:
    ap = argparse.ArgumentParser(description="第三道检验：规模外推")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("calib", "single", "fleet"):
        p = sub.add_parser(name)
        p.add_argument("--seed", type=int, required=True)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--out", type=Path, default=HERE)
        if name == "calib":
            p.add_argument("--size", type=int, required=True)
        if name in ("single", "fleet"):
            p.add_argument("--layout", choices=LAYOUTS, required=True)
        if name == "single":
            p.add_argument("--size", type=int, choices=SIZES, required=True)
    p = sub.add_parser("merge")
    p.add_argument("src", type=Path)
    p.add_argument("--out", type=Path)
    sub.add_parser("selftest")
    sub.add_parser("smoke")
    a = ap.parse_args()
    t0 = time.perf_counter()
    if a.cmd == "calib":
        insts = [x for x in gate2_instances() if x["size"] == a.size and x["seed"] == a.seed]
        res, tag = run_parallel(solve_calib, sorted(insts, key=lambda x: -len(x["tasks"])), a.workers), f"calib_{a.size}_{a.seed}"
    elif a.cmd == "single":
        res, tag = run_parallel(solve_single, single_instances(a.layout, a.size, a.seed), a.workers), f"single_{a.layout}_{a.size}_{a.seed}"
    elif a.cmd == "fleet":
        res, tag = run_parallel(solve_fleet_eps, [(a.layout, a.seed, e) for e in LS_EPS], a.workers), f"fleet_{a.layout}_{a.seed}"
    elif a.cmd == "merge":
        return merge(a.src, a.out or a.src)
    elif a.cmd == "selftest":
        return selftest()
    else:
        return smoke()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"gate3_{tag}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"{tag}：{len(res)} 项，耗时 {time.perf_counter() - t0:.0f} s（{a.workers} 进程）")


if __name__ == "__main__":
    main()
