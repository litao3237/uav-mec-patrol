"""ESI 的统一数值接受规则，区分求解器状态与物理约束验收结果。"""
from __future__ import annotations

from dataclasses import replace
import math

from uav_mec.analysis.constraint_audit import AuditTolerance, audit_both_timelines
from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.optimization.resource.result import ResourceSolveResult


def qualify_stage1_result(
    instance: Instance,
    solution: DiscreteSolution,
    result: ResourceSolveResult,
) -> ResourceSolveResult:
    """核验完整 Stage-1 快照，失败时保留变量及原状态供复查。

    使用与正式实验相同的冻结容差。原变量和最早时序必须同时通过，
    不能通过重建时间或裁剪资源掩盖求解器返回值的违约。
    """
    raw_status = str(result.diagnostics.get(
        "stage1_solver_status", result.diagnostics.get("stage1_status", result.status)
    ))
    audit = None
    reason = None
    energy_check = None
    if raw_status != "optimal":
        reason = "stage1_not_optimal"
    elif not result.stage1_values:
        reason = "missing_stage1_values"
    elif not math.isfinite(result.energy_stage1_j):
        reason = "nonfinite_stage1_energy"
    else:
        audit = audit_both_timelines(instance, solution, result.stage1_values)
        if not all(item["complete"] and item["passed"] for item in audit.values()):
            reason = "stage1_residual_failed"
        else:
            # 缓存目标也必须对应这份物理变量，防止错误目标参与精英比较。
            physical = audit["saved"]["metrics"]["energy_j"]
            tolerance = AuditTolerance()
            limit = tolerance.energy_j + tolerance.relative * max(
                1.0, abs(physical), abs(result.energy_stage1_j)
            )
            error = abs(result.energy_stage1_j - physical)
            energy_check = {"difference_j": error, "tolerance_j": limit, "passed": error <= limit}
            if not energy_check["passed"]:
                reason = "stage1_energy_mismatch"

    qualified = reason is None
    # 已有消费者会检查 stage1_status，因此拒绝状态必须向外传播，不能只新增诊断标志。
    # stage1_solver_status 保留求解器的原始 optimal，避免抹去数值故障证据。
    status = "invalid_residual" if raw_status == "optimal" and not qualified else raw_status
    diagnostics = dict(result.diagnostics, stage1_solver_status=raw_status,
                       stage1_status=status, stage1_qualified=qualified,
                       stage1_acceptance_reason=reason, stage1_acceptance_audit=audit,
                       stage1_energy_consistency=energy_check,
                       stage1_acceptance_rule="optimal_saved_and_reconstructed_residuals_v1")
    return replace(result, status=status if not qualified else result.status, diagnostics=diagnostics)


def stage1_is_qualified(result: ResourceSolveResult) -> bool:
    """缺少验收证据时按不合格处理，不从 optimal 状态推断物理可行。"""
    return bool(result.diagnostics.get("stage1_qualified", False))
