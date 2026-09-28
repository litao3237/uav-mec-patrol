"""离线核验六规模五算法完整矩阵，导出场景等权指标及共同有效样本比较。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

import numpy as np

from aggregate_innovation_mechanism import assert_audit_equivalent
from run_multiscale_metrics import (
    DETERMINISTIC, METHODS, PROTOCOL, execution_schedule, expected_keys, phase_matrix,
)
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)

CORE_METRICS = {
    "stage1_qualified_rate", "both_stages_qualified_rate", "stage1_energy_j", "stage2_energy_j",
    "normalized_mec_cpu", "mean_delay_s", "p95_delay_s", "min_deadline_slack_s", "offload_ratio",
    "total_distance_m", "contacts", "cpu_stage2_minus_stage1", "energy_stage2_minus_stage1_j",
    "initialization_s", "search_s", "resource_recompute_s", "independent_audit_s",
    "total_to_resources_s", "total_with_audit_s",
}


def require(condition: bool, message: str) -> None:
    """验收失败立即中止，禁止把残缺矩阵发布为完整结果。"""
    if not condition:
        raise ValueError(message)


def scenario_summary(observations: list[dict]) -> dict:
    """先平均场景内的算法重复，再场景等权；区间仅作描述，不承诺检验功效。"""
    groups = defaultdict(list)
    for row in observations:
        require(math.isfinite(row["value"]), "汇总值必须有限；缺失不能替换为零")
        groups[row["scenario_seed"]].append(row["value"])
    scenes = [{"scenario_seed": s, "observations": len(v), "mean": mean(v)}
              for s, v in sorted(groups.items())]
    values = np.array([s["mean"] for s in scenes])
    interval = None
    if len(values) >= 2:
        rng = np.random.default_rng(PROTOCOL["bootstrap_seed"])
        samples = rng.choice(values, size=(PROTOCOL["bootstrap_replicates"], len(values)), replace=True)
        interval = np.quantile(samples.mean(axis=1), [.025, .975]).tolist()
    return {"valid_observations": len(observations), "independent_scenarios": len(scenes),
            "scenario_equal_mean": float(values.mean()) if len(values) else None,
            "run_equal_mean": mean(o["value"] for o in observations) if observations else None,
            "descriptive_scenario_bootstrap_95": interval, "per_scenario": scenes}


def row_metrics(row: dict) -> dict:
    """能耗与QoS使用各自的合格集合；CPU是分配量/容量之和，不称实测利用率。"""
    first, second = row["stage1"], row["stage2"]
    result = {"stage1_qualified_rate": float(first["qualified"]),
              "both_stages_qualified_rate": float(first["qualified"] and second["qualified"]),
              **row["timing"]}
    if first["qualified"]:
        result["stage1_energy_j"] = first["audit"]["saved"]["metrics"]["energy_j"]
    if first["qualified"] and second["qualified"]:
        saved = second["audit"]["saved"]["metrics"]
        rebuilt = second["audit"]["reconstructed"]["metrics"]
        result.update({"stage2_energy_j": saved["energy_j"],
                       "normalized_mec_cpu": saved["normalized_mec_cpu"],
                       "mean_delay_s": rebuilt["mean_delay_s"],
                       "p95_delay_s": rebuilt["p95_delay_s"],
                       "min_deadline_slack_s": rebuilt["min_deadline_slack_s"],
                       "offload_ratio": rebuilt["offload_ratio"],
                       "total_distance_m": rebuilt["total_distance_m"],
                       "contacts": rebuilt["contacts"],
                       "cpu_stage2_minus_stage1": saved["normalized_mec_cpu"]
                       - first["audit"]["saved"]["metrics"]["normalized_mec_cpu"],
                       "energy_stage2_minus_stage1_j": saved["energy_j"]
                       - first["audit"]["saved"]["metrics"]["energy_j"]})
        result.update({f"stage2_component_{k}_j": v for k, v in saved["energy_components_j"].items()})
    return result


def verify_archive(root: Path, phase: str) -> tuple[list[dict], list[dict], str]:
    """重新恢复实例和两套时序，核对状态、哈希、去重及完整矩阵。"""
    expected = expected_keys(phase)
    seen, commits, configs, environments = set(), set(), set(), set()
    rows, sources = [], []
    for path in sorted(root.glob("metrics_K*_S*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        require(data["phase"] == phase and data["complete"] is True, f"阶段或完整性错误：{path}")
        require(data["protocol_sha256"] == content_hash(PROTOCOL) == content_hash(data["protocol"]),
                f"协议不一致：{path}")
        instance = restore_instance(data["instance"])
        initial = restore_solution(data["initial_solution"])
        require(content_hash(instance) == data["instance_sha256"], f"实例哈希不一致：{path}")
        require(content_hash(initial) == data["initial_sha256"], f"初解哈希不一致：{path}")
        tasks, scenario = data["tasks"], data["scenario_seed"]
        seeds = phase_matrix(phase)[2]
        schedule = [list(g) for g in execution_schedule(tasks, scenario, seeds)]
        require(data["execution_schedule"] == schedule and data["algorithm_seeds"] == seeds,
                f"运行顺序或算法种子不一致：{path}")
        commits.add(data["provenance"]["git_commit"])
        configs.add((data["config_file_sha256"], content_hash(data["config"])))
        environments.add(content_hash({k: data["provenance"][k] for k in ("python", "dependencies", "threads")}))
        sources.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for row in data["rows"]:
            key = (row["tasks"], row["scenario_seed"], row["algorithm_seed"], row["method"])
            require(key in expected and key not in seen, f"重复或额外记录：{key}")
            seen.add(key)
            require(key[:2] == (tasks, scenario), f"场景归属不一致：{key}")
            require(row["initial_sha256"] == data["initial_sha256"], f"初解不一致：{key}")
            group = "B/ESI" if row["method"] in METHODS[-2:] else row["method"]
            require(schedule[row["group_order_index"]] == [group, row["algorithm_seed"]],
                    f"运行顺序不一致：{key}")
            solution = restore_solution(row["solution"])
            require(content_hash(solution) == row["solution_sha256"], f"方案哈希不一致：{key}")
            for number in (1, 2):
                stage = row[f"stage{number}"]
                resource = row["resources"]
                original = resource["stage1_values"] if number == 1 else resource["diagnostics"].get("stage2_raw_values")
                status = resource["diagnostics"].get(f"stage{number}_status",
                                                     resource["status"] if number == 1 else "not_run")
                require(stage["status"] == status and stage["available"] == bool(original),
                        f"阶段快照与原始求解记录不符：{key}")
                if not stage["available"]:
                    require(not stage["qualified"] and stage["values"] is None, f"阶段缺失但标记合格：{key}")
                    continue
                require(content_hash(stage["values"]) == content_hash(original), f"阶段变量被替换：{key}")
                limit = None if number == 1 else (row["resources"]["energy_stage1_j"]
                        + row["resources"]["diagnostics"]["energy_tolerance_j"])
                audit = audit_both_timelines(instance, solution, stage["values"], energy_limit_j=limit)
                assert_audit_equivalent(audit, stage["audit"], str(key))
                qualified = stage["status"] == "optimal" and all(a["passed"] for a in audit.values())
                require(qualified == stage["qualified"], f"阶段有效性被修改：{key}")
            require(all(math.isfinite(v) and v >= 0 for v in row["timing"].values()), f"计时非法：{key}")
            timing = row["timing"]
            require(math.isclose(timing["total_to_resources_s"], sum(timing[t] for t in
                                 ("initialization_s", "search_s", "resource_recompute_s")), abs_tol=1e-9),
                    f"计时分项与总量不一致：{key}")
            require(math.isclose(timing["total_with_audit_s"], timing["total_to_resources_s"]
                                 + timing["independent_audit_s"], abs_tol=1e-9), f"核验总时间不一致：{key}")
            row["metrics"] = row_metrics(row)
            rows.append(row)
    require(seen == expected, f"矩阵不完整：missing={sorted(expected-seen, key=str)}")
    require(len(commits) == len(configs) == len(environments) == 1, "代码、配置或依赖/线程混用")
    by_key = {(r["tasks"], r["scenario_seed"], r["algorithm_seed"], r["method"]): r for r in rows}
    for key, row in by_key.items():
        if key[-1] == "ESI-ALNS":
            base = by_key[(*key[:3], "B-ALNS")]
            require(row["diagnostics"]["exploration_sha256"] == base["solution_sha256"], f"共享探索不一致：{key}")
        if key[-1] == "RGA-MR":
            require(row["diagnostics"]["ga_evaluations"] > 0, f"GA没有真实评价：{key}")
    return rows, sources, next(iter(commits))


def summarize(rows: list[dict], phase: str) -> dict:
    """同时发布条件均值、全方法共同子集和配对差，防止不同有效集合产生虚假排名。"""
    counts, marginal, common, paired = [], [], [], []
    tasks, scenarios, seeds = phase_matrix(phase)
    # 即使某个阶段全失败也保留指标及空值，不能让缺失指标从报告中消失。
    metrics = sorted(CORE_METRICS | {metric for row in rows for metric in row["metrics"]})
    lookup = {(r["tasks"], r["scenario_seed"], r["algorithm_seed"], r["method"]): r for r in rows}
    for k in tasks:
        for method in METHODS:
            group = [r for r in rows if r["tasks"] == k and r["method"] == method]
            counts.append({"tasks": k, "method": method, "observed": len(group),
                           "stage1_qualified": sum(r["stage1"]["qualified"] for r in group),
                           "stage2_qualified": sum(r["stage2"]["qualified"] for r in group),
                           "both_stages_qualified": sum(r["stage1"]["qualified"] and r["stage2"]["qualified"] for r in group)})
            for metric in metrics:
                values = [{"scenario_seed": r["scenario_seed"], "value": r["metrics"][metric]}
                          for r in group if metric in r["metrics"]]
                marginal.append({"tasks": k, "method": method, "metric": metric,
                                 "expected_observations": len(group), **scenario_summary(values)})
        for metric in metrics:
            matched = {m: [] for m in METHODS}
            differences = {m: [] for m in METHODS[:-1]}
            for scenario in scenarios:
                for seed in seeds:
                    block = {m: lookup[k, scenario, None if m in DETERMINISTIC else seed, m] for m in METHODS}
                    if all(metric in r["metrics"] for r in block.values()):
                        for method, row in block.items():
                            matched[method].append({"scenario_seed": scenario, "value": row["metrics"][metric]})
                    esi = block["ESI-ALNS"]["metrics"].get(metric)
                    for method in METHODS[:-1]:
                        baseline = block[method]["metrics"].get(metric)
                        if esi is not None and baseline is not None:
                            differences[method].append({"scenario_seed": scenario, "value": esi - baseline})
            for method, values in matched.items():
                common.append({"tasks": k, "method": method, "metric": metric,
                               "subset": "all_five_methods_common_valid_seed_blocks", **scenario_summary(values)})
            for method, values in differences.items():
                paired.append({"tasks": k, "baseline": method, "metric": metric,
                               "direction": "ESI-ALNS minus baseline", **scenario_summary(values)})
    return {"counts": counts, "method_conditional_summaries": marginal,
            "all_method_common_summaries": common, "paired_esi_differences": paired,
            "interpretation": "各方法条件均值不直接等于总体排名；共同子集可能很小或为空。确定性基线在配对块复用，但独立样本始终是场景。P95先在单次运行任务内计算，再场景等权。"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=["pilot", "formal"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, sources, commit = verify_archive(args.input_dir, args.phase)
    report = {"complete": True, "integrity_gate_passed": True, "phase": args.phase,
              "protocol": PROTOCOL, "protocol_sha256": content_hash(PROTOCOL), "code_commit": commit,
              "expected_method_records": len(expected_keys(args.phase)), "observed_method_records": len(rows),
              "sources": sources, **summarize(rows, args.phase)}
    write_json(args.output, report)
    # 提供逐记录扁平源数据，绘图不再从Word或汇总柱高反推数值。
    columns = ["tasks", "scenario_seed", "algorithm_seed", "method"]
    columns += sorted(CORE_METRICS | {k for row in rows for k in row["metrics"]})
    with args.output.with_suffix(".csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({**{k: row[k] for k in columns[:4]}, **row["metrics"]} for row in rows)
    print(json.dumps({"phase": args.phase, "records": len(rows), "integrity_gate_passed": True,
                      "counts": report["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
