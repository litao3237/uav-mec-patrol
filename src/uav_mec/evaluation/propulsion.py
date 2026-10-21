"""Opt-in steady horizontal rotary propulsion formula of Zeng et al., 2019."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class RotorParameters:
    P0_w: float = 79.86
    Pi_w: float = 88.63
    tip_speed_mps: float = 120.0
    induced_speed_mps: float = 4.03
    drag_ratio: float = 0.6
    air_density_kg_m3: float = 1.225
    rotor_solidity: float = 0.05
    disk_area_m2: float = 0.503

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in asdict(self).values()):
            raise ValueError("Rotor parameters must be finite and positive")


def rotor_power_w(speed_mps: float, params: RotorParameters) -> float:
    if not math.isfinite(speed_mps) or speed_mps < 0:
        raise ValueError("Rotor velocity must be finite and nonnegative")
    v = float(speed_mps)
    a = v * v / (2.0 * params.induced_speed_mps ** 2)
    # sqrt(sqrt(1+a²)-a), rearranged for numerical stability
    induced = params.Pi_w / math.sqrt(math.hypot(1.0, a) + a)
    profile = params.P0_w * (1.0 + 3.0 * v * v / params.tip_speed_mps ** 2)
    parasite = (0.5 * params.drag_ratio * params.air_density_kg_m3
                * params.rotor_solidity * params.disk_area_m2 * v ** 3)
    power = profile + induced + parasite
    if not math.isfinite(power) or power <= 0:
        raise ValueError("Invalid rotor power")
    return power


def propulsion_power_w(uav, speed_mps: float) -> float:
    if uav.propulsion_model == "constant":
        return uav.hover_power_w if speed_mps == 0 else uav.flight_power_w
    if uav.propulsion_model == "rotor":
        return rotor_power_w(speed_mps, RotorParameters(**(uav.rotor_params or {})))
    raise ValueError(f"Unsupported propulsion model {uav.propulsion_model!r}")


def flight_power_w(uav) -> float:
    return propulsion_power_w(uav, uav.speed_mps)


def hover_power_w(uav) -> float:
    return propulsion_power_w(uav, 0.0)
