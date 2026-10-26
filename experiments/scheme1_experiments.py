"""方案一论文实验 E1–E3（实验规划 29_ 第 2 节）：分片运行、汇总统计与出图

- E1 主对比：N ∈ {30, 40, 50, 60, 70, 80}，5 架机，火线与扇形布点，ε ∈ {0.1, 0.25}，种子 100–119，共 480 个实例；
  B0–B4、P1、P2 与逐份下界，P2 每次抽样记录 30 对下界与精确值
- E2 AoI–时长折中：N = 50，两种布点，ε ∈ {0, 0.05, 0.1, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0}；B0、B2、P1、P2、
  往返方案（不受预算约束）与下界。ε = 0.1、0.25 的实例与 E1 相同，汇总时取 E1 的结果，不重复运行
- E3 消融：N ∈ {50, 80} 的 E1 实例（160 个）上另跑 B2R（随机方向的两阶段）、P2A 与 P2N（加速开、关，先后运行，
  结果须与 E1 的 P2 完全相同，只用于计时）、P2D（最后一站只能回基地）；B1、B2、P1、P2 取 E1 的结果配对比较

用法：
  python experiments/scheme1_experiments.py list --shards E1=10,E2=11,E3=19
  python experiments/scheme1_experiments.py shard --exp E1 --shard 0 --shards 10 --workers 4 --out 目录
  python experiments/scheme1_experiments.py summary --inputs 目录 --out 目录
  python experiments/scheme1_experiments.py smoke --out 目录     （本地冒烟：每个实验取少量实例走完全流程）
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from uav_mec.scheme1 import METHODS, load_scheme1_params, make_instance, run_methods, summary_rows  # noqa: E402

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
M_UAV = 5
SEEDS = tuple(range(100, 120))           # 评估实例的种子，与检验（0–3）、冒烟（97–99）分开
LAYOUTS = ("fireline", "sector")
E1_SIZES = (30, 40, 50, 60, 70, 80)
E1_EPS = (0.1, 0.25)
E2_N = 50
E2_EPS = (0.0, 0.05, 0.1, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0)
E3_SIZES = (50, 80)
LB_SAMPLES = 30                           # E1 中 P2 每次抽样记录的下界与精确值对数（X8 图）
EXP_METHODS = {"E1": METHODS, "E2": ("B0", "B2", "P1", "P2", "PP"), "E3": ("B2R", "P2A", "P2N", "P2D")}


def jobs(exp: str, seeds=SEEDS, sizes=None, eps_list=None) -> list[tuple]:
    """一个实验的全部运行单元 (实验, 布点, N, 种子, ε)

    E2 跳过与 E1 相同的 ε（0.1、0.25），E3 只含 N ∈ {50, 80}；sizes、eps_list 只在冒烟测试中用来缩小范围
    """
    if exp == "E1":
        sizes, eps_list = sizes or E1_SIZES, eps_list or E1_EPS
    elif exp == "E2":
        sizes, eps_list = sizes or (E2_N,), [e for e in (eps_list or E2_EPS) if e not in E1_EPS]
    elif exp == "E3":
        sizes, eps_list = sizes or E3_SIZES, eps_list or E1_EPS
    else:
        raise ValueError(exp)
    return [(exp, lay, n, s, e) for lay in LAYOUTS for n in sizes for e in eps_list for s in seeds]


def est_cost(job: tuple) -> float:
    """运行单元的相对耗时估计，只用于把实例均匀分到各分片（不影响结果）

    依据本地实测（种子 100）：ε 越大停靠组合越多、下界越难剪枝（火线 N = 50 时 ε = 1.0 比 0.1 慢约 10 倍，
    扇形约 4 倍），扇形一般比火线慢；规模的影响因实例而异，取平方。E3 每个实例要跑三次本文方法，其中不加速的一次约慢一倍
    """
    exp, layout, n, _, eps = job
    c = (n / 50) ** 2 * (1 + 10 * eps ** 1.5) * (3.0 if layout == "sector" else 1.0)
    return c * (4.0 if exp == "E3" else 1.0)


def shard_jobs(exp: str, shard: int, shards: int) -> list[tuple]:
    """第 shard 个分片的运行单元：按估计耗时从大到小排序后蛇形分配，各分片总量接近"""
    order = sorted(jobs(exp), key=lambda j: (-est_cost(j), j))
    out = []
    for i, j in enumerate(order):
        r = i % (2 * shards)
        if (r if r < shards else 2 * shards - 1 - r) == shard:
            out.append(j)
    return out


def run_job(job: tuple) -> dict:
    """运行一个单元：生成实例并运行该实验的方法，返回带元数据的记录"""
    exp, layout, n, seed, eps = job
    inst, groups = make_instance(layout, n, M_UAV, seed, load_scheme1_params(str(CONFIG)))
    t0 = time.perf_counter()
    rec = run_methods(inst, groups, eps, methods=EXP_METHODS[exp], tag=(layout, n, M_UAV, seed, eps),
                      lb_samples=LB_SAMPLES if exp == "E1" else 0)
    rec["meta"] = {"exp": exp, "layout": layout, "n": n, "m": M_UAV, "seed": seed, "eps": eps}
    rec["job_secs"] = time.perf_counter() - t0
    return rec


def record_name(meta: dict) -> str:
    return "{exp}_{layout}_n{n}_s{seed}_e{eps}".format(**meta)


def run_jobs(job_list: list[tuple], out: Path, workers: int, log_name: str) -> list[dict]:
    """并行运行一组单元，逐个写记录 JSON，并写汇总行 CSV 与耗时日志

    :return: 汇总行
    """
    from scheme1_plots import write_rows

    (out / "records").mkdir(parents=True, exist_ok=True)
    order = sorted(job_list, key=lambda j: -est_cost(j))   # 大的先跑，进程池尾部更均衡
    rows, log = [], []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max(1, workers)) as ex:
        for rec in ex.map(run_job, order):
            meta = rec["meta"]
            (out / "records" / f"{record_name(meta)}.json").write_text(json.dumps(rec, ensure_ascii=False),
                                                                     encoding="utf-8")
            rows += summary_rows(rec, meta)
            log.append(f"{record_name(meta)}\t{rec['job_secs']:.1f}")
    log.append(f"total\t{time.perf_counter() - t0:.1f}")
    write_rows(out / f"rows_{log_name}.csv", rows)
    (out / f"log_{log_name}.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    return rows


# ---------------------------------------------------------------------------
# 汇总：读取记录、检查、配对统计
# ---------------------------------------------------------------------------

def load_records(inputs) -> dict:
    """读取各分片的记录：{(实验, 布点, N, 种子, ε): 记录}；目录下任意层的 records/*.json 都会读到"""
    recs = {}
    for d in inputs:
        for p in sorted(Path(d).rglob("records/*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            m = rec["meta"]
            recs[(m["exp"], m["layout"], m["n"], m["seed"], m["eps"])] = rec
    return recs


def rel_tol(x: float) -> float:
    return 1e-9 * max(1.0, abs(x))


def paired(base: list[float], prop: list[float]) -> dict:
    """配对比较：prop 相对 base 的改善 100·(base − prop)/base（%）

    :return: 对数、改善的中位数与四分位数、均值与 95% 置信区间半宽、优/平/劣的实例数、Wilcoxon 符号秩检验的 p 值
             （差全为零时 p 记为 1）
    """
    from scheme1_plots import mean_ci
    from scipy.stats import wilcoxon

    imp = [100.0 * (b - p) / b for b, p in zip(base, prop)]
    q1, med, q3 = statistics.quantiles(imp, n=4, method="inclusive") if len(imp) >= 2 else (imp[0],) * 3
    mean, ci = mean_ci(imp)
    wins = sum(p < b - rel_tol(b) for b, p in zip(base, prop))
    ties = sum(abs(p - b) <= rel_tol(b) for b, p in zip(base, prop))
    if all(b == p for b, p in zip(base, prop)):
        pv = 1.0           # 差全为零，检验无定义
    else:
        try:
            pv = float(wilcoxon(base, prop).pvalue)
        except ValueError:
            pv = 1.0
        if math.isnan(pv):
            pv = 1.0
    return {"pairs": len(imp), "median": med, "q1": q1, "q3": q3, "mean": mean, "ci": ci,
            "wins": wins, "ties": ties, "losses": len(imp) - wins - ties, "p": pv}


def paired_line(name: str, st: dict) -> str:
    return (f"  {name}：中位 {st['median']:.1f}%（四分位 {st['q1']:.1f}～{st['q3']:.1f}），均值 {st['mean']:.1f} ± {st['ci']:.1f}%，"
            f"优/平/劣 {st['wins']}/{st['ties']}/{st['losses']}，Wilcoxon p = {st['p']:.1e}")


def obj_of(rec: dict, m: str) -> float:
    return rec["methods"][m]["summary"]["obj"]


def check_common(recs: list[dict], methods) -> list[str]:
    """通用检查：方案可行（往返方案不受预算约束，除外）且每个观测点恰好分配一次"""
    bad = [(record_name(r["meta"]), m) for r in recs for m in methods if m != "PP"
           and not (r["methods"][m]["summary"]["feasible"] and r["methods"][m]["summary"]["assigned_once"])]
    return [f"不可行或分配有误：{len(bad)} 个 {bad[:5]}"] if bad else []


def check_order(recs: list[dict]) -> list[str]:
    """E1、E2 的序关系：同一航线上两阶段的停靠最优（B2 ≤ B0、B1、B4），本文方法不劣于起点（P2 ≤ P1 ≤ B2）"""
    pairs = [("B2", "B0"), ("B2", "B1"), ("B2", "B4"), ("P1", "B2"), ("P2", "P1")]
    bad = []
    for r in recs:
        for a, b in pairs:
            if a in r["methods"] and b in r["methods"] and obj_of(r, a) > obj_of(r, b) + rel_tol(obj_of(r, b)):
                bad.append((record_name(r["meta"]), a, b))
    return [f"序关系不成立：{len(bad)} 处 {bad[:5]}"] if bad else []


def fingerprint(rows: list[dict]) -> str:
    from scheme1_plots import result_fingerprint

    return result_fingerprint(rows)


def table_lines(rows: list[dict], methods, key: str = "n", metric: str = "norm_aoi", fmt: str = "{:7.4f}",
                with_lb: bool = True) -> list[str]:
    """均值表：每个分组一行、每种方法一列（可加逐份下界列）"""
    from scheme1_plots import select

    head = f"  {key:<5}" + "".join(f"{m:>9}" for m in methods) + ("       LB" if with_lb else "")
    out = [head]
    for g in sorted({r[key] for r in rows}):
        sel = [r for r in rows if r[key] == g]
        cells = []
        for m in methods:
            vals = [r[metric] for r in select(sel, method=m)]
            cells.append(f"{fmt.format(statistics.fmean(vals)):>9}" if vals else f"{'—':>9}")
        lb = ""
        if with_lb:
            lbs = [r["lb_norm"] for r in sel if r["method"] == sel[0]["method"]]
            lb = f"{statistics.fmean(lbs):9.4f}"
        out.append(f"  {g!s:<5}" + "".join(cells) + lb)
    return out


E1_METRICS = ("norm_aoi", "mean_aoi_s", "p95_aoi_s", "max_aoi_s", "on_time_rate", "norm_overtime", "max_mission_min",
              "mission_increase_pct", "battery_binding_frac", "energy_kj", "distance_km", "stops_per_uav", "secs")


def means_rows(rows: list[dict], keys, methods, metrics=E1_METRICS) -> list[dict]:
    """各分组、各方法的指标均值与 95% 置信区间半宽（列名后缀 _ci），供 CSV 与论文表格"""
    from scheme1_plots import mean_ci

    out = []
    for g in sorted({tuple(r[k] for k in keys) for r in rows}):
        sel = [r for r in rows if tuple(r[k] for k in keys) == g]
        for m in methods:
            ms = [r for r in sel if r["method"] == m]
            if not ms:
                continue
            row = dict(zip(keys, g), method=m, count=len(ms))
            for met in metrics:
                row[met], row[met + "_ci"] = mean_ci([float(r[met]) for r in ms])
            out.append(row)
    return out


def default_scene_lines(rows: list[dict], methods) -> list[str]:
    """默认场景（N = 50，ε = 0.1）各方法的主要指标均值"""
    cols = [("norm_aoi", "归一化AoI", "{:.4f}"), ("mean_aoi_s", "平均AoI s", "{:.0f}"), ("p95_aoi_s", "P95 s", "{:.0f}"),
            ("on_time_rate", "按时%", "{:.1%}"), ("max_mission_min", "最长min", "{:.1f}"),
            ("mission_increase_pct", "时长+%", "{:.1f}"), ("energy_kj", "能耗kJ", "{:.0f}"),
            ("stops_per_uav", "停靠/机", "{:.1f}"), ("secs", "耗时s", "{:.1f}")]
    out = ["  方法 " + "".join(f"{c[1]:>11}" for c in cols)]
    for m in methods:
        ms = [r for r in rows if r["method"] == m]
        if ms:
            out.append(f"  {m:<4} " + "".join(f"{c[2].format(statistics.fmean(r[c[0]] for r in ms)):>11}" for c in cols))
    return out


def summarize_e1(recs: dict, expected: int, out: Path) -> tuple[list[str], list[str], list[dict], list[dict]]:
    """E1：均值表、P2 相对各方法的配对比较、与下界的差距、默认场景全部指标

    :return: (摘要行, 问题列表, 汇总行, 记录列表)
    """
    from scheme1_plots import write_rows

    e1 = [r for k, r in sorted(recs.items()) if k[0] == "E1"]
    rows = [row for r in e1 for row in summary_rows(r, r["meta"])]
    problems = check_common(e1, METHODS) + check_order(e1)
    bad_lb = sum(lb > ex + rel_tol(ex) for r in e1 for _, lb, ex in r["methods"]["P2"].get("lb_pairs", []))
    if bad_lb:
        problems.append(f"下界样本超过精确值：{bad_lb} 对")
    if len(e1) != expected:
        problems.append(f"E1 实例数 {len(e1)}/{expected}")
    lines = [f"## E1 主对比：{len(e1)}/{expected} 个实例，结果指纹 {fingerprint(rows)}"]
    paired_rows = []
    order = ("P2", "P1", "B2", "B1", "B3", "B4", "B0")
    for lay in LAYOUTS:
        for eps in E1_EPS:
            insts = [r for r in e1 if r["meta"]["layout"] == lay and r["meta"]["eps"] == eps]
            if not insts:
                continue
            sel = [r for r in rows if r["layout"] == lay and r["eps"] == eps]
            lines.append(f"{lay}  ε = {eps}：平均归一化 AoI（各规模 {len(insts) // len({r['meta']['n'] for r in insts})} 个种子的均值）")
            lines += table_lines(sel, order)
            lines.append("  本文方法 P2 相对各方法的改善（各规模合并，按实例配对）：")
            for m in order[1:]:
                st = paired([obj_of(r, m) for r in insts], [obj_of(r, "P2") for r in insts])
                lines.append(paired_line(f"相对 {m}", st))
                paired_rows.append(dict(layout=lay, eps=eps, n="all", method=m, **st))
                for n in sorted({r["meta"]["n"] for r in insts}):
                    sub = [r for r in insts if r["meta"]["n"] == n]
                    paired_rows.append(dict(layout=lay, eps=eps, n=n, method=m,
                                            **paired([obj_of(r, m) for r in sub], [obj_of(r, "P2") for r in sub])))
            gap = [100 * (r["methods"]["P2"]["summary"]["norm_aoi"] / r["features"]["lb_norm"] - 1) for r in insts]
            lines.append(f"  P2 与逐份下界的差距：中位 {statistics.median(gap):.1f}%，最大 {max(gap):.1f}%")
    for lay in LAYOUTS:
        sel = [r for r in rows if r["layout"] == lay and r["eps"] == 0.1 and r["n"] == 50]
        if sel:
            lines.append(f"{lay}  N = 50  ε = 0.1：主要指标（均值）")
            lines += default_scene_lines(sel, order)
    write_rows(out / "E1_rows.csv", rows)
    write_rows(out / "E1_means.csv", means_rows(rows, ("layout", "eps", "n"), order))
    write_rows(out / "E1_paired.csv", paired_rows)
    return lines, problems, rows, e1


def summarize_e2(recs: dict, expected: int, out: Path) -> tuple[list[str], list[str], list[dict], dict]:
    """E2：各 ε 下的均值、P2 相对 B2 的改善、最大任务时长增幅、电池起约束的比例、往返方案所需的 ε

    ε = 0.1、0.25 的实例取自 E1（只用 B0、B2、P1、P2）
    :return: (摘要行, 问题列表, 汇总行, 每个 (布点, 种子) 的往返方案结果)
    """
    from scheme1_plots import write_rows

    e2 = [r for k, r in sorted(recs.items()) if k[0] == "E2"]
    shared = [r for k, r in sorted(recs.items()) if k[0] == "E1" and k[2] == E2_N and k[4] in E1_EPS
              and k[3] in {r2["meta"]["seed"] for r2 in e2}]
    keep = ("B0", "B2", "P1", "P2")
    rows = [row for r in e2 for row in summary_rows(r, r["meta"]) if row["method"] in keep]
    rows += [row for r in shared for row in summary_rows(r, dict(r["meta"], exp="E2")) if row["method"] in keep]
    problems = check_common(e2, EXP_METHODS["E2"]) + check_order(e2)
    if len(e2) != expected:
        problems.append(f"E2 实例数 {len(e2)}/{expected}")
    battery = load_scheme1_params(str(CONFIG)).battery_j
    pp = {}
    for r in e2:
        key = (r["meta"]["layout"], r["meta"]["seed"])
        o = r["methods"]["PP"]
        pp.setdefault(key, {"layout": key[0], "seed": key[1], "norm_aoi": o["summary"]["norm_aoi"],
                            "lb_norm": r["features"]["lb_norm"], "eps_needed": o["summary"]["mission_increase_pct"] / 100,
                            "battery_ok": all(u["energy_j"] <= battery + 1e-6 for u in o["uavs"] if u["n"])})
    pp_bad = [k for k, v in pp.items() if abs(v["norm_aoi"] - v["lb_norm"]) > rel_tol(v["lb_norm"])]
    if pp_bad:
        problems.append(f"往返方案未达到逐份下界：{pp_bad[:5]}")
    lines = [f"## E2 AoI–时长折中：另跑 {len(e2)}/{expected} 个实例，ε = 0.1、0.25 取自 E1；结果指纹 {fingerprint(rows)}"]
    for lay in LAYOUTS:
        sel = [r for r in rows if r["layout"] == lay]
        if not sel:
            continue
        lines.append(f"{lay}：平均归一化 AoI 随 ε 的变化（N = {E2_N}）")
        lines += table_lines(sel, ("P2", "P1", "B2", "B0"), key="eps")
        lines.append("  ε      P2 相对 B2 的改善（中位，p 值）   P2 最长任务时长相对 T̂   P2 中电池起约束的机比例")
        for eps in sorted({r["eps"] for r in sel}):
            insts = [r for r in e2 + shared if r["meta"]["layout"] == lay and r["meta"]["eps"] == eps]
            st = paired([obj_of(r, "B2") for r in insts], [obj_of(r, "P2") for r in insts])
            mi = statistics.fmean(r["methods"]["P2"]["summary"]["mission_increase_pct"] for r in insts)
            bb = statistics.fmean(r["methods"]["P2"]["summary"]["battery_binding_frac"] for r in insts)
            lines.append(f"  {eps:<5}  {st['median']:6.1f}%（p = {st['p']:.1e}）            {mi:+6.1f}%"
                         f"                  {100 * bb:5.1f}%")
        v = [x for k, x in pp.items() if k[0] == lay]
        if v:
            lines.append(f"  往返方案（每份数据都达到逐份下界）所需的 ε：均值 {statistics.fmean(x['eps_needed'] for x in v):.2f}，"
                         f"最大 {max(x['eps_needed'] for x in v):.2f}；电池够用的实例 {sum(x['battery_ok'] for x in v)}/{len(v)}")
    write_rows(out / "E2_rows.csv", rows)
    write_rows(out / "E2_means.csv", means_rows(rows, ("layout", "eps"), ("P2", "P1", "B2", "B0")))
    write_rows(out / "E2_pingpong.csv", list(pp.values()))
    return lines, problems, rows, pp


def summarize_e3(recs: dict, expected: int, out: Path) -> tuple[list[str], list[str], list[dict], list[tuple]]:
    """E3：消融表、各组件贡献的配对比较、加速的计时与一致性

    :return: (摘要行, 问题列表, 汇总行（E1 的 P2、P1、B2、B1 与 E3 的 B2R、P2D、P2A、P2N）, (E3 记录, E1 记录) 列表)
    """
    from scheme1_plots import write_rows

    e3 = [r for k, r in sorted(recs.items()) if k[0] == "E3"]
    problems = check_common(e3, EXP_METHODS["E3"])
    if len(e3) != expected:
        problems.append(f"E3 实例数 {len(e3)}/{expected}")
    joined = []
    for r in e3:
        m = r["meta"]
        base = recs.get(("E1", m["layout"], m["n"], m["seed"], m["eps"]))
        if base is None:
            problems.append(f"缺少对应的 E1 实例：{record_name(m)}")
            continue
        joined.append((r, base))
    mism = [record_name(r["meta"]) for r, b in joined
            if not (obj_of(r, "P2A") == obj_of(b, "P2") == obj_of(r, "P2N")
                    and r["methods"]["P2A"]["routes"] == b["methods"]["P2"]["routes"] == r["methods"]["P2N"]["routes"])]
    if mism:
        problems.append(f"P2A、P2N 与 E1 的 P2 不一致：{len(mism)} 个 {mism[:5]}")
    depot_bad = [record_name(r["meta"]) for r, _ in joined
                 if not all(st[-1][1] == -1 for st in r["methods"]["P2D"]["stops"] if st)]
    if depot_bad:
        problems.append(f"P2D 的最后一站不在基地：{depot_bad[:5]}")
    b2r_bad = [record_name(r["meta"]) for r, b in joined if obj_of(b, "B2") > obj_of(r, "B2R") + rel_tol(obj_of(r, "B2R"))]
    if b2r_bad:
        problems.append(f"B2 劣于随机方向的 B2R：{b2r_bad[:5]}")
    rows = []
    for r, b in joined:
        meta = dict(r["meta"])
        rows += [row for row in summary_rows(b, meta) if row["method"] in ("P2", "P1", "B2", "B1")]
        rows += summary_rows(r, meta)
    lines = [f"## E3 消融：{len(e3)}/{expected} 个实例（B1、B2、P1、P2 取自 E1）；结果指纹 {fingerprint(rows)}"]
    order = ("P2", "P2D", "P1", "B2", "B2R", "B1")
    for lay in LAYOUTS:
        for eps in E1_EPS:
            sel = [x for x in rows if x["layout"] == lay and x["eps"] == eps]
            if sel:
                lines.append(f"{lay}  ε = {eps}：平均归一化 AoI")
                lines += table_lines(sel, order)
    comps = [("精确停靠（B1 → B2）", "B1", "B2"), ("顺序优化（B2 → P1）", "B2", "P1"), ("跨机分配（P1 → P2）", "P1", "P2"),
             ("选方向（B2R → B2）", "B2R", "B2"), ("终点规则（P2D → P2）", "P2D", "P2")]
    comp_rows = []

    def obj(pair, m):
        r, b = pair
        return obj_of(r, m) if m in r["methods"] else obj_of(b, m)

    for lay in LAYOUTS:
        sub = [p for p in joined if p[0]["meta"]["layout"] == lay]
        if not sub:
            continue
        lines.append(f"{lay}：各组件的贡献（N 与 ε 合并，按实例配对，后者相对前者的改善）")
        for name, a, b in comps:
            st = paired([obj(p, a) for p in sub], [obj(p, b) for p in sub])
            lines.append(paired_line(name, st))
            comp_rows.append(dict(layout=lay, component=name, base=a, prop=b, **st))
    lines.append("加速（时间价格筛选 + 前缀复用）：同一实例上先后运行，结果须完全相同")
    acc_rows = []
    for lay in LAYOUTS:
        for n in sorted({p[0]["meta"]["n"] for p in joined}):
            sub = [p[0] for p in joined if p[0]["meta"]["layout"] == lay and p[0]["meta"]["n"] == n]
            if not sub:
                continue
            ta = [r["methods"]["P2A"]["secs"] for r in sub]
            tn = [r["methods"]["P2N"]["secs"] for r in sub]
            sp = [b / a for a, b in zip(ta, tn)]
            ea = [r["methods"]["P2A"]["stats"]["exact"] for r in sub]
            en = [r["methods"]["P2N"]["stats"]["exact"] for r in sub]
            lines.append(f"  {lay} N = {n}：求解时间中位 {statistics.median(tn):.1f} s → {statistics.median(ta):.1f} s，"
                         f"提速中位 {statistics.median(sp):.2f} 倍（{min(sp):.2f}～{max(sp):.2f}），"
                         f"精确动态规划次数中位 {statistics.median(en):.0f} → {statistics.median(ea):.0f}")
            acc_rows.append(dict(layout=lay, n=n, instances=len(sub), secs_plain_median=statistics.median(tn),
                                 secs_fast_median=statistics.median(ta), speedup_median=statistics.median(sp),
                                 speedup_min=min(sp), speedup_max=max(sp), exact_plain_median=statistics.median(en),
                                 exact_fast_median=statistics.median(ea)))
    lines.append(f"  一致性：P2A、P2N 与 E1 的 P2 完全相同的实例 {len(joined) - len(mism)}/{len(joined)}")
    write_rows(out / "E3_rows.csv", rows)
    write_rows(out / "E3_means.csv", means_rows(rows, ("layout", "eps", "n"), order + ("P2A", "P2N")))
    write_rows(out / "E3_components.csv", comp_rows)
    write_rows(out / "E3_acceleration.csv", acc_rows)
    return lines, problems, rows, joined


# ---------------------------------------------------------------------------
# 出图（编号对应实验规划 29_ 第 5.2 节）
# ---------------------------------------------------------------------------

def figures_e1(rows: list[dict], recs: list[dict], d: Path, lang: str) -> list[Path]:
    """E1 的图：F4–F9（火线 ε = 0.1）、F18–F19（扇形）、X1–X5 与 F11（ε = 0.25）、F10、X6、F2、X8、F13 右图与 X10，
    以及一个火线实例（N = 50、ε = 0.1、最小种子）的 F20 航线图、X15 时间线、X9 各机任务时长"""
    import scheme1_plots as sp

    files: list[Path] = []
    main = sp.select(rows, layout="fireline", eps=0.1)
    if main:
        for fid, metric in (("F4", "norm_aoi"), ("F5", "mean_aoi_s"), ("F6", "on_time_rate"), ("F7", "max_mission_min"),
                            ("F8", "energy_kj"), ("F9", "stops_per_uav")):
            files += sp.save(sp.fig_metric(main, metric, lang), d, f"E1_{fid}_{metric}_fireline_eps0.1")
    sec = sp.select(rows, layout="sector", eps=0.1)
    if sec:
        files += sp.save(sp.fig_metric(sec, "norm_aoi", lang), d, "E1_F18_norm_aoi_sector_eps0.1")
        files += sp.save(sp.fig_metric(sec, "on_time_rate", lang), d, "E1_F19_on_time_rate_sector_eps0.1")
    hi = sp.select(rows, layout="fireline", eps=0.25)
    if hi:
        for i, metric in enumerate(("norm_aoi", "mean_aoi_s", "on_time_rate", "max_mission_min", "energy_kj"), start=1):
            files += sp.save(sp.fig_metric(hi, metric, lang), d, f"E1_X{i}_{metric}_fireline_eps0.25")
        files += sp.save(sp.fig_metric(hi, "norm_aoi", lang, kind="line", methods=("P2", "P1", "B2", "B1")), d,
                         "E1_F11_norm_aoi_line_fireline_eps0.25")
    case_recs = [r for r in recs if r["meta"]["layout"] == "fireline" and r["meta"]["eps"] == 0.1 and r["meta"]["n"] == 50]
    if case_recs:
        files += sp.save(sp.fig_aoi_box(case_recs, lang), d, "E1_F10_aoi_box_fireline_n50_eps0.1")
        files += sp.save(sp.fig_aoi_cdf(case_recs, lang), d, "E1_X6_aoi_cdf_fireline_n50_eps0.1")
        files += sp.save(sp.fig_convergence(case_recs, lang), d, "E1_F2_convergence_fireline_n50_eps0.1")
        case = min(case_recs, key=lambda r: r["meta"]["seed"])
        files += sp.save(sp.fig_route_maps(case, lang), d, "E1_F20_route_maps_case")
        files += sp.save(sp.fig_timeline(case, lang), d, "E1_X15_timeline_case")
        files += sp.save(sp.fig_uav_mission(case, lang), d, "E1_X9_uav_mission_case")
    if recs:
        files += sp.save(sp.fig_lb_ratio(recs, lang), d, "E1_X8_lb_ratio")
    low = sp.select(rows, eps=0.1)
    if low:
        files += sp.save(sp.fig_gain_scatter(low, lang), d, "E1_F13b_X10_gain_scatter_eps0.1")
    return files


def _gain_by_eps(rows: list[dict], lay: str) -> tuple[list, list, list, list]:
    """某布点下各 ε 的 P2 相对 B2 改善（%）：(ε, 中位数, 下四分位, 上四分位)"""
    by: dict = {}
    for r in rows:
        if r["layout"] == lay and r["method"] in ("P2", "B2"):
            by.setdefault((r["eps"], r["seed"]), {})[r["method"]] = r["obj"]
    xs, med, lo, hi = [], [], [], []
    for eps in sorted({k[0] for k in by}):
        g = [100 * (v["B2"] - v["P2"]) / v["B2"] for k, v in by.items() if k[0] == eps and len(v) == 2]
        q = statistics.quantiles(g, n=4, method="inclusive") if len(g) >= 2 else (g[0],) * 3
        xs.append(eps)
        lo.append(q[0])
        med.append(q[1])
        hi.append(q[2])
    return xs, med, lo, hi


def _layout_lines(series: dict, lang: str, ylabel: str, band: dict | None = None):
    """两种布点各一条线（本文方法的颜色，圆点实线 = 火线、方点虚线 = 扇形），可加四分位色带"""
    import scheme1_plots as sp
    from matplotlib.lines import Line2D

    fig, ax = sp.new_fig()
    handles = []
    for lay, mk, ls in (("fireline", "o", "-"), ("sector", "s", (0, (3, 1.5)))):
        if lay not in series:
            continue
        xs, ys = series[lay]
        if band and lay in band:
            ax.fill_between(xs, band[lay][0], band[lay][1], color=sp.COLORS["P2"], alpha=0.12, linewidth=0, zorder=1)
        ax.plot(xs, ys, color=sp.COLORS["P2"], marker=mk, linestyle=ls, markerfacecolor=sp.INK["surface"],
                markeredgecolor=sp.COLORS["P2"], markeredgewidth=0.9, zorder=3)
        handles.append(Line2D([], [], color=sp.COLORS["P2"], marker=mk, linestyle=ls, markerfacecolor=sp.INK["surface"],
                              markeredgecolor=sp.COLORS["P2"], label=sp.label(lang, lay)))
    ax.set_xlabel(sp.label(lang, "eps"))
    ax.set_ylabel(ylabel)
    sp.legend_top(fig, handles)
    return fig


def figures_e2(rows: list[dict], d: Path, lang: str) -> list[Path]:
    """E2 的图：每种布点的 F12（归一化 AoI 随 ε）与最长任务时长增幅；F13 左图（改善随 ε）；电池起约束的比例"""
    import scheme1_plots as sp

    files: list[Path] = []
    for lay in LAYOUTS:
        sel = [r for r in rows if r["layout"] == lay]
        if not sel:
            continue
        groups, series = sp.metric_series(sel, "norm_aoi", "eps", methods=("P2", "B2", "B0"))
        lb = [statistics.fmean(r["lb_norm"] for r in sel if r["eps"] == g and r["method"] == "P2") for g in groups]
        fig, ax = sp.new_fig()
        handles = sp.line_chart(ax, groups, series, lang, ref=lb, ref_key="LB")
        ax.set_xlabel(sp.label(lang, "eps"))
        ax.set_ylabel(sp.label(lang, "norm_aoi"))
        sp.legend_top(fig, handles)
        files += sp.save(fig, d, f"E2_F12_tradeoff_{lay}")
        groups, series = sp.metric_series(sel, "mission_increase_pct", "eps", methods=("P2", "B2"))
        fig, ax = sp.new_fig()
        handles = sp.line_chart(ax, groups, series, lang, ref=[100 * g for g in groups], ref_key="budget")
        ax.set_xlabel(sp.label(lang, "eps"))
        ax.set_ylabel(sp.label(lang, "mission_increase_pct"))
        sp.legend_top(fig, handles)
        files += sp.save(fig, d, f"E2_mission_increase_{lay}")
    gains, bands, batt = {}, {}, {}
    for lay in LAYOUTS:
        xs, med, lo, hi = _gain_by_eps(rows, lay)
        if xs:
            gains[lay], bands[lay] = (xs, med), (lo, hi)
            sel = [r for r in rows if r["layout"] == lay and r["method"] == "P2"]
            batt[lay] = (xs, [100 * statistics.fmean(r["battery_binding_frac"] for r in sel if r["eps"] == e) for e in xs])
    if gains:
        files += sp.save(_layout_lines(gains, lang, sp.label(lang, "gain"), bands), d, "E2_F13a_gain_vs_eps")
        files += sp.save(_layout_lines(batt, lang, sp.label(lang, "battery_binding_frac")), d, "E2_battery_binding")
    return files


def figures_e3(rows: list[dict], joined: list[tuple], d: Path, lang: str) -> list[Path]:
    """E3 的图：F14、F15（消融：归一化 AoI 与按时送达率）与 F3（加速前后的求解时间、精确动态规划次数）"""
    import scheme1_plots as sp

    files: list[Path] = []
    order = ("P2", "P2D", "P1", "B2", "B2R", "B1")
    for lay in LAYOUTS:
        for eps in E1_EPS:
            sel = [x for x in rows if x["layout"] == lay and x["eps"] == eps]
            if sel:
                files += sp.save(sp.fig_metric(sel, "norm_aoi", lang, methods=order), d,
                                 f"E3_F14_ablation_norm_aoi_{lay}_eps{eps}")
                files += sp.save(sp.fig_metric(sel, "on_time_rate", lang, methods=order), d,
                                 f"E3_F15_ablation_on_time_{lay}_eps{eps}")
    cases = sorted({(p[0]["meta"]["layout"], p[0]["meta"]["n"]) for p in joined})
    if cases:
        short = {"zh": {"fireline": "火线", "sector": "扇形"}, "en": {"fireline": "Fire", "sector": "Sector"}}[lang]
        groups = [f"{short[lay]} {n}" for lay, n in cases]
        for key, ylabel, fname in (("secs", sp.label(lang, "secs"), "E3_F3_acceleration_time"),
                                   ("exact", sp.label(lang, "exact_calls"), "E3_F3_acceleration_exact_calls")):
            series = {}
            for m in ("P2A", "P2N"):
                series[m] = [[(r["methods"][m]["secs"] if key == "secs" else r["methods"][m]["stats"]["exact"])
                              for r, _ in joined if (r["meta"]["layout"], r["meta"]["n"]) == c] for c in cases]
            fig, ax = sp.new_fig()
            handles = sp.grouped_bars(ax, groups, series, lang, width=0.6)
            ax.set_xlabel(sp.label(lang, "case"))
            ax.set_ylabel(ylabel)
            sp.legend_top(fig, handles)
            files += sp.save(fig, d, fname)
    return files


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def summarize(inputs, out: Path, langs=("zh", "en"), job_lists: dict | None = None) -> bool:
    """汇总全部分片：三个实验的表格与检查写进 summary.txt，CSV 与图写进 out；有问题时返回 False"""
    import scheme1_plots as sp

    job_lists = job_lists or {e: jobs(e) for e in ("E1", "E2", "E3")}
    recs = load_records(inputs)
    out.mkdir(parents=True, exist_ok=True)
    l1, p1, r1, e1 = summarize_e1(recs, len(job_lists["E1"]), out)
    l2, p2, r2, _ = summarize_e2(recs, len(job_lists["E2"]), out)
    l3, p3, r3, joined = summarize_e3(recs, len(job_lists["E3"]), out)
    problems = p1 + p2 + p3
    files: list[Path] = []
    for lang in langs:
        sp.setup(lang)
        d = out / "figures" / lang
        files += figures_e1(r1, e1, d, lang) + figures_e2(r2, d, lang) + figures_e3(r3, joined, d, lang)
    lines = l1 + [""] + l2 + [""] + l3 + [""]
    lines.append("检查：" + ("全部通过（实例齐全、方案可行、分配无误、序关系成立、下界样本有效、往返方案达到下界、"
                             "加速前后结果相同、P2D 终点在基地）" if not problems else "；".join(problems)))
    lines.append(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return not problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一论文实验 E1–E3")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="各实验的实例数与分片的估计负载")
    p.add_argument("--shards", default="E1=10,E2=11,E3=19")
    p = sub.add_parser("shard", help="运行一个分片")
    p.add_argument("--exp", choices=("E1", "E2", "E3"), required=True)
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--shards", type=int, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("summary", help="汇总全部分片")
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("smoke", help="本地冒烟：每个实验取少量实例走完运行与汇总")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for item in a.shards.split(","):
            exp, k = item.split("=")
            loads = [sum(est_cost(j) for j in shard_jobs(exp, s, int(k))) for s in range(int(k))]
            print(f"{exp}：{len(jobs(exp))} 个实例，{k} 个分片，估计负载 {min(loads):.1f}～{max(loads):.1f}（合计 {sum(loads):.1f}）")
        return 0
    if a.cmd == "shard":
        js = shard_jobs(a.exp, a.shard, a.shards)
        run_jobs(js, a.out, a.workers, f"{a.exp}_{a.shard}")
        print(f"{a.exp} 分片 {a.shard}/{a.shards}：{len(js)} 个实例完成")
        return 0
    if a.cmd == "summary":
        return 0 if summarize(a.inputs, a.out) else 1
    cfg = {"E1": {"sizes": (30, 50), "seeds": (100, 101)}, "E2": {"seeds": (100, 101), "eps_list": (0.0, 0.35)},
           "E3": {"sizes": (50,), "seeds": (100, 101)}}
    job_lists = {e: jobs(e, **kw) for e, kw in cfg.items()}
    for e, js in job_lists.items():
        run_jobs(js, a.out / "shards" / e, a.workers, f"{e}_smoke")
    return 0 if summarize([a.out / "shards"], a.out / "summary", job_lists=job_lists) else 1


if __name__ == "__main__":
    sys.exit(main())
