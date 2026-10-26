"""方案一正式算法（src/uav_mec/scheme1）的回归与提速检查

1. 回归：代入检验脚本的四舍五入常数，与第三道检验（experiments/scheme1/gate3_check.py）的 B、C 部分逐位比对
   （目标值、局部搜索得到的顺序、评估次数、跨机移动次数）
2. 提速：用冻结参数，在单机实例（每机 10/13/16 个观测点、两种布点）与机队实例上，分别运行加速与不加速，
   确认结果完全相同，并记录耗时、精确动态规划次数与被时间价格下界剪掉的候选比例
任何一项不一致则以非零码退出
用法：python experiments/scheme1_algo_check.py --workers 4 --out 目录
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "scheme1"))

from uav_mec.scheme1 import (RouteEvaluator, SearchConfig, load_scheme1_params, make_instance,  # noqa: E402
                             route_local_search, script_constants, seed_of, shortest_tour, solve_fleet)

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
EPS = 0.1


def formal_single(sp, layout: str, size: int, seed: int, group: int, eps: float, accelerate: bool) -> dict:
    """与第三道检验 B 部分相同的单机流程：逐机预算，两阶段+，从最短回路两个方向出发的局部搜索"""
    inst, groups = make_instance(layout, size, 5, seed, sp)
    g = groups[group]
    tour, l_tsp = shortest_tour(inst, g)
    hov = inst.hover_time(g)
    cap = (1 + eps) * (l_tsp / sp.speed_mps + hov) - hov
    ev = RouteEvaluator(inst, lambda r: cap, accelerate=accelerate)
    dirs = []
    for p in (tour, tour[::-1]):
        if ev.length_ok(p):
            ev.touch(p)
        dirs.append(ev.exact(p)[0])
    t0 = time.perf_counter()
    best, evals = None, []
    for si, start in enumerate((tour, tour[::-1])):
        r, v, e, _ = route_local_search(ev, start, SearchConfig().evals(len(g)),
                                        random.Random(seed_of(f"{layout}-{size}-{seed}-{group}", eps, si)))
        evals.append(e)
        if best is None or v[0] < best[1][0]:
            best = (r, v)
    return {"bplus": min(dirs), "ls": best[1][0], "perm": best[0], "evals": evals, "secs": time.perf_counter() - t0,
            "exact": ev.stats["exact"], "pruned": ev.stats["pruned"], "lambda": ev.stats["lambda"]}


def regress_single(args) -> dict:
    layout, size, seed, group = args
    import gate3_check as g3
    sc = script_constants(load_scheme1_params(CONFIG))
    ref_inst = g3.single_instances(layout, size, seed)[group]
    ref = g3.solve_single(ref_inst, eps_list=(EPS,))["eps"][str(EPS)]
    got = formal_single(sc, layout, size, seed, group, EPS, accelerate=True)
    _, groups = make_instance(layout, size, 5, seed, sc)
    ref_perm = [groups[group][i] for i in ref["ls_perm"]]
    same = (ref["bplus"] == got["bplus"] and ref["ls"] == got["ls"] and ref_perm == got["perm"]
            and [s["evals"] for s in ref["stats"]] == got["evals"])
    return {"case": f"单机 {layout} {size}/{seed}/{group}", "same": same, "ref": ref["ls"], "got": got["ls"]}


def regress_fleet(args) -> dict:
    layout, seed = args
    import gate3_check as g3
    sc = script_constants(load_scheme1_params(CONFIG))
    ref = g3.solve_fleet_eps((layout, seed, EPS))
    inst, groups = make_instance(layout, 50, 5, seed, sc)
    got = solve_fleet(inst, groups, EPS, SearchConfig(accelerate=True), tag=(layout, seed, EPS))
    same = ((ref["two_stage"], ref["per_route"], ref["fleet"], ref["inter_evals"], ref["accepted"])
            == (got.two_stage, got.per_route, got.objective, got.stats["inter_evals"], got.stats["accepted"]))
    return {"case": f"机队 {layout} 种子 {seed}", "same": same, "ref": ref["fleet"], "got": got.objective}


def speed_single(args) -> dict:
    layout, size, seed = args
    sp = load_scheme1_params(CONFIG)
    a = formal_single(sp, layout, size, seed, 0, EPS, accelerate=False)
    b = formal_single(sp, layout, size, seed, 0, EPS, accelerate=True)
    same = a["ls"] == b["ls"] and a["perm"] == b["perm"] and a["evals"] == b["evals"]
    return {"case": f"单机 {layout} 每机 {size // 5} 点", "same": same, "plain_s": a["secs"], "fast_s": b["secs"],
            "exact_plain": a["exact"], "exact_fast": b["exact"], "pruned": b["pruned"], "lambda": b["lambda"]}


def speed_fleet(args) -> dict:
    layout, seed = args
    sp = load_scheme1_params(CONFIG)
    inst, groups = make_instance(layout, 50, 5, seed, sp)
    out = {}
    for acc in (False, True):
        t0 = time.perf_counter()
        out[acc] = (solve_fleet(inst, groups, EPS, SearchConfig(accelerate=acc), tag=(layout, seed, EPS)),
                    time.perf_counter() - t0)
    (a, ta), (b, tb) = out[False], out[True]
    same = a.routes == b.routes and a.objective == b.objective and a.stats["accepted"] == b.stats["accepted"]
    return {"case": f"机队 {layout} 5 机 50 点", "same": same, "plain_s": ta, "fast_s": tb,
            "exact_plain": a.stats["exact"], "exact_fast": b.stats["exact"], "pruned": b.stats["pruned"],
            "lambda": b.stats["lambda"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=Path("outputs/scheme1/algo"))
    a = ap.parse_args()
    jobs = ([(regress_single, (lay, size, 0, 0)) for lay in ("sector", "fireline") for size in (50, 65, 80)]
            + [(regress_fleet, (lay, s)) for lay in ("sector", "fireline") for s in (0, 1)]
            + [(speed_single, (lay, size, 1)) for lay in ("sector", "fireline") for size in (50, 65, 80)]
            + [(speed_fleet, (lay, 2)) for lay in ("sector", "fireline")])
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(fn, arg) for fn, arg in jobs]
        res = [f.result() for f in futs]
    reg = [r for r in res if "ref" in r]
    spd = [r for r in res if "plain_s" in r]
    lines = [f"回归（代入检验脚本常数，与第三道检验逐位比对，ε = {EPS}）：{sum(r['same'] for r in reg)}/{len(reg)} 例一致"]
    lines += [f"  {r['case']}：{'一致' if r['same'] else '不一致'}（检验 {r['ref']:.12f}，正式实现 {r['got']:.12f}）" for r in reg]
    lines.append(f"提速（冻结参数，ε = {EPS}，加速与不加速结果{'全部相同' if all(r['same'] for r in spd) else '存在差异'}）")
    for r in spd:
        lines.append(f"  {r['case']}：不加速 {r['plain_s']:.1f} s，加速 {r['fast_s']:.1f} s，提速 {r['plain_s'] / r['fast_s']:.1f} 倍；"
                     f"精确动态规划 {r['exact_plain']} → {r['exact_fast']} 次，下界剪掉 {r['pruned']} 个候选，λ 动态规划 {r['lambda']} 次")
    lines.append(f"  合计：不加速 {sum(r['plain_s'] for r in spd):.0f} s，加速 {sum(r['fast_s'] for r in spd):.0f} s，"
                 f"提速 {sum(r['plain_s'] for r in spd) / sum(r['fast_s'] for r in spd):.1f} 倍；"
                 f"各例提速中位 {statistics.median(r['plain_s'] / r['fast_s'] for r in spd):.1f} 倍")
    lines.append(f"总耗时 {time.perf_counter() - t0:.0f} s（{a.workers} 进程）")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "algo_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "algo_check_out.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    if not all(r["same"] for r in res):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
