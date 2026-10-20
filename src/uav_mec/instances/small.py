from __future__ import annotations

from uav_mec.domain import (
    ContactPoint,
    ContactVisit,
    DiscreteSolution,
    Instance,
    MEC,
    Route,
    RouteStop,
    Task,
    TaskDecision,
    UAV,
)


def build_small_instance() -> tuple[Instance, DiscreteSolution]:
    """Deterministic K=5, M=2, E=2 validation instance."""

    tasks = {
        "S1": Task("S1", 200.0, 120.0, 2.0, 600.0, 0.0, 55.0),
        "S2": Task("S2", 320.0, 180.0, 1.5, 700.0, 0.0, 62.0),
        "S3": Task("S3", 600.0, 220.0, 1.0, 600.0, 0.0, 92.0),
        "S4": Task("S4", 150.0, 350.0, 1.2, 500.0, 0.0, 70.0),
        "S5": Task("S5", 280.0, 420.0, 2.5, 700.0, 0.0, 82.0),
    }

    mecs = {
        "E1": MEC("E1", 450.0, 300.0, 6.0, 12.0, 300.0),
        "E2": MEC("E2", 850.0, 800.0, 8.0, 16.0, 350.0),
    }

    uavs = {
        "U1": UAV("U1", 10.0, 1.20, 0.10, 180.0, 200.0, 30000.0),
        "U2": UAV("U2", 10.0, 1.00, 0.10, 180.0, 200.0, 30000.0),
    }

    contact_points = {
        "E1_P1": ContactPoint("E1_P1", "E1", 400.0, 200.0),
        "E1_P2": ContactPoint("E1_P2", "E1", 350.0, 350.0),
        "E1_P3": ContactPoint("E1_P3", "E1", 500.0, 420.0),
        "E2_P1": ContactPoint("E2_P1", "E2", 720.0, 700.0),
        "E2_P2": ContactPoint("E2_P2", "E2", 850.0, 600.0),
    }

    instance = Instance(
        depot_xy=(100.0, 100.0),
        tasks=tasks,
        mecs=mecs,
        uavs=uavs,
        contact_points=contact_points,
        cycle_s=130.0,
        avg_delay_budget_s=72.0,
        max_contacts_per_uav=3,
        reference_gain_db=-50.0,
        pathloss_exp=2.3,
        noise_psd_dbm_per_hz=-164.0,
    )

    visits = {
        "V11": ContactVisit("V11", "U1", "E1_P1"),
        "V21": ContactVisit("V21", "U2", "E1_P2"),
    }

    solution = DiscreteSolution(
        routes={
            "U1": Route(
                "U1",
                (
                    RouteStop.depot(),
                    RouteStop.task("S1"),
                    RouteStop.task("S2"),
                    RouteStop.contact("V11"),
                    RouteStop.task("S3"),
                    RouteStop.depot(),
                ),
            ),
            "U2": Route(
                "U2",
                (
                    RouteStop.depot(),
                    RouteStop.task("S4"),
                    RouteStop.task("S5"),
                    RouteStop.contact("V21"),
                    RouteStop.depot(),
                ),
            ),
        },
        contact_visits=visits,
        task_decisions={
            "S1": TaskDecision.offload("V11"),
            "S2": TaskDecision.offload("V11"),
            "S3": TaskDecision.local(),
            "S4": TaskDecision.local(),
            "S5": TaskDecision.offload("V21"),
        },
        metadata={"name": "small_validation"},
    )
    return instance, solution
