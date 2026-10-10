"""Opt-in P0 behavioral checks; frozen develop defaults remain unchanged."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from uav_mec.algorithms.alns import problem_operators as ops
from uav_mec.algorithms.alns.problem_operators import (
    ProblemOperatorConfig,
    _choose_elite_route_options,
    _structural_elite_candidates,
)
from uav_mec.domain import Route, RouteStop, TaskDecision
from uav_mec.instances.small import build_small_instance


def _option(uav_id: str, position: int):
    return SimpleNamespace(uav_id=uav_id, position=position)


def test_p0_default_flags_off_and_original_top_two_unchanged():
    config = ProblemOperatorConfig()
    assert not config.elite_diversify_route_uavs
    assert config.elite_route_shortlist_quota == 0
    options = [
        _option("U1", 2), _option("U1", 3),
        _option("U2", 1), _option("U3", 1),
    ]
    assert _choose_elite_route_options(
        options,
        original_uav="U1",
        original_position=2,
        originally_local=True,
        limit=2,
        diversify_uavs=False,
    ) == options[:2]


def test_p0_opt_in_keeps_one_alternative_and_cross_uav():
    options = [
        _option("U1", 2),  # true no-op for a local task
        _option("U1", 3),
        _option("U1", 4),
        _option("U2", 1),
        _option("U3", 1),
    ]
    chosen = _choose_elite_route_options(
        options,
        original_uav="U1",
        original_position=2,
        originally_local=True,
        limit=2,
        diversify_uavs=True,
    )
    assert [(x.uav_id, x.position) for x in chosen] == [
        ("U1", 3), ("U2", 1),
    ]


def test_p0_opt_in_does_not_discard_offloaded_original_position():
    options = [_option("U1", 2), _option("U2", 1)]
    chosen = _choose_elite_route_options(
        options,
        original_uav="U1",
        original_position=2,
        originally_local=False,
        limit=2,
        diversify_uavs=True,
    )
    assert chosen == options


def test_p0_route_quota_controls_expensive_shortlist(monkeypatch):
    instance, baseline = build_small_instance()
    state = SimpleNamespace(instance=instance, solution=baseline)

    route1 = deepcopy(baseline)
    route1.metadata["p0_rank"] = 1
    route1.routes["U1"] = Route("U1", (
        RouteStop.depot(), RouteStop.task("S2"),
        RouteStop.task("S1"), RouteStop.contact("V11"),
        RouteStop.task("S3"), RouteStop.depot(),
    ))
    route2 = deepcopy(baseline)
    route2.metadata["p0_rank"] = 2
    route2.routes["U1"] = Route("U1", (
        RouteStop.depot(), RouteStop.task("S3"),
        RouteStop.task("S1"), RouteStop.task("S2"),
        RouteStop.contact("V11"), RouteStop.depot(),
    ))
    route3 = deepcopy(baseline)
    route3.metadata["p0_rank"] = 3
    route3.routes["U1"] = Route("U1", (
        RouteStop.depot(), RouteStop.task("S1"),
        RouteStop.task("S2"), RouteStop.task("S3"),
        RouteStop.contact("V11"), RouteStop.depot(),
    ))
    mode = deepcopy(baseline)
    mode.metadata["p0_rank"] = 4
    mode.task_decisions["S1"] = TaskDecision.local()

    monkeypatch.setattr(ops, "_route_compute_relocate_candidates",
        lambda state, config: [
            ("route_compute_relocate::one", route1),
            ("route_compute_relocate::two", route2),
            ("route_compute_relocate::three", route3),
        ])
    monkeypatch.setattr(ops, "_critical_tasks_for_mode_move",
        lambda state, limit: [])
    monkeypatch.setattr(ops, "_best_mode_batch_move",
        lambda state, config: mode)
    monkeypatch.setattr(ops, "_proxy_precheck_key",
        lambda state, solution: (solution.metadata["p0_rank"],))

    config = ProblemOperatorConfig(
        elite_shortlist_limit=2,
        elite_family_quota=1,
        elite_enable_contact_relocate=False,
        elite_enable_batch_merge=False,
        elite_enable_contact_remove=False,
        elite_enable_batch_split=False,
        elite_enable_contact_point_replace=False,
        elite_enable_mode_batch_reassign=True,
    )
    baseline_trace = {}
    base = _structural_elite_candidates(
        state, config=config, trace=baseline_trace,
    )
    assert [label for label, _ in base] == [
        "route_compute_relocate::one", "task_mode_or_batch_reassign",
    ]
    assert baseline_trace["raw_candidates"] == 4
    assert baseline_trace["shortlist_by_family"] == {"route": 1, "mode_batch": 1}

    p0_trace = {}
    p0 = _structural_elite_candidates(
        state, config=replace(config, elite_route_shortlist_quota=2),
        trace=p0_trace,
    )
    assert [label for label, _ in p0] == [
        "route_compute_relocate::one", "route_compute_relocate::two",
    ]
    assert p0_trace["shortlist_by_family"] == {"route": 2}
