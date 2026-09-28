"""以统一的单栏柱状图和折线图导出六规模、五算法正式实验结果。"""
from __future__ import annotations

import argparse
import importlib.metadata
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.legend_handler import HandlerPatch
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import LogLocator, NullFormatter
from PIL import Image, ImageDraw, ImageOps
from prepare_multiscale_plot_data import (
    METHODS,
    ROOT,
    SCALES,
    build_tables,
    require,
    sha256,
    write_csv,
    write_json,
)

LOG = logging.getLogger(__name__)
OUT = ROOT / "paper_figures/multiscale_20260928"
WIDTH_MM = 88.9
HEIGHT_MM = 72.0
COLORS = ("#8C939B", "#A49AB6", "#76A79A", "#477FA6", "#D27B3E")
MARKERS = ("o", "s", "^", "D", "v")
LINESTYLES = ("--", ":", "-.", "--", "-")
# 辅助元素只承担不确定性和灰度辨识功能，用较细、较疏的笔画避免压过柱高。
PATTERN_COLOR = "#606871"
PATTERN_ALPHA = 0.48
PATTERN_WIDTH_PT = 0.30
PATTERN_STEP_PT = 11.0
ERROR_WIDTH_PT = 0.45
SCENARIO_POINT_AREA_PT2 = 6.0
SCENARIO_POINT_COLOR = "#68727C"
SCENARIO_POINT_ALPHA = 0.85


def pattern_geometry(x: float, y: float, width: float, height: float, kind: int, step: float):
    """直接计算矩形内部纹理，避免 PDF 平铺图案在几何验收中出现虚假的页外笔画。"""
    segments, dots = [], []
    if width <= 0 or height <= 0 or kind == 4:
        return segments, dots
    if kind in (0, 1):
        for intercept in np.arange(-width, height, step):
            start, stop = max(0, -intercept), min(width, height - intercept)
            if stop > start:
                y1, y2 = start + intercept, stop + intercept
                if kind == 1:
                    y1, y2 = height - y1, height - y2
                segments.append([(x + start, y + y1), (x + stop, y + y2)])
    elif kind == 2:
        dots = [(x + width / 2, y + value) for value in np.arange(step / 2, height, step)]
    else:
        segments = [[(x, y + value), (x + width, y + value)] for value in np.arange(step / 2, height, step)]
    return segments, dots


class MethodPatch(Rectangle):
    """保存算法纹理身份的图例色块。"""

    def __init__(self, method_index: int):
        super().__init__((0, 0), 1, 1, facecolor=COLORS[method_index], edgecolor="#41464C",
                         linewidth=0.35, label=METHODS[method_index])
        self.method_index = method_index


class MethodPatchHandler(HandlerPatch):
    """让图例和柱体使用相同的显式矢量纹理，不依赖 PDF 重复图案。"""

    def create_artists(self, legend, handle, xdescent, ydescent, width, height, fontsize, trans):
        artists = super().create_artists(legend, handle, xdescent, ydescent, width, height, fontsize, trans)
        rect = artists[0]
        x, y = rect.get_xy()
        segments, dots = pattern_geometry(x + 0.4, y + 0.4, rect.get_width() - 0.8,
                                          rect.get_height() - 0.8, handle.method_index, 7)
        if segments:
            artists.append(LineCollection(segments, transform=trans, color=PATTERN_COLOR,
                                          linewidths=PATTERN_WIDTH_PT, alpha=PATTERN_ALPHA))
        if dots:
            artists.append(Line2D(*zip(*dots), transform=trans, linestyle="none", marker="o",
                                  markersize=0.65, color=PATTERN_COLOR, alpha=PATTERN_ALPHA))
        return artists


def pattern_bar(ax, rect, kind: int, dpi: float) -> None:
    """以物理点为纹理间距，转换回数据坐标，确保各导出分辨率保持相同外观。"""
    box = rect.get_window_extent()
    margin = 0.4 * dpi / 72
    segments, dots = pattern_geometry(box.x0 + margin, box.y0 + margin,
                                      box.width - 2 * margin, box.height - 2 * margin, kind, PATTERN_STEP_PT * dpi / 72)
    inverse = ax.transData.inverted()
    if segments:
        ax.add_collection(LineCollection([inverse.transform(segment) for segment in segments],
                                         color=PATTERN_COLOR, linewidths=PATTERN_WIDTH_PT,
                                         alpha=PATTERN_ALPHA, zorder=3.2))
    if dots:
        values = inverse.transform(dots)
        ax.plot(values[:, 0], values[:, 1], linestyle="none", marker="o", markersize=0.65,
                color=PATTERN_COLOR, alpha=PATTERN_ALPHA, zorder=3.2)


@dataclass(frozen=True)
class FigureSpec:
    """每张图绑定指标、样本集合、单位变换和证据用途，避免模板替换时串用数据。"""
    name: str
    scope: str
    metric: str
    ylabel: str
    scale: float
    limits: tuple[float, float]
    caption: str
    role: str
    kind: str = "bar"


SPECS = (
    FigureSpec("fig01_energy_common", "common", "stage1_energy_j", "UAV energy (kJ)", 0.001, (0, 320),
               "不同任务规模下的 UAV 能耗（五算法共同有效样本）。", "主比较：能耗"),
    FigureSpec("fig02_qualification", "conditional", "both_stages_qualified_rate", "Qualified runs (%)", 100, (0, 108),
               "不同任务规模下的两阶段数值验收合格率。", "主比较：有效解覆盖与失败边界"),
    FigureSpec("fig03_p95_delay_common", "common", "p95_delay_s", "P95 task delay (s)", 1, (0, 430),
               "不同任务规模下的运行内 P95 任务时延（共同有效样本）。", "性能边界：尾部时延"),
    FigureSpec("fig04_cpu_common", "common", "normalized_mec_cpu", "Normalized MEC CPU allocation", 1, (0, 1.6),
               "不同任务规模下的 Stage-2 归一化 MEC CPU 分配量（共同有效样本）。", "资源代价：CPU 分配"),
    FigureSpec("fig05_construction_search_time", "conditional", "original_construction_search_s",
               "Construction + search time (s)", 1, (0.002, 100),
               "不同任务规模下的初始化与搜索耗时（对数纵轴）。", "计算代价：固定搜索配置", "line"),
    FigureSpec("fig06_paired_energy_saving", "paired", "stage1_energy_j", "Energy saving vs B-ALNS (kJ)", -0.001, (0, 7.8),
               "ESI-ALNS 相对 B-ALNS 的配对节能量；点为场景均值。", "增量证据：同轨迹探索后的精英强化", "paired_bar"),
    FigureSpec("fig07_stage2_cpu_reduction", "common", "cpu_stage2_minus_stage1",
               "Reduction in normalized MEC CPU", -1, (0, 1.65),
               "同一离散结构下 Stage-2 相对 Stage-1 的 CPU 分配减少量。", "机制证据：能耗容差内的资源细化"),
    FigureSpec("figS01_mean_delay_common", "common", "mean_delay_s", "Mean task delay (s)", 1, (0, 260),
               "不同任务规模下的平均任务时延（共同有效样本）。", "补充：平均时延"),
    FigureSpec("figS02_offload_common", "common", "offload_ratio", "Offloaded tasks (%)", 100, (0, 21),
               "不同任务规模下的任务卸载比例（共同有效样本）。", "补充：卸载结构"),
    FigureSpec("figS03_energy_conditional", "conditional", "stage1_energy_j", "UAV energy (kJ)", 0.001, (0, 320),
               "不同任务规模下各算法自身有效样本的条件能耗均值。", "补充：共同子集筛选对结果的影响"),
    FigureSpec("figS04_route_common", "common", "total_distance_m", "Total flight distance (km)", 0.001, (0, 16.5),
               "不同任务规模下的总飞行路径长度（共同有效样本）。", "补充：路径结构与主要能耗来源"),
)


def configure() -> None:
    """固定可编辑字体与物理尺寸，灰度打印通过纹理或点形区分五算法。"""
    font_manager.findfont("Arial", fallback_to_default=False)
    plt.rcParams.update({
        "font.family": "Arial", "font.size": 8, "axes.labelsize": 8,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7.4,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.65,
        "axes.edgecolor": "#41464C", "text.color": "#252A30", "axes.labelcolor": "#252A30",
        "xtick.color": "#41464C", "ytick.color": "#41464C", "xtick.major.width": 0.6,
        "ytick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "legend.frameon": False, "hatch.linewidth": 0.4, "figure.dpi": 150,
        "savefig.dpi": 600, "figure.facecolor": "white", "axes.facecolor": "white",
    })


def point(row: dict, spec: FigureSpec) -> dict:
    """反向指标同时反转区间端点；保留原始指标及运行等权值以供追溯。"""
    require(row["scenario_equal_mean"] is not None, f"{spec.name} 缺少有效均值")
    bounds = row["descriptive_scenario_bootstrap_95"]
    interval = sorted(value * spec.scale for value in bounds) if bounds else (None, None)
    return {"figure": spec.name, "scope": spec.scope, "tasks": row["tasks"], "method": row["method"],
            "source_metric": spec.metric, "scale_factor": spec.scale,
            "mean": row["scenario_equal_mean"] * spec.scale,
            "ci_low": interval[0], "ci_high": interval[1],
            "run_equal_mean": row["run_equal_mean"] * spec.scale,
            "valid_observations": row["valid_observations"],
            "expected_observations": row["expected_observations"],
            "independent_scenarios": row["independent_scenarios"],
            "observation_unit": "actual_method_runs" if spec.scope == "conditional" else "matched_seed_blocks",
            "interval": "descriptive_95_percent_scenario_bootstrap" if bounds else "not_estimated_n1"}


def decorate(fig, ax, spec: FigureSpec, points: list[dict]) -> None:
    """图例放在独立顶端留白中，样本数写入刻度，避免与柱体和误差线碰撞。"""
    if spec.kind == "paired_bar":
        handles = [Patch(facecolor=COLORS[-1], edgecolor="#41464C", linewidth=0.35, label="ESI-ALNS"),
                   Line2D([], [], marker="o", color=SCENARIO_POINT_COLOR, linestyle="none",
                          markersize=np.sqrt(SCENARIO_POINT_AREA_PT2), markeredgewidth=0.4,
                          markerfacecolor="white", alpha=SCENARIO_POINT_ALPHA, label="Scenario mean")]
    elif spec.kind == "line":
        handles = [Line2D([], [], color=color, marker=marker, linestyle=style, markersize=3.3,
                          markerfacecolor="white", linewidth=1.1, label=method)
                   for method, color, marker, style in zip(METHODS, COLORS, MARKERS, LINESTYLES)]
    else:
        handles = [MethodPatch(i) for i in range(len(METHODS))]
    if len(handles) == 5:
        handles = [handles[i] for i in (0, 3, 1, 4, 2)]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.53, 0.998),
               ncols=3 if len(handles) == 5 else 2, handlelength=1.65,
               handletextpad=0.45, columnspacing=0.9, labelspacing=0.42,
               handler_map={MethodPatch: MethodPatchHandler()})
    labels = [str(k) for k in SCALES]
    if spec.scope == "common":
        ns = [next(p["independent_scenarios"] for p in points if p["tasks"] == k) for k in SCALES]
        labels = [f"{k}\nn={n}" for k, n in zip(SCALES, ns)]
        note = "Common-valid scenes; n=1: no interval"
    elif spec.scope == "paired":
        note = "8 paired scenes / K; 95% descriptive intervals"
    elif spec.metric == "original_construction_search_s":
        note = "8 scenes / K; original search run; log scale"
    elif spec.metric == "both_stages_qualified_rate":
        note = "8 scenes / K; all scheduled runs retained"
    else:
        note = "Method-specific valid sets; n=1 at K=80 for 3 baselines"
    fig.text(0.565, 0.827, note, ha="center", va="center", fontsize=6.5)
    ax.set_xticks(np.arange(len(SCALES)), labels)
    ax.set_xlim(-0.58, 5.58)
    ax.set_ylim(*spec.limits)
    ax.set_xlabel("Number of tasks, K", labelpad=3)
    ax.set_ylabel(spec.ylabel, labelpad=4)
    ax.grid(axis="y", color="#DDE2E7", linewidth=0.45, zorder=0)
    ax.set_axisbelow(True)
    if spec.metric == "both_stages_qualified_rate":
        ax.set_yticks([0, 25, 50, 75, 100])
    if spec.kind == "line":
        lower_bounds = np.array([p["ci_low"] for p in points])
        if np.any(lower_bounds <= 0):
            raise ValueError("对数耗时图包含非正值")
        ax.set_yscale("log")
        ax.set_yticks([0.01, 0.1, 1, 10, 100], ["0.01", "0.1", "1", "10", "100"])
        ax.yaxis.set_minor_locator(LogLocator(base=10, subs=[2, 5]))
        ax.yaxis.set_minor_formatter(NullFormatter())


def draw(spec: FigureSpec, stats: dict) -> tuple[object, list[dict], list[dict]]:
    """仅绘制六个真实规模；误差条不连接或外推缺失数据，不将失败记成零。"""
    fig, ax = plt.subplots(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4))
    fig.subplots_adjust(left=0.195, right=0.98, bottom=0.225, top=0.785)
    methods = ("B-ALNS",) if spec.kind == "paired_bar" else METHODS
    points, scene_points, patterned_bars = [], [], []
    for i, method in enumerate(methods):
        rows = [stats[spec.scope, k, method, spec.metric] for k in SCALES]
        data = [point(row, spec) for row in rows]
        points.extend(data)
        x = np.arange(len(SCALES), dtype=float)
        y = np.array([p["mean"] for p in data])
        low = np.array([p["ci_low"] if p["ci_low"] is not None else p["mean"] for p in data])
        high = np.array([p["ci_high"] if p["ci_high"] is not None else p["mean"] for p in data])
        # 固定绘图区并做数值检查；新数据溢出时停止，不能无声裁掉不利结果。
        require(np.all(low >= spec.limits[0]) and np.all(high <= spec.limits[1]),
                f"{spec.name}/{method} 的区间超出预设纵轴")
        if spec.kind == "line":
            ax.plot(x, y, color=COLORS[i], marker=MARKERS[i], linestyle=LINESTYLES[i],
                    markersize=3.7, markerfacecolor="white", markeredgewidth=0.8, linewidth=1.1, zorder=3 + i / 10)
        else:
            offset = 0 if spec.kind == "paired_bar" else (i - 2) * 0.145
            x += offset
            bars = ax.bar(x, y, width=0.52 if spec.kind == "paired_bar" else 0.131,
                          color=COLORS[-1] if spec.kind == "paired_bar" else COLORS[i],
                          edgecolor="#41464C", linewidth=0.35, zorder=3)
            if spec.kind != "paired_bar":
                patterned_bars.extend((bar, i) for bar in bars)
        has_interval = np.array([p["ci_low"] is not None for p in data])
        ax.errorbar(x[has_interval], y[has_interval],
                    yerr=np.vstack((y - low, high - y))[:, has_interval], fmt="none",
                    ecolor=COLORS[i] if spec.kind == "line" else "#4F555D",
                    elinewidth=ERROR_WIDTH_PT, capsize=0.75, capthick=ERROR_WIDTH_PT, alpha=0.9, zorder=5)
        for j, row in enumerate(rows):
            for index, scene in enumerate(row["per_scenario"]):
                value = scene["mean"] * spec.scale
                scene_points.append({"figure": spec.name, "tasks": row["tasks"], "method": method,
                                     "scenario_seed": scene["scenario_seed"],
                                     "observations": scene["observations"], "value": value})
                if spec.kind == "paired_bar":
                    # 仅为分散场景点设置固定横向偏移；横坐标仍归属同一真实规模。
                    require(spec.limits[0] <= value <= spec.limits[1], "配对场景点超出纵轴")
                    ax.scatter(j + np.linspace(-0.19, 0.19, len(row["per_scenario"]))[index], value,
                               s=SCENARIO_POINT_AREA_PT2, facecolors="white", edgecolors=SCENARIO_POINT_COLOR,
                               linewidths=0.4, alpha=SCENARIO_POINT_ALPHA, zorder=6, clip_on=False)
    decorate(fig, ax, spec, points)
    fig.canvas.draw()
    for rect, method_index in patterned_bars:
        pattern_bar(ax, rect, method_index, fig.dpi)
    return fig, points, scene_points


def export(fig, spec: FigureSpec, out: Path, alignment) -> dict:
    """按原定尺寸导出，保留所有可编辑文字；tight 裁切会改变单栏尺寸，故不用。"""
    fig.canvas.draw()
    alignment(fig, json_out=str(out / "qa" / f"{spec.name}.alignment.json"), strict=True)
    for ext in ("pdf", "svg", "png", "tiff"):
        (out / ext).mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "pdf" / f"{spec.name}.pdf",
                metadata={"Title": spec.name, "Creator": "Matplotlib / verified multiscale experiment"})
    fig.savefig(out / "svg" / f"{spec.name}.svg")
    fig.savefig(out / "png" / f"{spec.name}.png", dpi=600)
    fig.savefig(out / "tiff" / f"{spec.name}.tiff", dpi=600, pil_kwargs={"compression": "tiff_lzw"})
    plt.close(fig)
    return {**asdict(spec), "width_mm": WIDTH_MM, "height_mm": HEIGHT_MM, "png_dpi": 600,
            "font": "Arial", "minimum_font_pt": 6.5,
            "exports": {ext: {"path": f"{ext}/{spec.name}.{ext}", "sha256": sha256(out / ext / f"{spec.name}.{ext}")}
                        for ext in ("pdf", "svg", "png", "tiff")}}


def previews(out: Path, registry: list[dict]) -> None:
    """用 Python 生成逐页矢量合订本和灰度预览；预览不作为投稿原图。"""
    import pymupdf
    combined = pymupdf.open()
    for spec in registry:
        with pymupdf.open(out / "pdf" / f"{spec['name']}.pdf") as source:
            combined.insert_pdf(source)
    combined.save(out / "all_figures.pdf")
    combined.close()
    for page, offset in enumerate(range(0, len(registry), 4), 1):
        sheet = Image.new("RGB", (1050, 960), "#E8EBEE")
        draw_text = ImageDraw.Draw(sheet)
        for position, spec in enumerate(registry[offset:offset + 4]):
            with Image.open(out / "png" / f"{spec['name']}.png") as source:
                thumb = source.convert("RGB")
                thumb.thumbnail((510, 413), Image.Resampling.LANCZOS)
                x, y = 15 + position % 2 * 520, 35 + position // 2 * 470
                sheet.paste(thumb, (x, y))
                draw_text.text((x, y - 21), spec["name"], fill="#202830")
        sheet.save(out / "qa" / f"preview_{page:02d}.png")
        ImageOps.grayscale(sheet).save(out / "qa" / f"preview_{page:02d}_gray.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--qa-scripts", type=Path, required=True,
                        help="nature-figure 的 scripts 目录，用于运行排版验收")
    args = parser.parse_args()
    sys.path.insert(0, str(args.qa_scripts.resolve()))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "qa").mkdir(exist_ok=True)
    _, stats, audit = build_tables(args.output)
    LOG.info("已通过 %d 条汇总对照；原始记录 %d 条", audit["summary_entries_cross_checked"], audit["records"])
    configure()
    registry, points, scenes = [], [], []
    for spec in SPECS:
        fig, figure_points, scene_points = draw(spec, stats)
        registry.append(export(fig, spec, args.output, require_matplotlib_panel_alignment))
        points.extend(figure_points)
        scenes.extend(scene_points)
        LOG.info("已导出 %s", spec.name)
    write_csv(args.output / "data/plotted_points.csv", points)
    write_csv(args.output / "data/plotted_scenario_means.csv", scenes)
    write_json(args.output / "figure_manifest.json", {"figures": registry, "source_verification": audit,
               "style_revision": "simplified_auxiliary_marks",
               "style": {"pattern_step_pt": PATTERN_STEP_PT, "pattern_alpha": PATTERN_ALPHA,
                         "pattern_width_pt": PATTERN_WIDTH_PT, "error_width_pt": ERROR_WIDTH_PT,
                         "scenario_point_area_pt2": SCENARIO_POINT_AREA_PT2, "scenario_point_alpha": SCENARIO_POINT_ALPHA},
               "python": sys.version.split()[0],
               "libraries": {key: importlib.metadata.version(key) for key in ("matplotlib", "numpy", "pymupdf", "pillow")},
               "scripts": {name: sha256(Path(__file__).with_name(name)) for name in (
                   "plot_multiscale_20260928.py", "prepare_multiscale_plot_data.py", "qa_multiscale_figures.py")}})
    previews(args.output, registry)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("fontTools.subset").setLevel(logging.WARNING)
    try:
        main()
    except Exception:
        # 保存异常堆栈及当前图名，防止半生成的图包被误认为已验收成果。
        LOG.exception("绘图或数据验收失败，本轮图包不可交付")
        raise
