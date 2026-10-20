"""Common task-success objective for v26. Physical feasibility is ranked first.

The scalar is a bounded monotone encoding of the lexicographic order used
by the discrete heuristics. The exact tuple should be used whenever available.
"""
from __future__ import annotations

import math


def task_key(*, physical_violations: int, on_time: int, normalized_lateness: float,
             energy_j: float, distance_m: float) -> tuple[float, ...]:
    return (float(physical_violations > 0), -float(on_time),
            float(normalized_lateness), float(energy_j), float(distance_m))


def task_scalar(*, total_tasks: int, physical_violations: int,
                on_time: int, normalized_lateness: float,
                energy_j: float, distance_m: float) -> float:
    """Guarantee discrete task count priority; remaining terms are bounded ties."""
    values = (normalized_lateness, energy_j, distance_m)
    if total_tasks < 0 or not (0 <= on_time <= total_tasks):
        raise ValueError("Invalid task-success counts")
    if not all(math.isfinite(x) and x >= 0 for x in values):
        raise ValueError("Task objective inputs must be finite and nonnegative")

    def bounded(x: float) -> float:
        return x / (1.0 + x)

    return float((total_tasks + 1) * 1e9 * (physical_violations > 0)
                 + (total_tasks - on_time) * 1e9
                 + bounded(normalized_lateness) * 1e6
                 + bounded(energy_j) * 1e3
                 + bounded(distance_m))
