from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any, Mapping

from uav_mec.domain import ContactPoint, Instance, MEC, Task, UAV
from uav_mec.evaluation.geometry import distance

from .config import load_yaml

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class RealCaseBuild:
    instance: Instance
    metadata: dict[str, Any]


def _pair(values: Any, *, name: str) -> tuple[float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        raise ValueError(f"{name} must contain exactly two values")
    return float(values[0]), float(values[1])


def _local_xy(
    lat: float,
    lon: float,
    *,
    lat0: float,
    lon0: float,
) -> tuple[float, float]:
    """Local tangent-plane approximation, accurate for the 4 km study AOI."""

    x = (
        EARTH_RADIUS_M
        * math.radians(lon - lon0)
        * math.cos(math.radians(lat0))
    )
    y = EARTH_RADIUS_M * math.radians(lat - lat0)
    return x, y


def _select_fire_points(
    snapshot: Mapping[str, Any],
    *,
    depot_lat: float,
    depot_lon: float,
    task_radius_km: float,
    num_tasks: int,
) -> list[dict[str, Any]]:
    candidates = [
        dict(item)
        for item in snapshot.get("fire_occurrences", [])
        if float(item["distance_from_depot_m"])
        <= task_radius_km * 1000.0 + 1e-9
    ]
    # Deduplicate near-identical coordinates while preserving the latest-first
    # ordering emitted by the scout.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for item in candidates:
        key = (
            round(float(item["latitude"]) * 1_000_000),
            round(float(item["longitude"]) * 1_000_000),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(
        key=lambda item: (
            -(int(item["fire_year"]) if item.get("fire_year") else 0),
            float(item["distance_from_depot_m"]),
            int(item["objectid"]) if item.get("objectid") else 0,
        )
    )
    if len(unique) < num_tasks:
        raise ValueError(
            f"Need {num_tasks} unique real fire points within "
            f"{task_radius_km:g} km, found {len(unique)}"
        )
    return unique[:num_tasks]


def _contact_points(
    mecs: Mapping[str, MEC],
    *,
    ring_fractions: tuple[float, ...],
    points_per_ring: int,
    include_center: bool,
) -> dict[str, ContactPoint]:
    points: dict[str, ContactPoint] = {}
    for mec_id, mec in mecs.items():
        if include_center:
            points[f"{mec_id}_C"] = ContactPoint(
                f"{mec_id}_C", mec_id, mec.x, mec.y
            )
        ring_idx = 0
        for fraction in ring_fractions:
            if fraction <= 0.0:
                continue
            ring_idx += 1
            radius = fraction * mec.radius_m
            offset = (
                (ring_idx % 2) * math.pi / points_per_ring
            )
            for j in range(points_per_ring):
                angle = (
                    2.0 * math.pi * j / points_per_ring + offset
                )
                pid = f"{mec_id}_R{ring_idx}_A{j:02d}"
                points[pid] = ContactPoint(
                    pid,
                    mec_id,
                    mec.x + radius * math.cos(angle),
                    mec.y + radius * math.sin(angle),
                )
    return points


def build_stanislaus_real_instance(
    snapshot_path: str | Path,
    *,
    config_path: str | Path = "configs/real_stanislaus.yaml",
    num_tasks: int | None = None,
    num_uavs: int | None = None,
    scenario_seed: int | None = None,
) -> RealCaseBuild:
    cfg = load_yaml(config_path)
    case = cfg["case"]
    uav_cfg = cfg["uav"]
    task_cfg = cfg["task"]
    contact_cfg = cfg["contact"]
    channel_cfg = cfg["channel"]
    experiment_cfg = cfg["experiment"]

    snapshot = json.loads(
        Path(snapshot_path).read_text(encoding="utf-8")
    )

    depot = case["depot"]
    depot_lat = float(depot["latitude"])
    depot_lon = float(depot["longitude"])
    task_radius_km = float(case["task_radius_km"])
    k = int(case["num_tasks"] if num_tasks is None else num_tasks)
    m = int(case["num_uavs"] if num_uavs is None else num_uavs)
    seed = int(
        experiment_cfg["scenario_seed"]
        if scenario_seed is None
        else scenario_seed
    )

    selected = _select_fire_points(
        snapshot,
        depot_lat=depot_lat,
        depot_lon=depot_lon,
        task_radius_km=task_radius_km,
        num_tasks=k,
    )

    depot_raw = _local_xy(
        depot_lat,
        depot_lon,
        lat0=depot_lat,
        lon0=depot_lon,
    )
    fire_raw = [
        _local_xy(
            float(item["latitude"]),
            float(item["longitude"]),
            lat0=depot_lat,
            lon0=depot_lon,
        )
        for item in selected
    ]

    mec_specs = cfg["mec"]["sites"]
    if len(mec_specs) < 2:
        raise ValueError("real_stanislaus requires at least two MEC sites")
    mec_raw = [
        _local_xy(
            float(spec["latitude"]),
            float(spec["longitude"]),
            lat0=depot_lat,
            lon0=depot_lon,
        )
        for spec in mec_specs
    ]

    max_radius = max(float(spec["radius_m"]) for spec in mec_specs)
    xs = [depot_raw[0], *(p[0] for p in fire_raw), *(p[0] for p in mec_raw)]
    ys = [depot_raw[1], *(p[1] for p in fire_raw), *(p[1] for p in mec_raw)]
    padding = max_radius + 50.0
    shift_x = -min(xs) + padding
    shift_y = -min(ys) + padding

    def shifted(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] + shift_x, point[1] + shift_y

    depot_xy = shifted(depot_raw)

    mecs: dict[str, MEC] = {}
    mec_meta: list[dict[str, Any]] = []
    for idx, (spec, raw_xy) in enumerate(
        zip(mec_specs, mec_raw, strict=True),
        start=1,
    ):
        x, y = shifted(raw_xy)
        mec_id = f"E{idx}"
        mecs[mec_id] = MEC(
            mec_id=mec_id,
            x=x,
            y=y,
            bandwidth_mhz=float(spec["bandwidth_mhz"]),
            cpu_ghz=float(spec["cpu_ghz"]),
            radius_m=float(spec["radius_m"]),
        )
        mec_meta.append(
            {
                "mec_id": mec_id,
                "name": str(spec["name"]),
                "role": str(spec.get("role", "")),
                "latitude": float(spec["latitude"]),
                "longitude": float(spec["longitude"]),
                "x_m": x,
                "y_m": y,
            }
        )

    uavs = {
        f"U{idx}": UAV(
            uav_id=f"U{idx}",
            speed_mps=float(uav_cfg["speed_mps"]),
            local_cpu_ghz=float(uav_cfg["local_cpu_ghz"]),
            tx_power_w=float(uav_cfg["tx_power_w"]),
            flight_power_w=float(uav_cfg["flight_power_w"]),
            hover_power_w=float(uav_cfg["hover_power_w"]),
            energy_budget_j=float(uav_cfg["energy_budget_j"]),
            altitude_m=float(uav_cfg["altitude_m"]),
            kappa=float(uav_cfg["kappa"]),
        )
        for idx in range(1, m + 1)
    }

    rng = Random(seed)
    data_lo, data_hi = _pair(
        task_cfg["data_mb_range"],
        name="task.data_mb_range",
    )
    cpb_lo, cpb_hi = _pair(
        task_cfg["cycles_per_bit_range"],
        name="task.cycles_per_bit_range",
    )
    deadline_lo, deadline_hi = _pair(
        task_cfg["deadline_ratio_range"],
        name="task.deadline_ratio_range",
    )
    cycle_s = float(case["cycle_s"])
    collect_s = float(task_cfg["collect_s"])
    deadline_lb_factor = float(task_cfg["deadline_lb_factor"])
    fastest_cpu = max(
        [float(uav_cfg["local_cpu_ghz"])]
        + [float(spec["cpu_ghz"]) for spec in mec_specs]
    )

    tasks: dict[str, Task] = {}
    task_meta: list[dict[str, Any]] = []
    for idx, (source, raw_xy) in enumerate(
        zip(selected, fire_raw, strict=True),
        start=1,
    ):
        x, y = shifted(raw_xy)
        data_mb = rng.uniform(data_lo, data_hi)
        cycles_per_bit = rng.uniform(cpb_lo, cpb_hi)
        workload_gcycles = data_mb * 8.0e-3 * cycles_per_bit
        sampled_deadline = rng.uniform(
            deadline_lo * cycle_s,
            deadline_hi * cycle_s,
        )
        optimistic_lb = (
            distance(depot_xy, (x, y))
            / float(uav_cfg["speed_mps"])
            + collect_s
            + workload_gcycles / fastest_cpu
        )
        deadline_s = max(
            sampled_deadline,
            deadline_lb_factor * optimistic_lb,
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
            collect_s=collect_s,
        )
        task_meta.append(
            {
                "task_id": task_id,
                "fire_occurrence_objectid": source.get("objectid"),
                "fire_occurrence_id": source.get("fireoccurid"),
                "fire_name": source.get("fire_name"),
                "fire_year": source.get("fire_year"),
                "latitude": float(source["latitude"]),
                "longitude": float(source["longitude"]),
                "x_m": x,
                "y_m": y,
            }
        )

    contact_points = _contact_points(
        mecs,
        ring_fractions=tuple(
            float(value)
            for value in contact_cfg["ring_fractions"]
        ),
        points_per_ring=int(contact_cfg["points_per_ring"]),
        include_center=bool(contact_cfg["include_center"]),
    )

    instance = Instance(
        depot_xy=depot_xy,
        tasks=tasks,
        mecs=mecs,
        uavs=uavs,
        contact_points=contact_points,
        cycle_s=cycle_s,
        avg_delay_budget_s=float(case["avg_delay_budget_s"]),
        max_contacts_per_uav=int(case["max_contacts_per_uav"]),
        reference_gain_db=float(channel_cfg["reference_gain_db"]),
        pathloss_exp=float(channel_cfg["pathloss_exp"]),
        noise_psd_dbm_per_hz=float(
            channel_cfg["noise_psd_dbm_per_hz"]
        ),
    )

    all_x = [
        depot_xy[0],
        *(task.x for task in tasks.values()),
        *(mec.x for mec in mecs.values()),
    ]
    all_y = [
        depot_xy[1],
        *(task.y for task in tasks.values()),
        *(mec.y for mec in mecs.values()),
    ]
    metadata = {
        "case_name": str(case["name"]),
        "projection": (
            "local tangent-plane/equirectangular approximation centered "
            "at the Groveland Ranger District Office"
        ),
        "task_radius_km": task_radius_km,
        "num_source_fire_occurrences": len(
            snapshot.get("fire_occurrences", [])
        ),
        "num_selected_tasks": len(tasks),
        "depot": {
            "name": str(depot["name"]),
            "latitude": depot_lat,
            "longitude": depot_lon,
            "x_m": depot_xy[0],
            "y_m": depot_xy[1],
        },
        "mec_sites": mec_meta,
        "tasks": task_meta,
        "geometry_extent_m": {
            "width": max(all_x) - min(all_x),
            "height": max(all_y) - min(all_y),
        },
        "source_urls": snapshot.get("sources", {}),
        "interpretation": {
            "mec": (
                "edge servers are modeled at real facility locations; "
                "this does not claim deployed MEC hardware exists there"
            ),
            "tasks": (
                "historical USFS fire-occurrence coordinates are used as "
                "prospective monitoring-node locations"
            ),
        },
    }
    return RealCaseBuild(instance=instance, metadata=metadata)
