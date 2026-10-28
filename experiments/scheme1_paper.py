"""方案一论文图表整理（实验规划 29_ 推进顺序第 7 步；图表清单见 29_ 第 5.2 节）

- collect：各实验的图先在本地用统一作图模块从 Actions 数据重画（汇总文本须与 Actions 逐字相同），
  再按 29_ 的编号（F1–F20、X1–X15）复制、改名，写图的清单；缺的图在清单里标出
- tables：表 1 关键实验参数（从冻结配置读出）、表 2 比较方法一览、表 3 主结果汇总
  （E1 默认场景 N = 50、5 架机的均值 ± 95% 置信区间），各出 Markdown、CSV 与 LaTeX（booktabs）
- schematics：示意图 S1–S4（见 scheme1_schematics.py）

用法：
  python experiments/scheme1_paper.py collect --src E1_E3=目录 E4=目录 E5=目录 E5LB=目录 E6=目录 E7=目录 --out 目录
  python experiments/scheme1_paper.py tables --e1 E1产物目录 --out 目录
  python experiments/scheme1_paper.py schematics --case E7案例记录.json --out 目录
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
LANGS = ("zh", "en")
EXTS = ("pdf", "png")

# 各来源对应的实验与 Actions 运行；E4、E5LB、E7 是在本地读 E1–E3 产物算出的，不另求解
SOURCES = {
    "E1_E3": "E1–E3，标签 scheme1-exp-v1，run 40295745598",
    "E4": "E4，本地分析 E1–E3 产物",
    "E5": "E5，标签 scheme1-e5-v1，run 40320022985",
    "E5LB": "E5 与下界的差距，本地分析 E1 产物",
    "E6": "E6，标签 scheme1-e6-v1，run 40341256152",
    "E7": "E7，本地读 E1 记录（典型案例种子 113，收益最大案例种子 103）",
}

# (编号, 来源, 原图名, 中文图名, 英文图名, 部分)；部分为 main（正文）、extended（扩展）、other（其他补充）。
# 一个编号对应两个文件时加 a、b；E1 的案例占位图（种子 100）已由 E7 取代，不收
FIGURES = [
    ("F01", "E5", "E5_F1_stop_dp_vs_bruteforce", "停靠动态规划与穷举的对拍", "Stop DP vs. brute-force enumeration", "main"),
    ("F02", "E1_E3", "E1_F2_convergence_fireline_n50_eps0.1", "局部搜索收敛曲线（火线，N = 50，ε = 0.1）",
     "Convergence of the local search (fire line, N = 50, ε = 0.1)", "main"),
    ("F03a", "E1_E3", "E3_F3_acceleration_time", "两项加速的效果：求解时间", "Effect of the two accelerations: solve time",
     "main"),
    ("F03b", "E1_E3", "E3_F3_acceleration_exact_calls", "两项加速的效果：精确动态规划次数",
     "Effect of the two accelerations: exact DP calls", "main"),
    ("F04", "E1_E3", "E1_F4_norm_aoi_fireline_eps0.1", "平均归一化 AoI 随规模的变化（火线，ε = 0.1）",
     "Mean normalized AoI vs. N (fire line, ε = 0.1)", "main"),
    ("F05", "E1_E3", "E1_F5_mean_aoi_s_fireline_eps0.1", "平均 AoI 随规模的变化（火线，ε = 0.1）",
     "Mean AoI vs. N (fire line, ε = 0.1)", "main"),
    ("F06", "E1_E3", "E1_F6_on_time_rate_fireline_eps0.1", "按时送达率随规模的变化（火线，ε = 0.1）",
     "On-time delivery vs. N (fire line, ε = 0.1)", "main"),
    ("F07", "E1_E3", "E1_F7_max_mission_min_fireline_eps0.1", "最大任务时长随规模的变化（火线，ε = 0.1）",
     "Max mission time vs. N (fire line, ε = 0.1)", "main"),
    ("F08", "E1_E3", "E1_F8_energy_kj_fireline_eps0.1", "能耗随规模的变化（火线，ε = 0.1）",
     "Total energy vs. N (fire line, ε = 0.1)", "main"),
    ("F09", "E1_E3", "E1_F9_stops_per_uav_fireline_eps0.1", "每机途中停靠次数随规模的变化（火线，ε = 0.1）",
     "Mid-route stops per UAV vs. N (fire line, ε = 0.1)", "main"),
    ("F10", "E1_E3", "E1_F10_aoi_box_fireline_n50_eps0.1", "每份数据 AoI 的分布（火线，N = 50，ε = 0.1）",
     "Per-item AoI distribution (fire line, N = 50, ε = 0.1)", "main"),
    ("F11", "E1_E3", "E1_F11_norm_aoi_line_fireline_eps0.25", "平均归一化 AoI 随规模的趋势（火线，ε = 0.25）",
     "Mean normalized AoI trend vs. N (fire line, ε = 0.25)", "main"),
    ("F12a", "E1_E3", "E2_F12_tradeoff_fireline", "AoI–时长折中曲线（火线）", "AoI–duration trade-off (fire line)", "main"),
    ("F12b", "E1_E3", "E2_F12_tradeoff_sector", "AoI–时长折中曲线（扇形）", "AoI–duration trade-off (sector)", "main"),
    ("F13", "E4", "E4_F13_gain_vs_eps_and_distance", "联合优化收益与预算、离覆盖距离的关系",
     "Gain of joint optimization vs. budget slack and distance to coverage", "main"),
    ("F14", "E1_E3", "E3_F14_ablation_norm_aoi_fireline_eps0.1", "消融：平均归一化 AoI（火线，ε = 0.1）",
     "Ablation: mean normalized AoI (fire line, ε = 0.1)", "main"),
    ("F15", "E1_E3", "E3_F15_ablation_on_time_fireline_eps0.1", "消融：按时送达率（火线，ε = 0.1）",
     "Ablation: on-time delivery (fire line, ε = 0.1)", "main"),
    ("F16", "E6", "E6_F16_stations", "敏感性：站点数", "Sensitivity: number of ground stations", "main"),
    ("F17a", "E6", "E6_F17_freshness_norm_aoi", "敏感性：时效窗（平均归一化 AoI）",
     "Sensitivity: freshness window (mean normalized AoI)", "main"),
    ("F17b", "E6", "E6_F17_freshness_on_time", "敏感性：时效窗（按时送达率）", "Sensitivity: freshness window (on-time delivery)",
     "main"),
    ("F18", "E1_E3", "E1_F18_norm_aoi_sector_eps0.1", "第二场景（扇形）：平均归一化 AoI（ε = 0.1）",
     "Second scenario (sector): mean normalized AoI (ε = 0.1)", "main"),
    ("F19", "E1_E3", "E1_F19_on_time_rate_sector_eps0.1", "第二场景（扇形）：按时送达率（ε = 0.1）",
     "Second scenario (sector): on-time delivery (ε = 0.1)", "main"),
    ("F20", "E7", "E7_F20_route_maps_median_s113", "火线案例的航线图（典型实例）", "Routes in the fire-line case (typical instance)",
     "main"),
    ("X01", "E1_E3", "E1_X1_norm_aoi_fireline_eps0.25", "平均归一化 AoI 随规模的变化（火线，ε = 0.25）",
     "Mean normalized AoI vs. N (fire line, ε = 0.25)", "extended"),
    ("X02", "E1_E3", "E1_X2_mean_aoi_s_fireline_eps0.25", "平均 AoI 随规模的变化（火线，ε = 0.25）",
     "Mean AoI vs. N (fire line, ε = 0.25)", "extended"),
    ("X03", "E1_E3", "E1_X3_on_time_rate_fireline_eps0.25", "按时送达率随规模的变化（火线，ε = 0.25）",
     "On-time delivery vs. N (fire line, ε = 0.25)", "extended"),
    ("X04", "E1_E3", "E1_X4_max_mission_min_fireline_eps0.25", "最大任务时长随规模的变化（火线，ε = 0.25）",
     "Max mission time vs. N (fire line, ε = 0.25)", "extended"),
    ("X05", "E1_E3", "E1_X5_energy_kj_fireline_eps0.25", "能耗随规模的变化（火线，ε = 0.25）",
     "Total energy vs. N (fire line, ε = 0.25)", "extended"),
    ("X06", "E1_E3", "E1_X6_aoi_cdf_fireline_n50_eps0.1", "每份数据 AoI 的累积分布（火线，N = 50，ε = 0.1）",
     "CDF of per-item AoI (fire line, N = 50, ε = 0.1)", "extended"),
    ("X07", "E5", "E5_X7_solve_time", "求解时间随规模的变化", "Solve time vs. problem size", "extended"),
    ("X08", "E1_E3", "E1_X8_lb_ratio", "时间价格下界的紧度（下界 ÷ 精确值）", "Tightness of the time-price bound (bound / exact)",
     "extended"),
    ("X09", "E7", "E7_X9_uav_mission_max_s103", "跨机移动前后各机任务时长（收益最大的实例）",
     "Per-UAV mission time before and after cross-UAV moves (largest-gain instance)", "extended"),
    ("X10", "E4", "E4_X10_gain_vs_slack_std", "收益与各机时间余量离散程度的关系", "Gain vs. dispersion of UAV time slack",
     "extended"),
    ("X11", "E6", "E6_X11_radius", "敏感性：覆盖半径", "Sensitivity: coverage radius", "extended"),
    ("X12", "E6", "E6_X12_battery", "敏感性：电池容量", "Sensitivity: battery capacity", "extended"),
    ("X13", "E6", "E6_X13_uavs", "敏感性：机数", "Sensitivity: number of UAVs", "extended"),
    ("X14", "E6", "E6_X14_rate", "敏感性：上传速率", "Sensitivity: upload rate", "extended"),
    ("X15", "E7", "E7_X15_timelines_median_s113", "火线案例中每份数据的采集与送达时间线（典型实例）",
     "Collection-to-delivery timelines in the fire-line case (typical instance)", "extended"),
]

# 其他补充图：保留原图名，不编号
OTHER = [
    ("E1_E3", "E3_F14_ablation_norm_aoi_fireline_eps0.25"), ("E1_E3", "E3_F14_ablation_norm_aoi_sector_eps0.1"),
    ("E1_E3", "E3_F14_ablation_norm_aoi_sector_eps0.25"), ("E1_E3", "E3_F15_ablation_on_time_fireline_eps0.25"),
    ("E1_E3", "E3_F15_ablation_on_time_sector_eps0.1"), ("E1_E3", "E3_F15_ablation_on_time_sector_eps0.25"),
    ("E1_E3", "E2_battery_binding"), ("E1_E3", "E2_mission_increase_fireline"), ("E1_E3", "E2_mission_increase_sector"),
    ("E4", "E4_spearman_heatmap"), ("E4", "E4_standardized_coefficients"),
    ("E5", "E5_gap_to_exact"), ("E5LB", "E5_gap_to_lower_bound"),
    ("E7", "E7_aoi_over_delta_cdf_median_s113"), ("E7", "E7_X9_uav_mission_median_s113"),
    ("E7", "E7_F20_route_maps_max_s103"), ("E7", "E7_X15_timelines_max_s103"), ("E7", "E7_aoi_over_delta_cdf_max_s103"),
]


def source_files(src: dict[str, Path], key: str, stem: str) -> dict[tuple[str, str], Path]:
    """某张图在来源目录中的文件

    :param src: {来源: 重画输出目录（其下 figures/zh、figures/en）}
    :param key: 来源
    :param stem: 原图名（不含扩展名）
    :return: {(语言, 扩展名): 路径}，只含存在的文件
    """
    if key not in src:
        return {}
    found = {}
    for lang in LANGS:
        for ext in EXTS:
            p = src[key] / "figures" / lang / f"{stem}.{ext}"
            if p.is_file():
                found[(lang, ext)] = p
    return found


def collect(src: dict[str, Path], out: Path) -> list[dict]:
    """按编号复制、改名，并返回清单行

    :param src: {来源: 重画输出目录}
    :param out: 输出目录；图写在 figures/<语言>/<部分>/ 下，编号图名为"编号_原图名"
    :return: 清单行（编号、部分、中英文图名、来源、原图名、状态）；四个文件（中英文 × PDF、PNG）齐全才算齐
    """
    rows = []
    entries = [(n, k, s, tz, te, part) for n, k, s, tz, te, part in FIGURES]
    entries += [("", k, s, "", "", "other") for k, s in OTHER]
    for num, key, stem, tz, te, part in entries:
        files = source_files(src, key, stem)
        name = f"{num}_{stem}" if num else stem
        for (lang, ext), p in files.items():
            d = out / "figures" / lang / part
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, d / f"{name}.{ext}")
        status = "齐" if len(files) == len(LANGS) * len(EXTS) else ("缺" if not files else f"不全（{len(files)}/4）")
        rows.append({"number": num, "part": part, "title_zh": tz, "title_en": te, "source": SOURCES.get(key, key),
                     "stem": stem, "file": name, "status": status})
    return rows


# ---------------------------------------------------------------------------
# 表
# ---------------------------------------------------------------------------

def signed(v: float) -> str:
    """负数用减号（U+2212）而不是连字符，排版时与正文的数学减号一致"""
    return f"{v:g}".replace("-", "−")


def table1_rows() -> list[dict]:
    """表 1 关键实验参数：数值从冻结配置、模型参数与实验常量读出，不手抄

    :return: 每行 {cat_zh, cat_en, item_zh, item_en, sym, sym_tex, val_zh, val_en}
    """
    import scheme1_experiments as e123

    from uav_mec.scheme1 import load_scheme1_params
    from uav_mec.scheme1.search import DEFAULT_MAX_EVALS, SearchConfig
    from uav_mec.v27.params import load_params

    p, sp, cfg = load_params(str(CONFIG)), load_scheme1_params(str(CONFIG)), SearchConfig()

    def km(v: float) -> str:
        return f"{v / 1000:g}"

    st = ", ".join(f"{n} ({km(x)}, {km(y)})" for n, x, y, _ in sp.stations)
    bw = sorted({s.bandwidth_mhz for s in p.sites[: p.num_sites]})
    rings_zh = "、".join(f"{f:g}r" for f in sp.ring_fractions)
    rings_en = " and ".join(f"{f:g}r" for f in sp.ring_fractions)
    # 评估上限：字典里与公式 1000 + 500·max(0, n − 8) 不同的点数单独列出
    exc = {n: v for n, v in sorted(DEFAULT_MAX_EVALS.items()) if v != 1000 + 500 * max(0, n - 8)}
    exc_zh = ("；" + "，".join(f"n = {n} 时取 {v}" for n, v in exc.items())) if exc else ""
    exc_en = ("; " + ", ".join(f"{v} for n = {n}" for n, v in exc.items())) if exc else ""
    sizes, e2eps = e123.E1_SIZES, e123.E2_EPS
    eps_set = "{" + ", ".join(f"{e:g}" for e in e123.E1_EPS) + "}"
    area = f"{km(sp.width_m)} km × {km(sp.height_m)} km"
    depot = f"({km(sp.depot[0])}, {km(sp.depot[1])}) km"
    radius = sp.stations[0][3]
    rows = [
        ("场景", "Scenario", "区域", "Area", "—", "—", area, area),
        ("场景", "Scenario", "基地", "Depot", "—", "—", depot, depot),
        ("场景", "Scenario", "地面站（km）", "Ground stations (km)", "—", "—", f"{st}；E1 与基地同址",
         f"{st}; E1 at the depot"),
        ("场景", "Scenario", "观测点数", "Observation points", "N", "N",
         f"{p.num_tasks}（E1 中 {min(sizes)}–{max(sizes)}）", f"{p.num_tasks} (E1: {min(sizes)}–{max(sizes)})"),
        ("场景", "Scenario", "无人机数", "UAVs", "m", "m", f"{e123.M_UAV}（E6 中 3、7）", f"{e123.M_UAV} (E6: 3, 7)"),
        ("无人机", "UAV", "飞行高度", "Altitude", "H", "H", f"{p.altitude_m:g} m", f"{p.altitude_m:g} m"),
        ("无人机", "UAV", "飞行速度", "Speed", "v", "v", f"{sp.speed_mps:g} m/s", f"{sp.speed_mps:g} m/s"),
        ("无人机", "UAV", "飞行功率", "Flight power", "P_f", "P_f", f"{sp.p_fly_w:.2f} W（旋翼模型，Zeng 2019）",
         f"{sp.p_fly_w:.2f} W (rotary-wing model, Zeng 2019)"),
        ("无人机", "UAV", "悬停功率", "Hover power", "P_h", "P_h", f"{sp.p_hover_w:.2f} W", f"{sp.p_hover_w:.2f} W"),
        ("无人机", "UAV", "电池容量", "Battery", "E_max", "E_{\\max}",
         f"{sp.battery_j / 1000:g} kJ（{sp.battery_j / 3600:g} Wh）",
         f"{sp.battery_j / 1000:g} kJ ({sp.battery_j / 3600:g} Wh)"),
        ("通信", "Link", "带宽", "Bandwidth", "B", "B", "、".join(f"{b:g} MHz" for b in bw),
         ", ".join(f"{b:g} MHz" for b in bw)),
        ("通信", "Link", "发射功率", "Transmit power", "P_t", "P_t", f"{p.tx_power_w:g} W", f"{p.tx_power_w:g} W"),
        ("通信", "Link", "参考信道增益 / 路损指数", "Reference gain / path-loss exponent", "β0 / α",
         "\\beta_0 / \\alpha", f"{signed(p.reference_gain_db)} dB / {p.pathloss_exp:g}",
         f"{signed(p.reference_gain_db)} dB / {p.pathloss_exp:g}"),
        ("通信", "Link", "噪声功率谱密度", "Noise PSD", "N0", "N_0", f"{signed(p.noise_psd_dbm_per_hz)} dBm/Hz",
         f"{signed(p.noise_psd_dbm_per_hz)} dBm/Hz"),
        ("通信", "Link", "覆盖半径", "Coverage radius", "r", "r",
         f"{radius:.2f} m（满带宽速率 ≥ {p.min_rate_mbps:g} Mbps 的水平半径）",
         f"{radius:.2f} m (horizontal range with full-band rate ≥ {p.min_rate_mbps:g} Mbps)"),
        ("通信", "Link", "上传速率", "Upload rate", "R", "R", f"{sp.rate_mbps:g} Mbps（覆盖圈内取常数）",
         f"{sp.rate_mbps:g} Mbps (constant inside coverage)"),
        ("通信", "Link", "候选上传点", "Candidate upload points", "—", "—",
         f"每站圆心，及 {rings_zh} 两圈上各 {sp.points_per_ring} 个等角点",
         f"each station center plus {sp.points_per_ring} equally spaced points on rings at {rings_en}"),
        ("数据", "Data", "数据量", "Data size", "D_i", "D_i", f"U[{sp.data_mbit[0]:g}, {sp.data_mbit[1]:g}] Mbit",
         f"U[{sp.data_mbit[0]:g}, {sp.data_mbit[1]:g}] Mbit"),
        ("数据", "Data", "采集（悬停）时间", "Collection (hover) time", "t_c", "t_c", f"{sp.collect_s:g} s",
         f"{sp.collect_s:g} s"),
        ("数据", "Data", "时效窗", "Freshness window", "δ_i", "\\delta_i",
         f"U[{sp.freshness_s[0]:g}, {sp.freshness_s[1]:g}] s，从采集完成起算",
         f"U[{sp.freshness_s[0]:g}, {sp.freshness_s[1]:g}] s, counted from collection completion"),
        ("数据", "Data", "地面处理时间", "Ground processing time", "τ", "\\tau", f"{sp.tau_s:g} s", f"{sp.tau_s:g} s"),
        ("预算与求解", "Budget and solver", "任务时长预算", "Mission-time budget", "T_max", "T_{\\max}",
         f"(1+ε)·T̂，ε ∈ {eps_set}（E2 中 {min(e2eps):g}–{max(e2eps):g}）",
         f"(1+ε)·T̂, ε ∈ {eps_set} (E2: {min(e2eps):g}–{max(e2eps):g})"),
        ("预算与求解", "Budget and solver", "参考任务时长", "Reference duration", "T̂", "\\hat{T}",
         "初始分配下各机最短回路不停靠的任务时长（含悬停）的最大值",
         "max over UAVs of the no-stop mission time (incl. hovering) on the shortest tour of the initial assignment"),
        ("预算与求解", "Budget and solver", "机内局部搜索评估上限", "Intra-UAV evaluation limit", "—", "—",
         f"1000 + 500·max(0, n − 8)，n 为航线上的观测点数{exc_zh}",
         f"1000 + 500·max(0, n − 8), n = points on the route{exc_en}"),
        ("预算与求解", "Budget and solver", "跨机阶段", "Cross-UAV phase", "—", "—",
         (f"评估上限 {cfg.inter_evals}；候选为每个观测点最近的 {cfg.neighbors} 个异机观测点；"
          f"移动被接受后，两条航线各做至多 {cfg.reopt_evals} 次评估的局部搜索"),
         (f"{cfg.inter_evals} evaluations; candidates are the {cfg.neighbors} nearest points of other UAVs; "
          f"after an accepted move both routes are re-optimized with up to {cfg.reopt_evals} evaluations")),
        # 火线生成器的几何参数写在 instance.fireline_points 里，不是配置项，这里照抄
        ("实例", "Instances", "布点", "Layouts", "—", "—",
         "火线：椭圆火线（长半轴 700–1100 m，长宽比 1.5–2.5，朝向随机），沿火线连续切段分配；扇形：区域内均匀，按方位角等分",
         ("fire line: elliptical front (semi-major axis 700–1100 m, aspect ratio 1.5–2.5, random orientation), "
          "contiguous arcs per UAV; sector: uniform points, split by bearing")),
        ("实例", "Instances", "评估种子", "Evaluation seeds", "—", "—",
         f"{e123.SEEDS[0]}–{e123.SEEDS[-1]}（每格 {len(e123.SEEDS)} 个实例）",
         f"{e123.SEEDS[0]}–{e123.SEEDS[-1]} ({len(e123.SEEDS)} instances per cell)"),
    ]
    keys = ("cat_zh", "cat_en", "item_zh", "item_en", "sym", "sym_tex", "val_zh", "val_en")
    return [dict(zip(keys, r, strict=True)) for r in rows]


# 表 2：比较方法（29_ 第 1 节）；每行为 (编号, 中文名, 英文名, 访问顺序 中/英, 分配 中/英, 停靠 中/英)
TABLE2 = [
    ("P2", "SCOUT（本文）", "SCOUT (ours)", "机内 + 跨机局部搜索", "intra- and cross-UAV local search", "联合优化", "joint",
     "精确停靠动态规划", "exact stop DP"),
    ("P1", "SCOUT-intra", "SCOUT-intra", "机内局部搜索", "intra-UAV local search", "初始分配", "initial",
     "精确停靠动态规划", "exact stop DP"),
    ("B2", "两阶段", "Two-stage", "最短回路（取较好方向）", "shortest tour (better direction)", "初始分配", "initial",
     "精确停靠动态规划", "exact stop DP"),
    ("B1", "就近贪心", "Greedy stop", "最短回路（取较好方向）", "shortest tour (better direction)", "初始分配", "initial",
     "每采一份，若到最近上传点的绕路不超出剩余预算就停靠", "stop at the nearest upload point after each item if the detour fits"),
    ("B3", "静态分簇（仿 Huang 2026）", "Static cluster (after Huang 2026)", "按最近站点分簇、逐簇访问（簇内 2-opt）",
     "cluster by nearest station, visit cluster by cluster (2-opt inside)", "初始分配", "initial",
     "每簇采完去该站点上传；超预算时从后往前删停靠", "upload at the cluster's station; drop stops from the end if over budget"),
    ("B4", "截止驱动（仿 Raj 2026）", "Deadline-driven (after Raj 2026)", "最短回路（取较好方向）",
     "shortest tour (better direction)", "初始分配", "initial", "为每份数据选仍能在 δ 内送达、绕路最少的停靠",
     "per item, the least-detour stop that still meets δ"),
    ("B0", "仅基地上传", "Base-only", "最短回路（取较好方向）", "shortest tour (better direction)", "初始分配", "initial",
     "不停靠，返航后在基地上传", "no stops; upload at the depot after return"),
    ("LB", "逐份下界", "Lower bound", "—", "—", "—", "—", "每份数据单独取最早可能的送达，不受时长预算约束",
     "earliest possible delivery per item, ignoring the budget"),
]

# 表 3：E1 默认场景（N = 50、5 架机）；(指标, 小数位, 换算倍数)；求解时间依赖运行器硬件，只作量级参考
T3_N = 50
T3_METRICS = (("norm_aoi", 3, 1.0), ("mean_aoi_s", 1, 1.0), ("p95_aoi_s", 1, 1.0), ("on_time_rate", 1, 100.0),
              ("max_mission_min", 2, 1.0), ("energy_kj", 0, 1.0), ("stops_per_uav", 2, 1.0), ("secs", 1, 1.0))
T3_METHODS = ("P2", "P1", "B2", "B1", "B3", "B4", "B0")
T3_TABLES = {"3a": ((("fireline", 0.1), ("sector", 0.1))), "3b": ((("fireline", 0.25), ("sector", 0.25)))}
T3_HEAD = {"zh": ("方法", "平均归一化 AoI", "平均 AoI（s）", "95 分位 AoI（s）", "按时送达率（%）", "最大任务时长（min）",
                  "总能耗（kJ）", "每机途中停靠", "求解时间（s）"),
           "en": ("Method", "Norm. AoI", "Mean AoI (s)", "95th-pct AoI (s)", "On-time (%)", "Max mission (min)",
                  "Energy (kJ)", "Stops per UAV", "Solve time (s)")}
LAYOUT_NAME = {"zh": {"fireline": "火线布点", "sector": "扇形布点"}, "en": {"fireline": "Fire line", "sector": "Sector"}}


def table3_data(rows: list[dict]) -> list[dict]:
    """表 3 的数值：E1 中 N = 50 各布点、各 ε 下每种方法每个指标的均值与 95% 置信区间半宽（t 分布，20 个种子）

    :param rows: E1–E3 汇总产物中 E1_rows.csv 的行（scheme1_plots.read_rows 读入）
    :return: 每个（布点, ε, 方法, 指标）一行；另加逐份下界（只有平均归一化 AoI）
    """
    import scheme1_plots as sp

    out = []
    for blocks in T3_TABLES.values():
        for lay, eps in blocks:
            sel = [r for r in rows if r["exp"] == "E1" and r["layout"] == lay and r["n"] == T3_N
                   and abs(r["eps"] - eps) < 1e-9]
            for m in T3_METHODS:
                rs = [r for r in sel if r["method"] == m]
                for key, nd, scale in T3_METRICS:
                    if m == "P1" and key == "secs":
                        continue      # P1 是同一次求解在机内阶段结束时的方案，记录的耗时就是 P2 的，不单列
                    mean, ci = sp.mean_ci([r[key] * scale for r in rs])
                    out.append({"layout": lay, "eps": eps, "method": m, "metric": key, "mean": mean, "ci": ci,
                                "n": len(rs), "decimals": nd})
            # 逐份下界是实例特征，各方法的行里相同，取 P2 的行
            lb = [r["lb_norm"] for r in sel if r["method"] == "P2"]
            mean, ci = sp.mean_ci(lb)
            out.append({"layout": lay, "eps": eps, "method": "LB", "metric": "norm_aoi", "mean": mean, "ci": ci,
                        "n": len(lb), "decimals": 3})
    return out


def _cell(d: dict | None, tex: bool = False) -> str:
    """均值 ± 半宽，按该指标的小数位；没有该项时为破折号"""
    if d is None:
        return "---" if tex else "—"
    nd = d["decimals"]
    pm = " $\\pm$ " if tex else " ± "
    return f"{d['mean']:.{nd}f}{pm}{d['ci']:.{nd}f}"


def table3_lines(data: list[dict], name: str, lang: str, tex: bool = False) -> list[str]:
    """表 3a 或 3b 的 Markdown 或 LaTeX（booktabs）行

    :param data: table3_data 的输出
    :param name: "3a"（ε = 0.1，正文）或 "3b"（ε = 0.25，扩展）
    :param lang: 语言
    :param tex: True 时输出 LaTeX，否则 Markdown
    """
    import scheme1_plots as sp

    idx = {(d["layout"], d["eps"], d["method"], d["metric"]): d for d in data}
    head = T3_HEAD[lang]
    ncol = len(head)
    lines = []
    if tex:
        lines += ["\\begin{tabular}{l" + "c" * (ncol - 1) + "}", "\\toprule",
                  " & ".join(tex_escape(h) for h in head) + " \\\\", "\\midrule"]
    else:
        lines += ["| " + " | ".join(head) + " |", "|" + "---|" * ncol]
    for k, (lay, eps) in enumerate(T3_TABLES[name]):
        title = f"{LAYOUT_NAME[lang][lay]}，ε = {eps:g}" if lang == "zh" else f"{LAYOUT_NAME[lang][lay]}, ε = {eps:g}"
        if tex:
            if k:
                lines.append("\\midrule")
            lines.append(f"\\multicolumn{{{ncol}}}{{l}}{{\\textit{{{tex_escape(title)}}}}} \\\\")
        else:
            lines.append(f"| **{title}** |" + " |" * (ncol - 1))
        for m in (*T3_METHODS, "LB"):
            cells = [_cell(idx.get((lay, eps, m, key)), tex) for key, _, _ in T3_METRICS]
            label = sp.label(lang, m)
            lines.append((" & ".join([tex_escape(label), *cells]) + " \\\\") if tex
                         else ("| " + " | ".join([label, *cells]) + " |"))
    note = T3_NOTE[lang]
    if tex:
        lines = [f"% {note}"] + lines + ["\\bottomrule", "\\end{tabular}"]
    else:
        lines += ["", note]
    return lines


T3_NOTE = {
    "zh": "注：N = 50、5 架机，每格 20 个实例的均值 ± 95% 置信区间（t 分布）。求解时间是 Actions 运行器上的耗时"
          "（每台 4 个进程并行），只作量级参考；P1 是同一次求解在机内阶段结束时的方案，不单独计时。",
    "en": "Note: N = 50, 5 UAVs; mean ± 95% confidence interval (t distribution) over 20 instances per cell. "
          "Solve times were measured on GitHub Actions runners (4 parallel processes each) and are indicative only; "
          "P1 is the intermediate solution of the same run and is not timed separately.",
}

TEX_MAP = {"%": "\\%", "&": "\\&", "_": "\\_", "#": "\\#", "ε": "$\\varepsilon$", "δ": "$\\delta$", "τ": "$\\tau$",
           "×": "$\\times$", "·": "$\\cdot$", "±": "$\\pm$", "≥": "$\\geq$", "≤": "$\\leq$", "–": "--", "—": "---",
           "−": "$-$", "∈": "$\\in$"}


def tex_escape(s: str) -> str:
    """把正文里的特殊字符与希腊字母换成 LaTeX 写法；已是数学模式的片段（$…$）不应再传入

    T̂ 是 T 加组合附加符号，先换成占位符；花括号先转义，最后再放回含花括号的 \\hat{T}，避免把它也转义掉
    """
    out = s.replace("T̂", "\x00").replace("{", "\\{").replace("}", "\\}")
    for k, v in TEX_MAP.items():
        out = out.replace(k, v)
    return out.replace("\x00", "$\\hat{T}$")


def table1_lines(rows: list[dict], lang: str, tex: bool = False) -> list[str]:
    """表 1 的 Markdown 或 LaTeX 行：类别、参数、符号、取值"""
    head = ("类别", "参数", "符号", "取值") if lang == "zh" else ("Category", "Parameter", "Symbol", "Value")
    if tex:
        lines = ["\\begin{tabular}{llcp{0.55\\linewidth}}", "\\toprule", " & ".join(tex_escape(h) for h in head) + " \\\\",
                 "\\midrule"]
    else:
        lines = ["| " + " | ".join(head) + " |", "|---|---|---|---|"]
    prev = None
    for r in rows:
        cat = r[f"cat_{lang}"] if r[f"cat_{lang}"] != prev else ""
        if tex and cat and prev is not None:
            lines.append("\\midrule")
        prev = r[f"cat_{lang}"]
        if tex:
            sym = "—" if r["sym_tex"] == "—" else f"${r['sym_tex']}$"
            lines.append(" & ".join([tex_escape(cat), tex_escape(r[f"item_{lang}"]), sym,
                                     tex_escape(r[f"val_{lang}"])]) + " \\\\")
        else:
            lines.append("| " + " | ".join([cat, r[f"item_{lang}"], r["sym"], r[f"val_{lang}"]]) + " |")
    if tex:
        lines += ["\\bottomrule", "\\end{tabular}"]
    return lines


def table2_lines(lang: str, tex: bool = False) -> list[str]:
    """表 2 的 Markdown 或 LaTeX 行：编号、方法、访问顺序、分配、停靠"""
    head = ("编号", "方法", "访问顺序", "分配", "上传停靠") if lang == "zh" else (
        "ID", "Method", "Visiting order", "Assignment", "Upload stops")
    k = 0 if lang == "zh" else 1
    if tex:
        lines = ["\\begin{tabular}{llp{0.25\\linewidth}lp{0.3\\linewidth}}", "\\toprule",
                 " & ".join(tex_escape(h) for h in head) + " \\\\", "\\midrule"]
    else:
        lines = ["| " + " | ".join(head) + " |", "|---|---|---|---|---|"]
    for code, nz, ne, oz, oe, az, ae, sz, se in TABLE2:
        cells = [code, (nz, ne)[k], (oz, oe)[k], (az, ae)[k], (sz, se)[k]]
        lines.append((" & ".join(tex_escape(c) for c in cells) + " \\\\") if tex else ("| " + " | ".join(cells) + " |"))
    if tex:
        lines += ["\\bottomrule", "\\end{tabular}"]
    return lines


def write_text(path: Path, lines: list[str]) -> None:
    """按 UTF-8、LF 写文本（Windows 下也不写成 CRLF）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


T_NAMES = {"1": ("表1_关键实验参数", "Table1_parameters"), "2": ("表2_比较方法", "Table2_methods"),
           "3a": ("表3a_主结果_eps0.1", "Table3a_main_results_eps0.1"),
           "3b": ("表3b_主结果_eps0.25", "Table3b_main_results_eps0.25")}


def write_tables(e1_rows: Path, out: Path) -> list[Path]:
    """写全部表：每个表的中英文 Markdown 与 LaTeX，以及表 1、表 3 的 CSV

    :param e1_rows: E1–E3 汇总产物中的 E1_rows.csv
    :param out: 输出目录（其下 tables/）
    :return: 写出的文件
    """
    import scheme1_plots as sp

    d = out / "tables"
    files = []
    t1 = table1_rows()
    t3 = table3_data(sp.read_rows(e1_rows))
    for lang in LANGS:
        k = 0 if lang == "zh" else 1
        for tid in ("1", "2", "3a", "3b"):
            for tex in (False, True):
                if tid == "1":
                    lines = table1_lines(t1, lang, tex)
                elif tid == "2":
                    lines = table2_lines(lang, tex)
                else:
                    lines = table3_lines(t3, tid, lang, tex)
                p = d / lang / f"{T_NAMES[tid][k]}.{'tex' if tex else 'md'}"
                write_text(p, lines)
                files.append(p)
    sp.write_rows(d / "Table1_parameters.csv", t1)
    sp.write_rows(d / "Table3_main_results.csv", t3)
    return files + [d / "Table1_parameters.csv", d / "Table3_main_results.csv"]


PART_TITLES = (("main", "正文结果图"), ("extended", "扩展图"), ("other", "其他补充图（不编号）"))


def write_manifest(rows: list[dict], out: Path) -> None:
    """图的清单：CSV 与 Markdown（按正文、扩展、其他分组），缺的图标出

    :param rows: collect 的输出
    :param out: 输出目录
    """
    import scheme1_plots as sp

    sp.write_rows(out / "figure_manifest.csv", rows)
    intro = ("由 `experiments/scheme1_paper.py collect` 生成。编号按实验规划 29_ 第 5.2 节；"
             "文件在 `figures/<语言>/<部分>/` 下，名为“编号_原图名”，中英文各有 PDF 与 PNG。")
    lines = ["# 方案一论文图的清单", "", intro]
    for part, title in PART_TITLES:
        sel = [r for r in rows if r["part"] == part]
        lines += ["", f"## {title}（{len(sel)} 项）", "", "| 编号 | 图名 | 来源 | 文件 | 状态 |", "|---|---|---|---|---|"]
        lines += [f"| {r['number'] or '—'} | {r['title_zh'] or '—'} | {r['source']} | `{r['file']}` | {r['status']} |"
                  for r in sel]
    write_text(out / "图的清单.md", lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一论文图表整理")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("collect", help="按编号复制、改名各实验重画的图，写图的清单")
    p.add_argument("--src", nargs="+", required=True, help="来源=目录；来源为 " + "、".join(SOURCES))
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("tables", help="表 1–3")
    p.add_argument("--e1", type=Path, required=True, help="E1–E3 汇总产物目录（含 E1_rows.csv）")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("schematics", help="示意图 S1–S4")
    p.add_argument("--case", type=Path, required=True, help="E7 典型案例的记录 JSON")
    p.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        src = {}
        for item in a.src:
            key, _, path = item.partition("=")
            if key not in SOURCES or not path:
                ap.error("--src 的格式为 来源=目录，来源为 " + "、".join(SOURCES))
            src[key] = Path(path)
        rows = collect(src, a.out)
        write_manifest(rows, a.out)
        miss = [r["file"] for r in rows if r["status"] != "齐"]
        print(f"图：{len(rows) - len(miss)}/{len(rows)} 项齐全" + (f"；缺或不全：{'、'.join(miss)}" if miss else ""))
        return 0
    if a.cmd == "tables":
        files = write_tables(a.e1 / "E1_rows.csv", a.out)
        print(f"表：写出 {len(files)} 个文件")
        return 0
    import scheme1_schematics as sch

    files = sch.draw_all(a.case, a.out)
    print(f"示意图：{len(files) // 2} 张（各有 PDF 与 PNG）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
