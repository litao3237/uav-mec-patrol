"""冻结算法下的六规模五方法实验，保存完整方案、两阶段变量和独立残差。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import logging
from pathlib import Path
from time import perf_counter

import numpy as np

from run_innovation_mechanism import provenance, stage_snapshot
from uav_mec.algorithms import (
    GARouteConfig, ScreenedProxyObjectiveEvaluator, Stage1CVXObjectiveOracle,
    UavMecALNSConfig, build_fixed_route_nearest_mec_solution,
    build_greedy_initial_solution, build_mec_assisted_initial_solution,
    run_route_ga, run_uav_mec_hybrid_alns,
)
from uav_mec.analysis.constraint_audit import AuditTolerance
from uav_mec.analysis.experiment_snapshot import content_hash, write_json
from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config
from uav_mec.optimization.resource import CVXResourceSolver

METHODS = ("GR-MR", "FTR-NM", "RGA-MR", "B-ALNS", "ESI-ALNS")
DETERMINISTIC = METHODS[:2]
PROTOCOL = {
    "id": "multiscale_five_method_metrics_v1", "tasks": [30, 40, 50, 60, 70, 80],
    "scenarios": list(range(45, 53)), "algorithm_seeds": [100, 101, 102],
    "methods": list(METHODS), "uavs": 5, "mecs": 2, "release_s": 0,
    "iterations": 100, "elite_rounds": 2, "ga_population": 16, "ga_generations": 12,
    "energy_tol_rel": 1e-6, "audit_tolerance": asdict(AuditTolerance()),
    "order_seed": 20260928, "bootstrap_seed": 20260928, "bootstrap_replicates": 10000,
    "budget": "固定探索配置；B-ALNS与ESI共享探索轨迹，不是等时间比较",
    "algorithm": "原版ESI-ALNS；不调用受限机制诊断搜索或Energy-Guided变体",
    "qos_timeline": "两阶段均合格后使用Stage-2资源重建的最早时序",
    "independent_unit": "scenario；算法重复嵌套，确定性方法每场景一次",
}


def phase_matrix(phase: str) -> tuple[list[int], list[int], list[int]]:
    """先导只检查低中高负载的执行与记录，正式矩阵不按收益筛选。"""
    if phase == "pilot":
        return [30, 50, 80], [45], [100]
    if phase == "formal":
        return PROTOCOL["tasks"], PROTOCOL["scenarios"], PROTOCOL["algorithm_seeds"]
    raise ValueError(f"未知阶段：{phase}")


def expected_keys(phase: str) -> set[tuple]:
    """确定性方法不复制到算法种子维度，防止重复记录伪增样本数。"""
    tasks, scenarios, seeds = phase_matrix(phase)
    return {(k, s, a, m) for k in tasks for s in scenarios for m in METHODS
            for a in ([None] if m in DETERMINISTIC else seeds)}


def execution_schedule(tasks: int, scenario: int, seeds: list[int]) -> list[tuple]:
    """独立搜索组随机执行；共享探索的B/ESI保留为不可拆分的配对组。"""
    groups = [("GR-MR", None), ("FTR-NM", None)]
    groups += [(m, a) for a in seeds for m in ("RGA-MR", "B/ESI")]
    rng = np.random.default_rng([PROTOCOL["order_seed"], tasks, scenario])
    return [groups[int(i)] for i in rng.permutation(len(groups))]


def finalize(instance, solution, *, method: str, seed: int | None,
             initialization_s: float, search_s: float, diagnostics: dict) -> dict:
    """统一在最终结构重算两阶段资源；独立核验失败保留原始值但不进入指标均值。"""
    started = perf_counter()
    resources = CVXResourceSolver(
        run_stage2=True, energy_tol_rel=PROTOCOL["energy_tol_rel"],
        capture_stage2_raw_values=True,
    ).solve(instance, solution)
    resource_s = perf_counter() - started
    started = perf_counter()
    first = stage_snapshot(instance, solution, resources, stage=1)
    second = stage_snapshot(instance, solution, resources, stage=2)
    audit_s = perf_counter() - started
    return {
        "method": method, "algorithm_seed": seed, "solution": solution,
        "solution_sha256": content_hash(solution), "resources": resources,
        "stage1": first, "stage2": second, "diagnostics": diagnostics,
        "timing": {"initialization_s": initialization_s, "search_s": search_s,
                   "resource_recompute_s": resource_s, "independent_audit_s": audit_s,
                   "total_to_resources_s": initialization_s + search_s + resource_s,
                   "total_with_audit_s": initialization_s + search_s + resource_s + audit_s},
    }


def run_block(tasks: int, scenario: int, phase: str, config: Path, output: Path) -> None:
    """每个场景块在同一runner顺序完成各方法，逐组原子落盘以保留中断上下文。"""
    task_values, scenarios, seeds = phase_matrix(phase)
    if tasks not in task_values or scenario not in scenarios:
        raise ValueError("请求不属于冻结实验矩阵")
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有实验：{output}")
    cfg = load_paper_scale_config(config)
    instance = build_paper_scale_instance(
        cfg, num_tasks=tasks, num_uavs=PROTOCOL["uavs"], num_mecs=PROTOCOL["mecs"],
        scenario_seed=scenario,
    )
    started = perf_counter()
    route = build_greedy_initial_solution(instance)
    route_s = perf_counter() - started
    started = perf_counter()
    initial = build_mec_assisted_initial_solution(instance, base_solution=deepcopy(route))
    repair_s = perf_counter() - started
    initial_hash = content_hash(initial)
    schedule = execution_schedule(tasks, scenario, seeds)
    payload = {
        "protocol": PROTOCOL, "protocol_sha256": content_hash(PROTOCOL), "phase": phase,
        "provenance": provenance(), "config": cfg,
        "config_file_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "instance": instance, "instance_sha256": content_hash(instance),
        "initial_solution": initial, "initial_sha256": initial_hash,
        "tasks": tasks, "scenario_seed": scenario, "algorithm_seeds": seeds,
        "execution_schedule": schedule, "complete": False, "rows": [],
    }
    write_json(output, payload)

    def save(row: dict, index: int) -> None:
        # 确认搜索未原地污染共享初解，保证不同方法/种子的初始化一致。
        if content_hash(initial) != initial_hash:
            raise RuntimeError("共享初始方案被搜索过程修改")
        row.update(tasks=tasks, scenario_seed=scenario, group_order_index=index,
                   initial_sha256=initial_hash)
        payload["rows"].append(row)
        write_json(output, payload)
        logging.info("K%s S%s A%s %s：Stage1=%s Stage2=%s，搜索%.2fs", tasks,
                     scenario, row["algorithm_seed"], row["method"],
                     row["stage1"]["qualified"], row["stage2"]["qualified"],
                     row["timing"]["search_s"])

    try:
        for index, (group, seed) in enumerate(schedule):
            logging.info("开始 K%s S%s %s A%s", tasks, scenario, group, seed)
            if group == "GR-MR":
                save(finalize(instance, initial, method=group, seed=None,
                              initialization_s=route_s + repair_s, search_s=0.0,
                              diagnostics={"route_seed_s": route_s, "mec_repair_s": repair_s}), index)
            elif group == "FTR-NM":
                started = perf_counter()
                solution = build_fixed_route_nearest_mec_solution(instance, base_solution=deepcopy(route))
                build_s = perf_counter() - started
                save(finalize(instance, solution, method=group, seed=None,
                              initialization_s=route_s + build_s, search_s=0.0,
                              diagnostics={"route_seed_s": route_s, "nearest_mec_s": build_s}), index)
            elif group == "RGA-MR":
                started = perf_counter()
                result = run_route_ga(instance, seed=seed, config=GARouteConfig(
                    population_size=PROTOCOL["ga_population"], generations=PROTOCOL["ga_generations"]))
                search_s = perf_counter() - started
                save(finalize(instance, result.best_solution, method=group, seed=seed,
                              initialization_s=0.0, search_s=search_s,
                              diagnostics={"ga_evaluations": result.evaluations,
                                           "ga_cache_hits": result.cache_hits}), index)
            else:
                evaluator = ScreenedProxyObjectiveEvaluator()
                oracle = Stage1CVXObjectiveOracle()
                started = perf_counter()
                result = run_uav_mec_hybrid_alns(
                    instance, initial_solution=deepcopy(initial),
                    config=UavMecALNSConfig(iterations=PROTOCOL["iterations"], seed=seed,
                                           enable_problem_operators=False),
                    evaluator=evaluator, elite_oracle=oracle, elite_rounds=PROTOCOL["elite_rounds"],
                )
                wall_s = perf_counter() - started
                common = {"exploration_sha256": content_hash(result.exploration.best_solution),
                          "exploration_runtime_s": result.exploration_runtime_s,
                          "elite_phase_runtime_s": result.elite_phase_runtime_s,
                          "elite_stats": result.elite_stats, "oracle_records": oracle.solve_records,
                          "screening_stats": asdict(evaluator.stats)}
                # B为共享轨迹的探索终点；ESI成本包含后强化及其内部CVX验收。
                for method, solution, search_s, cvx in (
                    ("B-ALNS", result.exploration.best_solution, result.exploration_runtime_s,
                     result.exploration_cvx),
                    ("ESI-ALNS", result.best_solution, wall_s, result.final_cvx),
                ):
                    save(finalize(instance, solution, method=method, seed=seed,
                                  initialization_s=route_s + repair_s, search_s=search_s,
                                  diagnostics={**common, "search_stage1_result": cvx}), index)
    except Exception as exc:
        payload["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(output, payload)
        logging.exception("场景块中断 K%s S%s；保留已完成记录", tasks, scenario)
        raise
    payload["complete"] = True
    write_json(output, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--scenario", type=int, required=True)
    parser.add_argument("--phase", choices=["pilot", "formal"], required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_block(args.tasks, args.scenario, args.phase, args.config, args.output)


if __name__ == "__main__":
    main()
