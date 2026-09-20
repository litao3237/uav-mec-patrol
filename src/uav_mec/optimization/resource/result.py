from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceSolveResult:
    status: str
    solver: str
    is_dcp: bool
    energy_stage1_j: float
    energy_final_j: float
    stage1_values: dict[str, Any] = field(default_factory=dict)
    final_values: dict[str, Any] = field(default_factory=dict)
    stage1_duals: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return bool(self.final_values)
