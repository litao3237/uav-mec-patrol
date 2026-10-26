"""方案一统一作图模块：论文的全部结果图都由汇总 CSV 与逐实例记录 JSON 生成，样式只在这里定义

- 方法的颜色、填充纹理与标记固定（实验规划 29_ 第 5.4 节）。颜色取自数据可视化规范中经色觉校验的类别色，
  按固定顺序分配（相邻色在三种色觉缺陷下 ΔE ≥ 9.1）；其中三种浅色对白底对比度不足 3:1，
  因此柱状图同时用纹理、折线图同时用标记形状区分，黑白打印也能分辨
- 两套标签：英文（期刊）与中文（学位论文），由同一份数据生成；学位论文若要求宋体，改 FONTS["zh"] 后重出即可
- 每张图同时保存矢量 PDF（排版用）与 PNG 预览

用法：python experiments/scheme1_plots.py demo --out 目录 [--workers 4]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, Patch  # noqa: E402
from scipy.stats import t as student_t  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uav_mec.scheme1 import load_scheme1_params, make_instance  # noqa: E402
from uav_mec.scheme1.experiment import run_methods, summary_rows  # noqa: E402

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"

# 方法的固定顺序：本文方法在前、用最醒目的蓝色；顺序同时决定柱状图组内的排列与图例顺序
METHOD_ORDER = ("P2", "P1", "B2", "B1", "B3", "B4", "B0")
COLORS = {"P2": "#2a78d6", "P1": "#eb6834", "B2": "#1baf7a", "B1": "#eda100",
          "B3": "#e87ba4", "B4": "#008300", "B0": "#6250d6"}
# 纹理只用 45°/135° 斜线族与点，避免与网格线混淆；本文方法为实心
HATCHES = {"P2": "", "P1": "//////", "B2": "\\\\\\\\\\\\", "B1": "xxxx", "B3": "//", "B4": "\\\\", "B0": "...."}
MARKERS = {"P2": "o", "P1": "s", "B2": "^", "B1": "v", "B3": "D", "B4": "<", "B0": ">"}
INK = {"primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
       "wash": "#f0efec", "surface": "#ffffff"}
REF_STYLE = {"color": INK["secondary"], "linestyle": (0, (3, 2)), "linewidth": 0.9}   # 下界、预算线等参考线

FONTS = {"zh": ["Microsoft YaHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", "SimHei", "DejaVu Sans"],
         "en": ["Arial", "Liberation Sans", "DejaVu Sans"]}
SINGLE_W, DOUBLE_W = 3.5, 7.16   # 单栏、双栏宽度（英寸），与常见期刊版心一致

LABELS = {
    "zh": {
        "P2": "本文方法", "P1": "本文（仅机内）", "B2": "两阶段", "B1": "就近贪心", "B3": "静态分簇",
        "B4": "截止驱动", "B0": "仅基地上传", "LB": "逐份下界", "budget": "时长预算",
        "norm_aoi": "平均归一化 AoI", "mean_aoi_s": "平均 AoI（s）", "p95_aoi_s": "95 分位 AoI（s）",
        "max_aoi_s": "最大 AoI（s）", "on_time_rate": "按时送达率（%）", "norm_overtime": "归一化超时量",
        "max_mission_min": "最大任务时长（min）", "energy_kj": "总能耗（kJ）", "distance_km": "总航程（km）",
        "stops_per_uav": "每机途中停靠次数", "secs": "求解时间（s）",
        "n": "观测点数 N", "eps": "预算松弛 ε", "evals": "评估次数", "rel_obj": "目标 ÷ 两阶段目标",
        "median": "中位数", "range": "种子间范围", "inter_start": "开始跨机移动",
        "aoi_item": "每份数据的 AoI（s）", "cdf": "累积比例", "lb_ratio": "下界 ÷ 精确值", "route_len": "航线观测点数",
        "gain": "相对两阶段的改善（%）", "mean_dist_to_coverage_m": "离覆盖边界的平均距离（m）",
        "slack_std_s": "各机时间余量的标准差（s）", "uav": "无人机", "mission_min": "任务时长（min）",
        "time_min": "时间（min）", "x_km": "x（km）", "y_km": "y（km）", "depot": "基地", "station": "地面站",
        "upload": "停靠上传", "task": "观测点", "deadline": "时效窗截止", "carry": "采集到送达",
        "fireline": "火线布点", "sector": "扇形布点", "leg": "飞行航段", "detour": "绕路上传",
        "overtime": "超时部分", "fit": "最小二乘拟合", "title_aoi": "平均归一化 AoI",
    },
    "en": {
        "P2": "Proposed", "P1": "Proposed (intra)", "B2": "Two-stage", "B1": "Greedy stop",
        "B3": "Static cluster", "B4": "Deadline-driven", "B0": "Base-only", "LB": "Lower bound",
        "budget": "Time budget",
        "norm_aoi": "Mean normalized AoI", "mean_aoi_s": "Mean AoI (s)", "p95_aoi_s": "95th-percentile AoI (s)",
        "max_aoi_s": "Max AoI (s)", "on_time_rate": "On-time delivery (%)", "norm_overtime": "Normalized overtime",
        "max_mission_min": "Max mission time (min)", "energy_kj": "Total energy (kJ)",
        "distance_km": "Total distance (km)", "stops_per_uav": "Mid-route stops per UAV", "secs": "Solve time (s)",
        "n": "Observation points N", "eps": "Budget slack ε", "evals": "Evaluations",
        "rel_obj": "Objective / two-stage", "median": "Median", "range": "Range over seeds",
        "inter_start": "Cross-UAV moves start", "aoi_item": "Per-item AoI (s)", "cdf": "Cumulative fraction",
        "lb_ratio": "Lower bound / exact", "route_len": "Points on route", "gain": "Gain over two-stage (%)",
        "mean_dist_to_coverage_m": "Mean distance to coverage (m)", "slack_std_s": "Std of UAV time slack (s)",
        "uav": "UAV", "mission_min": "Mission time (min)", "time_min": "Time (min)", "x_km": "x (km)",
        "y_km": "y (km)", "depot": "Depot", "station": "Ground station", "upload": "Upload stop",
        "task": "Observation point", "deadline": "Deadline", "carry": "Collect to deliver",
        "fireline": "Fire-line layout", "sector": "Sector layout", "leg": "Flight leg", "detour": "Upload detour",
        "overtime": "Overtime", "fit": "Least-squares fit", "title_aoi": "norm. AoI",
    },
}
SCALE = {"on_time_rate": 100.0}   # 比例类指标画成百分数


def setup(lang: str) -> None:
    """按语言设置全局样式：字体、字号、坐标轴与网格（网格为实线细线，坐标轴退后，数据最醒目）

    :param lang: "zh" 或 "en"
    """
    plt.rcdefaults()
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": FONTS[lang], "axes.unicode_minus": False,
        "font.size": 7.5, "axes.labelsize": 7.5, "axes.titlesize": 7.5, "xtick.labelsize": 7, "ytick.labelsize": 7,
        "legend.fontsize": 7, "legend.frameon": False, "legend.handlelength": 1.6, "legend.columnspacing": 1.0,
        "text.color": INK["primary"], "axes.labelcolor": INK["primary"], "axes.edgecolor": INK["axis"],
        "axes.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": INK["grid"], "grid.linewidth": 0.5,
        "grid.linestyle": "-", "xtick.color": INK["axis"], "ytick.color": INK["axis"],
        "xtick.labelcolor": INK["secondary"], "ytick.labelcolor": INK["secondary"],
        "xtick.major.size": 2.5, "ytick.major.size": 2.5, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "lines.linewidth": 1.1, "lines.markersize": 4, "hatch.linewidth": 0.45,
        "figure.facecolor": INK["surface"], "axes.facecolor": INK["surface"], "savefig.facecolor": INK["surface"],
        "savefig.dpi": 300, "pdf.fonttype": 42, "svg.fonttype": "none",
    })


def label(lang: str, key: str) -> str:
    """取标签；没有登记的键原样返回"""
    return LABELS[lang].get(key, key)


def new_fig(ncols: int = 1, width: float = SINGLE_W, height: float = 2.3, **kw):
    """新建图：采用 constrained 布局，图例可放在绘图区外侧上方而不改变成图宽度"""
    fig, axes = plt.subplots(1, ncols, figsize=(width, height), layout="constrained", **kw)
    return fig, axes


def legend_top(fig, handles, ncol: int = 4) -> None:
    """图例放在全部绘图区的上方，多列、无边框，不遮挡数据；宽度超出成图时逐步减少列数（英文标签较长）"""
    renderer = fig.canvas.get_renderer()
    for k in range(min(ncol, len(handles)), 0, -1):
        leg = fig.legend(handles=handles, loc="outside upper center", ncol=k)
        if k == 1 or leg.get_window_extent(renderer).width <= 0.98 * fig.bbox.width:
            return
        leg.remove()


def method_handle(m: str, lang: str, kind: str = "bar") -> object:
    """方法的图例句柄：柱状图为带纹理的色块，折线图为线 + 空心标记"""
    if kind == "bar":
        return Patch(facecolor=COLORS[m], edgecolor=shade(COLORS[m]), linewidth=0, hatch=HATCHES[m], label=label(lang, m))
    return Line2D([], [], color=COLORS[m], marker=MARKERS[m], markerfacecolor=INK["surface"],
                  markeredgecolor=COLORS[m], markeredgewidth=0.9, label=label(lang, m))


def ref_handle(lang: str, key: str = "LB") -> Line2D:
    """参考线（下界、预算线）的图例句柄"""
    return Line2D([], [], label=label(lang, key), **REF_STYLE)


def shade(hex_color: str, k: float = 0.45) -> str:
    """同色系的深一档颜色（向黑色混合 k），用作纹理线色，使纹理与填充同色调"""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(round(c * (1 - k)) for c in (r, g, b)))


def mean_ci(xs) -> tuple[float, float]:
    """均值与 95% 置信区间半宽（t 分布）；只有一个样本时半宽为 0

    :param xs: 样本
    :return: (均值, 半宽)
    """
    xs = [float(x) for x in xs]
    m = statistics.fmean(xs)
    if len(xs) < 2:
        return m, 0.0
    return m, float(student_t.ppf(0.975, len(xs) - 1)) * statistics.stdev(xs) / math.sqrt(len(xs))


def save(fig, out_dir: Path, name: str) -> list[Path]:
    """同时保存 PDF 与 PNG 并关闭图

    :return: 两个文件的路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{name}.pdf", out_dir / f"{name}.png"]
    for p in paths:
        fig.savefig(p)
    plt.close(fig)
    return paths


def fmt_group(v) -> str:
    """分组标签：整数值去掉小数点"""
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


# ---------------------------------------------------------------------------
# 数据读写
# ---------------------------------------------------------------------------

def write_rows(path: Path, rows: list[dict]) -> None:
    """写汇总 CSV：列为全部行的键的并集，按首次出现的顺序"""
    keys = list(dict.fromkeys(k for r in rows for k in r))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_rows(path: Path) -> list[dict]:
    """读汇总 CSV：数值列转为 float，True/False 转为布尔值，其余保留字符串"""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in r.items():
            if v in ("True", "False"):
                r[k] = v == "True"
                continue
            try:
                r[k] = float(v)
            except (TypeError, ValueError):
                pass
    return rows


def select(rows: list[dict], **cond) -> list[dict]:
    """按列取值筛选行"""
    return [r for r in rows if all(r.get(k) == v for k, v in cond.items())]


# ---------------------------------------------------------------------------
# 基本图型
# ---------------------------------------------------------------------------

def _stats(samples) -> tuple[float, float]:
    """样本列表 → (均值, 95% 置信区间半宽)；单个数值视为没有误差"""
    return mean_ci(samples) if isinstance(samples, (list, tuple)) else (float(samples), 0.0)


def grouped_bars(ax, groups, series: dict, lang: str, ref=None, ref_key: str = "LB", hatch: bool = True,
                 width: float = 0.84) -> list:
    """分组柱状图：组内按 METHOD_ORDER 排列各方法，柱高为均值，误差线为 95% 置信区间

    柱与柱之间留白色间隙而不描边；纹理线取填充色的深一档
    :param ax: 坐标轴
    :param groups: 分组（横轴类别）
    :param series: {方法: [每组的样本列表或单个数值]}
    :param lang: 标签语言
    :param ref: 每组一个参考值（下界、预算线），画成跨整组的灰色虚线段
    :param ref_key: 参考线的标签键
    :param hatch: 是否加纹理
    :param width: 一组柱子占的总宽度，其余为组间空白
    :return: 图例句柄
    """
    ms = [m for m in METHOD_ORDER if m in series]
    slot = width / len(ms)
    for j, m in enumerate(ms):
        xs = [i - width / 2 + slot * (j + 0.5) for i in range(len(groups))]
        st = [_stats(s) for s in series[m]]
        ax.bar(xs, [s[0] for s in st], width=slot * 0.86, color=COLORS[m], edgecolor=shade(COLORS[m]), linewidth=0,
               hatch=HATCHES[m] if hatch else "", zorder=2)
        if any(s[1] > 0 for s in st):
            ax.errorbar(xs, [s[0] for s in st], yerr=[s[1] for s in st], fmt="none", ecolor=INK["secondary"],
                        elinewidth=0.5, capsize=1.0, capthick=0.5, zorder=3)
    handles = [method_handle(m, lang, "bar") for m in ms]
    if ref is not None:
        for i, v in enumerate(ref):
            ax.plot([i - width / 2, i + width / 2], [v, v], zorder=4, **REF_STYLE)
        handles.append(ref_handle(lang, ref_key))
    ax.set_xticks(range(len(groups)), [fmt_group(g) for g in groups])
    ax.set_xlim(-0.6, len(groups) - 0.4)
    ax.tick_params(axis="x", length=0)
    return handles


def line_chart(ax, xs, series: dict, lang: str, ref=None, ref_key: str = "LB", band: bool = False) -> list:
    """折线图（空心标记）：每个横轴取值画均值，可选 95% 置信区间色带

    :param xs: 横轴取值
    :param series: {方法: [每个横轴取值的样本列表或单个数值]}
    :param ref: 与 xs 对应的参考值，画成灰色虚线
    :param band: 是否画置信区间色带（约 12% 不透明度的浅色）
    :return: 图例句柄
    """
    handles = []
    for m in [m for m in METHOD_ORDER if m in series]:
        st = [_stats(s) for s in series[m]]
        if band:
            ax.fill_between(xs, [a - b for a, b in st], [a + b for a, b in st], color=COLORS[m], alpha=0.12,
                            linewidth=0, zorder=1)
        ax.plot(xs, [s[0] for s in st], color=COLORS[m], marker=MARKERS[m], markerfacecolor=INK["surface"],
                markeredgecolor=COLORS[m], markeredgewidth=0.9, zorder=3)
        handles.append(method_handle(m, lang, "line"))
    if ref is not None:
        ax.plot(xs, ref, zorder=2, **REF_STYLE)
        handles.append(ref_handle(lang, ref_key))
    return handles


def box(ax, data: dict, lang: str, colors: dict | None = None, rotate: int = 30) -> None:
    """箱线图：每类一个箱，横轴直接标类别名（不另加图例）

    箱体为该类颜色的浅色填充，中位数线用正文墨色；须为 1.5 倍四分位距，离群点为小空心点
    :param data: {类别: 样本}；类别为方法键时按 METHOD_ORDER 排列并用方法色
    :param colors: 非方法类别的颜色，缺省一律用本文方法的蓝色
    :param rotate: 横轴标签的旋转角度
    """
    keys = [m for m in METHOD_ORDER if m in data] + [k for k in data if k not in METHOD_ORDER]
    bp = ax.boxplot([data[k] for k in keys], positions=range(len(keys)), widths=0.55, patch_artist=True)
    for i, k in enumerate(keys):
        c = COLORS.get(k) or (colors or {}).get(k, COLORS["P2"])
        bp["boxes"][i].set(facecolor=matplotlib.colors.to_rgba(c, 0.18), edgecolor=c, linewidth=0.8)
        for art in bp["whiskers"][2 * i:2 * i + 2] + bp["caps"][2 * i:2 * i + 2]:
            art.set(color=c, linewidth=0.8)
        bp["medians"][i].set(color=INK["primary"], linewidth=1.0)
        bp["fliers"][i].set(marker="o", markersize=2, markerfacecolor="none", markeredgecolor=c, markeredgewidth=0.5)
    ax.set_xticks(range(len(keys)), [label(lang, fmt_group(k)) for k in keys], rotation=rotate,
                  ha="right" if rotate else "center")
    ax.tick_params(axis="x", length=0)


def cdf(ax, data: dict, lang: str, n_markers: int = 5) -> list:
    """累积分布曲线：阶梯线加稀疏空心标记，各方法的标记位置错开，黑白打印时靠标记形状区分

    :param data: {方法: 样本}
    :return: 图例句柄
    """
    ms = [m for m in METHOD_ORDER if m in data]
    handles = []
    for j, m in enumerate(ms):
        xs = sorted(data[m])
        n = len(xs)
        ys = [(i + 1) / n for i in range(n)]
        ax.step(xs, ys, where="post", color=COLORS[m], zorder=3)
        idx = sorted({min(n - 1, int((q + (j + 1) / (len(ms) + 1)) / n_markers * n)) for q in range(n_markers)})
        ax.plot([xs[i] for i in idx], [ys[i] for i in idx], linestyle="none", marker=MARKERS[m],
                markerfacecolor=INK["surface"], markeredgecolor=COLORS[m], markeredgewidth=0.9, zorder=4)
        handles.append(method_handle(m, lang, "line"))
    ax.set_ylim(0, 1.02)
    ax.grid(True, axis="both")
    return handles


def scatter_fit(ax, groups: dict, lang: str, color: str = COLORS["P2"]) -> tuple[list, tuple]:
    """散点图 + 合并样本的最小二乘拟合线；各组同色、用标记形状区分（颜色只代表方法，不另指别的类别）

    相关系数写在绘图区左上角，便于多个子图共用一个图例
    :param groups: {组标签键: (x 列表, y 列表)}，至多三组，标记依次为圆、方、三角
    :param color: 点与拟合线的颜色
    :return: (图例句柄, (斜率, 截距, 皮尔逊 r, 样本数))；横轴取值少于两个时不拟合，后三项为 None
    """
    if len(groups) > 3:
        raise ValueError("散点图至多三组")
    xs, ys, handles = [], [], []
    for (g, (x, y)), mk in zip(groups.items(), "os^"):
        ax.scatter(x, y, s=12, marker=mk, facecolors="none", edgecolors=color, linewidths=0.7, zorder=3)
        handles.append(Line2D([], [], linestyle="none", marker=mk, markerfacecolor="none", markeredgecolor=color,
                              markeredgewidth=0.7, label=label(lang, g)))
        xs += list(x)
        ys += list(y)
    ax.grid(True, axis="both")
    handles.append(Line2D([], [], color=color, label=label(lang, "fit")))
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return handles, (None, None, None, len(xs))
    slope, icpt = statistics.linear_regression(xs, ys)
    r = statistics.correlation(xs, ys)
    x0, x1 = min(xs), max(xs)
    ax.plot([x0, x1], [icpt + slope * x0, icpt + slope * x1], color=color, zorder=4)
    ax.text(0.03, 0.96, f"r = {r:.2f}", transform=ax.transAxes, va="top", color=INK["secondary"])
    return handles, (slope, icpt, r, len(xs))


def convergence(ax, runs: list, lang: str, color: str = COLORS["P2"], phase: float | None = None) -> list:
    """收敛曲线：各次运行的目标随评估次数的阶梯变化，画中位数与种子间范围（最小到最大）

    :param runs: 每次运行一条 (评估次数列表, 目标列表)，评估次数不减，每次接受改进时记录一点
    :param color: 曲线颜色
    :param phase: 若给出，在该评估次数处画竖直虚线，表示开始跨机移动
    :return: 图例句柄
    """
    from bisect import bisect_right

    xmax = max(r[0][-1] for r in runs)
    grid = [xmax * i / 400 for i in range(401)]
    vals = [[r[1][max(bisect_right(r[0], x) - 1, 0)] for r in runs] for x in grid]
    ax.fill_between(grid, [min(v) for v in vals], [max(v) for v in vals], step="post", color=color, alpha=0.12,
                    linewidth=0, zorder=1)
    ax.step(grid, [statistics.median(v) for v in vals], where="post", color=color, zorder=3)
    handles = [Line2D([], [], color=color, label=label(lang, "median")),
               Patch(facecolor=matplotlib.colors.to_rgba(color, 0.12), label=label(lang, "range"))]
    if phase is not None:
        ax.axvline(phase, zorder=2, **REF_STYLE)
        handles.append(Line2D([], [], label=label(lang, "inter_start"), **REF_STYLE))
    return handles


def route_map(ax, geom: dict, routes, stops, color: str, lang: str) -> None:
    """航线图：覆盖圈、地面站、候选上传点、观测点、基地，以及每架机的航线与停靠

    采集段为实线，去非基地上传点及离开它的绕路段为虚线，停靠的上传点为空心菱形；
    各机航线同色（颜色只代表方法），各机的观测点在空间上分开，不靠颜色区分
    :param geom: experiment.instance_geometry 的输出
    :param routes: 每架机的访问顺序
    :param stops: 每架机的停靠方案 [(第 k 个观测点之后, 上传点下标或 -1)]
    """
    km = 1e-3
    for _, sx, sy, r in geom["stations"]:
        ax.add_patch(Circle((sx * km, sy * km), r * km, facecolor=INK["wash"], edgecolor=INK["axis"], linewidth=0.5,
                            zorder=0))
        ax.plot(sx * km, sy * km, marker="^", markersize=4, color=INK["secondary"], linestyle="none", zorder=2)
    ax.plot([q[0] * km for q in geom["points"]], [q[1] * km for q in geom["points"]], linestyle="none", marker=".",
            markersize=1.5, color=INK["muted"], zorder=1)
    dep, tasks = geom["depot"], geom["tasks"]

    def seg(a, b, dashed):
        ax.plot([a[0] * km, b[0] * km], [a[1] * km, b[1] * km], color=color, linewidth=0.9,
                linestyle=(0, (2.5, 1.5)) if dashed else "-", zorder=3)

    used = set()
    for route, st in zip(routes, stops):
        stop_at = {int(k): int(q) for k, q in st}
        pos, from_stop = dep, False
        for k, g in enumerate(route, start=1):
            seg(pos, tasks[g], from_stop)
            pos, from_stop = tasks[g], False
            if k in stop_at:
                q = stop_at[k]
                if q == -1:
                    seg(pos, dep, False)
                    pos = dep
                else:
                    seg(pos, geom["points"][q], True)
                    pos, from_stop = geom["points"][q], True
                    used.add(q)
        if pos is not dep:
            seg(pos, dep, from_stop)
    ax.plot([t[0] * km for t in tasks], [t[1] * km for t in tasks], linestyle="none", marker="o", markersize=2.2,
            color=INK["secondary"], zorder=4)
    if used:
        ax.plot([geom["points"][q][0] * km for q in used], [geom["points"][q][1] * km for q in used],
                linestyle="none", marker="D", markersize=4, markerfacecolor=INK["surface"], markeredgecolor=color,
                markeredgewidth=0.9, zorder=5)
    ax.plot(dep[0] * km, dep[1] * km, marker="s", markersize=4.5, color=INK["primary"], linestyle="none", zorder=6)
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_xlabel(label(lang, "x_km"))


def map_legend(lang: str) -> list:
    """航线图的图例（与方法无关的中性墨色）"""
    return [Line2D([], [], linestyle="none", marker="s", markersize=4.5, color=INK["primary"], label=label(lang, "depot")),
            Patch(facecolor=INK["wash"], edgecolor=INK["axis"], linewidth=0.5, label=label(lang, "station")),
            Line2D([], [], linestyle="none", marker="o", markersize=2.2, color=INK["secondary"], label=label(lang, "task")),
            Line2D([], [], linestyle="none", marker="D", markersize=4, markerfacecolor=INK["surface"],
                   markeredgecolor=INK["secondary"], label=label(lang, "upload")),
            Line2D([], [], color=INK["secondary"], linewidth=0.9, label=label(lang, "leg")),
            Line2D([], [], color=INK["secondary"], linewidth=0.9, linestyle=(0, (2.5, 1.5)),
                   label=label(lang, "detour"))]


def timeline(ax, task_recs: list, color: str, lang: str) -> list:
    """时间线（甘特图）：每份数据一行，横条从采集完成到送达，竖短线为时效窗截止（采集 + δ）

    行按无人机分组、组内按采集时刻排列；越过截止线的部分加纹理，表示超时
    :param task_recs: evaluate_solution 输出的逐份记录（含 uav、collect_s、deliver_s、delta_s）
    :return: 图例句柄
    """
    recs = sorted(task_recs, key=lambda t: (t["uav"], t["collect_s"]))
    y, prev, centers, bounds = 0.0, None, {}, []
    for t in recs:
        if prev is not None and t["uav"] != prev:
            bounds.append(y + 0.4)
            y += 0.8
        c0, c1, dl = t["collect_s"] / 60, t["deliver_s"] / 60, (t["collect_s"] + t["delta_s"]) / 60
        ax.barh(y + 1, c1 - c0, left=c0, height=0.62, color=color, linewidth=0, zorder=2)
        if c1 > dl:
            ax.barh(y + 1, c1 - dl, left=dl, height=0.62, color=color, edgecolor=shade(color), linewidth=0,
                    hatch="//////", zorder=3)
        ax.plot([dl, dl], [y + 1 - 0.42, y + 1 + 0.42], color=INK["primary"], linewidth=0.8, zorder=4)
        centers.setdefault(t["uav"], []).append(y + 1)
        prev = t["uav"]
        y += 1
    for b in bounds:
        ax.axhline(b + 1, color=INK["grid"], linewidth=0.5, zorder=1)
    ax.set_yticks([statistics.fmean(v) for v in centers.values()],
                  [f"{label(lang, 'uav')} {u + 1}" for u in centers])
    ax.set_ylim(y + 0.6, 0.4)
    ax.tick_params(axis="y", length=0)
    ax.grid(True, axis="x")
    ax.grid(False, axis="y")
    ax.set_xlabel(label(lang, "time_min"))
    handles = [Patch(facecolor=color, label=label(lang, "carry")),
               Line2D([], [], linestyle="none", marker="|", markersize=6, markeredgewidth=0.8, color=INK["primary"],
                      label=label(lang, "deadline"))]
    if any(t["deliver_s"] > t["collect_s"] + t["delta_s"] for t in recs):
        handles.insert(1, Patch(facecolor=color, edgecolor=shade(color), linewidth=0, hatch="//////",
                                label=label(lang, "overtime")))
    return handles


# ---------------------------------------------------------------------------
# 按图组装：输入都是汇总 CSV 的行或逐实例记录 JSON
# ---------------------------------------------------------------------------

def metric_series(rows: list[dict], metric: str, group_key: str = "n", methods=METHOD_ORDER) -> tuple[list, dict]:
    """把汇总行整理为 (分组, {方法: [每组的样本列表]})，分组按取值升序；只取 methods 中的方法"""
    groups = sorted({r[group_key] for r in rows})
    s = SCALE.get(metric, 1.0)
    series = {m: [[r[metric] * s for r in rows if r["method"] == m and r[group_key] == g] for g in groups]
              for m in METHOD_ORDER if m in methods and any(r["method"] == m for r in rows)}
    return groups, series


def instance_rows(rows: list[dict]) -> list[dict]:
    """每个实例取一行（实例特征在各方法的行里相同）"""
    first = next(m for m in METHOD_ORDER if any(r["method"] == m for r in rows))
    return [r for r in rows if r["method"] == first]


def fig_metric(rows: list[dict], metric: str, lang: str, kind: str = "bar", group_key: str = "n",
               methods=METHOD_ORDER):
    """单一指标随分组（默认规模 N）变化的图（F4–F9、F11、F18–F19 等）

    归一化 AoI 叠加逐份下界，最大任务时长叠加时长预算 (1+ε)·T̂，均为同组实例的平均
    :param rows: 已筛选好布点与 ε 的汇总行
    :param metric: 指标列名
    :param kind: "bar" 为分组柱状图，"line" 为折线图
    :param group_key: 分组列名
    :param methods: 要画的方法；折线图中远高于其余方法的 B0、B3、B4 会把接近的几条线压在一起，可只画其余方法
    """
    groups, series = metric_series(rows, metric, group_key, methods)
    inst = instance_rows(rows)
    ref = ref_key = None
    if metric == "norm_aoi":
        ref, ref_key = [statistics.fmean(r["lb_norm"] for r in inst if r[group_key] == g) for g in groups], "LB"
    elif metric == "max_mission_min":
        ref = [statistics.fmean((1 + r["eps"]) * r["t_hat_s"] / 60 for r in inst if r[group_key] == g) for g in groups]
        ref_key = "budget"
    fig, ax = new_fig()
    if kind == "bar":
        handles = grouped_bars(ax, groups, series, lang, ref=ref, ref_key=ref_key)
    else:
        handles = line_chart(ax, groups, series, lang, ref=ref, ref_key=ref_key)
        ax.set_xticks(groups, [fmt_group(g) for g in groups])
    ax.set_xlabel(label(lang, group_key))
    ax.set_ylabel(label(lang, metric))
    legend_top(fig, handles)
    return fig


def task_aois(recs: list[dict]) -> dict:
    """多个实例的逐份 AoI 合并：{方法: [AoI]}"""
    return {m: [t["aoi_s"] for r in recs for t in r["methods"][m]["tasks"]]
            for m in METHOD_ORDER if all(m in r["methods"] for r in recs)}


def fig_aoi_box(recs: list[dict], lang: str):
    """F10：每份数据 AoI 的分布（箱线图）"""
    fig, ax = new_fig(height=2.4)
    box(ax, task_aois(recs), lang)
    ax.set_ylabel(label(lang, "aoi_item"))
    return fig


def fig_aoi_cdf(recs: list[dict], lang: str):
    """X6：每份数据 AoI 的累积分布"""
    fig, ax = new_fig()
    handles = cdf(ax, task_aois(recs), lang)
    ax.set_xlabel(label(lang, "aoi_item"))
    ax.set_ylabel(label(lang, "cdf"))
    legend_top(fig, handles)
    return fig


def fig_convergence(recs: list[dict], lang: str):
    """F2：本文方法的目标（÷ 两阶段目标）随评估次数的变化

    各实例的绝对水平不同，除以两阶段目标后种子间范围才反映收敛过程本身；竖虚线为开始跨机移动时评估次数的中位数
    """
    runs, phases = [], []
    for r in recs:
        p2 = r["methods"]["P2"]
        h, base = p2["history"], p2["two_stage_obj"]
        runs.append(([e[0] for e in h], [e[1] / base for e in h]))
        phases.append(next(e[0] for e in h if e[2] == "intra_end"))
    fig, ax = new_fig()
    handles = convergence(ax, runs, lang, phase=statistics.median(phases))
    ax.set_xlabel(label(lang, "evals"))
    ax.set_ylabel(label(lang, "rel_obj"))
    legend_top(fig, handles, ncol=3)
    return fig


def fig_lb_ratio(recs: list[dict], lang: str):
    """X8：时间价格下界的紧度，下界 ÷ 精确值按航线上的观测点数分组"""
    data: dict = {}
    for r in recs:
        for n, lb, ex in r["methods"]["P2"].get("lb_pairs", []):
            data.setdefault(int(n), []).append(lb / ex)
    fig, ax = new_fig()
    box(ax, dict(sorted(data.items())), lang, rotate=0)
    ax.set_xlabel(label(lang, "route_len"))
    ax.set_ylabel(label(lang, "lb_ratio"))
    return fig


def gain_points(rows: list[dict]) -> dict:
    """每个实例本文方法相对两阶段的改善（%）：{布点: [(实例行, 改善)]}"""
    by_inst: dict = {}
    for r in rows:
        by_inst.setdefault((r["layout"], r["n"], r["seed"], r["eps"]), {})[r["method"]] = r
    pts: dict = {}
    for (layout, *_), d in sorted(by_inst.items()):
        if "P2" in d and "B2" in d:
            pts.setdefault(layout, []).append((d["B2"], 100 * (d["B2"]["obj"] - d["P2"]["obj"]) / d["B2"]["obj"]))
    return pts


def fig_gain_scatter(rows: list[dict], lang: str):
    """F13 右图与 X10：相对两阶段的改善与实例特征（离覆盖边界距离、各机时间余量离散程度）的关系"""
    pts = gain_points(rows)
    fig, axes = new_fig(ncols=2, width=DOUBLE_W, height=2.3, sharey=True)
    for ax, feat in zip(axes, ("mean_dist_to_coverage_m", "slack_std_s")):
        groups = {lay: ([r[feat] for r, _ in v], [g for _, g in v]) for lay, v in pts.items()}
        handles, _ = scatter_fit(ax, groups, lang)
        ax.set_xlabel(label(lang, feat))
    axes[0].set_ylabel(label(lang, "gain"))
    legend_top(fig, handles)
    return fig


def fig_route_maps(rec: dict, lang: str, methods=("P2", "B2", "B0")):
    """F20：同一实例上几种方法的航线图，子图标题给出平均归一化 AoI"""
    fig, axes = new_fig(ncols=len(methods), width=DOUBLE_W, height=2.7, sharex=True, sharey=True)
    for ax, m in zip(axes, methods):
        out = rec["methods"][m]
        route_map(ax, rec["geometry"], out["routes"], out["stops"], COLORS[m], lang)
        v = out["summary"]["norm_aoi"]
        ax.set_title(f"{label(lang, m)}（{label(lang, 'title_aoi')} {v:.3f}）" if lang == "zh"
                     else f"{label(lang, m)} ({label(lang, 'title_aoi')} {v:.3f})")
    axes[0].set_ylabel(label(lang, "y_km"))
    legend_top(fig, map_legend(lang), ncol=6)
    return fig


def fig_timeline(rec: dict, lang: str, method: str = "P2"):
    """X15：一个实例上某方法每份数据从采集到送达的时间线"""
    tasks = rec["methods"][method]["tasks"]
    fig, ax = new_fig(height=1.0 + 0.055 * len(tasks))
    handles = timeline(ax, tasks, COLORS[method], lang)
    legend_top(fig, handles, ncol=3)
    return fig


def fig_uav_mission(rec: dict, lang: str):
    """X9：跨机移动前（P1）后（P2）各机的任务时长，虚线为时长预算"""
    series = {m: [u["mission_s"] / 60 for u in rec["methods"][m]["uavs"]] for m in ("P2", "P1")}
    k = len(series["P2"])
    fig, ax = new_fig()
    handles = grouped_bars(ax, list(range(1, k + 1)), series, lang, ref=[rec["t_max"] / 60] * k, ref_key="budget",
                           width=0.6)
    ax.set_xlabel(label(lang, "uav"))
    ax.set_ylabel(label(lang, "mission_min"))
    legend_top(fig, handles, ncol=3)
    return fig


# ---------------------------------------------------------------------------
# 示例：冒烟种子的小实例 → JSON / CSV → 中英文两套图
# ---------------------------------------------------------------------------

# 冒烟种子 97–99，与评估实例（种子 100 起）、检验实例（0–3）分开
DEMO = {"layouts": ("fireline", "sector"), "sizes": (20, 30), "m": 3, "seeds": (97, 98, 99), "eps": (0.1, 0.25),
        "lb_samples": 30}


def _demo_job(job: tuple) -> dict:
    """示例的一个运行单元：生成实例并运行全部方法（在进程池中执行）"""
    layout, n, m, seed, eps, lb_samples = job
    inst, groups = make_instance(layout, n, m, seed, load_scheme1_params(str(CONFIG)))
    rec = run_methods(inst, groups, eps, tag=(layout, n, m, seed, eps), lb_samples=lb_samples)
    rec["meta"] = {"layout": layout, "n": n, "m": m, "seed": seed, "eps": eps}
    return rec


def run_demo(out: Path, workers: int = 1, cfg: dict = DEMO) -> None:
    """在小实例上运行全部方法，逐实例存 JSON（records/），汇总存 CSV（summary.csv）

    :param out: 输出目录
    :param workers: 并行进程数（不影响结果，只影响耗时）
    :param cfg: 实例设置，格式同 DEMO
    """
    jobs = [(lay, n, cfg["m"], s, e, cfg["lb_samples"]) for lay in cfg["layouts"] for n in cfg["sizes"]
            for s in cfg["seeds"] for e in cfg["eps"]]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            recs = list(ex.map(_demo_job, jobs))
    else:
        recs = [_demo_job(j) for j in jobs]
    rows = []
    (out / "records").mkdir(parents=True, exist_ok=True)
    for rec in recs:
        meta = rec["meta"]
        name = "{layout}_n{n}_m{m}_s{seed}_e{eps}".format(**meta)
        (out / "records" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        rows += summary_rows(rec, meta)
    write_rows(out / "summary.csv", rows)


def demo_report(rows: list[dict]) -> tuple[str, bool]:
    """示例结果的文字摘要与自检

    自检：全部方案可行且每个观测点恰好分配一次；同一航线上的停靠方案中两阶段最优（B2 ≤ B0、B1、B4），
    本文方法不劣于起点（P1 ≤ B2、P2 ≤ P1）
    :return: (摘要文本, 自检是否全部通过)
    """
    lines, ok = [], True
    for lay in sorted({r["layout"] for r in rows}):
        for e in sorted({r["eps"] for r in rows}):
            lines.append(f"{lay}  eps={e}  平均归一化 AoI（{len({r['seed'] for r in rows})} 个种子的均值）")
            lines.append("  N    " + " ".join(f"{m:>7}" for m in METHOD_ORDER) + "      LB")
            for n in sorted({r["n"] for r in rows}):
                sel = select(rows, layout=lay, eps=e, n=n)
                vals = [statistics.fmean(r["norm_aoi"] for r in sel if r["method"] == m) for m in METHOD_ORDER]
                lb = statistics.fmean(r["lb_norm"] for r in instance_rows(sel))
                lines.append(f"  {fmt_group(n):<4} " + " ".join(f"{v:7.4f}" for v in vals) + f"  {lb:6.4f}")
    bad_feas = [r for r in rows if not (r["feasible"] and r["assigned_once"])]
    order_fail = 0
    by_inst: dict = {}
    for r in rows:
        by_inst.setdefault((r["layout"], r["n"], r["seed"], r["eps"]), {})[r["method"]] = r["obj"]
    for d in by_inst.values():
        tol = 1e-9 * max(1.0, abs(d["B2"]))
        pairs = [("B2", "B0"), ("B2", "B1"), ("B2", "B4"), ("P1", "B2"), ("P2", "P1")]
        order_fail += any(d[a] > d[b] + tol for a, b in pairs)
    ok = not bad_feas and order_fail == 0
    lines.append(f"自检：{len(by_inst)} 个实例，不可行或分配有误的方案 {len(bad_feas)} 个，"
                 f"顺序关系不成立的实例 {order_fail} 个 → {'通过' if ok else '未通过'}")
    gains = [g for v in gain_points(rows).values() for _, g in v]

    def pct(x: float) -> str:
        return f"{round(x, 1) + 0.0:.1f}%"   # 加 0.0 把舍入后的 -0.0 变成 0.0

    lines.append(f"本文方法相对两阶段的改善：均值 {pct(statistics.fmean(gains))}，最小 {pct(min(gains))}，"
                 f"最大 {pct(max(gains))}")
    return "\n".join(lines), ok


def plot_demo(out: Path, langs=("zh", "en")) -> list[Path]:
    """由示例的 CSV 与 JSON 出图：每种基本图型至少一张，中英文各一套

    :return: 生成的文件路径
    """
    rows = read_rows(out / "summary.csv")
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "records").glob("*.json"))]
    layouts = sorted({r["layout"] for r in rows})
    main_lay = "fireline" if "fireline" in layouts else layouts[0]
    alt_lay = next((x for x in layouts if x != main_lay), main_lay)
    eps_lo, eps_hi = min(r["eps"] for r in rows), max(r["eps"] for r in rows)
    main = select(rows, layout=main_lay, eps=eps_lo)
    nmax = max(r["n"] for r in main)
    case_recs = [r for r in recs if r["meta"]["layout"] == main_lay and r["meta"]["eps"] == eps_lo
                 and r["meta"]["n"] == nmax]
    case = case_recs[-1]
    files: list[Path] = []
    for lang in langs:
        setup(lang)
        d = out / "figures" / lang
        for metric in ("norm_aoi", "mean_aoi_s", "on_time_rate", "max_mission_min", "energy_kj", "stops_per_uav"):
            files += save(fig_metric(main, metric, lang), d, f"bar_{metric}")
        files += save(fig_metric(select(rows, layout=main_lay, eps=eps_hi), "norm_aoi", lang, kind="line",
                                 methods=("P2", "P1", "B2", "B1")), d, "line_norm_aoi")
        files += save(fig_metric(select(rows, layout=alt_lay, eps=eps_lo), "norm_aoi", lang), d, "bar_norm_aoi_alt")
        files += save(fig_aoi_box(case_recs, lang), d, "box_aoi")
        files += save(fig_aoi_cdf(case_recs, lang), d, "cdf_aoi")
        files += save(fig_convergence(case_recs, lang), d, "convergence")
        files += save(fig_lb_ratio(recs, lang), d, "box_lb_ratio")
        files += save(fig_gain_scatter(rows, lang), d, "scatter_gain")
        files += save(fig_route_maps(case, lang), d, "route_maps")
        files += save(fig_timeline(case, lang), d, "timeline")
        files += save(fig_uav_mission(case, lang), d, "bar_uav_mission")
    return files


def main(argv=None) -> int:
    """命令行入口：demo 子命令运行示例并出图，自检不通过时返回 1"""
    ap = argparse.ArgumentParser(description="方案一统一作图模块")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="在冒烟种子的小实例上运行全部方法并出示例图（中英文两套）")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--workers", type=int, default=1)
    d.add_argument("--plot-only", action="store_true", help="只用已有的 CSV 与 JSON 重画")
    a = ap.parse_args(argv)
    if not a.plot_only:
        run_demo(a.out, a.workers)
    text, ok = demo_report(read_rows(a.out / "summary.csv"))
    files = plot_demo(a.out)
    text += f"\n图：{len(files) // 2} 张（各有 PDF 与 PNG），在 {a.out / 'figures'}"
    (a.out / "demo_summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
