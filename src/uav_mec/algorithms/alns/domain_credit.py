"""M0.4: domain-conditioned ALNS operator reward, never domain-shaped objective.

Real flight power and route distance, MEC-associated deadline relief net of
upload hover/transmission overhead, and near-deadline pressure are additional
*selector feedback only*. The search objective, physical model, acceptance
criterion, candidate operators and final CVX recourse are unchanged.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from uav_mec.evaluation.task_objective import LATENESS_TOL
from .evaluator import solution_signature
from .quality_control import UnitCreditBandit, _quality
from .state import UavMecState


_COMPONENTS = frozenset({"flight", "mec", "deadline"})


def _clip(value: float, *, bound: float = 1.0) -> float:
    return max(-bound, min(bound, float(value)))


def _pressure(ratio: float, *, onset: float = 0.80) -> float:
    """Deadline risk grows only inside the last 20% of the time budget."""
    if not isfinite(ratio):
        raise ValueError("Non-finite completion/deadline ratio")
    return min(2.0, max(0.0, (ratio - onset) / (1.0 - onset)))


def domain_features(before: dict, after: dict) -> dict[str, float]:
    """Signed, capped proxy changes; positive is better, negative is worse.

    Flight: exact route-flight energy from UAV speed/power (not visit count).
    MEC: mean completion-ratio relief for *contact-associated* tasks, minus
    increased upload hover/tx burden. Only a proxy association, not a
    causal or exact CVX estimate of the benefit of adding one MEC contact.
    Deadline: deadline-risk relief near deadlines for all tasks, including
    currently on-time tasks. No explicit reward for more contact visits.
    """
    old_ratio, new_ratio = before["normalized_completion"], after["normalized_completion"]
    if set(old_ratio) != set(new_ratio):
        raise ValueError("Domain feedback must compare identical task cohort")
    if not old_ratio:
        raise ValueError("Domain feedback requires at least one task")
    for s in (before, after):
        if any(not isfinite(s[k]) or s[k] < 0 for k in
               ("flight_energy_j", "flight_distance_m", "upload_energy_j", "energy_j")):
            raise ValueError("Invalid cached proxy resource feature")
    # 8% change in physical flight energy saturates the route signal.
    delta_flight_j = before["flight_energy_j"] - after["flight_energy_j"]
    flight_fraction = delta_flight_j / max(1.0, before["flight_energy_j"])
    flight_signal = _clip(flight_fraction / 0.08)

    offloaded = set(before["offloaded_tasks"]) | set(after["offloaded_tasks"])
    if not offloaded.issubset(old_ratio):
        raise ValueError("Offloaded task IDs must belong to the common cohort")
    if offloaded:
        relief = sum(old_ratio[t] - new_ratio[t] for t in sorted(offloaded)) / len(offloaded)
        # The new contact must also pay real UAV transmission/hover burden.
        upload_cost_fraction = ((after["upload_energy_j"] - before["upload_energy_j"])
                                / max(1.0, before["energy_j"]))
        contact_signal = _clip(4.0 * relief - 3.0 * upload_cost_fraction)
    else:
        contact_signal = 0.0
        upload_cost_fraction = 0.0
        relief = 0.0

    pressure_old = sum(_pressure(v) for v in old_ratio.values()) / len(old_ratio)
    pressure_new = sum(_pressure(v) for v in new_ratio.values()) / len(new_ratio)
    # A reduction of .20 in mean near-deadline pressure saturates the signal.
    deadline_signal = _clip((pressure_old - pressure_new) / 0.20)
    return {
        "flight": flight_signal,
        "mec": contact_signal,
        "deadline": deadline_signal,
        "delta_flight_j": delta_flight_j,
        "delta_flight_m": before["flight_distance_m"] - after["flight_distance_m"],
        "delta_upload_energy_j": before["upload_energy_j"] - after["upload_energy_j"],
        "contact_associated_delay_ratio_relief": relief,
        "old_deadline_pressure": pressure_old,
        "new_deadline_pressure": pressure_new,
        "delta_deadline_pressure": pressure_old - pressure_new,
        "old_contacts": before["contact_visits"],
        "new_contacts": after["contact_visits"],
    }


class DomainAwareCreditBandit(UnitCreditBandit):
    """Selector reward correction on top of the frozen M0.3 UCB policy.

    Domain bonuses are allowed only when the candidate is physically feasible,
    keeps the best on-time cohort, does not regress normalized lateness, and
    stays within 1% of the previously visited state's energy. This prevents a
    shorter flight with a larger total UAV-energy bill (or lost successes)
    from receiving an unqualified positive route/contact bonus.
    """

    def __init__(
        self, *, components: tuple[str, ...] = ("flight", "mec", "deadline"),
        flight_weight: float = 0.18,
        mec_weight: float = 0.14,
        deadline_weight: float = 0.12,
        **kwargs,
    ):
        super().__init__(**kwargs)
        requested = tuple(components)
        if len(set(requested)) != len(requested) or not set(requested).issubset(_COMPONENTS):
            raise ValueError(f"Unsupported or duplicated domain components: {requested}")
        if not requested:
            raise ValueError("Use UnitCreditBandit for the unmodified reference")
        weights = {"flight": flight_weight, "mec": mec_weight, "deadline": deadline_weight}
        if any(not isfinite(x) or not 0 <= x <= 0.25 for x in weights.values()):
            raise ValueError("Domain weights must be finite, nonnegative and capped")
        self.components = requested
        self.weights = weights
        self._previous_domain: dict | None = None
        self.domain_history: list[dict[str, Any]] = []

    @staticmethod
    def _snapshot(state: UavMecState) -> dict:
        getter = getattr(state.evaluator, "domain_snapshot", None)
        if not callable(getter):
            raise TypeError("Domain credit requires a domain_snapshot-enabled evaluator")
        return getter(state.instance, state.solution)

    def __call__(self, rng, best: UavMecState, curr: UavMecState):
        pair = super().__call__(rng, best, curr)
        self._previous_domain = self._snapshot(curr)
        return pair

    def update(self, cand: UavMecState, d_idx: int, r_idx: int, outcome):
        if self._previous_domain is None:
            raise RuntimeError("Domain reward update without previous current state")
        old_domain = self._previous_domain
        original_best = self._last_best
        original_current = self._last_current
        # Preserve M0.3 UCB count, selection and reward sequence, then add a
        # bounded signed domain term to this one completed candidate.
        super().update(cand, d_idx, r_idx, outcome)
        candidate_quality = _quality(cand)
        after_domain = self._snapshot(cand)
        features = domain_features(old_domain, after_domain)
        eligible = bool(
            candidate_quality[0] == 0
            and original_best is not None
            and original_current is not None
            and candidate_quality[1] <= original_best[1]
            and candidate_quality[2] <= original_best[2] + LATENESS_TOL
        )
        # Under a large real-energy loss, do not reward a shorter path, a
        # speculative contact gain or deadline pressure as if it were a win.
        tolerable_energy = bool(
            original_current is not None
            and candidate_quality[3] <= original_current[3] * 1.01 + 1e-3
        )
        signed = sum(
            self.weights[k] * features[k] for k in self.components
        )
        if not eligible:
            signed = -0.15
        elif not tolerable_energy:
            signed = min(0.0, signed) - 0.10
        old_reward = float(self.credit_history[-1]["credit"])
        new_reward = _clip(old_reward + signed, bound=1.0)
        new_reward = max(0.0, new_reward)
        correction = new_reward - old_reward
        pair = (int(d_idx), int(r_idx))
        self.total_reward[pair] += correction
        self.credit_history[-1]["credit"] = new_reward
        self.credit_history[-1]["domain_signal"] = signed
        event = {
            "iteration": self.total_picks,
            "destroy": self.destroy_names[d_idx],
            "repair": self.repair_names[r_idx],
            "active_components": list(self.components),
            "base_credit": old_reward,
            "adjusted_credit": new_reward,
            "domain_signal": signed,
            "eligible": eligible,
            "energy_guard": tolerable_energy,
            **features,
        }
        self.domain_history.append(event)
        if self.diagnostic_trace:
            self.trace[-1]["credit"] = new_reward
            self.trace[-1]["domain_signal"] = signed
            self.trace[-1]["domain_features"] = features
        self._previous_domain = None
