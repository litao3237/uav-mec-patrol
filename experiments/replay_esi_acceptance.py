"""从冻结 B-ALNS 检查点重放修正后的 ESI 与消融，不改写原搜索记录。"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

from experiment_common import provenance, stage_snapshot
from run_multiscale_ablation import PROFILES, paired_summaries, profile_problem_config
from uav_mec.algorithms import ProxyObjectiveEvaluator, Stage1CVXObjectiveOracle, UavMecALNSConfig
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.problem_operators import contact_mode_intensification
from uav_mec.analysis.constraint_audit import AuditTolerance, audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash, restore_instance, restore_solution, write_json
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.cvx_solver import solve_stage2_realization
from uav_mec.optimization.resource.result import ResourceSolveResult


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = {
    "id": "esi_acceptance_repair_v1", "source_run": "36382512068",
    "source_commit": "d83a282041eee5d94d8b77c94f0c6c764c58f19a",
    "tasks": [30, 40, 50, 60, 70, 80], "scenarios": list(range(45, 53)),
    "algorithm_seeds": [100, 101, 102], "elite_rounds": 2,
    "ablation_tasks": [30, 50, 70, 80], "ablation_scenarios": [45, 46, 47],
    "acceptance": "optimal, complete saved/reconstructed residuals, consistent objective",
    "audit_tolerance": asdict(AuditTolerance()),
    "baseline": "原运行B-ALNS结构及其搜索缓存连续变量；未合格基线跳过ESI",
    "retries": "沿用原Stage-1求解器流程，不新增结果依赖重试，不放宽容差",
    "scope": "重放后强化，原探索轨迹、实例、种子和消融操作定义保持不变",
    "timing": "仅报告本机重放分项，不与原云端探索时间相加",
}


def code_manifest() -> dict:
    """保存实际运行文件摘要，工作区未提交时也不冒称只由 HEAD 决定。"""
    paths = sorted((ROOT / "src").rglob("*.py"))
    paths += [Path(__file__), ROOT / "experiments/run_multiscale_ablation.py",
              ROOT / "experiments/experiment_common.py"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def restore_resource(data: dict) -> ResourceSolveResult:
    """归档将非有限数存为 null，恢复时保持失败能耗为无穷而不是零。"""
    restored = deepcopy(data)
    for field in ("energy_stage1_j", "energy_final_j"):
        if restored[field] is None:
            restored[field] = float("inf")
    return ResourceSolveResult(**restored)


def stage2_snapshot(instance, solution, result):
    """以已验收的缓存能耗为锚点重算 Stage-2，不重算并替换 Stage-1。"""
    if not stage1_is_qualified(result):
        return {"status": "skipped_unqualified_stage1", "qualified": False,
                "available": False, "values": None, "audit": None}, 0.0, None
    started = perf_counter()
    tolerance = result.diagnostics["energy_tolerance_j"]
    outcome = solve_stage2_realization(instance, solution, build_event_info(instance, solution),
                                      energy_star_j=result.energy_stage1_j,
                                      energy_tolerance_j=tolerance)
    values = outcome["raw_values"]
    audit = (audit_both_timelines(instance, solution, values,
                                 energy_limit_j=result.energy_stage1_j + tolerance) if values else None)
    snapshot = {"status": outcome["status"], "qualified": bool(outcome["accepted"] and audit
                and all(a["passed"] for a in audit.values())),
                "available": bool(values), "values": values, "audit": audit}
    return snapshot, perf_counter() - started, outcome


def replay_profile(instance, source, config, profile, *, include_stage2):
    """每个分支独立缓存，同一起点、同一规则，记录全部拒绝和最终快照。"""
    solution = restore_solution(source["solution"])
    before = content_hash(solution)
    raw = restore_resource(source["diagnostics"]["search_stage1_result"])
    oracle = Stage1CVXObjectiveOracle()
    started = perf_counter()
    base = oracle.prime(instance, solution, raw)
    seed_audit_s = perf_counter() - started
    started = perf_counter()
    state = UavMecState(instance, deepcopy(solution), ProxyObjectiveEvaluator())
    final, stats = contact_mode_intensification(
        state, config=profile_problem_config(config.problem, profile),
        objective=oracle, max_rounds=PROTOCOL["elite_rounds"],
    )
    result = oracle.solve(instance, final.solution)
    elite_s = perf_counter() - started
    if content_hash(solution) != before:
        raise RuntimeError("重放污染了冻结基线")
    if stage1_is_qualified(base) and not stage1_is_qualified(result):
        raise RuntimeError("不合格输出覆盖合格精英，停止发布结果")
    if stage1_is_qualified(base) and result.energy_stage1_j > base.energy_stage1_j + 1e-6:
        raise RuntimeError("合格精英能耗出现回升")
    first = stage_snapshot(instance, final.solution, result, stage=1)
    if first["qualified"] != stage1_is_qualified(result):
        raise RuntimeError("内部验收与独立验收不一致")
    second, stage2_s, outcome = (stage2_snapshot(instance, final.solution, result)
                                  if include_stage2 else (None, None, None))
    valid = stage1_is_qualified(base) and stage1_is_qualified(result)
    return {
        "tasks": source["tasks"], "scenario_seed": source["scenario_seed"],
        "algorithm_seed": source["algorithm_seed"], "profile": profile,
        "base_solution_sha256": before, "base_stage1_status": base.diagnostics["stage1_status"],
        "base_stage1_qualified": stage1_is_qualified(base),
        "base_acceptance_reason": base.diagnostics["stage1_acceptance_reason"],
        "base_energy_j": base.energy_stage1_j if stage1_is_qualified(base) else None,
        "final_energy_j": result.energy_stage1_j if stage1_is_qualified(result) else None,
        "final_stage1_status": result.diagnostics["stage1_status"], "strict_pair": valid,
        "gain_vs_base_pct": 100 * (base.energy_stage1_j - result.energy_stage1_j)
                              / max(1.0, abs(base.energy_stage1_j)) if valid else None,
        "solution": final.solution, "solution_sha256": content_hash(final.solution),
        "stage1": first, "stage2": second, "resources": result,
        "stage2_outcome": outcome, "elite_stats": stats, "oracle_records": oracle.solve_records,
        "elite_cvx_calls": oracle.calls, "elite_cvx_cache_hits": oracle.cache_hits,
        "elite_runtime_s": elite_s, "seed_audit_s": seed_audit_s,
        "audit_runtime_s": oracle.audit_runtime_s, "stage2_replay_s": stage2_s,
        "rejections": dict(Counter(r["rejection_reason"] for r in oracle.solve_records if not r["qualified"])),
    }


def run_block(source_path: Path, output: Path, *, full_only=False):
    """场景内顺序重放，场景间可以并行；原始和新结果保存在不同目录。"""
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source["provenance"]["git_commit"] != PROTOCOL["source_commit"] or not source["complete"]:
        raise ValueError(f"源归档版本或完整性不符：{source_path}")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest = code_manifest()
    if output.exists():
        old = json.loads(output.read_text(encoding="utf-8"))
        if old["complete"] and old["source_sha256"] == digest and old["code_manifest"] == manifest:
            logging.info("已完成且来源一致，跳过%s", output.name)
            return
        raise FileExistsError(f"存在不同版本或未完成文件，拒绝覆盖：{output}")
    instance = restore_instance(source["instance"])
    if content_hash(instance) != source["instance_sha256"]:
        raise ValueError("实例快照摘要不符")
    k, s = source["tasks"], source["scenario_seed"]
    ablate = not full_only and k in PROTOCOL["ablation_tasks"] and s in PROTOCOL["ablation_scenarios"]
    payload = {"complete": False, "protocol": PROTOCOL, "protocol_sha256": content_hash(PROTOCOL),
               "provenance": provenance(), "code_manifest": manifest, "source_sha256": digest,
               "tasks": k, "scenario_seed": s, "instance_sha256": source["instance_sha256"],
               "ablation_included": ablate, "config": asdict(UavMecALNSConfig()), "rows": []}
    write_json(output, payload)
    try:
        for seed in PROTOCOL["algorithm_seeds"]:
            baseline = next(r for r in source["rows"] if r["method"] == "B-ALNS" and r["algorithm_seed"] == seed)
            config = UavMecALNSConfig(iterations=100, seed=seed, enable_problem_operators=False)
            for profile in (PROFILES if ablate else ("full",)):
                row = replay_profile(instance, baseline, config, profile, include_stage2=profile == "full")
                payload["rows"].append(row)
                write_json(output, payload)
                logging.info("K%s S%s A%s %s：Stage1=%s 能耗=%s 接受=%s 拒绝=%s 耗时=%.2fs",
                             k, s, seed, profile, row["stage1"]["qualified"], row["final_energy_j"],
                             row["elite_stats"]["improvements"], row["rejections"], row["elite_runtime_s"])
    except Exception as exc:
        payload["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(output, payload)
        logging.exception("重放中断K%s S%s，保留已有记录", k, s)
        raise
    if ablate:
        payload["paired"] = paired_summaries(payload["rows"])
    payload["complete"] = True
    write_json(output, payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_block(args.source, args.output, full_only=args.full_only)


if __name__ == "__main__":
    main()
