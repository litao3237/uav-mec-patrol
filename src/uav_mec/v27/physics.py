"""Propulsion and channel physics for the v27 model."""

from __future__ import annotations

import math

from .params import ModelParams, RotorParams


def rotor_power_w(r: RotorParams, v: float) -> float:
    """Zeng, Xu, Zhang (IEEE TWC 2019): rotary-wing propulsion power.

    P(V) = P0 (1 + 3V^2/U_tip^2)
         + Pi (sqrt(1 + V^4/(4 v0^4)) - V^2/(2 v0^2))^{1/2}
         + 0.5 d0 rho s A V^3.
    Hover power is P(0) = P0 + Pi.
    """
    if v < 0:
        raise ValueError("speed must be nonnegative")
    v0 = r.induced_velocity_mps
    blade = r.profile_power_w * (1.0 + 3.0 * v * v / r.tip_speed_mps**2)
    inner = math.sqrt(1.0 + v**4 / (4.0 * v0**4)) - v * v / (2.0 * v0 * v0)
    induced = r.induced_power_w * math.sqrt(max(inner, 0.0))
    parasite = 0.5 * r.drag_ratio * r.air_density * r.solidity * r.disc_area_m2 * v**3
    return blade + induced + parasite


def flight_power_w(p: ModelParams) -> float:
    return rotor_power_w(p.rotor, p.speed_mps)


def hover_power_w(p: ModelParams) -> float:
    return rotor_power_w(p.rotor, 0.0)


def noise_psd_w_per_hz(p: ModelParams) -> float:
    return 10.0 ** ((p.noise_psd_dbm_per_hz - 30.0) / 10.0)


def snr_coefficient_mhz(p: ModelParams, horizontal_m: float) -> float:
    """gamma = P_tx * g / N0 expressed in MHz, so the SNR at bandwidth b (MHz) is gamma/b.

    g = beta0 / d^alpha with d the 3D UAV-station distance (LoS, as in the v25 model).
    """
    d3 = math.hypot(horizontal_m, p.altitude_m)
    beta0 = 10.0 ** (p.reference_gain_db / 10.0)
    gain = beta0 / d3**p.pathloss_exp
    return p.tx_power_w * gain / noise_psd_w_per_hz(p) / 1e6


def rate_mbps(bandwidth_mhz: float, gamma_mhz: float) -> float:
    if bandwidth_mhz <= 0 or gamma_mhz <= 0:
        raise ValueError("bandwidth and gamma must be positive")
    return bandwidth_mhz * math.log2(1.0 + gamma_mhz / bandwidth_mhz)


def coverage_radius_m(p: ModelParams, bandwidth_mhz: float) -> float:
    """Largest horizontal distance whose full-band rate is >= min_rate_mbps (capped)."""
    lo, hi = 0.0, p.max_radius_m
    if rate_mbps(bandwidth_mhz, snr_coefficient_mhz(p, hi)) >= p.min_rate_mbps:
        return hi
    if rate_mbps(bandwidth_mhz, snr_coefficient_mhz(p, lo)) < p.min_rate_mbps:
        raise ValueError("min_rate_mbps is unreachable even directly above the station")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if rate_mbps(bandwidth_mhz, snr_coefficient_mhz(p, mid)) >= p.min_rate_mbps:
            lo = mid
        else:
            hi = mid
    return lo
