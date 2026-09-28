"""核对冻结的六规模数据，并生成具有场景、运行和配对分母的绘图数据。"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "paper_results/multiscale_20260928"
METHODS = ("GR-MR", "FTR-NM", "RGA-MR", "B-ALNS", "ESI-ALNS")
SCALES = (30, 40, 50, 60, 70, 80)
SCENARIOS = tuple(range(45, 53))
SEEDS = (100, 101, 102)
DETERMINISTIC = set(METHODS[:2])
SUMMARY_SCOPES = {
    "conditional": "method_conditional_summaries",
    "common": "all_method_common_summaries",
    "paired": "paired_esi_differences",
}


def require(condition: bool, message: str) -> None:
    """遇到来源或统计不一致立即停止，避免继续生成貌似完整的论文图。"""
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    """使用 UTF-8 BOM 便于 Excel 读取；空值保持为空，绝不补零。"""
    require(bool(rows), f"拒绝输出空表：{path.name}")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(observations: list[dict]) -> dict:
    """场景内重复先平均，场景再等权；沿用冻结协议的描述性 bootstrap。"""
    groups = defaultdict(list)
    for row in observations:
        require(math.isfinite(row["value"]), "统计输入出现非有限值")
        groups[row["scenario_seed"]].append(row["value"])
    scenes = [{"scenario_seed": key, "observations": len(values), "mean": mean(values)}
              for key, values in sorted(groups.items())]
    values = np.array([row["mean"] for row in scenes])
    interval = None
    if len(values) >= 2:
        rng = np.random.default_rng(20260928)
        samples = rng.choice(values, size=(10000, len(values)), replace=True)
        interval = np.quantile(samples.mean(axis=1), [0.025, 0.975]).tolist()
    return {"valid_observations": len(observations), "independent_scenarios": len(scenes),
            "scenario_equal_mean": float(values.mean()) if len(values) else None,
            "run_equal_mean": mean(row["value"] for row in observations) if observations else None,
            "descriptive_scenario_bootstrap_95": interval, "per_scenario": scenes}


def compare_summary(actual: dict, expected: dict, context: str) -> None:
    """逐项核对中心值、区间和场景组成，而非只检查最终均值。"""
    for name in ("valid_observations", "independent_scenarios", "per_scenario"):
        require(actual[name] == expected[name], f"{context} 的 {name} 不一致")
    for name in ("scenario_equal_mean", "run_equal_mean", "descriptive_scenario_bootstrap_95"):
        a, b = actual[name], expected[name]
        if a is None or b is None:
            require(a is None and b is None, f"{context} 的空值口径不一致")
        else:
            require(np.allclose(a, b, rtol=1e-12, atol=1e-10), f"{context} 的 {name} 不一致")


def load_verified() -> tuple[list[dict], dict, dict]:
    """哈希、矩阵和阶段有效性先验收；保留失败记录与原 runner 的全部计时。"""
    verification = json.loads((SOURCE / "verification.json").read_text("utf-8"))
    checked = []
    for item in verification["files"]:
        path = SOURCE / item["file"]
        require(path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"],
                f"源文件哈希不一致：{item['file']}")
        checked.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": item["sha256"]})
    summary = json.loads((SOURCE / "stage2_v2_summary.json").read_text("utf-8"))
    require(summary["complete"] and summary["integrity_gate_passed"], "冻结数据没有通过完整性验收")
    with (SOURCE / "stage2_v2_metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        raw = list(csv.DictReader(stream))
    metadata = {"tasks", "scenario_seed", "algorithm_seed", "method", "solution_sha256",
                "source_record_sha256", "stage1_status", "stage2_status", "stage1_qualified",
                "stage2_qualified", "original_stage2_qualified"}
    numeric = [key for key in raw[0] if key not in metadata]
    rows, seen = [], set()
    for original in raw:
        row = dict(original)
        for key in ("tasks", "scenario_seed", "algorithm_seed"):
            row[key] = int(row[key]) if row[key] else None
        for key in ("stage1_qualified", "stage2_qualified", "original_stage2_qualified"):
            require(row[key] in ("True", "False"), f"非法布尔值：{key}")
            row[key] = row[key] == "True"
        for key in numeric:
            row[key] = float(row[key]) if row[key] else None
            require(row[key] is None or math.isfinite(row[key]), f"{key} 出现非有限值")
        key = (row["tasks"], row["scenario_seed"], row["algorithm_seed"], row["method"])
        require(key not in seen, f"重复记录：{key}")
        seen.add(key)
        first, both = row["stage1_qualified"], row["stage1_qualified"] and row["stage2_qualified"]
        require(row["stage1_qualified_rate"] == float(first)
                and row["both_stages_qualified_rate"] == float(both), f"有效率标志错误：{key}")
        require((row["stage1_energy_j"] is not None) == first
                and (row["stage2_energy_j"] is not None) == both, f"缺失值规则错误：{key}")
        # 此总和只来自同一原搜索运行，明确排除跨机器的 Stage-2 复验耗时。
        row["original_construction_search_s"] = row["original_initialization_s"] + row["original_search_s"]
        rows.append(row)
    expected = {(k, scene, seed, method) for k in SCALES for scene in SCENARIOS for method in METHODS
                for seed in ((None,) if method in DETERMINISTIC else SEEDS)}
    require(seen == expected and len(rows) == 528, "六规模五算法矩阵不完整")
    require(sum(row["stage1_qualified"] for row in rows) == 441
            and sum(row["both_stages_qualified_rate"] for row in rows) == 441,
            "阶段合格数与最终验收不一致")
    return rows, summary, {"source_files": checked, "records": len(rows), "qualified": 441,
                           "matrix_complete": True, "bootstrap_seed": 20260928, "bootstrap_replicates": 10000}


def build_tables(out: Path) -> tuple[list[dict], dict, dict]:
    """重建并核对冻结汇总，额外派生仅包含初始化与搜索的耗时口径。"""
    rows, frozen, audit = load_verified()
    lookup = {(r["tasks"], r["scenario_seed"], r["algorithm_seed"], r["method"]): r for r in rows}
    metrics = sorted({r["metric"] for r in frozen["method_conditional_summaries"]})
    derived = ["original_construction_search_s"] + [key for key in rows[0] if key.startswith("original_") and key.endswith("_s")]
    metrics = sorted(set(metrics + derived))
    entries = []
    for k in SCALES:
        for metric in metrics:
            common, paired = {m: [] for m in METHODS}, {m: [] for m in METHODS[:-1]}
            for scenario in SCENARIOS:
                for seed in SEEDS:
                    block = {m: lookup[k, scenario, None if m in DETERMINISTIC else seed, m] for m in METHODS}
                    if all(row.get(metric) is not None for row in block.values()):
                        for method, row in block.items():
                            common[method].append({"scenario_seed": scenario, "value": row[metric]})
                    esi = block["ESI-ALNS"].get(metric)
                    for method in METHODS[:-1]:
                        baseline = block[method].get(metric)
                        if esi is not None and baseline is not None:
                            paired[method].append({"scenario_seed": scenario, "value": esi - baseline})
            for method in METHODS:
                group = [r for r in rows if r["tasks"] == k and r["method"] == method]
                observations = [{"scenario_seed": r["scenario_seed"], "value": r[metric]}
                                for r in group if r.get(metric) is not None]
                entries.append({"scope": "conditional", "tasks": k, "method": method, "metric": metric,
                                "expected_observations": len(group), **summarize(observations)})
                entries.append({"scope": "common", "tasks": k, "method": method, "metric": metric,
                                "expected_observations": 24, **summarize(common[method])})
            for method in METHODS[:-1]:
                entries.append({"scope": "paired", "tasks": k, "method": method, "metric": metric,
                                "expected_observations": 24, **summarize(paired[method])})
    stats = {(r["scope"], r["tasks"], r["method"], r["metric"]): r for r in entries}
    checks = 0
    for scope, name in SUMMARY_SCOPES.items():
        for expected in frozen[name]:
            method = expected.get("method", expected.get("baseline"))
            key = (scope, expected["tasks"], method, expected["metric"])
            compare_summary(stats[key], expected, str(key))
            checks += 1
    coverage = []
    for expected in frozen["counts"]:
        group = [r for r in rows if r["tasks"] == expected["tasks"] and r["method"] == expected["method"]]
        valid = [r for r in group if r["both_stages_qualified_rate"]]
        require(len(group) == expected["observed"] and len(valid) == expected["both_stages_qualified"],
                f"合格数不一致：{expected}")
        common = stats["common", expected["tasks"], expected["method"], "stage1_energy_j"]
        coverage.append({**expected, "failed": len(group) - len(valid),
                         "valid_independent_scenarios": len({r["scenario_seed"] for r in valid}),
                         "scheduled_independent_scenarios": 8, "common_valid_blocks": common["valid_observations"],
                         "common_valid_independent_scenarios": common["independent_scenarios"]})
    flat, scenes = [], []
    for row in entries:
        interval = row["descriptive_scenario_bootstrap_95"]
        flat.append({k: v for k, v in row.items() if k not in ("per_scenario", "descriptive_scenario_bootstrap_95")}
                    | {"ci_low": interval[0] if interval else None, "ci_high": interval[1] if interval else None})
        for scene in row["per_scenario"]:
            scenes.append({k: row[k] for k in ("scope", "tasks", "method", "metric")} | scene)
    write_csv(out / "data/run_metrics.csv", rows)
    write_csv(out / "data/all_statistics.csv", flat)
    write_csv(out / "data/all_scenario_means.csv", scenes)
    write_csv(out / "data/sample_coverage.csv", coverage)
    write_csv(out / "data/failed_records.csv", [r for r in rows if not r["both_stages_qualified_rate"]])
    audit.update({"summary_entries_cross_checked": checks, "summary_match": True,
                  "common_scenes": [stats["common", k, "ESI-ALNS", "stage1_energy_j"]["independent_scenarios"] for k in SCALES],
                  "all_failed_records_retained": 87, "new_experiments_or_solver_calls": False,
                  "original_search_and_replay_times_combined": False})
    write_json(out / "qa/data_verification.json", audit)
    return rows, stats, audit
