"""Seven primary task-QoS figures from new verified measurements only."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


FIGURES = {
    "success_rate": "Task success rate",
    "mean_delay_all": "Mean all-task delay (s; unserved right-censored at cycle)",
    "p95_delay_all": "P95 all-task delay (s; unserved right-censored at cycle)",
    "total_energy": "Total UAV energy (J)",
    "energy_per_successful_task": "Energy per successful task (J)",
    "mec_cpu_utilization": "Mean MEC CPU allocation fraction",
    "runtime": "End-to-end runtime (s)",
}
METHODS = ("GR-MR", "FTR-NM", "RGA-MR", "SA-MR", "DPSO-MR", "B-ALNS", "ESI-ALNS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--study", default="main")
    parser.add_argument("--level", default="baseline")
    args = parser.parse_args()
    rows = list(csv.DictReader(args.summary.open(encoding="utf-8", newline="")))
    rows = [row for row in rows if row["study"] == args.study and
            row["level"] == args.level]
    if not rows:
        raise ValueError("No verified new observations for requested study and level")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for metric, label in FIGURES.items():
        fig, ax = plt.subplots(figsize=(7.5, 4.7))
        plotted = 0
        for method in METHODS:
            observations = [r for r in rows if r["method"] == method and
                            r["metric"] == metric and r["value"]]
            observations.sort(key=lambda r: int(r["tasks"]))
            xs = [int(r["tasks"]) for r in observations if math.isfinite(float(r["value"]))]
            ys = [float(r["value"]) for r in observations if math.isfinite(float(r["value"]))]
            if xs:
                ax.plot(xs, ys, marker="o", linewidth=1.7, label=method)
                plotted += 1
        if not plotted:
            plt.close(fig)
            continue
        ax.set_xlabel("Number of planned tasks")
        ax.set_ylabel(label)
        if metric in ("success_rate", "mec_cpu_utilization"):
            ax.set_ylim(0, 1.01)
        ax.grid(alpha=0.25)
        ax.legend(ncol=2, fontsize=8)
        fig.tight_layout()
        fig.savefig(args.output_dir / f"{metric}.png", dpi=200)
        fig.savefig(args.output_dir / f"{metric}.pdf")
        plt.close(fig)
    print("Created available v26 task-QoS plots without imputing missing values")


if __name__ == "__main__":
    main()
