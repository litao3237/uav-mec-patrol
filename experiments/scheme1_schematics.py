"""方案一论文示意图 S1–S4（实验规划 29_ 第 5.2 节）：场景、时间线与 AoI、算法框架、实验流程

S1 用 E7 典型案例（种子 113）的真实几何：火线与观测点、地面站与覆盖圈、本文方法的一条航线；
S2 用示意数字说明一架无人机"采集 → 携带 → 停靠上传"的时间线与 AoI 的定义；S3、S4 为流程图。
样式沿用统一作图模块（字体、墨色、方法色），中英文各一套，各存 PDF 与 PNG
"""

from __future__ import annotations

import json
import math
import statistics
from itertools import pairwise
from pathlib import Path

import scheme1_plots as sp
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Patch, Polygon

INK = sp.INK
FIRE_LINE, FIRE_FILL = "#c8553d", "#f7e1d9"   # 火线与燃烧区；不与方法色（P1 的橙色）混用：S1 只画本文方法

TEXT = {
    "zh": {
        "fire": "火线与观测点：采集态势数据\n80–160 Mbit，δ = 300–600 s", "cover": "地面站覆盖圈：\n飞进圈内才能上传\n（≥ 10 Mbps）",
        "stop": "停靠上传", "alarm": "告警：低速链路实时回传", "depot": "基地", "uav": "无人机航线（SCOUT，一架）",
        "fire_short": "火线（燃烧区）",
        "station_note": "地面站", "x": "x（km）", "y": "y（km）",
        "fly": "飞行", "detour": "绕路去上传点", "collect": "采集（悬停）", "upload": "上传（悬停）",
        "carry": "采集到送达（AoI）", "overtime": "超时部分", "deadline": "时效窗截止", "lane_uav": "无人机",
        "item": "数据", "time": "时间（min）", "aoi_def": "AoI$_i = d_i - c_i$（$c_i$：采集完成，$d_i$：送达）",
        "obj_def": "平均归一化 AoI $= \\frac{1}{N}\\sum_i$ AoI$_i / \\delta_i$",
        "order": "停靠时按 $D_i\\delta_i$ 升序逐份上传，每份传完即送达",
    },
    "en": {
        "fire": "Fire line and\nobservation points:\n80–160 Mbit, δ = 300–600 s",
        "cover": "Ground-station\ncoverage: upload\nonly inside\n(≥ 10 Mbps)", "stop": "Upload stop",
        "alarm": "Alarms: low-rate link\nin real time", "depot": "Depot", "uav": "UAV route (SCOUT, one UAV)",
        "fire_short": "Fire line (burning area)",
        "station_note": "Ground station", "x": "x (km)", "y": "y (km)",
        "fly": "Fly", "detour": "Detour to upload point", "collect": "Collect (hover)", "upload": "Upload (hover)",
        "carry": "Collect to deliver (AoI)", "overtime": "Overtime", "deadline": "Deadline", "lane_uav": "UAV",
        "item": "Item", "time": "Time (min)", "aoi_def": "AoI$_i = d_i - c_i$ ($c_i$: collected, $d_i$: delivered)",
        "obj_def": "Mean normalized AoI $= \\frac{1}{N}\\sum_i$ AoI$_i / \\delta_i$",
        "order": "At a stop, items are uploaded in ascending $D_i\\delta_i$;\neach is delivered when its upload ends",
    },
}


def t(lang: str, key: str) -> str:
    """示意图的文字"""
    return TEXT[lang][key]


# ---------------------------------------------------------------------------
# S1 场景
# ---------------------------------------------------------------------------

# 标注文字的位置（km）与对齐方式，按 E7 典型案例（种子 113）的几何放在目标旁的空白处，引线尽量短；换案例时需重新调整
S1_LABELS = {"fire": (1.84, 1.72, "left"), "cover": (2.2, 2.45, "left"), "stop": (1.1, 2.9, "left"),
             "alarm": (0.95, 0.72, "left")}


def _pick_uav(out: dict) -> int:
    """S1 只画一架机：取途中停靠次数最少（至少一次）的机，图面最清楚；相同时取机号小的"""
    cand = [(sum(1 for k, _ in st if int(k) < len(r)), u) for u, (r, st) in enumerate(zip(out["routes"], out["stops"]))
            if r and any(int(k) < len(r) for k, _ in st)]
    return min(cand)[1] if cand else 0


def fig_s1_scene(rec: dict, lang: str):
    """S1：场景示意（真实案例几何 + 一架机的航线 + 标注）

    :param rec: E7 典型案例的记录（含 geometry 与 P2 的航线、停靠）
    :param lang: 语言
    """
    g, km = rec["geometry"], 1e-3
    fig, ax = sp.new_fig(width=sp.SINGLE_W, height=3.35)
    for name, sx, sy, r in g["stations"]:
        ax.add_patch(Circle((sx * km, sy * km), r * km, facecolor=INK["wash"], edgecolor=INK["axis"], linewidth=0.5,
                            zorder=0))
        ax.plot(sx * km, sy * km, marker="^", markersize=4.5, color=INK["secondary"], linestyle="none", zorder=3)
        ax.annotate(name, (sx * km, sy * km), xytext=(0, -9), textcoords="offset points", ha="center", fontsize=6,
                    color=INK["secondary"], zorder=3)
    pts = g["tasks"]
    cx, cy = statistics.fmean(p[0] for p in pts), statistics.fmean(p[1] for p in pts)
    ring = sorted(range(len(pts)), key=lambda i: math.atan2(pts[i][1] - cy, pts[i][0] - cx))
    ax.add_patch(Polygon([(pts[i][0] * km, pts[i][1] * km) for i in ring], closed=True, facecolor=FIRE_FILL,
                         edgecolor=FIRE_LINE, linewidth=1.3, zorder=1))
    ax.plot([p[0] * km for p in pts], [p[1] * km for p in pts], linestyle="none", marker="o", markersize=2.0,
            color=INK["primary"], zorder=4)
    out = rec["methods"]["P2"]
    u = _pick_uav(out)
    route, stops = out["routes"][u], {int(k): int(q) for k, q in out["stops"][u]}
    color, dep = sp.COLORS["P2"], g["depot"]
    pos, from_stop, stop_pts = dep, False, []
    seq = []
    for k, gid in enumerate(route, start=1):
        seq.append((pos, pts[gid], from_stop, pos is dep))
        pos, from_stop = pts[gid], False
        if k in stops:
            q = stops[k]
            tgt = dep if q == -1 else g["points"][q]
            seq.append((pos, tgt, q != -1, q == -1))
            if q != -1:
                stop_pts.append(tgt)
            pos, from_stop = tgt, q != -1
    if pos is not dep:
        seq.append((pos, dep, from_stop, True))
    for a, b, dashed, transit in seq:
        ax.plot([a[0] * km, b[0] * km], [a[1] * km, b[1] * km], color=sp.tint(color, 0.45) if transit else color,
                linewidth=0.8 if transit else 1.1, linestyle=(0, (2.5, 1.5)) if dashed else "-", zorder=5)
    for s in stop_pts:
        ax.plot(s[0] * km, s[1] * km, marker="D", markersize=4.5, markerfacecolor=INK["surface"], markeredgecolor=color,
                markeredgewidth=1.0, linestyle="none", zorder=6)
    first = pts[route[0]]
    mid = ((dep[0] + first[0]) / 2 * km, (dep[1] + first[1]) / 2 * km)
    ax.plot(*mid, marker="X", markersize=6, color=color, linestyle="none", zorder=7)
    # 告警走低速链路：从火线最低处的观测点到基地画点线（示意，不在优化模型内）；不从所画航线上取点，免得与航线重叠
    far = min(pts, key=lambda p: p[1])
    ax.plot([far[0] * km, dep[0] * km], [far[1] * km, dep[1] * km], color=INK["secondary"], linewidth=0.8,
            linestyle=(0, (1, 1.6)), zorder=2)
    ax.plot(dep[0] * km, dep[1] * km, marker="s", markersize=5, color=INK["primary"], linestyle="none", zorder=8)
    ax.annotate(t(lang, "depot"), (dep[0] * km, dep[1] * km), xytext=(6, -2), textcoords="offset points", fontsize=6.5,
                va="top")
    arrow = {"arrowstyle": "-", "color": INK["secondary"], "linewidth": 0.5, "shrinkA": 1, "shrinkB": 2}
    right = max(pts, key=lambda p: p[0])
    e3 = max(g["stations"], key=lambda s: s[2])
    # 引线的目标点都要落在坐标范围内，否则 annotate 默认不画（覆盖圈取 E3 圈的右边缘）
    targets = {"fire": (right[0] * km, right[1] * km), "cover": ((e3[1] + e3[3]) * km, e3[2] * km),
               "stop": (stop_pts[0][0] * km, stop_pts[0][1] * km) if stop_pts else None,
               "alarm": ((far[0] + dep[0]) / 2 * km, (far[1] + dep[1]) / 2 * km)}
    for key, (x, y, ha) in S1_LABELS.items():
        if targets[key] is None:
            continue
        ax.annotate(t(lang, key), targets[key], xytext=(x, y), fontsize=5.8, ha=ha, va="center", arrowprops=arrow,
                    color=INK["primary"], zorder=9, linespacing=1.25)
    ax.set_xlim(0, sp.load_scheme1_params(str(sp.CONFIG)).width_m * km)
    ax.set_ylim(0, 3.0)
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_xlabel(t(lang, "x"))
    ax.set_ylabel(t(lang, "y"))
    handles = [Line2D([], [], color=color, linewidth=1.1, label=t(lang, "uav")),
               Line2D([], [], linestyle="none", marker="X", markersize=6, color=color,
                      label=sp.label(lang, "uav")),
               Patch(facecolor=FIRE_FILL, edgecolor=FIRE_LINE, linewidth=1.0, label=t(lang, "fire_short"))]
    sp.legend_top(fig, handles, ncol=3)
    return fig


# ---------------------------------------------------------------------------
# S2 一架无人机的时间线与 AoI 定义（示意数字）
# ---------------------------------------------------------------------------

# 活动段（分钟）：(开始, 结束, 类型, 数据)；类型 fly / detour / collect / upload。数字只为示意，
# 采集 10 s、上传约 12–15 s（约 120–150 Mbit ÷ 10 Mbps）与模型参数同量级
S2_ACTS = [(0.0, 1.5, "fly", None), (1.5, 1.67, "collect", "i"), (1.67, 3.0, "fly", None), (3.0, 3.17, "collect", "j"),
           (3.17, 4.4, "detour", None), (4.4, 4.6, "upload", "i"), (4.6, 4.85, "upload", "j"),
           (4.85, 6.5, "fly", None), (6.5, 6.67, "collect", "k"), (6.67, 9.0, "fly", None), (9.0, 9.22, "upload", "k")]
S2_DELTA = {"i": 5.0, "j": 5.5, "k": 2.2}      # 时效窗（分钟）；k 故意取短，示意超时的画法


def fig_s2_timeline(lang: str):
    """S2：一架无人机的"采集 → 携带 → 停靠上传"时间线（上）与每份数据的 AoI（下）"""
    fig, ax = sp.new_fig(width=sp.DOUBLE_W, height=2.35)
    color, up_color = sp.COLORS["P2"], sp.COLORS["B2"]
    y_uav, lanes = 3.4, {"i": 2.2, "j": 1.4, "k": 0.6}
    collect_end = {d: e for s, e, kind, d in S2_ACTS if kind == "collect"}
    deliver = {d: e for s, e, kind, d in S2_ACTS if kind == "upload"}
    for s, e, kind, d in S2_ACTS:
        if kind in ("fly", "detour"):
            ax.plot([s, e], [y_uav, y_uav], color=INK["secondary"], linewidth=1.0,
                    linestyle=(0, (2.5, 1.5)) if kind == "detour" else "-", zorder=2)
        else:
            fc = sp.tint(color, 0.35) if kind == "collect" else sp.tint(up_color, 0.35)
            ax.add_patch(FancyBboxPatch((s, y_uav - 0.22), e - s, 0.44, boxstyle="square,pad=0", facecolor=fc,
                                        edgecolor=color if kind == "collect" else up_color, linewidth=0.6, zorder=3))
            ax.text((s + e) / 2, y_uav + 0.36, d, ha="center", va="bottom", fontsize=6.5, style="italic")
    for d, y in lanes.items():
        c, dl, dv = collect_end[d], collect_end[d] + S2_DELTA[d], deliver[d]
        ax.barh(y, dv - c, left=c, height=0.42, color=color, linewidth=0, zorder=3)
        if dv > dl:
            ax.barh(y, dv - dl, left=dl, height=0.42, color=sp.tint(color, 0.6), edgecolor=color, linewidth=0,
                    hatch="//////", zorder=4)
        ax.plot([dl, dl], [y - 0.3, y + 0.3], color=INK["primary"], linewidth=0.9, zorder=5)
        for x in (c, dv):
            ax.plot([x, x], [y + 0.21, y_uav - 0.22], color=INK["axis"], linewidth=0.5, linestyle=(0, (1, 1.5)), zorder=1)
        ax.text(c - 0.08, y, f"{t(lang, 'item')} {d}", ha="right", va="center", fontsize=6.5)
        ax.text((c + dv) / 2, y + 0.3, f"AoI$_{d}$", ha="center", va="bottom", fontsize=6.2, color=INK["secondary"])
    ax.text(-0.1, y_uav, t(lang, "lane_uav"), ha="right", va="center", fontsize=6.5)
    ax.text(9.6, 2.35, t(lang, "aoi_def"), fontsize=6.3, va="center")
    ax.text(9.6, 1.75, t(lang, "obj_def"), fontsize=6.3, va="center")
    ax.text(9.6, 1.15, t(lang, "order"), fontsize=5.8, va="center", color=INK["secondary"], wrap=True)
    ax.set_xlim(-1.2, 15.8)
    ax.set_ylim(0.1, 4.1)
    ax.set_yticks([])
    ax.set_xticks(range(0, 10, 2))
    ax.spines["bottom"].set_bounds(0, 9.5)      # 坐标轴只画到时间线结束处，右侧是公式说明
    ax.spines["left"].set_visible(False)
    ax.grid(False)
    ax.set_xlabel(t(lang, "time"))
    ax.xaxis.set_label_coords(0.29, -0.13)
    handles = [Patch(facecolor=sp.tint(color, 0.35), edgecolor=color, linewidth=0.6, label=t(lang, "collect")),
               Patch(facecolor=sp.tint(up_color, 0.35), edgecolor=up_color, linewidth=0.6, label=t(lang, "upload")),
               Line2D([], [], color=INK["secondary"], linewidth=1.0, label=t(lang, "fly")),
               Line2D([], [], color=INK["secondary"], linewidth=1.0, linestyle=(0, (2.5, 1.5)), label=t(lang, "detour")),
               Patch(facecolor=color, label=t(lang, "carry")),
               Patch(facecolor=sp.tint(color, 0.6), edgecolor=color, linewidth=0, hatch="//////",
                     label=t(lang, "overtime")),
               Line2D([], [], linestyle="none", marker="|", markersize=6, markeredgewidth=0.9, color=INK["primary"],
                      label=t(lang, "deadline"))]
    sp.legend_top(fig, handles, ncol=7)
    return fig


# ---------------------------------------------------------------------------
# S3 算法框架、S4 实验流程（流程图）
# ---------------------------------------------------------------------------

FLOW = {
    "zh": {
        "in": "输入：观测点与初始分配、地面站与覆盖圈、时长预算 $(1+\\varepsilon)\\hat{T}$",
        "s1": "① 两阶段起点：每机最短回路（两个方向）+ 精确停靠",
        "s2": "② 机内局部搜索（各机独立）：2-opt、交换、Or-opt\n首次改进，一整轮无改进即停 → 此时的方案即 SCOUT-intra",
        "s3": "③ 跨机移动与交换：候选为最近的 5 个异机观测点\n接受后两条航线各做一次短局部搜索",
        "s4": "④ 增强阶段（可选，随时可停）：4 条链并行，1 条从 ③ 的解出发，3 条换初始分配\n扰动（double-bridge、整块移交、近邻交换）→ 机内与跨机重优化 → 变好才接受",
        "out": "输出：各机访问顺序 + 停靠方案（①–③ 为 SCOUT，①–④ 为 SCOUT+）",
        "ev_title": "评估器：给定访问顺序 → 最优停靠与目标值",
        "ev": "• 精确停靠动态规划（帕累托标签，\n   满足时长预算与电池）\n• 时间价格下界：先估下界，不可能\n   更好的候选直接跳过\n• 前缀复用：只重算改动位置之后的部分",
        "cand": "候选顺序", "val": "目标值",
        "p1": "实例生成\n火线、扇形布点\n评估种子 100–119", "p2": "冻结\n参数：v27 配置（文献核实）\n代码：Git 标签",
        "p3": "GitHub Actions\n按估计耗时分片并行\nubuntu-24.04，Python 3.14.5", "p4": "汇总作业\n检查：可行、序关系\n配对检验、作图",
        "p5": "本地\n分析（E4、E7）与重画\n汇总文本与 Actions 逐字核对",
        "pnote": "本地与 Actions 逐位一致：sin、cos 用正确舍入的实现，推导参数保留 9 位小数",
    },
    "en": {
        "in": "Input: observation points and initial assignment, ground stations and coverage, budget "
              "$(1+\\varepsilon)\\hat{T}$",
        "s1": "(1) Two-stage start: shortest tour per UAV (both directions) + exact stops",
        "s2": "(2) Intra-UAV local search (per UAV): 2-opt, swap, Or-opt\nfirst improvement until a full pass fails → SCOUT-intra",
        "s3": "(3) Cross-UAV moves and swaps: 5 nearest points of other UAVs\nshort re-optimization of both routes after a move",
        "s4": "(4) Enhancement (optional, anytime): 4 parallel chains, one from (3), three from shifted assignments\nkick (double-bridge, block move, neighbor swaps) → re-optimize → accept if better",
        "out": "Output: visiting order + upload stops per UAV ((1)–(3): SCOUT; (1)–(4): SCOUT+)",
        "ev_title": "Evaluator: visiting order → optimal stops and objective",
        "ev": "• Exact stop DP (Pareto labels,\n   time budget and battery)\n• Time-price lower bound: skip\n   candidates that cannot improve\n• Prefix reuse: recompute only after\n   the changed position",
        "cand": "candidate", "val": "objective",
        "p1": "Instance generation\nfire line and sector\nseeds 100–119", "p2": "Freeze\nparameters: v27 config\ncode: Git tag",
        "p3": "GitHub Actions\nsharded by estimated cost\nubuntu-24.04, Python 3.14.5",
        "p4": "Summary job\nchecks: feasibility, ordering\npaired tests, figures",
        "p5": "Local\nanalysis (E4, E7), re-plotting\nsummary text checked vs. Actions",
        "pnote": "Bit-identical locally and on Actions: correctly rounded sin/cos, derived parameters rounded to 9 decimals",
    },
}


def _box(ax, x: float, y: float, w: float, h: float, text: str, edge: str = INK["secondary"], fill: str = INK["surface"],
         size: float = 6.3, weight: str = "normal", align: str = "center", ls: str = "-") -> None:
    """圆角框加文字；(x, y) 为框的中心；ls 为边框线型（可选步骤用虚线）"""
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.12",
                                facecolor=fill, edgecolor=edge, linewidth=0.8, linestyle=ls, zorder=2))
    tx = x if align == "center" else x - w / 2 + 0.15
    ax.text(tx, y, text, ha=align, va="center", fontsize=size, fontweight=weight, zorder=3, linespacing=1.35)


def _arrow(ax, a: tuple, b: tuple, style: str = "-|>", label: str | None = None, offset: tuple = (0, 0.12)) -> None:
    """从 a 到 b 的箭头，可在中点旁加小字"""
    ax.annotate("", xy=b, xytext=a, arrowprops={"arrowstyle": style, "color": INK["secondary"], "linewidth": 0.8,
                                                 "shrinkA": 0, "shrinkB": 0, "mutation_scale": 7}, zorder=1)
    if label:
        ax.text((a[0] + b[0]) / 2 + offset[0], (a[1] + b[1]) / 2 + offset[1], label, ha="center", va="bottom",
                fontsize=5.6, color=INK["secondary"])


def fig_s3_algorithm(lang: str):
    """S3：算法框架——左列为求解流程（①–③ 为 SCOUT，加上可选的 ④ 为 SCOUT+），右侧为各步共用的评估器"""
    f = FLOW[lang]
    fig, ax = sp.new_fig(width=sp.DOUBLE_W, height=3.3)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7.2)
    ax.axis("off")
    xl, w, h, hs = 3.05, 5.9, 0.78, 0.95
    ys = {"in": 6.65, "s1": 5.55, "s2": 4.3, "s3": 3.05, "s4": 1.8, "out": 0.6}
    steps, tall = ("s1", "s2", "s3", "s4"), ("s2", "s3", "s4")
    color = sp.COLORS["P2"]
    for key, y in ys.items():
        edge = color if key in steps else INK["secondary"]
        fill = sp.tint(color, 0.94 if key == "s4" else 0.88) if key in steps else INK["wash"]
        # ④ 是可选的增强阶段：虚线边框、更浅的底色
        _box(ax, xl, y, w, hs if key in tall else h, f[key], edge=edge, fill=fill, ls="--" if key == "s4" else "-")
    for a, b in pairwise(ys):
        ha = hs if a in tall else h
        hb = hs if b in tall else h
        _arrow(ax, (xl, ys[a] - ha / 2), (xl, ys[b] + hb / 2))
    xe, we = 8.2, 3.2
    ye, he = (ys["s1"] + ys["s4"]) / 2, ys["s1"] - ys["s4"] + 0.8
    _box(ax, xe, ye, we, he, f["ev"], edge=sp.COLORS["B2"], fill=sp.tint(sp.COLORS["B2"], 0.88), size=6.0, align="left")
    ax.text(xe, ye + he / 2 + 0.12, f["ev_title"], ha="center", va="bottom", fontsize=6.3, fontweight="bold")
    for key in steps:
        y = ys[key]
        _arrow(ax, (xl + w / 2, y + 0.1), (xe - we / 2, y + 0.1), label=f["cand"] if key == "s2" else None)
        _arrow(ax, (xe - we / 2, y - 0.1), (xl + w / 2, y - 0.1), label=f["val"] if key == "s2" else None,
               offset=(0, -0.3))
    return fig


def fig_s4_pipeline(lang: str):
    """S4：实验流程——实例生成 → 冻结 → Actions 分片运行 → 汇总 → 本地分析与核对"""
    f = FLOW[lang]
    fig, ax = sp.new_fig(width=sp.DOUBLE_W, height=1.55)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 2.2)
    ax.axis("off")
    keys = ("p1", "p2", "p3", "p4", "p5")
    w, h, gap = 1.78, 1.25, 0.25
    x0 = (10 - (len(keys) * w + (len(keys) - 1) * gap)) / 2 + w / 2
    for i, key in enumerate(keys):
        x = x0 + i * (w + gap)
        edge = sp.COLORS["P2"] if key == "p3" else INK["secondary"]
        _box(ax, x, 1.3, w, h, f[key], edge=edge, fill=sp.tint(edge, 0.88) if key == "p3" else INK["wash"], size=5.8)
        if i:
            _arrow(ax, (x - w / 2 - gap, 1.3), (x - w / 2, 1.3))
    ax.text(5, 0.28, f["pnote"], ha="center", va="center", fontsize=5.8, color=INK["secondary"])
    return fig


def load_case(path: Path) -> dict:
    """读 E7 案例记录 JSON"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


NAMES = {"S1": "S1_scene", "S2": "S2_timeline_aoi", "S3": "S3_algorithm", "S4": "S4_pipeline"}


def draw_all(case: Path, out: Path) -> list[Path]:
    """画全部示意图，中英文各一套

    :param case: E7 典型案例的记录 JSON（S1 用它的几何与航线）
    :param out: 输出目录，图写在 figures/<语言>/schematic/ 下
    :return: 生成的文件
    """
    rec = load_case(case)
    files = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = out / "figures" / lang / "schematic"
        files += sp.save(fig_s1_scene(rec, lang), d, NAMES["S1"])
        files += sp.save(fig_s2_timeline(lang), d, NAMES["S2"])
        files += sp.save(fig_s3_algorithm(lang), d, NAMES["S3"])
        files += sp.save(fig_s4_pipeline(lang), d, NAMES["S4"])
    return files
