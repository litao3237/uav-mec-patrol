"""方案一 E8 补跑脚本的测试：补跑与复现实例清单、任务身份、按阶段列出任务、拆开运行与就地运行逐位相同、比对只忽略耗时"""

from __future__ import annotations

import importlib.util
import json
import pickle
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TINY = [("fireline", 20, 97, 0.1), ("sector", 20, 97, 0.1)]      # 冒烟规模，单个实例几秒


def load_fill():
    spec = importlib.util.spec_from_file_location("scheme1_e8_fill", ROOT / "experiments" / "scheme1_e8_fill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_split(f, job: tuple):
    """按 replay → 运行缺的任务 → 再 replay 的顺序拆开运行一个实例；任务结果经 pickle 往返，与进程间传结果相同

    :return: (记录, {任务身份: 结果}, {任务身份: {"name", "wall"}})
    """
    results, info = {}, {}
    for stage in (1, 2, 3):
        rec, pending = f.replay(job, results)
        if rec is not None:
            return rec, results, info
        for i, t in enumerate(pending):
            r = pickle.loads(pickle.dumps(f.run_task({"job": job, **t}), protocol=pickle.HIGHEST_PROTOCOL))
            results[r["key"]] = r["result"]
            info[r["key"]] = {"name": f"{f.inst_name(job)}.s{stage}.{i}.{f.LABELS[t['fn']]}", "wall": r["wall"]}
    raise AssertionError("两个阶段后仍未组装出记录")


def test_sets():
    f = load_fill()
    assert sorted(f.MISSING) == sorted(f.e8.shard_jobs(13, 40))     # E8 中超时的分片 13
    assert not set(f.REPRO) & set(f.MISSING)
    assert set(f.MISSING + f.REPRO) <= set(f.e8.jobs())


def test_task_key():
    f = load_fill()
    job = ("fireline", 20, 97, 0.1)
    a = f.task_key("task_chain", (job, [[1, 2], [3]], 12.5, 7, (0,)))
    assert a == f.task_key("task_chain", (job, [list(x) for x in ([1, 2], [3])], 25 / 2, 7, (0,)))   # 只看取值
    assert a != f.task_key("task_chain", (job, [[1, 2], [3]], 12.5, 7, ("warm", 1)))
    assert a != f.task_key("task_chain", (job, [[1, 2], [3]], 12.500000000001, 7, (0,)))


def test_stage1_tasks_match_run_instance():
    f = load_fill()
    e8 = f.e8
    for job in TINY:
        rec, pending = f.replay(job, {})
        assert rec is None
        assert [t["fn"] for t in pending][:2] == ["task_p2", "task_replica"]
        inst, _, cfg, _, budget, tag = e8.setup(job)
        offs = e8.feasible_offsets(inst, job[0], budget, cfg, random.Random(e8.seed_of("E8cold", *tag)), e8.CHAINS - 1)
        assert [(t["fn"], t["args"][1:]) for t in pending[2:]] == [("task_cold_init", (k, o))
                                                                     for k, o in enumerate(offs, start=1)]


def test_split_equals_in_process():
    f = load_fill()
    for job in TINY:
        rec, _, _ = run_split(f, job)
        assert f.compare(rec, f.e8.run_instance(job, None)) == []


def test_plan_merge_and_skip(tmp_path):
    f = load_fill()
    job = TINY[0]
    plan1 = f.make_plan1([job])
    assert all(n.startswith(f.inst_name(job) + ".s1.") for n in plan1["tasks"])
    _, results, info = run_split(f, job)
    s1_keys = {t["key"] for t in plan1["tasks"].values()}
    plan2, skipped = f.make_plan2(plan1, {k: v for k, v in results.items() if k in s1_keys})
    assert not skipped and len(plan2["tasks"]) == f.e8.CHAINS and plan2["jobs"] == [job]
    assert f.make_plan2(plan1, results)[0]["tasks"] == {}               # 结果已齐全时不再安排任务
    lines, ok = f.merge(plan1, results, info, tmp_path, None)
    assert ok, lines
    rec = json.loads((tmp_path / "records" / f"{f.inst_name(job)}.json").read_text(encoding="utf-8"))
    assert rec["split"]["stage1_secs"] and len(rec["split"]["stage2_secs"]) == f.e8.CHAINS
    assert f.compare(rec, f.e8.run_instance(job, None)) == []
    p2_key = next(t["key"] for t in plan1["tasks"].values() if t["fn"] == "task_p2")
    partial = {k: v for k, v in results.items() if k in s1_keys and k != p2_key}
    plan2b, skipped_b = f.make_plan2(plan1, partial)                  # 第一阶段缺结果的实例跳过
    assert plan2b["jobs"] == [] and len(skipped_b) == 1


def test_compare_ignores_timing_only():
    f = load_fill()
    rec = f.e8.run_instance(TINY[1], None)
    other = pickle.loads(pickle.dumps(rec))
    other["job_secs"] += 1.0
    other["p2"]["secs"] += 1.0
    other["p2"]["replica_secs"] += 1.0
    other["ils"]["secs"] += 1.0
    other["chains"][0]["secs"] += 1.0
    other["split"] = {"note": "补跑"}
    assert f.compare(rec, other) == []
    other["ils"]["obj"] = rec["ils"]["obj"] * (1 + 1e-15)
    assert f.compare(rec, other)
