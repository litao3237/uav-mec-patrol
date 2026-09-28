"""在冻结的六规模方案与Stage-1能耗锚点上复验Stage-2，不重新搜索或修改历史数据。"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

from aggregate_innovation_mechanism import assert_audit_equivalent
from aggregate_multiscale_metrics import require, row_metrics, summarize
from run_innovation_mechanism import provenance, stage_snapshot
from run_multiscale_metrics import expected_keys
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash, restore_instance, restore_solution, write_json
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.cvx_solver import solve_stage2_realization
from uav_mec.optimization.resource.result import ResourceSolveResult

SOURCE = {
    "run_id": 36382512068, "code_commit": "d83a282041eee5d94d8b77c94f0c6c764c58f19a",
    "artifact_name": "six-scale-formal-complete-archive",
    "archive_sha256": "c5bdd0a5593093f8bfc7769545e951099ecedc3698094a4b21020ba6e8bf101a",
    "summary_sha256": "88f58c189b9ca89049c6f24a1e6a6f514341454019a0d23c7186cdcbaae8743e",
}
PROTOCOL = {
    "id": "stage2_fixed_snapshot_repair_v2", "source": SOURCE,
    "formulation": "dimensionless_rate_epigraph_v1", "energy_unit_j": 1000.0,
    "unchanged": ["discrete_solution", "stage1_snapshot", "stage1_energy", "energy_tolerance", "audit_tolerance"],
    "acceptance": "optimal plus saved/reconstructed independent residuals",
    "clarabel_retries": [[1.0, .99], [100.0, .99], [1.0, .95], [1.0, .8], [100.0, .8]],
    "skip": "stage1_not_qualified", "scope": "固定结构资源重算，不是新的外层搜索或泛化实验",
    "timing": "单独保存Stage-2复算耗时；不把原runner搜索与新机器耗时拼成端到端速度",
}


def load_sources(root: Path) -> tuple[dict, dict[str, tuple[dict, str]]]:
    """绑定已验收原归档的摘要及逐文件哈希，拒绝替换结构或混合数据源。"""
    summary_path = root / "summary.json"
    require(hashlib.sha256(summary_path.read_bytes()).hexdigest() == SOURCE["summary_sha256"], "源汇总哈希不符")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require(summary["complete"] and summary["code_commit"] == SOURCE["code_commit"], "源归档版本不符")
    blocks = {}
    for item in summary["sources"]:
        path = root / "parts" / item["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        require(digest == item["sha256"], f"源文件哈希不符：{path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        blocks[path.name] = (data, digest)
    return summary, blocks


def replay_block(data: dict, source_digest: str, output: Path) -> None:
    """同场景顺序复验所有原合格与失败方法，避免只挑失败记录产生新选择偏差。"""
    if output.exists():
        raise FileExistsError(f"拒绝覆盖复验结果：{output}")
    instance = restore_instance(data["instance"])
    payload = {"protocol": PROTOCOL, "protocol_sha256": content_hash(PROTOCOL),
               "provenance": provenance(), "source_block_sha256": source_digest,
               "tasks": data["tasks"], "scenario_seed": data["scenario_seed"],
               "complete": False, "rows": []}
    write_json(output, payload)
    try:
        for original in data["rows"]:
            row = deepcopy(original)
            row["source_record_sha256"] = content_hash(original)
            row["source_timing"] = row.pop("timing")
            row["timing"] = {}
            row["original_stage2"] = {k: original["stage2"][k] for k in ("status", "available", "qualified")}
            resource = deepcopy(original["resources"])
            solution = restore_solution(original["solution"])
            started = perf_counter()
            if original["stage1"]["qualified"]:
                outcome = solve_stage2_realization(
                    instance, solution, build_event_info(instance, solution),
                    energy_star_j=resource["energy_stage1_j"],
                    energy_tolerance_j=resource["diagnostics"]["energy_tolerance_j"],
                )
                resource["diagnostics"].update(
                    stage2_status=outcome["status"], stage2_solver=outcome["solver"],
                    stage2_raw_values=outcome["raw_values"], stage2_accepted=outcome["accepted"],
                    stage2_attempts=outcome["attempts"], stage2_formulation=PROTOCOL["formulation"],
                    stage2_solver_errors=[f"{a['solver']}: {a.get('error', a['status'])}"
                                          for a in outcome["attempts"] if not a["accepted"]],
                )
                resource["final_values"] = outcome["raw_values"] if outcome["accepted"] else resource["stage1_values"]
                resource["energy_final_j"] = outcome["energy_j"] if outcome["accepted"] else resource["energy_stage1_j"]
                resource["status"] = outcome["status"] if outcome["accepted"] else resource["diagnostics"]["stage1_status"]
                resource["solver"] = outcome["solver"] if outcome["accepted"] else resource["diagnostics"]["stage1_solver"]
                # 用实际返回快照同步诊断，不残留旧Stage-2的时延和回程值。
                final = resource["final_values"]
                resource["diagnostics"]["avg_delay_final_s"] = sum(final["task_completion_s"][t]
                    - instance.tasks[t].release_s for t in instance.tasks) / len(instance.tasks)
                info = build_event_info(instance, solution)
                resource["diagnostics"]["return_times_final_s"] = {
                    u: info.base_return_s[u] + sum(final["tau_s"][v] for v in info.contact_order[u])
                    for u in instance.uavs}
                row["resources"] = resource
                row["stage2"] = stage_snapshot(instance, solution, ResourceSolveResult(**resource), stage=2)
                row["stage2_replay_s"] = perf_counter() - started
            else:
                # 未合格的Stage-1锚点不进入词典序第二阶段，不偷偷重算或修补第一阶段。
                row["stage2"] = {"status": "skipped_unqualified_stage1", "available": False,
                                 "qualified": False, "values": None, "audit": None,
                                 "reason": "原Stage-1未通过独立验收"}
                row["stage2_replay_s"] = None
            row["metrics"] = row_metrics(row)
            if row["stage2_replay_s"] is not None:
                row["metrics"]["stage2_replay_s"] = row["stage2_replay_s"]
            payload["rows"].append(row)
            write_json(output, payload)
            logging.info("K%s S%s A%s %s：Stage2 %s→%s", row["tasks"], row["scenario_seed"],
                         row["algorithm_seed"], row["method"], original["stage2"]["qualified"], row["stage2"]["qualified"])
    except Exception as exc:
        payload["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(output, payload)
        logging.exception("固定结构Stage-2复验失败，已保留完成记录")
        raise
    payload["complete"] = True
    write_json(output, payload)


def aggregate(source_root: Path, results: Path, output: Path) -> dict:
    """完整复验528条记录，逐项证明Stage-1、方案和能耗上限未变。"""
    source_summary, source_blocks = load_sources(source_root)
    rows, files, commits, seen = [], [], set(), set()
    transitions = Counter()
    for path in sorted(results.glob("replay_K*_S*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        original, digest = source_blocks[path.name.replace("replay_", "metrics_")]
        require(data["complete"] and data["protocol_sha256"] == content_hash(PROTOCOL)
                == content_hash(data["protocol"]), f"复验协议或完整性异常：{path}")
        require(data["source_block_sha256"] == digest, "源场景块被替换")
        instance = restore_instance(original["instance"])
        originals = {(r["method"], r["algorithm_seed"]): r for r in original["rows"]}
        commits.add(data["provenance"]["git_commit"])
        files.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for row in data["rows"]:
            key = tuple(row[k] for k in ("tasks", "scenario_seed", "algorithm_seed", "method"))
            require(key in expected_keys("formal") and key not in seen, f"重复或意外记录：{key}")
            require(key[:2] == (original["tasks"], original["scenario_seed"]), "场景归属异常")
            seen.add(key)
            old = originals[row["method"], row["algorithm_seed"]]
            require(row["source_record_sha256"] == content_hash(old), "源方法记录摘要不符")
            for field in ("stage1", "solution", "solution_sha256"):
                require(content_hash(row[field]) == content_hash(old[field]), f"禁止修改原{field}")
            for field in ("stage1_values", "stage1_duals", "energy_stage1_j"):
                require(content_hash(row["resources"][field]) == content_hash(old["resources"][field]), f"第一阶段{field}被修改")
            require(row["resources"]["diagnostics"].get("energy_tolerance_j")
                    == old["resources"]["diagnostics"].get("energy_tolerance_j"), "禁止放宽能耗容差")
            stage = row["stage2"]
            if not old["stage1"]["qualified"]:
                require(stage["status"] == "skipped_unqualified_stage1" and not stage["qualified"], "非法Stage-1锚点")
            elif stage["available"]:
                require(content_hash(stage["values"]) == content_hash(row["resources"]["diagnostics"]["stage2_raw_values"]),
                        "第二阶段快照与返回记录不一致")
                require(stage["status"] == row["resources"]["diagnostics"]["stage2_status"], "第二阶段状态不一致")
                audit = audit_both_timelines(instance, restore_solution(row["solution"]), stage["values"],
                    energy_limit_j=old["resources"]["energy_stage1_j"] + old["resources"]["diagnostics"]["energy_tolerance_j"])
                assert_audit_equivalent(audit, stage["audit"], str(key))
                require(stage["qualified"] == (stage["status"] == "optimal" and all(a["passed"] for a in audit.values())),
                        "第二阶段有效性判定被修改")
            else:
                require(stage["qualified"] is False and stage["values"] is None, "缺失快照冒充成功")
            computed = row_metrics(row)
            if row["stage2_replay_s"] is not None:
                computed["stage2_replay_s"] = row["stage2_replay_s"]
            require(content_hash(computed) == content_hash(row["metrics"]), "指标无法由快照还原")
            transitions[f"{old['stage2']['qualified']}->{stage['qualified']}"] += 1
            rows.append(row)
    require(seen == expected_keys("formal") and len(commits) == 1, "复验矩阵不完整或代码版本混用")
    report = {"complete": True, "integrity_gate_passed": True, "protocol": PROTOCOL,
              "code_commit": next(iter(commits)), "records": len(rows), "sources": files,
              "stage2_transitions": dict(transitions), "original_counts": source_summary["counts"],
              **summarize(rows, "formal")}
    write_json(output, report)
    print(json.dumps({"records": len(rows), "stage2_transitions": dict(transitions),
                      "both_stages_qualified": sum(r["both_stages_qualified"] for r in report["counts"])}, ensure_ascii=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tasks", type=int, choices=[30, 40, 50, 60, 70, 80])
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.aggregate_only:
        aggregate(args.source_root, args.output_dir, args.output_dir / "summary.json")
        return
    if args.tasks is None:
        parser.error("复验必须指定--tasks；全矩阵汇总使用--aggregate-only")
    _, blocks = load_sources(args.source_root)
    for name, (data, digest) in blocks.items():
        if data["tasks"] == args.tasks:
            replay_block(data, digest, args.output_dir / name.replace("metrics_", "replay_"))


if __name__ == "__main__":
    main()
