"""第二道检验：单机小规模实例上枚举访问顺序 + 停靠动态规划求联合最优，与两阶段比较

事先声明的判定规则（2026-10-26 运行前写定，不随结果调整）
- 主指标：平均归一化 AoI，即 (1/n) Σ AoI_i/δ_i；改善 = 1 - mean(联合)/mean(两阶段+)，按 ε 在全部实例上汇总
- 两阶段+：精确最短回路（枚举得到）的两个方向各求一次最优停靠，取较好者，作为保守的两阶段基线
- ε = 0.1 与 ε = 0.25 下改善均 ≥ 10%：通过，进入完整外层算法设计；均 < 5%：不通过；其余为灰区
- 时长预算 T_max = (1+ε)·T̂，T̂ 为该机精确最短回路不停靠时的任务时长（逐机预算）
其余设置沿用冻结参数与 degeneracy_check.py：E1–E3 三站、44 个候选上传点、10 Mbps、τ = 1 s、新终点规则
实例：按冻结配置生成 n = 30/35/40 个观测点、5 架机扇形分配，每个扇区作为一个单机实例（6/7/8 个观测点），各 4 个种子
用法
- python gate2_check.py crosscheck [--out 目录]：加速动态规划对拍，偏差超过 1e-9 时以非零码退出
- python gate2_check.py run [--workers 11] [--out 目录]：本地跑全部实例并判定
- python gate2_check.py run --size 40 --seed 3 --workers 4 --out 目录：只跑一个分片（Actions 矩阵作业）
- python gate2_check.py merge 分片目录 [--out 目录]：汇总分片并判定，实例不全时以非零码退出
输出目录缺省为脚本所在目录
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

from degeneracy_check import (DEPOT, M_UAV, RATE, TAU, TOL, V, candidate_points, dist, dp, hover_time,
                              lower_bound, make_tasks, sweep_assign)

EPS = (0.05, 0.1, 0.25, 0.5)
GATE_EPS = (0.1, 0.25)
SIZES = (30, 35, 40)      # 5 架机扇形分配后每机 6/7/8 个观测点
SEEDS = 4
HERE = Path(__file__).resolve().parent


def pareto(labels: list[tuple]) -> list[tuple]:
    """按 (目标, 飞行时间) 取非支配集合"""
    out, best_f = [], math.inf
    for lab in sorted(labels, key=lambda x: (x[0], x[1])):
        if lab[1] < best_f - 1e-9:
            out.append(lab)
            best_f = lab[1]
    return out


def insert_pareto(cur: list[tuple], lab: tuple) -> None:
    o, f = lab[0], lab[1]
    for x in cur:
        if x[0] <= o + 1e-12 and x[1] <= f + 1e-9:
            return
    cur[:] = [x for x in cur if not (o <= x[0] + 1e-12 and f <= x[1] + 1e-9)]
    cur.append(lab)


def pareto_dp(route: list[dict], pts: list[tuple], cap: float | None) -> list[tuple]:
    """固定顺序下的停靠动态规划，返回终点处（Σ AoI/δ, 飞行时间, 停靠方案）的帕累托集合

    段的 AoI 与段起点无关：起点到段内第一个观测点的飞行发生在任何采集之前，只影响飞行时间。
    因此同一位置的全部状态先按"飞到下一个观测点"合并成一个帕累托集合再向后转移，转移从 |P|² 降为 |P|
    :param route: 已排好顺序的观测点
    :param pts: 候选上传点
    :param cap: 飞行时间上限（s），None 表示不限
    :return: [(目标, 飞行时间, ((航点序号, 上传点序号), ...)), ...]，上传点序号 -1 表示基地，最后一项为终点上传
    """
    n = len(route)
    q = [t["q"] for t in route]
    big = math.inf if cap is None else cap
    # rest[k]：采完第 k 个观测点后不再停靠、按顺序采完并直接回基地的飞行时间，用作剩余飞行的下界
    rest = [0.0] * (n + 2)
    rest[n] = dist(q[n - 1], DEPOT) / V
    for k in range(n - 1, 0, -1):
        rest[k] = rest[k + 1] + dist(q[k - 1], q[k]) / V
    pt_of = (lambda qi: DEPOT if qi == -1 else pts[qi])
    labels: list[dict] = [dict() for _ in range(n + 1)]
    labels[0][-1] = [(0.0, 0.0, ())]
    terminal: list[tuple] = []
    for j in range(n):
        first = q[j]
        merged = []
        for qi, labs in labels[j].items():
            d0 = dist(pt_of(qi), first) / V
            for (o, f, s) in labs:
                if f + d0 + rest[j + 1] <= big + TOL:      # 之后即使不再停靠也超预算的标签直接剪掉
                    merged.append((o, f + d0, s))
        merged = pareto(merged)
        if not merged:
            continue
        t_rel = c_over_d = w_sum = path = 0.0
        for k in range(j + 1, n + 1):
            t = route[k - 1]
            if k > j + 1:
                leg = dist(q[k - 2], q[k - 1]) / V
                path += leg
                t_rel += leg
            t_rel += t["tc"]
            c_over_d += t_rel / t["delta"]
            w_sum += 1.0 / t["delta"]
            clock = up_term = 0.0
            for x in sorted(route[j:k], key=lambda y: y["D"] * y["delta"]):   # 站内 WSPT
                clock += x["D"] / RATE
                up_term += clock / x["delta"]
            base_obj = t_rel * w_sum + up_term + TAU * w_sum - c_over_d
            ends = range(len(pts)) if k < n else itertools.chain((-1,), range(len(pts)))
            for qi in ends:
                pq = pt_of(qi)
                tail = dist(q[k - 1], pq) / V
                seg_obj = base_obj + tail * w_sum
                seg_fly = path + tail + (dist(pq, DEPOT) / V if k == n else 0.0)
                min_after = dist(pq, q[k]) / V + rest[k + 1] if k < n else 0.0
                for (o, f, s) in merged:
                    nf = f + seg_fly
                    if nf + min_after > big + TOL:
                        continue
                    lab = (o + seg_obj, nf, s + ((k, qi),))
                    if k == n:
                        terminal.append(lab)
                    else:
                        insert_pareto(labels[k].setdefault(qi, []), lab)
    return pareto(terminal)


def best_under(front: list[tuple], cap: float) -> tuple | None:
    feas = [lab for lab in front if lab[1] <= cap + TOL]
    return min(feas, key=lambda x: (x[0], x[1])) if feas else None


def crosscheck(out_dir: Path) -> None:
    """对拍：pareto_dp 在给定上限下的最优值 vs degeneracy_check.dp（已与穷举对拍）

    :param out_dir: 输出目录；最大偏差超过 1e-9 时以非零码退出，让 Actions 作业在主计算前失败
    """
    rng = random.Random(11)
    pts = candidate_points()
    worst, cnt = 0.0, 0
    for _ in range(60):
        n = rng.randint(5, 8)
        route = make_tasks(rng, n)
        hov = hover_time(route)
        f_ns = sum(dist(a, b) for a, b in zip([DEPOT] + [t["q"] for t in route], [t["q"] for t in route] + [DEPOT])) / V
        for cap in (None, f_ns * rng.uniform(1.0, 1.5)):
            front = pareto_dp(route, pts, cap)
            a = min(x[0] for x in front) if cap is None else best_under(front, cap)[0]
            b = dp(route, pts, cap)[0]
            worst = max(worst, abs(a - b))
            cnt += 1
    msg = f"对拍 {cnt} 组（5–8 个观测点，不限与飞行时间上限各半），pareto_dp 与已验证动态规划的最大偏差 {worst:.2e}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate2_crosscheck_out.txt").write_text(msg + "\n", encoding="utf-8", newline="\n")
    print(msg)
    if worst > 1e-9:
        raise SystemExit(1)


def tour_len(perm, dm) -> float:
    nodes = (0,) + tuple(i + 1 for i in perm) + (0,)
    return sum(dm[nodes[i]][nodes[i + 1]] for i in range(len(nodes) - 1))


def solve(inst: dict) -> dict:
    """单机实例：枚举全部访问顺序求联合最优；精确最短回路两个方向求两阶段"""
    t0 = time.perf_counter()
    tasks = inst["tasks"]
    n = len(tasks)
    pts = candidate_points()
    nodes = [DEPOT] + [t["q"] for t in tasks]
    dm = [[dist(a, b) for b in nodes] for a in nodes]
    hov = hover_time(tasks)
    perms = list(itertools.permutations(range(n)))
    lens = [tour_len(p, dm) for p in perms]
    l_tsp = min(lens)
    t_hat = l_tsp / V + hov
    caps = {e: (1 + e) * t_hat - hov for e in EPS}     # 飞行时间上限
    cap_max = caps[max(EPS)]
    joint = {e: None for e in EPS}
    tsp = {}
    n_dp = 0
    for perm, length in zip(perms, lens):
        if length / V > cap_max + TOL:
            continue
        front = pareto_dp([tasks[i] for i in perm], pts, cap_max)
        n_dp += 1
        for e in EPS:
            b = best_under(front, caps[e])
            if b is not None and (joint[e] is None or b[0] < joint[e]["obj"] - 1e-12):
                joint[e] = {"obj": b[0], "fly": b[1], "perm": list(perm), "stops": [list(s) for s in b[2]]}
        if length <= l_tsp + 1e-6:
            tsp[perm] = front
    two_stage = {}
    for e in EPS:
        rows = []
        for perm, front in tsp.items():
            b = best_under(front, caps[e])
            rows.append({"obj": b[0], "fly": b[1], "perm": list(perm), "stops": [list(s) for s in b[2]]})
        two_stage[e] = rows
    return {"size": inst["size"], "seed": inst["seed"], "group": inst["group"], "n": n,
            "tasks": [{"q": list(t["q"]), "D": t["D"], "delta": t["delta"], "tc": t["tc"]} for t in tasks],
            "l_tsp": l_tsp, "hover": hov, "t_hat": t_hat, "lb": lower_bound(tasks, pts),
            "w_sum": sum(1 / t["delta"] for t in tasks), "n_dp": n_dp, "n_perm": len(perms),
            "joint": {str(e): joint[e] for e in EPS}, "two_stage": {str(e): two_stage[e] for e in EPS},
            "secs": time.perf_counter() - t0}


def instances() -> list[dict]:
    rng = random.Random(20261026)
    out = []
    for size in SIZES:
        for seed in range(SEEDS):
            tasks = make_tasks(rng, size)
            for g, group in enumerate(sweep_assign(tasks)):
                out.append({"size": size, "seed": seed, "group": g, "tasks": group})
    return out


def summarize(res: list[dict]) -> list[str]:
    lines = []

    def stats(rows, e):
        key = str(e)
        j = [r["joint"][key]["obj"] / r["n"] for r in rows]
        b_plus = [min(x["obj"] for x in r["two_stage"][key]) / r["n"] for r in rows]
        b_avg = [statistics.mean(x["obj"] for x in r["two_stage"][key]) / r["n"] for r in rows]
        per = [1 - a / b for a, b in zip(j, b_plus)]
        return {"J": statistics.mean(j), "B+": statistics.mean(b_plus), "Bavg": statistics.mean(b_avg),
                "imp": 1 - statistics.mean(j) / statistics.mean(b_plus),
                "imp_avg": 1 - statistics.mean(j) / statistics.mean(b_avg),
                "med": statistics.median(per), "ge10": sum(p >= 0.10 for p in per), "cnt": len(per),
                "lb": statistics.mean(r["lb"] / r["n"] for r in rows)}

    lines.append("平均归一化 AoI（(1/n) Σ AoI/δ）：联合最优 J、两阶段+ B+（最短回路较好方向）、两阶段平均 Bavg（两个方向的平均）")
    for e in EPS:
        lines.append(f"ε = {e}")
        for nu in sorted({r["n"] for r in res}):
            s = stats([r for r in res if r["n"] == nu], e)
            lines.append(f"  每机 {nu} 个观测点（{s['cnt']} 个实例）：J {s['J']:.4f}，B+ {s['B+']:.4f}，Bavg {s['Bavg']:.4f}，下界 {s['lb']:.4f}；"
                         f"改善（对 B+）{100 * s['imp']:.1f}%（对 Bavg {100 * s['imp_avg']:.1f}%），逐例中位 {100 * s['med']:.1f}%，"
                         f"≥10% 的实例 {s['ge10']}/{s['cnt']}")
        s = stats(res, e)
        lines.append(f"  全部 {s['cnt']} 个实例：改善（对 B+）{100 * s['imp']:.1f}%（对 Bavg {100 * s['imp_avg']:.1f}%），逐例中位 {100 * s['med']:.1f}%，"
                     f"≥10% 的实例 {s['ge10']}/{s['cnt']}")
    gate = [stats(res, e)["imp"] for e in GATE_EPS]
    verdict = "通过" if all(g >= 0.10 for g in gate) else ("不通过" if all(g < 0.05 for g in gate) else "灰区")
    lines.append(f"判定（事先声明）：ε = 0.1 改善 {100 * gate[0]:.1f}%，ε = 0.25 改善 {100 * gate[1]:.1f}% → {verdict}")
    lines.append(f"枚举规模：每例做动态规划的顺序数 中位 {statistics.median(r['n_dp'] for r in res):.0f}（全部顺序 6!/7!/8!），"
                 f"单例耗时 中位 {statistics.median(r['secs'] for r in res):.0f} s、最大 {max(r['secs'] for r in res):.0f} s")
    return lines


def run(out_dir: Path, workers: int, size: int | None = None, seed: int | None = None) -> None:
    """运行第二道检验；同时给出 size 与 seed 时只跑这一个分片，否则跑全部实例并判定

    :param out_dir: 输出目录
    :param workers: 进程数
    :param size: 分片的观测点总数（30/35/40），None 表示全部
    :param seed: 分片的种子序号（0–3），None 表示全部
    """
    # 每个分片都重新生成全部实例再筛选，保证与整体运行时的随机数流完全一致
    insts = [x for x in instances() if (size is None or x["size"] == size) and (seed is None or x["seed"] == seed)]
    if not insts:
        raise SystemExit(f"没有匹配的实例：size={size}，seed={seed}")
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(solve, sorted(insts, key=lambda x: -len(x["tasks"]))))
    res.sort(key=lambda r: (r["size"], r["seed"], r["group"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    if size is not None:
        # 分片只写原始结果，判定留到汇总后，避免用不完整的数据下结论
        (out_dir / f"gate2_results_{size}_{seed}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print(f"分片 size={size} seed={seed}：{len(res)} 个实例，耗时 {time.perf_counter() - t0:.0f} s（{workers} 进程）")
        return
    (out_dir / "gate2_results.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    lines = summarize(res) + [f"总耗时 {time.perf_counter() - t0:.0f} s（{workers} 进程）"]
    (out_dir / "gate2_out.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def merge(src_dir: Path, out_dir: Path) -> None:
    """汇总各分片结果并按事先声明的规则判定

    :param src_dir: 分片结果所在目录（含子目录），文件名为 gate2_results_<size>_<seed>.json
    :param out_dir: 汇总结果与判定的输出目录；实例不全时写明不完整、不做判定并以非零码退出
    """
    files = sorted(src_dir.rglob("gate2_results_*_*.json"))
    res = [r for f in files for r in json.loads(f.read_text(encoding="utf-8"))]
    res.sort(key=lambda r: (r["size"], r["seed"], r["group"]))
    expected = len(SIZES) * SEEDS * M_UAV
    complete = len(res) == expected and len({(r["size"], r["seed"], r["group"]) for r in res}) == expected
    lines = [f"汇总 {len(files)} 个分片、{len(res)} 个实例（应为 {expected} 个）"]
    if complete:
        lines += summarize(res) + [f"单实例耗时之和 {sum(r['secs'] for r in res):.0f} s"]
    else:
        lines.append("结果不完整，不做判定")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate2_results.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    (out_dir / "gate2_out.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    if not complete:
        raise SystemExit(1)


def speed() -> None:
    """测一个 8 点实例的规模与耗时，用来估计总运行时间"""
    inst = [x for x in instances() if len(x["tasks"]) == 8][0]
    r = solve(inst)
    print(f"8 点实例：做动态规划的顺序 {r['n_dp']}/{r['n_perm']}，耗时 {r['secs']:.1f} s")


def main() -> None:
    ap = argparse.ArgumentParser(description="第二道检验：联合优化 vs 两阶段")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("crosscheck")
    p.add_argument("--out", type=Path, default=HERE)
    sub.add_parser("speed")
    p = sub.add_parser("run")
    p.add_argument("--size", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--workers", type=int, default=11)
    p.add_argument("--out", type=Path, default=HERE)
    p = sub.add_parser("merge")
    p.add_argument("src", type=Path)
    p.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.cmd == "crosscheck":
        crosscheck(a.out)
    elif a.cmd == "speed":
        speed()
    elif a.cmd == "run":
        if (a.size is None) != (a.seed is None):
            ap.error("分片运行需要同时给出 --size 与 --seed")
        run(a.out, a.workers, a.size, a.seed)
    else:
        merge(a.src, a.out or a.src)


if __name__ == "__main__":
    main()
