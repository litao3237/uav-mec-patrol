"""Single task-QoS ordering and numerical convention for the M0 protocol.

Only the on-time count is integer. No smooth scalar can represent a strict
lexicographic ordering on arbitrarily close real-valued lateness values.
We therefore use exact tuples for deterministic/elite comparisons and an
explicitly *surrogate* finite scalar only where the ALNS/SA API demands one.
"""
from __future__ import annotations

import math

# This is a numerical *classification* tolerance, not a relaxation of any
# route, radio, CPU, battery or UAV-return physical hard constraint.
ON_TIME_TOL_S = 1e-6
LATENESS_TOL = 1e-8
ENERGY_EQUALITY_TOL_J = 1e-3
DISTANCE_EQUALITY_TOL_M = 1e-6


def task_key(*, physical_violations: int, on_time: int,
             normalized_lateness: float, energy_j: float,
             distance_m: float) -> tuple[float, ...]:
    if physical_violations < 0 or on_time < 0:
        raise ValueError("Invalid physical violation / success count")
    if not all(math.isfinite(x) and x >= 0 for x in
               (normalized_lateness, energy_j, distance_m)):
        raise ValueError("Task QoS measurements must be finite and nonnegative")
    return (float(physical_violations > 0), -float(on_time),
            float(normalized_lateness), float(energy_j), float(distance_m))


def measured_task_key(instance, delays_s: dict[str, float], *,
                      energy_j: float, distance_m: float,
                      physical_violations: int = 0) -> tuple[float, ...]:
    """Use the earliest reconstructed physical completion times, not epigraph slack."""
    if set(delays_s) != set(instance.tasks):
        raise ValueError("Measured task delays must cover every admitted task")
    successes = 0
    late = 0.0
    for t, delay in delays_s.items():
        if not math.isfinite(delay) or delay < -ON_TIME_TOL_S:
            raise ValueError("Invalid measured task completion delay")
        task = instance.tasks[t]
        excess = delay - task.deadline_s - ON_TIME_TOL_S
        successes += int(excess <= 0.0)
        late += max(0.0, excess) / max(1.0, task.deadline_s)
    return task_key(physical_violations=physical_violations, on_time=successes,
                    normalized_lateness=late, energy_j=energy_j,
                    distance_m=distance_m)


def better_task_key(candidate: tuple[float, ...],
                    incumbent: tuple[float, ...], *,
                    min_energy_improvement_j: float = 0.0,
                    min_energy_improvement_rel: float = 0.0,
                    lateness_tol: float = LATENESS_TOL) -> bool:
    """Lexicographic task success -> lateness -> real Joules -> real meters.

    Thresholds for energy are expressed only in physical Joules (never on
    the dimensionless ALNS scalar). An energy near-tie can be broken by
    distance only if energy differs by <= 1e-3 J.
    """
    if candidate[0] != incumbent[0]:
        return candidate[0] < incumbent[0]
    if candidate[1] != incumbent[1]:
        return candidate[1] < incumbent[1]
    if candidate[2] < incumbent[2] - lateness_tol:
        return True
    if candidate[2] > incumbent[2] + lateness_tol:
        return False
    energy_delta = incumbent[3] - candidate[3]
    threshold = max(min_energy_improvement_j,
                    min_energy_improvement_rel * max(1.0, abs(incumbent[3])))
    if energy_delta > max(ENERGY_EQUALITY_TOL_J, threshold):
        return True
    if abs(energy_delta) <= ENERGY_EQUALITY_TOL_J:
        return candidate[4] < incumbent[4] - DISTANCE_EQUALITY_TOL_M
    return False


def task_scalar(*, total_tasks: int, physical_violations: int,
                on_time: int, normalized_lateness: float,
                energy_j: float, distance_m: float,
                energy_reference_j: float = 1.0,
                distance_reference_m: float = 1.0) -> float:
    """Finite monotone surrogate for libraries accepting scalar costs only.

    Physics-scale normalization avoids the old E/(1+E) saturation at 1e5 J.
    Integer task counts strictly dominate all lower-priority bounded terms;
    real-valued lateness/energy tradeoffs are *approximations*, not exact lex.
    """
    task_key(physical_violations=physical_violations, on_time=on_time,
             normalized_lateness=normalized_lateness, energy_j=energy_j,
             distance_m=distance_m)
    if total_tasks < 0 or on_time > total_tasks:
        raise ValueError("Invalid total task count")
    if energy_reference_j <= 0 or distance_reference_m <= 0:
        raise ValueError("Normalization reference must be positive")

    def bounded(x: float, reference: float) -> float:
        return x / (x + reference)

    return float((total_tasks + 1) * 1e9 * int(physical_violations > 0)
                 + (total_tasks - on_time) * 1e9
                 + bounded(normalized_lateness, 1.0) * 1e6
                 + bounded(energy_j, energy_reference_j) * 1e3
                 + bounded(distance_m, distance_reference_m))
