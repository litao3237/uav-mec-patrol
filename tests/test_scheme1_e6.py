"""方案一 E6 运行脚本的测试：运行单元与分片、各档的参数变体、运行与汇总流程"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_e6():
    spec = importlib.util.spec_from_file_location("scheme1_e6", ROOT / "experiments" / "scheme1_e6.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_jobs_and_shards():
    e6 = load_e6()
    js = e6.jobs()
    assert len(js) == 80 * 14 and len(set(js)) == len(js)   # 默认档 + 13 个非默认档，每档 80 个实例
    flat = [j for s in range(5) for j in e6.shard_jobs(s, 5)]
    assert sorted(flat) == sorted(js)


def test_level_variants():
    e6 = load_e6()
    base, m0 = e6.variant("base", "-")
    r0 = base.stations[0][3]
    assert m0 == 5 and len(base.stations) == 3
    one, _ = e6.variant("stations", "1")
    four, _ = e6.variant("stations", "4")
    assert [s[0] for s in one.stations] == ["E1"]
    assert four.stations[:3] == base.stations and four.stations[3] == ("E4", 2600.0, 2600.0, r0)
    assert all(s[3] == 300.0 for s in e6.variant("radius", "300")[0].stations)
    assert e6.variant("freshness", "150-300")[0].freshness_s == (150.0, 300.0)
    assert e6.variant("battery", "180")[0].battery_j == 180000.0
    assert e6.variant("rate", "60")[0].rate_mbps == 60.0
    assert e6.variant("uavs", "7")[1] == 7
    # 默认档的参数与冻结配置完全相同（默认档结果须与 E1 一致）
    for f, spec in e6.FACTORS.items():
        sp, m = e6.variant(f, spec["default"])
        assert sp == base and m == m0, f


def test_run_and_summarize_small(tmp_path):
    pytest.importorskip("matplotlib")
    e6 = load_e6()
    e6.N = 20     # 缩小规模以加快测试
    sub = {k: e6.FACTORS[k] for k in ("stations", "freshness")}
    jl = [j for j in e6.jobs(seeds=(98,), factors=sub) if j[4] == 0.1]
    e6.run_jobs(jl, tmp_path / "shards", workers=1, log_name="test")
    assert e6.summarize([tmp_path / "shards"], tmp_path / "summary", expected=len(jl), factors=list(sub))
    text = (tmp_path / "summary" / "summary.txt").read_text(encoding="utf-8")
    assert "检查：全部通过" in text
    assert len(list((tmp_path / "summary" / "figures" / "zh").glob("*.png"))) == 3
