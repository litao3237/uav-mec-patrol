"""E2、E6 补跑三个基线的测试：运行单元、与原实验同一实例（B2 逐位相同）、检查与汇总、并入原结果"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_supp():
    sys.path.insert(0, str(ROOT / "experiments"))
    spec = importlib.util.spec_from_file_location("scheme1_supp", ROOT / "experiments" / "scheme1_supp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_jobs():
    supp = load_supp()
    js = supp.jobs()
    assert len(js) == 280 + 1120 and len(set(js)) == len(js)
    assert {j[5] for j in js if j[0] == "E2"} == {0.0, 0.05, 0.15, 0.35, 0.5, 0.75, 1.0}   # 0.1、0.25 已在 E1 中
    assert [j[1:] for j in js if j[0] == "E6"] == supp.e6.jobs()
    assert sorted(j for s in range(4) for j in supp.shard_jobs(s, 4)) == sorted(js)


def test_same_instances_as_original_and_summary(tmp_path, monkeypatch):
    """缩小规模后各跑一个 E2、E6 实例：补跑的 B2 与原实验运行函数给出的 B2 逐位相同，检查通过；参考值改动后检查失败"""
    supp = load_supp()
    # 缩小规模以加快测试；原实验的运行函数读同一个模块常量，测试结束后还原
    monkeypatch.setattr(supp.e123, "E2_N", 12)
    monkeypatch.setattr(supp.e6, "N", 12)
    jobs = [("E2", "-", "-", "fireline", 100, 0.5), ("E6", "radius", "300", "sector", 101, 0.1)]
    supp.run_jobs(jobs, tmp_path / "shards" / "S0", workers=1, log_name="t")
    ref_rows = []
    orig2 = supp.e123.run_job(("E2", "fireline", 12, 100, 0.5))
    ref_rows.append(("E2", "-", "-", "fireline", 100, 0.5, repr(orig2["methods"]["B2"]["summary"]["obj"])))
    orig6 = supp.e6.run_job(("radius", "300", "sector", 101, 0.1))
    ref_rows.append(("E6", "radius", "300", "sector", 101, 0.1, repr(orig6["methods"]["B2"]["summary"]["obj"])))
    ref = tmp_path / "ref.csv"
    with open(ref, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([*supp.KEY_FIELDS, "b2_obj"])
        w.writerows(ref_rows)
    assert supp.summarize([tmp_path / "shards"], tmp_path / "summary", expected=2, ref_path=ref)
    text = (tmp_path / "summary" / "summary.txt").read_text(encoding="utf-8")
    assert "检查：全部通过" in text and "B1" in text
    # 参考值改动一位：B2 核对失败
    ref_rows[1] = (*ref_rows[1][:6], repr(float(ref_rows[1][6]) * (1 + 1e-12)))
    with open(ref, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([*supp.KEY_FIELDS, "b2_obj"])
        w.writerows(ref_rows)
    assert not supp.summarize([tmp_path / "shards"], tmp_path / "summary2", expected=2, ref_path=ref)
    # 并入 E6 原记录：补上三个基线；B2 不同时报错
    rec6 = supp.load_records([tmp_path / "shards"])
    merged = supp.merge_e6([json.loads(json.dumps(orig6))], rec6)
    assert set(merged[0]["methods"]) >= {"P2", "P1", "B2", "B0", "B1", "B3", "B4"}
    bad = json.loads(json.dumps(orig6))
    bad["methods"]["B2"]["summary"]["obj"] += 1.0
    with pytest.raises(ValueError):
        supp.merge_e6([bad], rec6)


def test_merge_e2_rows():
    """E2 的 7 种方法：原 E2 行 + E1 中 N = 50、ε = 0.1、0.25 的三个基线 + 补跑行；补跑的 B2 与原行不同时报错"""
    supp = load_supp()
    e2 = [{"exp": "E2", "layout": "fireline", "seed": 100.0, "eps": 0.5, "method": "B2", "obj": 3.0}]
    e1 = [{"exp": "E1", "layout": "fireline", "n": 50.0, "seed": 100.0, "eps": 0.1, "method": m, "obj": 1.0}
          for m in ("B1", "B3", "B4", "B2")]
    rec = {"meta": {"exp": "E2", "factor": "-", "level": "-", "layout": "fireline", "n": 50, "m": 5, "seed": 100,
                    "eps": 0.5},
           "features": {"lb_norm": 0.1},
           "methods": {m: {"secs": 0.0, "summary": {"obj": 3.0 if m == "B2" else 4.0}} for m in supp.SUPP_METHODS}}
    rows = supp.merge_e2(e2, e1, [rec])
    assert sorted(r["method"] for r in rows) == ["B1", "B1", "B2", "B3", "B3", "B4", "B4"]
    assert all(r["exp"] == "E2" for r in rows)
    rec["methods"]["B2"]["summary"]["obj"] = 3.5
    with pytest.raises(ValueError):
        supp.merge_e2(e2, e1, [rec])
