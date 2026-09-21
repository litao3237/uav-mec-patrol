from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from typing import Any


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result file: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No GA result JSON files found in {input_dir}")
    return rows


def _method_summary(
    rows: list[dict[str, Any]],
    method: str,
) -> dict[str, Any]:
    statuses = [row[method]["stage1_status"] for row in rows]
    energies = [
        float(row[method]["energy_j"])
        for row in rows
        if row[method]["energy_j"] is not None
    ]
    return {
        "runs": len(rows),
        "strict_optimal": sum(status == "optimal" for status in statuses),
        "strict_rate": (
            sum(status == "optimal" for status in statuses) / len(rows)
            if rows
            else 0.0
        ),
        "mean_energy_j": mean(energies) if energies else None,
        "median_energy_j": median(energies) if energies else None,
    }


def _paired(
    rows: list[dict[str, Any]],
    baseline: str,
) -> dict[str, Any]:
    gains: list[float] = []
    for row in rows:
        base = row[baseline]["energy_j"]
        hybrid = row["hybrid"]["energy_j"]
        if base is None or hybrid is None:
            continue
        gains.append(
            100.0
            * (float(base) - float(hybrid))
            / max(1.0, abs(float(base)))
        )
    return {
        "comparable": len(gains),
        "hybrid_better": sum(gain > 1e-9 for gain in gains),
        "equal": sum(abs(gain) <= 1e-9 for gain in gains),
        "baseline_better": sum(gain < -1e-9 for gain in gains),
        "mean_hybrid_advantage_pct": mean(gains) if gains else None,
        "median_hybrid_advantage_pct": (
            median(gains) if gains else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate per-seed GA baseline comparison JSON files."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _load_rows(Path(args.input_dir))
    aggregate = {
        "methods": {
            method: _method_summary(rows, method)
            for method in ("ga", "generic_alns", "hybrid")
        },
        "paired": {
            "hybrid_vs_ga": _paired(rows, "ga"),
            "hybrid_vs_generic_alns": _paired(
                rows,
                "generic_alns",
            ),
        },
        "ga_search": {
            "mean_distinct_evaluations": mean(
                float(row["ga"]["evaluations"])
                for row in rows
            ),
            "mean_search_runtime_s": mean(
                float(row["ga"]["search_runtime_s"])
                for row in rows
            ),
            "proxy_feasible_runs": sum(
                bool(row["ga"]["proxy_feasible"])
                for row in rows
            ),
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "aggregate": aggregate,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(json.dumps(aggregate, indent=2, ensure_ascii=False))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
