"""Tests for the v27 timeliness model (independent of the archived v25 code)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from uav_mec.v27 import Structure, evaluate, generate_instance, load_params
from uav_mec.v27.audit import audit
from uav_mec.v27.dvfs import solve_dvfs
from uav_mec.v27.instance import ContactPoint, Instance, Station, Task
from uav_mec.v27.offload_search import optimize_offloading
from uav_mec.v27.physics import (
    coverage_radius_m, hover_power_w, flight_power_w, rate_mbps, rotor_power_w, snr_coefficient_mhz,
)
from uav_mec.v27.routing import sweep_routes

CFG = Path(__file__).resolve().parents[1] / "configs" / "v27_timeliness.yaml"


@pytest.fixture(scope="module")
def params():
    return load_params(CFG)


def _tiny(params, tasks: dict[str, Task], *, uavs: int = 1) -> Instance:
    st = Station("E1", *params.depot_xy, 10.0, 20.0, 600.0)
    st2 = Station("E2", 1000.0, 300.0, 10.0, 10.0, 600.0)
    pts = {
        "E1_C": ContactPoint("E1_C", "E1", *params.depot_xy, snr_coefficient_mhz(params, 0.0)),
        "E2_C": ContactPoint("E2_C", "E2", 1000.0, 300.0, snr_coefficient_mhz(params, 0.0)),
    }
    return Instance(params, tasks, {"E1": st, "E2": st2}, pts, "E1_C", uavs)


def _task(tid, x, y, *, w=10.0, data=20.0, fresh=200.0, onboard=True, kind="light"):
    return Task(tid, kind, x, y, data, w, 2.0, fresh, 1.0, onboard)


# --- physics -----------------------------------------------------------------

def test_zeng_hover_and_cruise_power(params):
    assert hover_power_w(params) == pytest.approx(79.86 + 88.63, rel=1e-9)
    assert flight_power_w(params) == pytest.approx(126.0, abs=0.1)
    # cruising at 10 m/s needs less power than hovering for a rotary-wing UAV
    assert rotor_power_w(params.rotor, 10.0) < rotor_power_w(params.rotor, 0.0)


def test_coverage_radius_meets_min_rate(params):
    r = coverage_radius_m(params, 10.0)
    assert 0 < r <= params.max_radius_m
    assert rate_mbps(10.0, snr_coefficient_mhz(params, r)) == pytest.approx(params.min_rate_mbps, rel=1e-6)


# --- DVFS subproblem ---------------------------------------------------------

def test_single_task_cube_root_rule():
    a, mu, kappa, w = 1e-3, 1e-6, 1.875, 10.0
    res = solve_dvfs([0.0], [w], [a], mu=mu, kappa=kappa, f_min=0.1, f_max=5.0, battery_residual=1e9)
    f_star = (a / (2 * mu * kappa)) ** (1 / 3)
    assert res.freq[0] == pytest.approx(min(f_star, 5.0), rel=1e-4)


def test_no_energy_price_uses_fmax():
    res = solve_dvfs([0.0, 1.0], [4.0, 4.0], [1.0, 1.0], mu=0.0, kappa=1.0, f_min=0.5, f_max=2.0,
                     battery_residual=1e9)
    assert np.allclose(res.freq, 2.0)
    assert res.finish[1] == pytest.approx(4.0)        # FIFO: waits for task 1


def test_battery_binding_lowers_frequency():
    w = np.array([10.0, 10.0])
    free = solve_dvfs([0, 0], w, [1, 1], mu=0.0, kappa=1.0, f_min=0.2, f_max=2.0, battery_residual=1e9)
    budget = 0.5 * free.energy_j
    tight = solve_dvfs([0, 0], w, [1, 1], mu=0.0, kappa=1.0, f_min=0.2, f_max=2.0,
                       battery_residual=budget)
    assert tight.energy_j <= budget * (1 + 1e-6)
    assert np.all(tight.freq < 2.0)


def test_battery_infeasible_reported():
    res = solve_dvfs([0.0], [100.0], [1.0], mu=0.0, kappa=1.0, f_min=1.0, f_max=2.0, battery_residual=1.0)
    assert res.status == "infeasible_battery"


def test_empty_dvfs_still_checks_battery():
    # 没有本地任务时计算能耗为 0，但剩余电量为负说明飞行与悬停已超出电池，仍须判为不可行
    ok = solve_dvfs([], [], [], mu=0.0, kappa=1.0, f_min=0.5, f_max=2.0, battery_residual=0.0)
    assert ok.status == "empty"
    bad = solve_dvfs([], [], [], mu=0.0, kappa=1.0, f_min=0.5, f_max=2.0, battery_residual=-1.0)
    assert bad.status == "infeasible_battery"
    assert bad.objective == np.inf


def test_dvfs_matches_cvxpy_when_available():
    cp = pytest.importorskip("cvxpy")
    t = np.array([0.0, 3.0, 4.0, 20.0])
    w = np.array([6.0, 8.0, 2.0, 5.0])
    a = np.array([1e-3, 2e-3, 1e-3, 5e-4])
    mu, kappa, fmin, fmax, B = 2e-6, 1.875, 0.3, 2.0, 1e9
    res = solve_dvfs(t, w, a, mu=mu, kappa=kappa, f_min=fmin, f_max=fmax, battery_residual=B)
    p = cp.Variable(4)
    c = cp.Variable(4)
    cons = [p >= w / fmax, p <= w / fmin, c >= t + p, kappa * cp.sum(cp.multiply(w**3, cp.power(p, -2))) <= B]
    cons += [c[k] >= c[k - 1] + p[k] for k in range(1, 4)]
    prob = cp.Problem(cp.Minimize(a @ c + mu * kappa * cp.sum(cp.multiply(w**3, cp.power(p, -2)))), cons)
    prob.solve()
    assert res.objective == pytest.approx(prob.value, rel=1e-5)


# --- timeline / structure ----------------------------------------------------

def test_aoi_is_measured_from_collection(params):
    p = params.with_overrides(energy_weight=0.0)
    inst = _tiny(p, {"A": _task("A", 300.0, 1300.0, w=10.0)})
    ev = evaluate(inst, Structure(routes={"U1": ["A"]}))
    # flight time does not count against freshness: AoI = w / f_max only
    assert ev.aoi["A"] == pytest.approx(10.0 / p.cpu_max_gcps, rel=1e-6)
    assert ev.timeline.collect_done["A"] == pytest.approx(1000.0 / p.speed_mps + 2.0)


def test_tdma_station_serves_fcfs(params):
    tasks = {"A": _task("A", 300.0, 400.0, data=200.0), "B": _task("B", 300.0, 400.0, data=200.0)}
    inst = _tiny(params, tasks, uavs=2)
    d = Structure(routes={"U1": ["A", "V1"], "U2": ["B", "V2"]},
                  visits={"V1": "E1_C", "V2": "E1_C"}, upload={"A": "V1", "B": "V2"})
    ev = evaluate(inst, d)
    ups = sorted(ev.timeline.uploads, key=lambda u: u.start)
    assert ups[1].start == pytest.approx(ups[0].end)       # second UAV waits, full band each
    assert audit(inst, d, ev) == []


def test_battery_checked_without_local_tasks(params):
    # 全部卸载的无人机没有机载计算，飞行与悬停能耗超出电池时 evaluate 与独立审计都应拒绝
    p = params.with_overrides(battery_j=1000.0)
    inst = _tiny(p, {"A": _task("A", 300.0, 1300.0)})
    d = Structure(routes={"U1": ["A", "V1"]}, visits={"V1": "E1_C"}, upload={"A": "V1"})
    ev = evaluate(inst, d)
    assert not ev.feasible
    assert "UAV U1 exceeds battery" in ev.reasons
    assert ev.key()[0] == 1
    assert any("battery exceeded" in e for e in audit(inst, d, ev))


def test_structure_violations(params):
    tasks = {"A": _task("A", 500.0, 500.0), "H": _task("H", 600.0, 600.0, onboard=False, kind="heavy")}
    inst = _tiny(params, tasks)
    d = Structure(routes={"U1": ["V1", "A", "H"]}, visits={"V1": "E2_C"}, upload={"A": "V1"})
    msgs = " | ".join(d.violations(inst))
    assert "uploaded before collection" in msgs
    assert "cannot run onboard" in msgs


# --- end-to-end + audit ------------------------------------------------------

def test_generated_instance_and_audit_clean(params):
    inst = generate_instance(params, num_tasks=12, num_uavs=2, seed=7)
    d = Structure(routes=sweep_routes(inst))
    ev = evaluate(inst, d)
    assert ev.feasible
    assert audit(inst, d, ev) == []
    res = optimize_offloading(inst, d, max_passes=2)
    assert res.evaluation.key() <= ev.key()
    assert audit(inst, res.structure, res.evaluation) == []


def test_audit_detects_tampering(params):
    inst = generate_instance(params, num_tasks=8, num_uavs=2, seed=3)
    d = Structure(routes=sweep_routes(inst))
    ev = evaluate(inst, d)
    t = next(iter(inst.tasks))
    ev.completion[t] -= 1.0
    assert audit(inst, d, ev)


def test_deadlines_do_not_depend_on_mission_start(params):
    inst = generate_instance(params, num_tasks=40, seed=11)
    for task in inst.tasks.values():
        cls = params.heavy if task.kind == "heavy" else params.light
        assert cls.freshness_s[0] <= task.freshness_s <= cls.freshness_s[1]
        assert math.isfinite(task.workload_gc) and task.workload_gc > 0
