from __future__ import annotations

import math
from collections.abc import Mapping


def rate_mbps(bandwidth_mhz: float, gamma_mhz: float) -> float:
    if bandwidth_mhz <= 0.0:
        raise ValueError("bandwidth_mhz must be positive")
    if gamma_mhz < 0.0:
        raise ValueError("gamma_mhz must be nonnegative")
    return bandwidth_mhz * math.log2(1.0 + gamma_mhz / bandwidth_mhz)


def rate_prime(bandwidth_mhz: float, gamma_mhz: float) -> float:
    b = bandwidth_mhz
    g = gamma_mhz
    if b <= 0.0:
        raise ValueError("bandwidth_mhz must be positive")
    return (math.log(1.0 + g / b) - g / (b + g)) / math.log(2.0)


def upload_time_s(data_mbit: float, bandwidth_mhz: float, gamma_mhz: float) -> float:
    return data_mbit / rate_mbps(bandwidth_mhz, gamma_mhz)


def upload_time_prime(data_mbit: float, bandwidth_mhz: float, gamma_mhz: float) -> float:
    rate = rate_mbps(bandwidth_mhz, gamma_mhz)
    derivative = rate_prime(bandwidth_mhz, gamma_mhz)
    return -data_mbit * derivative / (rate * rate)


def local_cpu_from_shadow_price(
    gamma_complete: float,
    *,
    kappa_scaled: float,
    battery_price: float,
    max_cpu_ghz: float,
    min_cpu_ghz: float = 1e-4,
) -> float:
    """Closed-form DVFS allocation from the local-CPU KKT stationarity equation."""

    if gamma_complete <= 0.0:
        return min_cpu_ghz
    interior = (
        gamma_complete / (2.0 * (1.0 + battery_price) * kappa_scaled)
    ) ** (1.0 / 3.0)
    return min(max(interior, min_cpu_ghz), max_cpu_ghz)


def _pair_bandwidth_for_lambda(
    lambda_bandwidth: float,
    terms: list[tuple[float, float, float]],
    *,
    min_bandwidth_mhz: float,
    max_bandwidth_mhz: float,
    inner_iterations: int = 45,
) -> float:
    """Minimize one pair's Lagrangian term for a fixed bandwidth price.

    ``terms`` contains (phi, data_mbit, gamma_mhz) for every contact made by
    the same (UAV, MEC) pair.
    """

    def stationarity(b: float) -> float:
        return lambda_bandwidth + sum(
            phi * upload_time_prime(data, b, gamma)
            for phi, data, gamma in terms
        )

    lo = min_bandwidth_mhz
    hi = max(max_bandwidth_mhz, lo)
    if stationarity(lo) >= 0.0:
        return lo
    if stationarity(hi) <= 0.0:
        return hi

    for _ in range(inner_iterations):
        mid = 0.5 * (lo + hi)
        if stationarity(mid) <= 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def allocate_bandwidth_by_kkt(
    capacity_mhz: float,
    pair_terms: Mapping[tuple[str, str], list[tuple[float, float, float]]],
    *,
    min_bandwidth_mhz: float = 1e-3,
    outer_iterations: int = 45,
) -> tuple[dict[tuple[str, str], float], float]:
    """Allocate one MEC's bandwidth using KKT price bisection.

    Returns the pair allocations and the capacity shadow price ``lambda_B``.
    Since every upload has positive hover/transmit cost, useful MEC bandwidth is
    fully occupied unless only lower-bound allocations exist.
    """

    pairs = list(pair_terms)
    if not pairs:
        return {}, 0.0
    if len(pairs) * min_bandwidth_mhz > capacity_mhz + 1e-12:
        raise ValueError("Bandwidth lower bounds exceed MEC capacity")
    if len(pairs) == 1:
        return {pairs[0]: capacity_mhz}, max(
            0.0,
            -sum(
                phi * upload_time_prime(data, capacity_mhz, gamma)
                for phi, data, gamma in pair_terms[pairs[0]]
            ),
        )

    def allocations(price: float) -> dict[tuple[str, str], float]:
        return {
            pair: _pair_bandwidth_for_lambda(
                price,
                pair_terms[pair],
                min_bandwidth_mhz=min_bandwidth_mhz,
                max_bandwidth_mhz=capacity_mhz,
            )
            for pair in pairs
        }

    lo = 0.0
    hi = 1.0
    while sum(allocations(hi).values()) > capacity_mhz:
        hi *= 2.0
        if hi > 1e18:
            raise RuntimeError("Could not bracket bandwidth dual price")

    alloc: dict[tuple[str, str], float] = {}
    for _ in range(outer_iterations):
        mid = 0.5 * (lo + hi)
        alloc = allocations(mid)
        if sum(alloc.values()) > capacity_mhz:
            lo = mid
        else:
            hi = mid

    price = 0.5 * (lo + hi)
    alloc = allocations(price)
    total = sum(alloc.values())
    # Remove tiny numerical capacity slack without changing KKT structure.
    if total > 0.0 and abs(total - capacity_mhz) <= 1e-8 * max(1.0, capacity_mhz):
        scale = capacity_mhz / total
        alloc = {pair: value * scale for pair, value in alloc.items()}
    return alloc, price


def allocate_mec_cpu_by_kkt(
    capacity_ghz: float,
    xi_by_pair: Mapping[tuple[str, str], float],
    *,
    min_cpu_ghz: float = 1e-4,
    outer_iterations: int = 45,
) -> tuple[dict[tuple[str, str], float], float]:
    """Square-root KKT allocation for one MEC CPU capacity constraint."""

    pairs = list(xi_by_pair)
    if not pairs:
        return {}, 0.0
    if len(pairs) * min_cpu_ghz > capacity_ghz + 1e-12:
        raise ValueError("MEC CPU lower bounds exceed capacity")

    weights = {pair: max(0.0, float(xi_by_pair[pair])) for pair in pairs}
    if max(weights.values(), default=0.0) <= 1e-18:
        equal = capacity_ghz / len(pairs)
        return {pair: equal for pair in pairs}, 0.0

    def allocations(price: float) -> dict[tuple[str, str], float]:
        out: dict[tuple[str, str], float] = {}
        for pair, xi in weights.items():
            if xi <= 0.0:
                out[pair] = min_cpu_ghz
            else:
                out[pair] = max(min_cpu_ghz, math.sqrt(xi / price))
        return out

    lo = 1e-18
    hi = 1.0
    while sum(allocations(hi).values()) > capacity_ghz:
        hi *= 2.0
        if hi > 1e30:
            raise RuntimeError("Could not bracket MEC CPU dual price")

    alloc: dict[tuple[str, str], float] = {}
    for _ in range(outer_iterations):
        mid = 0.5 * (lo + hi)
        alloc = allocations(mid)
        if sum(alloc.values()) > capacity_ghz:
            lo = mid
        else:
            hi = mid

    price = 0.5 * (lo + hi)
    alloc = allocations(price)
    total = sum(alloc.values())
    if total > 0.0 and abs(total - capacity_ghz) <= 1e-8 * max(1.0, capacity_ghz):
        scale = capacity_ghz / total
        alloc = {pair: value * scale for pair, value in alloc.items()}
    return alloc, price
