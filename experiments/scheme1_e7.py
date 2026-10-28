"""方案一 E7：火线案例（实验规划 29_ 第 2 节 E7；决定与做法见该节"决定与实现细节"）

不另生成、不另求解：从 E1 的记录（标签 scheme1-exp-v1，Actions run 40295745598 的产物）中取火线、N = 50、
5 架机、ε = 0.1 的 20 个实例，按 P2 相对 B2 的改善选两个案例：改善最接近中位数的（典型），
与改善最大的（收益最大，不是典型）。对两个案例出航线图（F20）、逐份时间线（X15）、AoI ÷ δ 的累积分布
与各机任务时长（X9），并汇总各方法的指标；--verify 时用同一冻结代码重算两个案例，目标须与记录逐位相同

用法：
  python experiments/scheme1_e7.py run --e1 E1产物目录 --out 目录 [--verify]
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
LAYOUT = "fireline"
N = 50
M_UAV = 5
EPS = 0.1
SEEDS = tuple(range(100, 120))
SHOWN = ("P2", "B2", "B0")               # 图中比较的方法（29_ E7 的报告要求）
TABLE = ("P2", "P1", "B2", "B0")         # 表中另列 P1，区分机内调整与跨机移动的作用
CASE_NAMES = {"median": "典型（改善最接近中位数）", "max": "收益最大（不是典型）"}


def record_path(e1_dir: Path, seed: int) -> Path:
    """E1 记录文件的路径，命名与 scheme1_experiments.record_name 一致

    :param e1_dir: E1 汇总产物的目录（含 records/）
    :param seed: 种子
    :return: 记录 JSON 的路径
    """
    return e1_dir / "records" / f"E1_{LAYOUT}_n{N}_s{seed}_e{EPS}.json"


def load_case_records(e1_dir: Path, seeds=None) -> dict[int, dict]:
    """读 E1 中火线、N = 50、ε = 0.1 的记录

    :param e1_dir: E1 汇总产物的目录
    :param seeds: 种子，缺省为 SEEDS
    :return: {种子: 记录}
    :raises FileNotFoundError: 缺少某个种子的记录
    """
    return {s: json.loads(record_path(e1_dir, s).read_text(encoding="utf-8")) for s in (seeds or SEEDS)}


def gain(rec: dict) -> float:
    """P2 相对 B2 的改善 100·(B2 − P2)/B2（%）"""
    b, p = rec["methods"]["B2"]["summary"]["obj"], rec["methods"]["P2"]["summary"]["obj"]
    return 100.0 * (b - p) / b


def select_cases(gains: dict[int, float]) -> dict[str, int]:
    """按运行前写定的规则选案例

    :param gains: {种子: P2 相对 B2 的改善 %}
    :return: {"median": 改善最接近中位数的种子, "max": 改善最大的种子}；相差相同时都取种子小的
    """
    med = statistics.median(gains.values())
    dist = {s: abs(g - med) for s, g in gains.items()}
    # 实例数为偶数时，中位数是中间两个的平均，两者离中位数在数学上一样近，浮点误差却可能让任一个略近；
    # 相差在 1e-9 个百分点内视为相同，再按种子取小的，使选择只取决于写定的规则
    best = min(dist.values())
    return {"median": min(s for s in gains if dist[s] <= best + 1e-9),
            "max": min(gains, key=lambda s: (-gains[s], s))}


def uav_of(routes) -> dict[int, int]:
    """观测点 gid → 负责它的机号（从 0 起）"""
    return {g: u for u, r in enumerate(routes) for g in r}


def edges(routes) -> set[tuple[int, int]]:
    """航线的无向航段集合，基地记为 −1；只看访问次序，不含去上传点的绕路

    用来衡量本文方法对两阶段航线改动了多少：两者共有的航段越多，改动越局部
    """
    out = set()
    for r in routes:
        if r:
            out |= {tuple(sorted(p)) for p in pairwise([-1, *r, -1])}
    return out


def mid_route_frac(routes, stops) -> float:
    """在途中（返航前最后一次上传之前）就已上传的数据份数比例

    停靠方案 (k, q) 表示采完第 k 个观测点后去上传点 q 上传此前未送的全部数据；k 等于航线长度的是返航前的
    最后一次上传（在上传点或基地）。每架机途中上传的份数即最后一次途中停靠的 k
    """
    total = sum(len(r) for r in routes)
    mid = sum(max((int(k) for k, _ in st if int(k) < len(r)), default=0) for r, st in zip(routes, stops))
    return mid / total if total else 0.0


def case_rows(rec: dict, seed: int, case: str) -> list[dict]:
    """一个案例上各方法的指标行

    :param rec: E1 记录
    :param seed: 种子
    :param case: 案例名（median 或 max）
    :return: TABLE 中每个方法一行
    """
    init = uav_of(rec["methods"]["B2"]["routes"])          # B2 沿用初始分配
    e_b2 = edges(rec["methods"]["B2"]["routes"])
    rows = []
    for m in TABLE:
        out = rec["methods"][m]
        s, routes = out["summary"], out["routes"]
        e_m, own = edges(routes), uav_of(routes)
        rows.append({
            "case": case, "seed": seed, "method": m, "norm_aoi": s["norm_aoi"], "mean_aoi_s": s["mean_aoi_s"],
            "p95_aoi_s": s["p95_aoi_s"], "max_aoi_s": s["max_aoi_s"], "on_time_rate": s["on_time_rate"],
            "overtime_items": sum(not t["on_time"] for t in out["tasks"]), "norm_overtime": s["norm_overtime"],
            "stops_per_uav": s["stops_per_uav"], "mid_route_frac": mid_route_frac(routes, out["stops"]),
            "max_mission_min": s["max_mission_min"], "budget_min": rec["t_max"] / 60.0,
            "distance_km": s["distance_km"], "energy_kj": s["energy_kj"],
            "points_per_uav": "/".join(str(len(r)) for r in routes),
            "moved_points": sum(own[g] != u for g, u in init.items()),
            "shared_edges_with_B2": len(e_m & e_b2) / len(e_m) if e_m else 1.0,
        })
    return rows


def item_rows(rec: dict, seed: int, case: str) -> list[dict]:
    """一个案例上各方法的逐份记录（采集、送达、AoI 与时效窗），供论文表格或重画时间线"""
    return [{"case": case, "seed": seed, "method": m, "gid": t["gid"], "uav": t["uav"] + 1,
             "collect_s": t["collect_s"], "deliver_s": t["deliver_s"], "aoi_s": t["aoi_s"], "delta_s": t["delta_s"],
             "aoi_over_delta": t["aoi_s"] / t["delta_s"], "on_time": int(t["on_time"])}
            for m in SHOWN for t in rec["methods"][m]["tasks"]]


def solve_case(seed: int, sp=None) -> dict:
    """用当前（冻结的）代码重算一个案例，设置与 E1 的运行单元相同（方法、种子标签、下界抽样数）

    :param seed: 种子
    :param sp: 模型参数，缺省读冻结配置
    :return: run_methods 的记录（只含 B0、B2、P1、P2）
    """
    import scheme1_experiments as e123  # 取 E1 的下界抽样数，保证与 E1 的调用一致

    from uav_mec.scheme1 import load_scheme1_params, make_instance, run_methods

    sp = sp or load_scheme1_params(str(CONFIG))
    inst, groups = make_instance(LAYOUT, N, M_UAV, seed, sp)
    return run_methods(inst, groups, EPS, methods=("B0", "B2", "P1", "P2"), tag=(LAYOUT, N, M_UAV, seed, EPS),
                       lb_samples=e123.LB_SAMPLES)


def verify(recs: dict[int, dict], seeds) -> list[str]:
    """重算案例并与记录比较 TABLE 中各方法的目标

    :param recs: {种子: E1 记录}
    :param seeds: 要重算的种子
    :return: 不一致的说明；全部逐位相同时为空列表
    """
    bad = []
    for s in seeds:
        new = solve_case(s)
        for m in TABLE:
            a, b = new["methods"][m]["summary"]["obj"], recs[s]["methods"][m]["summary"]["obj"]
            if a != b:
                bad.append(f"种子 {s} {m}：重算 {a!r}，记录 {b!r}")
    return bad


def figures(selected: dict[str, tuple[int, dict]], out: Path) -> list[Path]:
    """两个案例的中英文图：航线图（标机号、往返基地航段用浅色、换机的观测点加圈）、逐份时间线、AoI ÷ δ 累积分布、各机任务时长

    :param selected: {案例名: (种子, 记录)}
    :param out: 输出目录，图写在 figures/zh 与 figures/en 下
    :return: 生成的文件路径
    """
    import scheme1_plots as sp

    files = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = out / "figures" / lang
        for case, (seed, rec) in selected.items():
            tag = f"{case}_s{seed}"
            files += sp.save(sp.fig_route_maps(rec, lang, SHOWN, uav_labels=True, light_transit=True, mark_moved=True),
                             d, f"E7_F20_route_maps_{tag}")
            files += sp.save(sp.fig_timelines(rec, lang, SHOWN), d, f"E7_X15_timelines_{tag}")
            # 累积分布与各机任务时长是方法对比图，画记录中的全部方法（E1 记录含主对比的 7 种）；
            # 航线图与时间线仍只画 SHOWN，子图多了看不清
            every = tuple(m for m in sp.METHOD_ORDER if m in rec["methods"])
            files += sp.save(sp.fig_norm_aoi_cdf(rec, lang, every), d, f"E7_aoi_over_delta_cdf_{tag}")
            files += sp.save(sp.fig_uav_mission(rec, lang, every), d, f"E7_X9_uav_mission_{tag}")
    return files


def table_lines(rows: list[dict]) -> list[str]:
    """一个案例的指标表（等宽排版，写进 summary.txt）"""
    head = ("  方法  归一化AoI  平均/95分位/最大 AoI(s)   按时率  超时份数  每机停靠  途中上传  最长任务/预算(min)"
            "  航程(km)  能耗(kJ)  各机点数        换机点数  与B2共有航段")
    lines = [head]
    for r in rows:
        lines.append(f"  {r['method']:<4}  {r['norm_aoi']:9.4f}  {r['mean_aoi_s']:6.1f}/{r['p95_aoi_s']:6.1f}/{r['max_aoi_s']:6.1f}"
                     f"  {100 * r['on_time_rate']:6.1f}%  {r['overtime_items']:8d}  {r['stops_per_uav']:8.1f}"
                     f"  {100 * r['mid_route_frac']:7.1f}%  {r['max_mission_min']:8.2f} / {r['budget_min']:.2f}"
                     f"  {r['distance_km']:8.2f}  {r['energy_kj']:8.1f}  {r['points_per_uav']:<14}"
                     f"  {r['moved_points']:8d}  {100 * r['shared_edges_with_B2']:11.1f}%")
    return lines


def run(e1_dir: Path, out: Path, do_verify: bool = False, seeds=None) -> bool:
    """读 E1 记录、按规则选案例、写 CSV、复制所选记录、出图与汇总

    :param e1_dir: E1 汇总产物的目录（含 records/）
    :param out: 输出目录
    :param do_verify: 是否用同一冻结代码重算所选案例并与记录比较
    :param seeds: 候选种子，缺省为 SEEDS
    :return: 复核通过或未要求复核时为 True
    """
    import scheme1_plots as sp

    seeds = tuple(seeds or SEEDS)
    recs = load_case_records(e1_dir, seeds)
    gains = {s: gain(r) for s, r in recs.items()}
    cases = select_cases(gains)
    rank = {s: i + 1 for i, s in enumerate(sorted(seeds, key=lambda s: (-gains[s], s)))}
    out.mkdir(parents=True, exist_ok=True)
    sp.write_rows(out / "E7_gains.csv", [{"seed": s, "gain_pct": gains[s], "rank": rank[s],
                                          "case": "+".join(c for c, v in cases.items() if v == s)} for s in seeds])
    metrics, items = [], []
    for case, s in cases.items():
        metrics += case_rows(recs[s], s, case)
        items += item_rows(recs[s], s, case)
    sp.write_rows(out / "E7_case_metrics.csv", metrics)
    sp.write_rows(out / "E7_case_items.csv", items)
    (out / "records").mkdir(exist_ok=True)
    for s in sorted(set(cases.values())):
        shutil.copy2(record_path(e1_dir, s), out / "records" / record_path(e1_dir, s).name)
    files = figures({c: (s, recs[s]) for c, s in cases.items()}, out)
    bad = verify(recs, sorted(set(cases.values()))) if do_verify else None

    vals = sorted(gains.values())
    title = (f"## E7 火线案例：E1 记录中火线布点、N = {N}、{M_UAV} 架机、ε = {EPS} 的 {len(seeds)} 个实例"
             f"（种子 {seeds[0]}–{seeds[-1]}）")
    lines = [title, f"P2 相对 B2 的改善：中位 {statistics.median(vals):.2f}%，范围 {vals[0]:.2f}–{vals[-1]:.2f}%",
             "  种子  改善(%)  排名  案例"]
    lines += [f"  {s:4d}  {gains[s]:7.2f}  {rank[s]:4d}  {'+'.join(c for c, v in cases.items() if v == s)}" for s in seeds]
    for case, s in cases.items():
        rec = recs[s]
        lines += ["", f"### {CASE_NAMES[case]}：种子 {s}，改善 {gains[s]:.2f}%（排名 {rank[s]}/{len(seeds)}）",
                  f"  T̂ = {rec['t_hat'] / 60:.2f} min，预算 (1+ε)T̂ = {rec['t_max'] / 60:.2f} min"]
        lines += table_lines([r for r in metrics if r["case"] == case])
    lines.append("")
    if bad is None:
        lines.append("复核：未运行（加 --verify 时用同一冻结代码重算所选案例）")
    elif not bad:
        lines.append(f"复核：本地用同一冻结代码重算种子 {sorted(set(cases.values()))}，{'、'.join(TABLE)} 的目标与 E1 记录逐位相同")
    else:
        lines += ["复核：有不一致"] + [f"  {b}" for b in bad]
    lines.append(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    text = "\n".join(lines) + "\n"
    (out / "summary.txt").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return not bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一 E7：火线案例")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--e1", type=Path, required=True, help="E1 汇总产物的目录（含 records/）")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--verify", action="store_true", help="用同一冻结代码重算所选案例并与记录比较")
    a = ap.parse_args(argv)
    return 0 if run(a.e1, a.out, a.verify) else 1


if __name__ == "__main__":
    sys.exit(main())
