"""核对补充实验矩阵、离线复核快照并按场景等权汇总，失败样本不补零。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean

import numpy as np

from run_innovation_mechanism import METHODS, PROTOCOL
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.analysis.mechanism_controls import FrozenDecisions


def scenario_summary(pairs: list[dict]) -> dict:
    """先对同场景算法重复求均值，再以场景为单位重采样，不伪增独立样本数。"""
    groups = defaultdict(list)
    for p in pairs:
        groups[p["scenario_seed"]].append(p["difference"])
    per_scene = [{"scenario_seed": s, "pairs": len(v), "mean_difference": mean(v)}
                 for s, v in sorted(groups.items())]
    values = np.array([r["mean_difference"] for r in per_scene])
    interval = None
    if len(values) >= 2:
        rng = np.random.default_rng(PROTOCOL["bootstrap"]["seed"])
        samples = rng.choice(values, size=(PROTOCOL["bootstrap"]["replicates"], len(values)), replace=True)
        interval = np.quantile(samples.mean(axis=1), [.025, .975]).tolist()
    return {"pairs": len(pairs), "independent_scenarios": len(groups),
            "scenario_equal_mean": float(values.mean()) if len(values) else None,
            "run_equal_mean": mean(p["difference"] for p in pairs) if pairs else None,
            "scenario_bootstrap_percentile_95": interval, "per_scenario": per_scene}


def aggregate(root: Path, phase: str) -> dict:
    """严格核对矩阵和哈希；数值未合格仍是完整观察，执行错误则中止验收。"""
    scenarios = list(range(45, 48 if phase == "pilot" else 53))
    seeds = [100] if phase == "pilot" else [100, 101, 102]
    expected = {(k, s, a, m) for k in (50, 80) for s in scenarios for a in seeds for m in METHODS}
    seen = set()
    rows, sources, commits = [], [], set()
    for path in sorted(root.glob("mechanism_K*_S*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["phase"] == phase and data["complete"] is True, path
        assert data["protocol_sha256"] == content_hash(PROTOCOL) == content_hash(data["protocol"]), path
        instance = restore_instance(data["instance"])
        initial = restore_solution(data["initial_solution"])
        assert content_hash(instance) == data["instance_sha256"], path
        commits.add(data["provenance"]["git_commit"])
        sources.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for row in data["rows"]:
            key = (row["tasks"], row["scenario_seed"], row["algorithm_seed"], row["method"])
            assert key in expected and key not in seen, key
            assert (row["tasks"], row["scenario_seed"]) == (data["tasks"], data["scenario_seed"])
            seen.add(key)
            solution = restore_solution(row["solution"])
            assert content_hash(solution) == row["solution_sha256"], key
            assert row["initial_sha256"] == content_hash(initial), key
            guard = FrozenDecisions.from_initial(row["method"], initial)
            assert guard.allows(solution) and row["frozen_invariant_passed"], key
            assert guard.allows(restore_solution(row["exploration_solution"])), key
            assert row["method_order"][row["order_index"]] == row["method"], key
            assert sorted(row["method_order"]) == sorted(METHODS), key
            # 从归档实例及变量重新核验，拒绝仅复制执行时的passed标志。
            for number in (1, 2):
                stage = row[f"stage{number}"]
                if not stage["available"]:
                    assert stage["qualified"] is False and stage["values"] is None
                    continue
                limit = None if number == 1 else (row["resources"]["energy_stage1_j"]
                         + row["resources"]["diagnostics"]["energy_tolerance_j"])
                audit = audit_both_timelines(instance, solution, stage["values"], energy_limit_j=limit)
                assert content_hash(audit) == content_hash(stage["audit"]), key
                qualified = stage["status"] == "optimal" and all(v["passed"] for v in audit.values())
                assert qualified == stage["qualified"], key
            rows.append(row)
    assert seen == expected, f"矩阵不完整：missing={sorted(expected-seen)} extra={sorted(seen-expected)}"
    assert len(commits) == 1, f"不能混合不同代码版本：{commits}"
    comparisons, stage_comparisons, counts = [], [], []
    for k in (50, 80):
        selected = [r for r in rows if r["tasks"] == k]
        for method in METHODS:
            group = [r for r in selected if r["method"] == method]
            counts.append({"tasks": k, "method": method, "expected": len(scenarios) * len(seeds),
                           "observed": len(group), "stage1_qualified": sum(r["stage1"]["qualified"] for r in group),
                           "stage2_qualified": sum(r["stage2"]["qualified"] for r in group),
                           "mean_search_runtime_s": mean(r["search_runtime_s"] for r in group),
                           "mean_overrun_s": mean(r["overrun_s"] for r in group),
                           "mean_freeze_rejections": mean(r["outer_freeze_stats"]["rejected_by_freeze"] for r in group),
                           "no_structure_variation_runs": sum(max(r["outer_freeze_stats"]["unique_admissible_structures"],
                                                                 r["elite_freeze_stats"]["unique_admissible_structures"]) <= 1 for r in group)})
            paired = [{"scenario_seed": r["scenario_seed"], "difference": r["stage_comparison"]["cpu_occupation_change"]}
                      for r in group if r["stage_comparison"] is not None]
            stage_comparisons.append({"tasks": k, "method": method, "metric": "stage2_minus_stage1_normalized_cpu",
                                      **scenario_summary(paired)})
        full = {(r["scenario_seed"], r["algorithm_seed"]): r for r in selected if r["method"] == "full"}
        for method in METHODS[1:]:
            paired = []
            for r in selected:
                if r["method"] != method:
                    continue
                baseline = full[r["scenario_seed"], r["algorithm_seed"]]
                if not (r["stage1"]["qualified"] and baseline["stage1"]["qualified"]):
                    continue
                restricted = r["stage1"]["audit"]["saved"]["metrics"]["energy_j"]
                joint = baseline["stage1"]["audit"]["saved"]["metrics"]["energy_j"]
                paired.append({"scenario_seed": r["scenario_seed"], "algorithm_seed": r["algorithm_seed"],
                               "difference": 100 * (restricted - joint) / restricted})
            comparisons.append({"tasks": k, "reference": method, "metric": "full_energy_saving_percent",
                                **scenario_summary(paired), "paired_values": paired})
    return {"complete": True, "phase": phase, "protocol": PROTOCOL, "protocol_sha256": content_hash(PROTOCOL),
            "code_commit": next(iter(commits)), "expected_method_runs": len(expected), "observed_method_runs": len(rows),
            "sources": sources, "counts": counts, "mechanism_comparisons": comparisons,
            "resource_stage_comparisons": stage_comparisons,
            "integrity_gate_passed": True,
            "interpretation": "能耗比较仅限共同Stage-1原数值状态及独立残差均合格子集；所有失败另计。候选拒绝造成的搜索效率差异须并列解释。"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=["pilot", "formal"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = aggregate(args.input_dir, args.phase)
    write_json(args.output, report)
    print(json.dumps({k: report[k] for k in ("phase", "expected_method_runs", "observed_method_runs", "counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
