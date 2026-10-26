"""第二道检验的结果分析：联合最优顺序与两阶段+ 的特征对比，并画改善曲线与示例航线

读取同目录 gate2_results.json，输出 gate2_features_out.txt、gate2_improvement.png、gate2_example_*.png
需要 matplotlib（用项目虚拟环境的 Python 运行）
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from degeneracy_check import DEPOT, RADIUS, STATIONS, V, candidate_points, dist  # noqa: E402

HERE = Path(__file__).resolve().parent
EPS = (0.05, 0.1, 0.25, 0.5)
FOCUS = (0.1, 0.25)
# 参考调色板（浅色）：类别色前三槽位与图表墨色，已用 validate_palette.js 校验
INK, INK2, MUTED, GRID, BASE, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
NEUTRAL_FILL = "#f0efec"
SITE_NAMES = dict(zip(("E1", "E2", "E3"), STATIONS))

plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF})


def tour_len(perm, tasks) -> float:
    pts = [DEPOT] + [tuple(tasks[i]["q"]) for i in perm] + [DEPOT]
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def edges(perm) -> set:
    nodes = [0] + [i + 1 for i in perm] + [0]
    return {frozenset((nodes[i], nodes[i + 1])) for i in range(len(nodes) - 1)}


def kendall(a, b) -> float:
    """两个顺序之间逆序对的比例（0 为相同，1 为完全反向）"""
    pos = {v: i for i, v in enumerate(b)}
    seq = [pos[v] for v in a]
    n = len(seq)
    bad = sum(1 for i in range(n) for j in range(i + 1, n) if seq[i] > seq[j])
    return bad / (n * (n - 1) / 2)


def features(sol, r, pts, tsp_perms) -> dict:
    """一个解的结构特征：顺序与最短回路的差异、停靠次数与绕路、停靠前最后一个观测点的位置与时效窗"""
    tasks = r["tasks"]
    n = r["n"]
    perm, stops = sol["perm"], sol["stops"]
    pt = (lambda qi: DEPOT if qi == -1 else pts[qi])
    q = [tuple(tasks[i]["q"]) for i in perm]
    length = tour_len(perm, tasks)
    mid = [s for s in stops if s[0] < n]
    fin = stops[-1]
    final_detour = (dist(q[-1], pt(fin[1])) + dist(pt(fin[1]), DEPOT) - dist(q[-1], DEPOT)) / V
    detour = sol["fly"] - length / V
    # 到最近站点覆盖边界的距离，负值表示在覆盖圈内
    dc = {i: min(dist(tuple(tasks[i]["q"]), s) for s in STATIONS) - RADIUS for i in range(n)}
    last = [perm[k - 1] for k, _ in mid]
    bounds = [0] + [k for k, _ in stops]
    return {
        "aoi_s": sol["obj"] / r["w_sum"],
        "is_tsp": length <= r["l_tsp"] + 1e-6,
        "order_ratio": length / r["l_tsp"],
        "shared_edges": len(edges(perm) & edges(tsp_perms[0])) / (n + 1),
        "kendall": min(kendall(perm, t) for t in tsp_perms),
        "n_stops": len(mid),
        "detour_per_stop": (detour - final_detour) / len(mid) if mid else float("nan"),
        "detour": detour,
        "stop_dist": statistics.mean(dist(q[k - 1], pt(qi)) for k, qi in mid) if mid else float("nan"),
        "dc_last": statistics.mean(dc[i] for i in last) if last else float("nan"),
        "dc_all": statistics.mean(dc.values()),
        "delta_last": statistics.mean(tasks[i]["delta"] for i in last) if last else float("nan"),
        "delta_all": statistics.mean(t["delta"] for t in tasks),
        "seg_max": max(bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)),
        "final_depot": fin[1] == -1 or pt(fin[1]) == DEPOT,
    }


def mean_of(rows, key) -> float:
    vals = [x[key] for x in rows if not (isinstance(x[key], float) and math.isnan(x[key]))]
    return statistics.mean(vals) if vals else float("nan")


def plot_improvement(res) -> None:
    """改善（联合相对两阶段+）随 ε 的变化，每机观测点数各一条线；门槛 5% 与 10% 为参考线"""
    fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=150)
    ax.axhspan(5, 10, color=NEUTRAL_FILL, zorder=0)
    for y, lab in ((5, "门槛 5%"), (10, "门槛 10%")):
        ax.axhline(y, color=MUTED, lw=1, ls=(0, (4, 3)), zorder=1)
        ax.text(0.505, y + 0.4, lab, color=INK2, fontsize=8, ha="right", va="bottom")
    for idx, nu in enumerate(sorted({r["n"] for r in res})):
        rows = [r for r in res if r["n"] == nu]
        ys = []
        for e in EPS:
            j = statistics.mean(r["joint"][str(e)]["obj"] for r in rows)
            b = statistics.mean(min(x["obj"] for x in r["two_stage"][str(e)]) for r in rows)
            ys.append(100 * (1 - j / b))
        ax.plot(EPS, ys, color=SERIES[idx], lw=2, marker="o", ms=6, mec=SURF, mew=1.5, label=f"每机 {nu} 个观测点", zorder=3)
        ax.annotate(f"{nu} 点", (EPS[-1], ys[-1]), xytext=(6, 0), textcoords="offset points", color=INK2, fontsize=8, va="center")
    ax.set_xlabel("时长预算 ε（相对最短回路不停靠时长的增幅）", color=INK2, fontsize=9)
    ax.set_ylabel("联合优化相对两阶段+ 的改善（%）", color=INK2, fontsize=9)
    ax.set_xticks(EPS)
    ax.set_xticklabels([str(e) for e in EPS])
    ax.set_xlim(0.02, 0.55)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=8, labelcolor=INK2)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(HERE / "gate2_improvement.png")
    plt.close(fig)


def draw_route(ax, r, sol, pts, title) -> None:
    tasks = r["tasks"]
    n = r["n"]
    pt = (lambda qi: DEPOT if qi == -1 else pts[qi])
    for name, s in SITE_NAMES.items():
        ax.add_patch(plt.Circle(s, RADIUS, facecolor=NEUTRAL_FILL, edgecolor=BASE, lw=1, zorder=0))
        ax.plot(*s, marker="^", color=INK2, ms=7, zorder=2)
        ax.text(s[0], s[1] - 120, name + ("（基地）" if s == DEPOT else ""), color=INK2, fontsize=8, ha="center", va="top")
    stop_after = {k: qi for k, qi in sol["stops"]}
    pos = DEPOT
    path_pts = []
    for k, i in enumerate(sol["perm"], start=1):
        qk = tuple(tasks[i]["q"])
        ax.plot([pos[0], qk[0]], [pos[1], qk[1]], color=SERIES[0], lw=2, solid_capstyle="round", zorder=3)
        pos = qk
        path_pts.append(qk)
        if k in stop_after:
            up = pt(stop_after[k])
            ax.plot([pos[0], up[0]], [pos[1], up[1]], color=SERIES[0], lw=1.6, ls=(0, (3, 2)), zorder=3)
            ax.plot(*up, marker="s", mfc=SURF, mec=SERIES[0], mew=1.6, ms=7, zorder=4)
            pos = up
    ax.plot([pos[0], DEPOT[0]], [pos[1], DEPOT[1]], color=SERIES[0], lw=1.6, ls=(0, (3, 2)), zorder=3)
    med = statistics.median(t["delta"] for t in tasks)
    for k, i in enumerate(sol["perm"], start=1):
        t = tasks[i]
        tight = t["delta"] <= med
        ax.plot(*t["q"], marker="o", ms=9, mfc=INK if tight else SURF, mec=INK, mew=1.3, zorder=5)
        ax.annotate(str(k), t["q"], xytext=(7, 5), textcoords="offset points", color=INK, fontsize=9, zorder=6)
    ax.set_xlim(0, 3000)
    ax.set_ylim(0, 3000)
    ax.set_aspect("equal")
    ax.set_title(title, color=INK, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=7, labelcolor=MUTED)
    for side in ax.spines.values():
        side.set_color(BASE)


def plot_example(r, e, pts, fname, tag) -> None:
    key = str(e)
    b = min(r["two_stage"][key], key=lambda x: x["obj"])
    j = r["joint"][key]
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 5.0), dpi=150)
    for ax, sol, name in ((axes[0], b, "两阶段+（最短回路 + 最优停靠）"), (axes[1], j, "联合最优（枚举顺序 + 最优停靠）")):
        mid = sum(1 for k, _ in sol["stops"] if k < r["n"])
        draw_route(ax, r, sol, pts, f"{name}\n加权平均 AoI {sol['obj'] / r['w_sum']:.0f} s，途中停靠 {mid} 次，飞行 {sol['fly']:.0f} s")
    imp = 100 * (1 - j["obj"] / b["obj"])
    fig.suptitle(f"{tag}：每机 {r['n']} 个观测点，ε = {e}，联合优化改善 {imp:.1f}%（预算内飞行上限 {(1 + e) * r['t_hat'] - r['hover']:.0f} s）",
                 color=INK, fontsize=10)
    fig.text(0.5, 0.015, "实线：采集航线；虚线：去上传点的绕路与返航；空心方块：上传点；实心圆：时效窗较紧的一半观测点；数字：访问顺序",
             color=INK2, fontsize=8, ha="center")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(HERE / fname)
    plt.close(fig)


def main() -> None:
    res = json.loads((HERE / "gate2_results.json").read_text(encoding="utf-8"))
    pts = candidate_points()
    out = []
    for e in FOCUS:
        key = str(e)
        fj, fb = [], []
        for r in res:
            tsp_perms = [x["perm"] for x in r["two_stage"][key]]
            b = min(r["two_stage"][key], key=lambda x: x["obj"])
            fj.append(features(r["joint"][key], r, pts, tsp_perms))
            fb.append(features(b, r, pts, tsp_perms))
        n_all = len(res)
        same = sum(1 for r in res if r["joint"][key]["obj"] >= min(x["obj"] for x in r["two_stage"][key]) - 1e-12)
        out.append(f"ε = {e}（{n_all} 个实例）")
        out.append(f"  联合最优就是最短回路（某个方向）的实例：{sum(x['is_tsp'] for x in fj)}/{n_all}；与两阶段+ 目标相同：{same}/{n_all}")
        out.append(f"  联合最优顺序：回路长度为最短回路的 {mean_of(fj, 'order_ratio'):.3f} 倍（最大 {max(x['order_ratio'] for x in fj):.3f}），"
                   f"与最短回路共享边 {100 * mean_of(fj, 'shared_edges'):.0f}%，逆序对比例 {mean_of(fj, 'kendall'):.2f}")
        for name, rows in (("联合最优", fj), ("两阶段+", fb)):
            out.append(f"  {name}：加权平均 AoI {mean_of(rows, 'aoi_s'):.0f} s；途中停靠 {mean_of(rows, 'n_stops'):.2f} 次；"
                       f"每次途中停靠绕路 {mean_of(rows, 'detour_per_stop'):.0f} s；总绕路 {mean_of(rows, 'detour'):.0f} s；"
                       f"停靠点距上一个观测点 {mean_of(rows, 'stop_dist'):.0f} m；"
                       f"停靠前最后一个观测点距覆盖边界 {mean_of(rows, 'dc_last'):.0f} m（全部观测点平均 {mean_of(rows, 'dc_all'):.0f} m）；"
                       f"其时效窗 {mean_of(rows, 'delta_last'):.0f} s（全部平均 {mean_of(rows, 'delta_all'):.0f} s）；"
                       f"最长一段 {mean_of(rows, 'seg_max'):.1f} 个观测点；最后在基地上传 {sum(x['final_depot'] for x in rows)}/{n_all}")
    (HERE / "gate2_features_out.txt").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    plot_improvement(res)
    # 示例：8 点实例在 ε = 0.1 下改善最大与改善居中的各一例
    rows8 = [r for r in res if r["n"] == max(x["n"] for x in res)]
    imp = lambda r: 1 - r["joint"]["0.1"]["obj"] / min(x["obj"] for x in r["two_stage"]["0.1"])
    rows8.sort(key=imp)
    plot_example(rows8[-1], 0.1, pts, "gate2_example_max.png", "改善最大的实例")
    plot_example(rows8[len(rows8) // 2], 0.1, pts, "gate2_example_median.png", "改善居中的实例")


if __name__ == "__main__":
    main()
