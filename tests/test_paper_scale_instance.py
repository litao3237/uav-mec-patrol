from __future__ import annotations

from dataclasses import replace

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


def test_mec_resource_and_radius_scaling_keep_tasks_fixed() -> None:
    cfg = load_paper_scale_config()
    scaled = replace(
        cfg,
        mec_sites=tuple(
            replace(
                spec,
                bandwidth_mhz=1.5 * spec.bandwidth_mhz,
                radius_m=0.75 * spec.radius_m,
            )
            for spec in cfg.mec_sites
        ),
    )

    base = build_paper_scale_instance(
        cfg,
        num_tasks=80,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=45,
    )
    changed = build_paper_scale_instance(
        scaled,
        num_tasks=80,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=45,
    )

    assert changed.tasks == base.tasks
    assert changed.uavs == base.uavs
    assert tuple(changed.mecs) == tuple(base.mecs)
    for mec_id in base.mecs:
        assert changed.mecs[mec_id].x == base.mecs[mec_id].x
        assert changed.mecs[mec_id].y == base.mecs[mec_id].y
        assert (
            changed.mecs[mec_id].bandwidth_mhz
            == 1.5 * base.mecs[mec_id].bandwidth_mhz
        )
        assert (
            changed.mecs[mec_id].radius_m
            == 0.75 * base.mecs[mec_id].radius_m
        )


def test_spatial_profiles_preserve_baseline_and_task_attribute_stream() -> None:
    cfg = load_paper_scale_config()
    default = build_paper_scale_instance(
        cfg,
        num_tasks=40,
        num_mecs=2,
        scenario_seed=45,
    )
    explicit_uniform = build_paper_scale_instance(
        cfg,
        num_tasks=40,
        num_mecs=2,
        scenario_seed=45,
        task_spatial_profile="uniform",
    )
    clustered = build_paper_scale_instance(
        cfg,
        num_tasks=40,
        num_mecs=2,
        scenario_seed=45,
        task_spatial_profile="clustered",
    )
    boundary = build_paper_scale_instance(
        cfg,
        num_tasks=40,
        num_mecs=2,
        scenario_seed=45,
        task_spatial_profile="boundary",
    )

    assert explicit_uniform == default
    assert clustered.mecs == default.mecs
    assert boundary.mecs == default.mecs
    assert clustered.uavs == default.uavs
    assert boundary.uavs == default.uavs
    assert clustered.contact_points == default.contact_points
    assert boundary.contact_points == default.contact_points

    assert clustered.tasks != default.tasks
    assert boundary.tasks != default.tasks

    for task_id, base_task in default.tasks.items():
        for variant in (clustered.tasks[task_id], boundary.tasks[task_id]):
            assert variant.data_mb == base_task.data_mb
            assert variant.cycles_per_bit == base_task.cycles_per_bit
            assert variant.collect_s == base_task.collect_s
            assert variant.release_s == base_task.release_s


def test_contact_budget_sweep_keeps_instance_realization_fixed() -> None:
    cfg = load_paper_scale_config()
    base = build_paper_scale_instance(
        replace(cfg, max_contacts_per_uav=3),
        num_tasks=80,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=45,
    )
    tight = build_paper_scale_instance(
        replace(cfg, max_contacts_per_uav=1),
        num_tasks=80,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=45,
    )
    loose = build_paper_scale_instance(
        replace(cfg, max_contacts_per_uav=4),
        num_tasks=80,
        num_uavs=5,
        num_mecs=2,
        scenario_seed=45,
    )

    assert tight.tasks == base.tasks == loose.tasks
    assert tight.mecs == base.mecs == loose.mecs
    assert tight.uavs == base.uavs == loose.uavs
    assert tight.contact_points == base.contact_points == loose.contact_points
    assert tight.max_contacts_per_uav == 1
    assert base.max_contacts_per_uav == 3
    assert loose.max_contacts_per_uav == 4
