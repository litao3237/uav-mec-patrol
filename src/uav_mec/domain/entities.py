from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Tuple


@dataclass(frozen=True)
class Task:
    task_id: str
    x: float
    y: float
    data_mb: float
    cycles_per_bit: float
    release_s: float
    deadline_s: float
    collect_s: float = 1.0

    @property
    def data_mbit(self) -> float:
        return 8.0 * self.data_mb

    @property
    def workload_gcycles(self) -> float:
        return self.data_mb * 8.0e-3 * self.cycles_per_bit


@dataclass(frozen=True)
class MEC:
    mec_id: str
    x: float
    y: float
    bandwidth_mhz: float
    cpu_ghz: float
    radius_m: float


@dataclass(frozen=True)
class UAV:
    uav_id: str
    speed_mps: float
    local_cpu_ghz: float
    tx_power_w: float
    flight_power_w: float
    hover_power_w: float
    energy_budget_j: float
    altitude_m: float = 30.0
    kappa: float = 1e-27


@dataclass(frozen=True)
class ContactPoint:
    """Candidate physical point inside one MEC coverage region.

    Contact points belong to the instance, not to a UAV. A concrete UAV visit is
    represented by ContactVisit in domain.solution.
    """

    point_id: str
    mec_id: str
    x: float
    y: float



@dataclass(frozen=True)
class RotorPowerParameters:
    """One explicitly declared rotor/airframe profile in SI units.

    Rotor parameters for the E1 scenario are *later literature calibration*
    of Zeng et al.'s rotary-wing equation, not Table I of the original paper.
    No speed optimization, extra take-off energy, or turn/acceleration model.
    """
    profile_power_w: float
    induced_power_w: float
    blade_tip_speed_mps: float
    mean_induced_velocity_mps: float
    fuselage_drag_ratio: float
    air_density_kg_m3: float
    rotor_solidity: float
    rotor_disc_area_m2: float

    def __post_init__(self) -> None:
        values = (
            self.profile_power_w, self.induced_power_w,
            self.blade_tip_speed_mps, self.mean_induced_velocity_mps,
            self.air_density_kg_m3, self.rotor_solidity, self.rotor_disc_area_m2,
        )
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Rotary-wing profile requires finite positive physical parameters")
        if not math.isfinite(self.fuselage_drag_ratio) or self.fuselage_drag_ratio < 0:
            raise ValueError("Fuselage drag ratio must be finite and nonnegative")


@dataclass
class Instance:
    depot_xy: Tuple[float, float]
    tasks: Dict[str, Task]
    mecs: Dict[str, MEC]
    uavs: Dict[str, UAV]
    contact_points: Dict[str, ContactPoint]
    cycle_s: float
    avg_delay_budget_s: float
    max_contacts_per_uav: int = 3
    reference_gain_db: float = -50.0
    pathloss_exp: float = 2.3
    noise_psd_dbm_per_hz: float = -164.0
    # Opt-in protocol: deadline/mean-delay are reported as task-level QoS, not constraints.
    # Default preserves the archived strict experimental formulation.
    qos_hard: bool = True
    # Opt-in fixed-speed, fly-hover-communicate rotor propulsion profile.
    # The archived fixed-power instance keeps these as the exact defaults.
    propulsion_model: str = "fixed"
    rotor_parameters: RotorPowerParameters | None = None
