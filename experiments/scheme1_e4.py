"""方案一 E4：什么时候值得联合优化（实验规划 29_ 第 2 节 E4；分析前写定的做法见该节"实现细节"）

输入 E1–E3 汇总产物（E1_rows.csv、E2_rows.csv 与 records/），不另跑实验：
- 改善 y = 100·(B2 − P2)/B2；按 ε 分层，层内对特征做 Spearman 相关（Holm 校正）与普通最小二乘
  （特征取层内标准分，HC3 稳健标准误）
- ε 的作用：E2 各 ε 下改善的中位数与四分位数、Spearman ρ(改善, ε)
- 探索性：改善拆成机内、跨机两部分；两阶段解的剩余余量
- 图：F13（左右两图）、X10、Spearman 热图、标准化系数图，中英文各一套

用法：python experiments/scheme1_e4.py --data 产物目录 --out 输出目录
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import scheme1_plots as sp  # noqa: E402
import matplotlib.cm as mcm  # noqa: E402
import matplotlib.colors as mcolors  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# 特征：dist 离覆盖边界的平均距离（m），slack_std 初始分配下各机时间余量的标准差（s），ppu 每机观测点数（只在 E1 中变化）
FEATURE_LABELS = {
    "zh": {"dist": "离覆盖边界距离", "slack_std": "各机余量标准差", "ppu": "每机观测点数", "leftover": "两阶段剩余余量",
           "gain": "相对两阶段的改善（%）", "gain_intra": "机内部分", "gain_cross": "跨机部分",
           "rho": "Spearman ρ", "beta": "标准化系数（百分点/标准差）", "stratum": "分层"},
    "en": {"dist": "Distance to coverage", "slack_std": "Std of UAV slack", "ppu": "Points per UAV",
           "leftover": "Two-stage leftover slack", "gain": "Gain over two-stage (%)", "gain_intra": "Intra-UAV part",
           "gain_cross": "Cross-UAV part", "rho": "Spearman ρ", "beta": "Standardized coef. (pp per SD)",
           "stratum": "Stratum"},
}


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------

def load_instances(data: Path) -> list[dict]:
    """把 E1、E2 的汇总行整理成每个实例一条：B2、P1、P2 的目标，改善及其机内、跨机两部分，实例特征

    E2_rows.csv 中 ε = 0.1、0.25 的行取自 E1（同一批实例），这里两个实验各保留一份，分析时按实验分开
    """
    out = []
    for exp, name in (("E1", "E1_rows.csv"), ("E2", "E2_rows.csv")):
        by: dict = {}
        for r in sp.read_rows(data / name):
            by.setdefault((r["layout"], int(r["n"]), int(r["seed"]), r["eps"]), {})[r["method"]] = r
        for (layout, n, seed, eps), ms in sorted(by.items()):
            b2, p1, p2 = ms["B2"]["obj"], ms["P1"]["obj"], ms["P2"]["obj"]
            f = ms["B2"]
            out.append({"exp": exp, "layout": layout, "n": n, "m": int(f["m"]), "seed": seed, "eps": eps,
                        "b2": b2, "p1": p1, "p2": p2,
                        "gain": 100 * (b2 - p2) / b2, "gain_intra": 100 * (b2 - p1) / b2,
                        "gain_cross": 100 * (p1 - p2) / b2,
                        "dist": f["mean_dist_to_coverage_m"], "slack_std": f["slack_std_s"], "ppu": n / int(f["m"])})
    return out


def add_leftover(data: Path, insts: list[dict]) -> None:
    """探索性特征：两阶段解中各机"飞行时间上限 − 实际飞行时间"的均值（s），从实例记录读取

    E2 中 ε = 0.1、0.25 的实例记录在 E1 名下
    """
    for x in insts:
        exp = "E1" if (x["exp"] == "E1" or x["eps"] in (0.1, 0.25)) else "E2"
        p = data / "records" / f"{exp}_{x['layout']}_n{x['n']}_s{x['seed']}_e{x['eps']}.json"
        uavs = json.loads(p.read_text(encoding="utf-8"))["methods"]["B2"]["uavs"]
        x["leftover"] = statistics.fmean(u["cap_s"] - u["fly_s"] for u in uavs if u["n"])


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def holm(pvals: list[float]) -> list[float]:
    """Holm–Bonferroni 校正后的 p 值（保持输入顺序）"""
    order = sorted(range(len(pvals)), key=pvals.__getitem__)
    adj, running = [0.0] * len(pvals), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvals) - rank) * pvals[i]))
        adj[i] = running
    return adj


def spearman(xs, ys) -> tuple[float, float]:
    """Spearman ρ 与双侧 p；取值无变化时返回 (nan, nan)"""
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return math.nan, math.nan
    res = stats.spearmanr(xs, ys)
    return float(res.statistic), float(res.pvalue)


def zscore(v: list[float]) -> np.ndarray:
    a = np.asarray(v, dtype=float)
    sd = a.std(ddof=1)
    return (a - a.mean()) / sd if sd > 0 else a * 0.0


def ols_hc3(y: list[float], cols: dict) -> dict:
    """普通最小二乘与 HC3 稳健标准误

    :param y: 因变量
    :param cols: {名称: 取值列}，不含截距（自动加）
    :return: {"coef": {名称: (系数, 标准误, t, p, 95% 区间半宽)}, "r2", "n"}
    """
    names = ["const", *cols]
    X = np.column_stack([np.ones(len(y)), *[np.asarray(v, dtype=float) for v in cols.values()]])
    yv = np.asarray(y, dtype=float)
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ yv
    resid = yv - X @ beta
    h = np.einsum("ij,jk,ik->i", X, xtx_inv, X)
    meat = X.T @ (X * (resid ** 2 / (1 - h) ** 2)[:, None])
    cov = xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.diag(cov))
    df = len(yv) - X.shape[1]
    tcrit = stats.t.ppf(0.975, df)
    coef = {}
    for i, nm in enumerate(names):
        t = beta[i] / se[i] if se[i] > 0 else math.nan
        coef[nm] = (float(beta[i]), float(se[i]), float(t), float(2 * stats.t.sf(abs(t), df)), float(tcrit * se[i]))
    ss_res, ss_tot = float(resid @ resid), float(((yv - yv.mean()) ** 2).sum())
    return {"coef": coef, "r2": 1 - ss_res / ss_tot if ss_tot > 0 else math.nan, "n": len(yv)}


def strata(insts: list[dict]) -> list[tuple[str, float, list[dict], tuple]]:
    """分析的层：(实验, ε, 实例, 特征)；E1 两层用三个特征，E2 九层用两个特征（每机观测点数恒定）"""
    out = []
    for eps in sorted({x["eps"] for x in insts if x["exp"] == "E1"}):
        out.append(("E1", eps, [x for x in insts if x["exp"] == "E1" and x["eps"] == eps], ("dist", "slack_std", "ppu")))
    for eps in sorted({x["eps"] for x in insts if x["exp"] == "E2"}):
        out.append(("E2", eps, [x for x in insts if x["exp"] == "E2" and x["eps"] == eps], ("dist", "slack_std")))
    return out


def spearman_table(layers, target: str = "gain") -> list[dict]:
    """各层各特征的 Spearman ρ（全部实例与两种布点各自），并在整张表内做 Holm 校正"""
    rows = []
    for exp, eps, xs, feats in layers:
        for f in feats:
            rho, p = spearman([x[f] for x in xs], [x[target] for x in xs])
            row = {"exp": exp, "eps": eps, "feature": f, "target": target, "n": len(xs), "rho": rho, "p": p}
            for lay in ("fireline", "sector"):
                sub = [x for x in xs if x["layout"] == lay]
                row[f"rho_{lay}"], row[f"p_{lay}"] = spearman([x[f] for x in sub], [x[target] for x in sub])
            rows.append(row)
    ok = [i for i, r in enumerate(rows) if not math.isnan(r["p"])]
    for i, a in zip(ok, holm([rows[i]["p"] for i in ok])):
        rows[i]["p_holm"] = a
    return rows


def ols_table(layers) -> list[dict]:
    """各层内的线性模型：改善 ~ 特征的层内标准分 + 扇形布点指示"""
    rows = []
    for exp, eps, xs, feats in layers:
        cols = {f: zscore([x[f] for x in xs]) for f in feats}
        cols["sector"] = [1.0 if x["layout"] == "sector" else 0.0 for x in xs]
        res = ols_hc3([x["gain"] for x in xs], cols)
        for nm, (b, se, t, p, half) in res["coef"].items():
            rows.append({"exp": exp, "eps": eps, "term": nm, "coef": b, "se_hc3": se, "t": t, "p": p, "ci95": half,
                         "r2": res["r2"], "n": res["n"]})
    return rows


def pooled_e1(insts: list[dict]) -> dict:
    """E1 合并两层的模型：改善 ~ 特征标准分 + ε = 0.25 指示 + 扇形布点指示"""
    xs = [x for x in insts if x["exp"] == "E1"]
    cols = {f: zscore([x[f] for x in xs]) for f in ("dist", "slack_std", "ppu")}
    cols["eps0.25"] = [1.0 if x["eps"] == 0.25 else 0.0 for x in xs]
    cols["sector"] = [1.0 if x["layout"] == "sector" else 0.0 for x in xs]
    return ols_hc3([x["gain"] for x in xs], cols)


def eps_effect(insts: list[dict]) -> tuple[list[dict], dict]:
    """E2：各布点、各 ε 下改善的中位数与四分位数，以及每种布点内的 Spearman ρ(改善, ε)"""
    rows, rho = [], {}
    for lay in ("fireline", "sector"):
        xs = [x for x in insts if x["exp"] == "E2" and x["layout"] == lay]
        for eps in sorted({x["eps"] for x in xs}):
            g = [x["gain"] for x in xs if x["eps"] == eps]
            q1, med, q3 = statistics.quantiles(g, n=4, method="inclusive")
            gc = [x["gain_cross"] for x in xs if x["eps"] == eps]
            rows.append({"layout": lay, "eps": eps, "n": len(g), "median": med, "q1": q1, "q3": q3,
                         "mean": statistics.fmean(g), "cross_median": statistics.median(gc)})
        rho[lay] = spearman([x["eps"] for x in xs], [x["gain"] for x in xs]) + (len(xs),)
    return rows, rho


# ---------------------------------------------------------------------------
# 图（样式取自统一作图模块：本文方法的颜色，两种布点用标记与线型区分）
# ---------------------------------------------------------------------------

LAYOUT_STYLE = {"fireline": ("o", "-"), "sector": ("s", (0, (3, 1.5)))}


def _flabel(lang: str, key: str) -> str:
    return FEATURE_LABELS[lang].get(key, sp.label(lang, key))


def _scatter(ax, xs: list[dict], feat: str, lang: str) -> None:
    """改善与某特征的散点（两种布点同色、标记区分）+ 合并样本的最小二乘拟合线，左上角注明 Spearman ρ"""
    c = sp.COLORS["P2"]
    for lay, (mk, _) in LAYOUT_STYLE.items():
        sub = [x for x in xs if x["layout"] == lay]
        ax.scatter([x[feat] for x in sub], [x["gain"] for x in sub], s=9, marker=mk, facecolors="none",
                   edgecolors=c, linewidths=0.6, zorder=3)
    fx, gy = [x[feat] for x in xs], [x["gain"] for x in xs]
    slope, icpt = statistics.linear_regression(fx, gy)
    x0, x1 = min(fx), max(fx)
    ax.plot([x0, x1], [icpt + slope * x0, icpt + slope * x1], color=c, zorder=4)
    rho, p = spearman(fx, gy)
    ax.text(0.03, 0.96, f"ρ = {rho:.2f}（p = {p:.1e}）" if lang == "zh" else f"ρ = {rho:.2f} (p = {p:.1e})",
            transform=ax.transAxes, va="top", color=sp.INK["secondary"])
    ax.grid(True, axis="both")


def _layout_handles(lang: str, with_fit: bool) -> list:
    from matplotlib.lines import Line2D

    c = sp.COLORS["P2"]
    hs = [Line2D([], [], color=c, marker=mk, linestyle=ls, markerfacecolor=sp.INK["surface"], markeredgecolor=c,
                 label=sp.label(lang, lay)) for lay, (mk, ls) in LAYOUT_STYLE.items()]
    if with_fit:
        hs.append(Line2D([], [], color=c, label=sp.label(lang, "fit")))
    return hs


def fig_f13(insts: list[dict], eps_rows: list[dict], lang: str):
    """F13：左图为 E2 改善随 ε 的分层折线（四分位色带），右图为 E1 ε = 0.1 时改善与离覆盖距离的散点"""
    fig, (axl, axr) = sp.new_fig(ncols=2, width=sp.DOUBLE_W, height=2.4)
    c = sp.COLORS["P2"]
    for lay, (mk, ls) in LAYOUT_STYLE.items():
        r = [x for x in eps_rows if x["layout"] == lay]
        e = [x["eps"] for x in r]
        axl.fill_between(e, [x["q1"] for x in r], [x["q3"] for x in r], color=c, alpha=0.12, linewidth=0, zorder=1)
        axl.plot(e, [x["median"] for x in r], color=c, marker=mk, linestyle=ls, markerfacecolor=sp.INK["surface"],
                 markeredgecolor=c, markeredgewidth=0.9, zorder=3)
    axl.set_xlabel(sp.label(lang, "eps"))
    axl.set_ylabel(_flabel(lang, "gain"))
    axl.grid(True, axis="both")
    _scatter(axr, [x for x in insts if x["exp"] == "E1" and x["eps"] == 0.1], "dist", lang)
    axr.set_xlabel(sp.label(lang, "mean_dist_to_coverage_m"))
    sp.legend_top(fig, _layout_handles(lang, True))
    return fig


def fig_x10(insts: list[dict], lang: str):
    """X10：E1 两档 ε 下改善与各机余量标准差（初始分配的不均衡程度）的散点"""
    fig, axes = sp.new_fig(ncols=2, width=sp.DOUBLE_W, height=2.4, sharey=True)
    for ax, eps in zip(axes, (0.1, 0.25)):
        _scatter(ax, [x for x in insts if x["exp"] == "E1" and x["eps"] == eps], "slack_std", lang)
        ax.set_xlabel(sp.label(lang, "slack_std_s"))
        ax.set_title(f"ε = {eps}")
    axes[0].set_ylabel(_flabel(lang, "gain"))
    sp.legend_top(fig, _layout_handles(lang, True))
    return fig


def _cols(layers) -> list[str]:
    return [f"{exp}\n{eps:g}" for exp, eps, _, _ in layers]


def fig_heatmap(layers, sp_rows: list[dict], lang: str):
    """按 ε 分层的 Spearman ρ 热图：蓝负、红正、灰为零；Holm 校正后 p < 0.05 的格子加 *，不适用的格子为斜线"""
    feats = ("dist", "slack_std", "ppu")
    cmap = mcolors.LinearSegmentedColormap.from_list("div", [sp.COLORS["P2"], sp.INK["wash"], "#e34948"])
    lookup = {(r["exp"], r["eps"], r["feature"]): r for r in sp_rows}
    mat = np.full((len(feats), len(layers)), np.nan)
    for j, (exp, eps, _, _) in enumerate(layers):
        for i, f in enumerate(feats):
            if (exp, eps, f) in lookup:
                mat[i, j] = lookup[(exp, eps, f)]["rho"]
    fig, ax = sp.new_fig(width=sp.DOUBLE_W, height=2.1)
    vmax = 0.8
    ax.imshow(np.ma.masked_invalid(mat), cmap=cmap, vmin=-vmax, vmax=vmax, aspect="auto")
    for i, f in enumerate(feats):
        for j, (exp, eps, _, _) in enumerate(layers):
            r = lookup.get((exp, eps, f))
            if r is None:   # 每机观测点数在 E2 中恒定，不适用
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=sp.INK["surface"], edgecolor=sp.INK["grid"],
                                       hatch="///", linewidth=0))
                continue
            rgb = cmap((r["rho"] + vmax) / (2 * vmax))[:3]
            lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
            star = "*" if r.get("p_holm", 1.0) < 0.05 else ""
            ax.text(j, i, f"{r['rho']:.2f}{star}", ha="center", va="center", fontsize=6.5,
                    color="white" if lum < 0.45 else sp.INK["primary"])
    ax.set_xticks(range(len(layers)), _cols(layers))
    ax.set_yticks(range(len(feats)), [_flabel(lang, f) for f in feats])
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.axvline(1.5, color=sp.INK["surface"], linewidth=2)
    sm = mcm.ScalarMappable(cmap=cmap, norm=mcolors.Normalize(-vmax, vmax))
    cb = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.01)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=0, labelsize=6.5)
    cb.set_label(_flabel(lang, "rho"))
    return fig


def fig_coef(layers, ols_rows: list[dict], lang: str):
    """标准化系数图：每个特征一个子图，横轴为各层，点为系数、线段为 95% 置信区间（HC3），虚线为零"""
    feats = ("dist", "slack_std", "ppu")
    lookup = {(r["exp"], r["eps"], r["term"]): r for r in ols_rows}
    fig, axes = sp.new_fig(ncols=3, width=sp.DOUBLE_W, height=2.5, sharey=True)
    c = sp.COLORS["P2"]
    for ax, f in zip(axes, feats):
        for j, (exp, eps, _, _) in enumerate(layers):
            r = lookup.get((exp, eps, f))
            if r is None:
                continue
            ax.errorbar(j, r["coef"], yerr=r["ci95"], fmt="o", color=c, markerfacecolor=sp.INK["surface"],
                        markeredgecolor=c, markersize=3.5, elinewidth=0.8, capsize=1.5, zorder=3)
        ax.axhline(0, **sp.REF_STYLE)
        ax.axvline(1.5, color=sp.INK["grid"], linewidth=0.6)
        ax.set_xticks(range(len(layers)), [f"{eps:g}" for _, eps, _, _ in layers], fontsize=6)
        ax.set_title(_flabel(lang, f))
        ax.set_xlabel("E1 | E2：ε" if lang == "zh" else "E1 | E2: ε")
        ax.grid(True, axis="y")
    axes[0].set_ylabel(_flabel(lang, "beta"))
    return fig


# ---------------------------------------------------------------------------
# 文字摘要与命令行
# ---------------------------------------------------------------------------

def report_lines(insts, layers, sp_rows, sp_parts, sp_left, ols_rows, pooled, eps_rows, eps_rho) -> list[str]:
    """E4 的文字摘要（数字与 CSV 一致）"""
    n1 = sum(x["exp"] == "E1" for x in insts)
    n2 = sum(x["exp"] == "E2" for x in insts)
    L = [f"## E4 什么时候值得联合优化：E1 {n1} 个实例（2 层），E2 {n2} 个实例（9 层）；改善 = 100·(B2 − P2)/B2"]
    L.append("ε 的作用（E2，N = 50）：改善的中位数［四分位］，跨机部分的中位数")
    for lay in ("fireline", "sector"):
        rho, p, n = eps_rho[lay]
        L.append(f"  {lay}：Spearman ρ(改善, ε) = {rho:.2f}（p = {p:.1e}，n = {n}）")
        for r in [x for x in eps_rows if x["layout"] == lay]:
            L.append(f"    ε = {r['eps']:<5g} {r['median']:6.1f}% ［{r['q1']:5.1f}～{r['q3']:5.1f}］  跨机 {r['cross_median']:5.1f}%")
    L.append("Spearman 相关（每层；p 为整张表 Holm 校正后；括号内为火线 / 扇形各自的 ρ）")
    for exp, eps, xs, feats in layers:
        cells = []
        for f in feats:
            r = next(r for r in sp_rows if r["exp"] == exp and r["eps"] == eps and r["feature"] == f)
            cells.append(f"{f} ρ = {r['rho']:+.2f}（p = {r['p_holm']:.1e}；{r['rho_fireline']:+.2f} / {r['rho_sector']:+.2f}）")
        L.append(f"  {exp} ε = {eps:<5g} n = {len(xs)}：" + "；".join(cells))
    L.append("线性模型（每层；系数 = 特征增加 1 个层内标准差时改善变化的百分点，± 为 95% 区间，HC3）")
    for exp, eps, xs, feats in layers:
        rs = [r for r in ols_rows if r["exp"] == exp and r["eps"] == eps]
        r2 = rs[0]["r2"]
        cells = [f"{r['term']} {r['coef']:+.2f} ± {r['ci95']:.2f}（p = {r['p']:.1e}）" for r in rs if r["term"] != "const"]
        L.append(f"  {exp} ε = {eps:<5g} R² = {r2:.2f}：" + "；".join(cells))
    cells = [f"{nm} {b:+.2f} ± {h:.2f}（p = {p:.1e}）" for nm, (b, _, _, p, h) in pooled["coef"].items() if nm != "const"]
    L.append(f"  E1 合并模型 n = {pooled['n']}，R² = {pooled['r2']:.2f}：" + "；".join(cells))
    L.append("探索性：改善的机内、跨机两部分与特征的 Spearman ρ（未校正 p）")
    for exp, eps, xs, feats in layers:
        if exp != "E1" and eps not in (0.0, 0.1, 0.5):
            continue
        cells = []
        for part in ("gain_intra", "gain_cross"):
            for f in feats:
                r = next(r for r in sp_parts if r["exp"] == exp and r["eps"] == eps and r["feature"] == f and r["target"] == part)
                cells.append(f"{part[5:]}~{f} {r['rho']:+.2f}（{r['p']:.0e}）")
        L.append(f"  {exp} ε = {eps:<5g}：" + "；".join(cells))
    L.append("探索性：两阶段解的剩余余量与改善的 Spearman ρ（未校正 p）")
    L.append("  " + "；".join(f"{r['exp']} ε={r['eps']:g} {r['rho']:+.2f}（{r['p']:.0e}）" for r in sp_left))
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一 E4：联合优化收益与实例特征的关系")
    ap.add_argument("--data", type=Path, required=True, help="E1–E3 汇总产物目录（含 E1_rows.csv、E2_rows.csv、records/）")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    insts = load_instances(a.data)
    add_leftover(a.data, insts)
    layers = strata(insts)
    sp_rows = spearman_table(layers, "gain")
    sp_parts = spearman_table(layers, "gain_intra") + spearman_table(layers, "gain_cross")
    sp_left = []
    for exp, eps, xs, _ in layers:
        rho, p = spearman([x["leftover"] for x in xs], [x["gain"] for x in xs])
        sp_left.append({"exp": exp, "eps": eps, "rho": rho, "p": p, "n": len(xs)})
    ols_rows = ols_table(layers)
    pooled = pooled_e1(insts)
    eps_rows, eps_rho = eps_effect(insts)
    a.out.mkdir(parents=True, exist_ok=True)
    sp.write_rows(a.out / "E4_instances.csv", insts)
    sp.write_rows(a.out / "E4_spearman.csv", sp_rows)
    sp.write_rows(a.out / "E4_spearman_parts.csv", sp_parts)
    sp.write_rows(a.out / "E4_spearman_leftover.csv", sp_left)
    sp.write_rows(a.out / "E4_ols.csv", ols_rows)
    sp.write_rows(a.out / "E4_ols_pooled_e1.csv", [{"term": nm, "coef": b, "se_hc3": se, "t": t, "p": p, "ci95": h,
                                                     "r2": pooled["r2"], "n": pooled["n"]}
                                                    for nm, (b, se, t, p, h) in pooled["coef"].items()])
    sp.write_rows(a.out / "E4_eps_effect.csv", eps_rows)
    lines = report_lines(insts, layers, sp_rows, sp_parts, sp_left, ols_rows, pooled, eps_rows, eps_rho)
    files = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = a.out / "figures" / lang
        files += sp.save(fig_f13(insts, eps_rows, lang), d, "E4_F13_gain_vs_eps_and_distance")
        files += sp.save(fig_x10(insts, lang), d, "E4_X10_gain_vs_slack_std")
        files += sp.save(fig_heatmap(layers, sp_rows, lang), d, "E4_spearman_heatmap")
        files += sp.save(fig_coef(layers, ols_rows, lang), d, "E4_standardized_coefficients")
    lines.append(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    (a.out / "E4_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
