from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import logging
from time import perf_counter
from typing import Any

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource import (
    CVXResourceSolver,
    ResourceSolveResult,
)

from .evaluator import (
    ScreenedProxyObjectiveEvaluator,
    solution_signature,
)
from .problem_operators import contact_mode_intensification
from .runner import (
    UavMecALNSConfig,
    UavMecALNSResult,
    run_uav_mec_alns,
)
from .state import ObjectiveEvaluator, UavMecState
from uav_mec.evaluation.task_objective import task_scalar


class Stage1CVXObjectiveOracle:
    """缓存精英结构的 Stage-1 求解和完整残差验收，仅合格值可参与接受比较。"""

    def __init__(
        self,
        solver: CVXResourceSolver | None = None,
    ) -> None:
        self.solver = solver or CVXResourceSolver(
            run_stage2=False
        )
        self._cache: dict[tuple, ResourceSolveResult] = {}
        self.calls = 0
        self.cache_hits = 0
        self.solve_runtimes_s: list[float] = []
        self.solve_records: list[dict[str, Any]] = []
        self.audit_runtime_s = 0.0
        self.seeded_results = 0

    def _qualify(self, instance, solution, result):
        """独立核验先于缓存与比较；求解器的 optimal 不替代可行性检查。"""
        # 延迟导入避免 analysis 与资源求解模块初始化时出现循环依赖。
        from uav_mec.analysis.stage1_acceptance import qualify_stage1_result

        started = perf_counter()
        qualified = qualify_stage1_result(instance, solution, result)
        self.audit_runtime_s += perf_counter() - started
        if qualified.diagnostics["stage1_status"] == "invalid_residual":
            logging.getLogger(__name__).warning(
                "ESI拒绝Stage-1候选：原因=%s，求解器=%s，原状态=%s",
                qualified.diagnostics["stage1_acceptance_reason"], result.solver,
                qualified.diagnostics["stage1_solver_status"],
            )
        return qualified

    def prime(self, instance, solution, result):
        """从冻结检查点恢复基线，重新验收且拒绝覆盖已有缓存。

        此操作不计为新的凸求解，核验时间单独累计，便于重放实验准确报告成本。
        """
        key = solution_signature(solution)
        if key in self._cache:
            raise ValueError("拒绝覆盖已缓存的Stage-1结果")
        qualified = self._qualify(instance, solution, deepcopy(result))
        self._cache[key] = qualified
        self.seeded_results += 1
        return qualified

    def solve(
        self,
        instance: Instance,
        solution: DiscreteSolution,
    ) -> ResourceSolveResult:
        key = solution_signature(solution)
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]

        self.calls += 1
        info = build_event_info(instance, solution)
        started = perf_counter()
        result = self.solver.solve(
            instance,
            solution,
            info,
        )
        runtime_s = perf_counter() - started
        self.solve_runtimes_s.append(runtime_s)
        result = self._qualify(instance, solution, result)
        self.solve_records.append(
            {
                "runtime_s": runtime_s,
                "status": str(
                    result.diagnostics.get(
                        "stage1_status",
                        result.status,
                    )
                ),
                "energy_j": (
                    float(result.energy_stage1_j)
                    if result.feasible
                    else None
                ),
                "contacts": len(solution.contact_visits),
                "qualified": result.diagnostics["stage1_qualified"],
                "solver_status": result.diagnostics["stage1_solver_status"],
                "rejection_reason": result.diagnostics["stage1_acceptance_reason"],
                "residual_summary": {
                    name: {field: audit.get(field) for field in
                           ("passed", "complete", "worst_constraint", "max_normalized_violation", "reason")}
                    for name, audit in (result.diagnostics["stage1_acceptance_audit"] or {}).items()
                },
                "offloaded_tasks": sum(
                    decision.mode.value == "offload"
                    for decision in solution.task_decisions.values()
                ),
            }
        )
        self._cache[key] = result
        return result

    def __call__(
        self,
        instance: Instance,
        solution: DiscreteSolution,
    ) -> float:
        result = self.solve(instance, solution)
        stage1_status = str(
            result.diagnostics.get(
                "stage1_status",
                result.status,
            )
        )
        if (
            not result.feasible
            or stage1_status != "optimal"
            or not result.diagnostics.get("stage1_qualified", False)
        ):
            return float("inf")
        if not instance.qos_hard:
            metrics = result.diagnostics["stage1_acceptance_audit"]["reconstructed"]
            delays = metrics["timeline"]["task_delay_s"]
            success = sum(delays[t] <= instance.tasks[t].deadline_s + 1e-9 for t in instance.tasks)
            lateness = sum(max(0., delays[t] - instance.tasks[t].deadline_s)
                           / max(1., instance.tasks[t].deadline_s) for t in instance.tasks)
            return task_scalar(total_tasks=len(instance.tasks), physical_violations=0,
                               on_time=success, normalized_lateness=lateness,
                               energy_j=float(result.energy_stage1_j),
                               distance_m=metrics["metrics"]["total_distance_m"])
        return float(result.energy_stage1_j)


@dataclass
class HybridUavMecALNSResult:
    """Result of generic exploration plus exact elite intensification."""

    exploration: UavMecALNSResult
    best_solution: DiscreteSolution
    exploration_cvx: ResourceSolveResult
    final_cvx: ResourceSolveResult
    elite_stats: dict[str, Any]
    elite_cvx_calls: int
    elite_cvx_cache_hits: int
    elite_runtime_s: float
    exploration_runtime_s: float = 0.0
    elite_phase_runtime_s: float = 0.0

    @property
    def exploration_cvx_energy_j(self) -> float:
        return float(self.exploration_cvx.energy_stage1_j)

    @property
    def final_cvx_energy_j(self) -> float:
        return float(self.final_cvx.energy_stage1_j)

    @property
    def improvement_pct(self) -> float:
        base = self.exploration_cvx_energy_j
        final = self.final_cvx_energy_j
        return 100.0 * (base - final) / max(1.0, abs(base))


def run_uav_mec_hybrid_alns(
    instance: Instance,
    *,
    initial_solution: DiscreteSolution | None = None,
    config: UavMecALNSConfig | None = None,
    evaluator: ObjectiveEvaluator | None = None,
    elite_rounds: int = 2,
    elite_oracle: Stage1CVXObjectiveOracle | None = None,
    exploration_max_runtime_s: float | None = None,
    elite_max_runtime_s: float | None = None,
) -> HybridUavMecALNSResult:
    """Run generic ALNS exploration, then exact elite structural refinement.

    The exploration trajectory deliberately excludes problem-specific peer
    operators because current ablations show they can steal exploration budget
    from strong generic neighborhoods. Problem structure is instead injected in
    a short elite phase whose accepted moves are monotone under Stage-1 CVX.
    """

    if elite_rounds <= 0:
        raise ValueError("elite_rounds must be positive")
    if (
        exploration_max_runtime_s is not None
        and exploration_max_runtime_s < 0
    ):
        raise ValueError(
            "exploration_max_runtime_s must be non-negative"
        )
    if elite_max_runtime_s is not None and elite_max_runtime_s < 0:
        raise ValueError("elite_max_runtime_s must be non-negative")

    cfg = config or UavMecALNSConfig()
    exploration_cfg = replace(
        cfg,
        enable_problem_operators=False,
        max_runtime_s=(
            exploration_max_runtime_s
            if exploration_max_runtime_s is not None
            else cfg.max_runtime_s
        ),
    )
    objective_evaluator = (
        evaluator or ScreenedProxyObjectiveEvaluator()
    )

    exploration_started = perf_counter()
    exploration = run_uav_mec_alns(
        instance,
        initial_solution=initial_solution,
        config=exploration_cfg,
        evaluator=objective_evaluator,
    )
    exploration_runtime_s = perf_counter() - exploration_started

    oracle = elite_oracle or Stage1CVXObjectiveOracle()
    elite_phase_started = perf_counter()
    exploration_cvx = oracle.solve(
        instance,
        exploration.best_solution,
    )
    stage1_status = str(
        exploration_cvx.diagnostics.get(
            "stage1_status",
            exploration_cvx.status,
        )
    )
    skip_reason = None
    if not exploration_cvx.feasible:
        skip_reason = "exploration_stage1_infeasible"
    elif stage1_status != "optimal":
        # Elite acceptance is intended to be an exact monotone refinement.
        # Do not compare candidate energies against an approximate
        # OPTIMAL_INACCURATE baseline.
        skip_reason = (
            "exploration_stage1_invalid_residual"
            if stage1_status == "invalid_residual"
            else "exploration_stage1_not_strict_optimal"
        )
    elif not exploration_cvx.diagnostics.get("stage1_qualified", False):
        skip_reason = "exploration_stage1_unqualified"

    if skip_reason is not None:
        return HybridUavMecALNSResult(
            exploration=exploration,
            best_solution=deepcopy(exploration.best_solution),
            exploration_cvx=exploration_cvx,
            final_cvx=exploration_cvx,
            elite_stats={
                "rounds": 0,
                "candidates_evaluated": 0,
                "improvements": 0,
                "accepted_moves": [],
                "evaluated_moves": [],
                "skipped": skip_reason,
            },
            elite_cvx_calls=oracle.calls,
            elite_cvx_cache_hits=oracle.cache_hits,
            elite_runtime_s=0.0,
            exploration_runtime_s=exploration_runtime_s,
            elite_phase_runtime_s=(
                perf_counter() - elite_phase_started
            ),
        )

    state = UavMecState(
        instance,
        deepcopy(exploration.best_solution),
        objective_evaluator,
    )

    elapsed_before_intensification = (
        perf_counter() - elite_phase_started
    )
    remaining_elite_runtime_s = (
        None
        if elite_max_runtime_s is None
        else max(
            0.0,
            elite_max_runtime_s - elapsed_before_intensification,
        )
    )

    t0 = perf_counter()
    intensified, elite_stats = contact_mode_intensification(
        state,
        config=cfg.problem,
        objective=oracle,
        max_rounds=elite_rounds,
        max_runtime_s=remaining_elite_runtime_s,
    )
    elite_runtime_s = perf_counter() - t0

    validate_solution(instance, intensified.solution)
    final_cvx = oracle.solve(
        instance,
        intensified.solution,
    )

    # 最后一道防线防止自定义评价器或未来改动把未验收结果作为精英返回。
    if not final_cvx.diagnostics.get("stage1_qualified", False):
        logging.getLogger(__name__).error("ESI最终结果未通过验收，保留已合格的探索基线")
        intensified.solution = deepcopy(exploration.best_solution)
        final_cvx = exploration_cvx
        elite_stats["output_fallback"] = "unqualified_final_to_qualified_baseline"

    return HybridUavMecALNSResult(
        exploration=exploration,
        best_solution=deepcopy(intensified.solution),
        exploration_cvx=exploration_cvx,
        final_cvx=final_cvx,
        elite_stats=elite_stats,
        elite_cvx_calls=oracle.calls,
        elite_cvx_cache_hits=oracle.cache_hits,
        elite_runtime_s=elite_runtime_s,
        exploration_runtime_s=exploration_runtime_s,
        elite_phase_runtime_s=(
            perf_counter() - elite_phase_started
        ),
    )
