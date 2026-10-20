from __future__ import annotations

from dataclasses import replace
from random import Random

from uav_mec.domain import DiscreteSolution, Instance

from .small import build_small_instance


def build_random_validation_instance(seed: int) -> tuple[Instance, DiscreteSolution]:
    """Return a seeded perturbation of the hand-checked K=5 validation topology.

    This is intentionally *not* the final paper-scale instance generator. Its
    purpose is solver cross-validation: preserve the known discrete route/contact
    structure while perturbing geometry, task sizes, deadlines and MEC capacity.
    """

    rng = Random(seed)
    instance, solution = build_small_instance()

    tasks = {}
    for task_id, task in instance.tasks.items():
        data_scale = rng.uniform(0.90, 1.10)
        cycle_scale = rng.uniform(0.94, 1.06)
        workload_scale = data_scale * cycle_scale
        deadline_scale = max(0.98, workload_scale) * rng.uniform(1.00, 1.05)
        tasks[task_id] = replace(
            task,
            x=task.x + rng.uniform(-18.0, 18.0),
            y=task.y + rng.uniform(-18.0, 18.0),
            data_mb=task.data_mb * data_scale,
            cycles_per_bit=task.cycles_per_bit * cycle_scale,
            deadline_s=task.deadline_s * deadline_scale,
        )

    mecs = dict(instance.mecs)
    e1 = mecs["E1"]
    mecs["E1"] = replace(
        e1,
        bandwidth_mhz=e1.bandwidth_mhz * rng.uniform(0.92, 1.10),
        cpu_ghz=e1.cpu_ghz * rng.uniform(0.90, 1.10),
    )

    instance.tasks = tasks
    instance.mecs = mecs
    instance.avg_delay_budget_s = 72.0 * rng.uniform(0.98, 1.08)
    solution.metadata = {**solution.metadata, "validation_seed": seed}
    return instance, solution
