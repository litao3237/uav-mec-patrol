"""方案一论文图表整理脚本的测试：LaTeX 转义、表 1 的取值、表 3 的统计与输出、按编号收集图、示意图"""

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
    assert "| 本文方法 | 0.200 ± 0.000 |" in md and "| 逐份下界 | 0.100 ± 0.000 | — |" in md
    assert "**火线布点，ε = 0.1**" in md and "**扇形布点，ε = 0.1**" in md
    tex = (tmp_path / "out" / "tables" / "en" / "Table3a_main_results_eps0.1.tex").read_text(encoding="utf-8")
    assert "On-time (\\%)" in tex and "\\toprule" in tex and "Proposed (intra) &" in tex
    assert tex.count("---") >= 1                         # P1 不单列求解时间
    assert b"\r" not in (tmp_path / "out" / "tables" / "zh" / "表1_关键实验参数.md").read_bytes()


def test_collect(tmp_path):
    pp = load("scheme1_paper")
    src = tmp_path / "e123"
    for lang in pp.LANGS:
        d = src / "figures" / lang
        d.mkdir(parents=True)
        for ext in pp.EXTS:
            (d / f"E1_F4_norm_aoi_fireline_eps0.1.{ext}").write_bytes(b"x")
        (d / "E3_F3_acceleration_time.pdf").write_bytes(b"x")     # 只有 PDF：不全
    rows = pp.collect({"E1_E3": src}, tmp_path / "out")
    by = {r["file"]: r for r in rows}     # 文件名为"编号_原图名"，保留原图名便于追溯来源
    assert by["F04_E1_F4_norm_aoi_fireline_eps0.1"]["status"] == "齐"
    assert by["F03a_E3_F3_acceleration_time"]["status"] == "不全（2/4）"
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
