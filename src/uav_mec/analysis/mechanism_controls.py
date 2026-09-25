"""受控机制实验的决策冻结和候选过滤；不替换论文默认搜索算法。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from time import perf_counter

from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.domain import DiscreteSolution


@dataclass(frozen=True)
class FrozenDecisions:
    """冻结任务所属/访问序列或接触所属/物理点/顺序，允许合法的时间重建。"""

    mode: str
    signature: tuple

    @classmethod
    def from_initial(cls, mode: str, initial: DiscreteSolution) -> "FrozenDecisions":
        if mode not in ("full", "fixed_task_route", "fixed_contacts"):
            raise ValueError(f"未知机制对照：{mode}")
        return cls(mode, cls._signature(mode, initial))

    @staticmethod
    def _signature(mode: str, solution: DiscreteSolution) -> tuple:
        if mode == "full":
            return ()
        if mode == "fixed_task_route":
            return tuple((u, tuple(r.task_ids())) for u, r in sorted(solution.routes.items()))
        return tuple((u, tuple((v, solution.contact_visits[v].uav_id,
                               solution.contact_visits[v].point_id)
                              for v in r.contact_visit_ids()))
                     for u, r in sorted(solution.routes.items()))

    def allows(self, solution: DiscreteSolution) -> bool:
        return self.signature == self._signature(self.mode, solution)


class GuardedEvaluator:
    """在任一完整候选进入目标评价前拒绝解冻，记录拒绝成本与实际可搜索结构数。

    临时destroy状态可以缺少任务；它不能成为被接受的完整状态。有限初始目标
    保证违反冻结规则的inf候选在ALNS/ESI均无法被接受，最终方案还需独立断言。
    """

    def __init__(self, evaluator, frozen: FrozenDecisions, *, label: str,
                 started_at: float | None = None):
        self.evaluator = evaluator
        self.frozen = frozen
        self.label = label
        self.started_at = perf_counter() if started_at is None else started_at
        self.events: list[dict] = []
        self.admissible_signatures: set[str] = set()
        self.rejected = 0
        self.strict_incumbent_energy_j: float | None = None
        self.strict_incumbent_solution = None

    @property
    def stats(self):
        return getattr(self.evaluator, "stats", None)

    def __call__(self, instance, solution) -> float:
        started = perf_counter()
        signature = content_hash(solution_signature(solution))
        allowed = self.frozen.allows(solution)
        if not allowed:
            self.rejected += 1
            value = float("inf")
        else:
            self.admissible_signatures.add(signature)
            value = float(self.evaluator(instance, solution))
        is_strict = self.label == "stage1_oracle" and math.isfinite(value)
        if is_strict and (self.strict_incumbent_energy_j is None or value < self.strict_incumbent_energy_j):
            self.strict_incumbent_energy_j = value
            self.strict_incumbent_solution = deepcopy(solution)
        self.events.append({"elapsed_s": perf_counter() - self.started_at,
                            "evaluation_runtime_s": perf_counter() - started,
                            "structure_sha256": signature, "evaluation_type": self.label,
                            "frozen_allowed": allowed, "value": value if math.isfinite(value) else None,
                            "strict_by_original_protocol": is_strict,
                            "known_strict_incumbent_j": self.strict_incumbent_energy_j})
        return value

    def summary(self) -> dict:
        return {"evaluations": len(self.events), "rejected_by_freeze": self.rejected,
                "unique_admissible_structures": len(self.admissible_signatures)}
