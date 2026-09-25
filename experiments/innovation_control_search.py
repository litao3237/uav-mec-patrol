"""共同机制诊断搜索：保证冻结任务路径时仍可直接探索接触/卸载变量。"""
from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

import numpy as np

from uav_mec.algorithms import UavMecALNSSession
from uav_mec.algorithms.alns.problem_operators import contact_mode_intensification
from uav_mec.algorithms.alns.runner import _TrackingRouletteWheel


def run_controlled_exploration(instance, initial, config, evaluator, budget_s, *, max_iterations=None):
    """三臂共用通用ALNS与直接结构候选，只由外部冻结规则区分可接受解。

    首轮先导显示：先破坏任务路径再筛掉路径变化，会让固定路径臂不能调整
    剩余变量。为此添加不破坏路径的结构候选入口，并同样提供给完整/固定接触臂。
    这是单独的机制诊断协议，不修改论文默认ALNS或将诊断结果冒充原主比较。
    """
    started = perf_counter()
    session = UavMecALNSSession(instance, initial_solution=initial, config=config, evaluator=evaluator)
    structural_records = []

    def retain_complete_state(state, rng):
        """保持完整状态，允许结构候选在未获得严格资源解之前按代理目标探索。"""
        del rng
        return state.copy()

    def direct_structure_repair(state, rng):
        """复用现有结构候选及冻结评价器，所有新增候选成本计入共同搜索预算。"""
        del rng
        candidate, stats = contact_mode_intensification(
            state, config=config.problem, objective=evaluator, max_rounds=1,
            max_runtime_s=max(0.0, budget_s - (perf_counter() - started)),
        )
        structural_records.append(stats)
        return candidate

    generic_destroy_count = len(session.destroy_operators)
    generic_repair_count = len(session.repair_operators)
    session.destroy_operators.append(("retain_complete_state", retain_complete_state))
    session.repair_operators.append(("direct_structure_repair", direct_structure_repair))
    coupling = np.zeros((generic_destroy_count + 1, generic_repair_count + 1), dtype=bool)
    coupling[:generic_destroy_count, :generic_repair_count] = True
    coupling[-1, -1] = True
    # 显式建立算子配对，避免把完整结构候选施加到未修复的部分状态。
    session.selector = _TrackingRouletteWheel(
        scores=list(config.operator_scores), decay=config.operator_decay,
        num_destroy=len(session.destroy_operators), num_repair=len(session.repair_operators),
        op_coupling=coupling, destroy_names=[n for n, _ in session.destroy_operators],
        repair_names=[n for n, _ in session.repair_operators],
    )
    result = session.run_segment(max_runtime_s=max(0.0, budget_s - (perf_counter() - started)),
                                 max_iterations=max_iterations)
    return result, {"config": asdict(config), "operator_pair_counts": result.operator_pair_counts,
                    "iterations": result.iterations, "direct_structure_records": structural_records}
