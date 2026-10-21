"""Fixed-speed rotary-wing propulsion versus archived constant-power baseline.

Reference: Zeng, Xu and Zhang, IEEE TWC 2019,
Energy Minimization for Wireless Communication with Rotary-Wing UAV,
DOI 10.1109/TWC.2019.2902559 (rotary-wing power equation).

The explicit E1 *example parameter set* comes from later studies and must
not be attributed to Zeng's original numerical Table I. The numerical model
does not cover takeoff, landing, acceleration, sharp turns or vertical motion.
"""
from __future__ import annotations

from functools import lru_cache
import math

from uav_mec.domain import Instance, RotorPowerParameters, UAV


@lru_cache(maxsize=512)
def rotor_propulsion_power_w(speed_mps: float, params: RotorPowerParameters) -> float:
    """Rotary forward-flight power in W. Hover is P(0) = P0 + Pi.

    P(v) = P0 * (1 + 3v²/Utip²)
         + Pi * sqrt(sqrt(1 + v⁴/(4v0⁴)) - v²/(2v0²))
         + 0.5*d0*rho*s*A*v³.

    The induced term is evaluated via algebraic rationalization to avoid
    cancellation at high v: sqrt(sqrt(1+x²)-x) = 1/sqrt(hypot(1,x)+x).
    """
    v = float(speed_mps)
    if not math.isfinite(v) or v < 0:
        raise ValueError("Rotor forward speed must be finite and nonnegative")
    x = v * v / (2 * params.mean_induced_velocity_mps ** 2)
    profile = params.profile_power_w * (1.0 + 3.0 * v * v / params.blade_tip_speed_mps ** 2)
    induced = params.induced_power_w / math.sqrt(math.hypot(1.0, x) + x)
    parasite = (0.5 * params.fuselage_drag_ratio * params.air_density_kg_m3
                * params.rotor_solidity * params.rotor_disc_area_m2 * v ** 3)
    power = profile + induced + parasite
    if not math.isfinite(power) or power <= 0:
        raise ValueError("Rotor power must be finite positive")
    return power


def propulsion_powers_w(instance: Instance, uav: UAV) -> tuple[float, float]:
    """Return (flight, stationary hover) W, preserving fixed-mode bitwise math."""
    if instance.propulsion_model == "fixed":
        if instance.rotor_parameters is not None:
            raise ValueError("Fixed model must not have rotor parameters")
        return uav.flight_power_w, uav.hover_power_w
    if instance.propulsion_model != "rotary_fixed_speed":
        raise ValueError(f"Unknown propulsion model {instance.propulsion_model!r}")
    if instance.rotor_parameters is None:
        raise ValueError("Missing explicit rotor parameters")
    return (
        rotor_propulsion_power_w(uav.speed_mps, instance.rotor_parameters),
        rotor_propulsion_power_w(0.0, instance.rotor_parameters),
    )


def flight_power_w(instance: Instance, uav: UAV) -> float:
    return propulsion_powers_w(instance, uav)[0]


def hover_power_w(instance: Instance, uav: UAV) -> float:
    return propulsion_powers_w(instance, uav)[1]


def energy_for_distance_j(instance: Instance, uav: UAV, distance_m: float) -> float:
    if not math.isfinite(distance_m) or distance_m < 0:
        raise ValueError("Flight distance must be finite and nonnegative")
    if uav.speed_mps <= 0:
        raise ValueError("Flight speed must be positive")
    return flight_power_w(instance, uav) * (distance_m / uav.speed_mps)
