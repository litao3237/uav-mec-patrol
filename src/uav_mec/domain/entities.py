from __future__ import annotations

from dataclasses import dataclass
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
