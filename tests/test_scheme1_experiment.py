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
