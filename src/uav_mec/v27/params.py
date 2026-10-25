from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class RotorParams:
    profile_power_w: float
    induced_power_w: float
    tip_speed_mps: float
    induced_velocity_mps: float
    drag_ratio: float
    air_density: float
    solidity: float
    disc_area_m2: float


@dataclass(frozen=True)
class TaskClassParams:
    name: str
    data_mbit: tuple[float, float]
    cycles_per_bit: tuple[float, float]
    collect_s: float
    freshness_s: tuple[float, float]
    weight: float


@dataclass(frozen=True)
class SiteParams:
    name: str
    x: float
    y: float
    bandwidth_mhz: float
    cpu_gcps: float


@dataclass(frozen=True)
class ModelParams:
    width_m: float
    height_m: float
    depot_xy: tuple[float, float]
    num_tasks: int
    num_uavs: int
    max_contacts_per_uav: int
    task_margin_m: float
    heavy_fraction: float
    heavy_onboard_allowed: bool

    altitude_m: float
    speed_mps: float
    battery_j: float
    tx_power_w: float
    rotor: RotorParams
    cpu_max_gcps: float
    cpu_min_gcps: float
    cpu_power_at_max_w: float

    min_rate_mbps: float
    max_radius_m: float
    sites: tuple[SiteParams, ...]
    num_sites: int

    reference_gain_db: float
    pathloss_exp: float
    noise_psd_dbm_per_hz: float

    ring_fractions: tuple[float, ...]
    points_per_ring: int
    include_center: bool

    light: TaskClassParams
    heavy: TaskClassParams

    energy_weight: float
    scenario_seed: int

    @property
    def kappa_bar(self) -> float:
        """DVFS coefficient in W/(Gcycles/s)^3: power = kappa_bar * f^3."""
        return self.cpu_power_at_max_w / self.cpu_max_gcps**3

    def with_overrides(self, **kwargs: Any) -> "ModelParams":
        return replace(self, **kwargs)

    def validate(self) -> None:
        if self.num_tasks <= 0 or self.num_uavs <= 0:
            raise ValueError("num_tasks and num_uavs must be positive")
        if not 1 <= self.num_sites <= len(self.sites):
            raise ValueError("num_sites must be within the configured site list")
        if not 0.0 <= self.heavy_fraction <= 1.0:
            raise ValueError("heavy_fraction must lie in [0, 1]")
        if not 0.0 < self.cpu_min_gcps <= self.cpu_max_gcps:
            raise ValueError("cpu bounds must satisfy 0 < min <= max")
        if self.battery_j <= 0 or self.speed_mps <= 0 or self.altitude_m <= 0:
            raise ValueError("battery, speed and altitude must be positive")
        if self.energy_weight < 0:
            raise ValueError("energy_weight must be nonnegative")
        sx, sy = self.sites[0].x, self.sites[0].y
        if (sx, sy) != tuple(self.depot_xy):
            raise ValueError("the first site must be the depot station (terminal upload)")
        for cls in (self.light, self.heavy):
            for lo, hi in (cls.data_mbit, cls.cycles_per_bit, cls.freshness_s):
                if not 0 < lo <= hi:
                    raise ValueError(f"invalid range in task class {cls.name}")


def _pair(v: Any) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"expected a two-element range, got {v!r}")
    return float(v[0]), float(v[1])


def _task_class(name: str, d: Mapping[str, Any]) -> TaskClassParams:
    return TaskClassParams(
        name=name,
        data_mbit=_pair(d["data_mbit"]),
        cycles_per_bit=_pair(d["cycles_per_bit"]),
        collect_s=float(d["collect_s"]),
        freshness_s=_pair(d["freshness_s"]),
        weight=float(d["weight"]),
    )


def params_from_mapping(d: Mapping[str, Any]) -> ModelParams:
    sc, uav, mec, ch, ct, task = (
        d["scenario"], d["uav"], d["mec"], d["channel"], d["contact"], d["task"],
    )
    r = uav["rotor"]
    p = ModelParams(
        width_m=float(sc["width_m"]),
        height_m=float(sc["height_m"]),
        depot_xy=_pair(sc["depot_xy"]),
        num_tasks=int(sc["num_tasks"]),
        num_uavs=int(sc["num_uavs"]),
        max_contacts_per_uav=int(sc["max_contacts_per_uav"]),
        task_margin_m=float(sc["task_margin_m"]),
        heavy_fraction=float(sc["heavy_fraction"]),
        heavy_onboard_allowed=bool(sc["heavy_onboard_allowed"]),
        altitude_m=float(uav["altitude_m"]),
        speed_mps=float(uav["speed_mps"]),
        battery_j=float(uav["battery_j"]),
        tx_power_w=float(uav["tx_power_w"]),
        rotor=RotorParams(
            profile_power_w=float(r["profile_power_w"]),
            induced_power_w=float(r["induced_power_w"]),
            tip_speed_mps=float(r["tip_speed_mps"]),
            induced_velocity_mps=float(r["induced_velocity_mps"]),
            drag_ratio=float(r["drag_ratio"]),
            air_density=float(r["air_density"]),
            solidity=float(r["solidity"]),
            disc_area_m2=float(r["disc_area_m2"]),
        ),
        cpu_max_gcps=float(uav["cpu_max_gcps"]),
        cpu_min_gcps=float(uav["cpu_min_gcps"]),
        cpu_power_at_max_w=float(uav["cpu_power_at_max_w"]),
        min_rate_mbps=float(mec["min_rate_mbps"]),
        max_radius_m=float(mec["max_radius_m"]),
        sites=tuple(
            SiteParams(
                name=str(s["name"]), x=float(s["x"]), y=float(s["y"]),
                bandwidth_mhz=float(s["bandwidth_mhz"]), cpu_gcps=float(s["cpu_gcps"]),
            )
            for s in mec["sites"]
        ),
        num_sites=int(mec["num_sites"]),
        reference_gain_db=float(ch["reference_gain_db"]),
        pathloss_exp=float(ch["pathloss_exp"]),
        noise_psd_dbm_per_hz=float(ch["noise_psd_dbm_per_hz"]),
        ring_fractions=tuple(float(x) for x in ct["ring_fractions"]),
        points_per_ring=int(ct["points_per_ring"]),
        include_center=bool(ct["include_center"]),
        light=_task_class("light", task["light"]),
        heavy=_task_class("heavy", task["heavy"]),
        energy_weight=float(d["objective"]["energy_weight"]),
        scenario_seed=int(d["experiment"]["scenario_seed"]),
    )
    p.validate()
    return p


def load_params(path: str | Path = "configs/v27_timeliness.yaml") -> ModelParams:
    with Path(path).open("r", encoding="utf-8") as f:
        return params_from_mapping(yaml.safe_load(f))
