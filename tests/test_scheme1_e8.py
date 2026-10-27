"""方案一 E8 脚本的测试：运行单元与分片、链的起点、轮转分配、扰动、P2 逐步复现与冻结求解器相同、判定规则、运行与汇总流程"""

from __future__ import annotations

import importlib.util
import random
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_e8():
    spec = importlib.util.spec_from_file_location("scheme1_e8", ROOT / "experiments" / "scheme1_e8.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def small(e8, layout: str, n: int = 30, seed: int = 97):
    sp = e8.load_scheme1_params(str(e8.CONFIG))
    return e8.make_instance(layout, n, e8.M_UAV, seed, sp)


def test_jobs_and_shards():
    e8 = load_e8()
    js = e8.jobs()
    assert len(js) == 3 * 2 * 2 * 20 and len(set(js)) == len(js)
    shards = 40                                              # 与 scheme1-e8.yml 的分片数一致
    parts = [e8.shard_jobs(s, shards) for s in range(shards)]
    assert all(parts) and sorted(j for p in parts for j in p) == sorted(js)


def test_chain_specs():
    e8 = load_e8()
    p2 = {"routes": [[0, 1], [2]], "objective": 1.0}
    for n_cold in range(e8.CHAINS):
        colds = [{"k": k, "offset": 10 + k, "routes": [[k]], "objective": 2.0, "evals": 100 * k}
                 for k in range(1, n_cold + 1)]
        specs = e8.chain_specs(p2, colds)
        assert len(specs) == e8.CHAINS and len({s["key"] for s in specs}) == e8.CHAINS     # 链数固定，随机数流互不相同
        assert specs[0]["start"] == "warm" and specs[0]["key"] == (0,)                    # 链 0 与原方案相同
        cold = [s for s in specs if s["start"] == "cold"]
        assert [s["offset"] for s in cold] == [c["offset"] for c in colds]
        assert [s["used0"] for s in cold] == [c["evals"] for c in colds]                  # 冷启动的初始求解计入本链
        assert all(s["used0"] == 0 and s["routes"] is p2["routes"] for s in specs if s["start"] == "warm")


def test_reference_data():
    e8 = load_e8()
    ref = e8.load_ref()
    assert len(ref) == 160                                   # E1 中 N = 50、80 的 P2，两种布点 × 两档 ε × 20 个种子
    assert {k[1] for k in ref} == {50, 80} and all(v > 0 for v in ref.values())


def test_rotated_groups_and_kicks():
    e8 = load_e8()
    for layout in e8.LAYOUTS:
        inst, groups = small(e8, layout)
        assert e8.rotated_groups(inst, layout, e8.M_UAV, 0) == groups      # 偏移 0 即原初始分配
        g3 = e8.rotated_groups(inst, layout, e8.M_UAV, 3)
        assert sorted(g for r in g3 for g in r) == list(range(inst.n)) and g3 != groups
        rng = random.Random(1)
        for kind, fn in e8.KICKS.items():
            for _ in range(20):
                res = fn(inst, groups, rng)
                if res is None:
                    continue
                new, changed = res
                assert Counter(g for r in new for g in r) == Counter(range(inst.n)), kind
                assert all(new) and set(changed) <= set(range(len(new))), kind


def test_replica_matches_frozen():
    e8 = load_e8()
    for layout, eps in (("fireline", 0.1), ("sector", 0.25)):
        inst, groups = small(e8, layout, n=20, seed=98)
        cfg = e8.SearchConfig()
        t_hat = e8.reference_t_hat(inst, groups)
        tag = (layout, 20, e8.M_UAV, 98, eps)
        res = e8.solve_fleet(inst, groups, eps, cfg, tag=tag, t_hat=t_hat)
        rep = e8.replicate_p2(inst, groups, eps, t_hat, cfg, tag)
        assert rep["routes"] == res.routes and rep["objective"] == res.objective
        assert rep["per_route"] == res.per_route and rep["inter_evals"] == res.stats["inter_evals"]


def test_decide():
    e8 = load_e8()

    def rows(gains):
        return [{"layout": lay, "n": n, "eps": e, "gain_final": g}
                for (lay, n, e), g in zip([(lay, n, e) for lay in e8.LAYOUTS for n in (80, 120) for e in e8.EPS], gains)]

    assert e8.decide(rows([0.5] * 8))["band"] == "sufficient"
    assert e8.decide(rows([0.5] * 7 + [2.5]))["band"] == "middle"        # 有一格 ≥ 2%，不能算足够
    assert e8.decide(rows([1.5] * 8))["band"] == "middle"
    assert e8.decide(rows([3.2] * 8))["band"] == "upgrade"
    assert e8.decide(rows([0.5] * 7 + [5.5]))["band"] == "upgrade"       # 任一格 ≥ 5% 即升级


def test_run_and_summarize_small(tmp_path):
    pytest.importorskip("matplotlib")
    e8 = load_e8()
    jl = e8.jobs(sizes=(20,), seeds=(97,), eps_list=(0.1,))
    e8.run_jobs(jl, tmp_path / "shards", workers=1, log_name="test")
    assert e8.summarize([tmp_path / "shards"], tmp_path / "summary", expected=len(jl), sizes=(20,))
    text = (tmp_path / "summary" / "summary.txt").read_text(encoding="utf-8")
    assert "检查：全部通过" in text and "判定" in text
    rec = e8.load_records([tmp_path / "shards"])[0]
    assert rec["ils"]["obj"] <= rec["p2"]["obj"] and rec["p2"]["replica_ok"]
    assert rec["ils"]["evals"] >= e8.BUDGET_X * rec["p2"]["evals"] * 0.99 or any(
        c["stop"] != "budget" for c in rec["chains"])
    for lang in ("zh", "en"):
        assert len(list((tmp_path / "summary" / "figures" / lang).glob("*.png"))) == 2
