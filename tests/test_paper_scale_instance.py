from __future__ import annotations

from uav_mec.evaluation.geometry import distance
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def test_paper_scale_generation_is_reproducible() -> None:
    cfg = load_paper_scale_config()
    a = build_paper_scale_instance(cfg, scenario_seed=123)
    b = build_paper_scale_instance(cfg, scenario_seed=123)

    assert a.tasks == b.tasks
    assert a.mecs == b.mecs
    assert a.uavs == b.uavs
    assert a.contact_points == b.contact_points


def test_different_seed_changes_tasks_not_fixed_infrastructure() -> None:
    cfg = load_paper_scale_config()
    a = build_paper_scale_instance(cfg, scenario_seed=123)
    b = build_paper_scale_instance(cfg, scenario_seed=124)

    assert a.tasks != b.tasks
    assert a.mecs == b.mecs
    assert a.contact_points == b.contact_points


def test_baseline_counts_and_parameter_ranges() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(cfg)

    assert len(instance.tasks) == 50
    assert len(instance.uavs) == 5
    assert len(instance.mecs) == 3
    assert len(instance.contact_points) > len(instance.mecs)

    for task in instance.tasks.values():
        assert 1.0 <= task.data_mb <= 4.0
        assert 800.0 <= task.cycles_per_bit <= 1200.0
        assert task.release_s == 0.0
        assert task.deadline_s > 0.0

    assert instance.mecs["E1"].bandwidth_mhz == 4.0
    assert instance.mecs["E2"].cpu_ghz == 6.5
    assert instance.mecs["E3"].radius_m == 400.0


def test_contact_candidates_stay_inside_forest_and_mec_coverage() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(cfg)

    for point in instance.contact_points.values():
        mec = instance.mecs[point.mec_id]
        assert 0.0 <= point.x <= cfg.width_m
        assert 0.0 <= point.y <= cfg.height_m
        assert distance((point.x, point.y), (mec.x, mec.y)) <= mec.radius_m + 1e-9


def test_scale_overrides_support_planned_sweeps() -> None:
    cfg = load_paper_scale_config()
    instance = build_paper_scale_instance(
        cfg,
        num_tasks=80,
        num_uavs=8,
        num_mecs=4,
        scenario_seed=9,
    )

    assert len(instance.tasks) == 80
    assert len(instance.uavs) == 8
    assert len(instance.mecs) == 4


def test_mec_count_sweep_keeps_task_realization_fixed() -> None:
    cfg = load_paper_scale_config()
    instances = [
        build_paper_scale_instance(
            cfg,
            num_tasks=100,
            num_mecs=num_mecs,
            scenario_seed=45,
        )
        for num_mecs in (2, 3, 4)
    ]

    reference = instances[0].tasks
    assert instances[1].tasks == reference
    assert instances[2].tasks == reference

    assert tuple(instances[1].mecs)[:2] == tuple(instances[0].mecs)
    assert tuple(instances[2].mecs)[:3] == tuple(instances[1].mecs)


def test_uav_count_sweep_keeps_task_and_mec_realization_fixed() -> None:
    cfg = load_paper_scale_config()
    instances = [
        build_paper_scale_instance(
            cfg,
            num_tasks=80,
            num_uavs=num_uavs,
            num_mecs=2,
            scenario_seed=45,
        )
        for num_uavs in (3, 5, 8)
    ]

    reference_tasks = instances[0].tasks
    reference_mecs = instances[0].mecs
    reference_contacts = instances[0].contact_points

    assert instances[1].tasks == reference_tasks
    assert instances[2].tasks == reference_tasks
    assert instances[1].mecs == reference_mecs
    assert instances[2].mecs == reference_mecs
    assert instances[1].contact_points == reference_contacts
    assert instances[2].contact_points == reference_contacts

    # UAVs are homogeneous, so increasing M only appends additional UAV IDs.
    assert tuple(instances[1].uavs)[:3] == tuple(instances[0].uavs)
    assert tuple(instances[2].uavs)[:5] == tuple(instances[1].uavs)
