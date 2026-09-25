"""从已验收快照导出逐运行表和解释指标，不重新优化或更改有效样本规则。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from aggregate_innovation_mechanism import aggregate, scenario_summary
from uav_mec.analysis.experiment_snapshot import write_json


METRICS = (
    "energy_j", "normalized_mec_cpu", "total_distance_m", "contacts",
    "offloaded_tasks", "offload_ratio", "mean_delay_s", "p95_delay_s",
    "min_deadline_slack_s", "mean_carrying_wait_s",
)
ENERGY_COMPONENTS = ("flight_j", "collection_j", "upload_hover_j", "transmit_j", "local_compute_j")
IDENTITY = ("tasks", "scenario_seed", "algorithm_seed", "method")


def write_csv(path: Path, rows: list[dict]) -> None:
    """保留空缺单元格，禁止将未求解或不适用的指标替换为零。"""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_tables(root: Path, phase: str, output: Path) -> dict:
    """先离线复核完整矩阵，再导出原值、合格标志及共同有效子集的差值。

    保存时序可能含求解器松弛，时延比较统一取重建的最早可执行时序；CPU、
    能耗仍保留两套数值。两阶段比较必须两阶段均合格，方法间比较用共同Stage-1。
    """
    checked = aggregate(root, phase)
    rows = [row for path in sorted(root.glob("mechanism_K*_S*.json"))
            for row in json.loads(path.read_text(encoding="utf-8"))["rows"]]
    rows.sort(key=lambda row: tuple(row[key] for key in IDENTITY))
    runs, stages, differences, summaries = [], [], [], []
    for row in rows:
        identity = {key: row[key] for key in IDENTITY}
        run = {**identity, "code_commit": checked["code_commit"],
               "solution_sha256": row["solution_sha256"],
               "stage1_qualified": row["stage1"]["qualified"],
               "stage2_qualified": row["stage2"]["qualified"]}
        for key in ("nominal_budget_s", "search_runtime_s", "overrun_s",
                    "resource_recompute_runtime_s", "audit_runtime_s", "oracle_calls", "oracle_cache_hits"):
            run[key] = row[key]
        run.update({"freeze_rejections": row["outer_freeze_stats"]["rejected_by_freeze"],
                    "unique_admissible_structures": row["outer_freeze_stats"]["unique_admissible_structures"],
                    "direct_structure_calls": len(row["controlled_exploration"]["direct_structure_records"])})
        runs.append(run)
        for number in (1, 2):
            stage = row[f"stage{number}"]
            for timeline in ("saved", "reconstructed"):
                audit = stage.get("audit", {}).get(timeline, {}) if stage["available"] else {}
                values = audit.get("metrics", {})
                record = {**identity, "stage": number, "timeline": timeline,
                          "available": stage["available"], "solver_status": stage["status"],
                          "qualified": stage["qualified"], "audit_passed": audit.get("passed"),
                          "max_normalized_violation": audit.get("max_normalized_violation"),
                          "worst_constraint": audit.get("worst_constraint"),
                          **{key: values.get(key) for key in METRICS},
                          **{key: values.get("energy_components_j", {}).get(key) for key in ENERGY_COMPONENTS},
                          "carrying_wait_status": values.get("carrying_wait_status")}
                stages.append(record)

        # 同结构差值保留能耗保护上限；不把不准确或残差不合格阶段计入比较。
        if row["stage_comparison"] is not None:
            first = row["stage1"]["audit"]
            second = row["stage2"]["audit"]
            values = {
                "normalized_cpu": second["saved"]["metrics"]["normalized_mec_cpu"] - first["saved"]["metrics"]["normalized_mec_cpu"],
                "energy_j": second["saved"]["metrics"]["energy_j"] - first["saved"]["metrics"]["energy_j"],
                **{key: second["reconstructed"]["metrics"][key] - first["reconstructed"]["metrics"][key]
                   for key in ("mean_delay_s", "p95_delay_s", "min_deadline_slack_s")},
            }
            differences.extend({**identity, "comparison": "stage2_minus_stage1", "metric": key,
                                "difference": value, "energy_tolerance_j": row["stage_comparison"]["energy_tolerance_j"]}
                               for key, value in values.items())

    full = {(r["tasks"], r["scenario_seed"], r["algorithm_seed"]): r for r in rows if r["method"] == "full"}
    for row in rows:
        reference = full[row["tasks"], row["scenario_seed"], row["algorithm_seed"]]
        if row["method"] == "full" or not (row["stage1"]["qualified"] and reference["stage1"]["qualified"]):
            continue
        a = reference["stage1"]["audit"]["reconstructed"]["metrics"]
        b = row["stage1"]["audit"]["reconstructed"]["metrics"]
        for key in ("total_distance_m", "offload_ratio", "contacts", "mean_delay_s", "p95_delay_s"):
            differences.append({**{k: row[k] for k in IDENTITY}, "comparison": "full_minus_restricted",
                                "metric": key, "difference": a[key] - b[key]})

    groups = sorted({(r["tasks"], r["method"], r["comparison"], r["metric"]) for r in differences})
    for tasks, method, comparison, metric in groups:
        selected = [r for r in differences if (r["tasks"], r["method"], r["comparison"], r["metric"])
                    == (tasks, method, comparison, metric)]
        summaries.append({"tasks": tasks, "method": method, "comparison": comparison,
                          "metric": metric, **scenario_summary(selected)})
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "runs.csv", runs)
    write_csv(output / "stage_metrics.csv", stages)
    write_csv(output / "paired_explanatory_metrics.csv", differences)
    report = {"phase": phase, "code_commit": checked["code_commit"],
              "protocol_sha256": checked["protocol_sha256"], "sources": checked["sources"],
              "method_runs": len(runs), "stage_timeline_rows": len(stages),
              "scope": "解释指标；时延采用重建最早时序；主能耗百分比和CPU比较以原summary为准。未合格原值仅供审计，不纳入配对。",
              "summaries": summaries}
    write_json(output / "explanatory_summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=["pilot", "formal"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = export_tables(args.input_dir, args.phase, args.output_dir)
    print(json.dumps({key: result[key] for key in ("phase", "method_runs", "stage_timeline_rows")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
