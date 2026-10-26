"""方案一 E5 运行脚本的测试：运行单元与分片、穷举得到的精确最优、停靠动态规划与枚举对拍、汇总流程"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from uav_mec.scheme1 import exact_stops, load_scheme1_params, make_instance

ROOT = Path(__file__).resolve().parents[1]
SP = load_scheme1_params("configs/v27_timeliness.yaml")


def load_e5():
    spec = importlib.util.spec_from_file_location("scheme1_e5", ROOT / "experiments" / "scheme1_e5.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_jobs_and_shards_cover_everything_once():
    e5 = load_e5()
    assert {x: len(e5.jobs(x)) for x in ("X", "T", "F1")} == {"X": 120, "T": 72, "F1": 90}
    for exp, k in (("X", 4), ("T", 7), ("F1", 1)):
        flat = [j for s in range(k) for j in e5.shard_jobs(exp, s, k)]
        assert sorted(flat) == sorted(e5.jobs(exp)) and len(flat) == len(set(flat))


def test_enumeration_gives_the_optimum():
    """穷举的精确最优不劣于本文方法与两阶段，且能用精确停靠在最优顺序上复算出来"""
    e5 = load_e5()
    inst, groups = make_instance("fireline", 30, 5, 98, SP)
    out = e5.single_group(inst, groups[0], "fireline", 30, 98, 0)
    assert out["n"] == 6
    for e, v in out["eps"].items():
        tol = 1e-9 * v["exact"]
        assert v["exact"] <= v["p1"] + tol and v["exact"] <= v["b2"] + tol
        assert exact_stops(inst, v["exact_perm"], v["cap_s"])[0] == pytest.approx(v["exact"], rel=1e-12)
        assert sorted(v["exact_perm"]) == sorted(groups[0])


@pytest.mark.parametrize("n", [3, 4])
def test_stop_dp_matches_bruteforce(n):
    e5 = load_e5()
    for idx in range(2):
        r = e5.run_f1(("F1", n, idx))
        assert r["dp"] == pytest.approx(r["brute"], rel=1e-12)


def test_run_and_summarize_small(tmp_path):
    pytest.importorskip("matplotlib")
    e5 = load_e5()
    jl = [("X", "sector", 30, 98), ("T", "fireline", 30, 7, 98), ("F1", 4, 0)]
    e5.run_jobs(jl, tmp_path / "shards", workers=1, log_name="test")
    ok = e5.summarize([tmp_path / "shards"], tmp_path / "summary", {"X": 5, "T": 1, "F1": 1})
    assert ok
    text = (tmp_path / "summary" / "summary.txt").read_text(encoding="utf-8")
    assert "检查：全部通过" in text
    assert len(list((tmp_path / "summary" / "figures" / "zh").glob("*.png"))) == 3
