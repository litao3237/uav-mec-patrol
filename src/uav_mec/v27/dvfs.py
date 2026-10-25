"""Per-UAV onboard DVFS subproblem (convex).

For UAV u with locally processed tasks k = 1..n in collection (FIFO) order,
collection times t_k, workloads w_k (Gcycles) and time prices a_k >= 0:

    min_{p, c}  sum_k a_k c_k + mu * kappa * sum_k w_k^3 / p_k^2
    s.t.        c_k >= t_k + p_k,  c_k >= c_{k-1} + p_k            (FIFO queue)
                w_k / f_max <= p_k <= w_k / f_min                  (p_k = w_k / f_k)
                kappa * sum_k w_k^3 / p_k^2 <= B                   (battery residual)

The objective is linear in c plus a separable convex function of p and all
constraints are linear except the convex battery sublevel set, so the problem
is convex. With p_k = w_k / f_k the compute energy is kappa * w_k * f_k^2 and
the single-task stationarity condition gives the cube-root rule
f* = (a / (2 mu kappa))^{1/3} projected onto [f_min, f_max], as in v25 Eq. (25).

Solved with SLSQP on (p, c) with analytic gradients; the returned schedule is
re-derived by the exact FIFO recursion so the reported times never depend on
solver slack.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass
class DvfsResult:
    freq: np.ndarray        # Gcycles/s
    start: np.ndarray
    finish: np.ndarray
    energy_j: float
    objective: float
    status: str


def fifo_schedule(t: np.ndarray, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    start = np.empty_like(t)
    finish = np.empty_like(t)
    prev = -np.inf
    for k in range(len(t)):
        start[k] = max(t[k], prev)
        finish[k] = start[k] + p[k]
        prev = finish[k]
    return start, finish


def solve_dvfs(t, w, a, *, mu: float, kappa: float, f_min: float, f_max: float,
               battery_residual: float) -> DvfsResult:
    t = np.asarray(t, float)
    w = np.asarray(w, float)
    a = np.asarray(a, float)
    n = len(t)
    if n == 0:
        # 没有本地任务时计算能耗为 0，但飞行、悬停与发射的固定能耗仍可能超出电池，必须同样判定，否则全部卸载的无人机会绕过电池约束
        if battery_residual < 0.0:
            return DvfsResult(np.zeros(0), np.zeros(0), np.zeros(0), 0.0, np.inf, "infeasible_battery")
        return DvfsResult(np.zeros(0), np.zeros(0), np.zeros(0), 0.0, 0.0, "empty")

    def energy(p):
        return float(kappa * np.sum(w**3 / p**2))

    p_lo, p_hi = w / f_max, w / f_min
    if energy(p_hi) > battery_residual * (1 + 1e-12):
        s, f = fifo_schedule(t, p_hi)
        return DvfsResult(w / p_hi, s, f, energy(p_hi), np.inf, "infeasible_battery")

    # Fast exact path: with no energy price, f_max is optimal whenever affordable.
    if mu == 0.0 and energy(p_lo) <= battery_residual:
        s, f = fifo_schedule(t, p_lo)
        return DvfsResult(w / p_lo, s, f, energy(p_lo), float(a @ f), "optimal_fmax")

    scale = 1.0 / max(np.max(a) * max(np.max(t), 1.0), 1e-12)

    def obj(x):
        p, c = x[:n], x[n:]
        return scale * (a @ c + mu * kappa * np.sum(w**3 / p**2))

    def obj_grad(x):
        p = x[:n]
        g = np.empty(2 * n)
        g[:n] = scale * (-2.0 * mu * kappa * w**3 / p**3)
        g[n:] = scale * a
        return g

    rows, rhs = [], []
    for k in range(n):
        r = np.zeros(2 * n); r[n + k] = 1.0; r[k] = -1.0
        rows.append(r); rhs.append(t[k])                          # c_k - p_k >= t_k
        if k > 0:
            r = np.zeros(2 * n); r[n + k] = 1.0; r[n + k - 1] = -1.0; r[k] = -1.0
            rows.append(r); rhs.append(0.0)                        # c_k - c_{k-1} - p_k >= 0
    A = np.array(rows)
    b = np.array(rhs)
    bscale = 1.0 / max(battery_residual, 1.0)
    cons = [
        {"type": "ineq", "fun": lambda x: A @ x - b, "jac": lambda x: A},
        {"type": "ineq",
         "fun": lambda x: bscale * (battery_residual - kappa * np.sum(w**3 / x[:n] ** 2)),
         "jac": lambda x: np.concatenate([bscale * 2.0 * kappa * w**3 / x[:n] ** 3, np.zeros(n)])},
    ]
    best = None
    for p0 in (p_lo, np.sqrt(p_lo * p_hi)):
        _, c0 = fifo_schedule(t, p0)
        bounds = [(lo, hi) for lo, hi in zip(p_lo, p_hi)] + [(None, None)] * n
        res = minimize(obj, np.concatenate([p0, c0]), jac=obj_grad, method="SLSQP",
                       bounds=bounds, constraints=cons,
                       options={"maxiter": 500, "ftol": 1e-12})
        p = np.clip(res.x[:n], p_lo, p_hi)
        if energy(p) > battery_residual:            # project back onto the battery set
            lam = (energy(p) / battery_residual) ** 0.5
            p = np.clip(p * lam, p_lo, p_hi)
        s, f = fifo_schedule(t, p)
        val = float(a @ f + mu * energy(p))
        if best is None or val < best[0]:
            best = (val, p, s, f, "optimal" if res.success else f"approx:{res.message}")
    val, p, s, f, status = best
    # Never worse than the trivially feasible f_max / f_min corners.
    for corner in (p_lo, p_hi):
        if energy(corner) <= battery_residual:
            cs, cf = fifo_schedule(t, corner)
            cv = float(a @ cf + mu * energy(corner))
            if cv < val - 1e-12:
                val, p, s, f, status = cv, corner, cs, cf, "corner"
    return DvfsResult(w / p, s, f, energy(p), val, status)
