"""方案一 E6：事先声明的敏感性（实验规划 29_ 第 2 节 E6；决定与做法见该节"决定与实现细节"）

在默认场景（N = 50，5 架机，ε ∈ {0.1, 0.25}，两种布点，种子 100–119）上每次改变一个因素，比较 B0、B2、P2（同时记录 P1）：
站点数 1–4（4 站时 E4 按 10 MHz 处理）、覆盖半径 300/597.88/800 m、时效窗 150–300/300–600/600–900 s、
电池 180/270/360 kJ、机数 3/5/7、上传速率 10/30/60 Mbps。默认档重跑一次，结果须与 E1 相同

用法：
  python experiments/scheme1_e6.py shard --shard 0 --shards 16 --workers 4 --out 目录
  python experiments/scheme1_e6.py summary --inputs 目录 --out 目录
  python experiments/scheme1_e6.py smoke --out 目录
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

from uav_mec.scheme1 import load_scheme1_params, make_instance, run_methods, summary_rows  # noqa: E402
from uav_mec.v27.params import load_params  # noqa: E402

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
N = 50
M_DEFAULT = 5
SEEDS = tuple(range(100, 120))
LAYOUTS = ("fireline", "sector")
EPS = (0.1, 0.25)
METHODS = ("B0", "B2", "P1", "P2")
# 各因素的档位（字符串便于做记录名）；默认档由 "base" 一组实例代表，不在这里重复
FACTORS = {
    "stations": {"levels": ("1", "2", "3", "4"), "default": "3"},
    "radius": {"levels": ("300", "597.88", "800"), "default": "597.88"},
    "freshness": {"levels": ("150-300", "300-600", "600-900"), "default": "300-600"},
    "battery": {"levels": ("180", "270", "360"), "default": "360"},
    "uavs": {"levels": ("3", "5", "7"), "default": "5"},
    "rate": {"levels": ("10", "30", "60"), "default": "10"},
}


def jobs(seeds=SEEDS, factors=FACTORS) -> list[tuple]:
    """运行单元 (因素, 档位, 布点, 种子, ε)：默认档一组（因素记为 base），各因素的非默认档各一组"""
    out = [("base", "-", lay, s, e) for lay in LAYOUTS for s in seeds for e in EPS]
    for f, spec in factors.items():
        for lv in spec["levels"]:
            if lv != spec["default"]:
                out += [(f, lv, lay, s, e) for lay in LAYOUTS for s in seeds for e in EPS]
    return out


def variant(factor: str, level: str):
    """某档的模型参数与机数

    :return: (Scheme1Params, 机数)
    """
    sp = load_scheme1_params(str(CONFIG))
    m = M_DEFAULT
    if factor in FACTORS and level == FACTORS[factor]["default"]:
        return sp, m          # 默认档就是冻结参数（半径的标签 597.88 只是推导值 597.884766551 的近似）
    if factor == "stations":
        k = int(level)
        if k <= len(sp.stations):
            sp = sp.with_overrides(stations=sp.stations[:k])
        else:
            # 4 站：E4 按 10 MHz 处理，取与其他站相同的覆盖半径（E4 实际 8 MHz，见 29_ E6 的决定）
            r = sp.stations[0][3]
            extra = tuple((s.name, s.x, s.y, r) for s in load_params(CONFIG).sites[len(sp.stations):k])
            sp = sp.with_overrides(stations=sp.stations + extra)
    elif factor == "radius":
        sp = sp.with_overrides(stations=tuple((n, x, y, float(level)) for n, x, y, _ in sp.stations))
    elif factor == "freshness":
        a, b = (float(v) for v in level.split("-"))
        sp = sp.with_overrides(freshness_s=(a, b))
    elif factor == "battery":
        sp = sp.with_overrides(battery_j=float(level) * 1000.0)
    elif factor == "uavs":
        m = int(level)
    elif factor == "rate":
        sp = sp.with_overrides(rate_mbps=float(level))
    return sp, m


def est_cost(job: tuple) -> float:
    """相对耗时估计（只用于均匀分片）：随每机观测点数的平方与预算增长，扇形较慢，只有 1 个站时很快

    依据本地冒烟：扇形 ε = 0.25 的实例比 ε = 0.1 慢约 2.5 倍，1 站的实例只要几秒
    """
    factor, level, layout, _, eps = job
    m = int(level) if factor == "uavs" else M_DEFAULT
    c = (math.ceil(N / m) / 10) ** 2 * (2.0 if layout == "sector" else 1.0) * (1 + 8 * eps)
    return c * (0.1 if (factor, level) == ("stations", "1") else 1.0)


def shard_jobs(shard: int, shards: int) -> list[tuple]:
    order = sorted(jobs(), key=lambda j: (-est_cost(j), j))
    return [j for i, j in enumerate(order) if (i % (2 * shards) if i % (2 * shards) < shards
                                               else 2 * shards - 1 - i % (2 * shards)) == shard]


def run_job(job: tuple) -> dict:
    """生成该档的实例并运行 B0、B2、P1、P2；本文方法的种子标签与 E1 相同（机数一档随机数随 m 变化）"""
    factor, level, layout, seed, eps = job
    sp, m = variant(factor, level)
    inst, groups = make_instance(layout, N, m, seed, sp)
    t0 = time.perf_counter()
    rec = run_methods(inst, groups, eps, methods=METHODS, tag=(layout, N, m, seed, eps))
    rec["meta"] = {"exp": "E6", "factor": factor, "level": level, "layout": layout, "n": N, "m": m, "seed": seed,
                   "eps": eps}
    rec["job_secs"] = time.perf_counter() - t0
    return rec


def record_name(meta: dict) -> str:
    return "E6_{factor}_{level}_{layout}_s{seed}_e{eps}".format(**meta)


def run_jobs(job_list: list[tuple], out: Path, workers: int, log_name: str) -> None:
    """运行一组单元：逐个写记录 JSON 与汇总行 CSV、耗时日志；单进程时不开进程池"""
    from scheme1_plots import write_rows

    (out / "records").mkdir(parents=True, exist_ok=True)
    rows, log, t0 = [], [], time.perf_counter()
    order = sorted(job_list, key=lambda j: -est_cost(j))

    def write(rec):
        name = record_name(rec["meta"])
        (out / "records" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        rows.extend(summary_rows(rec, rec["meta"]))
        log.append(f"{name}\t{rec['job_secs']:.1f}")

    if workers <= 1:
        for j in order:
            write(run_job(j))
    else:
        with ProcessPoolExecutor(workers) as ex:
            for rec in ex.map(run_job, order):
                write(rec)
    log.append(f"total\t{time.perf_counter() - t0:.1f}")
    write_rows(out / f"rows_{log_name}.csv", rows)
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


def level_records(recs: list[dict], factor: str) -> dict:
    """某因素各档的实例记录：{档位: [记录]}；默认档取 base 组"""
    spec = FACTORS[factor]
    out = {}
    for lv in spec["levels"]:
        if lv == spec["default"]:
            out[lv] = [r for r in recs if r["meta"]["factor"] == "base"]
        else:
            out[lv] = [r for r in recs if r["meta"]["factor"] == factor and r["meta"]["level"] == lv]
    return out


def checks(recs: list[dict], expected: int) -> list[str]:
    """可行、每个观测点恰好分配一次、序关系（B2 ≤ B0，P2 ≤ P1 ≤ B2）、实例数"""
    problems = []
    if len(recs) != expected:
        problems.append(f"实例数 {len(recs)}/{expected}")
    bad = [record_name(r["meta"]) for r in recs for m in METHODS
           if not (r["methods"][m]["summary"]["feasible"] and r["methods"][m]["summary"]["assigned_once"])]
    if bad:
        problems.append(f"不可行或分配有误 {len(bad)} 处 {bad[:3]}")
    order = []
    for r in recs:
        o = {m: r["methods"][m]["summary"]["obj"] for m in METHODS}
        for a, b in (("B2", "B0"), ("P1", "B2"), ("P2", "P1")):
            if o[a] > o[b] + 1e-9 * max(1.0, abs(o[b])):
                order.append((record_name(r["meta"]), a, b))
    if order:
        problems.append(f"序关系不成立 {len(order)} 处 {order[:3]}")
    return problems


def factor_lines(recs: list[dict], factor: str) -> list[str]:
    """某因素的摘要：各布点、ε、档位下的平均归一化 AoI、按时率与 P2 相对 B2 的配对改善"""
    from scheme1_experiments import paired

    lines = [f"### {factor}（默认档 {FACTORS[factor]['default']}）"]
    lines.append("  布点      ε     档位        P2      B2      B0      LB   P2相对B2（中位，p）   按时率 P2/B2/B0"
                 + ("    电池起约束（P2）" if factor == "battery" else ""))
    for lay in LAYOUTS:
        for e in EPS:
            for lv, rs in level_records(recs, factor).items():
                sel = [r for r in rs if r["meta"]["layout"] == lay and r["meta"]["eps"] == e]
                if not sel:
                    continue

                def mean(m, key="norm_aoi"):
                    return statistics.fmean(r["methods"][m]["summary"][key] for r in sel)

                st = paired([r["methods"]["B2"]["summary"]["obj"] for r in sel],
                            [r["methods"]["P2"]["summary"]["obj"] for r in sel])
                lb = statistics.fmean(r["features"]["lb_norm"] for r in sel)
                line = (f"  {lay:<9} {e:<4}  {lv:<9} {mean('P2'):7.4f} {mean('B2'):7.4f} {mean('B0'):7.4f} {lb:7.4f}"
                        f"   {st['median']:5.1f}%（{st['p']:.0e}）"
                        f"   {100 * mean('P2', 'on_time_rate'):5.1f}/{100 * mean('B2', 'on_time_rate'):5.1f}/"
                        f"{100 * mean('B0', 'on_time_rate'):5.1f}%")
                if factor == "battery":
                    line += f"    {100 * mean('P2', 'battery_binding_frac'):5.1f}%"
                lines.append(line)
    return lines


def factor_rows(recs: list[dict]) -> list[dict]:
    """全部实例的汇总行（各因素的默认档都指向 base 组），供 CSV 与作图"""
    rows = []
    for r in recs:
        rows += summary_rows(r, r["meta"])
    return rows


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------

E6_LABELS = {
    "zh": {"stations": "地面站数量", "radius": "覆盖半径（m）", "freshness": "时效窗 δ（s）", "battery": "电池容量（kJ）",
           "uavs": "无人机数量 m", "rate": "上传速率（Mbps）", "norm_log": "平均归一化 AoI（对数刻度）"},
    "en": {"stations": "Ground stations", "radius": "Coverage radius (m)", "freshness": "Freshness window δ (s)",
           "battery": "Battery (kJ)", "uavs": "UAVs m", "rate": "Upload rate (Mbps)",
           "norm_log": "Mean normalized AoI (log scale)"},
}
FIG_NAMES = {"stations": "E6_F16_stations", "radius": "E6_X11_radius", "battery": "E6_X12_battery",
             "uavs": "E6_X13_uavs", "rate": "E6_X14_rate"}


def _grid(lang: str):
    """2 × 2 子图：行为 ε，列为布点"""
    import matplotlib.pyplot as plt
    import scheme1_plots as sp

    fig, axes = plt.subplots(2, 2, figsize=(sp.DOUBLE_W, 4.2), layout="constrained", sharex=True)
    for i, e in enumerate(EPS):
        for j, lay in enumerate(LAYOUTS):
            axes[i][j].set_title(f"{sp.label(lang, lay)}，ε = {e}" if lang == "zh" else f"{sp.label(lang, lay)}, ε = {e}")
    return fig, axes


def fig_factor_lines(recs: list[dict], factor: str, lang: str):
    """折线图（F16、X11–X14）：横轴为档位，纵轴为平均归一化 AoI（对数刻度），系列 P2、B2、B0 与逐份下界"""
    import scheme1_plots as sp

    fig, axes = _grid(lang)
    lv_recs = level_records(recs, factor)
    handles = []
    for i, e in enumerate(EPS):
        for j, lay in enumerate(LAYOUTS):
            ax = axes[i][j]
            pts = []
            for lv, rs in lv_recs.items():
                sel = [r for r in rs if r["meta"]["layout"] == lay and r["meta"]["eps"] == e]
                if sel:
                    pts.append((float(lv), sel))
            if not pts:
                continue
            xs = [x for x, _ in pts]
            series = {m: [[r["methods"][m]["summary"]["norm_aoi"] for r in sel] for _, sel in pts] for m in ("P2", "B2", "B0")}
            lb = [statistics.fmean(r["features"]["lb_norm"] for r in sel) for _, sel in pts]
            handles = sp.line_chart(ax, xs, series, lang, ref=lb, ref_key="LB")
            ax.set_yscale("log")
            sp.plain_log_ticks(ax)
            ax.set_xticks(xs, [f"{x:g}" for x in xs])
            ax.grid(True, axis="both", which="major")
            if i == 1:
                ax.set_xlabel(E6_LABELS[lang][factor])
            if j == 0:
                ax.set_ylabel(E6_LABELS[lang]["norm_log"])
    sp.legend_top(fig, handles)
    return fig


def fig_freshness(recs: list[dict], metric: str, lang: str):
    """F17：三档时效窗的分组柱状图（归一化 AoI 或按时送达率），系列 P2、B2、B0"""
    import scheme1_plots as sp

    fig, axes = _grid(lang)
    lv_recs = level_records(recs, "freshness")
    scale = sp.SCALE.get(metric, 1.0)
    handles = []
    for i, e in enumerate(EPS):
        for j, lay in enumerate(LAYOUTS):
            ax = axes[i][j]
            groups, series, lbs = [], {m: [] for m in ("P2", "B2", "B0")}, []
            for lv, rs in lv_recs.items():
                sel = [r for r in rs if r["meta"]["layout"] == lay and r["meta"]["eps"] == e]
                if not sel:
                    continue
                groups.append(lv.replace("-", "–"))
                for m in series:
                    series[m].append([scale * r["methods"][m]["summary"][metric] for r in sel])
                lbs.append(statistics.fmean(r["features"]["lb_norm"] for r in sel))
            if not groups:
                continue
            handles = sp.grouped_bars(ax, groups, series, lang, ref=lbs if metric == "norm_aoi" else None, ref_key="LB")
            if i == 1:
                ax.set_xlabel(E6_LABELS[lang]["freshness"])
            if j == 0:
                ax.set_ylabel(sp.label(lang, metric))
    sp.legend_top(fig, handles)
    return fig


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def summarize(inputs, out: Path, expected: int | None = None, factors=None) -> bool:
    """汇总：各因素的摘要与检查写 summary.txt，汇总行写 CSV，图写 figures/；有检查不通过时返回 False"""
    import scheme1_plots as sp

    factors = factors or list(FACTORS)
    recs = load_records(inputs)
    expected = len(jobs()) if expected is None else expected
    problems = checks(recs, expected)
    rows = factor_rows(recs)
    out.mkdir(parents=True, exist_ok=True)
    sp.write_rows(out / "E6_rows.csv", rows)
    fp = sp.result_fingerprint([{k: v for k, v in r.items() if k != "secs"} for r in rows])
    lines = [f"## E6 敏感性：{len(recs)}/{expected} 个实例（N = {N}，ε ∈ {{0.1, 0.25}}，两种布点，种子 100–119）；结果指纹 {fp}"]
    for f in factors:
        lines += factor_lines(recs, f)
    files: list[Path] = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = out / "figures" / lang
        for f in factors:
            if f == "freshness":
                files += sp.save(fig_freshness(recs, "norm_aoi", lang), d, "E6_F17_freshness_norm_aoi")
                files += sp.save(fig_freshness(recs, "on_time_rate", lang), d, "E6_F17_freshness_on_time")
            else:
                files += sp.save(fig_factor_lines(recs, f, lang), d, FIG_NAMES[f])
    lines.append("")
    lines.append("检查：" + ("全部通过（实例齐全、方案可行、分配无误、序关系成立）" if not problems else "；".join(problems)))
    lines.append(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return not problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一 E6：事先声明的敏感性")
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
        run_jobs(shard_jobs(a.shard, a.shards), a.out, a.workers, f"E6_{a.shard}")
        return 0
    if a.cmd == "summary":
        return 0 if summarize(a.inputs, a.out) else 1
    sub_f = {k: FACTORS[k] for k in ("stations", "freshness")}
    jl = jobs(seeds=(100,), factors=sub_f)
    run_jobs(jl, a.out / "shards", a.workers, "E6_smoke")
    return 0 if summarize([a.out / "shards"], a.out / "summary", expected=len(jl), factors=list(sub_f)) else 1


if __name__ == "__main__":
    sys.exit(main())
