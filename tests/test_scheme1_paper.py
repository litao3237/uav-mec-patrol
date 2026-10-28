"""方案一论文图表整理脚本的测试：LaTeX 转义、表 1 的取值、表 3 的统计与输出、SCOUT+ 一行与表 4、按编号收集图、示意图"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tex_escape():
    pp = load("scheme1_paper")
    s = pp.tex_escape("(1+ε)·T̂，ε ∈ {0.1, 0.25}，100% — δ")
    assert "\\{0.1, 0.25\\}" in s and "$\\hat{T}$" in s and "\\%" in s and "---" in s and "$\\delta$" in s
    assert "T̂" not in s and "̂" not in s


def test_table1_rows():
    pp = load("scheme1_paper")
    rows = {r["item_zh"]: r for r in pp.table1_rows()}
    assert rows["覆盖半径"]["val_zh"].startswith("597.88 m")
    assert rows["电池容量"]["val_en"] == "360 kJ (100 Wh)"
    assert "{0.1, 0.25}" in rows["任务时长预算"]["val_zh"]
    assert "n = 13 时取 3000" in rows["机内局部搜索评估上限"]["val_zh"]   # 字典里与公式不同的唯一一项
    assert all(r["sym_tex"] for r in rows.values())


def fake_e1_rows(path: Path) -> None:
    """两个种子的假 E1 行：各方法的指标取不同常数，便于检查均值与格式"""
    keys = ["exp", "layout", "n", "m", "seed", "eps", "method", "lb_norm"] + [k for k, _, _ in load("scheme1_paper").T3_METRICS]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for lay in ("fireline", "sector"):
            for eps in (0.1, 0.25):
                for seed in (100, 101):
                    for j, m in enumerate(("P2", "P1", "B2", "B1", "B3", "B4", "B0")):
                        row = {"exp": "E1", "layout": lay, "n": 50, "m": 5, "seed": seed, "eps": eps, "method": m,
                               "lb_norm": 0.1, "norm_aoi": 0.2 + 0.1 * j, "mean_aoi_s": 80.0, "p95_aoi_s": 150.0,
                               "on_time_rate": 1.0, "max_mission_min": 14.0, "energy_kj": 590.0,
                               "stops_per_uav": 4.0, "secs": 10.0 + seed - 100}
                        w.writerow(row)


def test_tables(tmp_path):
    pp = load("scheme1_paper")
    fake_e1_rows(tmp_path / "E1_rows.csv")
    files = pp.write_tables(tmp_path / "E1_rows.csv", tmp_path / "out")
    assert all(p.is_file() for p in files) and len(files) == 2 * 4 * 2 + 2
    md = (tmp_path / "out" / "tables" / "zh" / "表3a_主结果_eps0.1.md").read_text(encoding="utf-8")
    assert "| SCOUT（本文） | 0.200 ± 0.000 |" in md and "| 逐份下界 | 0.100 ± 0.000 | — |" in md
    assert "**火线布点，ε = 0.1**" in md and "**扇形布点，ε = 0.1**" in md
    tex = (tmp_path / "out" / "tables" / "en" / "Table3a_main_results_eps0.1.tex").read_text(encoding="utf-8")
    assert "On-time (\\%)" in tex and "\\toprule" in tex and "SCOUT-intra &" in tex
    assert tex.count("---") >= 1                         # P1 不单列求解时间
    assert b"\r" not in (tmp_path / "out" / "tables" / "zh" / "表1_关键实验参数.md").read_bytes()
    assert "SCOUT+ |" not in md and "SCOUT+ 一行" not in md       # 不给 E8 时没有 SCOUT+ 一行


def fake_e8_record(seed: int, p2_secs: float, chains: list[float], cold_sum: float, k: int, job: float,
                   gain: float, split: bool = False) -> dict:
    """假 E8 记录：只含表 4 用到的字段；ILS 的计算量 = 各链耗时 + 冷启动求解的总耗时"""
    rec = {"meta": {"layout": "fireline", "n": 50, "m": 5, "seed": seed, "eps": 0.1},
           "p2": {"norm_aoi": 0.2, "secs": p2_secs},
           "ils": {"norm_aoi": 0.2 * (1 - gain / 100), "secs": sum(chains) + cold_sum},
           "chains": [{"secs": s} for s in chains], "cold_chains": k, "job_secs": job, "gain": {"final": gain}}
    if split:
        rec["split"] = {"note": "补跑"}
    return rec


def test_e8_timing_and_table4():
    pp = load("scheme1_paper")
    a = fake_e8_record(100, 10.0, [20.0, 30.0, 25.0, 15.0], 36.0, 3, 50.0, 2.0)
    # 冷启动平均 12 s 长于 SCOUT 的 10 s：下界 = 12 + 最长链 30 − 10；上界 = 整例墙钟 50 − 10
    assert pp.e8_timing(a) == {"p2": 10.0, "lo": 32.0, "hi": 40.0}
    b = fake_e8_record(101, 20.0, [10.0, 10.0, 10.0, 40.0], 0.0, 0, 70.0, 4.0)
    assert pp.e8_timing(b) == {"p2": 20.0, "lo": 40.0, "hi": 50.0}             # 没有冷启动链时第一阶段只有 SCOUT
    c = fake_e8_record(102, 999.0, [1.0, 1.0, 1.0, 1.0], 3.0, 3, 9999.0, 9.0, split=True)
    (row,) = pp.table4_data([a, b, c])
    assert (row["instances"], row["timed"]) == (3, 2)                          # 补跑记录计入改善，不计入耗时
    assert (row["gain_mean"], row["gain_median"], row["gain_max"]) == (5.0, 4.0, 9.0)
    assert (row["scout_secs"], row["extra_lo"], row["extra_hi"]) == (15.0, 36.0, 45.0)
    assert (row["ratio_lo"], row["ratio_hi"]) == (2.6, 3.25)                   # 逐例比值 3.2、2.0 与 4.0、2.5 的中位数
    md = "\n".join(pp.table4_lines([row], "zh"))
    assert "| **火线布点** |" in md and "扇形" not in md.split("注：")[0]
    assert "| 50 | 0.1 | 0.2000 | 0.1900 | 5.00 / 4.00 / 9.00 | 15 | 36–45 | 2.6–3.2 |" in md
    tex = "\n".join(pp.table4_lines([row], "en", tex=True))
    assert "$\\varepsilon$" in tex and "36--45" in tex and "Gain (\\%)" in tex and tex.startswith("% Note:")


def test_tables_with_e8(tmp_path):
    pp = load("scheme1_paper")
    fake_e1_rows(tmp_path / "E1_rows.csv")
    d = tmp_path / "e8" / "records"
    d.mkdir(parents=True)
    for k, eps in enumerate((0.1, 0.25)):
        for seed in (100, 101):
            rec = fake_e8_record(seed, 10.0, [20.0, 30.0, 25.0, 15.0], 36.0, 3, 50.0, 2.0 + k)
            rec["meta"]["eps"] = eps
            for lay in ("fireline", "sector"):
                rec["meta"]["layout"] = lay
                (d / f"E8_{lay}_n50_s{seed}_e{eps}.json").write_text(json.dumps(rec), encoding="utf-8")
    # SCOUT+ 的指标按记录的方案重算；假记录没有方案，这里换成固定值，只检查表的组装
    fake = {"norm_aoi": 0.19, "mean_aoi_s": 70.0, "p95_aoi_s": 140.0, "on_time_rate": 1.0, "max_mission_min": 14.0,
            "energy_kj": 591.0, "stops_per_uav": 4.5}
    pp.scout_plus_summary = lambda rec, params: fake
    files = pp.write_tables(tmp_path / "E1_rows.csv", tmp_path / "out", [tmp_path / "e8"])
    assert all(p.is_file() for p in files) and len(files) == 2 * 5 * 2 + 3
    md = (tmp_path / "out" / "tables" / "zh" / "表3a_主结果_eps0.1.md").read_text(encoding="utf-8")
    lines = md.splitlines()
    plus = ("| SCOUT+ | 0.190 ± 0.000 | 70.0 ± 0.0 | 140.0 ± 0.0 | 100.0 ± 0.0 | 14.00 ± 0.00 | 591 ± 0 "
            "| 4.50 ± 0.00 | — |")
    i = lines.index(plus)
    assert lines[i - 1].startswith("| SCOUT（本文） |") and lines[i + 1].startswith("| SCOUT-intra |")
    assert "SCOUT+ 一行取自 E8" in md
    t4 = (tmp_path / "out" / "tables" / "en" / "Table4_enhancement_gain_and_time.md").read_text(encoding="utf-8")
    assert "| 50 | 0.25 | 0.2000 | 0.1940 | 3.00 / 3.00 / 3.00 | 10 | 32–40 | 3.2–4.0 |" in t4
    t2 = (tmp_path / "out" / "tables" / "zh" / "表2_比较方法.md").read_text(encoding="utf-8")
    assert "| ILS | SCOUT+ |" in t2


def test_scout_plus_summary_recomputes_plan():
    pp = load("scheme1_paper")
    from uav_mec.scheme1 import (Budget, SearchConfig, evaluate_solution, load_scheme1_params, make_instance,
                                 reference_t_hat, solve_fleet)

    params = load_scheme1_params(str(pp.CONFIG))
    inst, groups = make_instance("fireline", 12, 3, 100, params)
    t_hat = reference_t_hat(inst, groups)
    res = solve_fleet(inst, groups, 0.1, SearchConfig(), tag=("test",), t_hat=t_hat)
    stops = [list(pl[2]) for pl in res.plans]
    want = evaluate_solution(inst, list(zip(res.routes, stops)), Budget(inst, 0.1, t_hat))["summary"]
    # 经 JSON 往返，与 E8 记录的形式相同（元组变成列表）
    rec = json.loads(json.dumps({"meta": {"layout": "fireline", "n": 12, "m": 3, "seed": 100, "eps": 0.1},
                                 "ils": {"routes": res.routes, "stops": stops, "norm_aoi": want["norm_aoi"]}}))
    got = pp.scout_plus_summary(rec, params)
    assert all(got[k] == want[k] for k, _, _ in pp.T3_METRICS if k != "secs")
    rec["ils"]["norm_aoi"] += 1e-9
    with pytest.raises(ValueError):
        pp.scout_plus_summary(rec, params)


def test_collect(tmp_path):
    pp = load("scheme1_paper")
    src, src5, src8 = tmp_path / "e123", tmp_path / "e5", tmp_path / "e8"
    for lang in pp.LANGS:
        d = src / "figures" / lang
        d.mkdir(parents=True)
        for ext in pp.EXTS:
            (d / f"E1_F4_norm_aoi_fireline_eps0.1.{ext}").write_bytes(b"x")
        (src5 / "figures" / lang).mkdir(parents=True)
        (src5 / "figures" / lang / "E5_F3_acceleration_time.pdf").write_bytes(b"x")     # 只有 PDF：不全
        (src8 / "figures" / lang).mkdir(parents=True)
        for ext in pp.EXTS:
            (src8 / "figures" / lang / f"E8_X16_gain_vs_budget.{ext}").write_bytes(b"x")
    rows = pp.collect({"E1_E3": src, "E5": src5, "E8": src8}, tmp_path / "out")
    by = {r["file"]: r for r in rows}     # 文件名为"编号_原图名"，保留原图名便于追溯来源
    assert by["F04_E1_F4_norm_aoi_fireline_eps0.1"]["status"] == "齐"
    assert by["F03a_E5_F3_acceleration_time"]["status"] == "不全（2/4）"     # F3 取自 E5 的计时
    assert by["X16_E8_X16_gain_vs_budget"]["status"] == "齐"                 # E8 的图也由 collect 收录
    assert by["F01_E5_F1_stop_dp_vs_bruteforce"]["status"] == "缺"
    assert (tmp_path / "out" / "figures" / "en" / "main" / "F04_E1_F4_norm_aoi_fireline_eps0.1.png").is_file()
    pp.write_manifest(rows, tmp_path / "out")
    text = (tmp_path / "out" / "图的清单.md").read_text(encoding="utf-8")
    assert "## 正文结果图" in text and "| F04 |" in text


def test_schematics(tmp_path):
    pytest.importorskip("matplotlib")
    e7 = load("scheme1_e7")
    e7.N, e7.M_UAV = 12, 3
    case = tmp_path / "case.json"
    case.write_text(json.dumps(e7.solve_case(100)), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "experiments"))
    sch = load("scheme1_schematics")
    files = sch.draw_all(case, tmp_path / "out")
    assert len(files) == 16 and all(p.is_file() for p in files)
