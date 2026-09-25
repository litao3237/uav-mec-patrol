from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper_results" / "multiscale_ablation_summary.csv"
OUT = ROOT / "paper_figures" / "output"
PROFILES = ["no-route", "no-contact", "no-batch", "no-widening"]
LABELS = {
    "no-route": "w/o Route-compute",
    "no-contact": "w/o Contact",
    "no-batch": "w/o Batch",
    "no-widening": "w/o Widening",
}


def main() -> None:
    with DATA.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    ks = sorted({int(row["K"]) for row in rows})
    matrix = np.array([
        [
            float(next(
                row["mean_full_advantage_pct"]
                for row in rows
                if int(row["K"]) == k and row["profile"] == profile
            ))
            for k in ks
        ]
        for profile in PROFILES
    ])

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "font.size": 9,
        "axes.titlesize": 9.5,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
    })

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(7.2, 2.9),
        gridspec_kw={"width_ratios": [1.15, 1.0]},
    )

    ax = axes[0]
    for index, profile in enumerate(PROFILES):
        ax.plot(
            ks,
            matrix[index],
            marker="o",
            linewidth=1.4,
            label=LABELS[profile],
        )
    ax.set_xlabel("Number of tasks, K")
    ax.set_ylabel("Full ESI-ALNS advantage (%)")
    ax.set_xticks(ks)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.text(
        0.01,
        0.97,
        "(a)",
        transform=ax.transAxes,
        va="top",
        fontweight="bold",
    )

    ax = axes[1]
    image = ax.imshow(matrix, aspect="auto")
    ax.set_xticks(range(len(ks)), ks)
    ax.set_yticks(
        range(len(PROFILES)),
        [LABELS[profile] for profile in PROFILES],
    )
    ax.set_xlabel("Number of tasks, K")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            text = f"{value:.3f}" if value < 1 else f"{value:.2f}"
            ax.text(j, i, text, ha="center", va="center", fontsize=8)
    ax.text(
        0.01,
        0.97,
        "(b)",
        transform=ax.transAxes,
        va="top",
        fontweight="bold",
    )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.047, pad=0.03)
    colorbar.set_label("Advantage (%)")

    fig.tight_layout(pad=0.8)
    for ext in ("png", "pdf", "svg"):
        path = OUT / ext / f"fig08_multiscale_ablation.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=300 if ext == "png" else None, bbox_inches="tight")


if __name__ == "__main__":
    main()
