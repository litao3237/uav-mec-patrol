"""方案一 E5：最优性与规模（实验规划 29_ 第 2 节 E5；运行前写定的做法见该节"实现细节"）

- X 与精确解的差距：单机、每机 6/7/8 个观测点（N = 30/35/40、5 架机后的每个组），火线与扇形布点，种子 100–119，
  ε ∈ {0.1, 0.25}；精确联合最优 = 枚举全部访问顺序 × 精确停靠（每个顺序做一次帕累托动态规划，取两档预算下的最优）；
  与本文方法（单机时 P1 = P2：最短回路两个方向出发的局部搜索）、两阶段（B2）比较
- T 求解时间随规模：N ∈ {30, 50, 80, 120} × m ∈ {3, 5, 7}，两种布点，ε = 0.1，加速开、关各一次（同一进程先后运行，结果须相同）
- F1 停靠动态规划与穷举的对拍：小实例（每站圆心 + 2 个环上点）上精确停靠与枚举全部停靠方案的最优值、耗时
- lbgap 与逐份下界的差距：直接用 E1 的汇总表（本地运行，不另跑实验）

用法：
  python experiments/scheme1_e5.py shard --exp X --shard 0 --shards 12 --workers 4 --out 目录
  python experiments/scheme1_e5.py summary --inputs 目录 --out 目录
  python experiments/scheme1_e5.py lbgap --e1 E1_rows.csv --out 目录
  python experiments/scheme1_e5.py smoke --out 目录
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from uav_mec.scheme1 import (Instance, RouteEvaluator, SearchConfig, Task, exact_stops, load_scheme1_params,  # noqa: E402
                             make_instance, pareto_front, route_local_search, seed_of, shortest_tour, simulate,
                             solve_fleet)
from uav_mec.scheme1.stops import TOL  # noqa: E402

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
SEEDS = tuple(range(100, 120))
LAYOUTS = ("fireline", "sector")
X_SIZES = (30, 35, 40)              # 5 架机分配后每机 6/7/8 个观测点
X_EPS = (0.1, 0.25)
T_SIZES = (30, 50, 80, 120)
T_UAVS = (3, 5, 7)
T_SEEDS = (100, 101, 102)
T_EPS = 0.1
# 每机观测点数超过此值时只跑加速版本：本地实测每机 40 点时加速后约 21 分钟、精确动态规划约 1500 次，
# 不加速要对 5–7 万个候选逐个做精确动态规划，预计数小时以上，可能超过单个作业 6 小时的上限
T_PLAIN_MAX = 24
F1_SIZES = (4, 5, 6)
F1_PER_SIZE = 30


def jobs(exp: str, seeds=None) -> list[tuple]:
    """运行单元：X 为 (实验, 布点, N, 种子)，每个单元含 5 个单机组；T 为 (实验, 布点, N, m, 种子)；F1 为 (实验, 观测点数, 编号)"""
    if exp == "X":
        return [("X", lay, n, s) for lay in LAYOUTS for n in X_SIZES for s in (seeds or SEEDS)]
    if exp == "T":
        return [("T", lay, n, m, s) for lay in LAYOUTS for n in T_SIZES for m in T_UAVS for s in (seeds or T_SEEDS)]
    if exp == "F1":
        return [("F1", n, i) for n in F1_SIZES for i in range(F1_PER_SIZE)]
    raise ValueError(exp)


def est_cost(job: tuple) -> float:
    """相对耗时估计，只用于把单元均匀分到各分片：穷举约随 n! 增长；机队求解约随每机观测点数的 3 次方增长"""
    if job[0] == "X":
        return 5 * math.factorial(job[2] // 5) / 720
    if job[0] == "T":
        _, layout, n, m, _ = job
        k = math.ceil(n / m)
        return (k / 10) ** 3 * (5.0 if k <= T_PLAIN_MAX else 1.0) * (2.0 if layout == "sector" else 1.0)
    return 1.0


def shard_jobs(exp: str, shard: int, shards: int) -> list[tuple]:
    """按估计耗时从大到小蛇形分配，各分片负载接近"""
    order = sorted(jobs(exp), key=lambda j: (-est_cost(j), j))
    return [j for i, j in enumerate(order) if (i % (2 * shards) if i % (2 * shards) < shards
                                               else 2 * shards - 1 - i % (2 * shards)) == shard]


# ---------------------------------------------------------------------------
# 运行单元
# ---------------------------------------------------------------------------

def single_group(inst: Instance, g: list[int], layout: str, n_total: int, seed: int, group: int) -> dict:
    """一个单机组：两档预算下的精确联合最优（枚举）、本文方法（局部搜索）与两阶段

    预算取该机不停靠最短回路的任务时长 T̂（第三道检验单机部分的做法），飞行时间上限 = (1+ε)·T̂ − 悬停时间；
    本文方法与回归检查中的单机流程相同：最短回路两个方向各出发一次，取较好者
    """
    v = inst.params.speed_mps
    tour, l_tsp = shortest_tour(inst, g)
    hov = inst.hover_time(g)
    caps = {e: (1 + e) * (l_tsp / v + hov) - hov for e in X_EPS}
    out = {"group": group, "n": len(g), "l_tsp_m": l_tsp, "hover_s": hov,
           "lb_norm": sum((min(min(inst.tp[x]), inst.dt[x]) + inst.up[x] + inst.params.tau_s) / inst.delta[x]
                          for x in g) / len(g), "eps": {}}
    # 精确联合最优：每个顺序做一次帕累托动态规划（取最大的上限），两档预算各取可行标签中的最优
    t0 = time.perf_counter()
    cmax = max(caps.values())
    best = {e: None for e in caps}
    n_dp = 0
    for perm in itertools.permutations(g):
        route = list(perm)
        if inst.route_length_m(route) / v > cmax + TOL:
            continue
        front = pareto_front(inst, route, cmax)
        n_dp += 1
        for e, c in caps.items():
            feas = [lab for lab in front if lab[1] <= c + TOL]
            if feas:
                b = min(feas, key=lambda x: (x[0], x[1]))
                if best[e] is None or b[0] < best[e][0] - 1e-12:
                    best[e] = (b[0], b[1], route, b[2])
    t_exact = time.perf_counter() - t0
    out["n_dp"], out["secs_exact"] = n_dp, t_exact
    for e, cap in caps.items():
        ev = RouteEvaluator(inst, lambda r, c=cap: c)
        dirs = []
        for p in (tour, tour[::-1]):
            if ev.length_ok(p):
                ev.touch(p)
            dirs.append(ev.exact(p)[0])
        t1 = time.perf_counter()
        ls, evals = None, []
        for si, start in enumerate((tour, tour[::-1])):
            r, val, used, _ = route_local_search(ev, start, SearchConfig().evals(len(g)),
                                                 random.Random(seed_of(f"{layout}-{n_total}-{seed}-{group}", e, si)))
            evals.append(used)
            if ls is None or val[0] < ls[1][0]:
                ls = (r, val)
        ex = best[e]
        out["eps"][str(e)] = {"exact": ex[0], "exact_perm": ex[2], "exact_stops": [list(s) for s in ex[3]],
                              "p1": ls[1][0], "p1_perm": list(ls[0]), "b2": min(dirs), "evals": evals,
                              "secs_ls": time.perf_counter() - t1, "cap_s": cap}
    return out


def run_x(job: tuple) -> dict:
    """X 单元：一个机队实例的 5 个单机组"""
    _, layout, n_total, seed = job
    inst, groups = make_instance(layout, n_total, 5, seed, load_scheme1_params(str(CONFIG)))
    t0 = time.perf_counter()
    rec = {"meta": {"exp": "X", "layout": layout, "n_total": n_total, "seed": seed},
           "groups": [single_group(inst, g, layout, n_total, seed, i) for i, g in enumerate(groups)]}
    rec["job_secs"] = time.perf_counter() - t0
    return rec


def run_t(job: tuple) -> dict:
    """T 单元：同一实例上先后运行加速开、关的本文方法，记录耗时与精确动态规划次数（每机超过 T_PLAIN_MAX 点时只跑加速）"""
    _, layout, n, m, seed = job
    inst, groups = make_instance(layout, n, m, seed, load_scheme1_params(str(CONFIG)))
    per_uav = max(len(g) for g in groups)
    rec = {"meta": {"exp": "T", "layout": layout, "n": n, "m": m, "seed": seed, "eps": T_EPS,
                    "per_uav_max": per_uav}, "runs": {}}
    runs = (("P2A", True), ("P2N", False)) if per_uav <= T_PLAIN_MAX else (("P2A", True),)
    for name, acc in runs:
        t0 = time.perf_counter()
        res = solve_fleet(inst, groups, T_EPS, SearchConfig(accelerate=acc), tag=(layout, n, m, seed, T_EPS))
        rec["runs"][name] = {"secs": time.perf_counter() - t0, "obj": res.objective, "routes": res.routes,
                             "exact": res.stats["exact"], "pruned": res.stats["pruned"],
                             "intra_evals": res.stats["intra_evals"], "inter_evals": res.stats["inter_evals"]}
    return rec


def _f1_instance(n: int, idx: int) -> tuple[Instance, list[int], float]:
    """F1 的小实例：每站圆心加 2 个 0.85R 环上点（候选上传点少，枚举可行），观测点在区域内均匀随机，
    飞行时间上限在不停靠回路的 1.1–1.5 倍之间随机"""
    sp = load_scheme1_params(str(CONFIG)).with_overrides(ring_fractions=(0.85,), points_per_ring=2)
    rng = random.Random(seed_of("E5-F1", n, idx))
    tasks = [Task(i, rng.uniform(sp.margin_m, sp.width_m - sp.margin_m), rng.uniform(sp.margin_m, sp.height_m - sp.margin_m),
                  rng.uniform(*sp.data_mbit), rng.uniform(*sp.freshness_s), sp.collect_s) for i in range(n)]
    inst = Instance(sp, tasks)
    route = list(range(n))
    cap = rng.uniform(1.1, 1.5) * inst.route_length_m(route) / sp.speed_mps
    return inst, route, cap


def run_f1(job: tuple) -> dict:
    """F1 单元：精确停靠与枚举全部停靠方案（途中停靠位置 × 上传点 × 最后一站上传点或基地）"""
    _, n, idx = job
    inst, route, cap = _f1_instance(n, idx)
    t0 = time.perf_counter()
    dp = exact_stops(inst, route, cap)
    t_dp = time.perf_counter() - t0
    n_pts, best, count = len(inst.points), float("inf"), 0
    t0 = time.perf_counter()
    for r in range(n):
        for pos in itertools.combinations(range(1, n), r):
            for pts in itertools.product(range(n_pts), repeat=r):
                for fin in [-1, *range(n_pts)]:
                    count += 1
                    sim = simulate(inst, route, [*zip(pos, pts), (n, fin)])
                    if sim.fly_s <= cap + TOL:
                        best = min(best, sim.objective)
    t_bf = time.perf_counter() - t0
    return {"meta": {"exp": "F1", "n": n, "idx": idx}, "dp": dp[0], "brute": best, "plans": count,
            "secs_dp": t_dp, "secs_brute": t_bf, "points": n_pts}


RUNNERS = {"X": run_x, "T": run_t, "F1": run_f1}


def record_name(meta: dict) -> str:
    if meta["exp"] == "X":
        return "X_{layout}_n{n_total}_s{seed}".format(**meta)
    if meta["exp"] == "T":
        return "T_{layout}_n{n}_m{m}_s{seed}".format(**meta)
    return "F1_n{n}_i{idx}".format(**meta)


def _run(job: tuple) -> dict:
    return RUNNERS[job[0]](job)


def run_jobs(job_list: list[tuple], out: Path, workers: int, log_name: str) -> None:
    """并行运行一组单元，逐个写记录 JSON 与耗时日志"""
    (out / "records").mkdir(parents=True, exist_ok=True)
    log, t0 = [], time.perf_counter()
    order = sorted(job_list, key=lambda j: -est_cost(j))

    def write(rec):
        name = record_name(rec["meta"])
        (out / "records" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        log.append(f"{name}\t{rec.get('job_secs', 0.0):.1f}")

    if workers <= 1:      # 单进程时不开进程池（便于调试，也不要求模块可被子进程导入）
        for job in order:
            write(_run(job))
    else:
        with ProcessPoolExecutor(workers) as ex:
            for rec in ex.map(_run, order):
                write(rec)
    log.append(f"total\t{time.perf_counter() - t0:.1f}")
    (out / f"log_{log_name}.txt").write_text("\n".join(log) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def load_records(inputs) -> dict:
    """读取各分片的记录：{实验: [记录]}"""
    recs: dict = {"X": [], "T": [], "F1": []}
    for d in inputs:
        for p in sorted(Path(d).rglob("records/*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            recs[rec["meta"]["exp"]].append(rec)
    return recs


def x_rows(recs: list[dict]) -> list[dict]:
    """X：每个单机组、每档 ε 一行，含精确最优、本文方法、两阶段及差距（%）"""
    rows = []
    for r in recs:
        m = r["meta"]
        for g in r["groups"]:
            for e, v in g["eps"].items():
                ex = v["exact"]
                rows.append({"layout": m["layout"], "n_total": m["n_total"], "seed": m["seed"], "group": g["group"],
                             "n": g["n"], "eps": float(e), "exact": ex, "p2": v["p1"], "b2": v["b2"],
                             "gap_p2": 100 * (v["p1"] - ex) / ex, "gap_b2": 100 * (v["b2"] - ex) / ex,
                             "optimal": v["p1"] <= ex * (1 + 1e-9), "lb_norm": g["lb_norm"],
                             "secs_exact": g["secs_exact"], "secs_ls": v["secs_ls"], "n_dp": g["n_dp"]})
    return rows


def _c(x: float, d: int = 2) -> float:
    """显示用的舍入：加 0.0 把 10⁻¹⁶ 量级的浮点差舍入后得到的 −0.0 变成 0.0"""
    return round(x, d) + 0.0


def summarize_x(rows: list[dict], expected: int) -> tuple[list[str], list[str]]:
    """X 的摘要与检查：本文方法与两阶段都不能优于精确最优"""
    from scheme1_plots import result_fingerprint

    problems = []
    bad = [r for r in rows if r["p2"] < r["exact"] * (1 - 1e-9) or r["b2"] < r["exact"] * (1 - 1e-9)]
    if bad:
        problems.append(f"X：有方法优于穷举的精确最优 {len(bad)} 处（{bad[:2]}）")
    n_groups = len({(r["layout"], r["n_total"], r["seed"], r["group"]) for r in rows})
    if n_groups != expected:
        problems.append(f"X：单机组数 {n_groups}/{expected}")
    fp = result_fingerprint([{k: v for k, v in r.items() if not k.startswith("secs")} for r in rows])
    lines = [f"## E5-X 与精确解的差距：{n_groups}/{expected} 个单机组 × {len(X_EPS)} 档 ε；结果指纹 {fp}"]
    lines.append("  布点      n  ε     本文：差距 均值/中位/最大   找到最优   两阶段：差距 均值/中位/最大   拿到精确改善的份额")
    for lay in LAYOUTS:
        for n in sorted({r["n"] for r in rows}):
            for e in X_EPS:
                sel = [r for r in rows if r["layout"] == lay and r["n"] == n and r["eps"] == e]
                if not sel:
                    continue
                gp, gb = [r["gap_p2"] for r in sel], [r["gap_b2"] for r in sel]
                den = sum(r["b2"] - r["exact"] for r in sel)
                share = 100 * sum(r["b2"] - r["p2"] for r in sel) / den if den > 0 else float("nan")
                p = [_c(statistics.fmean(gp)), _c(statistics.median(gp)), _c(max(gp))]
                b = [_c(statistics.fmean(gb)), _c(statistics.median(gb)), _c(max(gb))]
                lines.append(f"  {lay:<9} {n}  {e:<4}  {p[0]:5.2f}% / {p[1]:5.2f}% / {p[2]:5.2f}%"
                             f"   {sum(r['optimal'] for r in sel):3d}/{len(sel):<3d}"
                             f"   {b[0]:5.2f}% / {b[1]:5.2f}% / {b[2]:6.2f}%   {share:6.1f}%")
    allp = [r["gap_p2"] for r in rows]
    lines.append(f"  合计：本文方法差距均值 {_c(statistics.fmean(allp)):.2f}%、最大 {_c(max(allp)):.2f}%，"
                 f"找到最优 {sum(r['optimal'] for r in rows)}/{len(rows)}；"
                 f"穷举耗时中位 {statistics.median(r['secs_exact'] for r in rows if r['n'] == max(r2['n'] for r2 in rows)):.1f} s"
                 f"（每机 {max(r['n'] for r in rows)} 点），本文方法中位 {statistics.median(r['secs_ls'] for r in rows):.2f} s")
    return lines, problems


def summarize_t(recs: list[dict], expected: int) -> tuple[list[str], list[str], list[dict]]:
    """T 的摘要与检查：加速前后结果相同；各 (布点, N, m) 的耗时中位数与提速"""
    problems = []
    both = [r for r in recs if "P2N" in r["runs"]]
    mism = [record_name(r["meta"]) for r in both
            if not (r["runs"]["P2A"]["obj"] == r["runs"]["P2N"]["obj"] and r["runs"]["P2A"]["routes"] == r["runs"]["P2N"]["routes"])]
    if mism:
        problems.append(f"T：加速前后结果不同 {mism[:5]}")
    if len(recs) != expected:
        problems.append(f"T：实例数 {len(recs)}/{expected}")
    rows = []
    for r in recs:
        m, a, b = r["meta"], r["runs"]["P2A"], r["runs"].get("P2N")
        rows.append({"layout": m["layout"], "n": m["n"], "m": m["m"], "seed": m["seed"], "per_uav": m["per_uav_max"],
                     "secs_fast": a["secs"], "secs_plain": b["secs"] if b else None,
                     "speedup": b["secs"] / a["secs"] if b else None, "exact_fast": a["exact"],
                     "exact_plain": b["exact"] if b else None, "pruned": a["pruned"], "obj": a["obj"]})
    head = f"## E5-T 求解时间随规模：{len(recs)}/{expected} 个实例（ε = {T_EPS}，加速开、关先后运行；每机超过 {T_PLAIN_MAX} 点只跑加速）"
    lines = [head]
    lines.append("  布点      N    m  每机点数  加速后（中位 s）  不加速（中位 s）  提速中位（范围）   精确动态规划次数中位")
    for lay in LAYOUTS:
        for n in T_SIZES:
            for mm in T_UAVS:
                sel = [x for x in rows if x["layout"] == lay and x["n"] == n and x["m"] == mm]
                if not sel:
                    continue
                fast = statistics.median(x["secs_fast"] for x in sel)
                ef = statistics.median(x["exact_fast"] for x in sel)
                if all(x["speedup"] is not None for x in sel):
                    sp_ = [x["speedup"] for x in sel]
                    plain = f"{statistics.median(x['secs_plain'] for x in sel):14.1f}"
                    rest = (f"   {statistics.median(sp_):5.2f}（{min(sp_):.2f}～{max(sp_):.2f}）"
                            f"   {statistics.median(x['exact_plain'] for x in sel):.0f} → {ef:.0f}")
                else:
                    plain, rest = f"{'未运行':>12}", f"   {'—':>16}   {ef:.0f}（加速）"
                lines.append(f"  {lay:<9} {n:<4} {mm}  {max(x['per_uav'] for x in sel):>6}   {fast:12.1f}   {plain}{rest}")
    lines.append(f"  一致性：两者都运行的 {len(both)} 个实例中，加速前后结果完全相同的 {len(both) - len(mism)} 个")
    return lines, problems, rows


def summarize_f1(recs: list[dict], expected: int) -> tuple[list[str], list[str], list[dict]]:
    """F1 的摘要与检查：精确停靠与枚举的最优值一致"""
    rows = [{"n": r["meta"]["n"], "idx": r["meta"]["idx"], "dp": r["dp"], "brute": r["brute"], "plans": r["plans"],
             "secs_dp": r["secs_dp"], "secs_brute": r["secs_brute"]} for r in recs]
    problems = []
    bad = [x for x in rows if abs(x["dp"] - x["brute"]) > 1e-9 * max(1.0, abs(x["brute"]))]
    if bad:
        problems.append(f"F1：精确停靠与枚举不一致 {len(bad)} 个")
    if len(rows) != expected:
        problems.append(f"F1：实例数 {len(rows)}/{expected}")
    worst = max((abs(x["dp"] - x["brute"]) / max(1.0, abs(x["brute"])) for x in rows), default=0.0)
    lines = [f"## E5-F1 停靠动态规划与枚举对拍：{len(rows)}/{expected} 个实例，一致 {len(rows) - len(bad)} 个，最大相对差 {worst:.1e}"]
    for n in F1_SIZES:
        sel = [x for x in rows if x["n"] == n]
        if sel:
            lines.append(f"  n = {n}：停靠方案 {sel[0]['plans']} 个，枚举耗时中位 {statistics.median(x['secs_brute'] for x in sel):.2f} s，"
                         f"动态规划 {1000 * statistics.median(x['secs_dp'] for x in sel):.2f} ms")
    return lines, problems, rows


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------

E5_LABELS = {
    "zh": {"gap_exact": "与精确最优的差距（%）", "gap_lb": "与逐份下界的差距（%）", "brute": "穷举全部停靠方案",
           "dp": "精确停靠动态规划", "opt_brute": "穷举得到的最优目标", "opt_dp": "动态规划得到的最优目标",
           "n_route": "航线上的观测点数", "secs_log": "求解时间（s，对数刻度）", "per_uav": "每机观测点数",
           "exact_log": "精确动态规划次数（对数刻度）", "speedup": "提速倍数（不加速 ÷ 加速）",
           "lb_ratio_log": "归一化 AoI ÷ 逐份下界（对数刻度）"},
    "en": {"gap_exact": "Gap to exact optimum (%)", "gap_lb": "Gap to per-item bound (%)", "brute": "Brute-force stops",
           "dp": "Exact stop DP", "opt_brute": "Optimum by brute force", "opt_dp": "Optimum by DP",
           "n_route": "Points on route", "secs_log": "Solve time (s, log scale)", "per_uav": "Points per UAV",
           "exact_log": "Exact DP calls (log scale)", "speedup": "Speedup (no accel. / accel.)",
           "lb_ratio_log": "Normalized AoI / per-item bound (log scale)"},
}


def _l(lang: str, key: str) -> str:
    import scheme1_plots as sp

    return E5_LABELS[lang].get(key) or sp.label(lang, key)


def fig_x_gap(rows: list[dict], lang: str):
    """与精确最优的差距：两档 ε 各一个子图，每个观测点数两个箱（本文方法、两阶段），两种布点合并"""
    import matplotlib
    import scheme1_plots as sp

    fig, axes = sp.new_fig(ncols=2, width=sp.DOUBLE_W, height=2.4, sharey=True)
    ns = sorted({r["n"] for r in rows})
    for ax, e in zip(axes, X_EPS):
        for k, (m, key) in enumerate((("P2", "gap_p2"), ("B2", "gap_b2"))):
            data = [[r[key] for r in rows if r["n"] == n and r["eps"] == e] for n in ns]
            pos = [i + (k - 0.5) * 0.36 for i in range(len(ns))]
            bp = ax.boxplot(data, positions=pos, widths=0.3, patch_artist=True)
            c = sp.COLORS[m]
            for i in range(len(ns)):
                bp["boxes"][i].set(facecolor=matplotlib.colors.to_rgba(c, 0.18), edgecolor=c, linewidth=0.8)
                for art in bp["whiskers"][2 * i:2 * i + 2] + bp["caps"][2 * i:2 * i + 2]:
                    art.set(color=c, linewidth=0.8)
                bp["medians"][i].set(color=sp.INK["primary"], linewidth=1.0)
                bp["fliers"][i].set(marker="o", markersize=2, markerfacecolor="none", markeredgecolor=c, markeredgewidth=0.5)
        ax.set_xticks(range(len(ns)), [str(n) for n in ns])
        ax.set_xlabel(_l(lang, "per_uav"))
        ax.set_title(f"ε = {e}")
        ax.set_ylim(bottom=-0.5)
    axes[0].set_ylabel(_l(lang, "gap_exact"))
    sp.legend_top(fig, [sp.method_handle("P2", lang), sp.method_handle("B2", lang)])
    return fig


def _t_points(rows: list[dict], lay: str, mm: int, key: str) -> list[tuple]:
    """某布点、机数下 key 随 N 的中位数（3 个种子）：[(N, 中位数)]

    不加速只在每机不超过 T_PLAIN_MAX 个观测点时运行，没有运行的档（值为 None）不画
    """
    pts = []
    for n in T_SIZES:
        vals = [r[key] for r in rows if r["layout"] == lay and r["m"] == mm and r["n"] == n and r[key] is not None]
        if vals:
            pts.append((n, statistics.median(vals)))
    return pts


def _level_line(ax, pts: list[tuple], color: str, linestyle, marker: str) -> None:
    """一条空心标记的折线"""
    import scheme1_plots as sp

    ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, linestyle=linestyle, marker=marker,
            markerfacecolor=sp.INK["surface"], markeredgecolor=color, markeredgewidth=0.9, zorder=3)


def _level_handle(label: str, color: str, linestyle, marker: str):
    """与 _level_line 同样式的图例句柄"""
    import scheme1_plots as sp
    from matplotlib.lines import Line2D

    return Line2D([], [], color=color, linestyle=linestyle, marker=marker, markerfacecolor=sp.INK["surface"],
                  markeredgecolor=color, markeredgewidth=0.9, label=label)


# 计时两个版本的线型：加速为实线，不加速为虚线（与作图模块中"变体用虚线"的约定一致）；图中各线都是 SCOUT，图例只写版本
T_VERSIONS = (("P2A", "-"), ("P2N", (0, (3, 1.5))))
T_VERSION_NAME = {"zh": {"P2A": "加速", "P2N": "不加速"}, "en": {"P2A": "accel.", "P2N": "no accel."}}
LAYOUT_DASH = {"fireline": "-", "sector": (0, (3, 1.5))}


def fig_t_lines(rows: list[dict], lang: str, metric: str):
    """F3：两项加速的效果随规模的变化（对数纵轴），左右为两种布点；每个子图 6 条线 = 加速开 / 关 × 机数 3、5、7

    按参考论文中"方法（变体）× 关键参数"的画法：颜色为本文方法的蓝色、机数越多越深，线型区分加速开关；
    机数为 3 时每机点数在 N ≥ 80 超过 T_PLAIN_MAX，不加速的线只有 N = 30、50 两点
    :param metric: "secs"（求解时间）或 "exact"（精确动态规划次数）
    :return: 图
    """
    import scheme1_plots as sp

    keys = {"secs": ("secs_fast", "secs_plain"), "exact": ("exact_fast", "exact_plain")}[metric]
    colors = sp.level_colors(sp.COLORS["P2"], len(T_UAVS))
    fig, axes = sp.new_fig(ncols=2, width=sp.DOUBLE_W, height=2.6, sharey=True)
    handles = []
    for ax, lay in zip(axes, LAYOUTS):
        for (version, dash), key in zip(T_VERSIONS, keys):
            for mm, c, mk in zip(T_UAVS, colors, sp.LEVEL_MARKERS):
                pts = _t_points(rows, lay, mm, key)
                if not pts:
                    continue
                _level_line(ax, pts, c, dash, mk)
                if ax is axes[0]:
                    name = T_VERSION_NAME[lang][version]
                    handles.append(_level_handle(f"{name}，m = {mm}" if lang == "zh" else f"{name}, m = {mm}", c, dash, mk))
        ax.set_yscale("log")
        ax.set_xticks(list(T_SIZES), [str(n) for n in T_SIZES])
        ax.set_title(sp.label(lang, lay))
        ax.set_xlabel(sp.label(lang, "n"))
        ax.grid(True, axis="both", which="major")
    axes[0].set_ylabel(_l(lang, "secs_log" if metric == "secs" else "exact_log"))
    sp.legend_top(fig, handles, ncol=3, rows_first=True)
    return fig


def fig_t_speedup(rows: list[dict], lang: str):
    """X7：两项加速的提速倍数（不加速 ÷ 加速的求解时间，3 个种子的中位数）随规模的变化；6 条线 = 两种布点 × 机数 3、5、7

    提速只在两个版本都运行时有定义，机数为 3 的线只有 N = 30、50 两点；虚线 1 表示没有提速
    :return: 图
    """
    import scheme1_plots as sp

    colors = sp.level_colors(sp.COLORS["P2"], len(T_UAVS))
    short = {"zh": {"fireline": "火线", "sector": "扇形"}, "en": {"fireline": "Fire line", "sector": "Sector"}}[lang]
    fig, ax = sp.new_fig(height=2.6)
    handles = []
    for lay in LAYOUTS:
        for mm, c, mk in zip(T_UAVS, colors, sp.LEVEL_MARKERS):
            pts = _t_points(rows, lay, mm, "speedup")
            if pts:
                _level_line(ax, pts, c, LAYOUT_DASH[lay], mk)
                handles.append(_level_handle(f"{short[lay]}，m = {mm}" if lang == "zh" else f"{short[lay]}, m = {mm}",
                                             c, LAYOUT_DASH[lay], mk))
    ax.axhline(1.0, zorder=1, **sp.REF_STYLE)
    ax.set_xticks(list(T_SIZES), [str(n) for n in T_SIZES])
    ax.set_xlabel(sp.label(lang, "n"))
    ax.set_ylabel(_l(lang, "speedup"))
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="both")
    sp.legend_top(fig, handles, ncol=3, rows_first=True)
    return fig


def fig_f1(rows: list[dict], lang: str):
    """F1：左为枚举与动态规划的最优目标（对角线即完全一致），右为两者耗时的中位数（对数纵轴）"""
    import scheme1_plots as sp
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig, (axl, axr) = sp.new_fig(ncols=2, width=sp.DOUBLE_W, height=2.5)
    c = sp.COLORS["P2"]
    lo = min(min(x["brute"], x["dp"]) for x in rows)
    hi = max(max(x["brute"], x["dp"]) for x in rows)
    axl.plot([lo, hi], [lo, hi], zorder=1, **sp.REF_STYLE)
    hs = []
    for n, mk in zip(F1_SIZES, "os^"):
        sel = [x for x in rows if x["n"] == n]
        if not sel:
            continue
        axl.scatter([x["brute"] for x in sel], [x["dp"] for x in sel], s=12, marker=mk, facecolors="none", edgecolors=c,
                    linewidths=0.7, zorder=3)
        hs.append(Line2D([], [], linestyle="none", marker=mk, markerfacecolor="none", markeredgecolor=c, label=f"n = {n}"))
    axl.set_xlabel(_l(lang, "opt_brute"))
    axl.set_ylabel(_l(lang, "opt_dp"))
    axl.grid(True, axis="both")
    ns = [n for n in F1_SIZES if any(x["n"] == n for x in rows)]
    w = 0.36
    tb = [statistics.median(x["secs_brute"] for x in rows if x["n"] == n) for n in ns]
    td = [statistics.median(x["secs_dp"] for x in rows if x["n"] == n) for n in ns]
    axr.bar([i - w / 2 for i in range(len(ns))], tb, width=w * 0.9, color=sp.INK["muted"], linewidth=0, zorder=2)
    axr.bar([i + w / 2 for i in range(len(ns))], td, width=w * 0.9, color=c, linewidth=0, zorder=2)
    axr.set_yscale("log")
    axr.set_xticks(range(len(ns)), [str(n) for n in ns])
    axr.set_xlabel(_l(lang, "n_route"))
    axr.set_ylabel(_l(lang, "secs_log"))
    axr.tick_params(axis="x", length=0)
    hs += [Patch(facecolor=sp.INK["muted"], label=_l(lang, "brute")), Patch(facecolor=c, label=_l(lang, "dp"))]
    sp.legend_top(fig, hs, ncol=5)
    return fig


def fig_lbgap(by: dict, lang: str):
    """与逐份下界的差距随 N 的变化（E1 全部实例）：行为 ε、列为布点，每种方法一条线（归一化 AoI ÷ 逐份下界的中位数）

    与主对比用同一组 7 种方法；各方法与下界之比相差一个数量级（本文方法约 1.1–1.6，仅基地上传约 5–8），取对数纵轴。
    比值 = 1 + 差距 / 100，与 lbgap_summary.txt 中的差距（%）一一对应
    :param by: {(布点, N, 种子, ε): {方法: E1 汇总行}}
    :return: 图
    """
    import matplotlib.pyplot as plt
    import scheme1_plots as sp

    ns = sorted({k[1] for k in by})
    fig, axes = plt.subplots(2, len(LAYOUTS), figsize=(sp.DOUBLE_W, 4.2), layout="constrained", sharex=True, sharey=True)
    handles = []
    for i, e in enumerate((0.1, 0.25)):
        for j, lay in enumerate(LAYOUTS):
            ax = axes[i][j]
            series = {m: [statistics.median(v[m]["norm_aoi"] / v[m]["lb_norm"] for k, v in by.items()
                                            if k[0] == lay and k[1] == n and k[3] == e) for n in ns]
                      for m in sp.METHOD_ORDER}
            handles = sp.line_chart(ax, ns, series, lang)
            ax.set_yscale("log")
            sp.plain_log_ticks(ax)
            ax.set_xticks(ns, [str(n) for n in ns])
            ax.set_title(f"{sp.label(lang, lay)}，ε = {e}" if lang == "zh" else f"{sp.label(lang, lay)}, ε = {e}")
            ax.grid(True, axis="both")
            if i == 1:
                ax.set_xlabel(sp.label(lang, "n"))
        axes[i][0].set_ylabel(_l(lang, "lb_ratio_log"))
    sp.legend_top(fig, handles)
    return fig


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def summarize(inputs, out: Path, expected: dict | None = None) -> bool:
    """汇总 X、T、F1：摘要写 summary.txt，表写 CSV，图写 figures/；有检查不通过时返回 False"""
    import scheme1_plots as sp

    expected = expected or {"X": len(jobs("X")) * 5, "T": len(jobs("T")), "F1": len(jobs("F1"))}
    recs = load_records(inputs)
    out.mkdir(parents=True, exist_ok=True)
    xr = x_rows(recs["X"])
    lx, px = summarize_x(xr, expected["X"]) if xr else ([], ["X：没有记录"])
    lt, pt, tr = summarize_t(recs["T"], expected["T"]) if recs["T"] else ([], ["T：没有记录"], [])
    lf, pf, fr = summarize_f1(recs["F1"], expected["F1"]) if recs["F1"] else ([], ["F1：没有记录"], [])
    sp.write_rows(out / "E5_X_rows.csv", xr)
    sp.write_rows(out / "E5_T_rows.csv", tr)
    sp.write_rows(out / "E5_F1_rows.csv", fr)
    files: list[Path] = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = out / "figures" / lang
        if xr:
            files += sp.save(fig_x_gap(xr, lang), d, "E5_gap_to_exact")
        if tr:
            files += sp.save(fig_t_lines(tr, lang, "secs"), d, "E5_F3_acceleration_time")
            files += sp.save(fig_t_lines(tr, lang, "exact"), d, "E5_F3_acceleration_exact_calls")
            files += sp.save(fig_t_speedup(tr, lang), d, "E5_X7_speedup")
        if fr:
            files += sp.save(fig_f1(fr, lang), d, "E5_F1_stop_dp_vs_bruteforce")
    problems = px + pt + pf
    lines = lx + [""] + lt + [""] + lf + [""]
    lines.append("检查：" + ("全部通过（单机组齐全、没有方法优于精确最优、加速前后结果相同、动态规划与枚举一致）"
                             if not problems else "；".join(problems)))
    lines.append(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return not problems


def lbgap(e1_csv: Path, out: Path) -> None:
    """与逐份下界的差距（E1 全部实例，本地运行）：按布点、ε、N 的中位数与四分位数，并出图"""
    import scheme1_plots as sp

    by: dict = {}
    for r in sp.read_rows(e1_csv):
        by.setdefault((r["layout"], int(r["n"]), int(r["seed"]), r["eps"]), {})[r["method"]] = r
    rows = [{"layout": k[0], "n": k[1], "seed": k[2], "eps": k[3],
             "gap_p2": 100 * (v["P2"]["norm_aoi"] / v["P2"]["lb_norm"] - 1),
             "gap_b2": 100 * (v["B2"]["norm_aoi"] / v["B2"]["lb_norm"] - 1)} for k, v in sorted(by.items())]
    out.mkdir(parents=True, exist_ok=True)
    sp.write_rows(out / "E5_lbgap_rows.csv", rows)
    lines = [f"## E5 与逐份下界的差距（E1 全部 {len(rows)} 个实例；中位数［四分位］，括号外为本文方法，后为两阶段的中位数）"]
    for lay in LAYOUTS:
        for e in (0.1, 0.25):
            cells = []
            for n in sorted({r["n"] for r in rows}):
                sel = [r for r in rows if r["layout"] == lay and r["eps"] == e and r["n"] == n]
                q = statistics.quantiles([r["gap_p2"] for r in sel], n=4, method="inclusive")
                q = [round(x, 1) + 0.0 for x in q]   # 加 0.0 把舍入后的 −0.0（达到下界时的浮点误差）显示为 0.0
                cells.append(f"N={n} {q[1]:.1f}%［{q[0]:.1f}～{q[2]:.1f}］/{statistics.median(r['gap_b2'] for r in sel):.1f}%")
            lines.append(f"  {lay} ε = {e}：" + "；".join(cells))
    files = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        files += sp.save(fig_lbgap(by, lang), out / "figures" / lang, "E5_gap_to_lower_bound")
    (out / "lbgap_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一 E5：最优性与规模")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("shard")
    p.add_argument("--exp", choices=("X", "T", "F1"), required=True)
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--shards", type=int, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("summary")
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("lbgap")
    p.add_argument("--e1", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("smoke")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "shard":
        run_jobs(shard_jobs(a.exp, a.shard, a.shards), a.out, a.workers, f"{a.exp}_{a.shard}")
        return 0
    if a.cmd == "summary":
        return 0 if summarize(a.inputs, a.out) else 1
    if a.cmd == "lbgap":
        lbgap(a.e1, a.out)
        return 0
    js = {"X": [j for j in jobs("X", seeds=(100,)) if j[2] in (30, 35)],
          "T": [j for j in jobs("T", seeds=(100,)) if j[2] == 30 and j[3] in (5, 7)],
          "F1": [j for j in jobs("F1") if j[1] in (4, 5) and j[2] < 3]}
    for e, jl in js.items():
        run_jobs(jl, a.out / "shards" / e, a.workers, f"{e}_smoke")
    return 0 if summarize([a.out / "shards"], a.out / "summary",
                          {"X": len(js["X"]) * 5, "T": len(js["T"]), "F1": len(js["F1"])}) else 1


if __name__ == "__main__":
    sys.exit(main())
