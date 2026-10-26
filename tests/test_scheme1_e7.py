"""方案一 E7 案例脚本的测试：案例选择规则、航段与途中上传的统计、读记录到出图的流程与重算复核"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_e7():
    spec = importlib.util.spec_from_file_location("scheme1_e7", ROOT / "experiments" / "scheme1_e7.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_select_cases():
    e7 = load_e7()
    # 偶数个实例：中位数 3.0，种子 100、101、102 都差 1.0，取种子小的；最大值 4.0 并列时也取种子小的
    assert e7.select_cases({100: 2.0, 101: 4.0, 102: 4.0, 103: 1.0}) == {"median": 100, "max": 101}
    # 两个值离中位数在数学上一样近，浮点运算可能让其中一个略近，规则仍取种子小的
    assert e7.select_cases({5: 1.1, 7: 0.1 + 0.7})["median"] == 5
    assert e7.select_cases({5: 0.1 + 0.7, 7: 1.1})["median"] == 5


def test_edges_and_mid_route():
    e7 = load_e7()
    routes = [[3, 1, 2], [], [0]]
    assert e7.edges(routes) == {(-1, 3), (1, 3), (1, 2), (-1, 2), (-1, 0)}
    assert e7.uav_of(routes) == {3: 0, 1: 0, 2: 0, 0: 2}
    # 第 1 架机采完第 1、2 个点后各停靠一次、最后回基地上传：途中上传 2 份；第 3 架机只有返航前的上传
    stops = [[[1, 4], [2, 5], [3, -1]], [], [[1, 4]]]
    assert e7.mid_route_frac(routes, stops) == 2 / 4


def test_run_small(tmp_path):
    pytest.importorskip("matplotlib")
    e7 = load_e7()
    e7.N, e7.M_UAV = 12, 3          # 缩小规模以加快测试
    seeds = (100, 101, 102)
    e1 = tmp_path / "e1"
    (e1 / "records").mkdir(parents=True)
    for s in seeds:
        e7.record_path(e1, s).write_text(json.dumps(e7.solve_case(s)), encoding="utf-8")
    assert e7.run(e1, tmp_path / "out", do_verify=True, seeds=seeds)
    text = (tmp_path / "out" / "summary.txt").read_text(encoding="utf-8")
    assert "逐位相同" in text and "### 典型" in text and "### 收益最大" in text
    rows = (tmp_path / "out" / "E7_case_metrics.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 2 * len(e7.TABLE)
    for lang in ("zh", "en"):
        assert len(list((tmp_path / "out" / "figures" / lang).glob("*.png"))) == 8   # 两个案例 × 四张图
