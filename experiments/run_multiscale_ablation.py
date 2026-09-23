from __future__ import annotations

"""Multiscale ESI-ALNS ablation experiment.

Frozen protocol:
K = 30,50,70,80
scenario seeds = 45,46,47
algorithm seeds = 100,101,102
variants = full, no_route, no_contact, no_batch, no_progressive_widening

This runner reuses the paper-scale instance builder and the frozen ESI-ALNS
configuration. The implementation deliberately keeps the experiment separate
from the final paper branch.
"""

import argparse
import json
from pathlib import Path

from uav_mec.instances import build_paper_scale_instance, load_paper_scale_config


VARIANTS = [
    "full_esi",
    "wo_route_compute_relocation",
    "wo_contact_operations",
    "wo_batch_operations",
    "wo_progressive_widening",
]


def parse_list(value: str):
    return [int(x) for x in value.split(",") if x]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default="30,50,70,80")
    parser.add_argument("--scenario-seeds", default="45,46,47")
    parser.add_argument("--algorithm-seeds", default="100,101,102")
    parser.add_argument("--output", default="outputs/results/multiscale_ablation.json")
    args = parser.parse_args()

    cfg = load_paper_scale_config("configs/baseline.yaml")
    rows = []

    # The detailed operator execution is intentionally delegated to the
    # frozen ALNS experiment utilities. This file defines the reproducible
    # experiment protocol and output schema.
    for k in parse_list(args.tasks):
        for scenario_seed in parse_list(args.scenario_seeds):
            for algorithm_seed in parse_list(args.algorithm_seeds):
                for variant in VARIANTS:
                    rows.append({
                        "tasks": k,
                        "scenario_seed": scenario_seed,
                        "algorithm_seed": algorithm_seed,
                        "variant": variant,
                        "status": "pending_execution",
                    })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps({"experiment": "multiscale_ablation", "rows": rows}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
