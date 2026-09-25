"""执行配对机制对照和同结构两阶段验证，完整保存失败、时序及独立残差。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import logging
import math
import os
from pathlib import Path
import platform
import subprocess
from time import perf_counter

import numpy as np

from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator, Stage1CVXObjectiveOracle, UavMecALNSConfig,
    build_greedy_initial_solution, build_mec_assisted_initial_solution,
)
from uav_mec.algorithms.alns.problem_operators import contact_mode_intensification
from uav_mec.algorithms.alns.state import UavMecState
from uav_mec.analysis.constraint_audit import AuditTolerance, audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash, json_ready, write_json
from uav_mec.analysis.mechanism_controls import FrozenDecisions, GuardedEvaluator
from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config
from uav_mec.optimization.resource import CVXResourceSolver
from innovation_control_search import run_controlled_exploration

METHODS = ("full", "fixed_task_route", "fixed_contacts")
PROTOCOL = {
    "id": "innovation_mechanism_v2", "methods": list(METHODS), "release_s": 0,
    "uavs": 5, "mecs": 2, "nominal_budgets_s": {"50": 15.0, "80": 45.0},
    "exploration_fraction": 0.8, "elite_rounds": 2, "rrt_iterations": 100,
    "energy_tol_rel": 1e-5, "audit_tolerance": asdict(AuditTolerance()),
    "order_seed": 20260925, "scenario_seeds_formal": list(range(45, 53)),
    "algorithm_seeds_formal": [100, 101, 102],
    "comparison": "相同初始化和名义搜索预算，候选冻结过滤贯穿探索与ESI；报告拒绝成本",
    "exploration_operators": "三臂统一使用通用ALNS和直接结构候选配对，修复v1固定路径探索退化",
    "scope": "受限搜索机制诊断，不等于各受限数学问题的全局最优比较",
    "timeline_scope": "搜索中的代理评价及ESI稀疏Stage-1观测，不称完整严格能耗收敛轨迹",
    "stage2_source": "同一最终结构重新执行Stage-1/Stage-2；不回填为历史原始资源",
    "bootstrap": {"unit": "scenario", "replicates": 10000, "seed": 20260925},
}


def provenance() -> dict:
    """记录代码、依赖、硬件和线程配置，避免跨runner耗时被误认为算法收益。"""
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    return {"git_commit": sha, "python": platform.python_version(),
            "platform": platform.platform(), "processor": platform.processor(),
            "cpu_count": os.cpu_count(), "machine": platform.machine(),
            "dependencies": {p: version(p) for p in ("numpy", "cvxpy", "clarabel", "alns", "scs")},
            "threads": {k: os.environ.get(k) for k in
                        ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}


def stage_snapshot(instance, solution, result, *, stage: int) -> dict:
    """阶段失败保留原因；不把求解器回退的Stage-1变量当成Stage-2输出。"""
    status = result.diagnostics.get(f"stage{stage}_status", result.status if stage == 1 else "not_run")
    values = result.stage1_values if stage == 1 else result.diagnostics.get("stage2_raw_values")
    limit = None if stage == 1 else result.energy_stage1_j + result.diagnostics.get("energy_tolerance_j", 0.0)
    if not values:
        return {"status": status, "available": False, "qualified": False,
                "reason": "此阶段没有完整原始变量快照", "values": None, "audit": None}
    audit = audit_both_timelines(instance, solution, values, energy_limit_j=limit)
    return {"status": status, "available": True, "values": values, "audit": audit,
            "qualified": status == "optimal" and all(v["passed"] for v in audit.values())}


def run_method(instance, initial, *, method: str, seed: int, budget_s: float) -> dict:
    """独立方法冷启动缓存；初始化共享，探索和ESI使用同一冻结约束与预算规则。"""
    frozen = FrozenDecisions.from_initial(method, initial)
    started = perf_counter()
    outer = GuardedEvaluator(ScreenedProxyObjectiveEvaluator(), frozen,
                             label="screened_proxy", started_at=started)
    config = UavMecALNSConfig(iterations=100, seed=seed, max_runtime_s=.8 * budget_s,
                             enable_problem_operators=False)
    # 初始目标必须有限；否则inf候选可能破坏接受规则。此检查的成本计入搜索。
    if not math.isfinite(outer(instance, initial)):
        raise RuntimeError("初始代理目标非有限数，不能启动冻结对照")
    exploration, exploration_details = run_controlled_exploration(
        instance, deepcopy(initial), config, outer, .8 * budget_s,
    )
    exploration_runtime = perf_counter() - started
    assert frozen.allows(exploration.best_solution), "探索结果违反冻结约束"
    oracle = Stage1CVXObjectiveOracle()
    strict = GuardedEvaluator(oracle, frozen, label="stage1_oracle", started_at=started)
    elite_started = perf_counter()
    initial_energy = strict(instance, exploration.best_solution)
    solution = deepcopy(exploration.best_solution)
    stats = {"skipped": "exploration_stage1_not_optimal"}
    # 初始严格检查也计入ESI预算；正在进行的求解允许完成，超时显式报告。
    if math.isfinite(initial_energy):
        remaining = max(0.0, .2 * budget_s - (perf_counter() - elite_started))
        state, stats = contact_mode_intensification(
            UavMecState(instance, solution, outer), config=config.problem, objective=strict,
            max_rounds=2, max_runtime_s=remaining,
        )
        solution = state.solution
    search_runtime = perf_counter() - started
    assert frozen.allows(solution), "强化结果违反冻结约束"
    build_event_info(instance, solution)

    # 对最终离散方案离线重算资源；全部时间另列，不冒充搜索时已知结果。
    resource_started = perf_counter()
    resources = CVXResourceSolver(run_stage2=True, energy_tol_rel=1e-5,
                                  capture_stage2_raw_values=True).solve(instance, solution)
    resource_runtime = perf_counter() - resource_started
    audit_started = perf_counter()
    stage1 = stage_snapshot(instance, solution, resources, stage=1)
    stage2 = stage_snapshot(instance, solution, resources, stage=2)
    audit_runtime = perf_counter() - audit_started
    comparison = None
    if stage1["qualified"] and stage2["qualified"]:
        first, second = (s["audit"]["saved"]["metrics"] for s in (stage1, stage2))
        comparison = {"cpu_occupation_change": second["normalized_mec_cpu"] - first["normalized_mec_cpu"],
                      "energy_change_j": second["energy_j"] - first["energy_j"],
                      "energy_tolerance_j": resources.diagnostics["energy_tolerance_j"],
                      "same_structure_sha256": content_hash(solution)}
    return {
        "method": method, "frozen": asdict(frozen), "frozen_invariant_passed": True,
        "initial_sha256": content_hash(initial), "solution": solution,
        "solution_sha256": content_hash(solution), "exploration_solution": exploration.best_solution,
        "exploration_stage1_result": oracle.solve(instance, exploration.best_solution),
        "search_energy_j": strict.strict_incumbent_energy_j,
        "search_runtime_s": search_runtime, "nominal_budget_s": budget_s,
        "overrun_s": max(0.0, search_runtime - budget_s), "exploration_runtime_s": exploration_runtime,
        "resource_recompute_runtime_s": resource_runtime, "audit_runtime_s": audit_runtime,
        "outer_stats": asdict(outer.evaluator.stats), "outer_freeze_stats": outer.summary(),
        "controlled_exploration": exploration_details,
        "elite_freeze_stats": strict.summary(), "elite_stats": stats,
        "oracle_calls": oracle.calls, "oracle_cache_hits": oracle.cache_hits,
        "oracle_solve_records": oracle.solve_records,
        "evaluation_events": outer.events + strict.events,
        "resources": resources, "stage1": stage1, "stage2": stage2,
        "stage_comparison": comparison,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, choices=[50, 80], required=True)
    parser.add_argument("--scenario", type=int, required=True)
    parser.add_argument("--algorithm-seeds", default="100")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--phase", choices=["pilot", "formal"], default="pilot")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seeds = [int(x) for x in args.algorithm_seeds.split(",")]
    if not seeds or len(set(seeds)) != len(seeds) or not set(seeds) <= {100, 101, 102}:
        raise ValueError("算法种子须为100/101/102的非重复子集")
    if args.scenario not in range(45, 53):
        raise ValueError("冻结场景范围为45–52")
    cfg = load_paper_scale_config(args.config)
    instance = build_paper_scale_instance(cfg, num_tasks=args.tasks, num_uavs=5, num_mecs=2,
                                          scenario_seed=args.scenario)
    initial_started = perf_counter()
    initial = build_mec_assisted_initial_solution(instance, base_solution=build_greedy_initial_solution(instance))
    initial_runtime = perf_counter() - initial_started
    payload = {"protocol": PROTOCOL, "protocol_sha256": content_hash(PROTOCOL),
               "phase": args.phase, "provenance": provenance(),
               "config": json_ready(cfg), "config_file_sha256": hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
               "instance": instance, "instance_sha256": content_hash(instance),
               "tasks": args.tasks, "scenario_seed": args.scenario, "algorithm_seeds": seeds,
               "initial_solution": initial, "initialization_runtime_s": initial_runtime,
               "complete": False, "rows": []}
    write_json(args.output, payload)
    try:
        for seed in seeds:
            order = np.random.default_rng([20260925, args.tasks, args.scenario, seed]).permutation(METHODS).tolist()
            for index, method in enumerate(order):
                logging.info("开始 K%s S%s A%s %s（顺序%s）", args.tasks, args.scenario, seed, method, index)
                row = run_method(instance, initial, method=method, seed=seed,
                                 budget_s=PROTOCOL["nominal_budgets_s"][str(args.tasks)])
                row.update({"tasks": args.tasks, "scenario_seed": args.scenario,
                            "algorithm_seed": seed, "method_order": order, "order_index": index})
                payload["rows"].append(row)
                write_json(args.output, payload)
                logging.info("完成 %s：Stage1合格=%s Stage2合格=%s，搜索%.2fs", method,
                             row["stage1"]["qualified"], row["stage2"]["qualified"], row["search_runtime_s"])
    except Exception as exc:
        # 作业错误与数值未合格分开保存，保留已完成样本，并让CI明确失败。
        payload["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(args.output, payload)
        logging.exception("补充实验中断 K%s S%s", args.tasks, args.scenario)
        raise
    payload["complete"] = True
    write_json(args.output, payload)


if __name__ == "__main__":
    main()
