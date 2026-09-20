from __future__ import annotations

import math

from uav_mec.domain import DiscreteSolution, Instance

from .geometry import distance


def signal_gain(instance: Instance, solution: DiscreteSolution, visit_id: str) -> float:
    visit = solution.contact_visits[visit_id]
    point = instance.contact_points[visit.point_id]
    mec = instance.mecs[point.mec_id]
    uav = instance.uavs[visit.uav_id]
    horizontal = distance((point.x, point.y), (mec.x, mec.y))
    d3d = math.sqrt(horizontal * horizontal + uav.altitude_m * uav.altitude_m)
    beta0 = 10.0 ** (instance.reference_gain_db / 10.0)
    return beta0 / (d3d ** instance.pathloss_exp)


def noise_psd_w_per_hz(instance: Instance) -> float:
    return 10.0 ** ((instance.noise_psd_dbm_per_hz - 30.0) / 10.0)


def gamma_mhz(instance: Instance, solution: DiscreteSolution, visit_id: str) -> float:
    visit = solution.contact_visits[visit_id]
    uav = instance.uavs[visit.uav_id]
    gamma_hz = uav.tx_power_w * signal_gain(instance, solution, visit_id) / noise_psd_w_per_hz(instance)
    return gamma_hz / 1e6
