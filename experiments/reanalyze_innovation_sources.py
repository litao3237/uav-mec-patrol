"""重分析既有等预算QoS、ESI操作成本及v7配对边际价值，不运行优化器。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

from aggregate_innovation_mechanism import scenario_summary
from uav_mec.analysis.experiment_snapshot import write_json


def read_source(root: Path, key: str) -> tuple[dict, dict]:
    """只接受已通过冻结哈希核对的单个JSON结果，不混入来源清单。"""
    manifest = json.loads((root / key / "provenance.json").read_text(encoding="utf-8"))
    records = [r for r in manifest["files"] if r["file"].endswith(".json")]
    assert len(records) == 1
    path = root / key / records[0]["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == records[0]["sha256"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["complete"] is True
    return data, manifest


def unique_matrix(rows: list[dict], names: tuple[str, ...], expected: set[tuple]) -> None:
    keys = [tuple(r[k] for k in names) for r in rows]
    assert len(keys) == len(set(keys)) and set(keys) == expected, "来源矩阵缺失、重复或出现额外样本"


def valid_metrics(method: dict) -> bool:
    metrics = method.get("paper_metrics")
    return bool(metrics and metrics.get("stage1_status") == "optimal" and metrics.get("stage2_status") == "optimal")


def matched_analysis(data: dict) -> dict:
    """方法条件子集与共同Stage-2配对子集分开，确定性方法不重复扩充场景数。"""
    rows = data["rows"]
    unique_matrix(rows, ("K", "budget_factor", "scenario_seed", "algorithm_seed"),
                  {(k, f, s, a) for k in (50, 80) for f in (1, 2) for s in range(45, 53) for a in (100, 101, 102)})
    coverage, paired, decomposition = [], [], []
    for k in (50, 80):
        for factor in (1, 2):
            selected = [r for r in rows if r["K"] == k and r["budget_factor"] == factor]
            methods = sorted({name for r in selected for name in r["methods"]})
            for name in methods:
                records = [r for r in selected if name in r["methods"]]
                if name in ("gr_mr", "ftr_nm"):
                    by_scene = {}
                    for r in records:
                        previous = by_scene.get(r["scenario_seed"])
                        if previous:
                            old, new = previous["methods"][name], r["methods"][name]
                            assert old["stage1_status"] == new["stage1_status"]
                            if old["energy_j"] is not None and new["energy_j"] is not None:
                                assert math.isclose(old["energy_j"], new["energy_j"], rel_tol=1e-10)
                        by_scene[r["scenario_seed"]] = r
                    records = list(by_scene.values())
                valid = [r for r in records if valid_metrics(r["methods"][name])]
                coverage.append({"K": k, "budget_factor": factor, "method": name,
                                 "observed": len(records), "independent_scenarios": len({r["scenario_seed"] for r in records}),
                                 "stage1_optimal": sum(r["methods"][name]["stage1_status"] == "optimal" for r in records),
                                 "stage2_metrics_valid": len(valid),
                                 "valid_scenarios": len({r["scenario_seed"] for r in valid}),
                                 "mean_search_runtime_s": mean(r["methods"][name]["search_runtime_s"] for r in records)})
                for r in valid:
                    p = r["methods"][name]["paper_metrics"]
                    summed = sum(p[field] for field in ("fixed_energy_j", "communication_energy_j", "local_compute_energy_j"))
                    decomposition.append({"K": k, "budget_factor": factor, "scenario_seed": r["scenario_seed"],
                                          "algorithm_seed": r["algorithm_seed"], "method": name,
                                          "reconstructed_components_sum_j": summed,
                                          "returned_energy_final_j": p["energy_final_j"],
                                          "difference_j": summed - p["energy_final_j"],
                                          "relative_difference": (summed - p["energy_final_j"]) / p["energy_final_j"]})
            common = [r for r in selected if all(valid_metrics(r["methods"][name]) for name in ("b_alns", "esi_alns"))]
            if factor == 1:
                assert (len(common), len({r["scenario_seed"] for r in common})) == {50: (18, 8), 80: (16, 7)}[k]
            for metric in ("avg_delay_s", "min_deadline_slack_s", "normalized_mec_cpu", "fixed_energy_j",
                           "communication_energy_j", "local_compute_energy_j", "search_runtime_s"):
                values = []
                for r in common:
                    def extract(name):
                        method = r["methods"][name]
                        if metric == "search_runtime_s":
                            return method[metric]
                        if metric == "normalized_mec_cpu":
                            return sum(method["paper_metrics"]["cpu_utilization_by_mec"].values())
                        return method["paper_metrics"][metric]
                    values.append({"scenario_seed": r["scenario_seed"], "algorithm_seed": r["algorithm_seed"],
                                   "difference": extract("esi_alns") - extract("b_alns")})
                paired.append({"K": k, "budget_factor": factor, "metric": metric, "direction": "ESI minus B-ALNS",
                               "subset": "common valid Stage-2 metrics", **scenario_summary(values)})
    return {"unique_blocks": len(rows), "coverage": coverage, "paired_stage2": paired,
            "component_consistency": decomposition,
            "note": "分项总和是重建能耗，与返回Stage-2上图变量能耗可有松弛差异；不能作为Stage-1目标的精确拆分。"}


def v7_analysis(data: dict, *, development: bool) -> dict:
    """Legacy与Energy-Guided分开报告，按共同检查点子集计算边际效益。"""
    rows = data["rows"]
    scenarios = list(range(85, 93) if development else range(101, 109))
    unique_matrix(rows, ("tasks", "scenario_seed", "algorithm_seed"),
                  {(k, s, a) for k in (50, 80) for s in scenarios for a in (100, 101, 102)})
    summaries, comparisons, invalid = [], [], []
    for k in (50, 80):
        all_rows = [r for r in rows if r["tasks"] == k]
        strict_rows = [r for r in all_rows if r["checkpoint_strict"]]
        for r in all_rows:
            if not r["checkpoint_strict"]:
                invalid.append({key: r[key] for key in ("tasks", "scenario_seed", "algorithm_seed", "checkpoint_stage1_status")})
                assert not r["arms"]
                continue
            assert {a["arm"] for a in r["arms"]} == {"continued_b_alns", "legacy_esi", "energy_guided_esi"}
            for arm in r["arms"]:
                if arm["strict"]:
                    delta = r["checkpoint_energy_j"] - arm["energy_j"]
                    assert math.isclose(delta, arm["delta_energy_j"], abs_tol=1e-6)
                    assert math.isclose(delta / arm["branch_runtime_s"], arm["gain_j_per_s"], abs_tol=1e-6)
        for name in ("continued_b_alns", "legacy_esi", "energy_guided_esi"):
            selected = [(r, next(a for a in r["arms"] if a["arm"] == name)) for r in strict_rows]
            for metric in ("delta_energy_j", "gain_j_per_s", "gain_j_per_cvx", "branch_runtime_s", "exact_cvx_calls"):
                values = [{"scenario_seed": r["scenario_seed"], "difference": a[metric]}
                          for r, a in selected if a["strict"] and a.get(metric) is not None]
                summaries.append({"K": k, "arm": name, "metric": metric,
                                  "strict_checkpoints": len(strict_rows), "expected_checkpoints": len(all_rows),
                                  **scenario_summary(values)})
        for name in ("legacy_esi", "energy_guided_esi"):
            for metric in ("delta_energy_j", "gain_j_per_s"):
                values = []
                for r in strict_rows:
                    arms = {a["arm"]: a for a in r["arms"]}
                    if all(arms[a]["strict"] for a in ("continued_b_alns", name)):
                        values.append({"scenario_seed": r["scenario_seed"],
                                       "difference": arms[name][metric] - arms["continued_b_alns"][metric]})
                result = scenario_summary(values)
                scene_values = [v["mean_difference"] for v in result["per_scenario"]]
                result["scenario_better_equal_worse"] = [sum(v > 1e-6 for v in scene_values),
                                                         sum(abs(v) <= 1e-6 for v in scene_values),
                                                         sum(v < -1e-6 for v in scene_values)]
                comparisons.append({"K": k, "arm": name, "metric": metric, **result})
    return {"blocks": len(rows), "scenario_seeds": scenarios, "arms": summaries,
            "paired_vs_continued_b_alns": comparisons, "missing_strict_checkpoints": invalid,
            "note": "同检查点终点边际收益；checkpoint与末端测量成本不含在branch_runtime中。缺少CVX调用时J/CVX缺失，不补零。"}


def dense_analysis(path: Path) -> dict:
    """只把记录过的已评价候选作分母，拒绝把它解释成全部生成候选。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"]
    seen = [(r["K"], r["scenario_seed"], r["algorithm_seed"]) for r in rows]
    assert len(seen) == len(set(seen)) == 54
    families, by_k = defaultdict(Counter), []
    for r in rows:
        for m in r["elite_stats"].get("evaluated_moves", []):
            family = m["move"].split("::")[0]
            families[r["K"], family]["evaluated"] += 1
            families[r["K"], family]["finite_objective"] += m.get("objective") is not None
        for m in r["elite_stats"].get("accepted_moves", []):
            families[r["K"], m["move"].split("::")[0]]["accepted"] += 1
    for k in sorted({r["K"] for r in rows}):
        selected = [r for r in rows if r["K"] == k]
        by_k.append({"K": k, "runs": len(selected), "scenarios": len({r["scenario_seed"] for r in selected}),
                     "mean_elite_runtime_s": mean(r["elite_runtime_s"] for r in selected),
                     "mean_oracle_calls": mean(r["elite_cvx_calls"] for r in selected),
                     "mean_cache_hits": mean(r["elite_cvx_cache_hits"] for r in selected)})
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "runs": len(rows),
            "per_scale": by_k,
            "operations": [{"K": k, "family": name, **dict(counts)} for (k, name), counts in sorted(families.items())]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--dense", type=Path, default=Path("paper_figures/data/raw/dense.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources, data = {}, {}
    for key in ("matched", "v7_dev", "v7_unseen"):
        data[key], sources[key] = read_source(args.source_dir, key)
    result = {"complete": True, "sources": sources, "matched": matched_analysis(data["matched"]),
              "v7_dev": v7_analysis(data["v7_dev"], development=True),
              "v7_unseen": v7_analysis(data["v7_unseen"], development=False),
              "dense": dense_analysis(args.dense),
              "statistical_scope": "场景等权均值和描述性percentile bootstrap；非独立新实验，无全约束认证，无多重比较显著性主张。"}
    write_json(args.output, result)
    print(json.dumps({"matched_blocks": result["matched"]["unique_blocks"],
                      "v7_dev_blocks": result["v7_dev"]["blocks"], "v7_unseen_blocks": result["v7_unseen"]["blocks"],
                      "dense_runs": result["dense"]["runs"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
