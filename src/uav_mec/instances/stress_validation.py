from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from uav_mec.domain import ContactVisit, DiscreteSolution, Instance, Route, RouteStop, TaskDecision

from .small import build_small_instance


def _copy_base() -> tuple[Instance, DiscreteSolution]:
    instance, solution = build_small_instance()
    return deepcopy(instance), deepcopy(solution)


def build_resource_stress_cases() -> list[tuple[str, Instance, DiscreteSolution]]:
    cases: list[tuple[str, Instance, DiscreteSolution]] = []

    instance, solution = _copy_base()
    cases.append(("baseline", instance, solution))

    instance, solution = _copy_base()
    instance.mecs["E1"] = replace(instance.mecs["E1"], bandwidth_mhz=3.0)
    cases.append(("tight_bandwidth", instance, solution))

    instance, solution = _copy_base()
    instance.mecs["E1"] = replace(instance.mecs["E1"], cpu_ghz=1.2)
    cases.append(("tight_mec_cpu", instance, solution))

    instance, solution = _copy_base()
    instance.avg_delay_budget_s = 57.0
    cases.append(("tight_avg_delay", instance, solution))

    instance, solution = _copy_base()
    instance.tasks["S5"] = replace(instance.tasks["S5"], deadline_s=115.0)
    solution.routes["U2"] = Route(
        "U2",
        (
            RouteStop.depot(),
            RouteStop.task("S4"),
            RouteStop.task("S5"),
            RouteStop.depot(),
        ),
    )
    solution.contact_visits.pop("V21")
    solution.task_decisions["S5"] = TaskDecision.local()
    solution.metadata = {**solution.metadata, "stress_case": "local_fifo"}
    cases.append(("local_fifo", instance, solution))

    instance, solution = _copy_base()
    instance.cycle_s = 190.0
    instance.avg_delay_budget_s = 100.0
    instance.tasks["S1"] = replace(instance.tasks["S1"], deadline_s=100.0)
    instance.tasks["S2"] = replace(instance.tasks["S2"], deadline_s=105.0)
    instance.tasks["S3"] = replace(instance.tasks["S3"], deadline_s=145.0)
    solution.contact_visits = {
        "V11": ContactVisit("V11", "U1", "E1_P1"),
        "V12": ContactVisit("V12", "U1", "E1_P3"),
        "V21": ContactVisit("V21", "U2", "E1_P2"),
    }
    solution.routes["U1"] = Route(
        "U1",
        (
            RouteStop.depot(),
            RouteStop.task("S1"),
            RouteStop.contact("V11"),
            RouteStop.task("S2"),
            RouteStop.contact("V12"),
            RouteStop.task("S3"),
            RouteStop.depot(),
        ),
    )
    solution.task_decisions["S1"] = TaskDecision.offload("V11")
    solution.task_decisions["S2"] = TaskDecision.offload("V12")
    solution.metadata = {**solution.metadata, "stress_case": "same_mec_multi_contact"}
    cases.append(("same_mec_multi_contact", instance, solution))

    instance, solution = _copy_base()
    instance.cycle_s = 210.0
    instance.avg_delay_budget_s = 105.0
    instance.tasks["S4"] = replace(instance.tasks["S4"], deadline_s=100.0)
    instance.tasks["S5"] = replace(instance.tasks["S5"], deadline_s=150.0)
    instance.uavs["U2"] = replace(instance.uavs["U2"], energy_budget_j=50000.0)
    solution.contact_visits["V21"] = ContactVisit("V21", "U2", "E2_P1")
    solution.metadata = {**solution.metadata, "stress_case": "two_mec"}
    cases.append(("two_mec", instance, solution))

    instance, solution = _copy_base()
    instance.tasks["S1"] = replace(instance.tasks["S1"], deadline_s=20.0)
    cases.append(("infeasible_deadline", instance, solution))

    return cases
