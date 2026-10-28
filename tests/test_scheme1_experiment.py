"""方案一基线、实验记录与统一作图模块的测试：基线可行、指标口径一致、方法间的序关系、运行时记录与出图"""

from __future__ import annotations

import importlib.util
import itertools
import math
import statistics
from pathlib import Path

import pytest

from uav_mec.scheme1 import load_scheme1_params, make_instance, simulate
from uav_mec.scheme1.experiment import BUILDERS, METHODS, evaluate_solution, run_methods, summary_rows
from uav_mec.scheme1.search import Budget, reference_t_hat

SP = load_scheme1_params("configs/v27_timeliness.yaml")
ROOT = Path(__file__).resolve().parents[1]
# 冒烟种子（97–99），与评估实例分开；覆盖两种布点、两档预算与不同机数
CASES = [("fireline", 20, 3, 97, 0.1), ("sector", 20, 3, 98, 0.25), ("fireline", 16, 2, 99, 0.25)]
LB_SAMPLES = 20


def tol(x: float) -> float:
    return 1e-9 * max(1.0, abs(x))


@pytest.fixture(scope="module", params=CASES, ids=lambda c: f"{c[0]}-n{c[1]}-m{c[2]}-s{c[3]}-e{c[4]}")
def case(request):
    layout, n, m, seed, eps = request.param
    inst, groups = make_instance(layout, n, m, seed, SP)
    rec = run_methods(inst, groups, eps, tag=(layout, n, m, seed, eps), lb_samples=LB_SAMPLES)
    return inst, groups, rec


def test_every_method_is_feasible_and_assigns_each_point_once(case):
    _, groups, rec = case
    assert set(rec["methods"]) == set(METHODS)
    for m, out in rec["methods"].items():
        s = out["summary"]
        assert s["feasible"] and s["assigned_once"], m
        for u in out["uavs"]:
            assert u["mission_s"] <= rec["t_max"] + 1e-6, (m, u["uav"])
    for m in BUILDERS:   # 基线沿用初始分配
        assert [sorted(r) for r in rec["methods"][m]["routes"]] == [sorted(g) for g in groups], m


def test_metrics_follow_one_definition(case):
    inst, _, rec = case
    for m, out in rec["methods"].items():
        s, tasks = out["summary"], out["tasks"]
        sims = [simulate(inst, r, [tuple(x) for x in st]) for r, st in zip(out["routes"], out["stops"]) if r]
        assert s["obj"] == pytest.approx(sum(x.objective for x in sims), rel=1e-12), m
        assert s["obj"] == pytest.approx(sum(t["aoi_s"] / t["delta_s"] for t in tasks), rel=1e-12)
        assert s["norm_aoi"] * inst.n == pytest.approx(s["obj"], rel=1e-12)
        assert s["mean_aoi_s"] == pytest.approx(statistics.fmean(t["aoi_s"] for t in tasks), rel=1e-12)
        assert s["on_time_rate"] == pytest.approx(sum(t["aoi_s"] <= t["delta_s"] + 1e-9 for t in tasks) / inst.n)
        assert s["energy_kj"] * 1000 == pytest.approx(sum(x.energy_j for x in sims), rel=1e-12)
        assert s["max_aoi_s"] >= s["p95_aoi_s"] >= min(t["aoi_s"] for t in tasks)


def test_method_ordering(case):
    _, _, rec = case
    obj = {m: out["summary"]["obj"] for m, out in rec["methods"].items()}
    # 同一航线上两阶段的停靠是精确最优，B0、B1、B4 都是同一航线上的可行停靠方案
    for b in ("B0", "B1", "B4"):
        assert obj["B2"] <= obj[b] + tol(obj[b]), b
    assert obj["P1"] <= obj["B2"] + tol(obj["B2"])
    assert obj["P2"] <= obj["P1"] + tol(obj["P1"])
    assert obj["B2"] == pytest.approx(rec["methods"]["P2"]["two_stage_obj"], rel=1e-12)


def test_search_history_is_monotone_and_matches_results(case):
    _, _, rec = case
    p1, p2 = rec["methods"]["P1"], rec["methods"]["P2"]
    h = p2["history"]
    assert h[0][0] == 0 and h[0][2] == "two_stage" and h[0][1] == pytest.approx(p2["two_stage_obj"], rel=1e-12)
    assert all(a[0] <= b[0] for a, b in itertools.pairwise(h))
    assert all(b[1] <= a[1] + tol(a[1]) for a, b in itertools.pairwise(h))
    assert h[-1][2] == "end" and h[-1][1] == pytest.approx(p2["summary"]["obj"], rel=1e-9)
    assert p1["history"][-1][2] == "intra_end" and p1["history"] == h[:len(p1["history"])]
    assert p1["history"][-1][1] == pytest.approx(p1["summary"]["obj"], rel=1e-9)


def test_lower_bound_samples_never_exceed_exact_values(case):
    _, _, rec = case
    pairs = rec["methods"]["P2"]["lb_pairs"]
    assert 0 < len(pairs) <= LB_SAMPLES
    for n, lb, ex in pairs:
        assert n >= 1 and lb <= ex + tol(ex)


def test_event_timeline_is_consistent(case):
    _, _, rec = case
    for m, out in rec["methods"].items():
        by_uav: dict = {}
        for t in out["tasks"]:
            assert t["deliver_s"] - t["collect_s"] == pytest.approx(t["aoi_s"], abs=1e-9), m
            by_uav.setdefault(t["uav"], []).append(t)
        for u, ts in by_uav.items():
            assert [t["gid"] for t in ts] == out["routes"][u]   # 逐份记录按访问顺序排列
            assert all(a["collect_s"] < b["collect_s"] for a, b in itertools.pairwise(ts))


def test_instance_features_and_per_item_bound(case):
    inst, groups, rec = case
    f = rec["features"]
    assert f["n"] == inst.n and f["m"] == len(groups) and sum(f["per_uav"]) == inst.n
    assert 0.0 <= f["inside_coverage_frac"] <= 1.0
    assert f["slack_min_s"] >= -1e-9   # 不停靠的最短回路一定在预算内
    assert all(f["lb_norm"] <= out["summary"]["norm_aoi"] + 1e-12 for out in rec["methods"].values())
    g = rec["geometry"]
    assert len(g["tasks"]) == inst.n and len(g["points"]) == len(inst.points) and len(g["stations"]) == 3
    rows = summary_rows(rec, {"layout": "x"})
    assert [r["method"] for r in rows] == list(METHODS)
    assert not any(isinstance(v, (list, dict)) for r in rows for v in r.values())


@pytest.mark.parametrize("layout", ["fireline", "sector"])
def test_baselines_stay_feasible_without_slack(layout):
    """ε = 0 时预算最紧，所有基线仍须可行（贪心类规则只在余量内加停靠）"""
    inst, groups = make_instance(layout, 20, 3, 99, SP)
    budget = Budget(inst, 0.0, reference_t_hat(inst, groups))
    for m, build in BUILDERS.items():
        plan, info = build(inst, groups, budget)
        s = evaluate_solution(inst, plan, budget)["summary"]
        assert s["feasible"] and s["assigned_once"], m
        assert isinstance(info, dict)


def test_derived_params_are_platform_stable():
    """推导参数保留 9 位小数：末位差 1 个 ulp 的推导结果（不同平台数学库）对齐到同一个双精度数"""
    from uav_mec.scheme1.params import DERIVED_DECIMALS

    for v in (SP.p_fly_w, SP.p_hover_w, *(s[3] for s in SP.stations)):
        assert round(v, DERIVED_DECIMALS) == v
        for w in (math.nextafter(v, math.inf), math.nextafter(v, -math.inf)):
            assert round(w, DERIVED_DECIMALS) == v


def _reference_sin_cos(x: float) -> tuple[float, float]:
    """独立的参考实现：100 位十进制、不做自变量化简的泰勒级数（|x| < 20 时收敛足够）"""
    from decimal import Decimal, localcontext

    with localcontext() as ctx:
        ctx.prec = 100
        d = Decimal(x)
        s = c = Decimal(0)
        term = Decimal(1)
        for k in range(400):
            if k % 4 == 0:
                c += term
            elif k % 4 == 1:
                s += term
            elif k % 4 == 2:
                c -= term
            else:
                s -= term
            term = term * d / (k + 1)
        return float(s), float(c)


def test_stable_sin_cos_are_correctly_rounded():
    import random

    from uav_mec.scheme1 import stable_math

    rng = random.Random(7)
    # 含 2026-10-26 实测 Windows 数学库舍错的自变量
    xs = [5.736716405780561, 2.4215147753914708, 8.45613280630363, 6.983057550387843, math.pi / 4, 3 * math.pi / 4]
    xs += [rng.uniform(-13, 13) for _ in range(200)]
    for x in xs:
        assert (stable_math.sin(x), stable_math.cos(x)) == _reference_sin_cos(x), x
        assert abs(stable_math.sin(x) - math.sin(x)) <= math.ulp(math.sin(x))
    assert stable_math.sin(0.0) == 0.0 and stable_math.cos(0.0) == 1.0
    assert math.copysign(1.0, stable_math.sin(-0.0)) == -1.0


def test_instances_do_not_depend_on_platform_sin_cos(monkeypatch):
    """把平台的 math.sin/cos 都偏移 1 个 ulp，生成的观测点与候选上传点坐标不变"""
    def coords(layout):
        inst, groups = make_instance(layout, 30, 3, 97, SP)
        return [(t.x, t.y) for t in inst.tasks], list(inst.points), groups

    before = {lay: coords(lay) for lay in ("fireline", "sector")}
    sin0, cos0 = math.sin, math.cos
    monkeypatch.setattr(math, "sin", lambda x: math.nextafter(sin0(x), math.inf))
    monkeypatch.setattr(math, "cos", lambda x: math.nextafter(cos0(x), -math.inf))
    for lay, val in before.items():
        assert coords(lay) == val, lay


def load_plots():
    spec = importlib.util.spec_from_file_location("scheme1_plots", ROOT / "experiments" / "scheme1_plots.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plot_demo_writes_data_and_figures(tmp_path):
    pytest.importorskip("matplotlib")
    plots = load_plots()
    cfg = {"layouts": ("fireline", "sector"), "sizes": (12,), "m": 2, "seeds": (98, 99), "eps": (0.1, 0.25),
           "lb_samples": 10}
    plots.run_demo(tmp_path, workers=1, cfg=cfg)
    rows = plots.read_rows(tmp_path / "summary.csv")
    assert len(rows) == 2 * 2 * 2 * len(METHODS)
    assert len(list((tmp_path / "records").glob("*.json"))) == 8
    text, ok = plots.demo_report(rows)
    assert ok, text
    files = plots.plot_demo(tmp_path)
    assert len(files) == 2 * 2 * 16   # 两种语言 × PDF 与 PNG × 16 张图
    assert all(p.exists() and p.stat().st_size > 1000 for p in files)
    # 按规模分线的收敛图（F2）：每个 N 一条阶梯线和一组稀疏标记
    import json

    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((tmp_path / "records").glob("*.json"))]
    fig = plots.fig_convergence_by_n([r for r in recs if r["meta"]["eps"] == 0.1], "zh")
    assert len(fig.axes[0].get_lines()) == 2 * len({r["meta"]["n"] for r in recs})
    plots.plt.close(fig)


def test_plot_helpers():
    pytest.importorskip("matplotlib")
    plots = load_plots()
    m, h = plots.mean_ci([1.0, 2.0, 3.0])
    assert m == 2.0 and h == pytest.approx(2.4841, abs=1e-3)   # t₀.₉₇₅,₂ × 1 ÷ √3
    assert plots.mean_ci([5.0]) == (5.0, 0.0)
    assert plots.shade("#ffffff", 0.5) == "#808080"
    assert list(plots.METHOD_ORDER) == ["P2", "P1", "B2", "B1", "B3", "B4", "B0"]
    assert set(plots.COLORS) == set(plots.HATCHES) == set(plots.MARKERS) == set(METHODS)
    assert len(set(plots.COLORS.values())) == len(set(plots.HATCHES.values())) == len(METHODS)
    assert not math.isnan(plots.mean_ci([0.1, 0.1])[1])
    assert plots.tint("#000000", 0.5) == "#808080"
    assert all(plots.base_of(v) in METHODS for v in plots.VARIANT_OF)
    # 同一方法各档的颜色由浅到深；图例按行读出时的换序与 matplotlib 按列填充（前几列多放一项）一致
    cs = plots.level_colors(plots.COLORS["P2"], 6)
    assert len(set(cs)) == 6 and plots.level_colors("#2a78d6", 1) == ["#2a78d6"]
    assert sum(int(cs[0][i:i + 2], 16) for i in (1, 3, 5)) > sum(int(cs[-1][i:i + 2], 16) for i in (1, 3, 5))
    assert plots.row_major(list(range(6)), 3) == [0, 3, 1, 4, 2, 5]
    assert plots.row_major(list(range(7)), 4) == [0, 4, 1, 5, 2, 6, 3]
    assert plots.row_major(list(range(5)), 4) == [0, 4, 1, 2, 3]
    # 图例里带"（本文）"，子图标题用短名；其余方法两者相同
    assert plots.label("zh", "P2") == "SCOUT（本文）" and plots.short_label("zh", "P2") == "SCOUT"
    assert plots.short_label("en", "P2") == "SCOUT" and plots.short_label("en", "B2") == plots.label("en", "B2")


# ---------- E1–E3 用的附加方法与运行脚本 ----------

def _small_instance(seed: int, n: int):
    """小实例：每站圆心加 2 个 0.85R 环上点，便于穷举停靠方案"""
    import random

    from uav_mec.scheme1 import Instance, Task

    sp = SP.with_overrides(ring_fractions=(0.85,), points_per_ring=2)
    rng = random.Random(seed)
    tasks = [Task(i, rng.uniform(50, 2950), rng.uniform(50, 2950), rng.uniform(80, 160), rng.uniform(300, 600), 10.0)
             for i in range(n)]
    return Instance(sp, tasks)


@pytest.mark.parametrize("seed", range(4))
def test_depot_terminal_matches_brute_force(seed):
    """终点限基地：精确停靠与穷举（最后一站只能回基地）一致，且不优于不受限的停靠"""
    from uav_mec.scheme1 import exact_stops

    inst = _small_instance(seed, 5)
    route = list(range(5))
    cap = 1.25 * inst.route_length_m(route) / inst.params.speed_mps
    n, n_pts, best = len(route), len(inst.points), math.inf
    for r in range(n):
        for pos in itertools.combinations(range(1, n), r):
            for pts in itertools.product(range(n_pts), repeat=r):
                sim = simulate(inst, route, list(zip(pos, pts)) + [(n, -1)])
                if sim.fly_s <= cap + 1e-9:
                    best = min(best, sim.objective)
    got = exact_stops(inst, route, cap, depot_only=True)
    assert got[2][-1] == (n, -1)
    assert got[0] == pytest.approx(best, rel=1e-12)
    assert exact_stops(inst, route, cap)[0] <= got[0] + 1e-12


def test_fleet_variants_and_extra_baselines():
    """P2D 的最后一站都在基地；P2A、P2N 与 P2 相同；B2 ≤ B2R；往返方案达到逐份下界；两个上限的较小者即 cap"""
    from uav_mec.scheme1 import EXTRA_METHODS

    inst, groups = make_instance("fireline", 16, 2, 98, SP)
    rec = run_methods(inst, groups, 0.1, methods=METHODS + EXTRA_METHODS, tag=("fireline", 16, 2, 98, 0.1))
    ms = rec["methods"]
    assert all(st[-1][1] == -1 for st in ms["P2D"]["stops"] if st) and ms["P2D"]["summary"]["feasible"]
    assert ms["P2A"]["routes"] == ms["P2N"]["routes"] == ms["P2"]["routes"]
    assert ms["P2A"]["summary"]["obj"] == ms["P2N"]["summary"]["obj"] == ms["P2"]["summary"]["obj"]
    assert ms["B2"]["summary"]["obj"] <= ms["B2R"]["summary"]["obj"] + 1e-9 and ms["B2R"]["summary"]["feasible"]
    assert ms["PP"]["summary"]["norm_aoi"] == pytest.approx(rec["features"]["lb_norm"], rel=1e-12)
    budget = Budget(inst, 0.1, rec["t_hat"])
    for r in ms["P2"]["routes"]:
        assert min(budget.caps(r)) == budget.cap(r)


def load_experiments():
    spec = importlib.util.spec_from_file_location("scheme1_experiments", ROOT / "experiments" / "scheme1_experiments.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_experiment_jobs_and_shards():
    ex = load_experiments()
    sizes = {e: len(ex.jobs(e)) for e in ("E1", "E2", "E3")}
    assert sizes == {"E1": 480, "E2": 280, "E3": 160}
    assert not any(j[4] in ex.E1_EPS for j in ex.jobs("E2"))
    for exp, k in (("E1", 7), ("E2", 5), ("E3", 3)):
        parts = [ex.shard_jobs(exp, s, k) for s in range(k)]
        flat = [j for p in parts for j in p]
        assert sorted(flat) == sorted(ex.jobs(exp)) and len(flat) == len(set(flat))


def test_paired_statistics():
    pytest.importorskip("scipy")
    pytest.importorskip("matplotlib")
    ex = load_experiments()
    st = ex.paired([2.0, 4.0, 8.0], [1.0, 2.0, 4.0])
    assert st["median"] == pytest.approx(50.0) and (st["wins"], st["ties"], st["losses"]) == (3, 0, 0)
    eq = ex.paired([1.0, 2.0], [1.0, 2.0])
    assert eq["p"] == 1.0 and eq["ties"] == 2
