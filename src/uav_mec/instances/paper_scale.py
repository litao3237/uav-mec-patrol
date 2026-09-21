from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from random import Random
from statistics import mean
from typing import Any, Mapping

from uav_mec.domain import ContactPoint, Instance, MEC, Task, UAV
from uav_mec.evaluation.geometry import distance

from .config import load_yaml


@dataclass(frozen=True)
class MECSpec:
    x: float
    y: float
    bandwidth_mhz: float
    cpu_ghz: float
    radius_m: float


@dataclass(frozen=True)
class PaperScaleConfig:
    """Configuration for reproducible paper-scale forest instances.

    The numerical defaults live in configs/baseline.yaml. This dataclass
    separates scenario generation from the later route/offloading algorithm so
    experiments can vary K/M/E without mutating solver code.
    """

    width_m: float
    height_m: float
    num_tasks: int
    num_uavs: int
    num_mecs: int
    depot_xy: tuple[float, float]
    cycle_s: float
    avg_delay_budget_s: float
    max_contacts_per_uav: int

    uav_altitude_m: float
    uav_speed_mps: float
    uav_local_cpu_ghz: float
    uav_tx_power_w: float
    uav_flight_power_w: float
    uav_hover_power_w: float
    uav_energy_budget_j: float
    uav_kappa: float

    mec_sites: tuple[MECSpec, ...]

    task_data_mb_range: tuple[float, float]
    task_cycles_per_bit_range: tuple[float, float]
    task_deadline_ratio_range: tuple[float, float]
    task_collect_s: float
    task_margin_m: float
    deadline_lb_factor: float

    contact_ring_fractions: tuple[float, ...]
    contact_points_per_ring: int
    contact_include_center: bool

    reference_gain_db: float
    pathloss_exp: float
    noise_psd_dbm_per_hz: float

    scenario_seed: int
    algorithm_seed: int

    def with_scale(
        self,
        *,
        num_tasks: int | None = None,
        num_uavs: int | None = None,
        num_mecs: int | None = None,
        scenario_seed: int | None = None,
    ) -> "PaperScaleConfig":
        return replace(
            self,
            num_tasks=self.num_tasks if num_tasks is None else int(num_tasks),
            num_uavs=self.num_uavs if num_uavs is None else int(num_uavs),
            num_mecs=self.num_mecs if num_mecs is None else int(num_mecs),
            scenario_seed=self.scenario_seed if scenario_seed is None else int(scenario_seed),
        )


def _pair(values: Any, *, name: str) -> tuple[float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        raise ValueError(f"{name} must contain exactly two values")
    return float(values[0]), float(values[1])


def _mec_specs(section: Mapping[str, Any]) -> tuple[MECSpec, ...]:
    sites = section.get("sites")
    if not isinstance(sites, list) or not sites:
        raise ValueError("mec.sites must be a non-empty list")
    specs: list[MECSpec] = []
    for idx, raw in enumerate(sites, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"mec.sites[{idx}] must be a mapping")
        specs.append(
            MECSpec(
                x=float(raw["x"]),
                y=float(raw["y"]),
                bandwidth_mhz=float(raw["bandwidth_mhz"]),
                cpu_ghz=float(raw["cpu_ghz"]),
                radius_m=float(raw["radius_m"]),
            )
        )
    return tuple(specs)


def paper_scale_config_from_mapping(data: Mapping[str, Any]) -> PaperScaleConfig:
    scenario = data["scenario"]
    uav = data["uav"]
    mec = data["mec"]
    task = data["task"]
    contact = data["contact"]
    channel = data["channel"]
    experiment = data["experiment"]

    return PaperScaleConfig(
        width_m=float(scenario["width_m"]),
        height_m=float(scenario["height_m"]),
        num_tasks=int(scenario["num_tasks"]),
        num_uavs=int(scenario["num_uavs"]),
        num_mecs=int(scenario["num_mecs"]),
        depot_xy=_pair(scenario["depot_xy"], name="scenario.depot_xy"),
        cycle_s=float(scenario["cycle_s"]),
        avg_delay_budget_s=float(scenario["avg_delay_budget_s"]),
        max_contacts_per_uav=int(scenario["max_contacts_per_uav"]),
        uav_altitude_m=float(uav["altitude_m"]),
        uav_speed_mps=float(uav["speed_mps"]),
        uav_local_cpu_ghz=float(uav["local_cpu_ghz"]),
        uav_tx_power_w=float(uav["tx_power_w"]),
        uav_flight_power_w=float(uav["flight_power_w"]),
        uav_hover_power_w=float(uav["hover_power_w"]),
        uav_energy_budget_j=float(uav["energy_budget_j"]),
        uav_kappa=float(uav["kappa"]),
        mec_sites=_mec_specs(mec),
        task_data_mb_range=_pair(task["data_mb_range"], name="task.data_mb_range"),
        task_cycles_per_bit_range=_pair(
            task["cycles_per_bit_range"],
            name="task.cycles_per_bit_range",
        ),
        task_deadline_ratio_range=_pair(
            task["deadline_ratio_range"],
            name="task.deadline_ratio_range",
        ),
        task_collect_s=float(task["collect_s"]),
        task_margin_m=float(task["margin_m"]),
        deadline_lb_factor=float(task["deadline_lb_factor"]),
        contact_ring_fractions=tuple(float(v) for v in contact["ring_fractions"]),
        contact_points_per_ring=int(contact["points_per_ring"]),
        contact_include_center=bool(contact["include_center"]),
        reference_gain_db=float(channel["reference_gain_db"]),
        pathloss_exp=float(channel["pathloss_exp"]),
        noise_psd_dbm_per_hz=float(channel["noise_psd_dbm_per_hz"]),
        scenario_seed=int(experiment["scenario_seed"]),
        algorithm_seed=int(experiment["algorithm_seed"]),
    )


def load_paper_scale_config(path: str | Path = "configs/baseline.yaml") -> PaperScaleConfig:
    return paper_scale_config_from_mapping(load_yaml(path))


def _validate_config(cfg: PaperScaleConfig) -> None:
    if cfg.width_m <= 0 or cfg.height_m <= 0:
        raise ValueError("Forest dimensions must be positive")
    if cfg.num_tasks <= 0 or cfg.num_uavs <= 0 or cfg.num_mecs <= 0:
        raise ValueError("num_tasks, num_uavs and num_mecs must be positive")
    if cfg.num_mecs > len(cfg.mec_sites):
        raise ValueError(
            f"Requested {cfg.num_mecs} MECs but only {len(cfg.mec_sites)} candidate sites are configured"
        )
    if cfg.task_margin_m < 0 or 2 * cfg.task_margin_m >= min(cfg.width_m, cfg.height_m):
        raise ValueError("task.margin_m leaves no valid task-generation region")
    if cfg.contact_points_per_ring <= 0:
        raise ValueError("contact.points_per_ring must be positive")
    if any(r < 0.0 or r > 1.0 for r in cfg.contact_ring_fractions):
        raise ValueError("contact.ring_fractions must lie in [0, 1]")
    lo, hi = cfg.task_deadline_ratio_range
    if not (0.0 < lo <= hi):
        raise ValueError("task.deadline_ratio_range must be positive and ordered")
    if cfg.avg_delay_budget_s <= 0 or cfg.cycle_s <= 0:
        raise ValueError("cycle and average-delay budgets must be positive")

    for idx, spec in enumerate(cfg.mec_sites[: cfg.num_mecs], start=1):
        if not (0.0 <= spec.x <= cfg.width_m and 0.0 <= spec.y <= cfg.height_m):
            raise ValueError(f"MEC site {idx} lies outside the forest rectangle")
        if min(spec.bandwidth_mhz, spec.cpu_ghz, spec.radius_m) <= 0.0:
            raise ValueError(f"MEC site {idx} has a non-positive resource/coverage parameter")


def _build_mecs(cfg: PaperScaleConfig) -> dict[str, MEC]:
    return {
        f"E{idx}": MEC(
            mec_id=f"E{idx}",
            x=spec.x,
            y=spec.y,
            bandwidth_mhz=spec.bandwidth_mhz,
            cpu_ghz=spec.cpu_ghz,
            radius_m=spec.radius_m,
        )
        for idx, spec in enumerate(cfg.mec_sites[: cfg.num_mecs], start=1)
    }


def _build_contact_points(
    cfg: PaperScaleConfig,
    mecs: Mapping[str, MEC],
) -> dict[str, ContactPoint]:
    """Discretize each continuous MEC coverage region into candidate contacts.

    Rings are deterministic and staggered by half an angular step. Points outside
    the forest rectangle are omitted rather than clipped, because clipping would
    distort both route distance and channel geometry.
    """

    points: dict[str, ContactPoint] = {}
    for mec_id, mec in mecs.items():
        seen: set[tuple[int, int]] = set()

        def add(point_id: str, x: float, y: float) -> None:
            if not (0.0 <= x <= cfg.width_m and 0.0 <= y <= cfg.height_m):
                return
            if distance((x, y), (mec.x, mec.y)) > mec.radius_m + 1e-9:
                return
            key = (round(x * 1e6), round(y * 1e6))
            if key in seen:
                return
            seen.add(key)
            points[point_id] = ContactPoint(point_id, mec_id, x, y)

        if cfg.contact_include_center:
            add(f"{mec_id}_C", mec.x, mec.y)

        ring_index = 0
        for fraction in cfg.contact_ring_fractions:
            if fraction <= 0.0:
                continue
            ring_index += 1
            radius = fraction * mec.radius_m
            offset = (ring_index % 2) * math.pi / cfg.contact_points_per_ring
            for j in range(cfg.contact_points_per_ring):
                angle = 2.0 * math.pi * j / cfg.contact_points_per_ring + offset
                add(
                    f"{mec_id}_R{ring_index}_A{j:02d}",
                    mec.x + radius * math.cos(angle),
                    mec.y + radius * math.sin(angle),
                )

        if not any(point.mec_id == mec_id for point in points.values()):
            raise ValueError(f"No valid candidate contact point generated for {mec_id}")
    return points


def _build_uavs(cfg: PaperScaleConfig) -> dict[str, UAV]:
    return {
        f"U{idx}": UAV(
            uav_id=f"U{idx}",
            speed_mps=cfg.uav_speed_mps,
            local_cpu_ghz=cfg.uav_local_cpu_ghz,
            tx_power_w=cfg.uav_tx_power_w,
            flight_power_w=cfg.uav_flight_power_w,
            hover_power_w=cfg.uav_hover_power_w,
            energy_budget_j=cfg.uav_energy_budget_j,
            altitude_m=cfg.uav_altitude_m,
            kappa=cfg.uav_kappa,
        )
        for idx in range(1, cfg.num_uavs + 1)
    }


def _individual_optimistic_deadline_lb(
    cfg: PaperScaleConfig,
    *,
    x: float,
    y: float,
    workload_gcycles: float,
) -> float:
    """Very optimistic task-only lower bound used only to avoid trivial deadlines."""

    direct_collect = (
        distance(cfg.depot_xy, (x, y)) / cfg.uav_speed_mps
        + cfg.task_collect_s
    )
    # Use the configured infrastructure envelope, not only the active MEC
    # subset. This keeps the task/deadline realization invariant when E is
    # varied in an MEC-count sensitivity experiment.
    fastest_cpu = max(
        [cfg.uav_local_cpu_ghz]
        + [spec.cpu_ghz for spec in cfg.mec_sites]
    )
    return direct_collect + workload_gcycles / fastest_cpu


def _build_tasks(
    cfg: PaperScaleConfig,
    rng: Random,
    mecs: Mapping[str, MEC],
) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    margin = cfg.task_margin_m
    data_lo, data_hi = cfg.task_data_mb_range
    cpb_lo, cpb_hi = cfg.task_cycles_per_bit_range
    deadline_lo, deadline_hi = cfg.task_deadline_ratio_range

    for idx in range(1, cfg.num_tasks + 1):
        x = rng.uniform(margin, cfg.width_m - margin)
        y = rng.uniform(margin, cfg.height_m - margin)
        data_mb = rng.uniform(data_lo, data_hi)
        cycles_per_bit = rng.uniform(cpb_lo, cpb_hi)
        workload_gcycles = data_mb * 8.0e-3 * cycles_per_bit

        sampled_deadline = rng.uniform(
            deadline_lo * cfg.cycle_s,
            deadline_hi * cfg.cycle_s,
        )
        optimistic_lb = _individual_optimistic_deadline_lb(
            cfg,
            x=x,
            y=y,
            workload_gcycles=workload_gcycles,
        )
        deadline_s = max(
            sampled_deadline,
            cfg.deadline_lb_factor * optimistic_lb,
        )

        task_id = f"S{idx}"
        tasks[task_id] = Task(
            task_id=task_id,
            x=x,
            y=y,
            data_mb=data_mb,
            cycles_per_bit=cycles_per_bit,
            release_s=0.0,
            deadline_s=deadline_s,
            collect_s=cfg.task_collect_s,
        )
    return tasks


def build_paper_scale_instance(
    config: PaperScaleConfig | None = None,
    *,
    config_path: str | Path = "configs/baseline.yaml",
    num_tasks: int | None = None,
    num_uavs: int | None = None,
    num_mecs: int | None = None,
    scenario_seed: int | None = None,
) -> Instance:
    cfg = config or load_paper_scale_config(config_path)
    cfg = cfg.with_scale(
        num_tasks=num_tasks,
        num_uavs=num_uavs,
        num_mecs=num_mecs,
        scenario_seed=scenario_seed,
    )
    _validate_config(cfg)

    rng = Random(cfg.scenario_seed)
    mecs = _build_mecs(cfg)
    contact_points = _build_contact_points(cfg, mecs)
    uavs = _build_uavs(cfg)
    tasks = _build_tasks(cfg, rng, mecs)

    return Instance(
        depot_xy=cfg.depot_xy,
        tasks=tasks,
        mecs=mecs,
        uavs=uavs,
        contact_points=contact_points,
        cycle_s=cfg.cycle_s,
        avg_delay_budget_s=cfg.avg_delay_budget_s,
        max_contacts_per_uav=cfg.max_contacts_per_uav,
        reference_gain_db=cfg.reference_gain_db,
        pathloss_exp=cfg.pathloss_exp,
        noise_psd_dbm_per_hz=cfg.noise_psd_dbm_per_hz,
    )


def summarize_paper_scale_instance(instance: Instance) -> dict[str, Any]:
    tasks = list(instance.tasks.values())
    contacts_per_mec = {
        mec_id: sum(
            1
            for point in instance.contact_points.values()
            if point.mec_id == mec_id
        )
        for mec_id in instance.mecs
    }
    workloads = [task.workload_gcycles for task in tasks]
    deadlines = [task.deadline_s for task in tasks]
    data = [task.data_mb for task in tasks]

    return {
        "num_tasks": len(instance.tasks),
        "num_uavs": len(instance.uavs),
        "num_mecs": len(instance.mecs),
        "num_contact_points": len(instance.contact_points),
        "contacts_per_mec": contacts_per_mec,
        "data_mb_min": min(data),
        "data_mb_mean": mean(data),
        "data_mb_max": max(data),
        "workload_gcycles_min": min(workloads),
        "workload_gcycles_mean": mean(workloads),
        "workload_gcycles_max": max(workloads),
        "deadline_s_min": min(deadlines),
        "deadline_s_mean": mean(deadlines),
        "deadline_s_max": max(deadlines),
        "cycle_s": instance.cycle_s,
        "avg_delay_budget_s": instance.avg_delay_budget_s,
    }
