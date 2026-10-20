from __future__ import annotations

import json

from uav_mec.instances import build_stanislaus_real_instance


def _snapshot(tmp_path):
    fires = []
    base_lat = 37.821982
    base_lon = -120.098763
    for idx in range(60):
        # Deterministic points inside a few kilometers of the depot.
        row = idx // 10
        col = idx % 10
        lat = base_lat + (row - 2.5) * 0.004
        lon = base_lon + (col - 4.5) * 0.004
        fires.append(
            {
                "objectid": idx + 1,
                "fireoccurid": f"F{idx+1}",
                "fire_name": f"Fire {idx+1}",
                "fire_year": 2025 - (idx // 12),
                "total_acres": 1.0,
                "stat_cause": "TEST",
                "latitude": lat,
                "longitude": lon,
                "distance_from_depot_m": 100.0 + idx * 20.0,
            }
        )
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "sources": {
                    "communications": "test",
                    "fire_occurrence": "test",
                },
                "fire_occurrences": fires,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_real_geography_geometry_is_fixed_across_scenario_seeds(
    tmp_path,
) -> None:
    snapshot = _snapshot(tmp_path)
    a = build_stanislaus_real_instance(
        snapshot,
        num_tasks=50,
        scenario_seed=45,
    )
    b = build_stanislaus_real_instance(
        snapshot,
        num_tasks=50,
        scenario_seed=46,
    )

    assert a.instance.depot_xy == b.instance.depot_xy
    assert a.instance.mecs == b.instance.mecs
    assert a.instance.contact_points == b.instance.contact_points
    assert {
        key: (task.x, task.y)
        for key, task in a.instance.tasks.items()
    } == {
        key: (task.x, task.y)
        for key, task in b.instance.tasks.items()
    }
    assert any(
        a.instance.tasks[key].data_mb != b.instance.tasks[key].data_mb
        for key in a.instance.tasks
    )


def test_real_geography_uses_two_real_facility_anchors(tmp_path) -> None:
    built = build_stanislaus_real_instance(
        _snapshot(tmp_path),
        num_tasks=50,
        scenario_seed=45,
    )

    assert len(built.instance.tasks) == 50
    assert len(built.instance.uavs) == 5
    assert len(built.instance.mecs) == 2
    assert built.metadata["mec_sites"][0]["name"] == (
        "Groveland Ranger District Office"
    )
    assert built.metadata["mec_sites"][1]["name"] == "Smith Peak Lookout"
