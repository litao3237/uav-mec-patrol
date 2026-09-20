from __future__ import annotations

import argparse
import json
from pathlib import Path

from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
    summarize_paper_scale_instance,
)


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate deterministic paper-scale instances and print sanity statistics."
    )
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--tasks", default="30,50,80,100")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--uavs", type=int, default=None)
    parser.add_argument("--mecs", type=int, default=None)
    args = parser.parse_args()

    cfg = load_paper_scale_config(args.config)
    seed = cfg.scenario_seed if args.seed is None else args.seed
    task_counts = _parse_int_list(args.tasks)

    rows = []
    print(
        "K    M    E    contacts    data-MB(mean)    workload-Gcy(mean)    "
        "deadline-s(mean)    cycle-s"
    )
    print("-" * 100)
    for k in task_counts:
        instance = build_paper_scale_instance(
            cfg,
            num_tasks=k,
            num_uavs=args.uavs,
            num_mecs=args.mecs,
            scenario_seed=seed,
        )
        summary = summarize_paper_scale_instance(instance)
        rows.append({"seed": seed, **summary})
        print(
            f"{summary['num_tasks']:<4} "
            f"{summary['num_uavs']:<4} "
            f"{summary['num_mecs']:<4} "
            f"{summary['num_contact_points']:<11} "
            f"{summary['data_mb_mean']:<16.3f} "
            f"{summary['workload_gcycles_mean']:<21.3f} "
            f"{summary['deadline_s_mean']:<19.2f} "
            f"{summary['cycle_s']:.1f}"
        )

    out = Path("outputs/instances/paper_scale_sanity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
