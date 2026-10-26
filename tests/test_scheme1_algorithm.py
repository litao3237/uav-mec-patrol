"""方案一正式算法的单元测试：参数推导、精确停靠、时间价格下界、增量计算、加速等价与解的校验"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from uav_mec.scheme1 import (Instance, RouteEvaluator, SearchConfig, Task, base_only, exact_stops, held_karp,
                             lambda_dp, load_scheme1_params, make_instance, route_local_search, simulate, solve_fleet,
                             verify)
from uav_mec.scheme1.stops import lambda_dp_fly

SP = load_scheme1_params("configs/v27_timeliness.yaml")


def small_instance(seed: int, n: int, ring_points: int = 2) -> Instance:
    """小实例：每站圆心加 ring_points 个 0.85R 环上点，便于穷举"""
    sp = SP.with_overrides(ring_fractions=(0.85,), points_per_ring=ring_points)
    rng = random.Random(seed)
    tasks = [Task(i, rng.uniform(50, 2950), rng.uniform(50, 2950), rng.uniform(80, 160), rng.uniform(300, 600), 10.0)
             for i in range(n)]
    return Instance(sp, tasks)


def brute_force(inst: Instance, route: list[int], cap: float) -> float:
    """枚举全部停靠方案（中途停靠位置 × 上传点 × 最后一站上传点），用事件模拟求目标"""
    n, n_pts, best = len(route), len(inst.points), math.inf
    for r in range(n):
        for pos in itertools.combinations(range(1, n), r):
            for pts in itertools.product(range(n_pts), repeat=r):
                for fin in [-1] + list(range(n_pts)):
                    sim = simulate(inst, route, list(zip(pos, pts)) + [(n, fin)])
                    if sim.fly_s <= cap + 1e-9:
                        best = min(best, sim.objective)
    return best


def no_stop_fly(inst: Instance, route: list[int]) -> float:
    return inst.route_length_m(route) / inst.params.speed_mps


def test_params_derived_from_frozen_config():
    assert SP.p_fly_w == pytest.approx(126.0337, abs=1e-3)
    assert SP.p_hover_w == pytest.approx(168.49, abs=1e-6)
    assert [s[0] for s in SP.stations] == ["E1", "E2", "E3"]
    assert all(s[3] == pytest.approx(597.885, abs=1e-2) for s in SP.stations)
    assert len(Instance(SP, []).points) == 44


def test_held_karp_matches_enumeration():
    rng = random.Random(1)
    for _ in range(20):
        n = rng.randint(3, 7)
        pts = [(rng.uniform(0, 3000), rng.uniform(0, 3000)) for _ in range(n + 1)]
        dm = [[math.hypot(a[0] - b[0], a[1] - b[1]) for b in pts] for a in pts]
        _, length = held_karp(dm, n)
        brute = min(dm[0][p[0] + 1] + sum(dm[a + 1][b + 1] for a, b in zip(p, p[1:])) + dm[p[-1] + 1][0]
                    for p in itertools.permutations(range(n)))
        assert length == pytest.approx(brute, abs=1e-6)


@pytest.mark.parametrize("seed", range(6))
def test_exact_stops_match_brute_force_and_simulation(seed):
    inst = small_instance(seed, 4 + seed % 2, ring_points=1 if seed % 2 else 2)
    route = list(range(inst.n))
    for slack in (0.02, 0.15, 2.0):
        cap = no_stop_fly(inst, route) * (1 + slack)
        res = exact_stops(inst, route, cap)
        assert res[0] == pytest.approx(brute_force(inst, route, cap), abs=1e-9)
        sim = simulate(inst, route, list(res[2]))
        assert sim.objective == pytest.approx(res[0], abs=1e-9)
        assert sim.fly_s == pytest.approx(res[1], abs=1e-9)
        assert sim.fly_s <= cap + 1e-9


def test_lambda_bound_is_valid_and_consistent():
    rng = random.Random(3)
    for _ in range(15):
        inst = small_instance(rng.randint(0, 10 ** 6), rng.randint(5, 9))
        route = list(range(inst.n))
        rng.shuffle(route)
        cap = no_stop_fly(inst, route) * rng.uniform(1.0, 1.4)
        opt = exact_stops(inst, route, cap)[0]
        for lam in (0.0, 1e-4, 1e-3, 1e-2, 0.1):
            st = lambda_dp(inst, route, lam)
            assert st.value - lam * cap <= opt + 1e-9
            assert st.value == pytest.approx(lambda_dp_fly(inst, route, lam)[0], abs=1e-9)


def test_lambda_prefix_reuse_matches_full_computation():
    rng = random.Random(4)
    for _ in range(20):
        inst = small_instance(rng.randint(0, 10 ** 6), rng.randint(6, 10))
        base = list(range(inst.n))
        rng.shuffle(base)
        lam = rng.choice([1e-4, 3e-3, 2e-2])
        ref = lambda_dp(inst, base, lam)
        cut = rng.randint(1, inst.n - 2)
        tail = base[cut:]
        rng.shuffle(tail)
        cand = base[:cut] + tail
        assert lambda_dp(inst, cand, lam, reuse=ref).value == lambda_dp(inst, cand, lam).value


@pytest.mark.parametrize("seed", range(3))
def test_acceleration_gives_identical_route_search(seed):
    inst = small_instance(100 + seed, 9)
    start = list(range(inst.n))
    cap = no_stop_fly(inst, start) * 1.1
    out = {}
    for acc in (False, True):
        ev = RouteEvaluator(inst, lambda r, c=cap: c, accelerate=acc)
        out[acc] = route_local_search(ev, start, 800, random.Random(seed))
    (ra, va, ea, ca), (rb, vb, eb, cb) = out[False], out[True]
    assert ra == rb and va == vb and ea == eb and ca == cb


def test_acceleration_gives_identical_fleet_search_and_valid_solution():
    inst, groups = make_instance("sector", 18, 2, 7, SP)
    res = {acc: solve_fleet(inst, groups, 0.1, SearchConfig(accelerate=acc, inter_evals=600), tag=("t", acc is None))
           for acc in (False, True)}
    a, b = res[False], res[True]
    assert a.routes == b.routes and a.objective == b.objective
    assert a.stats["inter_evals"] == b.stats["inter_evals"] and a.stats["accepted"] == b.stats["accepted"]
    assert b.stats["exact"] < a.stats["exact"]
    chk = verify(inst, b)
    assert chk["assigned_once"] and chk["feasible"] and chk["max_obj_gap"] < 1e-9
    assert b.objective <= b.per_route + 1e-12 <= b.two_stage + 2e-12
    assert base_only(inst, groups) >= b.two_stage - 1e-9
