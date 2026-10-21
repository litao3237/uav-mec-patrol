"""M0.3: unit-aware task QoS acceptance and scale-free operator credit.

These optional components are limited to soft-deadline task-QoS studies.
They intentionally preserve the original ALNS+Roulette+RRT default.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite, log, sqrt
from typing import Any
import hashlib

import numpy as np

from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.task_objective import (
    LATENESS_TOL, ENERGY_EQUALITY_TOL_J, better_task_key,
)

from .evaluator import solution_signature
from .state import UavMecState


def _quality(state: UavMecState) -> tuple[float, ...]:
    """Read the screened evaluator's exact cached tuple, never an uncached proxy.

    Calling objective() first ensures the candidate underwent the *same*
    proxy/precheck/CVX screening used in the baseline scalar ALNS arm.
    """
    state.objective()
    evaluator = state.evaluator
    getter = getattr(evaluator, "quality_key", None)
    if not callable(getter):
        raise TypeError("Unit-aware ALNS requires a quality_key-enabled evaluator")
    key = tuple(float(x) for x in getter(state.instance, state.solution))
    if len(key) != 5 or any(not isfinite(x) for x in key):
        raise ValueError("Invalid or incomplete task-QoS quality tuple")
    return key


class TaskQoSRecordToRecord:
    """Allow a diminishing *Joule* and lateness excursion around the best.

    Priorities:
      - Never accept a physically unqualified candidate.
      - Never exchange on-time tasks for lower energy.
      - Always admit strict lexicographic progress in success or lateness.
      - For the same task success tier, allow temporary energy deterioration
        in Joules and small normalized-lateness excursions during exploration.

    Unlike RRT.autofit, allowances do not depend on the numerical magnitude
    of the library's composite scalar objective.
    """

    def __init__(
        self, *,
        iterations: int,
        start_energy_rel: float = 0.08,
        end_energy_rel: float = 0.0,
        start_lateness: float = 0.01,
        end_lateness: float = 0.0,
    ):
        if iterations <= 0:
            raise ValueError("iterations must be positive")
        if not 0.0 <= end_energy_rel <= start_energy_rel < 1.0:
            raise ValueError("Invalid relative energy excursion")
        if not 0.0 <= end_lateness <= start_lateness:
            raise ValueError("Invalid normalized-lateness excursion")
        self.iterations = int(iterations)
        self.start_energy_rel = float(start_energy_rel)
        self.end_energy_rel = float(end_energy_rel)
        self.start_lateness = float(start_lateness)
        self.end_lateness = float(end_lateness)
        self.calls = 0
        self.decisions: list[dict[str, Any]] = []

    def __call__(self, rng, best: UavMecState,
                 current: UavMecState, candidate: UavMecState) -> bool:
        del rng, current
        best_key, candidate_key = _quality(best), _quality(candidate)
        progress = min(1.0, self.calls / self.iterations)
        energy_fraction = (
            self.start_energy_rel
            + (self.end_energy_rel - self.start_energy_rel) * progress
        )
        lateness_budget = (
            self.start_lateness
            + (self.end_lateness - self.start_lateness) * progress
        )
        self.calls += 1

        # Physical feasibility is a hard gate regardless of energy or
        # QoS. The initial best may be proxy-infeasible; only a recovered,
        # verified candidate can be accepted by the new criterion.
        if candidate_key[0] != 0.0:
            accepted, reason = False, "physical_candidate_rejected"
        elif best_key[0] != 0.0:
            accepted, reason = True, "first_physical_feasible"
        elif candidate_key[1] > best_key[1]:
            accepted, reason = False, "success_count_protected"
        elif candidate_key[1] < best_key[1]:
            accepted, reason = True, "more_on_time_tasks"
        elif candidate_key[2] < best_key[2] - LATENESS_TOL:
            accepted, reason = True, "less_normalized_lateness"
        elif candidate_key[2] > best_key[2] + lateness_budget + LATENESS_TOL:
            accepted, reason = False, "lateness_excursion_exceeded"
        else:
            # Absolute threshold expressed in real Joules, keyed to the
            # current audited/approximated best energy, not a bounded score.
            energy_allow_j = (
                max(ENERGY_EQUALITY_TOL_J, best_key[3] * energy_fraction)
            )
            accepted = candidate_key[3] <= best_key[3] + energy_allow_j
            reason = ("within_physical_energy_budget" if accepted
                      else "energy_excursion_exceeded")
        self.decisions.append({
            "call": self.calls,
            "accepted": bool(accepted),
            "reason": reason,
            "best_on_time": int(-best_key[1]),
            "candidate_on_time": int(-candidate_key[1]),
            "best_lateness": best_key[2],
            "candidate_lateness": candidate_key[2],
            "best_energy_j": best_key[3],
            "candidate_energy_j": candidate_key[3],
            "energy_allowance_rel": energy_fraction,
            "lateness_allowance": lateness_budget,
        })
        return bool(accepted)


class UnitCreditBandit:
    """Destroy–repair pair UCB with physical-unit rewards and novelty credit.

    The ALNS library invokes __call__ before destruction and update after
    candidate scoring/outcome classification. Reward evaluates the candidate
    relative to pre-move current/best using cached task QoS tuples:
    success > normalized lateness > real Joules > novelty.

    Rewards are bounded in [0, 1], so operators are not rewarded simply
    because a scalar changes units or has a large constant task-count offset.
    The UCB term explores little-used operator pairs with coupled feasibility.
    """

    def __init__(
        self, *,
        num_destroy: int, num_repair: int, op_coupling,
        destroy_names: list[str], repair_names: list[str],
        exploration: float = 0.28,
        novelty_bonus: float = 0.05,
        diagnostic_trace: bool = False,
    ):
        coupling = np.asarray(op_coupling, dtype=bool)
        if coupling.shape != (num_destroy, num_repair):
            raise ValueError("Operator coupling shape mismatch")
        if len(destroy_names) != num_destroy or len(repair_names) != num_repair:
            raise ValueError("Operator name mismatch")
        if not np.any(coupling):
            raise ValueError("No enabled destroy/repair pairing")
        if exploration < 0 or not 0 <= novelty_bonus <= 0.25:
            raise ValueError("Invalid UCB reward parameters")
        self.pairs = [tuple(map(int, p)) for p in np.argwhere(coupling)]
        self.destroy_names = list(destroy_names)
        self.repair_names = list(repair_names)
        self.exploration = float(exploration)
        self.novelty_bonus = float(novelty_bonus)
        self.counts = {p: 0 for p in self.pairs}
        self.total_reward = {p: 0.0 for p in self.pairs}
        self._last_current: tuple[float, ...] | None = None
        self._last_best: tuple[float, ...] | None = None
        self._seen: set[tuple] = set()
        self._pair_counts: dict[str, list[int]] = {}
        self.trace: list[dict[str, Any]] = []
        self.credit_history: list[dict[str, Any]] = []
        self.diagnostic_trace = bool(diagnostic_trace)
        self.total_picks = 0

    @property
    def pair_counts(self) -> dict[str, list[int]]:
        return {key: list(counts) for key, counts in self._pair_counts.items()}

    def __call__(self, rng, best: UavMecState, curr: UavMecState):
        self._last_best = _quality(best)
        self._last_current = _quality(curr)
        self._seen.add(solution_signature(best.solution))
        self._seen.add(solution_signature(curr.solution))
        # Cover every allowed pairing once before exploiting the credit
        # estimate. This is a deterministic seeded policy, not a bug fix
        # or retroactive choice based on the final energy.
        untried = [p for p in self.pairs if self.counts[p] == 0]
        if untried:
            chosen = untried[int(rng.integers(len(untried)))]
        else:
            log_total = log(1.0 + sum(self.counts.values()))
            utilities = [
                self.total_reward[p] / self.counts[p]
                + self.exploration * sqrt(log_total / self.counts[p])
                for p in self.pairs
            ]
            maximum = max(utilities)
            tied = [p for p, value in zip(self.pairs, utilities)
                    if abs(value - maximum) <= 1e-12]
            chosen = tied[int(rng.integers(len(tied)))]
        self.total_picks += 1
        return chosen

    def update(self, cand: UavMecState, d_idx: int, r_idx: int, outcome) -> None:
        pair = (int(d_idx), int(r_idx))
        if pair not in self.counts:
            raise ValueError("ALNS attempted a disabled operator pair")
        if self._last_best is None or self._last_current is None:
            raise RuntimeError("Credit update before selecting an operator pair")
        candidate_quality = _quality(cand)
        signature = solution_signature(cand.solution)
        novel = signature not in self._seen
        self._seen.add(signature)
        outcome_index = int(outcome)
        if outcome_index not in (0, 1, 2, 3):
            raise ValueError("Unknown ALNS operator reward outcome")
        key = f"{self.destroy_names[d_idx]} -> {self.repair_names[r_idx]}"
        self._pair_counts.setdefault(key, [0, 0, 0, 0])[outcome_index] += 1

        if candidate_quality[0] != 0:
            credit = 0.0
            label = "physical_reject"
        elif self._last_best[0] != 0:
            credit, label = 1.0, "physical_recovery"
        elif candidate_quality[1] < self._last_best[1]:
            credit, label = 1.0, "success_improvement"
        elif (candidate_quality[1] == self._last_best[1]
              and candidate_quality[2] < self._last_best[2] - LATENESS_TOL):
            credit, label = 0.85, "lateness_improvement"
        elif (candidate_quality[1] == self._last_best[1]
              and abs(candidate_quality[2] - self._last_best[2]) <= LATENESS_TOL
              and candidate_quality[3] < self._last_best[3] - ENERGY_EQUALITY_TOL_J):
            # Actual Joule improvement, not bounded objective points.
            saving = (self._last_best[3] - candidate_quality[3]) / max(1.0, self._last_best[3])
            credit, label = 0.55 + min(0.25, 5 * saving), "energy_improvement"
        elif better_task_key(candidate_quality, self._last_current):
            credit, label = 0.40, "current_improvement"
        elif outcome_index != 3:
            credit, label = 0.10, "diversification_accepted"
        else:
            credit, label = 0.0, "rejected"
        if novel and candidate_quality[0] == 0:
            credit = min(1.0, credit + self.novelty_bonus)
        self.counts[pair] += 1
        self.total_reward[pair] += credit
        event = {
            "iteration": self.total_picks,
            "destroy": self.destroy_names[d_idx],
            "repair": self.repair_names[r_idx],
            "outcome_index": outcome_index,
            "credit": float(credit),
            "credit_reason": label,
            "novel": novel,
        }
        self.credit_history.append(event)
        if self.diagnostic_trace:
            info = build_event_info(cand.instance, cand.solution)
            raw = repr(signature).encode("utf-8")
            self.trace.append({
                **event,
                "candidate_score": float(cand.objective()),
                "candidate_structure_sha256": hashlib.sha256(raw).hexdigest(),
                "candidate_distance_m": float(sum(info.route_distance_m.values())),
                "candidate_contact_visits": len(cand.solution.contact_visits),
                "candidate_quality": [float(x) for x in candidate_quality],
            })
