"""从冻结 CSV 重建实验图，并复制已确认的模型、框架及 GIS 示意图。"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from pathlib import Path
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
METHODS = ["GR-MR", "FTR-NM", "RGA-MR", "SA-MR", "DPSO-MR", "B-ALNS", "ESI-ALNS"]
COLORS = ["#5F6871", "#8062A3", "#168875", "#986B35", "#B04A77", "#237DB0", "#D26420"]
STYLES = ["--", "-", "--", "-", "--", "--", "-"]
MARKERS = ["o", "s", "^", "v", "D", "s", "o"]
# 图型沿用定稿：趋势用线，离散条件和消融用柱；柱状图均包含零基线。
LABELS = {
    3: "UAV energy (kJ)", 4: "Qualified runs (%)", 5: "Paired energy saving (kJ)",
    6: "Refinement time (s)", 7: "Mean task delay (s)", 8: "P95 task delay (s)",
    9: "Normalized MEC CPU (1)", 10: "MEC CPU reduction (1)", 11: "Offloaded tasks (%)",
    12: "Total flight distance (km)", 13: "Full ESI advantage (%)",
    14: "Qualified runs (%)", 15: "Qualified-run energy (kJ)",
    16: "Qualified runs (%)", 17: "Qualified-run energy (kJ)",
    18: "Gap to reference (%)", 20: "Qualified runs (%)", 21: "Qualified-run energy (kJ)",
    22: "P95 task delay (s)", 23: "Normalized MEC CPU (1)",
}
LINES = {3, 6, 12, 17}
AXES = {3: ((114, 268), list(range(120, 261, 20))),
        7: ((0, 235), [0, 50, 100, 150, 200]),
        8: ((0, 390), [0, 100, 200, 300]),
        12: ((6, 13.8), list(range(6, 14))),
        17: ((226, 233), list(range(227, 233)))}


def number(value: str) -> float:
    """空单元格与 NaN 保持缺失，绝不变成零能耗或零预留。"""
    return float(value) if value else math.nan


def load_series(path: Path, figure: int) -> tuple[np.ndarray, dict, str]:
    """核对每个方法和设置仅有一条统计记录，避免图形隐式合并重复。"""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    field = "level" if 14 <= figure <= 17 else "scenario_seed" if figure >= 20 else "tasks"
    group = "profile" if figure == 13 else "method"
    if figure == 18:
        # 参考差距图使用三场景各自的均值；逐运行值仍完整保留在源表。
        xs = np.array(sorted({int(r["scenario"]) for r in rows}))
        values = []
        for x in xs:
            scene = [r for r in rows if int(r["scenario"]) == x]
            means = {float(r["scenario_mean_pct"]) for r in scene}
            if len(means) != 1:
                raise ValueError(f"经验参考场景均值不唯一：{x}")
            value = means.pop()
            if not math.isclose(value, np.mean([float(r["gap_pct"]) for r in scene]), rel_tol=1e-12):
                raise ValueError(f"经验参考均值与逐运行值不符：{x}")
            values.append(value)
        return xs, {"Standard search": np.array(values)}, "Workload scenario"
    xs = np.array(sorted({float(r[field]) for r in rows}))
    groups = (["no-route", "no-contact", "no-batch", "no-widening"] if figure == 13
              else ["ESI-ALNS"] if figure in (5, 6) else METHODS)
    if len(rows) != len(xs) * len(groups):
        raise ValueError(f"图 {figure} 记录数量不符")
    series = {}
    for method in groups:
        values = []
        for x in xs:
            selected = [r for r in rows if float(r[field]) == x
                        and (figure in (5, 6) or r[group] == method)]
            if len(selected) != 1:
                raise ValueError(f"图 {figure} {method} 设置 {x} 记录不唯一")
            values.append(number(selected[0]["mean"]))
        series[method] = np.array(values)
    xlabel = ("Contact limit per UAV" if figure in (14, 15) else
              "Bandwidth multiplier (1)" if figure in (16, 17) else
              "Workload scenario (same GIS map)" if figure >= 20 else "Number of tasks")
    return xs, series, xlabel


def draw(path: Path, output: Path, formats: list[str]) -> dict:
    """样式只改变显示，不平滑、抖动、局部放大或改变源值。"""
    figure = int(path.name[3:5])
    xs, series, xlabel = load_series(path, figure)
    is_line = figure in LINES
    fig, ax = plt.subplots(figsize=(3.5, 57 / 25.4))
    fig.subplots_adjust(left=.16, right=.987, bottom=.17, top=.805)
    ax.set_xlabel(xlabel, labelpad=2)
    ax.set_ylabel(LABELS[figure], labelpad=2)
    ax.tick_params(length=2, pad=2, width=.5)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(.55)
    handles, labels = [], []
    count = len(series)
    step = .8 / count
    missing = zero = plotted = 0
    for index, (method, values) in enumerate(series.items()):
        color_index = METHODS.index(method) if method in METHODS else index
        color = COLORS[color_index]
        if is_line:
            line, = ax.plot(xs, values, color=color, linestyle=STYLES[color_index],
                            marker=MARKERS[color_index], markerfacecolor="white",
                            markeredgewidth=.55, markersize=3, linewidth=1 if method == "ESI-ALNS" else .8)
            if not np.array_equal(line.get_ydata(), values, equal_nan=True):
                raise ValueError("折线与源值不一致")
            handles.append(Line2D([], [], color=color, ls=STYLES[color_index],
                                  marker=MARKERS[color_index], mfc="white", ms=2.7, mew=.55, lw=.9))
        else:
            positions = np.arange(len(xs)) + (index - (count - 1) / 2) * step
            for x, value in zip(positions, values):
                if math.isfinite(value):
                    patch, = ax.bar(x, value, width=step * .88, color=color,
                                    edgecolor="white", linewidth=.18)
                    if patch.get_height() != value:
                        raise ValueError("柱高与源值不一致")
                    if value == 0:
                        ax.plot(x, 0, "o", ms=2.4, mfc="white", mec=color, mew=.7, clip_on=False)
                else:
                    # x 是缺失标记而非零值柱；以图内说明区分缺失和真实零。
                    ax.plot(x, 0, "x", ms=2.6, mew=.7, color=color, clip_on=False)
            handles.append(Patch(facecolor=color, edgecolor="none"))
        missing += int(np.count_nonzero(~np.isfinite(values)))
        zero += int(np.count_nonzero(values == 0))
        plotted += int(np.count_nonzero(np.isfinite(values)))
        labels.append({"no-route": "No route", "no-contact": "No contact",
                       "no-batch": "No batch", "no-widening": "No widening"}.get(method, method))
    if is_line:
        ax.set_xticks(xs)
        ax.margins(x=.05)
    else:
        ax.set_xticks(np.arange(len(xs)), [f"{x:g}" for x in xs])
        ax.set_xlim(-.57, len(xs) - .43)
        finite = [v for values in series.values() for v in values if math.isfinite(v)]
        # 支持带符号的机制差；其余非负统计采用零基线。
        lower, upper = min([0., *finite]), max([0., *finite])
        span = max(upper - lower, .1)
        ax.set_ylim(lower - .08 * span if lower < 0 else 0, upper + .16 * span)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    if figure in AXES:
        limits, ticks = AXES[figure]
        ax.set(ylim=limits, yticks=ticks)
        for values in series.values():
            finite = values[np.isfinite(values)]
            if np.any((finite < limits[0]) | (finite > limits[1])):
                raise ValueError(f"图 {figure} 固定纵轴裁掉了数据，须重新审查刻度")
    fig.legend(handles, labels, ncol=4, loc="upper center", bbox_to_anchor=(.55, .995),
               columnspacing=.8, handlelength=1.4, handletextpad=.35,
               borderpad=.3, labelspacing=.4, frameon=False)
    if missing:
        # 说明放在图例下的独立空白带，避免盖住柱体或曲线。
        note = "Other methods: no validated runs" if figure == 17 else "x: no validated runs"
        fig.text(.56, .805, note, ha="center", va="bottom", fontsize=5.8)
    fig.canvas.draw()
    if len(fig.axes) != 1:
        raise ValueError("当前图件要求单一坐标区，禁止局部放大")
    for suffix in formats:
        directory = output / suffix
        directory.mkdir(parents=True, exist_ok=True)
        # 显式声明各导出格式，便于源码检查和出版格式核验。
        if suffix == "pdf":
            fig.savefig(directory / f"{path.stem}.pdf", facecolor="white")
        elif suffix == "svg":
            fig.savefig(directory / f"{path.stem}.svg", facecolor="white")
        elif suffix == "png":
            fig.savefig(directory / f"{path.stem}.png", dpi=600, facecolor="white")
        else:
            fig.savefig(directory / f"{path.stem}.tiff", dpi=600, facecolor="white",
                        pil_kwargs={"compression": "tiff_lzw"})
    plt.close(fig)
    return {"figure": figure, "plotted_values": plotted, "missing_values": missing,
            "zero_values": zero, "axes_count": 1, "insets": False,
            "alignment": "not applicable: single panel", "values_checked": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/figures")
    parser.add_argument("--formats", nargs="+", choices=["pdf", "svg", "png", "tiff"],
                        default=["pdf", "svg", "png", "tiff"])
    args = parser.parse_args()
    if args.output_dir.resolve().is_relative_to((ROOT / "figures").resolve()):
        raise ValueError("冻结图件禁止覆盖，请使用独立输出目录")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("fontTools").setLevel(logging.WARNING)
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"],
                         "font.size": 7, "axes.labelsize": 7, "xtick.labelsize": 6.5,
                         "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
                         "pdf.fonttype": 42, "svg.fonttype": "none", "legend.frameon": False})
    reports = []
    for path in sorted((ROOT / "figures/data").glob("fig*.csv")):
        reports.append(draw(path, args.output_dir, args.formats))
        logging.info("已重建 %s", path.stem)
    # SVG 是这三幅经人工确认的矢量源资产；保持图1/2原布局，不自动重画。
    for number_ in (1, 2, 19):
        for suffix in args.formats:
            source, = (ROOT / "figures" / suffix).glob(f"fig{number_:02d}_*.{suffix}")
            shutil.copy2(source, args.output_dir / suffix / source.name)
    (args.output_dir / "render_report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
